# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e

# Digest-pinned for reproducible builds (#301). Bump the tag and digest together.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir .

COPY app/ ./app/

EXPOSE 8003

# The teams-bridge is a lightweight HTTP service — no migrations, no
# external storage. uvicorn runs the FastAPI app directly. Operators
# in air-gapped environments who do not use Teams should not run this
# service at all; the docker-compose `teams` profile gates startup.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
