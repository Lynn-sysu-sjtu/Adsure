# -*- coding: utf-8 -*-
"""Run the 30-case health-food, beauty, and game baseline datasets.

The report keeps the complete request, reference answer, engine response, and
comparison details so it can be used as a before/after jsonbase baseline.
"""

import argparse
import csv
import hashlib
import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from audit_api import audit_endpoint


PROJECT_BASE = Path(__file__).resolve().parents[1]
WORKSPACE_BASE = PROJECT_BASE.parents[1]
DEFAULT_DATASET_DIR = WORKSPACE_BASE / "测试集"
DEFAULT_OUTPUT_DIR = PROJECT_BASE / "test_reports" / "three_dataset_baseline"
RISK_KEYS = ["审核_推荐风险等级", "瀹℃牳_鎺ㄨ崘椋庨櫓绛夌骇"]
DIMENSION_KEYS = ["审核_推荐违规类型", "瀹℃牳_鎺ㄨ崘杩濊绫诲瀷"]
DEFAULT_UID_BINDINGS = PROJECT_BASE / "assets" / "json_test_uid_bindings_20260917.json"
DEFAULT_GAME_UID_MAPPING = PROJECT_BASE / "assets" / "game_test_expected_rule_mapping_20260917.json"


def _first_value(data, keys, default=None):
    for key in keys:
        if key in data:
            return data[key]
    return default


def normalize_risk_level(value):
    text = str(value or "").strip()
    for level in ("高", "中", "低"):
        if text.startswith(level):
            return level
    return text or None


def split_expected_dimensions(value):
    if not value:
        return []
    text = str(value).replace("；", ";").replace("、", ";")
    return [item.strip() for item in text.split(";") if item.strip()]


def _rule_ids(items):
    return sorted({item.get("rule_id") for item in (items or []) if item.get("rule_id")})


def _rule_uids(items):
    return sorted({item.get('rule_uid') for item in (items or []) if item.get('rule_uid')})


def compare_json_case(case, response, diagnostics):
    uid_expected = case.get('expected', {}) or {}
    uid_data = response.get('data', {}) or {}
    candidate_uids = sorted(set(
        diagnostics.get('candidate_rule_uids') or _rule_uids(uid_data.get('matched_rules'))
    ))
    final_uids = _rule_uids(uid_data.get('matched_rules'))
    required_uids = set(uid_expected.get('must_recall_rule_uids') or [])
    forbidden_uids = set(uid_expected.get('must_not_recall_rule_uids') or [])
    candidate_uid_set = set(candidate_uids)
    final_uid_set = set(final_uids)
    expected = case.get("expected", {}) or {}
    data = response.get("data", {}) or {}
    candidate_ids = sorted(set(diagnostics.get("candidate_rule_ids") or _rule_ids(data.get("matched_rules"))))
    final_ids = _rule_ids(data.get("matched_rules"))
    required = set(expected.get("must_recall_rule_ids") or [])
    forbidden = set(expected.get("must_not_recall_rule_ids") or [])
    candidate_set = set(candidate_ids)
    final_set = set(final_ids)
    expected_routing = expected.get("expected_routing")
    actual_routing = data.get("routing")
    uid_contract_present = (
        'must_recall_rule_uids' in uid_expected or 'must_not_recall_rule_uids' in uid_expected
    )
    primary_identity = 'rule_uid' if uid_contract_present else 'rule_id'
    primary_required = required_uids if primary_identity == 'rule_uid' else required
    primary_candidate = candidate_uid_set if primary_identity == 'rule_uid' else candidate_set
    primary_final = final_uid_set if primary_identity == 'rule_uid' else final_set
    return {
        'primary_rule_identity': primary_identity,
        'expected_rule_recall_scorable': bool(primary_required),
        'required_candidate_primary_recall_match': primary_required.issubset(primary_candidate),
        'required_final_primary_recall_match': primary_required.issubset(primary_final),
        'required_candidate_uid_recall_match': required_uids.issubset(candidate_uid_set),
        'missing_required_candidate_rule_uids': sorted(required_uids - candidate_uid_set),
        'required_final_uid_recall_match': required_uids.issubset(final_uid_set),
        'missing_required_final_rule_uids': sorted(required_uids - final_uid_set),
        'forbidden_candidate_uid_recall_match': forbidden_uids.isdisjoint(candidate_uid_set),
        'unexpected_forbidden_candidate_rule_uids': sorted(forbidden_uids & candidate_uid_set),
        'forbidden_final_uid_recall_match': forbidden_uids.isdisjoint(final_uid_set),
        'unexpected_forbidden_final_rule_uids': sorted(forbidden_uids & final_uid_set),
        'candidate_rule_uids': candidate_uids,
        'final_rule_uids': final_uids,
        "response_ok": response.get("code") == 0,
        "required_candidate_recall_match": required.issubset(candidate_set),
        "missing_required_candidate_rule_ids": sorted(required - candidate_set),
        "required_final_recall_match": required.issubset(final_set),
        "missing_required_final_rule_ids": sorted(required - final_set),
        "forbidden_candidate_recall_match": forbidden.isdisjoint(candidate_set),
        "unexpected_forbidden_candidate_rule_ids": sorted(forbidden & candidate_set),
        "forbidden_final_recall_match": forbidden.isdisjoint(final_set),
        "unexpected_forbidden_final_rule_ids": sorted(forbidden & final_set),
        "routing_match": actual_routing == expected_routing,
        "expected_routing": expected_routing,
        "actual_routing": actual_routing,
        "expected_judgment": expected.get("expected_judgment"),
        "actual_risk_level": _first_value(data, RISK_KEYS),
        "actual_audit_opinion": data.get("审核_审核意见"),
        "candidate_rule_ids": candidate_ids,
        "final_rule_ids": final_ids,
    }


