# LQ.AI Backend API

FastAPI service implementing the LQ.AI backend OpenAPI surface (`docs/api/backend-openapi.yaml`).

## Quick start

```bash
uv sync --extra dev               # creates .venv from the committed uv.lock
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

Dependencies are locked with [uv](https://docs.astral.sh/uv/) per
[ADR 0023](../docs/adr/0023-uv-lockfiles-gateway-api.md); after editing
`pyproject.toml`, run `uv lock` and commit the updated `uv.lock` (CI gates on
`uv lock --check`).

Health check: `curl http://localhost:8000/health`

## Tests

```bash
pytest                    # unit + integration
pytest -m "not provider"  # skip provider-integration tests
ruff check .
ruff format --check .
mypy .
```

## Status

M1 build in progress. See [`docs/M1-IMPLEMENTATION-ORDER.md`](../docs/M1-IMPLEMENTATION-ORDER.md) for task breakdown.
