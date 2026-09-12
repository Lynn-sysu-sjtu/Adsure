from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from .models import EvidenceUnit, RequirementCheck, RiskCandidate
from .textmatch import compact, normalize, negated, text_windows, catalog as pattern_catalog


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = PROJECT_ROOT / "data" / "rules" / "video_mvp_health_food.json"

CORE_ABSOLUTE_TERMS = ("国家级", "最高级", "最佳")
CONTEXT_ABSOLUTE_TERMS = (
    "全网第一",
    "销量第一",
    "第一品牌",
    "行业第一",
    "唯一",
    "顶级",
    "极品",
)
ABSOLUTE_EXEMPTION_HINTS = (
    "第一时间",
    "第一步",
    "第一排",
    "特级",
    "一级",
)
DISEASE_TERMS = (
    "根治",
    "治愈",
    "治疗",
    "预防疾病",
    "降血糖",
    "降血压",
    "抗癌",
    "消炎",
    "药到病除",
)
MANDATORY_WARNING = "保健食品不是药物不能代替药物治疗疾病"


def _normalize(text: str) -> str:
    return compact(text)


def _risk_id(rule_id: str, text: str, start: float) -> str:
    value = f"{rule_id}|{text}|{start:.2f}".encode("utf-8")
    return "risk_" + hashlib.sha256(value).hexdigest()[:12]


def _load_catalog() -> dict[str, dict]:
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    result = {rule["rule_id"]: rule for rule in payload["rules"]}
    law = json.loads((CATALOG_PATH.parent / "advertising_law_2021.json").read_text(encoding="utf-8"))
    for item in law["rules"]:
        result.setdefault(item["rule_id"], dict(item, source_url=law["source_url"], source_name=law["source_name"]))
    for item in pattern_catalog().get("supplementary_legal_basis", []):
        result[item["rule_id"]] = item
    return result


def _basis(catalog: dict[str, dict], rule_ids: list[str]) -> list[dict]:
    return [catalog[rule_id] for rule_id in rule_ids if rule_id in catalog]


def _make_text_risk(
    evidence: EvidenceUnit,
    *,
    matched_text: str,
    rule_ids: list[str],
    title: str,
    severity: str,
    dimension: str,
    explanation: str,
    recommendation: str,
    catalog: dict[str, dict],
) -> RiskCandidate:
    start, end = evidence.t_start, evidence.t_end
    words = evidence.raw_ref.get("words", [])
    if words:
        joined = "".join(normalize(w["word"]) for w in words)
        offset = joined.find(matched_text)
        if offset >= 0:
            cursor = 0
            selected = []
            for word in words:
                size = len(normalize(word["word"]))
                if cursor < offset + len(matched_text) and cursor + size > offset:
                    selected.append(word)
                cursor += size
            if selected:
                start, end = selected[0]["start"], selected[-1]["end"]
    return RiskCandidate(
        risk_id=_risk_id(rule_ids[0], matched_text, evidence.t_start),
        title=title,
        severity=severity,
        disposition="建议修改" if severity == "high" else "人工复核",
        review_status="pending_human_review",
        risk_dimension=dimension,
        matched_text=matched_text,
        t_start=start,
        t_end=end,
        bbox=evidence.bbox,
        evidence_ids=evidence.raw_ref.get("constituent_ids", [evidence.id]),
        rule_ids=rule_ids,
        legal_basis=_basis(catalog, rule_ids),
        explanation=explanation,
        recommendation=recommendation,
        automated_finding="机器发现候选；不构成违法认定。",
        context_text=evidence.text,
        match_method=evidence.raw_ref.get("method", "normalized_pattern"),
        source=evidence.source,
        occurrences=[{"t_start": start, "t_end": end, "bbox": evidence.bbox,
                      "evidence_ids": evidence.raw_ref.get("constituent_ids", [evidence.id])}],
    )


def _merge_repeated_risks(risks: list[RiskCandidate], gap: float) -> list[RiskCandidate]:
    grouped: dict[tuple[str, str, str], list[RiskCandidate]] = defaultdict(list)
    for risk in risks:
        grouped[(risk.pattern_id, risk.matched_text, risk.source)].append(risk)
    merged: list[RiskCandidate] = []
    for items in grouped.values():
        items.sort(key=lambda item: item.t_start)
        current = items[0]
        for item in items[1:]:
            if item.t_start <= current.t_end + gap:
                current.t_end = max(current.t_end, item.t_end)
                current.evidence_ids.extend(item.evidence_ids)
                current.evidence_ids = list(dict.fromkeys(current.evidence_ids))
                current.occurrences.extend(item.occurrences)
            else:
                merged.append(current)
                current = item
        merged.append(current)
    return sorted(merged, key=lambda item: (item.t_start, item.risk_id))


def _frame_texts(evidence: list[EvidenceUnit]) -> dict[str, tuple[str, list[str]]]:
    frames: dict[str, tuple[list[str], list[str]]] = {}
    for item in evidence:
        if item.source != "ocr" or not item.frame_ids:
            continue
        frame_id = item.frame_ids[0]
        text_parts, ids = frames.setdefault(frame_id, ([], []))
        text_parts.append(item.text)
        ids.append(item.id)
    return {
        frame_id: ("".join(parts), ids)
        for frame_id, (parts, ids) in frames.items()
    }


