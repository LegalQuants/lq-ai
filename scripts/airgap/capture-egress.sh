#!/usr/bin/env bash
# Egress canary (DE-032 / DE-233) — tcpdump watch on the lq-ai compose
# bridge, recording outside DNS attempts and suspect connection packets.
#
# The seal (deny-egress.sh) DROPs offending packets; this canary catches
# the ATTEMPT. tcpdump on the bridge interface sees frames as the
# containers emit them — before the FORWARD-hook drop — so telemetry
# that an app silently tolerates as a connection error (the failure mode
# the survey memo flagged) still shows up in the pcap.
#
# The capture uses a BPF filter that records ONLY suspect packets, in
# three classes:
#   * ATTEMPTS — packets whose DESTINATION is not RFC1918 / loopback /
#     multicast / broadcast (outbound tries, including SYN retries and
#     pre-seal FIN teardowns).
#   * BREACHES — packets whose SOURCE is non-private (public replies).
#   * DNS ATTEMPTS — UDP/TCP port-53 packets aimed outside the stack
#     subnets, including private upstream resolvers, excluding loopback.
# Intra-stack traffic is excluded from these capture classes.
#
# `assert-clean` rejects outside DNS attempts and BREACH packets. Other
# outbound attempts are inventoried into <name>.attempts.txt (with
# container attribution) as part of the evidence artifact. A passing
# capture directly establishes no outside DNS attempts or public replies;
# interpret it alongside the installed firewall rules and counters to
# confirm packet drops.
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
# DNS is stricter than the general attempt inventory: a UDP/TCP port-53
# packet aimed outside the stack subnet fails even without any reply.
# seal-dns.sh covers Docker's loopback/host-forwarding path separately.
#
# Usage:
#   capture-egress.sh start <name>            # begin capture -> airgap-artifacts/<name>.pcap
#   capture-egress.sh stop <name>             # flush + stop
#   capture-egress.sh assert-clean <name>     # fail on outside DNS attempts or replies
#   capture-egress.sh assert-attempts <name>  # fail if NO suspect packet was captured
#   capture-egress.sh assert-dns-attempts <name> # require a deliberate DNS attempt
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
#
# ATTEMPT class: non-private DESTINATION (outbound tries).
ATTEMPT_BPF_V4='ip and
    not dst net 10.0.0.0/8 and
    not dst net 172.16.0.0/12 and
    not dst net 192.168.0.0/16 and
    not dst net 127.0.0.0/8 and
    not dst net 224.0.0.0/4 and
    not dst host 255.255.255.255'
ATTEMPT_BPF_V6='ip6 and
    not dst net fc00::/7 and
    not dst net fe80::/10 and
    not dst net ff00::/8 and
    not dst host ::1'
# BREACH class: non-private SOURCE (a public reply observed on the bridge).
BREACH_BPF_V4='ip and
    not src net 10.0.0.0/8 and
    not src net 172.16.0.0/12 and
    not src net 192.168.0.0/16 and
    not src net 127.0.0.0/8'
BREACH_BPF_V6='ip6 and
    not src net fc00::/7 and
    not src net fe80::/10 and
    not src net ff00::/8 and
    not src host ::1'
SUSPECT_BPF="(${ATTEMPT_BPF_V4}) or (${ATTEMPT_BPF_V6}) or (${BREACH_BPF_V4}) or (${BREACH_BPF_V6})"

dns_bpf() {
  local subnet subnets filter
  subnets="$(docker network inspect "$NETWORK" --format '{{range .IPAM.Config}}{{.Subnet}}{{"\n"}}{{end}}')"
  [ -n "$subnets" ] || { echo 'capture-egress: network has no subnets' >&2; return 1; }
  filter='(udp or tcp) and dst port 53 and not dst net 127.0.0.0/8 and not dst host ::1'
  while IFS= read -r subnet; do
    filter+=" and not dst net ${subnet}"
  done <<< "$subnets"
  echo "$filter"
}

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
  local name="$1" iface pcap dns_filter
  dns_filter="$(dns_bpf)"
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
  sudo tcpdump -i "$iface" -nn -U -Z root -w "$pcap" "(${SUSPECT_BPF}) or (${dns_filter})" \
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
  local pcap="$1"; shift
  # Read back with tcpdump itself; every line is one captured packet.
  # Optional extra args form a read-time display filter.
  sudo tcpdump -r "$pcap" -nn "$@" 2>/dev/null | wc -l | tr -d '[:space:]'
}

