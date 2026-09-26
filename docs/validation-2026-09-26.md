# Role evaluation validation — 26 September 2026

Release preparation corrected the empty-response metric: a nonempty answer that
fails a content check no longer counts as empty. Catalog contracts can now run
through the chat benchmark runner with dataset/evaluator metadata and declared
hard-failure overrides retained in the report. Unsupported evaluator names and
malformed checks fail before requests are sent. JSON checks reject non-JSON
numeric constants. The public catalog uses portable candidate examples rather
than installation-specific paths.

Validation on the prepared revision:

- `python -m pytest -q`: **119 passed**.
- `git diff --check`: passed.
- Existing Starlette/httpx test-client deprecation warning remains; no test failed.

The suite includes synthetic contract responses, invalid configurations, duplicate
identifiers, hard-failure versus threshold behavior, metadata retention and existing
control-plane regression coverage. CI runs the suite with Python 3.10 on pushes
and pull requests.

No live model, GPU, provider account or production route was changed or evaluated.
A deterministic contract pass is not semantic correctness, model qualification or
permission to promote a route. The checked-in catalog has four starter cases, not
the full role matrix described in the roadmap. OpenAI Codex assisted inspection,
fixes, tests and documentation under the maintainer's instruction to test and
publish the update.
