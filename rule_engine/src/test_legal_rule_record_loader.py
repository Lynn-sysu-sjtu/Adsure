# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

from legal_rule_record_loader import load_all_rule_records


class LegalRuleRecordLoaderTests(unittest.TestCase):
    def test_loads_root_rules_as_general_and_track_rules_by_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "通用.json").write_text(json.dumps({"rules": [{"rule_uid": "GEN-1"}]}, ensure_ascii=False), encoding="utf-8")
            folder = root / "游戏"; folder.mkdir(); (folder / "游戏.json").write_text(json.dumps({"rules": [{"rule_uid": "GAME-1"}]}, ensure_ascii=False), encoding="utf-8")
            records = load_all_rule_records(root)
            self.assertEqual({"通用", "游戏"}, {item["track"] for item in records})

    def test_rejects_duplicate_rule_uid_across_general_and_track_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "通用.json").write_text('{"rules":[{"rule_uid":"R1"}]}', encoding="utf-8")
            folder = root / "美妆"; folder.mkdir(); (folder / "美妆.json").write_text('{"rules":[{"rule_uid":"R1"}]}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate rule_uid"):
                load_all_rule_records(root)


if __name__ == "__main__": unittest.main()
