"""DE-330: the hand-authored tabular contract matches serialized models.

Read only this component block: the wider sketch has unrelated legacy YAML
constructs. Compare wire fields, required keys, types, references and formats,
including OpenAPI 3.1 null unions; descriptions/defaults are not contracts.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest
import yaml
from pydantic import BaseModel

from app.schemas.tabular import (
    CellResult,
    Citation,
    TabularExecutionResponse,
    TabularResults,
    TabularRow,
)

_SKETCH = Path(__file__).resolve().parents[2] / "docs/api/backend-openapi.yaml"
_REF_NAMES = {"Citation": "TabularCitation", "CellResult": "TabularCellResult"}


def _components() -> dict[str, Any]:
    text = _SKETCH.read_text()
    block = (
        "    TabularExecution:\n"
        + text.split("    TabularExecution:\n", 1)[1].split("    TabularExecutionSummary:", 1)[0]
    )
    result: dict[str, Any] = yaml.safe_load(dedent(block))
    return result


def _wire_shape(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalize equivalent union spellings and the sketch's component names."""

    branches = schema.get("anyOf", [schema])
    types: set[str] = set()
    refs: set[str] = set()
    formats: set[str] = set()
    result: dict[str, Any] = {}
    for branch in branches:
        kind = branch.get("type", [])
        types.update([kind] if isinstance(kind, str) else kind)
        if "$ref" in branch:
            name = branch["$ref"].rsplit("/", 1)[-1]
            refs.add(_REF_NAMES.get(name, name))
        if "format" in branch:
            formats.add(branch["format"])
        if "enum" in branch:
            result["enum"] = sorted(branch["enum"])
        if "items" in branch:
            result["items"] = _wire_shape(branch["items"])
        if isinstance(branch.get("additionalProperties"), dict):
            result["values"] = _wire_shape(branch["additionalProperties"])
    return {**result, "types": sorted(types), "refs": sorted(refs), "formats": sorted(formats)}


@pytest.mark.parametrize(
    ("name", "model"),
    [
        ("TabularResults", TabularResults),
        ("TabularRow", TabularRow),
        ("TabularCellResult", CellResult),
        ("TabularCitation", Citation),
    ],
)
def test_tabular_components_match_serialized_models(name: str, model: type[BaseModel]) -> None:
    documented = _components()[name]
    runtime = model.model_json_schema(mode="serialization")
    assert documented["type"] == runtime["type"] == "object"
    assert set(documented["required"]) == set(runtime["required"])
    assert documented["properties"].keys() == runtime["properties"].keys()
    for field, schema in runtime["properties"].items():
        assert _wire_shape(documented["properties"][field]) == _wire_shape(schema), field


def test_execution_results_ref_is_nullable_in_openapi_31() -> None:
    documented = _components()["TabularExecution"]["properties"]["results"]
    runtime = TabularExecutionResponse.model_json_schema(mode="serialization")["properties"][
        "results"
    ]
    assert _wire_shape(documented) == _wire_shape(runtime)
    assert _wire_shape(documented)["types"] == ["null"]
    assert _wire_shape(documented)["refs"] == ["TabularResults"]


def test_results_wire_contract_does_not_expose_persisted_vintage() -> None:
    assert "schema_version" not in _components()["TabularResults"]["properties"]
