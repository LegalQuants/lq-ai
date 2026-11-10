#!/usr/bin/env bash
# Keep Docker service discovery, but never forward external names to host DNS.
# --dns=127.0.0.1 means the container's own loopback, not the Docker host:
# https://docs.docker.com/engine/network/#dns-services
# Generate a DNS-only Compose override BEFORE the fresh sealed boot. Nothing
# listens on loopback port 53 in the shipped services; verify this with the
# workflow's DNS controls. No host resolver or daemon settings are changed.
set -euo pipefail

configure() {
  local output="${1:?usage: $0 configure <override.yml>}" config
  config="$(docker compose --profile local config --format json)"
  # Sharing a host/another container's netns would invalidate the per-container
  # loopback guarantee. Fail closed if the topology changes to either mode.
  if ! jq -e '.services | length > 0 and all(.[]; .network_mode == null)' \
    <<< "$config" >/dev/null; then
    echo 'seal-dns: expected isolated Compose service network namespaces' >&2
    return 1
  fi
  mkdir -p "$(dirname "$output")"
  # Ordinary Compose DNS lists append; replace existing upstreams completely.
  # Requires Compose >= 2.24.4; older clients fail at config parsing.
  jq -r '"services:", (.services | keys[] |
      "  \(. | @json):\n    dns: !override [127.0.0.1]")' \
    <<< "$config" > "$output"
  echo "seal-dns: DNS-only override written to ${output}"
}

verify() {
  local config service ids
  config="$(docker compose --profile local config --format json)"
  if ! jq -e '.services | length > 0 and all(.[];
      .dns == ["127.0.0.1"] and .network_mode == null)' \
    <<< "$config" >/dev/null; then
    echo 'seal-dns: Compose config does not apply the DNS seal to every service' >&2
    return 1
  fi
  while IFS= read -r service; do
    # Include completed one-shot init containers: they booted in the same window.
    ids="$(docker compose --profile local ps -aq "$service")"
    if [ -z "$ids" ]; then
      echo "seal-dns: missing sealed container for service ${service}" >&2
      return 1
    fi
    # shellcheck disable=SC2086 # Docker IDs are newline-separated tokens.
    if ! docker inspect $ids | jq -e 'length > 0 and all(.[];
        .HostConfig.Dns == ["127.0.0.1"] and
        (.HostConfig.NetworkMode | test("^(host|container:)") | not))' >/dev/null; then
      echo "seal-dns: service ${service} was created without DNS isolation" >&2
      return 1
    fi
  done < <(jq -r '.services | keys[]' <<< "$config")
  echo 'seal-dns: every container uses its own loopback DNS upstream'
}

case "${1:-}" in
  configure) configure "${2:?usage: $0 configure <override.yml>}" ;;
  verify) verify ;;
  *) echo "usage: $0 {configure <override.yml>|verify}" >&2; exit 2 ;;
esac
