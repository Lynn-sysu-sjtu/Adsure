import importlib
import json
import sys
import types
import unittest
from unittest import mock


def _install_test_flask():
    """Tiny import-only Flask stand-in; production dependencies stay untouched."""
    flask = types.ModuleType("flask")

    class FakeFlask:
        def __init__(self, _name):
            pass

        def route(self, *_args, **_kwargs):
            return lambda func: func

    class FakeResponse:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.headers = {}

    flask.Flask = FakeFlask
    flask.Response = FakeResponse
    flask.render_template = lambda *_args, **_kwargs: ""
    flask.jsonify = lambda value=None, **kwargs: value if value is not None else kwargs
    flask.request = types.SimpleNamespace(json=None)
    sys.modules["flask"] = flask


def _install_test_requests():
    requests = types.ModuleType("requests")
    requests.post = lambda *_args, **_kwargs: _FakeResponse({"code": 0})
    requests.get = lambda *_args, **_kwargs: _FakeResponse({"code": 0, "data": {}})
    requests.put = lambda *_args, **_kwargs: _FakeResponse({"code": 0, "data": {}})
    requests.Timeout = type("Timeout", (Exception,), {})
    requests.ConnectionError = type("ConnectionError", (Exception,), {})
    requests.RequestException = type("RequestException", (Exception,), {})
    requests.exceptions = types.SimpleNamespace(
        Timeout=requests.Timeout,
        ConnectionError=requests.ConnectionError,
        RequestException=requests.RequestException,
    )
    sys.modules["requests"] = requests


def _install_test_config():
    config = types.ModuleType("config")
    values = {
        "FEISHU_APP_ID": "test-app",
        "FEISHU_APP_SECRET": "test-secret",
        "BITABLE_APP_TOKEN": "test-base",
        "BITABLE_TABLE_ID": "test-table",
        "WORKBENCH_URL": "https://workbench.example.test",
        "LEGAL_DEPT_NAME": "法律与合规",
        "LEGAL_OPEN_IDS": [],
    }
    for key, value in values.items():
        setattr(config, key, value)
    sys.modules["config"] = config


