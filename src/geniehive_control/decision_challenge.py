"""Bounded review classification for GenieHive control-plane changes."""

from __future__ import annotations

from typing import Any


def classify_control_change(
    action: str,
    *,
    provider_enablement: bool = False,
    budget_change: bool = False,
    credential_change: bool = False,
    tenancy_change: bool = False,
    model_swap: bool = False,
    native_adapter: bool = False,
) -> dict[str, Any]:
    if not action.strip():
        raise ValueError("action is required")
    triggers: list[str] = []
    if provider_enablement:
        triggers.append("authority_or_capability_expansion")
    if budget_change:
        triggers.append("high_resource_cost")
    if credential_change or tenancy_change:
        triggers.append("security_boundary_change")
    if model_swap or native_adapter:
        triggers.append("novel_or_unfamiliar_path")
    level = "escalated" if credential_change or tenancy_change else "standard" if triggers else "none"
    return {
        "schema_version": "geniehive.decision_challenge_classification.v1",
        "action": action,
        "review_level": level,
        "trigger_codes": sorted(set(triggers)),
        "routine_routing_exempt": not triggers,
        "authority": "classification only; routing, credentials, budgets, and provider policy remain authoritative.",
    }
