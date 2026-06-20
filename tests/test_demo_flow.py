from pathlib import Path

from geniehive_control.main import create_app as create_control_app
from geniehive_control.models import HostHeartbeat, HostRegistration
from geniehive_node.config import load_config as load_node_config
from geniehive_node.inventory import build_heartbeat_payload, build_registration_payload


def _write_demo_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "qwen3-demo.gguf").write_bytes(b"demo")

    roles_path = tmp_path / "roles.yaml"
    roles_path.write_text(
        "\n".join(
            [
                "roles:",
                '  - role_id: "mentor"',
                '    display_name: "Mentor"',
                '    operation: "chat"',
                '    modality: "text"',
                "    routing_policy:",
                '      preferred_families: ["qwen3"]',
                "      allow_employee_devices: true",
                '      allowed_device_classes: ["apple_silicon_mac"]',
            ]
        )
    )

    control_path = tmp_path / "control.yaml"
    control_path.write_text(
        "\n".join(
            [
                "auth:",
                "  client_api_keys:",
                '    - "client-key"',
                "  node_api_keys:",
                '    - "node-key"',
                "storage:",
                f'  sqlite_path: "{tmp_path / "state.sqlite3"}"',
                f'roles_path: "{roles_path}"',
            ]
        )
    )

    node_path = tmp_path / "node.yaml"
    node_path.write_text(
        "\n".join(
            [
                "node:",
                '  host_id: "atlas-01"',
                '  display_name: "Atlas GPU Box"',
                '  listen_host: "127.0.0.1"',
                "  listen_port: 8891",
                '  address: "192.168.1.101"',
                "control_plane:",
                '  base_url: "http://127.0.0.1:8800"',
                '  node_api_key: "node-key"',
                "inventory:",
                f'  model_roots:\n    - "{models_dir}"',
                '  trust_tier: "employee_device"',
                '  device_class: "apple_silicon_mac"',
                "  max_contribution_ram_gb: 24",
                "  workload_classes:",
                '    - "background"',
                "  idle_only: true",
                "  ac_power_only: true",
                "  capabilities:",
                "    cuda: true",
                "services:",
                '  - service_id: "atlas-01/chat/qwen3-8b"',
                '    kind: "chat"',
                '    endpoint: "http://127.0.0.1:18091"',
                "    assets:",
                '      - asset_id: "qwen3-8b-q4km"',
                "        loaded: true",
                "    state:",
                '      health: "healthy"',
                '      load_state: "loaded"',
                "      accept_requests: true",
                "    observed:",
                "      p50_latency_ms: 900",
            ]
        )
    )
    return control_path, node_path, roles_path


def test_demo_flow_registers_node_and_resolves_role(tmp_path: Path) -> None:
    control_path, node_path, _ = _write_demo_files(tmp_path)
    control_app = create_control_app(control_path)
    registry = control_app.state.registry
    node_cfg = load_node_config(node_path)

    registration = build_registration_payload(node_cfg)
    heartbeat = build_heartbeat_payload(node_cfg)
    assert registration["resources"]["trust_tier"] == "employee_device"
    assert registration["resources"]["device_class"] == "apple_silicon_mac"
    assert registration["resources"]["contribution_policy"]["max_ram_gb"] == 24
    assert registration["resources"]["contribution_policy"]["workload_classes"] == ["background"]
    assert registration["resources"]["contribution_policy"]["idle_only"] is True
    assert registration["resources"]["contribution_policy"]["ac_power_only"] is True

    host = registry.register_host(HostRegistration.model_validate(registration))
    assert host["host_id"] == "atlas-01"

    updated = registry.heartbeat_host(HostHeartbeat.model_validate(heartbeat))
    assert updated is not None
    assert updated["metrics"]["service_count"] == 1

    roles = registry.list_roles()
    assert len(roles) == 1
    assert roles[0]["role_id"] == "mentor"

    resolved = registry.resolve_route("mentor")
    assert resolved is not None
    assert resolved["match_type"] == "role"
    assert resolved["service"]["service_id"] == "atlas-01/chat/qwen3-8b"
