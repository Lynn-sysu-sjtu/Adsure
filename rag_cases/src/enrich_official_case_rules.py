import argparse
import json
from pathlib import Path


DEFAULT_STRUCTURED_DIR = Path("data/structured")
DEFAULT_RULE_CATALOG_PATH = Path("data/rules/advertising_law_2021.json")

CASE_RULE_MAPPINGS = {
    "samr_2025_typical_ads_01": {
        "substantive": ["ADLAW-017", "ADLAW-028"],
        "liability": ["ADLAW-058-02", "ADLAW-055"],
    },
    "samr_2025_typical_ads_02": {
        "substantive": ["ADLAW-011-02", "ADLAW-017", "ADLAW-028"],
        "liability": ["ADLAW-059-02", "ADLAW-058-02", "ADLAW-055"],
    },
    "samr_2025_typical_ads_03": {
        "substantive": ["ADLAW-028"],
        "liability": ["ADLAW-055"],
    },
    "samr_2025_typical_ads_04": {
        "substantive": ["ADLAW-017"],
        "liability": ["ADLAW-058-02"],
    },
    "samr_2025_typical_ads_05": {
        "substantive": ["ADLAW-009-02", "ADLAW-009-03", "ADLAW-017", "ADLAW-028"],
        "liability": ["ADLAW-057-01", "ADLAW-058-02", "ADLAW-055"],
    },
    "samr_2025_typical_ads_06": {
        "substantive": ["ADLAW-017"],
        "liability": ["ADLAW-058-02"],
    },
    "samr_2025_typical_ads_07": {
        "substantive": ["ADLAW-026-01", "ADLAW-026-04"],
        "liability": ["ADLAW-058-08"],
    },
    "samr_2025_typical_ads_08": {
        "substantive": ["ADLAW-017", "ADLAW-046"],
        "liability": ["ADLAW-058-02", "ADLAW-058-14"],
    },
    "samr_2025_typical_ads_09": {
        "substantive": ["ADLAW-028"],
        "liability": ["ADLAW-055"],
    },
    "samr_2025_typical_ads_10": {
        "substantive": ["ADLAW-015-02"],
        "liability": ["ADLAW-057-02"],
    },
}


def load_catalog(path: Path) -> tuple[dict, dict[str, dict]]:
    catalog = json.loads(path.read_text(encoding="utf-8"))
    rules = {rule["rule_id"]: rule for rule in catalog["rules"]}
    return catalog, rules


def legal_basis_detail(
    rule_id: str,
    relation: str,
    catalog: dict,
    rules: dict[str, dict],
) -> dict:
    rule = rules[rule_id]
    return {
        "rule_id": rule_id,
        "law_name": catalog["law_name"],
        "article": rule["article"],
        "paragraph": rule["paragraph"],
        "item": rule["item"],
        "rule_type": rule["rule_type"],
        "rule_summary": rule["text"],
        "rule_text_mode": catalog["rule_text_mode"],
        "relation": relation,
        "mapping_basis": "official_summary_fact_pattern",
        "mapping_review_status": "pending_legal_review",
        "version_date": catalog["version_date"],
        "effective_status": catalog["effective_status"],
        "source_name": catalog["source_name"],
        "source_url": catalog["source_url"],
    }


def enrich_case(case: dict, catalog: dict, rules: dict[str, dict]) -> dict:
    case_id = case.get("case_id")
    mapping = CASE_RULE_MAPPINGS.get(case_id)
    if mapping is None:
        return case
    missing = [
        rule_id
        for rule_id in mapping["substantive"] + mapping["liability"]
        if rule_id not in rules
    ]
    if missing:
        raise ValueError(f"{case_id}: unknown rule IDs: {', '.join(missing)}")

    enriched = dict(case)
    enriched["mapped_rule_ids"] = mapping["substantive"]
    enriched["possible_liability_rule_ids"] = mapping["liability"]
    enriched["legal_basis_details"] = [
        legal_basis_detail(rule_id, "applicable_rule_inferred", catalog, rules)
        for rule_id in mapping["substantive"]
    ] + [
        legal_basis_detail(rule_id, "possible_liability_inferred", catalog, rules)
        for rule_id in mapping["liability"]
    ]
    enriched["legal_basis_provenance"] = {
        "case_source_text": "《中华人民共和国广告法》有关规定",
        "specific_articles_published_by_case_source": False,
        "mapping_status": "inferred_pending_legal_review",
        "warning": "具体条款为依据官方摘要事实作出的适用性映射，不代表处罚机关在决定书中明确引用。",
    }
    note = str(enriched.get("notes") or "").strip()
    mapping_note = (
        "具体条款映射为依据官方摘要事实作出的待法律复核推定，"
        "不代表处罚决定书已明确引用。"
    )
    if mapping_note not in note:
        enriched["notes"] = f"{note} {mapping_note}".strip()
    return enriched


def run(
    structured_dir: Path = DEFAULT_STRUCTURED_DIR,
    rule_catalog_path: Path = DEFAULT_RULE_CATALOG_PATH,
) -> list[Path]:
    catalog, rules = load_catalog(rule_catalog_path)
    outputs = []
    for path in sorted(structured_dir.glob("samr_2025_typical_ads_*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        enriched = enrich_case(case, catalog, rules)
        path.write_text(
            json.dumps(enriched, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        outputs.append(path)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Attach reviewable Advertising Law mappings to verified SAMR cases."
    )
    parser.add_argument(
        "--structured-dir",
        type=Path,
        default=DEFAULT_STRUCTURED_DIR,
    )
    parser.add_argument(
        "--rule-catalog",
        type=Path,
        default=DEFAULT_RULE_CATALOG_PATH,
    )
    args = parser.parse_args()
    outputs = run(args.structured_dir, args.rule_catalog)
    print(json.dumps([str(path) for path in outputs], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
