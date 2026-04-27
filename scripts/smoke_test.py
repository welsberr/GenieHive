#!/usr/bin/env python3
"""GenieHive end-to-end smoke test.

Validates every major path introduced through P1–P2: registration, catalog,
non-streaming chat, streaming chat, embeddings, direct asset addressing, route
resolution, and Ollama discovery metrics.

Usage:
    python scripts/smoke_test.py --base-url http://127.0.0.1:8800 \
                                 --api-key change-me-client-key

Optional:
    --chat-role    Role alias to use for chat tests   (default: auto-detected)
    --chat-asset   Direct asset ID to use for chat    (default: auto-detected)
    --embed-asset  Direct asset ID to use for embed   (default: auto-detected)

Exit codes:
    0  all checks passed (or skipped)
    1  one or more checks failed
"""
from __future__ import annotations

import argparse
import json
import sys
import textwrap
from dataclasses import dataclass, field
from typing import Any

import httpx

# ── Result tracking ───────────────────────────────────────────────────────────

PASS  = "PASS"
FAIL  = "FAIL"
SKIP  = "SKIP"


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""


@dataclass
class Suite:
    checks: list[Check] = field(default_factory=list)

    def record(self, name: str, status: str, detail: str = "") -> Check:
        c = Check(name, status, detail)
        self.checks.append(c)
        symbol = {"PASS": "✓", "FAIL": "✗", "SKIP": "–"}.get(status, "?")
        line = f"  [{symbol}] {name}"
        if detail:
            line += f"\n      {detail}"
        print(line)
        return c

    def ok(self, name: str, detail: str = "") -> Check:
        return self.record(name, PASS, detail)

    def fail(self, name: str, detail: str = "") -> Check:
        return self.record(name, FAIL, detail)

    def skip(self, name: str, reason: str = "") -> Check:
        return self.record(name, SKIP, reason)

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.status == FAIL]

    def summary(self) -> str:
        passed = sum(1 for c in self.checks if c.status == PASS)
        failed = len(self.failed)
        skipped = sum(1 for c in self.checks if c.status == SKIP)
        return f"{passed} passed, {failed} failed, {skipped} skipped"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _headers(api_key: str) -> dict[str, str]:
    return {"X-Api-Key": api_key}


def _json_headers(api_key: str) -> dict[str, str]:
    return {"X-Api-Key": api_key, "Content-Type": "application/json"}


def _short(text: str, max_len: int = 120) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= max_len else text[:max_len] + "…"


def _first_chat_role(models: list[dict]) -> str | None:
    for m in models:
        if m.get("geniehive", {}).get("route_type") == "role" and \
           m.get("geniehive", {}).get("operation") == "chat":
            return m["id"]
    return None


def _first_chat_asset(models: list[dict]) -> str | None:
    for m in models:
        if m.get("geniehive", {}).get("route_type") == "asset" and \
           m.get("geniehive", {}).get("operation") == "chat":
            return m["id"]
    return None


def _first_embed_asset(models: list[dict]) -> str | None:
    for m in models:
        if m.get("geniehive", {}).get("operation") == "embeddings":
            return m["id"]
    return None


# ── Individual checks ─────────────────────────────────────────────────────────

def check_health(client: httpx.Client, base: str, s: Suite) -> bool:
    try:
        r = client.get(f"{base}/health")
        if r.status_code == 200 and r.json().get("status") == "ok":
            s.ok("control plane health")
            return True
        s.fail("control plane health", f"status={r.status_code} body={_short(r.text)}")
    except Exception as exc:
        s.fail("control plane health", str(exc))
    return False


def check_cluster_state(client: httpx.Client, base: str, api_key: str, s: Suite) -> dict:
    """Returns {'hosts': [...], 'services': [...], 'roles': [...]} or partial."""
    result: dict[str, list] = {}
    for name, path in [("hosts", "/v1/cluster/hosts"),
                       ("services", "/v1/cluster/services"),
                       ("roles", "/v1/cluster/roles")]:
        try:
            r = client.get(f"{base}{path}", headers=_headers(api_key))
            if r.status_code == 200:
                data = r.json()
                items = data.get(name, data.get("data", []))
                result[name] = items
                s.ok(f"cluster {name} registered", f"{len(items)} {name}")
            else:
                s.fail(f"cluster {name} registered",
                       f"status={r.status_code} body={_short(r.text)}")
        except Exception as exc:
            s.fail(f"cluster {name} registered", str(exc))
    return result