container_ip_map() {
  # Best-effort attribution: compose service name per bridge IP, so the
  # attempts inventory names WHICH container tried to phone home.
  docker network inspect "$NETWORK" \
    --format '{{range .Containers}}{{.IPv4Address}} {{.Name}}{{"\n"}}{{end}}' 2>/dev/null || true
}

assert_clean() {
  local name="$1" pcap breaches attempts dns_filter dns_attempts
  pcap="$(pcap_path "$name")"
  [ -f "$pcap" ] || { echo "capture-egress: ${pcap} missing" >&2; return 1; }

  # A blocked query can disclose a name even when there is no reply.
  # Reject DNS attempts before the generic blocked-connection inventory.
  dns_filter="$(dns_bpf)"
  dns_attempts="$(count_packets "$pcap" "$dns_filter")"
  if [ "$dns_attempts" != "0" ]; then
    echo "capture-egress: FAIL — ${dns_attempts} DNS attempt(s) outside the stack subnet" >&2
    # shellcheck disable=SC2024 # sudo reads the pcap; our user owns the report.
    sudo tcpdump -r "$pcap" -nn "$dns_filter" > "${ART_DIR}/${name}.dns-attempts.txt" 2>/dev/null
    container_ip_map >> "${ART_DIR}/${name}.dns-attempts.txt"
    head -n 50 "${ART_DIR}/${name}.dns-attempts.txt" >&2
    return 1
  fi

  # BREACH: any packet sourced from a non-private address fails the check.
  breaches="$(count_packets "$pcap" "(${BREACH_BPF_V4}) or (${BREACH_BPF_V6})")"
  if [ "$breaches" != "0" ]; then
    echo "capture-egress: FAIL — ${breaches} packet(s) from non-private sources on the bridge:" >&2
    echo "capture-egress: egress SUCCEEDED past the seal — the air-gap claim does not hold." >&2
    sudo tcpdump -r "$pcap" -nn "(${BREACH_BPF_V4}) or (${BREACH_BPF_V6})" 2>/dev/null | head -n 50 >&2
    return 1
  fi

  # ATTEMPT: other outbound tries are inventoried with container
  # attribution. Use the installed firewall rules and counters as drop
  # evidence; the capture alone establishes only the absence of replies.
  attempts="$(count_packets "$pcap" "(${ATTEMPT_BPF_V4}) or (${ATTEMPT_BPF_V6})")"
  if [ "$attempts" != "0" ]; then
    {
      echo "# Captured egress-attempt inventory — capture '${name}'"
      echo "# ${attempts} packet(s); zero public replies observed. See firewall counters for drop evidence."
      echo
      echo "## Container IP map"
      container_ip_map
      echo
      echo "## Attempts"
      sudo tcpdump -r "$pcap" -nn "(${ATTEMPT_BPF_V4}) or (${ATTEMPT_BPF_V6})" 2>/dev/null
    } > "${ART_DIR}/${name}.attempts.txt"
    chmod a+r "${ART_DIR}/${name}.attempts.txt" 2>/dev/null || true
    echo "capture-egress: WARN — ${attempts} attempted-egress packet(s) captured; consult firewall counters for drop evidence."
    echo "capture-egress: inventory written to ${ART_DIR}/${name}.attempts.txt (artifact)."
    echo "capture-egress: PASS — no outside DNS attempts or public replies in '${name}'; other attempts inventoried."
    return 0
  fi

  echo "capture-egress: PASS — zero suspect packets at all in '${name}'"
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

assert_dns_attempts() {
  local name="$1" pcap n dns_filter
  pcap="$(pcap_path "$name")"
  [ -f "$pcap" ] || { echo "capture-egress: ${pcap} missing" >&2; return 1; }
  dns_filter="$(dns_bpf)"
  n="$(count_packets "$pcap" "$dns_filter")"
  [ "$n" != "0" ] || { echo 'capture-egress: FAIL — DNS control captured nothing' >&2; return 1; }
  echo "capture-egress: DNS control recorded ${n} outside DNS attempt(s)"
}

case "${1:-}" in
  start) start "${2:?usage: $0 start <name>}" ;;
  stop) stop "${2:?usage: $0 stop <name>}" ;;
  assert-clean) assert_clean "${2:?usage: $0 assert-clean <name>}" ;;
  assert-attempts) assert_attempts "${2:?usage: $0 assert-attempts <name>}" ;;
  assert-dns-attempts) assert_dns_attempts "${2:?usage: $0 assert-dns-attempts <name>}" ;;
  *)
    echo "usage: $0 {start|stop|assert-clean|assert-attempts|assert-dns-attempts} <name>" >&2
    exit 2
    ;;
esac
