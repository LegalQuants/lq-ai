# Mini-PRD: Air-Gap Install Verification CI Test

> **Status:** Open for contribution
> **Effort:** S-M
> **Contributor profile:** Mid engineer with Docker networking, iptables/nftables, and CI familiarity. Comfortable writing GitHub Actions workflows that exercise a multi-service compose stack and capture network traces. ~one to two focused days.
> **Mentor:** Maintainer (Kevin Keller, via PR review)

## What this is

A new CI job that brings up the full LQ.AI stack with network egress blocked except to a documented allowlist, drives a representative chat through the local-inference path (Tier 1, via Ollama), and asserts that **no container makes an outbound connection to any non-allowlisted destination during the test window**. The test is the structural verification of the project's "Mode 2 air-gap-capable" claim.

The verification fails if any service attempts a telemetry call, an auto-update check, an external analytics ping, a license-server beacon, or any other outbound traffic that isn't to the operator's configured inference provider (and, in air-gap mode, isn't to any external destination at all). The verification is a CI gate; a PR that introduces an unexpected egress path turns the job red.

## Why it matters

[PRD §1.5](../../PRD.md#15-deployment-modes-and-the-inference-choice-spectrum) commits to Mode 2 as "fully air-gap-capable: no outbound network is required." [PRD §1.7](../../PRD.md#17-success-criteria-for-v1-m1-release) lists "No outbound calls in Mode 2 (verified by integration test)" as an M1 success criterion. The compose stack ships with the local-inference profile (`docker compose --profile local up`), which includes `ollama` and `paddleocr` as on-host services so the operator can run Tier 1 inference without any cloud-provider involvement.

What does not yet exist is a CI test that **asserts the air-gap property is actually preserved**. An accidental code path that emits telemetry, checks for updates, fetches a remote configuration, or otherwise contacts an external service would silently violate the air-gap commitment. A regulated-industry operator (defense, healthcare on-prem, EU sovereign deployment, energy, financial services) cannot adopt the project if they cannot verify the air-gap property; "documented in the PRD" is not the same as "verifiable on the operator's own infrastructure."

The CI test closes that gap. It is also a forcing function: every PR that touches a service is verified against the air-gap property at PR time, not at deployment time. If a contributor adds a new dependency that phones home on startup, the test catches it before merge. The structural advantage is that the operator gets to re-run the same test against their own deployment — the test is published in [`docs/security/`](../../security/) so the operator's infrastructure team has the same verification path the project uses internally.

A closed-source vendor's equivalent claim is unverifiable. The operator cannot run their test suite against the vendor's binary; they take the vendor's word for it. Here, the test runs against the actual stack, in the operator's own CI if they choose.

## What we'd ship

Three new files:

```
.github/workflows/
└── airgap-verify.yml          # NEW — runs the air-gap verification on PR + nightly

scripts/airgap/
├── deny-egress.sh             # NEW — sets the deny-all-egress network policy
├── drive-smoke.sh             # NEW — drives a representative chat through Tier 1
└── capture-egress.sh          # NEW — captures egress attempts via netshoot / tcpdump

docs/security/
└── air-gap-verification.md    # NEW — runbook the operator can use to re-run the test
```

**`airgap-verify.yml`** — a CI workflow that:

1. Brings up `docker compose --profile local up -d` (the Mode 2 profile defined in [`docker-compose.yml`](../../../docker-compose.yml) services `postgres`, `redis`, `rustfs`, `gateway`, `api`, `ingest-worker`, `web`, `ollama`, `paddleocr`).
2. Pulls down a small open-weight model into Ollama (e.g., `llama3.2:1b` for CI speed) so a representative chat can complete in seconds.
3. Applies a deny-all-egress network policy to the compose network via `scripts/airgap/deny-egress.sh` (iptables/nftables in the runner; or a sidecar container with NET_ADMIN that programs iptables on the compose bridge).
4. Starts an egress capture via `nicolaka/netshoot` running tcpdump on the bridge, writing to a pcap.
5. Drives a representative chat through the Tier 1 path via `scripts/airgap/drive-smoke.sh` (login, send a message, receive the response, log out). Asserts the chat completed successfully end-to-end.
6. Stops the capture and asserts via `scripts/airgap/capture-egress.sh` that the pcap contains zero packets to any non-private destination (no RFC1918 / loopback / link-local destinations excluded; everything else flagged).
7. Asserts the gateway routing-log shows `provider: ollama`, `tier: 1` exclusively for the test window.
8. Uploads the pcap as a CI artifact for debugging when the test fails.

**`deny-egress.sh`** — applies the deny-all-except-allowlist network policy. The allowlist is documented in the script header (initially empty for the strict-air-gap test; operators who run the same test against their own deployment can add their inference-provider IPs if running Mode 1 with cloud routing).

**`drive-smoke.sh`** — drives a deterministic smoke flow using the existing API. The flow: register a temp user (or use a fixture user), authenticate, create a chat, send "Summarize the attached document" with a small fixture text, wait for the response, verify the response is well-formed, log out. Uses `curl` against the local API; no Node/Python toolchain required.

**`capture-egress.sh`** — parses the pcap and emits a structured report: total packets, destinations grouped by IP, allowlist verdict per destination. Exits non-zero if any non-allowlisted destination appears.

**`air-gap-verification.md`** — operator runbook. Includes: what the test verifies, how the deny-all-egress policy is applied (in the CI; on a Kubernetes deployment via NetworkPolicy; on a bare-metal compose deployment via iptables); how the operator runs the test against their own deployment; how to read the pcap when the test fails; what to do if a PR introduces an unexpected egress path (file an issue with the captured pcap attached).

## How we'd know it's done

- [ ] `.github/workflows/airgap-verify.yml` runs on PRs that touch any of `api/`, `gateway/`, `web/`, `docker-compose.yml`, or `scripts/airgap/`, plus on a nightly schedule.
- [ ] The job is green on the current main branch (no unexpected egress paths exist).
- [ ] The job fails fast and informatively when an egress attempt is detected — the failure includes the destination IP, the offending container, and a pointer to the pcap artifact.
- [ ] `scripts/airgap/deny-egress.sh`, `drive-smoke.sh`, and `capture-egress.sh` are documented and runnable against a local compose stack (not just in CI).
- [ ] `docs/security/air-gap-verification.md` walks the operator through running the same test on their own deployment, with at least one worked example (Docker Compose; Kubernetes is welcome but not required for this PR).
- [ ] The job's runtime is bounded — ideally under 10 minutes — so it does not bottleneck the PR queue. A small open-weight model in Ollama (e.g., `llama3.2:1b` or `qwen2:0.5b`) is acceptable; the test verifies the egress property, not the model quality.
- [ ] The job runs without requiring any cloud-provider credentials — Mode 2 by construction.
- [ ] Allowlist entries are explicit and documented in `deny-egress.sh`; the test rejects any drift from the allowlist as a PR-breaking failure.
- [ ] [PRD §1.7 success criterion](../../PRD.md#17-success-criteria-for-v1-m1-release) ("No outbound calls in Mode 2 (verified by integration test)") is updated to link the workflow file.

## Where to start

1. Read [PRD §1.5 Deployment Modes](../../PRD.md#15-deployment-modes-and-the-inference-choice-spectrum) — Mode 2 ("self-hosted with local inference, air-gap-capable") is the property under test.
2. Read [PRD §1.7](../../PRD.md#17-success-criteria-for-v1-m1-release) — the M1 success criterion explicitly names "verified by integration test."
3. Read [`docker-compose.yml`](../../../docker-compose.yml) in full, particularly the `--profile local` services (`ollama` around line 304 and `paddleocr` around line 333). Understand which services are required for Mode 2 and which are no-ops when offline.
4. Read [`.github/workflows/ci.yml`](../../../.github/workflows/ci.yml) for the existing CI workflow conventions: how the workflow header documents scope, how services are brought up, how artifacts are uploaded. The new workflow follows the same conventions.
5. Read [`gateway/app/api/inference.py`](../../../gateway/app/api/inference.py) and [`gateway/app/providers/ollama.py`](../../../gateway/app/providers/ollama.py) to confirm the Tier 1 routing path. Cross-reference the tier-floor enforcement in [`gateway/app/tier_floor.py`](../../../gateway/app/tier_floor.py).
6. Read [`gateway/app/routing_log.py`](../../../gateway/app/routing_log.py) to understand how to verify "the request actually routed to Ollama" from the routing-log table.
7. Decide on the egress-block implementation. Two viable approaches:
   - **iptables on the GitHub Actions runner.** Simpler; works if the runner is Linux with full iptables. Programs OUTPUT chain to DROP everything except RFC1918, loopback, and the runner's own metadata service.
   - **Docker network isolation.** Create the compose stack on a custom bridge with no default-gateway route. Verifies the property at the compose-network layer rather than the host layer. More reflective of a real deployment.
   - The runbook in `air-gap-verification.md` documents both approaches; the CI test uses the one that fits the GitHub Actions runner environment.
8. Use `nicolaka/netshoot` as the capture sidecar (https://github.com/nicolaka/netshoot) — it ships with `tcpdump`, `tshark`, and the network-debugging utilities needed for both the capture and the failure-diagnosis paths.
9. Write `drive-smoke.sh` as `curl`-based commands against the API. The chat-creation + message-send + message-poll flow is the simplest deterministic smoke; reference the OpenAPI sketch in [`docs/api/backend-openapi.yaml`](../../api/backend-openapi.yaml) for the request shapes.
10. Iterate on the test locally before pushing the workflow — bring the stack up on a personal Linux machine, run the egress-block, drive the smoke, inspect the pcap. The CI workflow is a faithful reproduction of the local procedure.

## Scope cuts (what's out of scope for this PR)

- The workflow does not test Mode 1 (cloud-provider routing). Mode 1's egress is intentional; the test would always pass trivially or always fail trivially depending on whether the allowlist is open. A separate test could verify that Mode 1's egress is **only** to the configured providers; that is a follow-on PR.
- The workflow does not test Kubernetes / Helm-chart deployment egress. The Helm chart is itself deferred (DE-030); when the chart lands, a follow-on PR adds an equivalent test using NetworkPolicy.
- DNS-level egress detection (catching a service that resolves an external hostname even without traffic) is out of scope. The pcap-based assertion catches the actual packet, which is the substantive property; DNS resolution without traffic is a false positive for the air-gap property.
- The test does not verify Mode 2 inference quality. Model quality is a separate testing concern; this test verifies the egress property.
- The runbook documents the Compose-based test path; the Kubernetes path is welcome but not required for this PR.
- The test does not assert the absence of inbound traffic; the air-gap property is about outbound traffic.

## How this strengthens the project

The CI gate gives the project's air-gap commitment a continuous verification that runs on every PR. A regulated-industry operator can adopt LQ.AI in Mode 2 with structural confidence that "no outbound calls" is enforced, not just promised. The same operator can re-run the published test against their own deployment to verify the property on their infrastructure — a verification path that does not exist for any closed-source equivalent, where the operator cannot inspect the binary's network behavior at any depth without violating the EULA.

The test is also a forcing function for the contributor experience. Any code path that introduces an unexpected egress (a new dependency that phones home; an analytics call accidentally enabled; a debug telemetry knob left flipped on) is caught at PR time rather than at deployment time. The property the test verifies is concrete; the contributor knows when they have broken it.

## References

- [PRD §1.5 Deployment Modes and the Inference Choice Spectrum](../../PRD.md#15-deployment-modes-and-the-inference-choice-spectrum)
- [PRD §1.7 Success Criteria for v1 (M1 Release)](../../PRD.md#17-success-criteria-for-v1-m1-release)
- [PRD §1.8 Security Posture](../../PRD.md#18-security-posture)
- [PRD §6 Deployment](../../PRD.md#6-deployment)
- [PRD §9 — DE-032 Air-gap install verification](../../PRD.md#9-deferred-enhancements-and-identified-future-work)
- [`docker-compose.yml`](../../../docker-compose.yml) — the compose stack under test
- [`.github/workflows/ci.yml`](../../../.github/workflows/ci.yml) — existing CI workflow conventions
- [`gateway/app/providers/ollama.py`](../../../gateway/app/providers/ollama.py) — Tier 1 inference path
- [`gateway/app/tier_floor.py`](../../../gateway/app/tier_floor.py) — tier-floor enforcement
- [`gateway/app/routing_log.py`](../../../gateway/app/routing_log.py) — routing-log persistence (verification surface)
- `nicolaka/netshoot` (network-debug container): https://github.com/nicolaka/netshoot
- Related: [Mini-PRD: OpenSSF Scorecard + Best Practices Badge](openssf-scorecard-and-badges.md), [Mini-PRD: Reverse-proxy + TLS deployment recipes](reverse-proxy-tls-deployment-recipes.md)

## Definition of "merged"

The PR is merged when (a) the acceptance criteria checklist is fully checked off, (b) the CI job runs green on the PR branch and on `main`, (c) the maintainer has reviewed the workflow and the runbook, and (d) the runbook is reproducible by a non-maintainer on a clean Linux host. Practicing-attorney attestation is not required for this engineering-discipline contribution.
