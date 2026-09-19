from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from src.api import create_app

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "data/schemas/audit_response_v0.2.schema.json").read_text(encoding="utf-8"))


class AuditContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        data = Path(self.tmp.name)
        (data / "chunks").mkdir()
        (data / "structured").mkdir()
        (data / "structured_candidates").mkdir()
        (data / "chunks/production_chunks.json").write_text("[]", encoding="utf-8")
        self.client = TestClient(create_app(data_dir=data, api_key="test-secret"))

    def tearDown(self):
        self.tmp.cleanup()

    def post(self, payload, key="test-secret"):
        return self.client.post("/audit", headers={"X-API-Key": key}, json=payload)

    def standard(self, content="国家级美白科技，7天美白见效"):
        return {"record_id":"rec_feishu_001","mode":"标准","industry":"美妆","content":content,
                "urgency":"普通","supplement":"","platform":["小红书"],"material_type":"图文",
                "product_category":"护肤","extras":{"产品备案名称":"测试精华","核心宣称功效":["美白"]}}

    def assert_schema(self, response):
        errors=list(Draft202012Validator(SCHEMA).iter_errors(response))
        self.assertEqual([],[(e.json_path,e.message) for e in errors])

    def test_standard_request_matches_feishu_v02_schema(self):
        response=self.post(self.standard())
        self.assertEqual(200,response.status_code)
        body=response.json(); self.assert_schema(body)
        data=body["data"]
        self.assertEqual("rec_feishu_001",data["request_id"])
        self.assertEqual(data["预审_时间"],data["审核_审核时间"])
        self.assertEqual(data["审核_审核时间"],data["audit_time"])
        self.assertTrue(data["matched_rules"])
        self.assertIn("ADLAW-011-02",[r["rule_id"] for r in data["matched_rules"]])
        self.assertEqual(len(data["matched_rules"]),len({r["rule_id"] for r in data["matched_rules"]}))
        self.assertTrue(all(r["default_routing"] in {"运营","法务","运营补资料"} for r in data["matched_rules"]))
        self.assertNotIn("regex:",data["审核_高风险词命中"])
        self.assertTrue(data["context_package"]["human_review_required"])

    def test_base_v4_fields_wrapper_is_supported(self):
        payload={"record_id":"rec_base_001","mode":"标准","fields":{
            "①运营·行业领域":"美妆","①运营·物料内容":"可治疗痤疮，保证有效",
            "①运营·紧急程度":"加急","①运营·补充背景资料":"未提供证明",
            "①美妆·物料类型":"短视频","①美妆·投放平台":["抖音","小红书"],
            "①美妆·产品品类":"护肤","①美妆·产品备案名称":"测试产品"}}
        body=self.post(payload).json(); self.assert_schema(body)
        self.assertEqual("rec_base_001",body["data"]["request_id"])
        self.assertIn("涉医疗宣传",body["data"]["审核_推荐违规类型"])

    def test_no_match_is_not_presented_as_legal_clearance(self):
        body=self.post(self.standard("温和清洁肌肤，具体成分请见产品标签")).json()
        self.assert_schema(body)
        self.assertEqual("无明显风险",body["data"]["预审_风险等级"])
        self.assertEqual("低",body["data"]["审核_推荐风险等级"])
        self.assertEqual([],body["data"]["matched_rules"])
        self.assertIn("不代表无风险",body["data"]["审核_审核意见"])

    def test_fact_dependent_rule_requests_operations_materials(self):
        body=self.post(self.standard("临床验证99%有效")).json()
        self.assert_schema(body)
        self.assertIn("运营补资料",[r["default_routing"] for r in body["data"]["matched_rules"]])
        self.assertEqual("needs_fact_verification",body["data"]["matched_rules"][0]["applicability_status"])

    def test_frontend_does_not_receive_false_clear_state_for_material_checks(self):
        for content in ["普通精华也能祛斑美白、防晒、防脱发", "儿童润唇膏宝宝可以放心吃，100%无任何风险",
                        "左图长痘，右图用完皮肤完美无瑕，效果如图所见", "独家国家专利抗皱配方"]:
            with self.subTest(content=content):
                body=self.post(self.standard(content)).json(); self.assert_schema(body)
                self.assertNotEqual("无明显风险",body["data"]["预审_风险等级"])
                self.assertTrue(body["data"]["matched_rules"])
                self.assertTrue(all(r["applicability_status"]=="needs_fact_verification" for r in body["data"]["matched_rules"]))

    def test_bad_requests_use_stable_error_envelope(self):
        cases=[({},"缺少或无效字段：record_id"),
               ({"record_id":"x","mode":"标准","fields":{"①运营·行业领域":"美妆","①美妆·投放平台":["小红书"],"①美妆·物料类型":"图文"}},"缺少必填字段：①运营·物料内容"),
               ({**self.standard(),"human_reference":{"answer":"泄漏"}},"线上 /audit 不接收")]
        for payload,message in cases:
            with self.subTest(message=message):
                response=self.post(payload); self.assertEqual(400,response.status_code)
                body=response.json(); self.assertEqual(-1,body["code"]); self.assertIsNone(body["data"])
                self.assertIn(message,body["msg"]); self.assert_schema(body)

    def test_authentication_is_required(self):
        response=self.post(self.standard(),key="wrong")
        self.assertEqual(401,response.status_code)
        self.assert_schema(response.json())


if __name__ == "__main__":
    unittest.main()
