# Air-gap verification — credited maintainer implementation

Requested by the maintainer on 2026-10-10; implements roadmap 3.5, DE-032 and
the DNS requirement in
[DE-233](../../PRD.md#de-233--air-gap-install-verification-ci-test).

## Attribution and provenance

[SaifAlYounan](https://github.com/SaifAlYounan) contributed the original
sealed-network design, boot/login/chat driver and packet-evidence inventory in
[PR #427](https://github.com/LegalQuants/lq-ai/pull/427), with original harness
head `6a9ccf8f8669a7244ea9fcbd37a5f6956d2b5483`.
The maintainer added Docker DNS isolation, stricter direct-DNS acceptance,
regressions, integration corrections and precise evidence wording.

This version rebuilds the reviewed change at
`b57c9fbeaf01faf1424123b10612404686f38308` as one signed-off maintainer commit
on canonical main `7ac94dd1a581b745912d100b19ad23d822de6222`, preserving its
executable behavior. Credit appears here, in the runbook, in the original-harness
file headers and in the maintainer commit. The commit uses the maintainer's DCO
sign-off; contributor credit is recorded as provenance.

## Plan

1. Generate a test-only DNS override for every service in the resolved local profile.
   Configure Docker's external DNS upstream as `127.0.0.1` inside each container.
   Docker's embedded resolver at `127.0.0.11` still answers Compose service names;
   external names cannot use the host's resolver. Apply it before fresh boot.
   Use Compose's `!override` tag to replace existing upstreams completely;
   ordinary sequence merging appends them. Requires Compose 2.24.4+.
2. Reject direct UDP/TCP port-53 traffic outside the Compose subnet before the
   bridge's RFC1918 allow rules. A private upstream resolver outside the stack
   must not provide a route around the seal. Scope IPv6 rules to the same bridge.
3. Capture DNS attempts independently of replies. Fail the normal boot/chat window
   on any DNS packet aimed outside the stack; retain inventory-only handling for
   other blocked connection attempts from upstream components.
4. Prove internal service DNS works and fresh external queries fail over UDP/TCP.
   Run deliberate direct DNS probes in a separate negative-control window and
   require the ordinary acceptance check to reject that capture.
5. Verify actual container DNS settings, including completed init containers.
   Add a fast regression job for resolver behavior, capture filters and failure
   handling; publish the DNS override with the evidence; clean up in `always()`.
6. Reconcile the mini-PRD's old DNS exclusion and the runbook's permissive-DNS claim.

## Boundaries and validation

The override changes only DNS upstream selection, not networks, ports, service
commands, images or application code. Host DNS stays available to the runner.
This certifies the shipped stack with an explicit test isolation policy; it does
not claim byte-identical DNS settings or full offline ingestion coverage.

Regression tests must demonstrate an unsealed lookup reaching a controlled DNS
server, internal service-name resolution with the seal, blocked UDP/TCP external
queries, and rejection of direct DNS attempts without replies (IPv4 and IPv6).
The full boot/login/chat acceptance still requires the Linux air-gap CI job.
Workflow and runbook changes require maintainer/security review under CODEOWNERS.

Implementation references: [Docker DNS behavior](https://docs.docker.com/engine/network/#dns-services)
and [Compose replacement semantics](https://docs.docker.com/reference/compose-file/merge/#replace-value).

## Verification performed

- 25 pytest regressions passed, including real Docker UDP/TCP resolver controls
  against a disposable authoritative DNS fixture and stale-container detection.
- Actual tcpdump evaluated IPv4/IPv6 capture fixtures for DNS attempts without
  replies, allowed internal DNS, other blocked attempts and public replies.
- ShellCheck, Bash syntax, Ruff lint/format and workflow YAML checks passed.
- The integration snapshot at `994ccbadef0347366183724adad20ae9c2527dc8`
  applies the override to all 10 local-profile services; all other resolved
  Compose settings compare identical.
- A supplemental patch applies to the pinned PR's harness and reproduces the
  implementation. No GitHub writes, merges or development-volume changes occurred.

The full verification sequence passed on 2026-10-10 against that integration
snapshot plus the PR harness and DNS fix, inside a disposable Linux arm64
Docker daemon: fresh boot, admin login, forced password rotation,
`llama3.2:1b` responding **OK** at Tier 1, resolver controls, packet assertions and
both negative controls. The live firewall recorded one UDP and three TCP DNS
drops. Normal boot/chat had zero outside DNS attempts and zero public replies;
the four observed connection packets were Ollama prefetch FIN teardowns.

Application images were rebuilt from this snapshot with existing cached layers.
The web build used a temporary 5120 MiB Node heap cap to fit available memory;
application source, dependencies and runtime settings were unchanged. The nested
daemon was capped at 5 GiB and eight CPUs, with fresh test volumes.

The 25 DNS regressions were also rerun successfully after applying this patch
directly to contributor head `6a9ccf8f8669a7244ea9fcbd37a5f6956d2b5483`.

The integrated tree on canonical main `7ac94dd1a` additionally passed a fresh
full sealed Linux arm64 run, including migration 0070, both DNS and connection
negative controls, and the login/chat routing assertions. The reviewed source
head `b57c9fbea` then passed both the DNS regression job and the full hosted
Ubuntu sealed-network job in
[Air-gap verify run 38059216345](https://github.com/LegalQuants/lq-ai/actions/runs/38059216345).
The maintainer branch is compared against that source head to confirm identical
executable scripts and workflow steps. Its own hosted checks run after
publication; maintainer/security approval remains a separate requirement.

On the fresh maintainer branch, all 25 DNS regressions passed again, including
the disposable Docker fixture. Bash syntax, ShellCheck and Ruff lint/format
checks passed. Comparison with `b57c9fbea` confirms the scripts, packet filters,
acceptance conditions, tests and workflow steps are unchanged; the differences
are provenance comments and documentation updates.
