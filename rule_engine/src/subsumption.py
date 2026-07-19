# -*- coding: utf-8 -*-
"""Strict validation and filtering for structured LLM subsumption output."""

import copy
import re
import unicodedata
from dataclasses import dataclass

from rule_identity import rule_identity


ALLOWED_STATUSES = {
    "confirmed_violation",
    "needs_fact_verification",
    "not_applicable",
}
LIST_FIELDS = (
    "satisfied_elements",
    "unsatisfied_elements",
    "missing_facts",
)


class SubsumptionValidationError(ValueError):
    """Raised when model output cannot safely support a legal conclusion."""


@dataclass
class ValidatedSubsumption:
    final_rules: list
    rejected_rules: list
    judgments: list


def _normalized_text(value):
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _validate_list_field(item, field):
    value = item.get(field)
    if not isinstance(value, list) or any(not isinstance(element, str) for element in value):
        raise SubsumptionValidationError(f"{field} must be a list of strings")


def _validate_evidence(item, material_text):
    evidence = _normalized_text(item.get("material_evidence"))
    status = item.get("applicability_status")
    if status == "confirmed_violation" and not evidence:
        raise SubsumptionValidationError("confirmed violation requires material evidence")
    if evidence and evidence not in _normalized_text(material_text):
        raise SubsumptionValidationError("material evidence is not a continuous original substring")


def _enriched_rule(candidate, judgment):
    rule = copy.deepcopy(candidate)
    status = judgment["applicability_status"]
    rule.update(
        {
            "applicability_status": status,
            "material_evidence": judgment.get("material_evidence") or "",
            "satisfied_elements": list(judgment.get("satisfied_elements") or []),
            "unsatisfied_elements": list(judgment.get("unsatisfied_elements") or []),
            "missing_facts": list(judgment.get("missing_facts") or []),
            "applicability_reason": judgment.get("applicability_reason") or "",
            "confidence": judgment.get("confidence"),
            "judgment": "确认适用" if status == "confirmed_violation" else "需事实核验",
            "match_reason": judgment.get("applicability_reason") or candidate.get("match_reason") or "",
        }
    )
    return rule


def validate_subsumption_result(candidate_rules, raw_judgments, material_text):
    """Validate complete model coverage and return displayable final rules."""
    if not isinstance(raw_judgments, list):
        raise SubsumptionValidationError("rule_judgments must be a list")
    candidate_by_uid = {}
    for candidate in candidate_rules or []:
        uid = rule_identity(candidate)
        if not uid or uid in candidate_by_uid:
            raise SubsumptionValidationError("candidate rule_uid values must be unique")
        candidate_by_uid[uid] = candidate

    returned_uids = [str(item.get("rule_uid") or "") for item in raw_judgments if isinstance(item, dict)]
    if (
        len(raw_judgments) != len(candidate_by_uid)
        or len(returned_uids) != len(raw_judgments)
        or len(set(returned_uids)) != len(returned_uids)
        or set(returned_uids) != set(candidate_by_uid)
    ):
        raise SubsumptionValidationError("Every candidate must be judged exactly once")

    final_rules = []
    rejected_rules = []
    normalized_judgments = []
    for raw in raw_judgments:
        item = copy.deepcopy(raw)
        status = item.get("applicability_status")
        if status not in ALLOWED_STATUSES:
            raise SubsumptionValidationError(f"Illegal applicability status: {status}")
        for field in LIST_FIELDS:
            _validate_list_field(item, field)
        if status == "needs_fact_verification" and not item.get("missing_facts"):
            raise SubsumptionValidationError("needs_fact_verification requires missing_facts")
        _validate_evidence(item, material_text)
        confidence = item.get("confidence")
        if confidence is not None and (not isinstance(confidence, (int, float)) or isinstance(confidence, bool)):
            raise SubsumptionValidationError("confidence must be numeric or null")

        uid = item["rule_uid"]
        candidate = candidate_by_uid[uid]
        normalized_judgments.append(item)
        if status == "not_applicable":
            rejected = copy.deepcopy(candidate)
            rejected.update(
                {
                    "applicability_status": status,
                    "applicability_reason": item.get("applicability_reason") or "",
                    "material_evidence": item.get("material_evidence") or "",
                }
            )
            rejected_rules.append(rejected)
        else:
            final_rules.append(_enriched_rule(candidate, item))

    return ValidatedSubsumption(
        final_rules=final_rules,
        rejected_rules=rejected_rules,
        judgments=normalized_judgments,
    )
