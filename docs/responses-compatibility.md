# Local Codex through GenieHive

`POST /v1/responses` adapts text and tool requests to the existing Chat
Completions route. It uses the same client authentication, model/operation
authorization, budget enforcement, route selection and chat audit machinery.
No second routing registry or standalone protocol service is required.

The initial implementation supports full input history, text messages,
function calls, custom tool calls (including apply_patch), tool outputs, and
namespaced tools. Custom tools are exposed upstream as functions with one
`input` string and converted back to custom calls for the client. The upstream
does not enforce the custom tool's grammar; the client still validates and
executes the tool. The adapter never executes tools itself.

Generation is buffered upstream, then emitted as ordered Responses SSE
events when `stream: true`. Token-by-token delivery and cancellation during
generation are not yet qualified. Truncated tool calls and malformed tool
arguments fail with HTTP 502 rather than being executed. Upstream HTTP errors
are preserved before starting the event stream. Successful HTTP upstream
requests are audited by the chat handler; a subsequent conversion failure
does not currently revise that audit entry.

This is a stateless subset, not the complete Responses API. Send full history
on every request. Previous response IDs, conversations, background requests,
hosted tools, multimodal content and structured final output are rejected.
There is no Responses retrieval, storage or remote compaction endpoint.
Model-specific reasoning items in replayed history are omitted.

## Codex settings

Point a separate Codex configuration at the isolated GenieHive instance:

```toml
model = "strata-q2"
model_provider = "geniehive_local"
model_context_window = 16384
model_auto_compact_token_limit = 14000
model_reasoning_summary = "none"
web_search = "disabled"

[model_providers.geniehive_local]
name = "Local Strata through GenieHive"
base_url = "http://127.0.0.1:18421/v1"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
stream_idle_timeout_ms = 300000

[model_providers.geniehive_local.env_http_headers]
X-Api-Key = "GENIEHIVE_LOCAL_CLIENT_KEY"
```

Use a separate Codex state directory and `--no-daemon` for isolation. The
synthetic acceptance harness additionally disables optional integrations and
telemetry and supplies short task-specific model instructions to fit 16K.

For confidential data, register only the intended local service in a dedicated
GenieHive instance and omit external providers and fallback roles. Localhost
binding and this adapter alone do not enforce outbound network isolation or
protect files from other processes running under the same account. A private
tax workspace still requires separate storage and OS-enforced isolation.

## Validation

`tests/test_responses.py` exercises conversion, event sequencing, authentication,
unsupported input rejection, truncated tool rejection and upstream errors.
Run alongside the normal GenieHive regression suite. Synthetic live evidence
and the repeatable harness live in the local research workspace under
`strata-codex-evaluation/geniehive_probe.py`; they are not committed here.

Protocol reference: [Responses streaming events](https://developers.openai.com/api/reference/resources/responses/streaming-events).
