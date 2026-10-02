# LQ.AI Inference Gateway

Per [PRD §4](../docs/PRD.md#4-the-lq-ai-inference-gateway), the gateway is the security boundary — the only component holding privileged provider API keys, and the only egress path for customer prompts.

OpenAI-compatible surface (`/v1/chat/completions`, `/v1/embeddings`) plus admin endpoints under `/admin/v1`.

## Quick start

```bash
uv sync --extra dev               # creates .venv from the committed uv.lock
source .venv/bin/activate
uvicorn app.main:app --reload --port 8001
```

Dependencies are locked with [uv](https://docs.astral.sh/uv/) per
[ADR 0023](../docs/adr/0023-uv-lockfiles-gateway-api.md); after editing
`pyproject.toml`, run `uv lock` and commit the updated `uv.lock` (CI gates on
`uv lock --check`).

Health check: `curl http://localhost:8001/health`

## Configuration

The gateway reads a single YAML config (`gateway.yaml`); see [`../gateway.yaml.example`](../gateway.yaml.example) for the full schema.

## Tests

```bash
pytest                    # unit + integration
pytest -m "not provider"  # skip real-provider integration tests
ruff check .
ruff format --check .
mypy .
```

## Status

M1 build in progress. See [`../docs/M1-IMPLEMENTATION-ORDER.md`](../docs/M1-IMPLEMENTATION-ORDER.md) for task breakdown.
