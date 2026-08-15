from geniehive_control.decision_challenge import classify_control_change


def test_routine_approved_routing_is_exempt() -> None:
    payload = classify_control_change("resolve_route")
    assert payload["review_level"] == "none"
    assert payload["routine_routing_exempt"] is True


def test_provider_enablement_and_budget_change_are_standard() -> None:
    payload = classify_control_change("enable_provider", provider_enablement=True, budget_change=True)
    assert payload["review_level"] == "standard"
    assert set(payload["trigger_codes"]) == {"authority_or_capability_expansion", "high_resource_cost"}


def test_credential_or_tenancy_change_is_escalated() -> None:
    payload = classify_control_change("change_credentials", credential_change=True)
    assert payload["review_level"] == "escalated"
    assert "security_boundary_change" in payload["trigger_codes"]
