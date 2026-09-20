"""Small deployment-level feature flags with compatibility-off defaults."""

from __future__ import annotations


def enabled(name: str) -> bool:
    """Return True only for an explicitly enabled boolean config value."""
    try:
        import config
    except ImportError:
        return False
    return getattr(config, name, False) is True


def ops_enabled() -> bool:
    return enabled("ADSURE_OPS_ENABLED")


def legal_card_sync_enabled() -> bool:
    return enabled("ADSURE_LEGAL_CARD_SYNC_ENABLED")


def audit_timeline_enabled() -> bool:
    return enabled("ADSURE_AUDIT_TIMELINE_ENABLED")


def memory_center_available() -> bool:
    return enabled("ADSURE_MEMORY_CENTER_AVAILABLE")
