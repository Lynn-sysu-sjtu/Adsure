import json
import tempfile
import unittest
from pathlib import Path

from docx import Document

from src import import_case_library_docx


class ImportCaseLibraryDocxTests(unittest.TestCase):
    def test_import_is_idempotent_and_archives_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "游戏广告合规案例库.docx"
            doc = Document()
            for line in [
                "游戏广告合规案例库",
                "案例1：某游戏公司虚假广告案",
                "案号：（2023）粤0192民初1448号（关联民事判决）",
                "审理法院：广州互联网法院",
                "审理日期：2023年4月12日",
                "基本事实：抖音游戏广告宣传充值奖励，实际为随机抽取。",
                "违反条款：《广告法》第八条第一款",
                "处罚结果：罚款20000元。",
                "裁判要点：游戏奖励机制应准确说明。",
            ]:
                doc.add_paragraph(line)
            doc.save(source)

            candidates = root / "candidates"
            raw = root / "raw"
            report_path = root / "report.json"
            first = import_case_library_docx.run([source], candidates, raw, report_path)
            second = import_case_library_docx.run([source], candidates, raw, report_path)

            self.assertEqual(first["new_cases_created_this_run"], 1)
            self.assertEqual(second["new_cases_created_this_run"], 0)
            self.assertEqual(len(list(candidates.glob("*.json"))), 1)
            case = json.loads(next(candidates.glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(case["case_number"], "（2023）粤0192民初1448号")
            self.assertEqual(case["penalty_amount"], 20000)
            self.assertFalse(case["approved_for_rag"])
            self.assertTrue((root / case["raw_text_path"]).exists() if not Path(case["raw_text_path"]).is_absolute() else Path(case["raw_text_path"]).exists())
            self.assertEqual(len(case["source_documents"]), 1)


if __name__ == "__main__":
    unittest.main()
