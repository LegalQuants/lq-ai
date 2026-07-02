"""Deterministic OpenAPI export for the backend API.

The committed `docs/api/backend-openapi.generated.yaml` is a **generated**
artifact — the faithful contract emitted from the live FastAPI app — kept in
sync by a CI drift-guard (`tests/test_openapi_export.py`). It sits alongside
the hand-authored sketch `docs/api/backend-openapi.yaml` (DE-373).

Both the generator script (`scripts/gen_openapi.py`) and the drift-guard test
import `build_openapi_yaml()` from here, so the bytes they produce are
identical by construction. `yaml.safe_dump(..., sort_keys=True)` canonicalises
key order, so the output is stable across runs and Python versions regardless
of route-registration order.
"""

from __future__ import annotations

import yaml


def build_openapi_yaml() -> str:
    """Return the live app's OpenAPI schema as canonical, deterministic YAML."""
    # Local import: keep this module cheap to import and free of an app-load
    # cycle; the FastAPI app is only needed when actually generating.
    from app.main import app

    schema = app.openapi()
    return yaml.safe_dump(
        schema,
        sort_keys=True,
        default_flow_style=False,
        allow_unicode=True,
    )
