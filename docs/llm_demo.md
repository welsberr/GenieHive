# GenieHive LLM Demo

This runbook covers the first practical GenieHive LLM demo with three roles:

- master: the GenieHive control plane
- peer: a GenieHive node agent attached to one or more local LLM servers
- client: a demo client agent or Codex using GenieHive as the API front door

## Current Readiness

GenieHive is ready for a first live chat demo now.

What works in GenieHive already:

- node registration
- heartbeat
- role-aware route resolution
- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/embeddings`

What GenieHive does not do yet:

- launch upstream LLM servers for you automatically
- provide `POST /v1/audio/transcriptions`
- maintain advanced benchmark history or queue-aware scheduling

For the first demo, treat GenieHive as a metadata-rich router over already-running local servers.

## Topologies

### Smallest Demo

Run everything on one host:

- control plane on `127.0.0.1:8800`
- node agent on `127.0.0.1:8891`
- one or more upstream model servers on local ports

This is also the recommended setup for users who do not have a cluster. GenieHive still provides value as:

- a local router
- a metadata-rich local model catalog
- a role-to-model indirection layer
- a common front door for client tools

### Two-Host Demo

- master host runs GenieHive control plane
- peer host runs GenieHive node agent and one or more local LLM servers
- client runs anywhere that can reach the master

## Master Instructions

On the control-plane host:

1. Create a repo-local Python environment if you want isolation.
2. Start GenieHive control:

```bash
cd /home/netuser/bin/geniehive
bash scripts/run_control.sh
```

3. Confirm health:

```bash
curl -sS http://127.0.0.1:8800/health
```

Expected result:

- JSON containing `{"status":"ok"}`

4. Keep note of the example client and node keys from `configs/control.example.yaml`.

### Single-Box Shortcut

If you are running control and node on the same machine, use:

```bash
cd /home/netuser/bin/geniehive
bash scripts/run_control_singlebox.sh
```

For your P40 host, repo-provided external bind helpers now exist:

LAN:

```bash
bash scripts/run_control_p40_lan.sh
```

ZeroTier:

```bash
bash scripts/run_control_p40_zerotier.sh
```

Both use the P40-specific control config and only change the bind interface.

## Peer Instructions

On each peer host you need:

- one or more local LLM servers already running
- one GenieHive node config that points at those servers
- the control-plane base URL and node API key

For a single-machine setup, the peer is simply another process on the same host.

The node agent should advertise upstream server roots, not endpoint suffixes. For example:

- good: `http://127.0.0.1:11434`
- good: `http://127.0.0.1:18091`
- not good: `http://127.0.0.1:11434/v1/chat/completions`

### Option A: Ollama

Use this when you want the lowest-friction chat and embeddings demo.

1. Start Ollama if it is not already running:

```bash
ollama serve
```

2. Pull the model or models you want:

```bash
ollama pull qwen3
ollama pull nomic-embed-text
```

3. Example peer service config:

```yaml
services:
  - service_id: "peer1/chat/qwen3"
    kind: "chat"
    endpoint: "http://127.0.0.1:11434"
    runtime:
      engine: "ollama"
      launcher: "external"
    assets:
      - asset_id: "qwen3"
        loaded: true
    state:
      health: "healthy"
      load_state: "loaded"
      accept_requests: true

  - service_id: "peer1/embeddings/nomic-embed-text"
    kind: "embeddings"
    endpoint: "http://127.0.0.1:11434"
    runtime:
      engine: "ollama"
      launcher: "external"
    assets:
      - asset_id: "nomic-embed-text"
        loaded: true
    state:
      health: "healthy"
      load_state: "loaded"
      accept_requests: true
```

4. Start the node:

```bash
cd /home/netuser/bin/geniehive
bash scripts/run_node_singlebox.sh configs/node.singlebox.ollama.example.yaml
```

### Option B: llama.cpp

Use this when you want direct GGUF serving with `llama-server`.

1. Start a chat server:

```bash
llama-server -m /path/to/model.gguf --host 127.0.0.1 --port 18091
```

2. Example peer service config:

```yaml
services:
  - service_id: "peer1/chat/qwen3-8b"
    kind: "chat"
    endpoint: "http://127.0.0.1:18091"
    runtime:
      engine: "llama.cpp"
      launcher: "external"
    assets:
      - asset_id: "qwen3-8b-q4_k_m"
        loaded: true
    state:
      health: "healthy"
      load_state: "loaded"
      accept_requests: true
```

