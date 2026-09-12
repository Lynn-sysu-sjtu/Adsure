from __future__ import annotations

import html
import hashlib
import json
import os
import re
import shutil
import uuid
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from .pipeline import analyze_video
from .asr import readiness
from src.audit_contract import build_video_response


PROJECT_ROOT = Path(__file__).resolve().parents[2]
JOBS_ROOT = Path(os.getenv("VIDEO_MVP_JOBS_DIR", PROJECT_ROOT / "data" / "video_mvp" / "jobs"))
ALLOWED_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v"}
ALLOWED_TRANSCRIPT_SUFFIXES = {".srt", ".vtt", ".json", ".txt"}
JOB_ID = re.compile(r"^[0-9a-f]{32}$")
JOB_LOCK = threading.Lock()
CREATE_LOCK = threading.Lock()
INDUSTRIES = {"一般行业", "保健食品", "普通食品", "化妆品", "教育培训", "金融投资", "医疗", "药品", "医疗器械"}
FEISHU_INDUSTRY_MAP = {"美妆":"化妆品", "游戏":"一般行业", "通用":"一般行业"}
FEISHU_MODES = {"标准", "极速", "深度"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_dir(job_id: str) -> Path:
    if not JOB_ID.fullmatch(job_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    path = (JOBS_ROOT / job_id).resolve()
    if path.parent != JOBS_ROOT.resolve():
        raise HTTPException(status_code=404, detail="任务不存在")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=404, detail="任务数据不存在") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=500, detail="任务数据格式错误")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _find_job_by_request_id(request_id: str) -> str | None:
    for path in sorted(JOBS_ROOT.glob("*/job.json"), reverse=True):
        if not JOB_ID.fullmatch(path.parent.name):
            continue
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("request_id") == request_id:
                return path.parent.name
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _job_links(job_id: str) -> dict[str, str]:
    return {"poll_url":f"/api/jobs/{job_id}",
            "audit_response_url":f"/api/jobs/{job_id}/audit-response",
            "report_url":f"/api/jobs/{job_id}/report"}


def _poll_state(state: dict) -> dict:
    public_fields = (
        "job_id", "request_id", "record_id", "status", "message", "created_at",
        "started_at", "completed_at", "summary", "coverage_status", "review_status",
    )
    result = {key: state[key] for key in public_fields if key in state}
    terminal = state.get("status") in {"completed", "needs_attention", "failed"}
    result.update(_job_links(state["job_id"]))
    result.update(terminal=terminal, retry_after_ms=0 if terminal else 1500,
                  audit_response_ready=bool(state.get("audit_response_ready")))
    if state.get("status") == "failed":
        result["error"] = "视频审核失败，请使用 job_id 排查服务日志"
    return result


def _normalize_platforms(platform: str, platforms_json: str) -> tuple[str, list[str]]:
    """Accept the legacy scalar field and the Feishu array encoded in multipart."""
    if platforms_json.strip():
        try:
            values = json.loads(platforms_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="platforms_json 必须是 JSON 字符串数组") from exc
        if (not isinstance(values, list) or not values or
                any(not isinstance(item, str) or not item.strip() for item in values)):
            raise HTTPException(status_code=400, detail="platforms_json 必须是非空 JSON 字符串数组")
        platforms = list(dict.fromkeys(item.strip() for item in values))
    else:
        platforms = [platform.strip()] if platform.strip() else []
    return "、".join(platforms), platforms


async def _save_upload(upload: UploadFile, destination: Path, max_bytes: int) -> int:
    written = 0
    with destination.open("wb") as handle:
        while chunk := await upload.read(1024 * 1024):
            written += len(chunk)
            if written > max_bytes:
                handle.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="上传文件超过大小限制")
            handle.write(chunk)
    return written


def _process_job(job_id: str) -> None:
    # Bounded local concurrency avoids multiple models exhausting host memory.
    with JOB_LOCK:
        _run_job(job_id)


