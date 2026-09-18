import argparse
import json
from pathlib import Path

from src.build_chunks import production_exclusion_reasons


DEFAULT_STRUCTURED_DIR = Path("data/structured")
DEFAULT_JSON_OUTPUT = Path("data/reports/rule_mapping_queue.json")
DEFAULT_MARKDOWN_OUTPUT = Path("data/reports/rule_mapping_queue.md")


def load_mapping_queue(structured_dir: Path) -> list[dict]:
    queue = []
    for path in sorted(structured_dir.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        if production_exclusion_reasons(case):
            continue
        mapped_rule_ids = case.get("mapped_rule_ids") or []
        if mapped_rule_ids:
            continue
        queue.append(
            {
                "case_id": case["case_id"],
                "title": case.get("title", ""),
                "violation_type": case.get("violation_type", ""),
                "risk_dimensions": case.get("risk_dimensions", []),
                "illegal_claims": case.get("illegal_claims", []),
                "legal_basis": case.get("legal_basis", []),
                "regulatory_logic": case.get("regulatory_logic", ""),
                "source_name": case.get("source_name", ""),
                "source_url": case.get("source_url", ""),
                "raw_text_path": case.get("raw_text_path", ""),
                "mapped_rule_ids": [],
                "mapping_status": "pending_rule_owner_review",
            }
        )
    return queue


def render_markdown(queue: list[dict]) -> str:
    lines = [
        "# 正式案例规则映射复核队列",
        "",
        f"- 待映射案例：{len(queue)}",
        "- 状态：`pending_rule_owner_review`",
        "- 说明：本队列不自动推断规则 ID 或具体法条；仅整理已核验案例证据，供规则负责人对照正式规则目录人工回填。",
        "",
    ]
    for index, item in enumerate(queue, start=1):
        lines.extend(
            [
                f"## {index}. {item['case_id']} — {item['title']}",
                "",
                f"- 违法类型：{item['violation_type'] or '-'}",
                f"- 风险维度：{'；'.join(item['risk_dimensions']) or '-'}",
                f"- 广告宣称：{'；'.join(item['illegal_claims']) or '-'}",
                f"- 已公开法律依据：{'；'.join(item['legal_basis']) or '-'}",
                f"- 监管逻辑：{item['regulatory_logic'] or '-'}",
                f"- 来源：[{item['source_name']}]({item['source_url']})",
                f"- 原文路径：`{item['raw_text_path']}`",
                "- 待回填规则 ID：",
                "",
            ]
        )
    return "\n".join(lines)


def run(
    structured_dir: Path = DEFAULT_STRUCTURED_DIR,
    json_output: Path = DEFAULT_JSON_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
) -> list[dict]:
    queue = load_mapping_queue(structured_dir)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(
        json.dumps(queue, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_output.write_text(render_markdown(queue).rstrip() + "\n", encoding="utf-8")
    return queue


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导出正式案例规则 ID 人工复核队列")
    parser.add_argument("--structured-dir", type=Path, default=DEFAULT_STRUCTURED_DIR)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    queue = run(args.structured_dir, args.json_output, args.markdown_output)
    print(f"rule mapping queue exported: pending={len(queue)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
