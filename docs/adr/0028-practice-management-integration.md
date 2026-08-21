# ADR 0028: Practice-management-system integration architecture (registry, adapter protocol, credential models)

Status: Draft; revised 2026-08-20 after first maintainer review (issue 529, PR 530).
The revision generalizes this ADR per that review: the ARCHITECTURE lives here,
vendor-agnostic; the specific product—which vendors ship first, at what
verification maturity, with what acceptance criteria—lives in the companion
[mini-PRD](../proposals/practice-management-integration.md). Committee acceptance
is still the gate before any implementation PR.
Date: 2026-08-18 (revised 2026-08-20)
Relates to: [ADR 0014](0014-gateway-egress-boundary-for-tool-providers.md) (sole
audited egress), [ADR 0015](0015-governed-tool-calling-model.md) (governed tool calls),
[ADR 0016](0016-transparency-and-governance-invariants.md) (P3 no raw payloads),
[ADR 0021](0021-content-source-registry-and-free-source-expansion.md) (the registry
pattern this mirrors), PRD §9
[DE-206](../PRD.md#de-206--document-store-connectors-via-mcp) /
[DE-040](../PRD.md#de-040--direct-clm-integration) (the prior "via MCP" posture this
had to be reconciled with).

---

## Context

A firm that runs on a practice management system lives inside it: the PMS is the
record of every matter and everything in it. LQ.AI cannot see it. Today the bridge
is manual—export, re-upload, and when the work product is done, download and
re-file by hand. Every crossing loses provenance, and "which version did I
analyze?" lands on the attorney.

The PMS market is not one thing. Hundreds of products exist, and there is no
uniform connection story: some vendors offer per-user OAuth with self-serve
developer credentials; some authenticate an org-scoped service account with a
personal access token; some gate API access behind a paid tier and a support
ticket; a couple of vendors offer webhooks, and most offer nothing. Any
architecture that assumes one auth shape, one credential model, or one capability
surface is wrong on arrival. So this ADR pins a GENERAL architecture—a registry,
an adapter protocol, declared capabilities, and enumerated credential models—that
any PMS can slot into. Which vendors get adapters first, and why, is a product
decision that belongs in the mini-PRD, not here.

Three postures constrain everything: the gateway as sole audited egress
(ADR 0014), closed-set governed tool access (ADR 0015), and honest off-by-default
capability reporting (ADR 0021 D5). Two pieces of shipped prior art carry most of
the weight:

1. The content-source registry (ADR 0021). Free authority sources sit behind one
   backend registry (`api/app/research/registry.py`) joined at read time against
   the gateway's live `tool_providers` config. The pattern—registry, adapter,
   gateway egress, off by default, unavailable-with-reason—is proven; this ADR
   copies it deliberately.
2. The MCP-client subsystem (HONEST-STATE §5.5). Per-user OAuth tokens
   Fernet-encrypted at rest, a complete authorize/callback/status/disconnect
   surface (`api/app/api/mcp_oauth.py`), and gateway-brokered OAuth egress
   (`oauth_passthrough.py`). The per-user credential problem is already solved
   once; this ADR reuses that machinery rather than re-deriving it.

One thing had to be confronted head-on rather than footnoted: PRD §9 has no PMS
DE, and the closest statements of intent both lean the other way.
[DE-206](../PRD.md#de-206--document-store-connectors-via-mcp) commits
document-store connectors "via MCP," and
[DE-040](../PRD.md#de-040--direct-clm-integration) rejects direct CLM scope with
"the MCP path (M5+) is the integration story." So "why not MCP?" is the first
question this ADR answers.

## Decision drivers

1. One audited egress boundary. Vendor API calls carrying matter data originate
   at the gateway—SSRF/allowlist-guarded, tier-tagged, written to
   `tool_egress_log`. No second egress path, including an indirect one.
2. Vendor neutrality. This project does not endorse a PMS, and the architecture
   must not encode a preference. The registry is an open extension point; any
   vendor with a usable API can be added without touching the core.
3. Credentials never reach `api/`. Client secrets and service-account tokens are
   gateway-held (Fernet, ADR 0011 paths); per-user access tokens are stored
   encrypted by the api (the shipped MCP posture) and transmitted only to the
   gateway for header injection—never logged, never returned to a client.
4. Matter data is client-confidential. Every source in ADR 0021's registry is
   public authority; this one is privileged, tenant-scoped, and bidirectional.
   The failure mode is not a missing citation—it is a confidentiality incident or
   a corrupted matter record. Every default has to be the conservative one.
5. Writes are malpractice-adjacent. A generated draft landing in a matter folder
   must be individually human-approved and permanently distinguishable from
   attorney work product; the write surface stays minimal (documents and notes—
   never deadlines, time, or billing in v1).
6. Vendors differ, and pretending otherwise breaks things. Auth shapes, API
   surfaces, and capability sets vary per vendor; partial adapters are
   first-class via capability declaration, and nothing gets implied working that
   is not verified.
7. Citations must stay verifiable. A pulled document flows through the existing
   ingestion pipeline so the Citation Engine can verify against it; no parallel
   path.
8. Maintainability is a design input, not an afterthought. Vendor APIs drift.
   The architecture must make drift visible, bound its blast radius to one
   adapter, and leave a retirement path per vendor.

## Considered alternatives

### A. First-class gateway tool-provider types + a sibling PMS registry (chosen)

Each supported vendor becomes a new `type` under the existing gateway
`tool_providers` class—a sibling of `courtlistener` and `govinfo`—with a backend
PMS registry mirroring ADR 0021 D1's split: gateway holds
transport/auth/tier/allowlist; backend holds vendor semantics, capability
declarations, and domain adapters; the live registry is the join.

Why it wins: vendor egress happens AT the audited boundary. Every call is
SSRF-guarded, rate-limited, tier-tagged, and logged by a provider class that
already exists and has already been security-reviewed. The ADR 0021 posture (off
by default, unavailable-with-reason, no secrets in the join) transfers intact,
and the MCP OAuth machinery covers per-user credentials.

### B. Model the PMS as MCP servers (the DE-206 / DE-040 direction) (rejected, with a standing reopen condition)

The attraction is real on two axes. Zero new gateway code, with per-user OAuth
and tool discovery free. And maintenance: a VENDOR-maintained MCP server would
shift the API-drift burden onto the party that controls the API—a legitimate
long-term consideration this project should weigh for any integration.

Rejected anyway, and here is the problem: no PMS vendor operates a hosted MCP
server. Third-party self-hosted servers exist for several vendors (verified
2026-08-18; the mini-PRD carries specifics), and a self-hosted bridge means the
actual vendor egress happens at the bridge, outside the gateway's
SSRF/allowlist/audit boundary—the gateway would audit only the hop to the
bridge. That is the "separate egress-broker service" shape ADR 0014 explicitly
rejected, wearing an MCP costume. And the capabilities this feature actually
needs—matter sync, a live document index, capability-aware UX,
provenance-stamped writes—all require first-class backend code regardless of
transport, so MCP saves less than it appears to.

The reopen condition is standing and per-vendor (D9): if a vendor ships an
OFFICIAL HOSTED MCP server, that vendor's adapter can retire in its favor, and
the maintenance argument then points the other way. An operator can also already
connect any PMS MCP server that exists through the shipped MCP subsystem, with
generic chat-tool access; this ADR does not close that path—it builds what that
path cannot deliver.

### C. Backend-direct vendor calls from `api/` (rejected)

Violates ADR 0014. Named only to name it.

### D. Extend ADR 0021's content-source registry (rejected)

The two registries differ on every axis that matters: direction (read-only vs
bidirectional), data class (public authority vs client-confidential), auth
(operator key vs per-user OAuth or service account), and failure mode (missing
citation vs confidentiality incident). Merging them forces conditionals through
every code path of a shipped, security-reviewed subsystem. Sibling, not
extension.

## Decisions

### D1. A vendor-generic registry and adapter protocol; vendors are entries, not architecture

Gateway side: each supported PMS is a `tool_providers` `type` with an adapter in
`gateway/app/providers/tool/`. Every outbound call passes
`validate_egress_target`; per-provider token buckets honor vendor rate headers
and `Retry-After`; every call writes `tool_egress_log`—counts and types only,
per P3. Base URLs are gateway-owned constants keyed by a region enum, never
client-supplied (the same `extra="forbid"` SSRF backstop the existing
`/api/v1/admin/tool-providers` surface uses).

Backend side: `api/app/pms/registry.py` mirrors `research/registry.py`—a
`PMSSpec` per type carrying the vendor name, a CAPABILITY SET (`list_matters`,
`fetch_document`, `push_document`, `create_note`, extensible), an AUTH MODEL
(D3's enum), and the response adapter that normalizes vendor payloads to LQ.AI
domain models with a `vendor_native` passthrough. The live registry is the join
against `list_tool_providers()`: configured AND adapter-shipped means available;
registered-but-unconfigured is reported unavailable with a reason, never
silently dropped.

Adding a vendor is an adapter plus a registry row—no core changes, no schema
changes, no new endpoints. Capability declaration is load-bearing, not
decorative: an adapter declares only what its vendor's API actually supports,
and the UI and service refuse up front ("this adapter cannot do X") rather than
failing mid-operation.

### D2. The project prefers no vendor

This architecture makes no statement about which PMS a firm should run. The
registry is an open extension point; any vendor with a usable API can be
contributed under this ADR without a new ADR. Which adapters ship FIRST is a
product-sequencing decision, made in the mini-PRD against stated, checkable
criteria (API accessibility, self-serve credentials, market coverage, and
auth-shape diversity to prove the abstraction)—not a quality judgment among
vendors, and the docs must never present it as one. Every adapter, whoever
contributes it, meets the same bar: capability honesty, recorded-fixture tests,
and an HONEST-STATE row with a verification path.

### D3. Two-layer credentials with enumerated auth models

Layer 1—deployment registration (admin, once per vendor): whatever the vendor
requires at the deployment level (an OAuth client-credential pair, a
service-account token), stored gateway-side via the existing Fernet paths and
configured at runtime through a constrained admin proxy mirroring
`/api/v1/admin/tool-providers`. Accepted fields are type, credentials, and
region; URLs stay gateway-owned. A missing master key surfaces as the gateway's
existing typed 400, and the settings UI explains it.

Layer 2—per-user connection, where the vendor's model has one. The
authorization-code round trip reuses the MCP OAuth flow skeleton: single-use
TTL'd state rows binding callback to user, origin-validated `return_url`,
status and disconnect endpoints, token bytes never returned to any client.
Tokens land in a sibling `pms_oauth_tokens` table—same key shape and encryptor
as `mcp_oauth_tokens`, its own cascade semantics on vendor removal. Two deltas
from the MCP flow, both gateway-side: confidential clients (the gateway injects
the client secret at token exchange, so it never transits `api/`) and static
vendor endpoints carried as per-region adapter constants (PMS vendors do not
implement RFC 9728 discovery).

The auth model is an ENUM on the registry spec, because vendors genuinely
differ: `per_user_oauth` (confidential authorization-code; each attorney
connects an account) and `org_service_account` (a deployment-level token; no
per-user surface; every vendor-side action attributed to one integration user)
ship first, and the enum grows when a vendor demands a third shape. An
org-scoped model carries consequences pinned in D8. The asymmetry is modeled,
not flattened.

### D4. v1 is UI-driven; the model gets no PMS access

Every PMS action in v1 is a human clicking something. The REST surface calls the
gateway the way `research/service.py` does; the gateway audits egress; api-side
`audit_action` rows record who did what. No additions to the chat tool-loop
allowlist, no new `ToolIntent` members, no `PHASE_GRANTS` changes.
Client-confidential egress stays out of the model's hands entirely in v1, the
ADR 0015 surface goes untouched, and the human-gate requirement is satisfied by
construction. Model-driven PMS access is a future DE with its own design cycle.

### D5. Read path: sync the matters, index every document, pull content only on selection

Three layers; only the third moves document content.

1. Matter sync, bulk, at connect. The vendor's matters map into LQ.AI's matters
   (Projects) by creating a Project or linking an existing one—a
   `pms_matter_links` row carrying synced metadata and sync provenance. Bulk
   mapping happens once; there is no ongoing full re-sync.
2. A document index per linked matter. `pms_document_index` holds metadata
   only—names, folders, modified dates, a `version_marker`, a nullable
   `pulled_file_id`—refreshed per D6. No content.
3. Pull on selection. A selected document pulls through the normal path: `File`
   → ingestion → `Document` with `normalized_content` and character offsets,
   exactly like an upload, so citations verify through the existing KB cascade
   with zero new verification machinery. The `version_marker` gives dedupe and
   re-pull; a pull whose ingestion yields no extractable text is marked "no
   extractable text—not citable" at pull time (the pipeline has no OCR, DE-320,
   and PMS repositories are full of scanned pleadings and stamped orders).

Nobody bulk-loads a repository they will never read; nobody waits on a sync to
analyze the one pleading they care about. Bulk sync and matter linking are admin
or project-owner acts; the index and pull are available to members of the linked
Project; a synced Project carries the existing `privileged` /
`minimum_inference_tier` controls, surfaced at sync time with a recommendation.
The matter link doubles as the addressing layer for D7 writes.

### D6. Index freshness: webhooks where the vendor offers them, polling everywhere

The inbound webhook receiver is a genuinely new surface for this codebase
(everything existing is egress): a public api endpoint that verifies the
vendor's signature, updates `pms_document_index` / `pms_matter_links`, and does
nothing else—no vendor calls, no secrets—isolated in its own security-reviewed
PR. Polling (through the gateway, rate-limit-respecting) is the fallback for
vendors without webhooks and for deployments without a publicly reachable
callback URL. Conflict resolution on divergent edits stays out of scope; the
index is a mirror of the vendor's list, never an authority.

### D7. Write path: document push and note creation, per-action confirmation, provenance stamped

Surface: `push_document` and `create_note`, addressed through the D5 matter
link. Explicitly excluded from v1: time entries, billing, tasks, contacts, and
calendar/deadline writes (deadline writes are malpractice-adjacent and deserve
their own design cycle). Every push renders an explicit confirmation naming the
target matter, filename, and destination folder; no batch writes. Provenance is
a separate requirement from confirmation: the gate answers "did a human approve
this"; provenance answers "what is this, six months later, sitting in the
matter folder looking like attorney work product." Every pushed document
carries a filename convention marking AI-assisted origin plus a companion
activity note recording the model tier, the acting LQ.AI user, and the
session/chat id—and where a vendor offers no note surface, provenance rides in
metadata/filename and the gap is documented. Write-capable specs are marked
`destructive` + `requires_confirmation`; per ADR 0015 D4 they are excluded from
autonomous grants categorically, and per D4 they are not model-callable either.

### D8. Confidentiality posture

- Egress tier 2, operator-overridable: the destination is the client's own
  contractually-bound system of record, not a public API (public authority
  sources sit at 4).
- `anonymize_outbound: false`, as the explicit audited per-provider override
  ADR 0014 D5 provides—outbound arguments are identifiers and queries against
  the system that already holds the client's data, and pseudonymizing them
  breaks lookups while protecting nothing. Inbound pulled content is ordinary
  KB content: the M2 layer applies at inference egress.
- An `org_service_account` vendor sees the whole org, so LQ.AI must not become
  a privilege-escalation path: org-wide operations (matter list, linking) are
  admin/project-owner-gated; ordinary users work only inside linked Projects;
  vendor-side audit attribution limits are documented prominently, and push
  provenance names the real acting user in the note body.

### D9. Maintainability: drift is bounded, visible, and per-adapter

Vendor APIs change; the architecture plans for it rather than hoping.

- Each adapter pins a DOCUMENTED, VERSIONED vendor API surface (the version in
  the adapter's constants, asserted in its tests). Recorded-fixture suites
  double as drift detectors: when a vendor changes a response shape, the
  fixtures fail loudly in CI, in that adapter only.
- The blast radius of drift is one adapter. Nothing in the core—registry,
  credential machinery, sync/index/pull, write gate—depends on any vendor's
  shapes; the adapter is the only translation point.
- The HONEST-STATE row is the maintenance contract: every adapter ships with a
  named verification path an operator can run. An adapter nobody can verify
  anymore degrades to unavailable-with-reason (P4—fail restrictive), never to
  silently wrong.
- Per-vendor retirement path: a vendor that ships an official hosted MCP server
  reopens alternative B for that vendor, and its adapter can be retired in
  favor of the vendor-maintained surface.

### D10. Off by default; honest state; clean uninstall

No PMS type ships enabled; unconfigured means unavailable-with-reason. The
master admin toggle gates UI visibility only—the enforcement is, as everywhere,
the gateway config. Each adapter lands in `HONEST-STATE.md` with a verification
path, and an adapter built against documentation alone ships explicitly labeled
unverified with its promotion path named. Disabling a provider makes it
unavailable immediately; per-user tokens are retained encrypted until an
explicit "disconnect all users" (with a surfaced count), and removing a
vendor's registration cascade-deletes its `pms_oauth_tokens` rows. Matter links
and the document index deactivate but are not destroyed (they are provenance);
pulled documents are the firm's work product and remain, governed by the
existing ADR 0005 lifecycle. Switching vendors is disconnect-all plus fresh
setup, with a warning—a migration flow is a DE, not a v1 feature.

## What still needs an outside answer

1. Committee acceptance. This ADR travels as PR 530 for community comment per
   the ADR-first rule (2026-07-19 committee call); implementation PRs wait
   behind it. Scope decisions land at the weekly Sunday call or async on issue
   529, with 7-day ratification on minutes.
2. The DE number. DE-388 is proposed; numbering was checked against open PRs on
   2026-08-18 (ADR 0026 claimed by both PR 528 and PR 418, ADR 0027 by PR 430,
   DE-387 by PR 528) and moves with the merge queue.
3. Vendor-specific open items (redirect-URI policies, tenant verification
   steps) live in the mini-PRD §7, where the vendors do.

## Cross-references

- PRD [§1.8](../PRD.md#18-security-posture), [§4](../PRD.md#4-the-lq-ai-inference-gateway),
  §9 [DE-206](../PRD.md#de-206--document-store-connectors-via-mcp) /
  [DE-040](../PRD.md#de-040--direct-clm-integration) /
  [DE-320](../PRD.md#de-320--scanned-pdf-ocr-for-the-ingestion-pipeline).
- ADRs [0005](0005-file-storage-soft-delete-and-key-scheme.md),
  [0011](0011-transparency-first-model-selection.md),
  [0014](0014-gateway-egress-boundary-for-tool-providers.md),
  [0015](0015-governed-tool-calling-model.md),
  [0016](0016-transparency-and-governance-invariants.md),
  [0021](0021-content-source-registry-and-free-source-expansion.md).
- Product scope, reference adapters, and acceptance criteria:
  [`docs/proposals/practice-management-integration.md`](../proposals/practice-management-integration.md).
- Phase-0 record: [issue 529](https://github.com/legalquants/lq-ai/issues/529),
  [PR 530](https://github.com/legalquants/lq-ai/pull/530).
- Precedent code: `api/app/research/registry.py` + `service.py`,
  `api/app/api/mcp_oauth.py` + `api/app/models/mcp_oauth.py`,
  `gateway/app/providers/tool/` (`egress.py`, `mcp.py`, `oauth_passthrough.py`),
  `api/app/api/admin.py` (tool-providers proxy),
  `web/src/routes/lq-ai/admin/research-sources/+page.svelte`.
