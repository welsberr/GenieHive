from pathlib import Path

from geniehive_control.keys import generate_api_key, hash_api_key, redact_api_key, verify_api_key
from geniehive_control.registry import Registry


def test_api_key_hash_verify_and_redact() -> None:
    raw_key = generate_api_key(prefix="gh_test")
    key_hash = hash_api_key(raw_key, secret="test-secret")

    assert raw_key.startswith("gh_test_")
    assert key_hash.startswith("hmac-sha256:")
    assert verify_api_key(raw_key, key_hash, secret="test-secret") is True
    assert verify_api_key(raw_key + "-wrong", key_hash, secret="test-secret") is False
    assert verify_api_key(raw_key, key_hash, secret="other-secret") is False
    assert raw_key not in redact_api_key(raw_key)


def test_registry_client_key_lifecycle(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "geniehive.sqlite3")
    raw_key = "gh_test_secret"
    key_hash = hash_api_key(raw_key, secret="test-secret")

    created = registry.create_client_key(
        key_id="ck_test",
        key_hash=key_hash,
        display_name="Test User",
        principal_type="person",
        principal_ref="test-user",
        role="developer",
        allowed_models=["archive_migrator"],
        allowed_operations=["chat"],
        monthly_budget_cents=1000,
        monthly_token_limit=20000,
        notes="created by test",
    )

    assert created["key_id"] == "ck_test"
    assert created["key_hash"] == key_hash
    assert created["display_name"] == "Test User"
    assert created["allowed_models"] == ["archive_migrator"]
    assert created["allowed_operations"] == ["chat"]
    assert created["enabled"] is True
    assert created["last_used_at"] is None

    listed = registry.list_client_keys()
    assert [item["key_id"] for item in listed] == ["ck_test"]

    by_hash = registry.get_client_key_by_hash(key_hash)
    assert by_hash is not None
    assert by_hash["principal_ref"] == "test-user"

    disabled = registry.set_client_key_enabled("ck_test", False)
    assert disabled is not None
    assert disabled["enabled"] is False

    registry.touch_client_key("ck_test")
    touched = registry.get_client_key("ck_test")
    assert touched is not None
    assert touched["last_used_at"] is not None