Then start the node:

```bash
cd /home/netuser/bin/geniehive
bash scripts/run_node_singlebox.sh configs/node.singlebox.llamacpp.example.yaml
```

Note:

- The official `llama.cpp` docs clearly show OpenAI-compatible chat serving.
- For embeddings, some `llama.cpp` builds document non-OpenAI embedding endpoints such as `/embedding`, so GenieHive’s current `POST /v1/embeddings` path is safest with Ollama or vLLM unless you have verified your specific build.

### Option C: llamafile

Use this when you want a single-file local server built around llama.cpp.

1. Start a chat server:

```bash
./your-model.llamafile --server --host 127.0.0.1 --port 18091 --nobrowser
```

2. Example peer service config:

```yaml
services:
  - service_id: "peer1/chat/llamafile-qwen3"
    kind: "chat"
    endpoint: "http://127.0.0.1:18091"
    runtime:
      engine: "llamafile"
      launcher: "external"
    assets:
      - asset_id: "qwen3-8b-q4_k_m"
        loaded: true
    state:
      health: "healthy"
      load_state: "loaded"
      accept_requests: true
```

Then start the node:

```bash
cd /home/netuser/bin/geniehive
bash scripts/run_node_singlebox.sh configs/node.singlebox.llamafile.example.yaml
```

### Option D: vLLM

Use this when you want a more server-oriented OpenAI-compatible stack and you have the hardware budget for it.

1. Start the server:

```bash
vllm serve NousResearch/Meta-Llama-3-8B-Instruct --dtype auto --api-key token-abc123
```

2. Example peer service config:

```yaml
services:
  - service_id: "peer1/chat/llama3-8b"
    kind: "chat"
    endpoint: "http://127.0.0.1:8000"
    runtime:
      engine: "vllm"
      launcher: "external"
    assets:
      - asset_id: "NousResearch/Meta-Llama-3-8B-Instruct"
        loaded: true
    state:
      health: "healthy"
      load_state: "loaded"
      accept_requests: true

  - service_id: "peer1/embeddings/bge-base"
    kind: "embeddings"
    endpoint: "http://127.0.0.1:8001"
    runtime:
      engine: "vllm"
      launcher: "external"
    assets:
      - asset_id: "BAAI/bge-base-en-v1.5"
        loaded: true
    state:
      health: "healthy"
      load_state: "loaded"
      accept_requests: true
```

## Minimal Node Config Pattern

For a real peer host, the fields you most likely need to edit in `configs/node.example.yaml` are:

- `node.host_id`
- `node.display_name`
- `node.address`
- `control_plane.base_url`
- `control_plane.node_api_key`
- `inventory.capabilities`
- `services`

## Client Instructions

You now have two simple ways to exercise GenieHive as a client.

### Option 1: Inspect and call it manually

List models:

```bash
curl -sS http://127.0.0.1:8800/v1/models \
  -H 'X-Api-Key: change-me-client-key'
```

Chat using a role:

```bash
curl -sS http://127.0.0.1:8800/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'X-Api-Key: change-me-client-key' \
  -d '{
    "model": "mentor",
    "messages": [{"role":"user","content":"Give me a 2-sentence summary of why SQLite is useful here."}]
  }'
```

Embeddings using a direct embedding asset:

```bash
curl -sS http://127.0.0.1:8800/v1/embeddings \
  -H 'Content-Type: application/json' \
  -H 'X-Api-Key: change-me-client-key' \
  -d '{
    "model": "nomic-embed-text",
    "input": "GenieHive is a local-first control plane."
  }'
```

### Option 2: Use the demo client agent

Run:

```bash
cd /home/netuser/bin/geniehive
python scripts/demo_client_agent.py \
  --base-url http://127.0.0.1:8800 \
  --api-key change-me-client-key \
  --task "Summarize the current GenieHive demo in three bullets."
```

That script will:

- read `GET /v1/models`
- choose a chat-capable model automatically if you do not specify one
- prefer entries GenieHive marks as suitable for lower-complexity offload
- submit a chat request and print the answer

If you want to force a specific route:

```bash
python scripts/demo_client_agent.py \
  --base-url http://127.0.0.1:8800 \
  --api-key change-me-client-key \
  --model mentor \
  --task "State what host and route type you would expect for this demo."
```

## Codex-As-Client

For Codex or another agentic client, the intended pattern is:

1. Read `GET /v1/models`.
2. Filter for `geniehive.operation == "chat"`.
3. Prefer:
   - `geniehive.offload_hint.suitability == "good_for_low_complexity"`
   - `geniehive.loaded_target_count > 0` for role entries
   - lower `best_p50_latency_ms`
4. Send lower-complexity requests to GenieHive.
5. Keep higher-complexity, high-context, or high-risk tasks local unless the catalog indicates a better remote fit.

## Good First Live Demo

If you want the safest first success path:

- control plane on one host
- node agent on the same host
- Ollama upstream with one chat model
- role alias `mentor`
- demo client agent calling `mentor`

That avoids GGUF-specific launch tuning while still exercising the full GenieHive master/peer/client path.

## Single-Machine End-to-End Example

### Ollama-backed single box

1. Start Ollama:

```bash
ollama serve
```

2. Pull models:

```bash
ollama pull qwen3
ollama pull nomic-embed-text
```

3. Start GenieHive control:

```bash
cd /home/netuser/bin/geniehive
bash scripts/run_control_singlebox.sh
```

4. Start GenieHive node:

```bash
cd /home/netuser/bin/geniehive
bash scripts/run_node_singlebox.sh configs/node.singlebox.ollama.example.yaml
```

5. Inspect:

```bash
bash scripts/demo_inspect.sh
```

6. Run the client agent:

```bash
python scripts/demo_client_agent.py \
  --base-url http://127.0.0.1:8800 \
  --api-key change-me-client-key \
  --task "Explain in three bullets what GenieHive is doing in this single-machine demo."
```

### llama.cpp-backed single box

1. Start the local server:

```bash
llama-server -m /path/to/model.gguf --host 127.0.0.1 --port 18091
```

2. Start GenieHive control:

```bash
cd /home/netuser/bin/geniehive
bash scripts/run_control_singlebox.sh
```

3. Start GenieHive node:

```bash
cd /home/netuser/bin/geniehive
bash scripts/run_node_singlebox.sh configs/node.singlebox.llamacpp.example.yaml
```

4. Run the client agent:

```bash
python scripts/demo_client_agent.py \
  --base-url http://127.0.0.1:8800 \
  --api-key change-me-client-key \
  --task "Summarize why a single-machine GenieHive setup can still be useful."
```

## Host-Specific Note: Dual Tesla P40 + 128 GB RAM

For a machine with:

- `2 x Nvidia Tesla P40`
- `AMD Ryzen 5600G`
- `128 GB RAM`

the most practical first GenieHive layout is:

- one chat model on `GPU0`
- one chat or utility model on `GPU1`
- one slower fallback chat model on CPU

This is now sketched in:

- `configs/node.singlebox.p40-triple.example.yaml`
- `configs/control.singlebox.p40.example.yaml`
- `configs/roles.singlebox.p40.example.yaml`
- `scripts/start_p40_triple_llamacpp.sh`
- `scripts/launch_p40_triple.sh`
- `scripts/p40_triple_gpu0.sh`
- `scripts/p40_triple_gpu1.sh`
- `scripts/p40_triple_cpu.sh`

The current concrete defaults use models already present under `/home/netuser/bin/models/llm`:

- `GPU0`: `Qwen2.5-14B-Instruct-1M-Q5_K_M.gguf`
- `GPU1`: `Qwen3.5-9B-Q5_K_M.gguf`
- `CPU`: `rocket-3b.Q5_K_M.gguf`

### Why this layout works

- each P40 has enough VRAM for a quantized 7B to 14B model comfortably
- 128 GB RAM is enough to hold a separate CPU-served fallback model without much trouble
- the CPU route will be much slower, but it is still useful for low-priority offload or fallback handling

### Suggested role usage

- `mentor` or primary chat role -> `GPU0`
- `general_assistant` or alternate chat role -> `GPU1`
- `fallback_writer` or `background_summarizer` -> CPU route

The repo now includes a host-specific role catalog with exactly that intent.

### Launch pattern

1. Edit your model paths:

```bash
cd /home/netuser/bin/geniehive
bash scripts/start_p40_triple_llamacpp.sh
```

