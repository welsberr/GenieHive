"""Versioned model and workload contracts for role qualification.

This module is deliberately file-oriented.  It describes what was evaluated;
it does not change routing or promote a model into production.
"""
from __future__ import annotations

import json
import re
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
    max_completion_tokens: int = Field(default=120, gt=0)
    checks: list[dict[str, Any]] = Field(default_factory=lambda: [{"kind": "nonempty"}])
    adversarial: bool = False
    boundary: bool = False

    @model_validator(mode="after")
    def validate_case(self) -> "EvaluationCase":
        if not self.case_id.strip() or not self.prompt.strip():
            raise ValueError("case_id and prompt must be nonempty")
        validate_checks(self.checks)
        return self


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
        if not self.role_ids or any(not role.strip() for role in self.role_ids):
            raise ValueError("workload must name at least one role")
        if not all(value.strip() for value in (self.workload_id, self.dataset_revision, self.evaluator)):
            raise ValueError("workload identity, dataset revision and evaluator must be nonempty")
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

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "EvaluationCatalog":
        for label, ids in (("model_id", [m.model_id for m in self.model_profiles]),
                           ("workload_id", [w.workload_id for w in self.workloads])):
            if len(ids) != len(set(ids)):
                raise ValueError(f"{label} values must be unique within a catalog")
        return self


def load_evaluation_catalog(path: str | Path) -> EvaluationCatalog:
    return EvaluationCatalog.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def check_response(content: str, checks: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Apply small deterministic checks; subjective judging stays external."""
    import json as _json
    try:
        validate_checks(checks)
    except ValueError as error:
        return False, [f"invalid_check:{error}"]
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
                _json.loads(content, parse_constant=_reject_json_constant)
            except (TypeError, ValueError):
                failures.append("invalid_json")
        else:
            if kind not in {"nonempty", "contains", "regex", "json"}:
                failures.append(f"unknown_check:{kind}")
    return not failures, failures


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"not a JSON value: {value}")


def validate_checks(checks: list[dict[str, Any]]) -> None:
    """Reject malformed contracts before they can accidentally pass a response."""
    if not checks:
        raise ValueError("at least one response check is required")
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError("response checks must be objects")
        kind = check.get("kind")
        if not isinstance(kind, str) or kind not in {"nonempty", "contains", "regex", "json"}:
            raise ValueError(f"unknown check kind: {kind}")
        field = {"contains": "value", "regex": "pattern"}.get(kind)
        if set(check) - ({"kind", field} if field else {"kind"}):
            raise ValueError(f"unexpected fields for {kind} check")
        if field and (not isinstance(check.get(field), str) or not check[field]):
            raise ValueError(f"{kind} requires a nonempty {field}")
        if kind == "regex":
            try:
                re.compile(check["pattern"], re.MULTILINE)
            except re.error as error:
                raise ValueError(f"invalid regular expression: {error}") from error
