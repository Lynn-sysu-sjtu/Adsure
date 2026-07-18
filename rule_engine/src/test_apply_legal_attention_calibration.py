import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from apply_legal_attention_calibration import apply_confirmed_routes


class ApplyLegalAttentionCalibrationTests(unittest.TestCase):
    def test_applies_only_confirmed_high_route_changes_and_syncs_legacy_route(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            rule_file = base / "rules.json"
            rule_file.write_text(
                json.dumps(
                    {
                        "rules": [
                            {
                                "rule_id": "RULE-001",
                                "routing": {"default_route": "legal_review_required"},
                                "legal_attention": {
                                    "default_route": "legal_review_required",
                                    "route_reason": "old reason",
                                },
                            },
                            {
                                "rule_id": "RULE-002",
                                "routing": {"default_route": "legal_review_required"},
                                "legal_attention": {"default_route": "legal_review_required"},
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            csv_path = base / "calibration.csv"
            with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=[
                        "rule_id",
                        "source_file",
                        "review_priority",
                        "route_changed",
                        "recommended_route",
                        "reason",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "rule_id": "RULE-001",
                        "source_file": str(rule_file),
                        "review_priority": "high",
                        "route_changed": "True",
                        "recommended_route": "operator_supply_docs",
                        "reason": "accepted reason",
                    }
                )
                writer.writerow(
                    {
                        "rule_id": "RULE-002",
                        "source_file": str(rule_file),
                        "review_priority": "medium",
                        "route_changed": "True",
                        "recommended_route": "operator_supply_docs",
                        "reason": "not accepted by filter",
                    }
                )

            summary = apply_confirmed_routes(csv_path, accepted_priority="high")

            data = json.loads(rule_file.read_text(encoding="utf-8"))
            first = data["rules"][0]
            second = data["rules"][1]
            self.assertEqual("operator_supply_docs", first["legal_attention"]["default_route"])
            self.assertEqual("operator_supply_docs", first["routing"]["default_route"])
            self.assertEqual("human_confirmed", first["legal_attention"]["calibration_status"])
            self.assertIn("accepted reason", first["legal_attention"]["route_reason"])
            self.assertEqual("legal_review_required", second["legal_attention"]["default_route"])
            self.assertEqual(1, summary["updated_rules"])
            self.assertEqual(1, summary["skipped_rows"])


    def test_uses_title_to_disambiguate_duplicate_rule_ids(self):
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            rule_file = base / "rules.json"
            rule_file.write_text(
                json.dumps(
                    {
                        "rules": [
                            {
                                "rule_id": "DUP-001",
                                "title": "first title",
                                "legal_attention": {"default_route": "legal_review_required"},
                            },
                            {
                                "rule_id": "DUP-001",
                                "title": "second title",
                                "legal_attention": {"default_route": "legal_review_required"},
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            csv_path = base / "calibration.csv"
            with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=["rule_id", "title", "source_file", "review_priority", "route_changed", "recommended_route"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "rule_id": "DUP-001",
                        "title": "second title",
                        "source_file": str(rule_file),
                        "review_priority": "high",
                        "route_changed": "true",
                        "recommended_route": "operator_supply_docs",
                    }
                )

            summary = apply_confirmed_routes(csv_path, accepted_priority="high")

            data = json.loads(rule_file.read_text(encoding="utf-8"))
            self.assertEqual("legal_review_required", data["rules"][0]["legal_attention"]["default_route"])
            self.assertEqual("operator_supply_docs", data["rules"][1]["legal_attention"]["default_route"])
            self.assertEqual(1, summary["updated_rules"])
            self.assertEqual(0, summary["error_count"])

if __name__ == "__main__":
    unittest.main()