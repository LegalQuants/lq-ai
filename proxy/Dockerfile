# LQ.AI release-stack reverse proxy (lq-ai-proxy image).
#
# Bakes the proven Caddyfile into the published image so the macOS launcher —
# which has no repo on the user's Mac — gets the proxy config without a bind
# mount (mirrors how the api/gateway images bake the skills corpus +
# gateway.yaml.example). caddy:2-alpine is multi-arch upstream, so the
# release workflow builds linux/amd64 + linux/arm64 without trouble.
# Digest-pinned for reproducible builds (#301). Bump the tag and digest together.
FROM caddy:2-alpine@sha256:d8542f48d34a9cf4e4c11a478865229840e87e4c96ea3f439101f31a5d35f75f

COPY Caddyfile /etc/caddy/Caddyfile

# Caddy serves the unified origin on :8080. wget ships in the BusyBox base.
HEALTHCHECK --interval=10s --timeout=5s --retries=10 --start-period=10s \
  CMD wget -qO- http://localhost:8080/ >/dev/null 2>&1 || exit 1
