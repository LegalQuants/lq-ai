#!/usr/bin/env bash
# Egress canary (DE-032 / DE-233) — tcpdump watch on the lq-ai compose
# bridge, recording any packet that tries to leave the deployment.
#
# The seal (deny-egress.sh) DROPs offending packets; this canary catches
# the ATTEMPT. tcpdump on the bridge interface sees frames as the
# containers emit them — before the FORWARD-hook drop — so telemetry
# that an app silently tolerates as a connection error (the failure mode
# the survey memo flagged) still shows up in the pcap and fails the job.
#
# The capture uses a BPF filter that records ONLY suspect packets:
# IPv4 whose destination is not RFC1918 / loopback / link-local /
# multicast / broadcast, and IPv6 whose destination is not
# unique-local / link-local / multicast / loopback. Intra-stack traffic
# (all RFC1918) is never captured, so a clean run produces an EMPTY
# pcap — that empty file, uploaded as a CI artifact, is the proof.
# Anti-vacuous-pass guard: the workflow's negative-control step runs a
# deliberate egress attempt against a second capture on the SAME
# interface with the SAME filter and asserts packets DO appear
# (`assert-attempts`), proving the canary is wired to the right place.
#
# Note on 169.254.0.0/16: excluded from "allowed" on purpose — nothing
# in the stack should ever touch a link-local/metadata address, so an
# attempt at e.g. 169.254.169.254 counts as suspect. (The BPF filter
# below treats only genuinely-local noise — multicast/broadcast — as
# benign.)
#
# Usage:
#   capture-egress.sh start <name>            # begin capture -> airgap-artifacts/<name>.pcap
#   capture-egress.sh stop <name>             # flush + stop
#   capture-egress.sh assert-clean <name>     # fail if ANY suspect packet was captured
#   capture-egress.sh assert-attempts <name>  # fail if NO suspect packet was captured
#
# Env:
#   AIRGAP_NETWORK       compose network to watch (default lq-ai_default)
#   AIRGAP_ARTIFACT_DIR  output dir (default airgap-artifacts)
#
# Requires: Linux host, sudo tcpdump (preinstalled on GitHub ubuntu runners).

set -euo pipefail

NETWORK="${AIRGAP_NETWORK:-lq-ai_default}"
ART_DIR="${AIRGAP_ARTIFACT_DIR:-airgap-artifacts}"

# Suspect = anything not plausibly local. Multicast (224/4, ff00::/8)
# and broadcast are excluded because Linux netns'es emit benign IGMP /
# ICMPv6 router-solicitation noise on any bridge; that noise never
# leaves the segment and would make every run "dirty" for free.
SUSPECT_BPF='
  (ip and
    not dst net 10.0.0.0/8 and
    not dst net 172.16.0.0/12 and
    not dst net 192.168.0.0/16 and
    not dst net 127.0.0.0/8 and
    not dst net 224.0.0.0/4 and
    not dst host 255.255.255.255)
  or
  (ip6 and
    not dst net fc00::/7 and
    not dst net fe80::/10 and
    not dst net ff00::/8 and
    not dst host ::1)
'

resolve_iface() {
  # Same derivation as deny-egress.sh: br-<first 12 chars of network id>.
  local net_id
  net_id="$(docker network inspect "$NETWORK" --format '{{.Id}}')"
  local iface="br-${net_id:0:12}"
  if ! ip link show "$iface" >/dev/null 2>&1; then
    echo "capture-egress: derived bridge interface ${iface} for network ${NETWORK} does not exist" >&2
    return 1
  fi
  echo "$iface"
}

pcap_path() { echo "${ART_DIR}/$1.pcap"; }