def _run_job(job_id: str) -> None:
    directory = _job_dir(job_id)
    state_path = directory / "job.json"
    state = _read_json(state_path)
    state.update({"status": "processing", "started_at": _now(), "message": "正在抽帧并识别画面文字"})
    _write_json(state_path, state)
    def progress(message: str) -> None:
        state["message"] = message
        _write_json(state_path, state)
    try:
        report = analyze_video(
            directory / state["video_file"],
            directory,
            job_id=job_id,
            industry=state["industry"],
            product_category=state["product_category"],
            platform=state["platform"],
            transcript_path=(directory / state["transcript_file"] if state.get("transcript_file") else None),
            transcript_text=state.get("transcript_text", ""),
            sample_interval=float(state["sample_interval"]),
            max_frames=int(state["max_frames"]),
            asr_mode=state.get("asr_mode", "auto"),
            proof_paths=[directory / p for p in state.get("proof_files",[])],
            product_name=state.get("product_name",""), product_id=state.get("product_id",""),
            activity_text=state.get("activity_text",""), landing_page_text=state.get("landing_page_text",""),
            cloud_consent_endpoint=state.get("cloud_consent_endpoint",""),
            progress=progress,
        )
        completed_at = _now()
        audit_time = int(datetime.fromisoformat(completed_at).timestamp() * 1000)
        audit_response = {"code":0, "msg":"ok", "data":build_video_response(report, state, now_ms=audit_time)}
        _write_json(directory / "audit_response.json", audit_response)
        manifest = _read_json(directory / "manifest.json")
        manifest.setdefault("artifacts", {})["feishu_audit_response_sha256"] = _sha256(directory / "audit_response.json")
        manifest["feishu_contract"] = {"version":"0.2", "request_id":audit_response["data"]["request_id"],
                                       "review_status":"pending_human_review"}
        _write_json(directory / "manifest.json", manifest)
        state.update({
            "status": report.get("analysis_status", "completed"),
            "completed_at": completed_at,
            "message": "分析完成，等待人工复核" if report.get("analysis_status") == "completed" else "识别覆盖不完整，请查看报告中的失败原因",
            "summary": report["summary"],
            "coverage_status": report["coverage_status"],
            "review_status": report["review_status"],
            "audit_response_ready": True,
        })
    except Exception as exc:
        state.update({
            "status": "failed",
            "completed_at": _now(),
            "message": "分析失败",
            "error": str(exc),
            "audit_response_ready": False,
        })
    _write_json(state_path, state)


def _base_css() -> str:
    return """
    :root{color-scheme:light;--ink:#25211f;--muted:#726762;--paper:#fbf7f0;--card:#fffdf9;
    --red:#bf3b2d;--orange:#e77835;--line:#e9ddd1;--green:#2f7557;--amber:#b66a14}
    *{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:-apple-system,
    BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;line-height:1.55}
    .shell{max-width:1180px;margin:0 auto;padding:34px 24px 70px}.brand{display:flex;gap:14px;align-items:center;margin-bottom:26px}
    .mark{width:42px;height:42px;background:var(--red);border-radius:13px;display:grid;place-items:center;color:white;font-weight:800}
    h1,h2,h3,p{margin-top:0}h1{font-size:30px;margin-bottom:3px}.muted{color:var(--muted)}
    .card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:22px;box-shadow:0 10px 35px rgba(70,42,26,.05)}
    .grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.grid3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
    label{font-size:13px;font-weight:700;display:block;margin:12px 0 6px}input,select,textarea{width:100%;border:1px solid #d9c9bd;
    background:white;border-radius:11px;padding:11px 12px;font:inherit}textarea{min-height:108px;resize:vertical}
    button,.button{display:inline-block;border:0;background:var(--red);color:white;padding:12px 20px;border-radius:11px;font-weight:750;cursor:pointer;text-decoration:none}
    button:disabled{opacity:.55;cursor:wait}.notice{background:#fff5e9;border-left:4px solid var(--orange);padding:12px 14px;border-radius:9px;margin:16px 0}
    .pill{display:inline-block;padding:3px 9px;border-radius:999px;background:#f2e6db;font-size:12px;font-weight:700}.pill.high{color:#9a241d;background:#fae1dd}
    .pill.medium{color:#8d530b;background:#ffedce}.pill.ok{color:#236246;background:#dff1e7}.metric{padding:14px;border-radius:14px;background:#f7efe7}
    .metric b{display:block;font-size:25px}.risk{border-left:4px solid var(--orange);margin:12px 0;padding:14px 15px;background:#fffaf4;border-radius:8px;cursor:pointer}
    .risk.high{border-color:var(--red)}.risk:hover{background:#fff3e7}.small{font-size:13px}.list{display:grid;gap:10px}.split{display:grid;grid-template-columns:minmax(0,1.08fr) minmax(360px,.92fr);gap:20px}
    .video-wrap{position:relative;background:#111;border-radius:16px;overflow:hidden;line-height:0;position:sticky;top:18px}video{width:100%;max-height:68vh}
    #bbox{display:none;position:absolute;border:3px solid #ff4d3d;background:rgba(255,77,61,.10);pointer-events:none;box-shadow:0 0 0 1px white inset}
    a{color:#a83329}.section{margin-top:20px}.source{padding:12px;border:1px solid var(--line);border-radius:11px;background:#fff}.status{padding:12px 14px;border-radius:10px;background:#f5ece3}
    code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}.footer{margin-top:28px;padding-top:18px;border-top:1px solid var(--line)}
    @media(max-width:850px){.split,.grid,.grid3{grid-template-columns:1fr}.video-wrap{position:relative;top:0}}
    """