def compare_game_case(case, response, diagnostics):
    expected = case.get("expected", {}) or {}
    data = response.get("data", {}) or {}
    expected_dimensions = expected.get("expected_dimensions") or []
    actual_dimensions = _first_value(data, DIMENSION_KEYS, []) or []
    if not isinstance(actual_dimensions, list):
        actual_dimensions = [actual_dimensions]
    expected_set = set(expected_dimensions)
    actual_set = set(actual_dimensions)
    expected_risk = normalize_risk_level(expected.get("expected_risk_level"))
    actual_risk = normalize_risk_level(_first_value(data, RISK_KEYS))
    return {
        "response_ok": response.get("code") == 0,
        "risk_match": actual_risk == expected_risk,
        "expected_risk_level_normalized": expected_risk,
        "actual_risk_level_normalized": actual_risk,
        "dimension_match": expected_set.issubset(actual_set),
        "missing_expected_dimensions": sorted(expected_set - actual_set),
        "unexpected_actual_dimensions": sorted(actual_set - expected_set),
        "expected_dimensions": sorted(expected_set),
        "actual_dimensions": sorted(actual_set),
        "candidate_rule_ids": sorted(set(diagnostics.get("candidate_rule_ids") or [])),
        "final_rule_ids": _rule_ids(data.get("matched_rules")),
        "actual_routing": data.get("routing"),
        "actual_audit_opinion": data.get("审核_审核意见"),
    }


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_dataset(path, dataset_name):
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    cases = []
    for source_case in document.get("cases", []):
        case = dict(source_case)
        case["dataset"] = dataset_name
        case["source_kind"] = "json"
        case["source_file"] = path.name
        cases.append(case)
    return cases


def _load_game_dataset(path):
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("openpyxl is required to read the game XLSX dataset") from exc

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.active
    rows = list(sheet.values)
    headers = list(rows[0])
    cases = []
    for row in rows[1:]:
        values = dict(zip(headers, row))
        case_id = values["评测编号"]
        fields = {
            "①运营·行业领域": "游戏",
            "①运营·紧急程度": "普通",
        }
        for header in headers[1:9]:
            fields[header] = values.get(header)
        cases.append(
            {
                "case_id": case_id,
                "name": values.get("标准答案·核心违规判定") or case_id,
                "dataset": "游戏",
                "source_kind": "xlsx",
                "source_file": path.name,
                "input_payload": {
                    "record_id": "rec_" + str(case_id).lower().replace("-", "_"),
                    "mode": "标准",
                    "fields": fields,
                },
                "expected": {
                    "expected_risk_level": values.get("标准答案·风险等级"),
                    "expected_core_judgment": values.get("标准答案·核心违规判定"),
                    "expected_dimensions": split_expected_dimensions(values.get("标准答案·违规类型")),
                    "expected_high_risk_words": values.get("标准答案·高风险词"),
                    "expected_legal_basis": values.get("标准答案·预期引用法条"),
                    "expected_recommendation": values.get("标准答案·修改建议"),
                    "violation_nature": values.get("备注·违规性质"),
                },
            }
        )
    return cases


