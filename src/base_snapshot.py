#!/usr/bin/env python3
"""Read a local Feishu Base snapshot without uploading or exposing records."""

from __future__ import annotations

import argparse
import base64
import gzip
import json
from pathlib import Path
from typing import Any


READ_ONLY_UI_TYPES = {
    "AutoNumber",
    "CreatedTime",
    "CreatedUser",
    "Formula",
    "Lookup",
    "ModifiedTime",
    "ModifiedUser",
}


def decode_snapshot(path: Path) -> dict[str, Any]:
    envelope = json.loads(path.read_text(encoding="utf-8"))
    encoded = envelope.get("gzipSnapshot")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("Base snapshot missing gzipSnapshot")
    decoded = gzip.decompress(base64.b64decode(encoded))
    snapshots = json.loads(decoded.decode("utf-8"))
    if not isinstance(snapshots, list) or not snapshots:
        raise ValueError("Base snapshot payload must be a non-empty array")
    schema = snapshots[0].get("schema")
    if not isinstance(schema, dict):
        raise ValueError("Base snapshot schema missing")
    return schema


def extract_field_schema(path: Path) -> dict[str, Any]:
    schema = decode_snapshot(path)
    data = schema.get("data") or {}
    table = data.get("table") or {}
    table_meta = table.get("meta") or {}
    table_id = str(table_meta.get("id") or "")
    table_map = schema.get("tableMap") or {}
    table_name = str((table_map.get(table_id) or {}).get("name") or "")
    field_map = table.get("fieldMap") or {}
    if not table_id or not isinstance(field_map, dict):
        raise ValueError("Base snapshot table metadata incomplete")

    fields = []
    for field_id, field in field_map.items():
        if not isinstance(field, dict):
            continue
        ui_type = str(field.get("fieldUIType") or "")
        options = [
            {
                "id": str(option.get("id") or ""),
                "name": str(option.get("name") or ""),
            }
            for option in (field.get("property") or {}).get("options", [])
            if isinstance(option, dict) and option.get("name")
        ]
        fields.append(
            {
                "field_id": str(field_id),
                "name": str(field.get("name") or ""),
                "type": int(field.get("type") or 0),
                "ui_type": ui_type,
                "is_primary": bool(field.get("isPrimary")),
                "writable": (
                    ui_type not in READ_ONLY_UI_TYPES
                    and ui_type != "Attachment"
                ),
                "options": options,
            }
        )

    primary_key = str(table.get("primaryKey") or "")
    return {
        "schema_id": "ads_review_base_v4",
        "source_snapshot_name": path.name,
        "table_id": table_id,
        "table_name": table_name,
        "field_count": len(fields),
        "primary_key_field_id": primary_key,
        "primary_key_field_name": next(
            (
                field["name"]
                for field in fields
                if field["field_id"] == primary_key
            ),
            "",
        ),
        "fields": sorted(fields, key=lambda field: field["name"]),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/schemas/ads_review_base_v4_fields.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = extract_field_schema(args.snapshot)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Extracted {payload['field_count']} fields from "
        f"{payload['source_snapshot_name']}: {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
