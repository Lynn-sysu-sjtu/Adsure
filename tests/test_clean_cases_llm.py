import json
import tempfile
import unittest
from pathlib import Path

from src import clean_cases


class CleanCasesLLMTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raw_text_dir = self.root / "data/raw_text"
        self.structured_dir = self.root / "data/structured"
        self.structured_samples_dir = self.root / "data/structured_samples"
        self.reports_dir = self.root / "data/reports"
        self.prompt_path = self.root / "prompts/clean_case_prompt.md"
        self.raw_text_dir.mkdir(parents=True)
        self.structured_dir.mkdir(parents=True)
        self.structured_samples_dir.mkdir(parents=True)
        self.reports_dir.mkdir(parents=True)
        self.prompt_path.parent.mkdir(parents=True)
        self.prompt_path.write_text("案例正文：\n{{case_text}}\n", encoding="utf-8")
        self.raw_text_path = self.raw_text_dir / "case_001.json"
        self.raw_text_path.write_text(
            json.dumps(
                {
                    "case_id": "case_001",
                    "title": "普通食品宣传降血糖案",
                    "source_type": "offline_sample",
                    "source_name": "离线样例",
                    "source_url": "https://example.com/offline/food-blood-sugar",
                    "raw_text_path": str(self.raw_text_path),
                    "case_text": "某公司在互联网广告中将普通食品宣传为可以“降血糖”，监管机关认为容易误导消费者。",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_openai_mode_without_api_key_falls_back_to_mock(self):
        outputs = clean_cases.run(
            raw_text_dir=self.raw_text_dir,
            structured_dir=self.structured_dir,
            structured_samples_dir=self.structured_samples_dir,
            prompt_path=self.prompt_path,
            reports_dir=self.reports_dir,
            mode="openai",
            env={},
        )

        self.assertEqual(len(outputs), 1)
        case = json.loads(outputs[0].read_text(encoding="utf-8"))
        self.assertIn("涉医疗宣传", case["risk_dimensions"])
        self.assertEqual(outputs[0].parent, self.structured_samples_dir)
        self.assertEqual(list(self.structured_dir.glob("*.json")), [])
        self.assertFalse((self.reports_dir / "llm_runs.jsonl").exists())

    def test_official_cases_write_to_structured_dir(self):
        self.raw_text_path.write_text(
            json.dumps(
                {
                    "case_id": "official_001",
                    "title": "官方案例",
                    "source_type": "official_typical_case",
                    "source_name": "国家市场监督管理总局",
                    "source_url": "https://www.samr.gov.cn/example.html",
                    "raw_text_path": str(self.raw_text_path),
                    "case_text": "某公司在互联网广告中宣称产品为“国家级最佳”，违反广告法第二十八条。",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        outputs = clean_cases.run(
            raw_text_dir=self.raw_text_dir,
            structured_dir=self.structured_dir,
            structured_samples_dir=self.structured_samples_dir,
            prompt_path=self.prompt_path,
            reports_dir=self.reports_dir,
            mode="mock",
            env={},
        )

        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0].parent, self.structured_dir)
        self.assertEqual(list(self.structured_samples_dir.glob("*.json")), [])

    def test_provider_request_logs_metadata_without_key_material(self):
        def fake_request(provider, model, prompt, api_key):
            return clean_cases.LLMResponse(
                text=json.dumps(
                    {
                        "case_id": "case_001",
                        "title": "普通食品宣传降血糖案",
                        "source_name": "离线样例",
                        "source_url": "https://example.com/offline/food-blood-sugar",
                        "facts_summary": "普通食品广告宣称可以降血糖。",
                        "risk_dimensions": ["涉医疗宣传"],
                        "illegal_claims": ["降血糖"],
                        "legal_basis": ["《中华人民共和国广告法》"],
                        "regulatory_logic": "监管机关认为普通食品不得宣传疾病治疗或健康改善功效。",
                        "vector_text": "普通食品通过互联网广告宣称可以降血糖，消费者可能理解为具有疾病治疗或健康改善功效。",
                        "review_status": "pending_review",
                    },
                    ensure_ascii=False,
                ),
                request_id="req_123",
                model=model,
            )

        outputs = clean_cases.run(
            raw_text_dir=self.raw_text_dir,
            structured_dir=self.structured_dir,
            structured_samples_dir=self.structured_samples_dir,
            prompt_path=self.prompt_path,
            reports_dir=self.reports_dir,
            mode="openai",
            env={"OPENAI_API_KEY": "sk-test-secret", "LLM_MODEL": "gpt-test"},
            llm_requester=fake_request,
        )

        self.assertEqual(len(outputs), 1)
        log_text = (self.reports_dir / "llm_runs.jsonl").read_text(encoding="utf-8")
        log = json.loads(log_text)
        self.assertEqual(log["request_id"], "req_123")
        self.assertEqual(log["model"], "gpt-test")
        self.assertEqual(log["provider"], "openai")
        self.assertNotIn("sk-test-secret", log_text)

    def test_invalid_json_output_is_saved_and_retried_twice(self):
        calls = []

        def fake_request(provider, model, prompt, api_key):
            calls.append(prompt)
            return clean_cases.LLMResponse(text="不是 JSON", request_id=f"req_{len(calls)}", model=model)

        outputs = clean_cases.run(
            raw_text_dir=self.raw_text_dir,
            structured_dir=self.structured_dir,
            structured_samples_dir=self.structured_samples_dir,
            prompt_path=self.prompt_path,
            reports_dir=self.reports_dir,
            mode="anthropic",
            env={"ANTHROPIC_API_KEY": "anthropic-secret", "LLM_MODEL": "claude-test"},
            llm_requester=fake_request,
            max_retries=2,
        )

        failed_outputs = sorted((self.reports_dir / "failed_outputs").glob("*.txt"))
        self.assertEqual(outputs, [])
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(failed_outputs), 3)
        self.assertEqual(failed_outputs[0].read_text(encoding="utf-8"), "不是 JSON")


if __name__ == "__main__":
    unittest.main()