def load_cases(dataset_dir):
    dataset_dir = Path(dataset_dir)
    health_path = dataset_dir / "20260906保健食品测试样例集.json"
    beauty_path = dataset_dir / "20260908美妆测试样例集.json"
    game_path = dataset_dir / "20260911游戏测试样例集.json"
    source_paths = [health_path, beauty_path, game_path]
    cases = []
    cases.extend(_load_json_dataset(health_path, "保健食品"))
    cases.extend(_load_json_dataset(beauty_path, "美妆"))
    cases.extend(_load_json_dataset(game_path, "游戏"))
    sources = [
        {"file": path.name, "path": str(path.resolve()), "sha256": _sha256(path)}
        for path in source_paths
    ]
    return cases, sources


def load_normalized_cases(path):
    path = Path(path)
    cases = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(cases, list):
        raise ValueError('Normalized case file must contain a JSON list.')
    origins = (
        ('HF-AD-', '保健食品', 'json', '20260906保健食品测试样例集.json'),
        ('BEAUTY-AD-', '美妆', 'json', '20260908美妆测试样例集.json'),
        ('EVAL-GAME-', '游戏', 'json', '20260911游戏测试样例集.json'),
    )
    normalized = []
    for source_case in cases:
        case = dict(source_case)
        if not all(case.get(key) for key in ('dataset', 'source_kind', 'source_file')):
            match = next((origin for origin in origins if str(case.get('case_id', '')).startswith(origin[0])), None)
            if match is None:
                raise ValueError(f"Cannot infer frozen case origin: {case.get('case_id')}")
            _, dataset, source_kind, source_file = match
            case.setdefault('dataset', dataset)
            case.setdefault('source_kind', source_kind)
            case.setdefault('source_file', source_file)
        normalized.append(case)
    return normalized, [{
        'file': path.name,
        'path': str(path.resolve()),
        'sha256': _sha256(path),
        'kind': 'frozen_normalized_cases',
    }]


def build_limitations(semantic_backend):
    limitations = []
    if semantic_backend == 'local':
        limitations.append('Semantic recall uses the deterministic local similarity backend, not Zhipu embeddings.')
    else:
        limitations.append('Semantic recall uses the rebuilt Zhipu embedding-3 rule index and live Zhipu query embeddings.')
    limitations.extend([
        'JSON reference answers do not define expected risk levels, so judgment text is preserved but not auto-scored.',
        'Game reference legal provisions are free text and are preserved for review rather than auto-scored against rule IDs.',
    ])
    return limitations


def load_uid_bindings(bindings_path=DEFAULT_UID_BINDINGS, game_mapping_path=DEFAULT_GAME_UID_MAPPING):
    """Load the corrected UID expectations for the three datasets."""
    bindings_path = Path(bindings_path)
    game_mapping_path = Path(game_mapping_path)
    bindings = json.loads(bindings_path.read_text(encoding="utf-8-sig"))
    game_mapping = json.loads(game_mapping_path.read_text(encoding="utf-8-sig"))
    result = {}

    for case_id, payload in bindings.items():
        must_recall = []
        must_not_recall = []
        statuses = {}
        for rule_id, info in (payload.get("must_recall") or {}).items():
            status = info.get("status")
            uid = info.get("uid")
            statuses[rule_id] = {"status": status, "uid": uid, "reason": info.get("reason")}
            if uid and status in {"resolved", "replace_expected_rule"}:
                must_recall.append(uid)
        for rule_id, info in (payload.get("must_not_recall") or {}).items():
            uid = info.get("uid")
            if uid:
                must_not_recall.append(uid)
        result[case_id] = {
            "must_recall_rule_uids": sorted(set(must_recall)),
            "must_not_recall_rule_uids": sorted(set(must_not_recall)),
            "binding_source": str(bindings_path),
            "binding_status": statuses,
        }

    for case in game_mapping.get("cases", []) or []:
        case_id = case.get("case_id")
        if not case_id:
            continue
        must_recall = [item.get("rule_uid") for item in (case.get("must_recall_rules") or []) if item.get("rule_uid")]
        must_not_recall = [item.get("rule_uid") for item in (case.get("must_not_recall_rules") or []) if item.get("rule_uid")]
        result[case_id] = {
            "must_recall_rule_uids": sorted(set(must_recall)),
            "must_not_recall_rule_uids": sorted(set(must_not_recall)),
            "binding_source": str(game_mapping_path),
            "binding_status": {
                item.get("rule_id"): {
                    "status": "game_expected",
                    "uid": item.get("rule_uid"),
                    "reason": item.get("application"),
                }
                for item in (case.get("must_recall_rules") or [])
            },
        }
    return result