def _home_page() -> str:
    from .cloud_config import public_status
    cloud = public_status()
    cloud_field = (f'<label><input type="checkbox" name="cloud_consent_endpoint" value="{html.escape(cloud["endpoint"])}">'
                   f'允许本次视频最多 12 张代表帧及对应机器口播发送到 {html.escape(cloud["endpoint"])}，'
                   f'使用 {html.escape(cloud["model"])} 识别画面；完整视频、材料、活动及落地页文本不发送。</label>'
                   if cloud.get("provider")=="cloud" and cloud.get("configured") else
                   '<p class="muted">云端视觉未配置；不会自动外发。语义识别需本机视觉模型就绪。</p>')
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>审心 Adsure · 视频广告合规审核 MVP</title><style>{_base_css()}</style></head><body><main class="shell">
    <div class="brand"><div class="mark">审</div><div><h1>视频广告合规审核 MVP</h1><div class="muted">证据先行 · 风险候选 · 人工复核</div></div></div>
    <div class="grid"><section class="card"><h2>上传待审视频</h2>
    <form id="job-form" enctype="multipart/form-data">
      <label>视频文件（MP4 / MOV / M4V）</label><input required type="file" name="video" accept="video/mp4,video/quicktime,.m4v">
      <div class="grid"><div><label>行业</label><select name="industry">{''.join('<option>'+name+'</option>' for name in ['一般行业','保健食品','普通食品','化妆品','教育培训','金融投资','医疗','药品','医疗器械'])}</select></div>
      <div><label>投放平台</label><input name="platform" placeholder="例如：抖音信息流"></div></div>
      <label>产品/服务</label><input name="product_category" placeholder="例如：膳食补充剂">
      <label>产品准确名称（用于证明材料对应）</label><input name="product_name" placeholder="与备案、检测报告、活动规则一致">
      <label>产品注册/备案编号（可选）</label><input name="product_id">
      <div class="grid"><div><label>字幕/ASR 文件（可选）</label><input type="file" name="transcript_file" accept=".srt,.vtt,.json,.txt"></div>
      <div><label>基线抽帧间隔（秒，变化处自动加密）</label><input type="number" name="sample_interval" min="0.25" max="30" step="0.25" value="0.5"></div></div>
      <label>口播转写文本（可选；无时间戳时只定位到完整视频）</label><textarea name="transcript_text" placeholder="可粘贴人工转写；优先上传带时间戳的 SRT/VTT/ASR JSON"></textarea>
      <label>证明材料（最多 5 份，PDF/DOCX/TXT/MD/JSON，总计不超过 50 MB）</label><input type="file" name="proof_files" multiple accept=".pdf,.docx,.txt,.md,.json">
      <label>活动规则文本（可选）</label><textarea name="activity_text" placeholder="产品名称：…&#10;赠品名称：…&#10;赠品规格：…&#10;赠送数量：…&#10;领取资格：…&#10;活动开始：2026-09-01&#10;活动结束：2026-09-30&#10;领取方式：…"></textarea>
      <label>落地页文本（可选，不自动访问网址）</label><textarea name="landing_page_text"></textarea>
      {cloud_field}
      <div class="notice small">自动识别视频音轨，无需字幕。字幕和人工文本可作补充；画面变化处自动加密采样。识别失败时会显示覆盖不足及原因。</div>
      <button id="submit" type="submit">开始审核</button><span id="status" class="muted small" style="margin-left:12px"></span>
    </form></section>
    <aside class="card"><h2>本版能力边界</h2><div class="list small">
      <div class="source"><b>识别与审核</b><br>自动口播转写、自适应抽帧 OCR、跨句/跨行规则匹配、绝对化表述、功效与效果保证、背书与量化引证线索、处罚案例参考。</div>
      <div class="source"><b>增强核验</b><br>中文双引擎、画面语义、证明材料与活动条件、平台条款候选；模型和规则是否就绪以实际报告为准。</div>
      <div class="source"><b>尚未覆盖</b><br>说话人身份、证明材料官方验真、真实功效与活动兑现、音乐授权、视频版权、IP 形象与字体版权。</div>
      <div class="source"><b>合规边界</b><br>机器输出是风险候选，不是违法认定；处罚案例只用于监管口径参考，不是待审视频事实核验。</div>
    </div></aside></div>
    <div class="footer muted small">审心 Adsure MVP · 原始视频哈希、原始 OCR、证据单元、规则结果和报告均在任务目录留痕。</div>
    </main><script>
    const form=document.getElementById('job-form'),button=document.getElementById('submit'),status=document.getElementById('status');
    form.addEventListener('submit',async(e)=>{{e.preventDefault();button.disabled=true;status.textContent='正在上传…';
      try{{const response=await fetch('/api/jobs',{{method:'POST',body:new FormData(form)}});const data=await response.json();
      if(!response.ok)throw new Error(data.detail||'创建失败');location.href='/jobs/'+data.job_id;}}
      catch(error){{status.textContent=error.message;button.disabled=false;}}}});
    </script></body></html>"""


def _waiting_page(job_id: str, state: dict[str, Any]) -> str:
    safe_state = html.escape(str(state.get("message", "等待处理")))
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>审核任务</title><style>{_base_css()}</style></head><body><main class="shell"><div class="brand"><div class="mark">审</div>
    <div><h1>视频审核任务</h1><div class="muted"><code>{job_id}</code></div></div></div><section class="card"><h2 id="headline">{safe_state}</h2>
    <p class="muted" id="detail">任务在本机处理。长视频和较密抽帧需要一些时间。</p><div class="status" id="status">状态：{html.escape(str(state.get('status', 'queued')))}</div>
    <p style="margin-top:18px"><a class="button" href="/">返回上传</a></p></section></main><script>
    async function poll(){{const r=await fetch('/api/jobs/{job_id}');const d=await r.json();
      document.getElementById('headline').textContent=d.message||d.status;document.getElementById('status').textContent='状态：'+d.status;
      if(d.status==='completed'||d.status==='needs_attention')location.reload();else if(d.status==='failed')document.getElementById('detail').textContent=d.error||'处理失败';else setTimeout(poll,1500);}}
    setTimeout(poll,1000);</script></body></html>"""


