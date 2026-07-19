# -*- coding: utf-8 -*-
"""Build offline semantic candidate reports for reviewed legal-issue groups."""

import argparse
import json
import math
from datetime import datetime
from pathlib import Path

from kg_rule_store import load_rule_library
from rule_identity import rule_identity
from rule_vector_index import DEFAULT_VECTOR_INDEX_PATH


PROJECT_BASE = Path(__file__).resolve().parents[1]


def _trigger_layer(rule):
    return (rule.get("recall") or {}).get("trigger_layer") or "content"


def _industries(rule):
    values = (rule.get("applies_to") or {}).get("industries")
    if not values:
        values = [rule.get("industry")]
    if not isinstance(values, list):
        values = [values]
    return {str(value).strip() for value in values if str(value or "").strip()}


def _compatible_industries(left, right):
    left_values = _industries(left)
    right_values = _industries(right)
    if not left_values or not right_values:
        return True
    if "通用" in left_values or "通用" in right_values:
        return True
    return bool(left_values & right_values)


def _cosine(left, right):
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
    right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def _best_similarity(left_vectors, right_vectors):
    return max(
        (_cosine(left, right) for left in left_vectors for right in right_vectors),
        default=0.0,
    )


def candidate_pairs(rules, embeddings, threshold=0.85):
    eligible = sorted(
        [rule for rule in rules if rule_identity(rule) in embeddings],
        key=lambda rule: str(rule_identity(rule)),
    )
    pairs = []
    for index, left in enumerate(eligible):
        for right in eligible[index + 1 :]:
            if _trigger_layer(left) != _trigger_layer(right):
                continue
            if not _compatible_industries(left, right):
                continue
            similarity = _best_similarity(
                embeddings.get(rule_identity(left), []),
                embeddings.get(rule_identity(right), []),
            )
            if similarity < float(threshold):
                continue
            pairs.append(
                {
                    "left_uid": rule_identity(left),
                    "left_rule_id": left.get("rule_id"),
                    "left_title": left.get("title"),
                    "right_uid": rule_identity(right),
                    "right_rule_id": right.get("rule_id"),
                    "right_title": right.get("title"),
                    "trigger_layer": _trigger_layer(left),
                    "similarity": round(similarity, 6),
                }
            )
    return sorted(pairs, key=lambda item: (-item["similarity"], item["left_uid"], item["right_uid"]))


def build_candidate_report(rules, embeddings, threshold=0.85, output_path=None):
    pairs = candidate_pairs(rules, embeddings, threshold=threshold)
    report = {
        "threshold": float(threshold),
        "rule_count": len(rules),
        "pair_count": len(pairs),
        "pairs": pairs,
    }
    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return report


def load_cached_embeddings(path=DEFAULT_VECTOR_INDEX_PATH):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    embeddings = {}
    for item in payload.get("vectors", []) or []:
        uid = item.get("rule_uid") or item.get("rule_id")
        vector = item.get("embedding")
        if uid and vector:
            embeddings.setdefault(uid, []).append(vector)
    return embeddings


def _write_markdown(report, output_path):
    lines = [
        "# Legal Issue Group Candidate Report",
        "",
        f"Threshold: {report['threshold']}",
        f"Candidate pairs: {report['pair_count']}",
        "",
    ]
    for item in report["pairs"]:
        lines.append(
            f"- {item['similarity']:.4f} | {item['left_uid']} {item['left_title']} | "
            f"{item['right_uid']} {item['right_title']}"
        )
    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", default=str(PROJECT_BASE))
    parser.add_argument("--vector-index", default=str(DEFAULT_VECTOR_INDEX_PATH))
    parser.add_argument("--threshold", type=float, default=0.85)
    args = parser.parse_args()

    base_dir = Path(args.base_dir)
    rules = load_rule_library(base_dir)["data"]["rules"]
    embeddings = load_cached_embeddings(args.vector_index)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = base_dir / "reports" / "legal_issue_groups"
    json_path = report_dir / f"{stamp}_candidates.json"
    md_path = report_dir / f"{stamp}_candidates.md"
    report = build_candidate_report(rules, embeddings, args.threshold, json_path)
    _write_markdown(report, md_path)
    print(f"wrote {report['pair_count']} candidate pairs to {json_path}")


if __name__ == "__main__":
    main()