def apply_uid_bindings(cases, bindings_path=DEFAULT_UID_BINDINGS, game_mapping_path=DEFAULT_GAME_UID_MAPPING):
    """Overlay corrected UID expectations onto the frozen JSON cases."""
    bindings = load_uid_bindings(bindings_path, game_mapping_path)
    applied = 0
    for case in cases:
        binding = bindings.get(case.get("case_id"))
        if not binding:
            continue
        expected = case.setdefault("expected", {})
        expected["must_recall_rule_uids"] = binding["must_recall_rule_uids"]
        expected["must_not_recall_rule_uids"] = binding["must_not_recall_rule_uids"]
        expected["uid_binding_source"] = binding["binding_source"]
        expected["uid_binding_status"] = binding["binding_status"]
        applied += 1
    return applied


def _summarize(results):
    by_dataset = defaultdict(list)
    for item in results:
        by_dataset[item["dataset"]].append(item)

    def summarize_group(items):
        counter = Counter()
        for item in items:
            comparison = item["comparison"]
            counter["response_ok"] += bool(comparison.get("response_ok"))
            if item["source_kind"] == "json":
                if comparison.get('expected_rule_recall_scorable'):
                    counter['expected_rule_recall_scorable'] += 1
                    counter['required_candidate_primary_recall_match'] += bool(comparison.get('required_candidate_primary_recall_match'))
                    counter['required_final_primary_recall_match'] += bool(comparison.get('required_final_primary_recall_match'))
                if comparison.get('primary_rule_identity') == 'rule_uid' and comparison.get('expected_rule_recall_scorable'):
                    counter["required_candidate_uid_recall_match"] += bool(comparison.get("required_candidate_uid_recall_match"))
                    counter["required_final_uid_recall_match"] += bool(comparison.get("required_final_uid_recall_match"))
                counter["forbidden_candidate_uid_recall_match"] += bool(comparison.get("forbidden_candidate_uid_recall_match"))
                expected_uids = set(item.get("expected", {}).get("must_recall_rule_uids") or [])
                candidate_uids = set(comparison.get("candidate_rule_uids") or [])
                final_uids = set(comparison.get("final_rule_uids") or [])
                counter["expected_uid_slots"] += len(expected_uids)
                counter["candidate_uid_hits"] += len(expected_uids & candidate_uids)
                counter["final_uid_hits"] += len(expected_uids & final_uids)
                counter["required_candidate_recall_match"] += bool(comparison.get("required_candidate_recall_match"))
                counter["required_final_recall_match"] += bool(comparison.get("required_final_recall_match"))
                counter["forbidden_candidate_recall_match"] += bool(comparison.get("forbidden_candidate_recall_match"))
                counter["routing_match"] += bool(comparison.get("routing_match"))
            else:
                counter["risk_match"] += bool(comparison.get("risk_match"))
                counter["dimension_match"] += bool(comparison.get("dimension_match"))
        return {"case_count": len(items), **dict(counter)}

    def with_uid_rates(summary):
        expected = summary.get("expected_uid_slots", 0)
        if expected:
            summary["candidate_uid_recall"] = round(summary["candidate_uid_hits"] / expected, 4)
            summary["final_uid_recall"] = round(summary["final_uid_hits"] / expected, 4)
        else:
            summary["candidate_uid_recall"] = 0.0
            summary["final_uid_recall"] = 0.0
        return summary

    all_summary = with_uid_rates(summarize_group(results))
    return {
        "all": all_summary,
        "by_dataset": {name: with_uid_rates(summarize_group(items)) for name, items in by_dataset.items()},
    }


