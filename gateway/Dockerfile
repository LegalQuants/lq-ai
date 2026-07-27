# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS base

# ADR 0023 — dependencies install from the committed uv.lock so the shipped
# tree is exactly the reviewed tree. The uv binary is copied from the
# version-tagged upstream image (same tag-pin posture as python:3.12-slim);
# bump the tag deliberately alongside the lockfile toolchain.
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /uvx /usr/local/bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# `uv sync --frozen` refuses to re-resolve: the build fails if uv.lock is
# missing or stale rather than silently shipping an unreviewed tree.
# `--no-install-project` installs dependencies only — the app/ source is
# COPY'd in below and imported from /app, matching the previous
# metadata-only `pip install .` behavior.
COPY pyproject.toml README.md uv.lock ./
RUN uv sync --frozen --no-install-project

# Put the locked venv first on PATH so python/uvicorn/spacy below (and the
# entrypoint's CMD) resolve to the synced environment.
ENV PATH="/app/.venv/bin:$PATH"

# M2-B2 — bake spaCy's en_core_web_lg model into the image so the
# Presidio AnalyzerEngine has its NLP backbone available at first
# request without a network round-trip at startup. ~560MB on disk;
# a one-time SBOM cost paid for deterministic deploys and air-gapped
# operator environments. The model is what feeds entity-recognition
# for PERSON, ORG, LOCATION, and the others Presidio's default
# pipeline depends on; the custom PatternRecognizers
# (CaseNumberRecognizer, MatterNumberRecognizer) don't depend on
# spaCy but they live in the same Analyzer. uv-created venvs ship without
# pip and `spacy download` shells out to `python -m pip`, so seed the
# interpreter's bundled pip into the venv first.
RUN python -m ensurepip && python -m spacy download en_core_web_lg

COPY app/ ./app/

# D0.5 — entrypoint script seeds /etc/lq-ai/gateway.yaml from the
# example file on first boot when the operator has mounted a writable
# named volume but not yet supplied a writable config. See
# entrypoint.sh + docs/adr/0010-gateway-config-hot-reload.md.
COPY entrypoint.sh /usr/local/bin/lq-ai-gateway-entrypoint.sh
RUN chmod +x /usr/local/bin/lq-ai-gateway-entrypoint.sh

# A3 (Inference Gateway scaffold) requires a ``gateway.yaml`` at startup.
# The image ships without one — the operator supplies it via a volume mount
# (see ``docker-compose.yml``). The gateway reads ``GATEWAY_CONFIG_PATH`` to
# find this file; default ``/etc/lq-ai/gateway.yaml`` matches the
# documented mount target. D0.5 changed the path from ``/etc/gateway.yaml``
# to ``/etc/lq-ai/gateway.yaml`` (a directory mount) so the entrypoint
# can seed a writable copy from the read-only example without
# touching the source-controlled file.
ENV GATEWAY_CONFIG_PATH=/etc/lq-ai/gateway.yaml \
    LQ_AI_GATEWAY_CONFIG_DIR=/etc/lq-ai

EXPOSE 8001

ENTRYPOINT ["/usr/local/bin/lq-ai-gateway-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
