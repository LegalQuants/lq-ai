# LQ.AI release-stack reverse proxy (lq-ai-proxy image).
#
# Bakes the proven Caddyfile into the published image so the macOS launcher —
# which has no repo on the user's Mac — gets the proxy config without a bind
# mount (mirrors how the api/gateway images bake the skills corpus +
# gateway.yaml.example). caddy:2-alpine is multi-arch upstream, so the
# release workflow builds linux/amd64 + linux/arm64 without trouble.
# Digest-pinned for reproducible builds (#301). Bump the tag and digest together.
FROM caddy:2-alpine@sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0

COPY Caddyfile /etc/caddy/Caddyfile

# Caddy serves the unified origin on :8080. wget ships in the BusyBox base.
HEALTHCHECK --interval=10s --timeout=5s --retries=10 --start-period=10s \
  CMD wget -qO- http://localhost:8080/ >/dev/null 2>&1 || exit 1
