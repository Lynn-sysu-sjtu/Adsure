# -*- coding: utf-8 -*-
"""Helpers for loading and saving rule JSON files used by app_kg.py."""

import copy
import json
from pathlib import Path


INTERNAL_SOURCE_FILE = "_source_file"
JSONBASE_DIR_NAME = "jsonbase"


def _read_json(path):
    with open(path, "r", encoding="utf-8-sig") as fp:
        return json.load(fp)


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
        fp.write("\n")



def _source_index(legal_sources):
    index = {}
    for source in legal_sources or []:
        if not isinstance(source, dict):
            continue
        source_id = source.get("id") or source.get("source_id")
        if source_id:
            index[source_id] = source
    return index


def _enrich_legal_basis(rule, source_by_id):
    for basis in rule.get("legal_basis", []) or []:
        if not isinstance(basis, dict):
            continue
        source_id = basis.get("source_id") or basis.get("source")
        source = source_by_id.get(source_id)
        if not source:
            continue
        basis.setdefault("source_name", source.get("name"))
        basis.setdefault("source_type", source.get("type"))
        if basis.get("legal_level") is None and source.get("legal_level") is not None:
            basis["legal_level"] = source.get("legal_level")

def _clean_rule(rule):
    clean = copy.deepcopy(rule)
    clean.pop(INTERNAL_SOURCE_FILE, None)
    return clean


def load_rule_library(base_dir, validate_assets=False):
    """Load and merge every JSON rule file in base_dir/jsonbase."""
    base_dir = Path(base_dir)
    jsonbase_dir = base_dir / JSONBASE_DIR_NAME
    json_files = sorted(p for p in jsonbase_dir.rglob("*.json") if p.is_file())
    if not json_files:
        raise FileNotFoundError(f"No .json rule files found in {jsonbase_dir}")

    documents = {}
    rules = []
    legal_sources = []
    source_ids = set()
    memory_rules = []
    review_workflow = None

    for path in json_files:
        doc = _read_json(path)
        source_name = path.relative_to(jsonbase_dir).as_posix()
        documents[source_name] = doc

        for source in doc.get("legal_sources", []):
            source_id = source.get("id")
            if source_id not in source_ids:
                legal_sources.append(source)
                source_ids.add(source_id)

        source_by_id = _source_index(doc.get("legal_sources", []))
        for rule in doc.get("rules", []):
            _enrich_legal_basis(rule, source_by_id)
            rule[INTERNAL_SOURCE_FILE] = source_name
            rules.append(rule)

        memory_rules.extend(doc.get("memory_rules", []))
        if review_workflow is None and doc.get("review_workflow"):
            review_workflow = doc.get("review_workflow")

    data = {
        "meta": {
            "name": "瀹″績澶氭枃浠惰鍒欏簱",
            "source_dir": str(jsonbase_dir),
            "source_files": [p.relative_to(jsonbase_dir).as_posix() for p in json_files],
            "rule_count": len(rules),
        },
        "legal_sources": legal_sources,
        "rules": rules,
        "memory_rules": memory_rules,
        "review_workflow": review_workflow or {},
    }

    if validate_assets:
        from rule_asset_validator import assert_valid_rule_assets, validate_rule_assets

        assert_valid_rule_assets(validate_rule_assets(rules))

    return {
        "base_dir": base_dir,
        "jsonbase_dir": jsonbase_dir,
        "json_files": json_files,
        "documents": documents,
        "data": data,
    }


def save_rule_library(library):
    """Save merged in-memory rules back to their original JSON files."""
    jsonbase_dir = Path(library["jsonbase_dir"])
    documents = library["documents"]
    rules = library["data"].get("rules", [])
    default_file = next(iter(documents), None)
    if default_file is None:
        raise FileNotFoundError(f"No writable source JSON files found in {jsonbase_dir}")

    grouped_rules = {filename: [] for filename in documents}
    for rule in rules:
        filename = rule.get(INTERNAL_SOURCE_FILE) or default_file
        if filename not in grouped_rules:
            grouped_rules[filename] = []
            documents[filename] = {
                "meta": {"name": filename},
                "legal_sources": [],
                "rules": [],
                "memory_rules": [],
                "review_workflow": {},
            }
        grouped_rules[filename].append(_clean_rule(rule))

    for filename, doc in documents.items():
        doc["rules"] = grouped_rules.get(filename, [])
        output_path = jsonbase_dir / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(output_path, doc)

