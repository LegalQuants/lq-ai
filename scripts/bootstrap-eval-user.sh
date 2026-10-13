#!/usr/bin/env bash
# CI-only: establish a fresh credential after stack-smoke, without parsing logs.
set -euo pipefail
: "${GITHUB_OUTPUT:?This helper requires a GitHub Actions step output file}"
password="eval-$(openssl rand -hex 16)"
echo "::add-mask::$password"
docker compose exec -T api python -m app.cli reset-admin-password \
  --email admin@lq.ai --password "$password" --no-force-change
# Scope the password to the consuming step; never export it through GITHUB_ENV.
echo "password=$password" >> "$GITHUB_OUTPUT"
