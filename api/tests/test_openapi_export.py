"""DE-373 drift-guard for the generated backend OpenAPI export.

`docs/api/backend-openapi.generated.yaml` is a generated artifact (see
`app.openapi_export`). This test regenerates it in-memory from the live app and
fails if the committed file has drifted — i.e. a route or schema changed without
regenerating. The fix is always: run `make openapi` and commit the result.

This is the guard that the hand-authored sketch `docs/api/backend-openapi.yaml`
never had (which is why it silently drifted; DE-373).
"""

from __future__ import annotations

import pathlib

import yaml

from app.openapi_export import build_openapi_yaml

_GENERATED = (
    pathlib.Path(__file__).resolve().parents[2] / "docs" / "api" / "backend-openapi.generated.yaml"
)


def test_generated_openapi_export_exists() -> None:
    assert _GENERATED.exists(), (
        f"{_GENERATED} is missing — run `make openapi` to generate and commit it."
    )


def test_generated_openapi_export_is_current() -> None:
    # Compare parsed structures, not raw bytes: this catches every real route /
    # schema drift while staying robust to YAML-formatting differences across
    # environments (e.g. pyyaml line-wrapping). The fix is always `make openapi`.
    committed = yaml.safe_load(_GENERATED.read_text(encoding="utf-8"))
    current = yaml.safe_load(build_openapi_yaml())
    assert committed == current, (
        "Committed backend-openapi.generated.yaml is stale — a route or schema "
        "changed without regenerating. Run `make openapi` and commit the result."
    )
