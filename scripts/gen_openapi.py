#!/usr/bin/env python3
"""Generate the committed backend OpenAPI export (DE-373).

Writes the faithful, deterministic OpenAPI schema emitted by the live FastAPI
app to `docs/api/backend-openapi.generated.yaml`. Run via `make openapi` (or
directly) whenever a route or schema changes; the drift-guard test
`api/tests/test_openapi_export.py` fails in CI if the committed file is stale.

Usage:
    python scripts/gen_openapi.py
"""

from __future__ import annotations

import pathlib
import sys

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
# Make the api package importable when run from the repo root.
sys.path.insert(0, str(_REPO_ROOT / "api"))

from app.openapi_export import build_openapi_yaml  # noqa: E402  (after sys.path setup)

_OUT = _REPO_ROOT / "docs" / "api" / "backend-openapi.generated.yaml"


def main() -> None:
    _OUT.write_text(build_openapi_yaml(), encoding="utf-8")
    print(f"wrote {_OUT.relative_to(_REPO_ROOT)}")


if __name__ == "__main__":
    main()
