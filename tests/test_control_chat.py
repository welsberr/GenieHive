import asyncio
from pathlib import Path

from geniehive_control.chat import ProxyError, proxy_chat_completion, proxy_embeddings
from geniehive_control.models import HostRegistration, RegisteredService, RoleProfile
from geniehive_control.registry import Registry
from geniehive_control.upstream import UpstreamClient


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class _FakePoster:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def post(self, url: str, *, json: dict, headers: dict[str, str] | None = None) -> _FakeResponse:
        self.calls.append({"url": url, "json": json, "headers": headers or {}})
        return _FakeResponse({"ok": True, "echo_model": json["model"]})


def _build_registry(tmp_path: Path) -> Registry:
    registry = Registry(tmp_path / "geniehive.sqlite3")
    registry.register_host(
        HostRegistration(
            host_id="atlas-01",
            address="192.168.1.101",
            services=[
                RegisteredService(
                    service_id="atlas-01/chat/qwen3-8b",
                    host_id="atlas-01",
                    kind="chat",
                    endpoint="http://192.168.1.101:18091",
                    assets=[{"asset_id": "qwen3-8b-q4km", "loaded": True}],
                    state={"health": "healthy", "load_state": "loaded", "accept_requests": True},
                    observed={"p50_latency_ms": 900},
                ),
                RegisteredService(
                    service_id="atlas-01/embeddings/bge-small",
                    host_id="atlas-01",
                    kind="embeddings",
                    endpoint="http://192.168.1.101:18092",
                    assets=[{"asset_id": "bge-small-en", "loaded": True}],
                    state={"health": "healthy", "load_state": "loaded", "accept_requests": True},
                    observed={"p50_latency_ms": 120},
                )
            ],
        )
    )
    registry.upsert_roles(
        [
            RoleProfile(
                role_id="mentor",
                display_name="Mentor",
                operation="chat",
                modality="text",
                routing_policy={"preferred_families": ["qwen3"]},
            ),
            RoleProfile(
                role_id="embedder",
                display_name="Embedder",
                operation="embeddings",
                modality="text",
                routing_policy={"require_loaded": True},
            )
        ]
    )
    return registry


def test_proxy_chat_completion_rewrites_role_to_loaded_asset(tmp_path: Path) -> None:
    registry = _build_registry(tmp_path)
    fake = _FakePoster()
    upstream = UpstreamClient(client=fake)

    async def run() -> dict:
        return await proxy_chat_completion(
            {
                "model": "mentor",
                "messages": [{"role": "user", "content": "hello"}],
            },
            registry=registry,
            upstream=upstream,
        )

    result = asyncio.run(run())
    assert result["ok"] is True
    assert result["echo_model"] == "qwen3-8b-q4km"
    assert fake.calls[0]["url"] == "http://192.168.1.101:18091/v1/chat/completions"
    assert fake.calls[0]["json"]["model"] == "qwen3-8b-q4km"


def test_proxy_chat_completion_preserves_direct_asset_match(tmp_path: Path) -> None:
    registry = _build_registry(tmp_path)
    fake = _FakePoster()
    upstream = UpstreamClient(client=fake)

    async def run() -> dict:
        return await proxy_chat_completion(
            {
                "model": "qwen3-8b-q4km",
                "messages": [{"role": "user", "content": "hello"}],
            },
            registry=registry,
            upstream=upstream,
        )

    result = asyncio.run(run())
    assert result["echo_model"] == "qwen3-8b-q4km"


def test_proxy_chat_completion_strips_reasoning_fields(tmp_path: Path) -> None:
    registry = _build_registry(tmp_path)

    class _ReasoningPoster:
        async def post(self, url: str, *, json: dict, headers: dict[str, str] | None = None) -> _FakeResponse:
            return _FakeResponse(
                {
                    "object": "chat.completion",
                    "model": json["model"],
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "GPU1 route is live.",
                                "reasoning_content": "hidden chain of thought",
                            },
                            "reasoning": {"tokens": 42},
                        }
                    ],
                }
            )

    upstream = UpstreamClient(client=_ReasoningPoster())

    async def run() -> dict:
        return await proxy_chat_completion(
            {
                "model": "mentor",
                "messages": [{"role": "user", "content": "hello"}],
            },
            registry=registry,
            upstream=upstream,
        )

    result = asyncio.run(run())
    choice = result["choices"][0]
    assert choice["message"]["content"] == "GPU1 route is live."
    assert "reasoning_content" not in choice["message"]
    assert "reasoning" not in choice