def check_model_catalog(client: httpx.Client, base: str, api_key: str,
                        s: Suite) -> list[dict]:
    try:
        r = client.get(f"{base}/v1/models", headers=_headers(api_key))
        if r.status_code != 200:
            s.fail("model catalog GET /v1/models",
                   f"status={r.status_code} body={_short(r.text)}")
            return []
        models = r.json().get("data", [])
        role_count = sum(1 for m in models
                         if m.get("geniehive", {}).get("route_type") == "role")
        asset_count = sum(1 for m in models
                          if m.get("geniehive", {}).get("route_type") == "asset")
        s.ok("model catalog GET /v1/models",
             f"{len(models)} total ({role_count} roles, {asset_count} assets)")
        return models
    except Exception as exc:
        s.fail("model catalog GET /v1/models", str(exc))
        return []


def check_route_resolve(client: httpx.Client, base: str, api_key: str,
                        role: str, s: Suite) -> bool:
    try:
        r = client.get(f"{base}/v1/cluster/routes/resolve",
                       params={"model": role},
                       headers=_headers(api_key))
        if r.status_code == 200:
            data = r.json()
            svc_id = data.get("service", {}).get("service_id", "?")
            s.ok(f"route resolve '{role}'", f"→ {svc_id}")
            return True
        s.fail(f"route resolve '{role}'",
               f"status={r.status_code} body={_short(r.text)}")
    except Exception as exc:
        s.fail(f"route resolve '{role}'", str(exc))
    return False


def check_chat_nonstreaming(client: httpx.Client, base: str, api_key: str,
                            model: str, label: str, s: Suite) -> bool:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user",
                      "content": "Reply with exactly the word: ready"}],
        "max_tokens": 16,
    }
    try:
        r = client.post(f"{base}/v1/chat/completions",
                        headers=_json_headers(api_key),
                        json=body,
                        timeout=120.0)
        if r.status_code == 200:
            data = r.json()
            content = (data.get("choices", [{}])[0]
                       .get("message", {}).get("content", ""))
            s.ok(f"chat non-streaming [{label}]", f"model={data.get('model')} "
                 f"reply={_short(content, 60)!r}")
            return True
        s.fail(f"chat non-streaming [{label}]",
               f"status={r.status_code} body={_short(r.text)}")
    except Exception as exc:
        s.fail(f"chat non-streaming [{label}]", str(exc))
    return False


def check_chat_streaming(base: str, api_key: str, model: str, s: Suite) -> bool:
    """Sends a streaming chat request and validates the SSE response."""
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user",
                      "content": "Reply with exactly the word: streaming"}],
        "max_tokens": 16,
        "stream": True,
    }
    url = f"{base.rstrip('/')}/v1/chat/completions"
    try:
        chunk_count = 0
        content_parts: list[str] = []
        got_done = False
        with httpx.stream("POST", url,
                          headers=_json_headers(api_key),
                          json=body,
                          timeout=120.0) as resp:
            if resp.status_code != 200:
                body_text = resp.read().decode(errors="replace")
                s.fail("chat streaming", f"status={resp.status_code} {_short(body_text)}")
                return False
            ct = resp.headers.get("content-type", "")
            if "text/event-stream" not in ct:
                s.fail("chat streaming",
                       f"expected text/event-stream content-type, got: {ct!r}")
                return False
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    got_done = True
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                chunk_count += 1
                delta = (chunk.get("choices", [{}])[0]
                         .get("delta", {}).get("content") or "")
                if delta:
                    content_parts.append(delta)
                # reasoning fields must have been stripped
                delta_obj = chunk.get("choices", [{}])[0].get("delta", {})
                if "reasoning_content" in delta_obj or "reasoning" in chunk:
                    s.fail("chat streaming",
                           "reasoning fields not stripped from SSE chunk")
                    return False

        if not got_done:
            s.fail("chat streaming", "stream ended without [DONE] sentinel")
            return False
        reply = "".join(content_parts)
        s.ok("chat streaming",
             f"{chunk_count} data chunks, reply={_short(reply, 60)!r}")
        return True
    except Exception as exc:
        s.fail("chat streaming", str(exc))
        return False


def check_embeddings(client: httpx.Client, base: str, api_key: str,
                     model: str, s: Suite) -> bool:
    body = {"model": model, "input": "GenieHive smoke test embedding probe."}
    try:
        r = client.post(f"{base}/v1/embeddings",
                        headers=_json_headers(api_key),
                        json=body,
                        timeout=60.0)
        if r.status_code == 200:
            data = r.json()
            vec = data.get("data", [{}])[0].get("embedding", [])
            s.ok("embeddings", f"model={data.get('model')} dims={len(vec)}")
            return True
        s.fail("embeddings", f"status={r.status_code} body={_short(r.text)}")
    except Exception as exc:
        s.fail("embeddings", str(exc))
    return False


