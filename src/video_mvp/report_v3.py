"""Server-rendered advanced checks; every supplied string is escaped."""
import html


def e(value):
    return html.escape(str(value))


def advanced_sections(report):
    if report.get("schema_version") != "video-mvp-report/v3":
        return ""
    blocks=[]
    semantics=report.get("visual_semantics",{})
    scene_items="".join(f'<div class="source"><b>{e(s["category"])}</b> · <a class="seek" href="#video" data-time="{s["t_start"]}">{s["t_start"]:.2f}–{s["t_end"]:.2f}s</a><br>{e(s["description"])}<br><span class="muted">不确定性：{e(s["uncertainty"])}；机器观察，待复核</span></div>' for s in semantics.get("observations",[]))
    errors = "；".join(x.get("message","") for x in semantics.get("errors",[]))
    blocks.append(f'<section class="card section"><h2>画面语义观察</h2><p>状态：{e(semantics.get("status"))} · {e(semantics.get("limitation",""))}</p><p>{e(errors)}</p>{scene_items or "尚无可用的语义识别结果，不代表画面没有风险。"}</section>')
    comparisons=report.get("coverage",{}).get("audio",{}).get("engine_disagreements",[])
    if comparisons:
        items="".join(f'<div class="source">{s["start"]:.2f}–{s["end"]:.2f}s<br>主引擎 Whisper：{e(s["primary"])}<br>中文独立复核：{e(s["alternative"])}<br>两者不一致，请回听；不自动改写原文。</div>' for s in comparisons)
        blocks.append(f'<section class="card section"><h2>语音双引擎分歧</h2>{items}</section>')
    materials=report.get("material_verification",{})
    items=[]
    for check in materials.get("checks",[]):
        refs="".join(f'<details><summary>{e(r.get("file_name"))} · {e(r.get("page","字段定位"))}</summary><pre style="white-space:pre-wrap">{e(r.get("quote",r.get("fields","")))}</pre></details>' for r in check.get("references",[]))
        gaps="；".join(check.get("gaps",[])+check.get("conflicts",[]))
        items.append(f'<div class="source"><b>{e(check["claim"])}</b> · {e(check["status"])}<br>{e(gaps)}<br>{e(check.get("conclusion",""))}{refs}</div>')
    unreadable = "；".join(materials.get("unreadable_documents",[]))
    blocks.append(f'<section class="card section"><h2>产品证明与活动条件</h2><p>已接收 {materials.get("document_count",0)} 份材料；真实性和实际兑现未获证明。</p><p>{e("提取不完整或无法读取："+unreadable) if unreadable else ""}</p>{"".join(items) or "未发现已配置的材料核验触发项；请确认产品名称与资料是否齐全。"}</section>')
    platform=report.get("platform_verification",{})
    items=[]
    for finding in platform.get("findings",[]):
        source=finding["source_status"]
        items.append(f'<div class="source"><b>{e(finding["platform"])} · {e(finding["title"])}</b><br>{e(finding["locator"])}<br>{e(finding["rule_summary"])}<br><span class="muted">{e(finding["reason"])} 来源状态：{e(source.get("freshness"))}</span><br><a target="_blank" rel="noopener" href="{e(finding["source_url"])}">官方来源</a></div>')
    blocks.append(f'<section class="card section"><h2>平台规则核验（与法律结论分开）</h2><p>{e("；".join(platform.get("warnings",[])))}</p>{"".join(items) or "没有可展示的平台条款命中；请查看规则可用性和适用场景。"}</section>')
    return "".join(blocks)
