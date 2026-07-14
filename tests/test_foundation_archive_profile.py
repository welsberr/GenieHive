from pathlib import Path

from geniehive_control.config import load_config
from geniehive_control.roles import load_role_catalog


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "configs/roles.foundation.archive.yaml"


def test_foundation_archive_catalog_has_five_provider_neutral_roles() -> None:
    catalog = load_role_catalog(CATALOG_PATH)
    role_ids = [role.role_id for role in catalog.roles]

    assert role_ids == [
        "archive_migrator",
        "archive_metadata_extractor",
        "archive_link_reviewer",
        "archive_copyeditor",
        "archive_factcheck_assistant",
    ]
    assert len(role_ids) == len(set(role_ids))
    assert all(role.operation == "chat" for role in catalog.roles)
    assert all(role.modality == "text" for role in catalog.roles)
    assert all(role.prompt_policy.system_prompt for role in catalog.roles)
    assert all(role.routing_policy.min_context == 8192 for role in catalog.roles)


def test_foundation_archive_catalog_contains_no_provider_endpoints_or_credentials() -> None:
    raw_text = CATALOG_PATH.read_text()

    assert "api_key" not in raw_text.lower()
    assert "base_url" not in raw_text.lower()
    assert "https://" not in raw_text.lower()


def test_foundation_control_config_loads_archive_catalog() -> None:
    config = load_config(ROOT / "configs/control.foundation.example.yaml")

    assert config.roles_path == "configs/roles.foundation.archive.yaml"
    catalog = load_role_catalog(ROOT / config.roles_path)
    assert {role.role_id for role in catalog.roles} == {
        "archive_migrator",
        "archive_metadata_extractor",
        "archive_link_reviewer",
        "archive_copyeditor",
        "archive_factcheck_assistant",
    }