def run_baseline(cases, sources, baseline_name, llm_backend, semantic_backend):
    os.environ["ADSURE_LLM_BACKEND"] = llm_backend
    os.environ["ADSURE_LLM_MODE"] = "strict"
    os.environ["ADSURE_SEMANTIC_BACKEND"] = semantic_backend
    os.environ["ADSURE_CATALOG_RECALL_ENABLED"] = "false"
    results = []
    for index, case in enumerate(cases, start=1):
        diagnostics = {}
        start = time.perf_counter()
        try:
            response = audit_endpoint(case["input_payload"], base_dir=PROJECT_BASE, diagnostics=diagnostics)
        except Exception as exc:
            response = {"code": -1, "msg": f"{type(exc).__name__}: {exc}", "data": None}
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        comparison = compare_json_case(case, response, diagnostics)
        results.append(
            {
                "sequence": index,
                "case_id": case["case_id"],
                "name": case.get("name"),
                "dataset": case["dataset"],
                "source_kind": case["source_kind"],
                "source_file": case["source_file"],
                "elapsed_ms": elapsed_ms,
                "input_payload": case["input_payload"],
                "expected": case.get("expected", {}),
                "comparison": comparison,
                "diagnostics": diagnostics,
                "actual_response": response,
            }
        )
        print(f"[{index:02d}/{len(cases)}] {case['case_id']} code={response.get('code')} elapsed_ms={elapsed_ms}", flush=True)

    return {
        "baseline_name": baseline_name,
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "engine_base_dir": str(PROJECT_BASE),
        "config": {
            "ADSURE_LLM_BACKEND": llm_backend,
            "ADSURE_LLM_MODE": "strict",
            "ADSURE_SEMANTIC_BACKEND": semantic_backend,
            "ADSURE_CATALOG_RECALL_ENABLED": "false",
            "DEEPSEEK_MODEL": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        },
        "limitations": build_limitations(semantic_backend),
        "sources": sources,
        "summary": _summarize(results),
        "cases": results,
    }


