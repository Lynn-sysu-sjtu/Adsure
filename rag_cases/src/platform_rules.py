"""Versioned platform-rule precheck for Xiaohongshu advertising.

This module is deliberately isolated from the administrative-penalty case RAG.
It produces platform-review candidates with source provenance and coverage
limitations. It never turns a rule hit into a legal conclusion or promises that
an advertisement will pass Xiaohongshu's final review.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG_PATH = (
    PROJECT_ROOT
    / "data"
    / "rules"
    / "platform"
    / "xiaohongshu_juguang_pilot.json"
)

SUPPORTED_PLATFORM = "小红书"
SUPPORTED_SCENE = "聚光"
SUPPORTED_INDUSTRIES = {"美妆", "游戏", "保健食品", "通用"}
PRODUCTION_REVIEW_STATUSES = {"approved"}
PILOT_REVIEW_STATUSES = {"approved", "approved_for_pilot"}

VERDICT_PRIORITY = {
    "预检未发现风险": 0,
    "待补充材料": 1,
    "需修改": 2,
    "待法务复核": 3,
    "禁止发布": 4,
}


class PlatformRuleCatalogError(ValueError):
    """Raised when a platform-rule catalog is malformed or unsafe to load."""


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(
        dict.fromkeys(
            item.strip()
            for item in value
            if isinstance(item, str) and item.strip()
        )
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _scope_matches(rule_values: Any, request_value: str) -> bool:
    values = set(_as_string_list(rule_values))
    return not values or "通用" in values or request_value in values


def _product_scope_matches(rule_values: Any, product_category: str) -> bool:
    values = _as_string_list(rule_values)
    if not values:
        return True
    return any(value in product_category for value in values)


def validate_catalog(payload: Any) -> list[str]:
    """Return deterministic validation errors for a platform-rule catalog."""

    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["catalog_root_must_be_object"]
    for field in (
        "catalog_id",
        "platform",
        "catalog_status",
        "collected_at",
        "rules",
    ):
        if field not in payload:
            errors.append(f"{field}_missing")
    if payload.get("platform") != SUPPORTED_PLATFORM:
        errors.append("platform_must_be_xiaohongshu")
    rules = payload.get("rules")
    if not isinstance(rules, list):
        return errors + ["rules_must_be_array"]

    seen: set[str] = set()
    for index, rule in enumerate(rules):
        prefix = f"rules[{index}]"
        if not isinstance(rule, dict):
            errors.append(f"{prefix}_must_be_object")
            continue
        for field in (
            "rule_id",
            "title",
            "platform",
            "scene_scope",
            "industry_scope",
            "material_scope",
            "rule_type",
            "risk_dimension",
            "rule_text",
            "default_action",
            "severity",
            "source_name",
            "source_url",
            "source_locator",
            "raw_text_path",
            "content_hash",
            "effective_status",
            "review_status",
        ):
            if field not in rule:
                errors.append(f"{prefix}.{field}_missing")
        rule_id = rule.get("rule_id")
        if not isinstance(rule_id, str) or not rule_id:
            errors.append(f"{prefix}.rule_id_invalid")
        elif rule_id in seen:
            errors.append(f"{prefix}.rule_id_duplicate")
        else:
            seen.add(rule_id)
        if rule.get("platform") != SUPPORTED_PLATFORM:
            errors.append(f"{prefix}.platform_invalid")
        if rule.get("default_action") not in VERDICT_PRIORITY:
            errors.append(f"{prefix}.default_action_invalid")
        if rule.get("severity") not in {"high", "medium", "low", "info"}:
            errors.append(f"{prefix}.severity_invalid")
        if rule.get("effective_status") not in {
            "active",
            "pending_effective_review",
            "superseded",
            "withdrawn",
        }:
            errors.append(f"{prefix}.effective_status_invalid")
        for field in ("source_url", "raw_text_path", "content_hash"):
            if not isinstance(rule.get(field), str) or not rule.get(field, "").strip():
                errors.append(f"{prefix}.{field}_invalid")
        logic = rule.get("decision_logic")
        if logic is not None and not isinstance(logic, dict):
            errors.append(f"{prefix}.decision_logic_invalid")
    return errors


def validate_precheck_payload(payload: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(payload, dict):
        return None, "请求体必须是 JSON 对象"

    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        return None, "缺少必填字段：content"
    industry = payload.get("industry")
    if not isinstance(industry, str) or industry.strip() not in SUPPORTED_INDUSTRIES:
        return None, "industry 必须是：美妆、游戏、保健食品或通用"
    industry = industry.strip()

    platforms = payload.get("platform")
    if not isinstance(platforms, list) or any(
        not isinstance(item, str) for item in platforms
    ):
        return None, "platform 必须是字符串数组"
    platforms = _as_string_list(platforms)
    if SUPPORTED_PLATFORM not in platforms:
        return None, "platform 必须包含小红书"

    material_type = payload.get("material_type", "图文")
    if not isinstance(material_type, str) or not material_type.strip():
        return None, "material_type 必须是非空字符串"
    material_type = material_type.strip()

    scene_supplied = bool(
        isinstance(payload.get("platform_scene"), str)
        and payload.get("platform_scene", "").strip()
    )
    platform_scene = (
        payload.get("platform_scene", "").strip()
        if scene_supplied
        else SUPPORTED_SCENE
    )

    title = payload.get("title", "")
    if title is None:
        title = ""
    if not isinstance(title, str):
        return None, "title 必须是字符串"
    tags = payload.get("tags", [])
    if not isinstance(tags, list) or any(not isinstance(item, str) for item in tags):
        return None, "tags 必须是字符串数组"

    assets = payload.get("assets", [])
    if not isinstance(assets, list) or any(not isinstance(item, dict) for item in assets):
        return None, "assets 必须是对象数组"
    normalized_assets: list[dict[str, Any]] = []
    for index, asset in enumerate(assets):
        asset_type = asset.get("type")
        if not isinstance(asset_type, str) or not asset_type.strip():
            return None, f"assets[{index}].type 必须是非空字符串"
        extracted_text = asset.get("extracted_text", "")
        if extracted_text is None:
            extracted_text = ""
        if not isinstance(extracted_text, str):
            return None, f"assets[{index}].extracted_text 必须是字符串"
        normalized_assets.append(
            {
                "asset_id": str(asset.get("asset_id") or f"asset_{index + 1}"),
                "type": asset_type.strip(),
                "analysis_status": str(asset.get("analysis_status") or "not_checked"),
                "extracted_text": extracted_text.strip(),
            }
        )

    qualifications = payload.get("qualifications", {})
    if not isinstance(qualifications, dict):
        return None, "qualifications 必须是对象"
    has_landing_page = payload.get("has_landing_page")
    if has_landing_page not in {True, False, None}:
        return None, "has_landing_page 必须是布尔值或 null"
    landing_page_text = payload.get("landing_page_text", "")
    if landing_page_text is None:
        landing_page_text = ""
    if not isinstance(landing_page_text, str):
        return None, "landing_page_text 必须是字符串"

    return {
        "record_id": str(payload.get("record_id") or ""),
        "content": content.strip(),
        "title": title.strip(),
        "tags": _as_string_list(tags),
        "industry": industry,
        "product_category": str(payload.get("product_category") or "").strip(),
        "platform": platforms,
        "platform_scene": platform_scene,
        "platform_scene_inferred": not scene_supplied,
        "material_type": material_type,
        "assets": normalized_assets,
        "qualifications": qualifications,
        "has_landing_page": has_landing_page,
        "landing_page_text": landing_page_text.strip(),
    }, None


def _evidence_units(request: dict[str, Any]) -> list[dict[str, str]]:
    units = [{"field": "content", "asset_id": "", "text": request["content"]}]
    if request["title"]:
        units.append({"field": "title", "asset_id": "", "text": request["title"]})
    for index, tag in enumerate(request["tags"]):
        units.append({"field": f"tags[{index}]", "asset_id": "", "text": tag})
    for asset in request["assets"]:
        if asset["extracted_text"]:
            units.append(
                {
                    "field": "asset.extracted_text",
                    "asset_id": asset["asset_id"],
                    "text": asset["extracted_text"],
                }
            )
    if request["landing_page_text"]:
        units.append(
            {
                "field": "landing_page_text",
                "asset_id": "landing_page",
                "text": request["landing_page_text"],
            }
        )
    return units


def _term_matches(
    units: Iterable[dict[str, str]],
    terms: list[str],
) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    for unit in units:
        for term in terms:
            if term and re.search(re.escape(term), unit["text"], flags=re.IGNORECASE):
                matches.append(
                    {
                        "field": unit["field"],
                        "asset_id": unit["asset_id"],
                        "matched_text": term,
                        "evidence_text": unit["text"],
                    }
                )
    return matches


def _finding_id(rule_id: str, evidence: Any) -> str:
    return "pf_" + _stable_hash({"rule_id": rule_id, "evidence": evidence})[:12]


def _build_finding(
    rule: dict[str, Any],
    evidence: list[dict[str, str]],
    *,
    missing_evidence: list[str] | None = None,
) -> dict[str, Any]:
    missing_evidence = missing_evidence or []
    return {
        "finding_id": _finding_id(
            rule["rule_id"],
            {"evidence": evidence, "missing_evidence": missing_evidence},
        ),
        "rule_id": rule["rule_id"],
        "rule_id_type": "adsure_internal_non_official",
        "title": rule["title"],
        "risk_dimension": rule["risk_dimension"],
        "severity": rule["severity"],
        "action": rule["default_action"],
        "review_status": "pending_human_review",
        "evidence": evidence,
        "missing_evidence": missing_evidence,
        "reason": rule.get("decision_reason") or rule["rule_text"],
        "suggestion": rule.get("suggestion") or "请结合完整物料和证明材料人工复核。",
        "source": {
            "source_name": rule["source_name"],
            "source_url": rule["source_url"],
            "source_locator": rule["source_locator"],
            "source_update_date": rule.get("source_update_date"),
            "raw_text_path": rule["raw_text_path"],
            "content_hash": rule["content_hash"],
        },
    }


class PlatformRuleRepository:
    """Load reviewed platform rules and run a deterministic pilot precheck."""

    def __init__(
        self,
        catalog_path: Path = DEFAULT_CATALOG_PATH,
        *,
        allow_pilot_rules: bool = False,
    ) -> None:
        self.catalog_path = catalog_path
        self.allow_pilot_rules = allow_pilot_rules
        self.load_error = ""
        self.catalog: dict[str, Any] = {}
        self.rules: list[dict[str, Any]] = []
        self.snapshot_id = ""
        try:
            self.catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            errors = validate_catalog(self.catalog)
            if errors:
                raise PlatformRuleCatalogError(";".join(errors))
            accepted_statuses = (
                PILOT_REVIEW_STATUSES
                if allow_pilot_rules
                else PRODUCTION_REVIEW_STATUSES
            )
            self.rules = [
                rule
                for rule in self.catalog["rules"]
                if rule.get("effective_status") == "active"
                and rule.get("review_status") in accepted_statuses
            ]
            self.snapshot_id = _stable_hash(
                {
                    "catalog_id": self.catalog["catalog_id"],
                    "rules": [
                        {
                            "rule_id": rule["rule_id"],
                            "content_hash": rule["content_hash"],
                            "review_status": rule["review_status"],
                        }
                        for rule in self.rules
                    ],
                }
            )[:16]
        except (OSError, json.JSONDecodeError, PlatformRuleCatalogError) as exc:
            self.load_error = f"{type(exc).__name__}: {exc}"

    @property
    def production_ready(self) -> bool:
        return bool(self.rules) and all(
            rule.get("review_status") == "approved" for rule in self.rules
        )

    def _applicable_rules(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            rule
            for rule in self.rules
            if _scope_matches(rule.get("scene_scope"), request["platform_scene"])
            and _scope_matches(rule.get("industry_scope"), request["industry"])
            and _scope_matches(rule.get("material_scope"), request["material_type"])
            and _product_scope_matches(
                rule.get("product_category_scope"),
                request["product_category"],
            )
        ]

    def precheck(self, payload: Any) -> tuple[dict[str, Any] | None, str | None]:
        request, message = validate_precheck_payload(payload)
        if message:
            return None, message
        assert request is not None

        checked_at = _utc_now()
        if self.load_error or not self.rules:
            reason = (
                "平台规则目录加载失败"
                if self.load_error
                else "当前没有已批准进入生产审核的平台规则"
            )
            result = {
                "platform": SUPPORTED_PLATFORM,
                "scene": request["platform_scene"],
                "policy_snapshot_id": self.snapshot_id or None,
                "catalog_status": self.catalog.get("catalog_status") or "unavailable",
                "production_ready": False,
                "verdict": "manual_review_required",
                "verdict_label": "待法务复核",
                "coverage_status": "rules_unavailable",
                "coverage_reason": reason,
                "unchecked_materials": ["小红书平台规则"],
                "findings": [],
                "checked_at": checked_at,
                "disclaimer": "平台规则预检不可替代小红书最终审核或人工法律复核。",
            }
            return {
                "platform_precheck": result,
                "审核_平台规则预检": self._summary(result),
            }, None

        if request["platform_scene"] != SUPPORTED_SCENE:
            result = {
                "platform": SUPPORTED_PLATFORM,
                "scene": request["platform_scene"],
                "policy_snapshot_id": self.snapshot_id,
                "catalog_status": self.catalog["catalog_status"],
                "production_ready": self.production_ready,
                "verdict": "out_of_scope",
                "verdict_label": "待法务复核",
                "coverage_status": "out_of_scope",
                "coverage_reason": "首期仅覆盖小红书聚光场景",
                "unchecked_materials": [request["platform_scene"]],
                "findings": [],
                "checked_at": checked_at,
                "disclaimer": "平台规则预检不可替代小红书最终审核或人工法律复核。",
            }
            return {
                "platform_precheck": result,
                "审核_平台规则预检": self._summary(result),
            }, None

        applicable_rules = self._applicable_rules(request)
        units = _evidence_units(request)
        findings: list[dict[str, Any]] = []
        required_qualification_names: set[str] = set()

        for rule in applicable_rules:
            logic = rule.get("decision_logic") or {"type": "manual"}
            logic_type = logic.get("type")
            if logic_type == "terms":
                evidence = _term_matches(units, _as_string_list(logic.get("terms")))
                if evidence:
                    findings.append(_build_finding(rule, evidence))
            elif logic_type == "required_evidence":
                required = _as_string_list(rule.get("required_evidence"))
                required_qualification_names.update(required)
                missing = [
                    name
                    for name in required
                    if not request["qualifications"].get(name)
                ]
                if missing:
                    findings.append(
                        _build_finding(rule, [], missing_evidence=missing)
                    )

        unchecked: list[str] = []
        if request["platform_scene_inferred"]:
            unchecked.append("投放场景需显式确认")
        if request["material_type"] != "图文":
            unchecked.append(f"首期未覆盖物料类型：{request['material_type']}")
        image_assets = [
            asset for asset in request["assets"] if asset["type"] == "image"
        ]
        if request["material_type"] == "图文" and (
            not image_assets
            or any(
                asset["analysis_status"] != "completed"
                or not asset["extracted_text"]
                for asset in image_assets
            )
        ):
            unchecked.append("图片/OCR")
        if request["has_landing_page"] is None:
            unchecked.append("是否存在落地页")
        elif request["has_landing_page"] and not request["landing_page_text"]:
            unchecked.append("落地页内容")

        missing_required = sorted(
            name
            for name in required_qualification_names
            if not request["qualifications"].get(name)
        )
        unchecked.extend(
            item for item in missing_required if item not in unchecked
        )

        pilot_only = any(
            rule.get("review_status") == "approved_for_pilot"
            for rule in applicable_rules
        )
        if pilot_only:
            unchecked.append("试点规则尚未完成生产发布审批")

        if findings:
            verdict_label = max(
                (finding["action"] for finding in findings),
                key=lambda item: VERDICT_PRIORITY[item],
            )
        elif unchecked:
            verdict_label = "待补充材料"
        else:
            verdict_label = "预检未发现风险"

        verdict_codes = {
            "禁止发布": "block_publish",
            "待法务复核": "manual_review_required",
            "需修改": "needs_revision",
            "待补充材料": "needs_materials",
            "预检未发现风险": "no_risk_found_within_coverage",
        }
        coverage_status = (
            "complete"
            if not unchecked and self.production_ready
            else "partial"
        )
        result = {
            "platform": SUPPORTED_PLATFORM,
            "scene": request["platform_scene"],
            "policy_snapshot_id": self.snapshot_id,
            "catalog_status": self.catalog["catalog_status"],
            "production_ready": self.production_ready,
            "verdict": verdict_codes[verdict_label],
            "verdict_label": verdict_label,
            "coverage_status": coverage_status,
            "coverage_reason": (
                "已检查当前载荷和已加载规则范围"
                if coverage_status == "complete"
                else "仍有素材、资质、场景或规则审批范围未覆盖"
            ),
            "checked_rule_ids": [rule["rule_id"] for rule in applicable_rules],
            "unchecked_materials": list(dict.fromkeys(unchecked)),
            "findings": findings,
            "checked_at": checked_at,
            "disclaimer": "平台规则预检不可替代小红书最终审核或人工法律复核。",
        }
        return {
            "platform_precheck": result,
            "审核_平台规则预检": self._summary(result),
        }, None

    @staticmethod
    def _summary(result: dict[str, Any]) -> str:
        lines = [
            f"【小红书平台预检】{result['verdict_label']}",
            f"场景：{result['scene']}",
            f"规则快照：{result.get('policy_snapshot_id') or '不可用'}",
            f"覆盖状态：{result['coverage_status']}",
        ]
        if result.get("findings"):
            lines.append("命中：" + "；".join(
                f"[{item['rule_id']}] {item['title']}"
                for item in result["findings"]
            ))
        if result.get("unchecked_materials"):
            lines.append("未覆盖：" + "、".join(result["unchecked_materials"]))
        lines.append("说明：仅为发布前预检，不代表平台最终审核结论。")
        return "\n".join(lines)

