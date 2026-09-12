from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from src.audit_contract import build_video_response
from src.video_mvp import api


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "data/schemas/audit_response_v0.2.schema.json").read_text(encoding="utf-8"))


def fixture_report(job_id: str = "job-fixture", *, complete: bool = False) -> dict:
    return {
        "job_id": job_id,
        "analysis_status": "completed" if complete else "needs_attention",
        "coverage_status": "sampled_complete" if complete else "not_proven",
        "review_status": "pending_human_review",
        "summary": {"risk_count": 1, "highest_severity": "high"},
        "risks": [{
            "risk_id": "risk-1", "title": "绝对化表述候选", "severity": "high",
            "risk_dimension": "绝对化用语", "matched_text": "国家级", "t_start": 1.2,
            "t_end": 2.1, "rule_ids": ["ADLAW-009-03"], "legal_basis": [{
                "source_name": "国家市场监督管理总局", "article": "第九条第三项"
            }], "explanation": "需结合上下文判断", "recommendation": "删除或改写绝对化表述",
            "context_text": "国家级美白科技", "source": "asr", "pattern_id": "absolute_term",
        }],
        "requirement_checks": [],
        "material_verification": {
            "status": "review_required", "document_count": 0, "unreadable_documents": [],
            "checks": [{"check_type": "product_claim", "claim": "美白", "status": "missing",
                        "gaps": ["未找到支持该具体主张的材料"], "conflicts": [],
                        "conclusion": "材料存在性不等于真实性和证明力已确认。"}],
        },
        "visual_semantics": {
            "status": "analyzed", "observations": [{"category": "before_after_comparison",
                "frame_ids": ["frame_000001"], "t_start": 3.0, "t_end": 3.0,
                "description": "左右前后对比画面", "uncertainty": "效果真实性未知"}],
        },
        "platform_verification": {
            "status": "manual_review_required", "findings": [{"platform": "小红书",
                "locator": "候选条款 1.1", "rule_summary": "广告应具有可识别性",
                "review_status": "pending_human_review"}],
            "warnings": ["投放前需复核官方最新版本"],
        },
        "scope": {"product_name": "测试精华", "product_category": "护肤", "platform": "小红书"},
        "warnings": [] if complete else ["画面覆盖待复核"],
    }


def assert_schema(test: unittest.TestCase, body: dict) -> None:
    errors = list(Draft202012Validator(SCHEMA).iter_errors(body))
    test.assertEqual([], [(item.json_path, item.message) for item in errors])


class VideoReportAdapterTests(unittest.TestCase):
    def test_video_findings_are_mapped_without_false_legal_conclusion(self) -> None:
        data = build_video_response(fixture_report(), {
            "request_id": "rec-video-001", "mode": "深度", "platform": "小红书"
        }, now_ms=1_800_000_000_000)
        body = {"code": 0, "msg": "ok", "data": data}
        assert_schema(self, body)
        self.assertEqual("rec-video-001", data["request_id"])
        self.assertEqual(data["预审_时间"], data["审核_审核时间"])
        self.assertEqual(data["审核_审核时间"], data["audit_time"])
        rule_ids = {item["rule_id"] for item in data["matched_rules"]}
        self.assertTrue({"ADLAW-009-03", "ADSURE-MATERIAL-CLAIM", "ADSURE-SCENE-BEFORE-AFTER"} <= rule_ids)
        self.assertTrue(all(item["applicability_status"] == "needs_fact_verification"
                            for item in data["matched_rules"]))
        self.assertIn("平台预检", data["审核_审核意见"])
        self.assertTrue(data["context_package"]["human_review_required"])

    def test_incomplete_no_hit_is_low_instead_of_clear(self) -> None:
        report = fixture_report()
        report["risks"] = []
        report["material_verification"]["checks"] = []
        report["visual_semantics"]["observations"] = []
        data = build_video_response(report, {"request_id": "rec-incomplete"}, now_ms=1)
        self.assertEqual("低", data["预审_风险等级"])
        self.assertIn("覆盖不足", data["预审_命中要点"])

    def test_complete_no_hit_can_use_no_obvious_risk_with_boundary(self) -> None:
        report = fixture_report(complete=True)
        report["risks"] = []
        report["material_verification"]["checks"] = []
        report["visual_semantics"]["observations"] = []
        data = build_video_response(report, {"request_id": "rec-complete"}, now_ms=1)
        self.assertEqual("无明显风险", data["预审_风险等级"])
        self.assertEqual("低", data["审核_推荐风险等级"])
        self.assertIn("不代表无风险", data["预审_命中要点"])


class VideoPollingContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.jobs = Path(self.tmp.name)

        def fake_analyze(_video: Path, destination: Path, **kwargs) -> dict:
            report = fixture_report(kwargs["job_id"])
            (destination / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            (destination / "manifest.json").write_text(json.dumps({"artifacts": {}}), encoding="utf-8")
            return report

        self.jobs_patch = patch.object(api, "JOBS_ROOT", self.jobs)
        self.analyze_patch = patch.object(api, "analyze_video", side_effect=fake_analyze)
        self.jobs_patch.start()
        self.mock_analyze = self.analyze_patch.start()
        self.client = TestClient(api.create_app())

    def tearDown(self) -> None:
        self.client.close()
        self.analyze_patch.stop()
        self.jobs_patch.stop()
        self.tmp.cleanup()

    def upload(self):
        return self.client.post("/api/jobs", files={"video": ("ad.mp4", b"fixture", "video/mp4")}, data={
            "record_id": "rec-video-poll-001", "industry": "美妆", "product_category": "护肤",
            "platforms_json": json.dumps(["小红书", "抖音"], ensure_ascii=False), "mode": "深度",
            "urgency": "加急", "supplement": "产品资料待补充",
        })

    def test_upload_poll_and_fetch_v02_result(self) -> None:
        created = self.upload()
        self.assertEqual(202, created.status_code)
        accepted = created.json()
        self.assertFalse(accepted["deduplicated"])
        job_id = accepted["job_id"]
        self.assertEqual(f"/api/jobs/{job_id}", accepted["poll_url"])
        status = self.client.get(accepted["poll_url"]).json()
        self.assertTrue(status["terminal"])
        self.assertTrue(status["audit_response_ready"])
        self.assertEqual(0, status["retry_after_ms"])
        self.assertNotIn("supplement", status)
        self.assertNotIn("transcript_text", status)
        self.assertNotIn("video_file", status)
        self.assertEqual(["小红书", "抖音"], json.loads((self.jobs / job_id / "job.json").read_text())["platforms"])

        result = self.client.get(accepted["audit_response_url"])
        self.assertEqual(200, result.status_code)
        body = result.json()
        assert_schema(self, body)
        self.assertEqual("rec-video-poll-001", body["data"]["request_id"])
        manifest = json.loads((self.jobs / job_id / "manifest.json").read_text(encoding="utf-8"))
        expected = hashlib.sha256((self.jobs / job_id / "audit_response.json").read_bytes()).hexdigest()
        self.assertEqual(expected, manifest["artifacts"]["feishu_audit_response_sha256"])

    def test_record_id_is_idempotent(self) -> None:
        first = self.upload().json()
        second = self.upload().json()
        self.assertEqual(first["job_id"], second["job_id"])
        self.assertTrue(second["deduplicated"])
        self.assertEqual(1, self.mock_analyze.call_count)

    def test_pending_job_returns_poll_instruction(self) -> None:
        job_id = "1" * 32
        directory = self.jobs / job_id
        directory.mkdir()
        (directory / "job.json").write_text(json.dumps({"job_id": job_id, "status": "processing"}), encoding="utf-8")
        status = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertFalse(status["terminal"])
        self.assertEqual(1500, status["retry_after_ms"])
        result = self.client.get(f"/api/jobs/{job_id}/audit-response")
        self.assertEqual(409, result.status_code)
        self.assertEqual(-1, result.json()["code"])

    def test_bad_platform_array_fails_before_job_creation(self) -> None:
        result = self.client.post("/api/jobs", files={"video": ("ad.mp4", b"fixture")},
                                  data={"platforms_json": "{}"})
        self.assertEqual(400, result.status_code)
        self.assertEqual([], list(self.jobs.iterdir()))


if __name__ == "__main__":
    unittest.main()