_install_test_flask()
_install_test_requests()
_install_test_config()
app_module = importlib.import_module("app")
fields = importlib.import_module("fields_v4")
card_templates = importlib.import_module("card_templates")
review_service = importlib.import_module("review_service")
ocr_preprocessor = importlib.import_module("ocr_preprocessor")


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class CompatibilityBaselineTests(unittest.TestCase):
    def test_three_industry_fields_remain_available(self):
        samples = {
            "美妆": {
                fields.F_美妆_物料类型: "图文",
                fields.F_美妆_产品品类: "护肤",
                fields.F_美妆_产品备案名称: "备案名",
                fields.F_美妆_物料涉及场景: ["详情页"],
                fields.F_美妆_核心宣称功效: "保湿",
            },
            "游戏": {
                fields.F_游戏_物料类型: "视频",
                fields.F_游戏_产品品类: "角色扮演",
                fields.F_游戏_游戏名称: "测试游戏",
                fields.F_游戏_物料涉及场景: ["开屏"],
                fields.F_游戏_IP名称: "测试IP",
            },
            "保健食品": {
                fields.F_保健食品_物料类型: "海报",
                fields.F_保健食品_产品品类: "营养补充",
                fields.F_保健食品_产品备案名称: "备案食品",
                fields.F_保健食品_批准文号: "国食健字测试",
                fields.F_保健食品_物料涉及场景: ["直播"],
                fields.F_保健食品_核心宣称功效: "补充营养",
            },
        }

        for industry, industry_fields in samples.items():
            with self.subTest(industry=industry):
                raw = {fields.F_行业领域: industry, **industry_fields}
                normalized = app_module.normalize_record("rec-test", raw)
                self.assertEqual(normalized["行业领域"], industry)
                for source_name, value in industry_fields.items():
                    label = f"{industry}_{source_name.split('·', 1)[1]}"
                    self.assertEqual(normalized[label], value)

    def test_initial_card_keeps_three_existing_buttons(self):
        raw_fields = {
            fields.F_行业领域: "美妆",
            fields.F_物料内容: "测试物料",
            fields.F_提交人: [{"id": "ou-test", "name": "运营"}],
            fields.F_紧急程度: "普通",
        }
        card = card_templates.build_initial_review_card("rec-test", raw_fields)
        actions = card["elements"][-1]["actions"]
        self.assertEqual([item["text"]["content"] for item in actions], [
            "🚀 开启 AI 审核",
            "✏️ 修改物料",
            "跳过 → 直发法务",
        ])
        self.assertEqual(actions[0]["value"]["action"], "start_ai_review")
        self.assertEqual(actions[2]["value"]["action"], "skip_review")

        versioned = card_templates.build_initial_review_card("rec-test", raw_fields, round_number=3)
        versioned_actions = versioned["elements"][-1]["actions"]
        self.assertEqual(versioned_actions[0]["value"]["round"], 3)
        self.assertEqual(versioned_actions[2]["value"]["round"], 3)

    def test_existing_result_more_info_and_legal_cards_keep_content_and_links(self):
        audit_fields = {
            fields.F_预审_风险等级: "高",
            fields.F_预审_命中要点: "命中要点测试",
            fields.F_预审_修改建议: "修改建议测试",
            fields.F_物料内容: "物料正文测试",
        }
        operator_card = card_templates.build_operator_result_card(
            "rec-test", audit_fields, round_number=1,
        )
        rendered_operator = repr(operator_card)
        self.assertIn("命中要点测试", rendered_operator)
        self.assertIn("修改建议测试", rendered_operator)
        operator_actions = operator_card["elements"][-1]["actions"]
        self.assertEqual(operator_actions[2]["value"]["action"], "resubmit")
        self.assertEqual(operator_actions[3]["value"]["action"], "escalate_to_legal")

        more_info = card_templates.build_more_info_card(
            "rec-test", audit_fields, round_number=1,
        )
        rendered_more_info = repr(more_info)
        self.assertIn("请补充物料信息", rendered_more_info)
        self.assertIn("去补充", rendered_more_info)
        self.assertNotIn("运营补资料", rendered_more_info)

        legal_card = card_templates.build_legal_review_card(
            "rec-test", audit_fields, workbench_url="https://workbench.example.test",
        )
        legal_action = legal_card["elements"][-1]["actions"][0]
        self.assertEqual(legal_action["text"]["content"], "🖥 打开法务工作台")
        self.assertEqual(legal_action["url"], "https://workbench.example.test")

    def test_operator_verdict_cards_keep_pass_and_revision_semantics(self):
        common = {
            fields.F_物料编号: "AD-001",
            fields.F_物料内容: "物料正文",
            fields.F_法务_AI意见评价: "同意无补充",
        }
        passed = card_templates.build_verdict_card(
            "rec-test", {**common, fields.F_法务_物料裁决: "通过"}, round_number=1,
        )
        self.assertIn("物料已通过法务审核", passed["header"]["title"]["content"])
        self.assertFalse(any(
            action.get("value", {}).get("action") == "resubmit"
            for action in passed["elements"][-1]["actions"]
        ))

        revision = card_templates.build_verdict_card(
            "rec-test", {
                **common,
                fields.F_法务_物料裁决: "不通过",
                fields.F_法务_最终修改意见: "请修改宣称",
            }, round_number=1,
        )
        self.assertIn("请修改宣称", repr(revision))
        self.assertTrue(any(
            action.get("value", {}).get("action") == "resubmit"
            for action in revision["elements"][-1]["actions"]
        ))

    def test_ocr_and_case_helpers_degrade_without_blocking(self):
        with mock.patch.object(
            ocr_preprocessor, "download_attachment", side_effect=RuntimeError("SECRET_OCR"),
        ):
            text = ocr_preprocessor.extract_text_from_attachments("rec-test", {
                fields.F_物料附件: [{
                    "file_token": "file-test", "name": "sample.png", "type": "image/png",
                }],
            })
        self.assertEqual(text, "")
        self.assertEqual(app_module.get_cases("rec-test"), {
            "cases": [], "record_id": "rec-test",
        })

    def test_six_legal_decision_combinations_keep_semantics(self):
        combinations = [
            ("同意无补充", "通过", "无", "已通过", {}),
            ("同意无补充", "不通过", "无", "需修改", {"final_suggestion": "修改"}),
            ("同意有补充", "通过", "refine", "已通过", {"supplement_reason": "补充"}),
            ("同意有补充", "不通过", "refine", "需修改", {
                "supplement_reason": "补充", "final_suggestion": "修改"
            }),
            ("驳回", "通过", "override", "已通过", {
                "objection_fields": ["风险等级"], "reject_reason": "理由", "correct_judgment": "正确"
            }),
            ("驳回", "不通过", "override", "需修改", {
                "objection_fields": ["违规类型"], "reject_reason": "理由",
                "correct_judgment": "正确", "final_suggestion": "修改"
            }),
        ]

        for opinion, verdict, feedback, status, extras in combinations:
            payload = {
                "ai_opinion": opinion,
                "verdict": verdict,
                "reviewer_name": "法务",
                "notify_operator": False,
                "submitted_at_ms": 1700000000000,
                **extras,
            }
            with self.subTest(opinion=opinion, verdict=verdict):
                self.assertEqual(review_service.validate_review_payload(payload), {})
                actual_status, actual_feedback = review_service.review_outcome(payload)
                self.assertEqual(actual_feedback, feedback)
                self.assertEqual(actual_status, status)
                update = review_service.build_update_fields(payload, {fields.F_流转_驳回次数: 2})
                self.assertEqual(update[fields.F_流转_当前状态], status)
                self.assertEqual(update[fields.F_流转_反馈类型], feedback)
                self.assertEqual(update[fields.F_法务_AI意见评价], opinion)
                self.assertEqual(update[fields.F_法务_物料裁决], verdict)
                if opinion == "驳回":
                    self.assertEqual(update[fields.F_流转_驳回次数], 3)


if __name__ == "__main__":
    unittest.main()
