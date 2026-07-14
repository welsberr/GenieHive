"""Small command-line client for the authenticated GenieHive admin API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import httpx


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="geniehive-admin")
    parser.add_argument("--base-url", default=os.environ.get("GENIEHIVE_BASE_URL", "http://127.0.0.1:8800"))
    parser.add_argument("--admin-key", default=os.environ.get("GENIEHIVE_ADMIN_KEY"))
    commands = parser.add_subparsers(dest="resource", required=True)

    client_key = commands.add_parser("client-key")
    client_commands = client_key.add_subparsers(dest="action", required=True)
    create = client_commands.add_parser("create")
    create.add_argument("--display-name", required=True)
    create.add_argument("--principal-type", required=True)
    create.add_argument("--principal-ref", required=True)
    create.add_argument("--key-id")
    create.add_argument("--role")
    create.add_argument("--allowed-model", action="append", default=[])
    create.add_argument("--allowed-operation", action="append", default=[])
    create.add_argument("--monthly-budget-cents", type=int)
    create.add_argument("--monthly-token-limit", type=int)
    create.add_argument("--notes")
    client_commands.add_parser("list")
    for action in ("enable", "disable"):
        command = client_commands.add_parser(action)
        command.add_argument("key_id")

    audit = commands.add_parser("audit")
    audit_commands = audit.add_subparsers(dest="action", required=True)
    requests = audit_commands.add_parser("list")
    requests.add_argument("--key-id")
    requests.add_argument("--principal-ref")
    requests.add_argument("--operation")
    requests.add_argument("--model")
    requests.add_argument("--success", choices=("true", "false"))
    requests.add_argument("--limit", type=int, default=100)
    audit_commands.add_parser("summary")
    return parser


def _url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + path


def _json_response(response: httpx.Response) -> None:
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("server returned malformed JSON") from exc
    print(json.dumps(_redact_key_hashes(payload), indent=2, sort_keys=True))


def _redact_key_hashes(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_key_hashes(item) for key, item in value.items() if key != "key_hash"}
    if isinstance(value, list):
        return [_redact_key_hashes(item) for item in value]
    return value


def _run(args: argparse.Namespace, client: Any) -> None:
    headers = {"X-Api-Key": args.admin_key}
    if args.resource == "client-key":
        if args.action == "create":
            payload = {
                "display_name": args.display_name,
                "principal_type": args.principal_type,
                "principal_ref": args.principal_ref,
                "allowed_models": args.allowed_model,
                "allowed_operations": args.allowed_operation,
            }
            for name in ("key_id", "role", "monthly_budget_cents", "monthly_token_limit", "notes"):
                value = getattr(args, name)
                if value is not None:
                    payload[name] = value
            _json_response(client.post(_url(args.base_url, "/v1/admin/client-keys"), headers=headers, json=payload))
        elif args.action == "list":
            _json_response(client.get(_url(args.base_url, "/v1/admin/client-keys"), headers=headers))
        else:
            _json_response(client.post(_url(args.base_url, f"/v1/admin/client-keys/{args.key_id}/{args.action}"), headers=headers))
        return

    if args.action == "summary":
        _json_response(client.get(_url(args.base_url, "/v1/admin/audit/summary"), headers=headers))
        return
    params = {
        key: value
        for key, value in {
            "key_id": args.key_id,
            "principal_ref": args.principal_ref,
            "operation": args.operation,
            "model": args.model,
            "success": args.success,
            "limit": args.limit,
        }.items()
        if value is not None
    }
    _json_response(client.get(_url(args.base_url, "/v1/admin/audit/requests"), headers=headers, params=params))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.admin_key:
        print("geniehive-admin: --admin-key or GENIEHIVE_ADMIN_KEY is required", file=sys.stderr)
        return 2
    try:
        with httpx.Client(timeout=30.0) as client:
            _run(args, client)
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        print(f"geniehive-admin: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