def check_ollama_discovery_metrics(services: list[dict], s: Suite) -> None:
    """Checks that at least one Ollama-backed service has loaded_model_count populated."""
    ollama_services = [
        svc for svc in services
        if svc.get("runtime", {}).get("engine") == "ollama"
        or "ollama" in svc.get("service_id", "").lower()
    ]
    if not ollama_services:
        s.skip("Ollama discovery metrics",
               "no Ollama-backed services registered — "
               "set discover_protocol: ollama in node config to enable")
        return
    populated = [
        svc for svc in ollama_services
        if svc.get("observed", {}).get("loaded_model_count") is not None
    ]
    if populated:
        examples = ", ".join(
            f"{svc['service_id']}:"
            f"loaded_model_count={svc['observed']['loaded_model_count']}"
            for svc in populated[:2]
        )
        s.ok("Ollama discovery metrics", examples)
    else:
        s.fail("Ollama discovery metrics",
               f"{len(ollama_services)} Ollama service(s) registered but "
               "observed.loaded_model_count is null — "
               "check that discover_protocol: ollama is set and a heartbeat has completed")


def check_reasoning_stripped(client: httpx.Client, base: str, api_key: str,
                              model: str, s: Suite) -> None:
    """Checks that reasoning_content is absent from non-streaming responses."""
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
        "max_tokens": 8,
    }
    try:
        r = client.post(f"{base}/v1/chat/completions",
                        headers=_json_headers(api_key),
                        json=body,
                        timeout=60.0)
        if r.status_code != 200:
            s.skip("reasoning fields stripped",
                   f"chat returned {r.status_code} — skipping strip check")
            return
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {})
        if "reasoning_content" in msg or "reasoning" in choice:
            s.fail("reasoning fields stripped",
                   "reasoning_content or reasoning present in response")
        else:
            s.ok("reasoning fields stripped")
    except Exception as exc:
        s.skip("reasoning fields stripped", str(exc))


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="GenieHive end-to-end smoke test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(__doc__ or ""),
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8800",
                        help="GenieHive control-plane base URL")
    parser.add_argument("--api-key", default="change-me-client-key",
                        help="GenieHive client API key")
    parser.add_argument("--chat-role",
                        help="Role alias to use for chat tests (auto-detected if omitted)")
    parser.add_argument("--chat-asset",
                        help="Direct asset ID for chat tests (auto-detected if omitted)")
    parser.add_argument("--embed-asset",
                        help="Direct asset ID for embeddings tests (auto-detected if omitted)")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    s = Suite()

    print(f"\nGenieHive smoke test → {base}\n")

    with httpx.Client(timeout=30.0) as client:
        # ── 1. Health ──────────────────────────────────────────────────────────
        if not check_health(client, base, s):
            print(f"\nControl plane unreachable — aborting.\n{s.summary()}")
            sys.exit(1)

        # ── 2. Cluster state ───────────────────────────────────────────────────
        cluster = check_cluster_state(client, base, args.api_key, s)
        services = cluster.get("services", [])

        # ── 3. Model catalog ───────────────────────────────────────────────────
        models = check_model_catalog(client, base, args.api_key, s)

        # ── 4. Detect targets ──────────────────────────────────────────────────
        chat_role  = args.chat_role  or _first_chat_role(models)
        chat_asset = args.chat_asset or _first_chat_asset(models)
        embed_asset = args.embed_asset or _first_embed_asset(models)

        # ── 5. Route resolution ────────────────────────────────────────────────
        if chat_role:
            check_route_resolve(client, base, args.api_key, chat_role, s)
        else:
            s.skip("route resolve", "no chat role in catalog")

        # ── 6. Non-streaming chat via role ─────────────────────────────────────
        if chat_role:
            ok = check_chat_nonstreaming(
                client, base, args.api_key, chat_role, f"role={chat_role}", s)
            if ok:
                check_reasoning_stripped(client, base, args.api_key, chat_role, s)
        else:
            s.skip("chat non-streaming [role]", "no chat role in catalog")
            s.skip("reasoning fields stripped", "no chat role in catalog")

        # ── 7. Non-streaming chat via direct asset ─────────────────────────────
        if chat_asset:
            check_chat_nonstreaming(
                client, base, args.api_key, chat_asset, f"asset={chat_asset}", s)
        else:
            s.skip("chat non-streaming [direct asset]", "no chat asset in catalog")

    # ── 8. Streaming chat (requires its own httpx.stream context) ─────────────
    if chat_role:
        check_chat_streaming(base, args.api_key, chat_role, s)
    else:
        s.skip("chat streaming", "no chat role in catalog")

    # ── 9. Embeddings ──────────────────────────────────────────────────────────
    with httpx.Client(timeout=60.0) as client:
        if embed_asset:
            check_embeddings(client, base, args.api_key, embed_asset, s)
        else:
            s.skip("embeddings", "no embeddings asset in catalog")

        # ── 10. Ollama discovery metrics ───────────────────────────────────────
        check_ollama_discovery_metrics(services, s)

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{s.summary()}")
    if s.failed:
        print("\nFailed checks:")
        for c in s.failed:
            print(f"  • {c.name}: {c.detail}")
        sys.exit(1)


if __name__ == "__main__":
    main()
