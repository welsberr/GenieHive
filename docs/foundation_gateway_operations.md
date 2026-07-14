# Foundation Gateway Operations

This page covers the archive smoke workflow. The broader key, provider, budget,
backup, and emergency-disable procedures will be added in the M9-B packet.

## Archive Smoke Test

Run from the GenieHive repository root:

```bash
export GENIEHIVE_BASE_URL="http://127.0.0.1:8800"
export GENIEHIVE_API_KEY="$ARCHIVE_GENIEHIVE_API_KEY"
export GENIEHIVE_MODEL="archive_migrator"
python scripts/smoke_foundation_archive.py
```

`GENIEHIVE_MODEL` defaults to `archive_migrator` when omitted. The client sends
one non-streaming OpenAI-compatible chat request and prints the assistant text.
It exits nonzero for missing configuration, transport errors, non-success HTTP
responses, malformed JSON, or a response without assistant content.

The client needs only a GenieHive URL, a GenieHive client key, and a role name.
It must not receive `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or any other provider
credential. Provider credentials, when enabled, stay in the control-plane
environment and are never placed in migration scripts.

## Configuration Reference

Use [archive_migration.example.env](/home/netuser/bin/GenieHive/configs/clients/archive_migration.example.env)
as a variable-name reference. Replace the example key through the deployment
secret mechanism; do not commit the replacement file.

The Foundation control configuration loads
`configs/roles.foundation.archive.yaml`, where `archive_migrator` is a role and
not a provider-specific model ID. Local services can satisfy the role, and
configured external services remain optional.
