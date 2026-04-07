PYTHON ?= python
PYTEST ?= pytest

.PHONY: test smoke health

test:
	$(PYTEST) -q

smoke:
	$(PYTEST) -q tests/test_smoke.py

health:
	bash scripts/check_singlebox_health.sh