start() {
  local name="$1" iface pcap
  iface="$(resolve_iface)"
  mkdir -p "$ART_DIR"
  pcap="$(pcap_path "$name")"
  rm -f "$pcap"
  echo "capture-egress: starting suspect-packet capture on ${iface} -> ${pcap}"
  # -U: packet-buffered writes so a kill mid-run loses nothing.
  # -Z root: Ubuntu's tcpdump drops privileges to the `tcpdump` user by
  #   default, which cannot write into the workspace; keep root and fix
  #   ownership at `stop` instead.
  # shellcheck disable=SC2024  # sudo applies to tcpdump; the redirect target is ours
  sudo tcpdump -i "$iface" -nn -U -Z root -w "$pcap" "$SUSPECT_BPF" \
    >"${ART_DIR}/${name}.tcpdump.log" 2>&1 &
  # Give tcpdump a beat to attach, then verify it is actually running —
  # a typo'd filter or interface dies instantly and would otherwise
  # produce a silent no-op canary.
  sleep 2
  if ! pgrep -f "tcpdump .*${pcap}" >/dev/null; then
    echo "capture-egress: tcpdump failed to start:" >&2
    cat "${ART_DIR}/${name}.tcpdump.log" >&2
    return 1
  fi
  echo "capture-egress: capture '${name}' running"
}

stop() {
  local name="$1" pcap pid
  pcap="$(pcap_path "$name")"
  # Find the real tcpdump pid by its unique output path (the backgrounded
  # job pid is sudo's, and signal relaying through sudo is not reliable
  # across environments).
  pid="$(pgrep -f "tcpdump .*${pcap}" || true)"
  if [ -z "$pid" ]; then
    echo "capture-egress: no running capture found for '${name}'" >&2
    return 1
  fi
  # SIGINT lets tcpdump flush and print its packet counters to the log.
  # shellcheck disable=SC2086  # pid list is space-separated on purpose
  sudo kill -INT $pid
  for _ in $(seq 1 20); do  # bounded wait for tcpdump to flush and exit
    pgrep -f "tcpdump .*${pcap}" >/dev/null || break
    sleep 0.5
  done
  # Artifact upload runs as the unprivileged runner user.
  sudo chmod a+r "$pcap" 2>/dev/null || true
  echo "capture-egress: capture '${name}' stopped; tcpdump counters:"
  tail -n 5 "${ART_DIR}/${name}.tcpdump.log" || true
}

count_packets() {
  local pcap="$1"
  # Read back with tcpdump itself; every line is one captured packet.
  sudo tcpdump -r "$pcap" -nn 2>/dev/null | wc -l | tr -d '[:space:]'
}

assert_clean() {
  local name="$1" pcap n
  pcap="$(pcap_path "$name")"
  [ -f "$pcap" ] || { echo "capture-egress: ${pcap} missing" >&2; return 1; }
  n="$(count_packets "$pcap")"
  if [ "$n" != "0" ]; then
    echo "capture-egress: FAIL — ${n} suspect (non-private-destination) packet(s) left the stack:" >&2
    sudo tcpdump -r "$pcap" -nn 2>/dev/null | head -n 50 >&2
    return 1
  fi
  echo "capture-egress: PASS — zero non-private egress packets in '${name}'"
}

assert_attempts() {
  local name="$1" pcap n
  pcap="$(pcap_path "$name")"
  [ -f "$pcap" ] || { echo "capture-egress: ${pcap} missing" >&2; return 1; }
  n="$(count_packets "$pcap")"
  if [ "$n" = "0" ]; then
    echo "capture-egress: FAIL — negative control captured NOTHING." >&2
    echo "capture-egress: the deliberate egress attempt must be visible; an empty" >&2
    echo "capture-egress: pcap here means the canary is watching the wrong place" >&2
    echo "capture-egress: and the positive result cannot be trusted." >&2
    return 1
  fi
  echo "capture-egress: PASS — negative control recorded ${n} blocked egress packet(s); canary is live"
}

case "${1:-}" in
  start) start "${2:?usage: $0 start <name>}" ;;
  stop) stop "${2:?usage: $0 stop <name>}" ;;
  assert-clean) assert_clean "${2:?usage: $0 assert-clean <name>}" ;;
  assert-attempts) assert_attempts "${2:?usage: $0 assert-attempts <name>}" ;;
  *)
    echo "usage: $0 {start|stop|assert-clean|assert-attempts} <name>" >&2
    exit 2
    ;;
esac
