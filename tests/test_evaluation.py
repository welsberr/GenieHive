import json
from pathlib import Path

import pytest

from geniehive_control.evaluation import EvaluationCase, check_response, load_evaluation_catalog


CATALOG = Path(__file__).parents[1] / "docs/evaluation_catalog_v1.json"


def test_evaluation_catalog_is_versioned_and_loadable() -> None:
    catalog = load_evaluation_catalog(CATALOG)
    assert catalog.schema_version == "geniehive.evaluation.catalog.v1"
    assert {model.variant for model in catalog.model_profiles} >= {"nail", "dagger"}
    assert {workload.workload_id for workload in catalog.workloads} == {"chat.structured_json", "chat.tool_call_format"}


def test_check_response_is_deterministic() -> None:
    assert check_response('{"title":"Origin","year":1859}', [{"kind": "json"}, {"kind": "contains", "value": "year"}]) == (True, [])
    assert check_response("not json", [{"kind": "json"}]) == (False, ["invalid_json"])


def test_workload_rejects_duplicate_cases(tmp_path: Path) -> None:
    raw = json.loads(CATALOG.read_text())
    raw["workloads"][0]["cases"].append(raw["workloads"][0]["cases"][0])
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="unique"):
        load_evaluation_catalog(path)


@pytest.mark.parametrize("checks", [[], [{}], [{"kind":"contains"}], [{"kind":"regex","pattern":"["}], [{"kind":"unknown"}]])
def test_malformed_checks_cannot_silently_pass(checks) -> None:
    with pytest.raises(ValueError):
        EvaluationCase(case_id="case", prompt="Return JSON", checks=checks)
    assert check_response("anything", checks)[0] is False


@pytest.mark.parametrize("response", ["NaN", "Infinity", '{"score": NaN}'])
def test_json_check_rejects_non_json_numeric_constants(response) -> None:
    assert check_response(response, [{"kind":"json"}]) == (False, ["invalid_json"])


def test_catalog_rejects_duplicate_workload_ids(tmp_path: Path) -> None:
    raw=json.loads(CATALOG.read_text())
    raw["workloads"].append(raw["workloads"][0])
    path=tmp_path/"duplicate.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="workload_id.*unique"):
        load_evaluation_catalog(path)
