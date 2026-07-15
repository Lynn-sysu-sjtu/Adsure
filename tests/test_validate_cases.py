import json
import tempfile
import unittest
from pathlib import Path

from src import validate_cases


class ValidateCasesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.structured_dir = self.root / "data/structured"
        self.reports_dir = self.root / "data/reports"
        self.prompt_path = self.root / "prompts/clean_case_prompt.md"
        self.structured_dir.mkdir(parents=True)
        self.reports_dir.mkdir(parents=True)
        self.prompt_path.parent.mkdir(parents=True)
        self.prompt_path.write_text(
            """
risk_dimensions 枚举：
- 虚假宣传
- 绝对化用语
- 其他

输出 JSON schema：
""",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def write_case(self, name, **overrides):
        case = {
            "case_id": name,
            "title": "某公司互联网广告处罚案",
            "source_name": "国家市场监督管理总局违法广告典型案例",
            "source_url": "https://www.samr.gov.cn/example-case.html",
            "facts_summary": "某公司在互联网广告中发布夸大宣传内容，监管机关认定相关内容容易误导消费者。",
            "risk_dimensions": ["虚假宣传"],
            "illegal_claims": ["国家级最佳"],
            "legal_basis": ["《中华人民共和国广告法》"],
            "regulatory_logic": "监管机关认为相关宣传内容与实际情况不符，足以影响消费者判断。",
            "vector_text": "某公司通过互联网广告宣传产品效果，使用国家级最佳等表述，监管机关认为该场景存在虚假宣传风险。",
            "review_status": "cleaned",
        }
        case.update(overrides)
        path = self.structured_dir / f"{name}.json"
        path.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def test_writes_markdown_report_and_keeps_structured_json_unchanged(self):
        case_path = self.write_case("valid_case")
        original = case_path.read_text(encoding="utf-8")

        report = validate_cases.run(
            structured_dir=self.structured_dir,
            reports_dir=self.reports_dir,
            prompt_path=self.prompt_path,
        )

        report_path = self.reports_dir / "validation_report.md"
        self.assertTrue(report_path.exists())
        self.assertFalse((self.reports_dir / "validation_report.json").exists())
        self.assertEqual(case_path.read_text(encoding="utf-8"), original)
        self.assertEqual(report["valid_count"], 1)
        self.assertIn("| valid_case | PASS |", report_path.read_text(encoding="utf-8"))

    def test_flags_invalid_source_url_and_prompt_enum_risk(self):
        self.write_case(
            "invalid_url_and_risk",
            source_url="sample://offline/example",
            risk_dimensions=["涉医疗宣传"],
        )

        report = validate_cases.run(
            structured_dir=self.structured_dir,
            reports_dir=self.reports_dir,
            prompt_path=self.prompt_path,
        )

        errors = report["cases"][0]["errors"]
        self.assertIn("invalid_source_url", errors)
        self.assertIn("invalid_risk_dimensions:涉医疗宣传", errors)

    def test_flags_short_or_keyword_list_vector_text(self):
        self.write_case(
            "bad_vector_text",
            vector_text="虚假宣传,绝对化用语,互联网广告",
        )

        report = validate_cases.run(
            structured_dir=self.structured_dir,
            reports_dir=self.reports_dir,
            prompt_path=self.prompt_path,
        )

        self.assertIn("invalid_vector_text", report["cases"][0]["errors"])

    def test_empty_legal_basis_requires_pending_review(self):
        self.write_case(
            "legal_basis_missing",
            legal_basis=[],
            review_status="cleaned",
        )

        report = validate_cases.run(
            structured_dir=self.structured_dir,
            reports_dir=self.reports_dir,
            prompt_path=self.prompt_path,
        )

        self.assertIn(
            "legal_basis_empty_requires_pending_review",
            report["cases"][0]["errors"],
        )


if __name__ == "__main__":
    unittest.main()
