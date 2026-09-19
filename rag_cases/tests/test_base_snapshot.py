import base64
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from src.base_snapshot import extract_field_schema


class BaseSnapshotTests(unittest.TestCase):
    def test_extracts_fields_without_copying_records(self):
        snapshot_payload = [
            {
                "schema": {
                    "tableMap": {"tbl_test": {"name": "数据表"}},
                    "data": {
                        "table": {
                            "meta": {"id": "tbl_test"},
                            "primaryKey": "fld_auto",
                            "fieldMap": {
                                "fld_auto": {
                                    "name": "自动编号",
                                    "type": 1005,
                                    "fieldUIType": "AutoNumber",
                                },
                                "fld_status": {
                                    "name": "状态",
                                    "type": 3,
                                    "fieldUIType": "SingleSelect",
                                    "property": {
                                        "options": [
                                            {"id": "opt_1", "name": "运营起草"}
                                        ]
                                    },
                                },
                            },
                        },
                        "recordMap": {
                            "rec_private": {
                                "fld_status": {"value": "opt_1"}
                            }
                        },
                    },
                }
            }
        ]
        envelope = {
            "gzipSnapshot": base64.b64encode(
                gzip.compress(
                    json.dumps(snapshot_payload).encode("utf-8")
                )
            ).decode("ascii")
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.base"
            path.write_text(json.dumps(envelope), encoding="utf-8")
            extracted = extract_field_schema(path)

        self.assertEqual(extracted["table_id"], "tbl_test")
        self.assertEqual(extracted["field_count"], 2)
        self.assertEqual(extracted["primary_key_field_name"], "自动编号")
        self.assertFalse(
            next(
                field
                for field in extracted["fields"]
                if field["name"] == "自动编号"
            )["writable"]
        )
        self.assertNotIn("recordMap", extracted)
        self.assertNotIn("rec_private", json.dumps(extracted))


if __name__ == "__main__":
    unittest.main()
