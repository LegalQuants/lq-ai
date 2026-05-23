# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir .

COPY app/ ./app/

EXPOSE 8002

# The slack-bridge is a lightweight HTTP service — no migrations, no
# external storage. uvicorn runs the FastAPI app directly. Operators
# in air-gapped environments who do not use Slack should not run this
# service at all; the docker-compose `slack` profile gates startup.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
