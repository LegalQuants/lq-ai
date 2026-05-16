# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir .

# M2-B2 — bake spaCy's en_core_web_lg model into the image so the
# Presidio AnalyzerEngine has its NLP backbone available at first
# request without a network round-trip at startup. ~560MB on disk;
# a one-time SBOM cost paid for deterministic deploys and air-gapped
# operator environments. The model is what feeds entity-recognition
# for PERSON, ORG, LOCATION, and the others Presidio's default
# pipeline depends on; the custom PatternRecognizers
# (CaseNumberRecognizer, MatterNumberRecognizer) don't depend on
# spaCy but they live in the same Analyzer.
RUN python -m spacy download en_core_web_lg

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
