# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SRC_DIR.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from jsonbase_correction_migration import load_manifest, sha256_text


MANIFEST_PATH = PROJECT_ROOT / "assets" / "jsonbase_correction_manifest_20260917.json"


class SourceRepairEvidenceTests(unittest.TestCase):
    def test_source_repairs_have_verified_traceable_text(self):
        entries = load_manifest(MANIFEST_PATH)["rules"]
        repairs = [item for item in entries if item["action"] == "source_repair"]
        self.assertEqual(9, len(repairs))
        for item in repairs:
            uid = item["rule_uid"]
            evidence = item.get("source_evidence") or {}
            self.assertEqual("verified", evidence.get("status"), uid)
            self.assertTrue(str(evidence.get("source") or "").strip(), uid)
            self.assertTrue(str(evidence.get("locator") or "").strip(), uid)
            text = str(evidence.get("restored_original_text") or "").strip()
            self.assertGreater(len(text), 20, uid)
            self.assertNotRegex(text, r"(?:\.\.\.|…)$", uid)
            self.assertEqual(sha256_text(text), evidence.get("sha256"), uid)


if __name__ == "__main__":
    unittest.main()