def analyze_rules(
    evidence: list[EvidenceUnit],
    *,
    industry: str,
    frame_count: int,
    coverage_complete: bool,
    sample_interval: float,
) -> tuple[list[RiskCandidate], list[RequirementCheck]]:
    catalog = _load_catalog()
    risks: list[RiskCandidate] = []

    patterns = pattern_catalog()["patterns"]
    windows = text_windows(evidence)
    # Suppress disclaimer fragments using their spatially/temporally adjacent context.
    warning_ids = set()
    for item in windows:
        if MANDATORY_WARNING in compact(item.text):
            warning_ids.update(item.raw_ref.get("constituent_ids", [item.id]))
    seen = set()
    for item in windows:
        if item.kind != "text" or not item.text.strip():
            continue
        text = normalize(item.text)
        for pattern in patterns:
            if pattern["scope"] == "non_medical" and industry in {"医疗", "药品", "医疗器械"}:
                continue
            if pattern["scope"] == "cosmetics" and industry != "化妆品":
                continue
            for match in re.finditer(pattern["regex"], text):
                if negated(text, match.start(), match.end()):
                    continue
                if pattern["id"] == "medical_claim" and item.id in warning_ids:
                    # Only suppress a fragment if it contains no additional claim beyond the warning.
                    if compact(item.text) in MANDATORY_WARNING:
                        continue
                parts = item.raw_ref.get("parts", [])
                if parts:
                    # A window is useful only when the match spans a boundary.
                    if any(match.group() in normalize(part) for part in parts):
                        continue
                term = match.group()
                key = (pattern["id"], term, item.source, item.t_start)
                if key in seen:
                    continue
                seen.add(key)
                ids = list(pattern["rule_ids"])
                if pattern["id"] == "medical_claim" and industry == "保健食品":
                    ids.append("ADLAW-018")
                level = pattern["severity"]
                explanation = "依据原始识别文本生成的规则候选；需核验广告语境、产品属性及证据。"
                if industry == "一般行业" and pattern["scope"] == "non_medical":
                    level = "medium"
                    explanation = "行业未细分，已保留疾病功效线索；确认产品是否属于医疗、药品、医疗器械后再适用第十七条。"
                if item.confidence is not None and item.confidence < .6:
                    explanation += " 本段识别置信度偏低，须对照音频或原始画面。"
                risk = _make_text_risk(item, matched_text=term, rule_ids=ids,
                    title=pattern["title"] + "：" + term, severity=level,
                    dimension=pattern["dimension"], explanation=explanation,
                    recommendation=pattern["advice"], catalog=catalog)
                risk.pattern_id = pattern["id"]
                risks.append(risk)

    risks = _merge_repeated_risks(risks, max(0.1, sample_interval * 1.1))
    checks: list[RequirementCheck] = []
    if industry == "保健食品":
        frames = _frame_texts(evidence)
        detected_warning_frames = [
            (frame_id, ids)
            for frame_id, (text, ids) in frames.items()
            if MANDATORY_WARNING in _normalize(text)
        ]
        warning_ratio = (
            len(detected_warning_frames) / frame_count if frame_count else 0.0
        )
        warning_ids = [
            evidence_id
            for _frame_id, ids in detected_warning_frames
            for evidence_id in ids
        ]
        if not coverage_complete:
            warning_status = "incomplete_coverage"
            warning_explanation = "抽帧未覆盖完整视频，不能判断警示语是否持续显示。"
        elif warning_ratio == 0:
            warning_status = "not_observed"
            warning_explanation = "在抽样画面中未识别到完整法定警示语；OCR 结果需人工复核。"
        elif warning_ratio < 1:
            warning_status = "not_continuously_observed"
            warning_explanation = "仅在部分抽样画面识别到完整警示语，不满足自动核验持续显示的条件。"
        else:
            warning_status = "observed_in_all_samples"
            warning_explanation = "所有抽样画面均识别到完整警示语；仍需人工确认清晰度及真实连续显示。"
        checks.append(RequirementCheck(
            check_id="l4_health_food_warning_continuity",
            title="完整警示语在视频中持续显示",
            status=warning_status,
            coverage_ratio=round(warning_ratio, 4),
            evidence_ids=list(dict.fromkeys(warning_ids)),
            rule_ids=["HFAD-007", "HFAD-010"],
            explanation=warning_explanation,
        ))

        joined = "".join(_normalize(text) for text, _ids in frames.values())
        checks.append(RequirementCheck(
            check_id="l4_health_food_audience",
            title="适宜人群与不适宜人群",
            status=("observed" if "适宜人群" in joined.replace("不适宜人群", "") and "不适宜人群" in joined else "not_observed"),
            coverage_ratio=None,
            evidence_ids=[],
            rule_ids=["HFAD-007"],
            explanation="机器只检查文字是否出现；具体内容及显著性必须与广告审查样件人工核对。",
        ))
        approval_observed = bool(re.search(r"(?:广告审查批准文号|广告批准文号|食健广审)", joined))
        checks.append(RequirementCheck(
            check_id="l4_health_food_approval_number",
            title="广告批准文号",
            status="observed" if approval_observed else "not_observed",
            coverage_ratio=None,
            evidence_ids=[],
            rule_ids=["HFAD-009", "HFAD-010"],
            explanation="机器只检查常见字段名称或编号前缀；应由法务核验文号真实性和有效期。",
        ))
        checks.append(RequirementCheck(
            check_id="l4_health_food_logo",
            title="保健食品标志",
            status="human_review_required",
            coverage_ratio=None,
            evidence_ids=[],
            rule_ids=["HFAD-007", "HFAD-010"],
            explanation="MVP 不自动识别保健食品标志，必须人工检查其存在、清晰度和持续显示。",
        ))
    return risks, checks
