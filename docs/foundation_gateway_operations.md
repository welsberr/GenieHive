# Foundation Gateway Operations

This runbook assumes commands are run from the GenieHive repository root. It
uses the Foundation example as a starting point and keeps provider credentials
out of YAML, client scripts, audit records, and source control.

## Initial Setup

Create an isolated environment and install the control plane and CLI:

```bash
cd /path/to/GenieHive
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

Copy the Foundation configuration and replace every `change-me-*` value through
the deployment secret mechanism. Set the hash secret before starting the
control plane:

```bash
cd /path/to/GenieHive
export GENIEHIVE_KEY_HASH_SECRET="use-a-secret-manager-value"
export GENIEHIVE_CONTROL_CONFIG="$PWD/configs/control.foundation.example.yaml"
.venv/bin/uvicorn geniehive_control.main:app --host 127.0.0.1 --port 8800
```

The Foundation profile enables named keys, audit records, and admin routes.
Keep the static client key as a break-glass administrator credential only; use
named keys for normal clients.

## Provider Credentials

Provider entries are optional and disabled by default. Enable a provider in the
configuration only after its credential is available in the control-plane
environment:

```bash
cd /path/to/GenieHive
export OPENAI_API_KEY="use-a-secret-manager-value"
export ANTHROPIC_API_KEY="use-a-secret-manager-value"
```

The `api_key_env` field names the environment variable; the value must not be
placed in YAML. Client machines need only `GENIEHIVE_BASE_URL`, a GenieHive
client key, and a role or model name. They must not receive provider keys.

## Key Lifecycle

Set the admin URL and credential once per shell:

```bash
cd /path/to/GenieHive
export GENIEHIVE_BASE_URL="http://127.0.0.1:8800"
export GENIEHIVE_ADMIN_KEY="$FOUNDATION_ADMIN_KEY"
```

Create a scoped archive client key. The raw key is printed once by the CLI;
store it in the client secret manager immediately:

```bash
cd /path/to/GenieHive
.venv/bin/geniehive-admin client-key create \
  --display-name "Archive migration" \
  --principal-type "service" \
  --principal-ref "archive-migration" \
  --allowed-model archive_migrator \
  --allowed-operation chat \
  --monthly-token-limit 100000
```

Inspect or revoke a key without touching SQLite directly:

```bash
cd /path/to/GenieHive
.venv/bin/geniehive-admin client-key list
.venv/bin/geniehive-admin client-key disable ck_example
.venv/bin/geniehive-admin client-key enable ck_example
```

The CLI never prints stored `key_hash` values. Disabling a key is the emergency
client revocation procedure; rotate the hash secret only as a coordinated
operation because it invalidates all named keys.

## Usage And Budgets

Audit logging must be enabled before these commands return data:

```bash
cd /path/to/GenieHive
.venv/bin/geniehive-admin audit summary
.venv/bin/geniehive-admin audit list --operation chat --limit 100
.venv/bin/geniehive-admin audit list --key-id ck_example --success false
```

Budget controls are opt-in under `budgeting.enabled`. Configure exact model
prices before enabling cost ceilings. A missing price is allowed or denied
according to `deny_on_unknown_cost`; it is never guessed. Token and cost limits
are checked before the upstream call and usage is derived from audit records.

## Archive Smoke Workflow

Run the smoke client from the repository root with the client key, never a
provider key:

```bash
cd /path/to/GenieHive
export GENIEHIVE_BASE_URL="http://127.0.0.1:8800"
export GENIEHIVE_API_KEY="$ARCHIVE_GENIEHIVE_API_KEY"
export GENIEHIVE_MODEL="archive_migrator"
python scripts/smoke_foundation_archive.py
```

`GENIEHIVE_MODEL` defaults to `archive_migrator`. The script sends one
non-streaming OpenAI-compatible chat request and exits nonzero for missing
configuration, transport or HTTP errors, malformed JSON, or missing assistant
content. See [archive_migration.example.env](/home/netuser/bin/GenieHive/configs/clients/archive_migration.example.env)
for variable names.

## Emergency Provider Disable

There is no provider-disable admin endpoint. To stop new traffic safely:

1. Edit the provider entry in `configs/control.foundation.example.yaml` (or the
   deployment copy) and set `enabled: false`.
2. Stop or restart the control-plane process using the deployment supervisor.
3. Confirm the provider is absent from `GET /v1/models` and inspect the audit
   summary for failed or rerouted requests.
4. Revoke the provider credential through its secret manager if compromise is
   suspected.

Do not delete audit rows during an incident. Preserve them for review, subject
to the deployment's retention policy.

## SQLite Backup And Restore

Back up the registry while the control plane is stopped, or use SQLite's backup
command while it is running:

```bash
cd /path/to/GenieHive
mkdir -p backups
sqlite3 state/geniehive.foundation.sqlite3 \
  ".backup 'backups/geniehive.foundation.$(date -u +%Y%m%dT%H%M%SZ).sqlite3'"
```

Protect backups like credentials: they contain key metadata and audit records.
To restore, stop the control plane, preserve the current file, then replace it
and restart:

```bash
cd /path/to/GenieHive
mv state/geniehive.foundation.sqlite3 state/geniehive.foundation.before-restore.sqlite3
cp backups/geniehive.foundation.REPLACE.sqlite3 state/geniehive.foundation.sqlite3
```

Verify `/health`, `/v1/models`, key authentication, and the audit summary after
restart. Test restoration periodically on a copy rather than against the live
database.

## Provider Seats Versus GenieHive

Use provider-native seats when the provider's own identity, team billing,
retention, or compliance controls are the requirement. Use GenieHive when one
managed gateway must present stable roles across local services and multiple
provider accounts, enforce shared key scopes or budgets, and retain a
provider-neutral audit trail. Do not duplicate a provider seat merely to gain a
second client key; use a named GenieHive key unless provider-native identity is
required.
