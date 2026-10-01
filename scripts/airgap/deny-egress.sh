#!/usr/bin/env bash
# Air-gap seal (DE-032 / DE-233) — deny-all-egress guard for the lq-ai
# compose bridge network.
#
# Inserts a rule chain into the host's DOCKER-USER iptables chain that
# drops every packet leaving the compose bridge whose destination is not
# private (RFC1918) or loopback. Containers keep talking to each other
# (their subnet is RFC1918) and to the host; anything aimed at the
# public internet dies at the FORWARD hook. This is the CI stand-in for
# a physically air-gapped network.
#
# Why iptables on the bridge rather than a compose `internal: true`
# override: the seal must certify the SHIPPED topology. An override file
# changes what is under test (and `internal: true` disables published
# ports, which the smoke driver on the host needs). iptables leaves
# docker-compose.yml byte-identical to what operators deploy. The
# declarative `internal: true` variant is documented in
# docs/security/air-gap-verification.md as the local-reproduction
# alternative for hosts where iptables is not available (e.g. Docker
# Desktop on macOS, where the daemon runs in a VM and host iptables
# does not see container traffic).
#
# DOCKER-USER only filters FORWARDED (container) traffic — the host's
# own connectivity (CI checkout, artifact upload) is untouched. We
# match `-i <bridge>` (traffic FROM containers); host->container
# published-port traffic arrives with RFC1918 addresses either way.
#
# Known limitation (documented in the runbook): Docker's embedded DNS
# resolves names via the HOST's resolver from the host network
# namespace, so name resolution from sealed containers may still
# succeed. The seal blocks the subsequent connection, and the tcpdump
# canary (capture-egress.sh) records the attempt. A physical air gap
# has no resolver at all.
#
# Usage:
#   deny-egress.sh seal     # install the guard (idempotent)
#   deny-egress.sh unseal   # remove the guard
#   deny-egress.sh status   # print the installed rules
#
# Env:
#   AIRGAP_NETWORK  compose network to seal (default: lq-ai_default —
#                   the compose project name is pinned to `lq-ai` in
#                   docker-compose.yml and no custom network is declared)
#
# Requires: Linux host, docker, sudo iptables (GitHub-hosted ubuntu
# runners provide passwordless sudo).

set -euo pipefail

CHAIN="LQ-AIRGAP"
NETWORK="${AIRGAP_NETWORK:-lq-ai_default}"

# Destinations a sealed stack is still allowed to reach: private ranges
# (the compose subnet itself, plus anything else on the operator's LAN
# — a real air-gapped deployment still has an internal network) and
# loopback. Everything else — public internet, link-local/metadata
# (169.254/16), carrier-grade NAT — is dropped.
ALLOWED_DST=(10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 127.0.0.0/8)

resolve_iface() {
  # Docker names the Linux bridge for a user-defined network
  # br-<first 12 chars of the network id> unless an explicit
  # com.docker.network.bridge.name option is set (docker-compose.yml
  # sets none). Fail loudly if the derived interface doesn't exist —
  # a wrong interface would make the seal (and the canary) vacuous.
  local net_id
  net_id="$(docker network inspect "$NETWORK" --format '{{.Id}}')"
  local iface="br-${net_id:0:12}"
  if ! ip link show "$iface" >/dev/null 2>&1; then
    echo "deny-egress: derived bridge interface ${iface} for network ${NETWORK} does not exist" >&2
    echo "deny-egress: (is the compose network up? does it use a custom bridge name?)" >&2
    return 1
  fi
  echo "$iface"
}

seal() {
  local iface
  iface="$(resolve_iface)"
  echo "deny-egress: sealing bridge ${iface} (network ${NETWORK})"

  # Create-or-flush the chain so re-running `seal` is idempotent and
  # never stacks duplicate rules.
  sudo iptables -N "$CHAIN" 2>/dev/null || sudo iptables -F "$CHAIN"
  local dst
  for dst in "${ALLOWED_DST[@]}"; do
    sudo iptables -A "$CHAIN" -d "$dst" -j RETURN
  done
  # DROP (not REJECT): a real air gap does not send ICMP refusals —
  # packets just die. Clients see timeouts, which is the failure mode
  # air-gapped operators actually get.
  sudo iptables -A "$CHAIN" -j DROP

  # Jump into the chain for every packet entering the FORWARD path from
  # our bridge. -C first so re-sealing doesn't insert a duplicate jump.
  sudo iptables -C DOCKER-USER -i "$iface" -j "$CHAIN" 2>/dev/null \
    || sudo iptables -I DOCKER-USER 1 -i "$iface" -j "$CHAIN"

  # IPv6: compose networks here are IPv4-only, but if the daemon has
  # IPv6 enabled a v6 DOCKER-USER chain exists — mirror the seal so v6
  # can't become a bypass. Skipped silently when docker never created
  # the chain (ip6tables still exits 0 on -L of a missing chain on some
  # hosts, hence the explicit guard).
  if sudo ip6tables -L DOCKER-USER >/dev/null 2>&1; then
    sudo ip6tables -N "$CHAIN" 2>/dev/null || sudo ip6tables -F "$CHAIN"
    # Unique-local + link-local are the v6 analogue of RFC1918/loopback.
    sudo ip6tables -A "$CHAIN" -d fc00::/7 -j RETURN
    sudo ip6tables -A "$CHAIN" -d fe80::/10 -j RETURN
    sudo ip6tables -A "$CHAIN" -d ::1/128 -j RETURN
    sudo ip6tables -A "$CHAIN" -j DROP
    sudo ip6tables -C DOCKER-USER -i "$iface" -j "$CHAIN" 2>/dev/null \
      || sudo ip6tables -I DOCKER-USER 1 -j "$CHAIN"
  fi

  echo "deny-egress: sealed. Rules:"
  status
}

unseal() {
  local iface
  iface="$(resolve_iface)"
  echo "deny-egress: unsealing bridge ${iface}"
  sudo iptables -D DOCKER-USER -i "$iface" -j "$CHAIN" 2>/dev/null || true
  sudo iptables -F "$CHAIN" 2>/dev/null || true
  sudo iptables -X "$CHAIN" 2>/dev/null || true
  if sudo ip6tables -L "$CHAIN" >/dev/null 2>&1; then
    sudo ip6tables -D DOCKER-USER -i "$iface" -j "$CHAIN" 2>/dev/null || true
    sudo ip6tables -F "$CHAIN" 2>/dev/null || true
    sudo ip6tables -X "$CHAIN" 2>/dev/null || true
  fi
  echo "deny-egress: unsealed"
}

status() {
  sudo iptables -L DOCKER-USER -v --line-numbers || true
  sudo iptables -L "$CHAIN" -v --line-numbers 2>/dev/null || echo "deny-egress: chain ${CHAIN} not installed"
}

case "${1:-}" in
  seal) seal ;;
  unseal) unseal ;;
  status) status ;;
  *)
    echo "usage: $0 {seal|unseal|status}" >&2
    exit 2
    ;;
esac
