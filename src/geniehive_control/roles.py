from __future__ import annotations

from pathlib import Path

import yaml

from .models import RoleCatalog


def load_role_catalog(path: str | Path) -> RoleCatalog:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    if not isinstance(raw, dict):
        raise ValueError("Role catalog must be a YAML mapping.")
    return RoleCatalog.model_validate(raw)
