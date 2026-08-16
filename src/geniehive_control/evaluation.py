"""Versioned model and workload contracts for role qualification.

This module is deliberately file-oriented.  It describes what was evaluated;
it does not change routing or promote a model into production.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ModelProfile(BaseModel):
    model_id: str
    family: str
    variant: str | None = None
    architecture: Literal["dense", "moe", "hybrid", "embedding", "asr", "vision"]
    parameter_count: str | None = None
    active_parameter_count: str | None = None
    quantization: str | None = None
    runtime: str
    runtime_revision: str | None = None
    context_limit: int | None = None
    vision: bool = False
    mtp: bool = False
    license: str | None = None
    source: str | None = None
    file_sha256: str | None = None
    availability: Literal["local", "candidate", "retired"] = "candidate"


class EvaluationCase(BaseModel):
    case_id: str
    prompt: str
    max_completion_tokens: int = 120
    checks: list[dict[str, Any]] = Field(default_factory=lambda: [{"kind": "nonempty"}])
    adversarial: bool = False
    boundary: bool = False


class EvaluationWorkload(BaseModel):
    workload_id: str
    role_ids: list[str]
    dataset_revision: str
    evaluator: str
    risk_class: Literal["low", "medium", "high"] = "medium"
    minimum_pass_rate: float = 0.8
    hard_failures: list[str] = Field(default_factory=list)
    system_prompt: str = "Return only the requested answer."
    chat_template_kwargs: dict[str, Any] | None = None
    cases: list[EvaluationCase]

    @model_validator(mode="after")
    def validate_contract(self) -> "EvaluationWorkload":
        if not self.role_ids:
            raise ValueError("workload must name at least one role")
        if not 0 <= self.minimum_pass_rate <= 1:
            raise ValueError("minimum_pass_rate must be between 0 and 1")
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("case_id values must be unique within a workload")
        if not self.cases:
            raise ValueError("workload must contain at least one case")
        return self


class EvaluationCatalog(BaseModel):
    schema_version: Literal["geniehive.evaluation.catalog.v1"]
    dataset_revision: str
    model_profiles: list[ModelProfile] = Field(default_factory=list)
    workloads: list[EvaluationWorkload] = Field(default_factory=list)


def load_evaluation_catalog(path: str | Path) -> EvaluationCatalog:
    return EvaluationCatalog.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def check_response(content: str, checks: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Apply small deterministic checks; subjective judging stays external."""
    import json as _json
    import re

    failures: list[str] = []
    for check in checks:
        kind = str(check.get("kind", "nonempty"))
        if kind == "nonempty" and not content.strip():
            failures.append("empty_response")
        elif kind == "contains" and str(check.get("value", "")) not in content:
            failures.append(f"missing:{check.get('value')}")
        elif kind == "regex" and re.search(str(check.get("pattern", "")), content, re.MULTILINE) is None:
            failures.append(f"regex_mismatch:{check.get('pattern')}")
        elif kind == "json":
            try:
                _json.loads(content)
            except (TypeError, ValueError):
                failures.append("invalid_json")
        else:
            if kind not in {"nonempty", "contains", "regex", "json"}:
                failures.append(f"unknown_check:{kind}")
    return not failures, failures
