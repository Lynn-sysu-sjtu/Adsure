import csv
import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from src import build_chunks, import_case_excel, test_retrieval, validate_cases


HEADERS = [
    "序号",
    "违法类型",
    "案例名称",
    "案号",
    "审理法院",
    "审理日期",
    "关键违法事实",
    "处罚依据",
    "处罚结果",
]


class ImportCaseExcelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel in [
            "data/imports",
            "data/structured",
            "data/structured_candidates",
            "data/structured_samples",
            "data/chunks",
            "data/reports",
            "data/analysis",
            "prompts",
        ]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        self.prompt_path = self.root / "prompts/clean_case_prompt.md"
        self.prompt_path.write_text(
            """
risk_dimensions 枚举：
- 虚假宣传
- 涉医疗宣传
- 普通食品疾病治疗功效宣传
- 保健食品违规宣传

输出 JSON schema：
""",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def make_workbook(self) -> Path:
        path = self.root / "data/imports/candidates.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws.append(["十大类违法广告行政处罚案例汇总表"])
        ws.append(["一、普通食品宣称疾病预防、治疗功能"])
        ws.append(HEADERS)
        ws.append(
            [
                1,
                "普通食品宣称疾病预防、治疗功能",
                "某县市场监督管理局与某食品公司非诉执行审查案",
                "（2020）测0101行审1号",
                "某县人民法院",
                43831,
                "在天猫店销售普通食品，宣传“降血糖”“治疗糖尿病”等疾病治疗功能。",
                "《广告法》第十七条、第五十八条",
                "罚款50000元",
            ]
        )
        ws.append([])
        ws.append(["二、保健食品功效保证、替代药物、超批准功能宣传"])
        ws.append(HEADERS)
        ws.append(
            [
                1,
                "保健食品功效保证、替代药物",
                "某市市场监督管理局与某保健食品店非诉执行审查案",
                "（2021）测0101行审2号",
                "某市人民法院",
                "2021-03-05",
                "通过会销播放视频，宣称保健食品可以“替代药物”“稳定血压”。",
                "《广告法》第十八条、第五十八条",
                "罚款30000元",
            ]
        )
        ws.append(["执法趋势分析"])
        ws.append(["此处是趋势分析，不应作为案例导入。"])
        ws.append(["合规建议"])
        ws.append(["此处是合规建议，不应作为案例导入。"])
        wb.save(path)
        return path

    def test_import_recognizes_categories_skips_analysis_and_converts_serial_date(self):
        workbook_path = self.make_workbook()

        report = import_case_excel.run(
            input_path=workbook_path,
            candidates_dir=self.root / "data/structured_candidates",
            reports_dir=self.root / "data/reports",
            analysis_dir=self.root / "data/analysis",
        )

        self.assertEqual(report["category_count"], 2)
        self.assertEqual(report["imported_count"], 2)
        self.assertGreaterEqual(report["skipped_count"], 5)
        self.assertEqual(
            report["by_violation_type"]["普通食品宣称疾病预防、治疗功能"],
            1,
        )
        cases = sorted((self.root / "data/structured_candidates").glob("*.json"))
        self.assertEqual(len(cases), 2)
        food_case = json.loads(cases[0].read_text(encoding="utf-8"))
        if food_case["industry"] != "普通食品":
            food_case = json.loads(cases[1].read_text(encoding="utf-8"))
        self.assertEqual(food_case["decision_date"], "2020-01-01")
        self.assertIsNone(food_case["source_url"])
        self.assertFalse(food_case["audit"]["approved_for_rag"])
        self.assertEqual(food_case["source_verification_status"], "pending_source_lookup")
        self.assertIn("降血糖", "".join(food_case["illegal_claims"]))
        analysis = (self.root / "data/analysis/enforcement_trends.md").read_text(encoding="utf-8")
        self.assertIn("执法趋势分析", analysis)
        self.assertIn("合规建议", analysis)
        todo_path = self.root / "data/reports/source_lookup_todo.csv"
        with todo_path.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 2)

    def test_candidates_validate_as_review_items_and_do_not_enter_production(self):
        workbook_path = self.make_workbook()
        import_case_excel.run(
            input_path=workbook_path,
            candidates_dir=self.root / "data/structured_candidates",
            reports_dir=self.root / "data/reports",
            analysis_dir=self.root / "data/analysis",
        )

        validation = validate_cases.run(
            structured_dir=self.root / "data/structured",
            structured_candidates_dir=self.root / "data/structured_candidates",
            structured_samples_dir=self.root / "data/structured_samples",
            reports_dir=self.root / "data/reports",
            prompt_path=self.prompt_path,
        )
        chunk_paths = build_chunks.run(
            structured_dir=self.root / "data/structured",
            structured_candidates_dir=self.root / "data/structured_candidates",
            structured_samples_dir=self.root / "data/structured_samples",
            chunks_dir=self.root / "data/chunks",
            reports_dir=self.root / "data/reports",
        )
        candidates = json.loads(chunk_paths["candidate"].read_text(encoding="utf-8"))
        production = json.loads(chunk_paths["production"].read_text(encoding="utf-8"))
        results = test_retrieval.search(
            query="普通食品宣传降血糖",
            chunks_path=chunk_paths["candidate"],
            top_k=1,
        )

        self.assertEqual(validation["candidate_count"], 2)
        self.assertEqual(validation["invalid_count"], 0)
        self.assertEqual(validation["needs_review_count"], 2)
        self.assertGreaterEqual(len(candidates), 4)
        self.assertEqual(production, [])
        self.assertIn("普通食品", results[0]["text"])


if __name__ == "__main__":
    unittest.main()
