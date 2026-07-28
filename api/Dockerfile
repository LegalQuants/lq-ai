# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS base

# ADR 0023 — dependencies install from the committed uv.lock so the shipped
# tree is exactly the reviewed tree. The uv binary is copied from the
# version-tagged upstream image (same tag-pin posture as python:3.12-slim);
# bump the tag deliberately alongside the lockfile toolchain.
COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /uvx /usr/local/bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install runtime deps from the lockfile (no dev extras in the image).
# `uv sync --frozen` refuses to re-resolve: the build fails if uv.lock is
# missing or stale rather than silently shipping an unreviewed tree.
# `--no-install-project` installs dependencies only — the app/ source is
# COPY'd in below and imported from /app, matching the previous
# metadata-only `pip install .` behavior.
COPY pyproject.toml README.md uv.lock ./
RUN uv sync --frozen --no-install-project

# Put the locked venv first on PATH so the entrypoint's alembic + uvicorn
# resolve to the synced environment.
ENV PATH="/app/.venv/bin:$PATH"

# Copy application code, migration files, and the entrypoint script
COPY app/ ./app/
COPY alembic.ini ./alembic.ini
COPY alembic/ ./alembic/
COPY entrypoint.sh /usr/local/bin/lq-ai-entrypoint
RUN chmod +x /usr/local/bin/lq-ai-entrypoint

EXPOSE 8000

# The entrypoint runs `alembic upgrade head` before exec'ing uvicorn so a
# fresh deployment lands a fully-migrated schema before the HTTP server
# accepts traffic. Operators handling migrations out-of-band can set
# LQ_AI_SKIP_MIGRATIONS=1 to bypass the step.
ENTRYPOINT ["/usr/local/bin/lq-ai-entrypoint"]
