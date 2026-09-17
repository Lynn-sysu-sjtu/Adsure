# -*- coding: utf-8 -*-
"""Deterministic applicability checks shared by every recall channel."""


PLATFORM_WILDCARDS = {"*", "all", "any", "\u901a\u7528", "\u5168\u90e8", "\u4e0d\u9650"}


def _values(value):
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def declared_platforms(rule):
    applies_to = rule.get("applies_to") or {}
    declared = _values(applies_to.get("platforms")) + _values(rule.get("platform"))
    normalized = {item.casefold() for item in declared}
    return {item for item in normalized if item not in PLATFORM_WILDCARDS}


def requested_platforms(request):
    context = request.get("context") or {}
    selected = context.get("platforms")
    if selected in (None, ""):
        selected = context.get("platform")
    return {item.casefold() for item in _values(selected)}


def platform_scope_matches(rule, request):
    required = declared_platforms(rule)
    if not required:
        return True
    selected = requested_platforms(request)
    return bool(selected and required.intersection(selected))
