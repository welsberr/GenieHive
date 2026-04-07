# GenieHive Roadmap

## Completed Foundations

- control-plane registry with SQLite persistence
- node registration and heartbeat
- role catalog and route resolution
- client-facing `GET /v1/models`
- client-facing `POST /v1/chat/completions`
- client-facing `POST /v1/embeddings`
- first control-plus-node demo flow

## Immediate Next Milestones

1. Run and document the first live LLM demo against real upstream servers.
2. Validate the `GET /v1/models` metadata as a Codex-friendly offload catalog for lower-complexity tasks.
3. Add `POST /v1/audio/transcriptions`.
4. Add a richer node metrics model for queue depth, current load, and observed performance over time.
5. Add a stronger operator/client distinction in the public metadata and auth surfaces.

## LLM Demo Note

The project is now ready for a first live LLM demo using GenieHive as:

- master: control plane
- peer: one or more node agents with pre-existing local LLM servers
- client: a small demo agent or Codex configured against GenieHive

The current live-demo priority is chat-first. Embeddings are also wired in GenieHive, but upstream compatibility differs across local servers, so the safest first demo matrix is:

- Ollama for chat and embeddings
- vLLM for chat and embeddings
- llama.cpp for chat
- llamafile for chat