If the defaults look good, you do not need to edit them before trying the first run.

If `tmux` is available, you can also launch the three processes detached:

```bash
cd /home/netuser/bin/geniehive
bash scripts/launch_p40_triple.sh
```

Then inspect pane state without binding your current terminal to the session:

```bash
bash scripts/tmux_session_status.sh
```

That status helper checks whether the session exists and whether each pane's launcher process is still running or has already exited. If `tmux` is not installed, the combined launcher prints the three helper commands instead.

2. Start the three `llama-server` processes in separate shells.

3. Start GenieHive control:

```bash
bash scripts/run_control_singlebox.sh configs/control.singlebox.p40.example.yaml
```

4. Start GenieHive node with the host-specific config:

```bash
bash scripts/run_node_singlebox.sh configs/node.singlebox.p40-triple.example.yaml
```

5. Inspect the catalog:

```bash
bash scripts/demo_inspect.sh
```

If something is not coming up cleanly, run:

```bash
bash scripts/check_singlebox_health.sh
```

That checks:

- `GPU0` upstream health
- `GPU1` upstream health
- CPU fallback upstream health
- GenieHive control health
- GenieHive node health
- authenticated cluster and model-catalog endpoints

6. Exercise the chat path:

```bash
python scripts/demo_client_agent.py \
  --base-url http://127.0.0.1:8800 \
  --api-key change-me-client-key \
  --model mentor \
  --task "State which route should be preferred for low-latency chat and which should be the slow fallback."
```

### Practical expectations

- `GPU0` and `GPU1` should be the preferred targets for normal chat work
- the CPU route should mostly be treated as fallback or low-priority background work
- GenieHive metadata should make that visible to clients through latency and offload hints

### Containerized Qwen3.5 probe

If the host-installed `llama-server` is too old for `Qwen3.5`, but the NVIDIA Container Toolkit is installed, you can test a newer CUDA-enabled `llama.cpp` without changing the host CUDA stack:

```bash
cd /home/netuser/bin/geniehive
bash scripts/test_qwen35_server_cuda_container.sh
```

Useful overrides:

```bash
GPU_INDEX=1 PORT=19092 bash scripts/test_qwen35_server_cuda_container.sh
MODEL_PATH=/home/netuser/bin/models/llm/Qwen3.5-9B-Q5_K_M.gguf bash scripts/test_qwen35_server_cuda_container.sh
```

That probe uses the official `ghcr.io/ggml-org/llama.cpp:server-cuda` image. If it loads the model and starts serving, then the remaining blocker is your host `llama.cpp` install, not GPU compatibility.

## External Client Access

For your current host addresses:

- LAN: `192.168.40.207`
- ZeroTier: `172.24.50.65`

The cleanest rule is:

- keep upstream model servers on `127.0.0.1`
- keep the GenieHive node on `127.0.0.1` unless you specifically need remote node access
- expose only the GenieHive control plane to LAN or ZeroTier clients

That gives remote clients a single stable endpoint without exposing the underlying model servers directly.

### LAN bind

```bash
cd /home/netuser/bin/geniehive
bash scripts/run_control_p40_lan.sh
```

Remote client example:

```bash
python scripts/demo_client_agent.py \
  --base-url http://192.168.40.207:8800 \
  --api-key change-me-client-key \
  --model mentor \
  --task "Briefly describe the preferred and fallback routes on this host."
```

### ZeroTier bind

```bash
cd /home/netuser/bin/geniehive
bash scripts/run_control_p40_zerotier.sh
```

Remote client example:

```bash
python scripts/demo_client_agent.py \
  --base-url http://172.24.50.65:8800 \
  --api-key change-me-client-key \
  --model mentor \
  --task "Briefly describe the preferred and fallback routes on this host."
```

### Security note

Prefer ZeroTier over general LAN exposure when possible. In both cases:

- do not expose the upstream `llama-server` ports
- keep the client API key enabled
- if you later open this beyond trusted networks, add a reverse proxy or VPN-only boundary rather than binding GenieHive broadly

### Role meanings for this host

- `mentor` should bias toward the `GPU0` Qwen2.5 14B route
- `general_assistant` should bias toward the `GPU1` Qwen3.5 9B route
- `background_summarizer` should bias toward the CPU Rocket 3B fallback route