def _report_page(job_id: str, report: dict[str, Any]) -> str:
    embedded = json.dumps(report, ensure_ascii=False).replace("<", "\\u003c")
    audio = report.get("coverage", {}).get("audio", {})
    coverage_note = html.escape(str(audio.get("status", "旧版未识别音轨")))
    def transcript_quality(segment: dict) -> str:
        score = segment.get("confidence")
        if segment.get("provider") not in {"faster-whisper","sherpa-onnx/SenseVoice"}:
            return "用户提供文本，未与音轨验证"
        if score is None:
            return "识别分数不可用，请回听"
        return f"识别分数 {float(score):.2f} · " + ("低置信度，请回听" if float(score) < .6 else "机器转写，仍须回听核对")
    transcript_html = ''.join(
        '<div class="source small"><a href="#video" class="seek" data-time="' + str(float(s['t_start'])) + '">' +
        f"{float(s['t_start']):.2f}s–{float(s['t_end']):.2f}s</a> " + html.escape(s['text']) +
        '<div class="muted">' + html.escape(s.get('provider','')) + ' · ' + html.escape(transcript_quality(s)) + '</div></div>'
        for s in report.get('transcript', []))
    tasks_html = ''.join('<div class="source small">'+html.escape(s)+'</div>' for s in report.get('manual_review_tasks',[]))
    from .report_v3 import advanced_sections
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>视频广告风险自查报告</title><style>{_base_css()}</style></head><body><main class="shell">
    <div class="brand"><div class="mark">审</div><div><h1>视频广告风险自查报告</h1><div class="muted">任务 <code>{job_id}</code> · 状态：待人工复核</div></div></div>
    <div class="grid3" id="metrics"></div><div class="notice"><b>重要边界：</b>{html.escape(str(report.get('disclaimer','')))}</div>
    <div class="status section">口播识别：{coverage_note} · 整体覆盖：{html.escape(report.get('coverage_status','unknown'))}<br><span class="small">覆盖完成只说明采样流程完成，不代表转写正确、风险查全或审核通过。</span></div>
    <div class="split"><div><div class="video-wrap"><video id="video" controls preload="metadata" src="/api/jobs/{job_id}/media"></video><div id="bbox"></div></div>
    <div class="section card"><h2>覆盖与限制</h2><div id="warnings" class="list small"></div></div></div>
    <div><section class="card"><h2>风险候选</h2><p class="muted small">点击候选可跳转视频时间点，并显示 OCR 画面框。</p><div id="risks"></div></section>
    <section class="card section"><h2>必要展示项</h2><div id="checks" class="list small"></div></section></div></div>
    <section class="card section"><h2>处罚案例参考</h2><p class="muted small">只用于监管口径参考，不是待审视频的事实证明。</p><div id="cases" class="list"></div></section>
    <section class="card section"><h2>口播原文与时间戳</h2><div class="list">{transcript_html or '没有可用口播文本，请查看覆盖原因。'}</div></section>
    {advanced_sections(report)}
    <section class="card section"><h2>还需核验的材料和内容</h2><div class="list">{tasks_html}</div></section>
    <section class="card section"><h2>能力状态</h2><div class="grid"><div><b>本版已实现</b><div id="implemented" class="small"></div></div><div><b>尚未接通</b><div id="missing" class="small"></div></div></div></section>
    <div class="footer"><a href="/">审核另一个视频</a> · <a href="/api/jobs/{job_id}/report">下载 JSON 报告</a> · <a href="/api/jobs/{job_id}/evidence">查看证据 JSON</a> · <a href="/api/jobs/{job_id}/manifest">查看证据哈希清单</a></div>
    </main><script>const report={embedded};const video=document.getElementById('video'),bbox=document.getElementById('bbox');
    document.querySelectorAll('.seek').forEach(a=>a.addEventListener('click',()=>{{video.currentTime=Number(a.dataset.time);video.pause();bbox.style.display='none';}}));
    const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
    const summary=report.summary||{{}};document.getElementById('metrics').innerHTML=[['风险候选',summary.risk_candidates||0],['画面证据',summary.ocr_evidence_units||0],['案例参考',summary.reference_cases||0]].map(x=>`<div class="metric"><span class="muted small">${{x[0]}}</span><b>${{x[1]}}</b></div>`).join('');
    function jump(r){{video.currentTime=Number(r.t_start||0);video.pause();const b=r.bbox;if(!b){{bbox.style.display='none';return}}const w=video.clientWidth,h=video.clientHeight,scale=Math.min(w/video.videoWidth,h/video.videoHeight),vw=video.videoWidth*scale,vh=video.videoHeight*scale;bbox.style.display='block';bbox.style.left=((w-vw)/2+b[0]*vw)+'px';bbox.style.top=((h-vh)/2+b[1]*vh)+'px';bbox.style.width=(b[2]*vw)+'px';bbox.style.height=(b[3]*vh)+'px';}}
    video.addEventListener('play',()=>bbox.style.display='none');
    const risks=document.getElementById('risks');if(!(report.risks||[]).length)risks.innerHTML='<div class="status">未生成词面风险候选。这不是无风险结论，请结合覆盖限制和人工复核。</div>';
    (report.risks||[]).forEach(r=>{{const d=document.createElement('div');d.className='risk '+esc(r.severity);d.innerHTML=`<span class="pill ${{esc(r.severity)}}">${{esc(r.severity)}}</span> <b>${{esc(r.title)}}</b><div class="small">${{r.source==='ocr'?'画面':r.source==='asr'?'口播/转写':'用户文本'}} · ${{Number(r.t_start).toFixed(2)}}s–${{Number(r.t_end).toFixed(2)}}s · 命中：${{esc(r.matched_text)}}</div><div class="small">原文：${{esc(r.context_text||r.matched_text)}}</div><div class="muted small">${{esc(r.explanation)}}</div><div class="small">建议：${{esc(r.recommendation)}}</div><div class="small">规则：${{esc((r.rule_ids||[]).join('、'))}}</div>`;d.onclick=()=>jump(r);risks.appendChild(d)}});
    const labels={{observed:'已识别，待复核',not_observed:'未识别',observed_in_all_samples:'全部采样点识别，待复核',not_continuously_observed:'仅部分采样点识别',incomplete_coverage:'覆盖不足',human_review_required:'必须人工检查'}};
    document.getElementById('checks').innerHTML=(report.requirement_checks||[]).map(c=>`<div class="source"><b>${{esc(c.title)}}</b> <span class="pill">${{esc(labels[c.status]||c.status)}}</span><br>${{esc(c.explanation)}}</div>`).join('')||'<div class="muted">当前行业无专项展示项检查。</div>';
    document.getElementById('warnings').innerHTML=(report.warnings||[]).map(w=>`<div class="source">${{esc(w)}}</div>`).join('')||'<div class="source">无系统警告；仍需人工复核。</div>';
    document.getElementById('cases').innerHTML=(report.reference_cases||[]).map(c=>`<div class="source"><b>${{esc(c.title||c.case_id)}}</b><div class="small">${{esc(c.penalty_authority||'')}} · ${{esc(c.publish_date||'')}}</div><div class="muted small">${{esc(c.match_explanation||c.facts_summary||'')}}</div>${{c.source_url?`<a target="_blank" rel="noopener" href="${{esc(c.source_url)}}">查看原始来源</a>`:''}}</div>`).join('')||'<div class="muted">本次没有检索到足够相关的处罚案例；找不到比误报更安全。</div>';
    document.getElementById('implemented').innerHTML=(report.capability_boundaries.implemented||[]).map(x=>'· '+esc(x)).join('<br>');
    document.getElementById('missing').innerHTML=(report.capability_boundaries.not_connected||[]).map(x=>'· '+esc(x)).join('<br>');
    </script></body></html>"""


def create_app() -> FastAPI:
    JOBS_ROOT.mkdir(parents=True, exist_ok=True)
    application = FastAPI(title="审心 Adsure 视频广告合规审核 MVP", version="0.3.0")

    @application.get("/", response_class=HTMLResponse)
    def home() -> str:
        return _home_page()

    @application.get("/health")
    def health() -> dict[str, Any]:
        from .cloud_config import public_status
        return {
            "status": "ok",
            "version": "0.3.0",
            "visual_config": public_status(),
            "asr": readiness(),
            "service": "video-compliance-mvp",
            "feishu_contract": {
                "version": "0.2",
                "upload": "/api/jobs",
                "poll": "/api/jobs/{job_id}",
                "result": "/api/jobs/{job_id}/audit-response",
            },
            "native_vision_source": Path(__file__).with_name("native_vision.m").is_file(),
            "jobs_dir": str(JOBS_ROOT),
        }

    @application.post("/api/jobs", status_code=202)
    async def create_job(
        background_tasks: BackgroundTasks,
        video: UploadFile = File(...),
        industry: str = Form("一般行业"),
        product_category: str = Form(""),
        platform: str = Form(""),
        platforms_json: str = Form(""),
        transcript_file: UploadFile | None = File(None),
        transcript_text: str = Form(""),
        sample_interval: float = Form(0.5),
        proof_files: list[UploadFile] = File(default=[]),
        product_name: str = Form(""), product_id: str = Form(""),
        activity_text: str = Form(""), landing_page_text: str = Form(""),
        cloud_consent_endpoint: str = Form(""),
        record_id: str = Form(""), mode: str = Form("标准"), urgency: str = Form("普通"),
        supplement: str = Form(""),
    ) -> dict[str, Any]:
        video_name = Path(video.filename or "video.mp4").name
        video_suffix = Path(video_name).suffix.lower()
        if video_suffix not in ALLOWED_VIDEO_SUFFIXES:
            raise HTTPException(status_code=400, detail="仅支持 MP4、MOV 或 M4V 视频")
        if not 0.25 <= sample_interval <= 30:
            raise HTTPException(status_code=400, detail="抽帧间隔必须在 0.25—30 秒之间")
        platform, platforms = _normalize_platforms(platform, platforms_json)
        requested_industry = industry
        industry = FEISHU_INDUSTRY_MAP.get(industry, industry)
        if industry not in INDUSTRIES:
            raise HTTPException(status_code=400, detail="暂不支持该行业模板")
        record_id = record_id.strip()
        if len(record_id) > 128 or any(ord(c) < 32 for c in record_id):
            raise HTTPException(status_code=400,detail="record_id 无效或超过 128 字符")
        if mode not in FEISHU_MODES:
            raise HTTPException(status_code=400,detail="mode 必须是：标准、极速或深度")
        if urgency not in {"普通","加急"}:
            raise HTTPException(status_code=400,detail="urgency 必须是：普通或加急")
        if len(supplement)>30000:
            raise HTTPException(status_code=400,detail="supplement 长度超过上限")
        if cloud_consent_endpoint:
            from .cloud_config import public_status
            current = public_status()
            if current.get("provider") != "cloud" or cloud_consent_endpoint != current.get("endpoint"):
                raise HTTPException(status_code=400,detail="云端目标地址已改变，请刷新页面重新确认")
        proof_files=[f for f in proof_files if f.filename]
        if len(proof_files)>5 or len(activity_text)>30000 or len(landing_page_text)>50000:
            raise HTTPException(status_code=400,detail="材料份数或文本长度超过上限")
        max_upload = int(os.getenv("VIDEO_MVP_MAX_UPLOAD_MB", "512")) * 1024 * 1024
        job_id = uuid.uuid4().hex
        request_id = record_id or job_id
        with CREATE_LOCK:
            existing = _find_job_by_request_id(request_id) if record_id else None
            if existing:
                previous = _read_json(_job_dir(existing) / "job.json")
                return {"job_id":existing,"request_id":request_id,"status":previous.get("status","queued"),
                        "url":f"/jobs/{existing}","deduplicated":True,**_job_links(existing)}
            directory = JOBS_ROOT / job_id
            directory.mkdir(parents=True)
            _write_json(directory / "job.json", {"job_id":job_id,"request_id":request_id,
                "record_id":record_id or None,"status":"uploading","message":"正在接收视频","created_at":_now(),
                "audit_response_ready":False})
        stored_video = "source" + video_suffix
        try:
            byte_count = await _save_upload(video, directory / stored_video, max_upload)
            if byte_count == 0:
                raise HTTPException(status_code=400, detail="视频文件为空")
            stored_transcript: str | None = None
            if transcript_file and transcript_file.filename:
                suffix = Path(transcript_file.filename).suffix.lower()
                if suffix not in ALLOWED_TRANSCRIPT_SUFFIXES:
                    raise HTTPException(status_code=400, detail="字幕仅支持 SRT、VTT、JSON 或 TXT")
                stored_transcript = "transcript" + suffix
                await _save_upload(transcript_file, directory / stored_transcript, 20 * 1024 * 1024)
            max_frames = int(os.getenv("VIDEO_MVP_MAX_FRAMES", "1800"))
            saved_proofs=[]
            proof_bytes=0
            for index, proof in enumerate(proof_files):
                suffix=Path(proof.filename).suffix.lower()
                if suffix not in {".pdf",".docx",".txt",".md",".json"}:
                    raise HTTPException(status_code=400,detail="证明材料格式不支持")
                stored=f"proof_{index:02d}_"+Path(proof.filename).name
                proof_bytes+=await _save_upload(proof,directory/stored,20*1024**2)
                if proof_bytes>50*1024**2:
                    raise HTTPException(status_code=413,detail="证明材料总计超过 50 MB")
                saved_proofs.append(stored)
            state = {
                "proof_files":saved_proofs,"product_name":product_name.strip(),"product_id":product_id.strip(),
                "activity_text":activity_text,"landing_page_text":landing_page_text,
                "cloud_consent_endpoint":cloud_consent_endpoint,
                "record_id":record_id or None,"request_id":request_id,"mode":mode,"urgency":urgency,
                "supplement":supplement,"requested_industry":requested_industry,
                "job_id": job_id,
                "status": "queued",
                "message": "已上传，等待本机分析",
                "created_at": _now(),
                "original_file_name": video_name,
                "video_file": stored_video,
                "video_bytes": byte_count,
                "industry": industry,
                "product_category": product_category.strip(),
                "platform": platform,
                "platforms": platforms,
                "transcript_file": stored_transcript,
                "transcript_text": transcript_text.strip(),
                "sample_interval": sample_interval,
                "max_frames": max_frames,
                "asr_mode": "auto",
                "audit_response_ready":False,
            }
            _write_json(directory / "job.json", state)
            background_tasks.add_task(_process_job, job_id)
            return {"job_id":job_id,"request_id":request_id,"status":"queued","url":f"/jobs/{job_id}",
                    "deduplicated":False,**_job_links(job_id)}
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise

    @application.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict[str, Any]:
        return _poll_state(_read_json(_job_dir(job_id) / "job.json"))

    @application.get("/api/jobs/{job_id}/audit-response")
    def audit_response(job_id: str) -> JSONResponse:
        directory = _job_dir(job_id)
        path = directory / "audit_response.json"
        if path.is_file():
            return JSONResponse(_read_json(path))
        state = _read_json(directory / "job.json")
        if state.get("status") == "failed":
            return JSONResponse(status_code=500,content={"code":-1,"msg":"视频审核失败，请使用 job_id 排查","data":None})
        return JSONResponse(status_code=409,content={"code":-1,"msg":"视频审核尚未完成，请按 poll_url 继续轮询","data":None})

    @application.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_page(job_id: str) -> str:
        directory = _job_dir(job_id)
        state = _read_json(directory / "job.json")
        if state.get("status") in {"completed", "needs_attention"} and (directory / "report.json").is_file():
            return _report_page(job_id, _read_json(directory / "report.json"))
        return _waiting_page(job_id, state)

    @application.get("/api/jobs/{job_id}/report")
    def report(job_id: str) -> JSONResponse:
        return JSONResponse(_read_json(_job_dir(job_id) / "report.json"))

    @application.get("/api/jobs/{job_id}/evidence")
    def evidence(job_id: str) -> JSONResponse:
        return JSONResponse(_read_json(_job_dir(job_id) / "evidence.json"))

    @application.get("/api/jobs/{job_id}/manifest")
    def manifest(job_id: str) -> JSONResponse:
        return JSONResponse(_read_json(_job_dir(job_id) / "manifest.json"))

    @application.get("/api/jobs/{job_id}/media")
    def media(job_id: str) -> FileResponse:
        directory = _job_dir(job_id)
        state = _read_json(directory / "job.json")
        video_path = directory / str(state.get("video_file", ""))
        if not video_path.is_file():
            raise HTTPException(status_code=404, detail="视频不存在")
        return FileResponse(video_path, media_type="video/mp4", filename=state.get("original_file_name"))

    @application.get("/api/jobs/{job_id}/frames/{file_name}")
    def frame(job_id: str, file_name: str) -> FileResponse:
        if Path(file_name).name != file_name or not file_name.lower().endswith((".jpg", ".jpeg")):
            raise HTTPException(status_code=404, detail="画面不存在")
        path = _job_dir(job_id) / "frames" / file_name
        if not path.is_file():
            raise HTTPException(status_code=404, detail="画面不存在")
        return FileResponse(path, media_type="image/jpeg")

    return application


app = create_app()