def save_report(report, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"{stamp}_{report['baseline_name']}"
    json_path = output_dir / f"{stem}.json"
    csv_path = output_dir / f"{stem}_comparison.csv"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "case_id", "dataset", "response_ok", "elapsed_ms", "expected_routing", "actual_routing",
            "routing_match", "primary_rule_identity", "expected_rule_recall_scorable",
            "required_candidate_primary_recall_match", "required_final_primary_recall_match",
            "required_candidate_uid_recall_match", "missing_required_candidate_rule_uids",
            "required_final_uid_recall_match", "missing_required_final_rule_uids",
            "forbidden_candidate_uid_recall_match", "unexpected_forbidden_candidate_rule_uids",
            "required_candidate_recall_match", "missing_required_candidate_rule_ids",
            "forbidden_candidate_recall_match", "unexpected_forbidden_candidate_rule_ids",
            "expected_risk", "actual_risk", "risk_match", "dimension_match", "missing_expected_dimensions",
            "candidate_rule_uids", "final_rule_uids", "candidate_rule_ids", "final_rule_ids", "error",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in report["cases"]:
            comparison = item["comparison"]
            writer.writerow(
                {
                    "case_id": item["case_id"],
                    "dataset": item["dataset"],
                    "response_ok": comparison.get("response_ok"),
                    "elapsed_ms": item["elapsed_ms"],
                    "expected_routing": comparison.get("expected_routing"),
                    "actual_routing": comparison.get("actual_routing"),
                    "routing_match": comparison.get("routing_match"),
                    "primary_rule_identity": comparison.get("primary_rule_identity"),
                    "expected_rule_recall_scorable": comparison.get("expected_rule_recall_scorable"),
                    "required_candidate_primary_recall_match": comparison.get("required_candidate_primary_recall_match"),
                    "required_final_primary_recall_match": comparison.get("required_final_primary_recall_match"),
                    "required_candidate_uid_recall_match": comparison.get("required_candidate_uid_recall_match"),
                    "missing_required_candidate_rule_uids": " | ".join(comparison.get("missing_required_candidate_rule_uids") or []),
                    "required_final_uid_recall_match": comparison.get("required_final_uid_recall_match"),
                    "missing_required_final_rule_uids": " | ".join(comparison.get("missing_required_final_rule_uids") or []),
                    "forbidden_candidate_uid_recall_match": comparison.get("forbidden_candidate_uid_recall_match"),
                    "unexpected_forbidden_candidate_rule_uids": " | ".join(comparison.get("unexpected_forbidden_candidate_rule_uids") or []),
                    "required_candidate_recall_match": comparison.get("required_candidate_recall_match"),
                    "missing_required_candidate_rule_ids": " | ".join(comparison.get("missing_required_candidate_rule_ids") or []),
                    "forbidden_candidate_recall_match": comparison.get("forbidden_candidate_recall_match"),
                    "unexpected_forbidden_candidate_rule_ids": " | ".join(comparison.get("unexpected_forbidden_candidate_rule_ids") or []),
                    "expected_risk": comparison.get("expected_risk_level_normalized"),
                    "actual_risk": comparison.get("actual_risk_level_normalized") or comparison.get("actual_risk_level"),
                    "risk_match": comparison.get("risk_match"),
                    "dimension_match": comparison.get("dimension_match"),
                    "missing_expected_dimensions": " | ".join(comparison.get("missing_expected_dimensions") or []),
                    "candidate_rule_uids": " | ".join(comparison.get("candidate_rule_uids") or []),
                    "final_rule_uids": " | ".join(comparison.get("final_rule_uids") or []),
                    "candidate_rule_ids": " | ".join(comparison.get("candidate_rule_ids") or []),
                    "final_rule_ids": " | ".join(comparison.get("final_rule_ids") or []),
                    "error": None if comparison.get("response_ok") else item["actual_response"].get("msg"),
                }
            )
    return json_path, csv_path


def main():
    parser = argparse.ArgumentParser(description="Run the three 10-case datasets and save full baseline output.")
    parser.add_argument("--dataset-dir", default=str(DEFAULT_DATASET_DIR))
    parser.add_argument("--normalized-cases", default=None)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--baseline-name", required=True)
    parser.add_argument("--llm-backend", choices=["mock", "deepseek"], required=True)
    parser.add_argument("--semantic-backend", choices=["local", "zhipu"], default="local")
    parser.add_argument("--uid-bindings", default=str(DEFAULT_UID_BINDINGS))
    parser.add_argument("--game-uid-mapping", default=str(DEFAULT_GAME_UID_MAPPING))
    args = parser.parse_args()

    if args.normalized_cases:
        cases, sources = load_normalized_cases(args.normalized_cases)
    else:
        cases, sources = load_cases(args.dataset_dir)
    if len(cases) != 30:
        raise SystemExit(f"Expected 30 cases, loaded {len(cases)}")
    applied = apply_uid_bindings(
        cases,
        bindings_path=args.uid_bindings,
        game_mapping_path=args.game_uid_mapping,
    )
    sources = list(sources) + [
        {
            "file": Path(args.uid_bindings).name,
            "path": str(Path(args.uid_bindings).resolve()),
            "sha256": _sha256(Path(args.uid_bindings)),
        },
        {
            "file": Path(args.game_uid_mapping).name,
            "path": str(Path(args.game_uid_mapping).resolve()),
            "sha256": _sha256(Path(args.game_uid_mapping)),
        },
    ]
    print(f"applied corrected UID bindings to {applied}/{len(cases)} cases", flush=True)
    report = run_baseline(cases, sources, args.baseline_name, args.llm_backend, args.semantic_backend)
    json_path, csv_path = save_report(report, args.output_dir)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"json_report={json_path}")
    print(f"comparison_csv={csv_path}")


if __name__ == "__main__":
    main()
