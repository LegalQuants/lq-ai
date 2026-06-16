# ADR 0014 — Gateway egress boundary for tool / data-source providers

**Status:** Proposed
**Date:** 2026-06-16
**Owner:** Legal-research + MCP milestone kickoff (feature branch `feat/legal-research-mcp-plan`)

## Context

[PRD §3.6 Research](../PRD.md#36-research) commits real-time legal-information retrieval (CourtListener first) with full Citation-Engine fidelity, and [§8.5 / DE-200](../PRD.md#de-200) commits an MCP-client subsystem. Both want LQ.AI to make **outbound calls to third-party tool/data endpoints** — something the platform does not do today. The only egress the platform performs now is **inference**, and that egress is funnelled through a single audited boundary: the Inference Gateway ([§1.8 security posture](../PRD.md#18-security-posture), [`docs/security/boundary-registers.md`](../security/boundary-registers.md)). The gateway is the only component holding privileged provider credentials and the only place tier-routing, anonymization, and the egress audit log (`inference_routing_log`, `api/app/models/inference.py`) attach.

The closest public prior art — [MikeOSS](https://github.com/willchen96/mike) — implements CourtListener and MCP by **egressing directly from the backend**, with per-user connectors and SSRF guards (`guardedFetch`, `validateRemoteMcpUrl`) bolted onto the backend process. That style contradicts three LQ.AI postures: gateway-as-sole-egress, operator-controlled credentials, and one audited boundary. We want parity on *capability*, not on *implementation style*.

This ADR pins **where third-party tool/data egress lives**. It is load-bearing for the legal-research mini-PRD ([`docs/proposals/legal-research-and-mcp.md`](../proposals/legal-research-and-mcp.md)) WS1, WS2, and WS3, and is the decision record gateway security review (`.github/CODEOWNERS` → `gateway/**`) will check the implementation against.

## Decision drivers

1. **One audited egress boundary, not two.** Adding a second place that holds third-party credentials and makes outbound calls doubles the security-review surface and the audit-gap risk. Whatever we build should extend the existing boundary, not stand up a rival.
2. **Reuse the gateway primitives that already exist.** The gateway has a provider adapter abstraction (`ProviderAdapter`, `gateway/app/providers/base.py`), a router with tier derivation and fallback (`gateway/app/router.py`), config-driven provider declaration (`gateway.yaml` / `gateway.yaml.example`), and Fernet key management (ADR 0011, runtime provider-keys API #128). A tool-provider class should slot into these, not reinvent them.
3. **SSRF / allowlist control is a boundary primitive, not per-call glue.** MikeOSS proves you need HTTPS-required, DNS private-address blocking, host allowlist, no `Host` override, and header validation. Those controls belong in one place that every outbound tool call passes through.
4. **Egress must be auditable in the same shape as inference.** An operator deploying this in a privileged environment needs one log answering "what data left, to whom, at what tier, and what was refused" — mirroring `inference_routing_log`, never logging raw payloads.
5. **Anonymization policy must be decidable for tool-call payloads.** Tool arguments (`find_in_case` keywords, `verify_citations` strings) can carry matter context; returned opinion text is public and must stay verbatim for citation grounding. The boundary is where that policy is enforced (see O1).

## Considered alternatives

### A. A new "tool provider" class inside the gateway — **chosen**

Introduce a **tool provider** (a.k.a. data-source provider) as a first-class gateway concept *distinct from* inference providers but reusing the same machinery. Declared in `gateway.yaml` under a new `tool_providers:` block; routed, tier-tagged, SSRF/allowlist-guarded, and audited by the gateway. The backend never calls a third-party tool endpoint directly — it asks the gateway, exactly as it asks for inference.

- **Cost:** a new provider subpackage (`gateway/app/providers/tool/`), a router path for non-inference egress, a new `tool_egress_log` table, and `gateway.yaml` schema additions. Real engineering, security-reviewed.
- **Why it wins:** every primitive the boundary needs already exists in the gateway and nowhere else. CourtListener becomes the first concrete `type`; each MCP server becomes another. SSRF/allowlist/tier/audit are written once and inherited by every future source (GovInfo, EUR-Lex, SEC EDGAR — DE-280/281). The backend's posture is unchanged: it holds no third-party credentials and makes no third-party calls.

### B. A separate egress-broker service

A dedicated third service (besides `api/` and `gateway/`) that brokers all third-party tool egress.

- **Rejected:** a whole new subsystem — its own deploy unit, auth surface, config, SBOM, and operational story — to do what the gateway is already architected to do. It would *also* need the gateway's tier/anonymization context to make egress decisions, so it would either duplicate that context or call back into the gateway. No capability we lack justifies the second service.

### C. Backend-direct egress with per-call guards (the MikeOSS shape)

The backend calls CourtListener / MCP servers directly, with `guardedFetch`-style SSRF guards inline.

- **Rejected:** breaks the single-boundary posture outright. It puts third-party credentials in the backend (operator-credential-control violation), creates a second un-audited egress path, and scatters SSRF logic across call sites instead of centralizing it. This is exactly the implementation style §1.8 exists to prevent. Named to reject it explicitly, because it is the obvious path and the wrong one.

## Decision

### D1. Tool providers are a new gateway provider class — chosen alternative A

A `tool_providers:` block in `gateway.yaml` declares each source: `name`, `type` (e.g. `courtlistener`, `mcp`), `base_url`, credential reference (`api_key_env` / `api_key_encrypted` / runtime — same three paths as inference providers per ADR 0011 + #128), `tier`, and an allowlist/SSRF policy. A `ToolProviderAdapter` base (sibling to `ProviderAdapter`, NOT a subclass — it exposes `invoke_tool(...)`, not `chat_completion(...)`) lives in `gateway/app/providers/tool/`. The router gains a tool-egress path alongside the inference path; alias/tier-derivation logic is reused where it applies.

> **Note on rate limiting.** The gateway's `RateLimitsConfig` (`gateway/app/config.py`) loads but its **enforcement middleware is not yet wired** (deferred to the gateway's "Phase E"). This ADR does NOT depend on that middleware. Tool-provider rate limiting in v1 is **per-provider, enforced at the tool-provider adapter** (a token-bucket/leaky-bucket the adapter owns), so it ships independently of the global enforcement work. If/when global enforcement lands, the tool-provider limits fold into it. The mini-PRD WS1 must not claim it "reuses" rate-limit enforcement that does not exist.

### D2. SSRF + allowlist controls are a gateway egress primitive

A single guarded-egress helper in the gateway enforces, for every outbound tool call: HTTPS required; DNS resolution checked against private/link-local/loopback ranges (block); host allowlist (per-provider, from config); no caller-supplied `Host` override; outbound header validation. This is the gateway-native equivalent of MikeOSS's `validateRemoteMcpUrl` / `guardedFetch`, written once. No tool-provider adapter may make a raw outbound request that bypasses it.

### D3. Egress audit log: `tool_egress_log`, mirroring `inference_routing_log`

A new table records, per outbound tool call: `timestamp`, `provider`, `tool`, `request_id`, `tier`, `bytes_out` / `bytes_in` (or row counts), `refused` + `refusal_reason`, `anonymization_applied`. **Never raw payloads** — counts and types only, the same guarantee `inference_routing_log` and the OTel anonymization-span contract (ADR 0013 D6) give. This is the operator's single "what data left" view for third-party egress.

### D4. Egress tiering: a tool provider declares a data-egress tier

Each tool provider declares a **data-egress tier** so the gateway can refuse a call whose payload sensitivity exceeds the matter/skill minimum (the inverse of the inference tier-floor: inference floors on *where the model runs*; egress ceilings on *where matter data may travel*). The tier also makes the anonymization decision (D5 / O1) decidable per provider. Concrete tier semantics for egress are pinned in the implementation plan; the *mechanism* (declared tier + gateway refusal + audit row) is fixed here.

### D5. Anonymization applies to outbound tool-call payloads by default (resolves O1)

Outbound tool-call arguments are anonymized by default through the existing M2 anonymization layer, exactly as inference request payloads are. **Inbound** fetched opinion / case text is marked `skip_anonymization` (it is public data, and citation grounding requires verbatim text) — mirroring the existing retrieval-context handling where retrieved chunks carry `lq_ai_skip_anonymization`. Rehydration of returned text into citations follows the same path as document citations. This default can be overridden per provider only with an explicit, audited config flag.

## Open questions (for the implementation plan / contributor)

1. **O2 — object-storage layout for cached opinions.** Reuse the `api/app/storage.py` MinIO/S3 abstraction (ADR 0005 sibling); confirm a key scheme (`courtlistener/opinions/by-cluster/{cluster_id}/...`) and retention policy in the WS3 plan.
2. **Streaming vs. request/response for tool egress.** Inference egress streams (SSE); tool egress is mostly request/response with occasional large bodies (opinion text). Confirm the adapter interface is request/response with a streamed-download escape hatch for large inbound bodies, pinned in WS1.
3. **Where the tool-result-to-citation handoff crosses the boundary.** Returned opinion text must reach the citation engine (`api/app/citation/`) with provenance intact; confirm whether the gateway returns structured provenance the backend persists, or the backend re-derives it. Pin in WS3/WS5.

## Cross-references

- PRD [§1.8](../PRD.md#18-security-posture), [§3.6](../PRD.md#36-research), [§4](../PRD.md#4-the-lq-ai-inference-gateway), [§4.7 anonymization](../PRD.md#47-anonymization-layer), [§8.5 / DE-200](../PRD.md#de-200), [DE-279/280/281](../PRD.md#de-279).
- [ADR 0011](0011-transparency-first-model-selection.md) (provider credential paths this reuses), [ADR 0005](0005-document-pipeline-architecture.md) sibling (storage), [ADR 0013](0013-autonomous-layer-design-influences.md) (the audit/OTel-counts-only guarantee this extends), [ADR 0015](0015-governed-tool-calling-model.md) (the consumer of this boundary — how tool calls are *invoked* and *governed*).
- [`docs/security/boundary-registers.md`](../security/boundary-registers.md) (the egress boundary is a new register entry).
- Mini-PRD: [`docs/proposals/legal-research-and-mcp.md`](../proposals/legal-research-and-mcp.md) (WS1 discharges this ADR).
- Reference (shapes, not implementation): [MikeOSS](https://github.com/willchen96/mike) `validateRemoteMcpUrl` / `guardedFetch`.