def test_proxy_chat_completion_applies_inferred_qwen_request_defaults(tmp_path: Path) -> None:
    registry = _build_registry(tmp_path)

    class _InspectingPoster:
        async def post(self, url: str, *, json: dict, headers: dict[str, str] | None = None) -> _FakeResponse:
            assert json["chat_template_kwargs"] == {"enable_thinking": False}
            return _FakeResponse({"ok": True, "echo_model": json["model"]})

    upstream = UpstreamClient(client=_InspectingPoster())

    async def run() -> dict:
        return await proxy_chat_completion(
            {
                "model": "mentor",
                "messages": [{"role": "user", "content": "hello"}],
            },
            registry=registry,
            upstream=upstream,
        )

    result = asyncio.run(run())
    assert result["echo_model"] == "qwen3-8b-q4km"


def test_proxy_chat_completion_preserves_explicit_template_kwargs(tmp_path: Path) -> None:
    registry = _build_registry(tmp_path)

    class _InspectingPoster:
        async def post(self, url: str, *, json: dict, headers: dict[str, str] | None = None) -> _FakeResponse:
            assert json["chat_template_kwargs"] == {"enable_thinking": True, "foo": "bar"}
            return _FakeResponse({"ok": True, "echo_model": json["model"]})

    upstream = UpstreamClient(client=_InspectingPoster())

    async def run() -> dict:
        return await proxy_chat_completion(
            {
                "model": "mentor",
                "messages": [{"role": "user", "content": "hello"}],
                "chat_template_kwargs": {"enable_thinking": True, "foo": "bar"},
            },
            registry=registry,
            upstream=upstream,
        )

    result = asyncio.run(run())
    assert result["echo_model"] == "qwen3-8b-q4km"


def test_proxy_chat_completion_applies_asset_request_policy(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "geniehive.sqlite3")
    registry.register_host(
        HostRegistration(
            host_id="atlas-01",
            address="192.168.1.101",
            services=[
                RegisteredService(
                    service_id="atlas-01/chat/custom-model",
                    host_id="atlas-01",
                    kind="chat",
                    endpoint="http://192.168.1.101:18091",
                    assets=[
                        {
                            "asset_id": "custom-model-v1",
                            "loaded": True,
                            "request_policy": {
                                "body_defaults": {
                                    "temperature": 0.2,
                                    "chat_template_kwargs": {"custom_flag": "yes"},
                                }
                            },
                        }
                    ],
                    state={"health": "healthy", "load_state": "loaded", "accept_requests": True},
                    observed={"p50_latency_ms": 900},
                )
            ],
        )
    )

    class _InspectingPoster:
        async def post(self, url: str, *, json: dict, headers: dict[str, str] | None = None) -> _FakeResponse:
            assert json["temperature"] == 0.2
            assert json["chat_template_kwargs"] == {"custom_flag": "yes"}
            return _FakeResponse({"ok": True, "echo_model": json["model"]})

    upstream = UpstreamClient(client=_InspectingPoster())

    async def run() -> dict:
        return await proxy_chat_completion(
            {
                "model": "custom-model-v1",
                "messages": [{"role": "user", "content": "hello"}],
            },
            registry=registry,
            upstream=upstream,
        )

    result = asyncio.run(run())
    assert result["echo_model"] == "custom-model-v1"


def test_proxy_chat_completion_fails_for_unknown_model(tmp_path: Path) -> None:
    registry = _build_registry(tmp_path)
    upstream = UpstreamClient(client=_FakePoster())

    async def run() -> None:
        await proxy_chat_completion(
            {
                "model": "unknown-model",
                "messages": [{"role": "user", "content": "hello"}],
            },
            registry=registry,
            upstream=upstream,
        )

    try:
        asyncio.run(run())
    except ProxyError as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("expected ChatProxyError")


def test_proxy_embeddings_rewrites_role_to_loaded_asset(tmp_path: Path) -> None:
    registry = _build_registry(tmp_path)
    fake = _FakePoster()
    upstream = UpstreamClient(client=fake)

    async def run() -> dict:
        return await proxy_embeddings(
            {
                "model": "embedder",
                "input": "hello",
            },
            registry=registry,
            upstream=upstream,
        )

    result = asyncio.run(run())
    assert result["ok"] is True
    assert result["echo_model"] == "bge-small-en"
    assert fake.calls[0]["url"] == "http://192.168.1.101:18092/v1/embeddings"
    assert fake.calls[0]["json"]["model"] == "bge-small-en"


def test_proxy_embeddings_fails_for_unknown_model(tmp_path: Path) -> None:
    registry = _build_registry(tmp_path)
    upstream = UpstreamClient(client=_FakePoster())

    async def run() -> None:
        await proxy_embeddings(
            {
                "model": "unknown-embedder",
                "input": "hello",
            },
            registry=registry,
            upstream=upstream,
        )

    try:
        asyncio.run(run())
    except ProxyError as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("expected ProxyError")
