"""异步任务 API 测试：提交-轮询-结果三段式 + 飞书 v0.2 契约。"""

from __future__ import annotations

import io
import json
import struct
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from app.api import build_feishu_response, create_app

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (ROOT / "data/schemas/audit_response_v0.2.schema.json").read_text(encoding="utf-8"))


def _tiny_mp4() -> bytes:
    """最小可用视频：真实编码由 review 链路处理，这里只需过格式校验。
    实际审核在 _run_job 里会失败（不是合法视频），用于验证失败路径。
    真实成功路径由 test_job_lifecycle_with_real_video 用 fixture 视频。"""
    return b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ADSURE_JOBS_DIR", str(tmp_path / "jobs"))
    from app.api import JOBS_ROOT
    import app.api as api_mod
    monkeypatch.setattr(api_mod, "JOBS_ROOT", tmp_path / "jobs")
    app = create_app()
    with TestClient(app) as c:
        yield c, tmp_path


def test_health_contract(client):
    c, _ = client
    r = c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "adsure-video-review"
    assert body["feishu_contract"]["version"] == "0.2"


def test_upload_rejects_bad_suffix(client):
    c, _ = client
    r = c.post("/api/jobs", files={"video": ("ad.avi", b"x", "video/avi")})
    assert r.status_code == 400


def test_upload_rejects_bad_industry(client):
    c, _ = client
    r = c.post("/api/jobs", files={"video": ("ad.mp4", b"x", "video/mp4")},
               data={"industry": "金融"})
    assert r.status_code == 400


def test_upload_rejects_oversize_supplement(client):
    c, _ = client
    r = c.post("/api/jobs", files={"video": ("ad.mp4", b"x", "video/mp4")},
               data={"supplement": "x" * 30001})
    assert r.status_code == 400


def test_failed_job_lifecycle_and_contract_shape(client):
    """坏视频 → 任务失败 → 状态可轮询、audit-response 返回 500 而非静默。"""
    c, tmp = client
    r = c.post("/api/jobs", files={"video": ("ad.mp4", _tiny_mp4(), "video/mp4")},
               data={"industry": "保健食品", "record_id": "rec-fail-001"})
    assert r.status_code == 202
    body = r.json()
    assert body["deduplicated"] is False
    job_id = body["job_id"]
    assert body["poll_url"] == f"/api/jobs/{job_id}"

    # TestClient 的 background 任务在请求内同步执行完毕
    status = c.get(body["poll_url"]).json()
    assert status["terminal"] is True
    assert status["job_id"] == job_id
    assert "retry_after_ms" in status

    result = c.get(body["audit_response_url"])
    assert result.status_code == 500
    assert result.json()["code"] == -1


def test_record_id_is_idempotent(client):
    c, _ = client
    files = {"video": ("ad.mp4", _tiny_mp4(), "video/mp4")}
    first = c.post("/api/jobs", files=files, data={"record_id": "rec-dup-001"}).json()
    second = c.post("/api/jobs", files=files, data={"record_id": "rec-dup-001"}).json()
    assert first["job_id"] == second["job_id"]
    assert second["deduplicated"] is True


# ── 飞书 v0.2 契约适配 ─────────────────────────────────────────


def _sample_report() -> dict:
    return {
        "meta": {"review_id": "job-x", "industry": "health_food",
                 "video": {"path": "ad.mp4", "duration": 30.0},
                 "llm": {"mode": "mock"},
                 "cost": {"ocr_calls": 12}},
        "summary": {"level": "high", "risk_count": 2, "advisory_count": 1},
        "cost": {"ocr_calls": 12},
        "evidence": [],
        "findings": [
            {"title": "「国家级」需事实核验", "t_start": 3.2, "t_end": 4.0,
             "source": "口播", "level": "medium", "level_label": "中",
             "counts_as_risk": True, "category": "需补充材料后复判",
             "legal_basis": "《广告法》第九条第（三）项",
             "报告": {"风险表达": "口播中出现「国家级」",
                      "风险定性": "依赖素材之外的事实",
                      "修改建议": "补充第三方数据"},
             "required_materials": ["第三方数据来源"]},
            {"title": "「根治」需事实核验", "t_start": 8.0, "t_end": 9.2,
             "source": "画面文字", "level": "high", "level_label": "高",
             "counts_as_risk": True, "category": "需补充材料后复判",
             "legal_basis": "《广告法》第十八条",
             "报告": {"风险表达": "画面出现「三天彻底根治」",
                      "风险定性": "疾病治疗宣称", "修改建议": "删除该表述"},
             "required_materials": []},
            {"title": "广告可识别性 —— 仅提示", "t_start": 0, "t_end": 0,
             "source": "全片", "level": "advisory", "level_label": "仅提示",
             "counts_as_risk": False, "category": "必备要素与显著性",
             "legal_basis": "《广告法》第十四条",
             "报告": {}},
        ],
        "disclaimer": "test",
    }


def test_feishu_response_matches_v02_schema():
    state = {"request_id": "rec-001", "job_id": "job-x"}
    data = build_feishu_response(_sample_report(), state, now_ms=1_800_000_000_000)
    body = {"code": 0, "msg": "ok", "data": data}
    errors = list(Draft202012Validator(SCHEMA).iter_errors(body))
    assert errors == [], [(e.json_path, e.message) for e in errors]
    assert data["request_id"] == "rec-001"
    assert data["预审_时间"] == data["审核_审核时间"] == data["audit_time"]
    # 高危「根治」路由法务；需材料的「国家级」路由运营补资料
    routes = {r["rule_id"]: r["default_routing"] for r in data["matched_rules"]}
    assert "法务" in routes.values()
    assert "运营补资料" in routes.values()
    assert data["routing"] == "法务"
    assert data["context_package"]["human_review_required"] is True
    # 仅提示项不进 matched_rules
    assert all("仅提示" not in r["title"] for r in data["matched_rules"])


def test_feishu_response_no_risk_boundary():
    report = _sample_report()
    report["findings"] = [f for f in report["findings"] if not f["counts_as_risk"]]
    data = build_feishu_response(report, {"request_id": "rec-clean"}, now_ms=1)
    assert data["预审_风险等级"] == "无明显风险"
    assert "不代表无风险" in data["预审_命中要点"]
    assert data["matched_rules"] == []


def test_feishu_response_aggregates_same_rule():
    report = _sample_report()
    # 两条都命中绝对化用语 → 聚合为一条，风险取最高
    report["findings"][1]["title"] = "「第一」需事实核验"
    report["findings"][1]["报告"]["风险表达"] = "画面出现「全网第一」"
    data = build_feishu_response(report, {"request_id": "rec-agg"}, now_ms=1)
    abs_rules = [r for r in data["matched_rules"] if r["rule_id"] == "ADLAW-009-03"]
    assert len(abs_rules) == 1
    assert "国家级" in abs_rules[0]["match_reason"]
    assert "全网第一" in abs_rules[0]["match_reason"]
