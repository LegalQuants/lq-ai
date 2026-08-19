# ADR 0028: Practice-management-system integration (PMS registry, sibling to ADR 0021)

Status: Draft; proposer-settled, NOT maintainer-reviewed. The five design forks in
the first draft were settled 2026-08-18, and the read path was revised the same day
(registry over MCP; sibling token table; UI-driven v1 with matter sync + document
index + pull-on-selection; webhook ingress for index freshness; egress tier 2; new
DE-388). Maintainer acceptance is still the gate before any implementation PR.
Date: 2026-08-18
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

An in-house team or a small firm lives inside its practice management system—Clio,
Filevine, or MyCase. That system is the record of every matter and everything in it.
LQ.AI cannot see it. Today the bridge is manual: export from the PMS, re-upload to
LQ.AI, and when the work product is done, download it and re-file it by hand. Every
crossing loses provenance, and "which version did I analyze?" lands on the attorney.

This ADR pins how LQ.AI connects to a PMS without weakening the three postures the
platform is built on: the gateway as sole audited egress (ADR 0014), closed-set
governed tool access (ADR 0015), and honest off-by-default capability reporting
(ADR 0021 D5).

Two pieces of shipped prior art constrain the design:

1. The content-source registry (ADR 0021). GovInfo, SEC EDGAR, and EUR-Lex sit
   behind one backend registry (`api/app/research/registry.py`) joined at read time
   against the gateway's live `tool_providers` config. The pattern—registry, adapter,
   gateway egress, off by default, unavailable-with-reason—is proven; this ADR copies
   it deliberately.
2. The MCP-client subsystem (HONEST-STATE §5.5). Per-user OAuth tokens
   Fernet-encrypted at rest (`mcp_oauth_tokens`), a complete
   authorize/callback/status/disconnect surface (`api/app/api/mcp_oauth.py`), and
   gateway-brokered OAuth egress (`oauth_passthrough.py`). The per-user credential
   problem is already solved once; this ADR reuses that machinery rather than
   re-deriving it.

One thing had to be confronted head-on rather than footnoted: PRD §9 has no PMS DE,
and the closest statements of intent both lean the other way.
[DE-206](../PRD.md#de-206--document-store-connectors-via-mcp) commits document-store
connectors "via MCP," and [DE-040](../PRD.md#de-040--direct-clm-integration) rejects
direct CLM scope with "the MCP path (M5+) is the integration story." So "why not
MCP?" is the first question this ADR answers.

## Decision drivers

1. One audited egress boundary. Vendor API calls carrying matter data originate
   at the gateway—SSRF/allowlist-guarded, tier-tagged, written to `tool_egress_log`.
   No second egress path, including an indirect one.
2. Credentials never reach `api/`. OAuth client secrets and service-account
   tokens are gateway-held (Fernet, ADR 0011 paths). Per-user access tokens are
   stored encrypted by the api (the shipped MCP posture) and transmitted only to the
   gateway for header injection; never logged, never returned to a client.
3. Matter data is client-confidential. Every source in ADR 0021's registry is
   public authority; this one is privileged, tenant-scoped, and bidirectional. The
   failure mode is not a missing citation—it is a confidentiality incident or a
   corrupted matter record. Every default has to be the conservative one.
4. Writes are malpractice-adjacent. A generated draft landing in a matter folder
   must be individually human-approved and permanently distinguishable from attorney
   work product; the write surface stays minimal (documents and notes—never
   deadlines, time, or billing in v1).
5. Vendors differ, and pretending otherwise breaks things. Filevine
   authenticates as an org service account, not per-user OAuth, and has no DocGen.
   MyCase is approval-gated behind its Advanced tier (~$109/user/month) and
   realistically untestable without a paid tenant. Partial adapters are first-class
   via capability declaration; nothing gets implied working that is not verified.
6. Citations must stay verifiable. A pulled document flows through the existing
   ingestion pipeline so the Citation Engine can verify against it; no parallel
   path (D4 layer 3).

## Considered alternatives

### A. First-class gateway tool-provider types + a sibling PMS registry (chosen)

Each vendor becomes a new `type` under the existing gateway `tool_providers` class
(`clio`, `filevine`, `mycase`—siblings of `courtlistener` and `govinfo`), with a
backend PMS registry mirroring ADR 0021 D1's split: gateway holds
transport/auth/tier/allowlist; backend holds vendor semantics, capability
declarations, and domain adapters; the live registry is the join.

Why it wins: vendor egress happens AT the audited boundary. Every Clio call is
SSRF-guarded, rate-limited, tier-tagged, and logged by a provider class that already
exists and has already been security-reviewed. The ADR 0021 posture (off by default,
unavailable-with-reason, no secrets in the join) transfers intact, and the MCP OAuth
machinery covers Layer-2 credentials.

### B. Model the PMS as MCP servers (the DE-206 / DE-040 direction) (rejected)

The attraction is real: zero new gateway code, and per-user OAuth, tool discovery,
and confirmation gating all come free. And MCP servers for these vendors are not
hypothetical—third-party self-hosted servers exist for all three (Oktopeak's
`clio-mcp` and `filevine-mcp`, RosenAdvertising's `mycase-mcp`; verified
2026-08-18). Rejected anyway (settled 2026-08-18), and here is the problem: every
one of those is a self-hosted local bridge, and none of the three vendors operates
a HOSTED MCP server. A self-hosted bridge means the actual vendor egress happens at
the bridge, outside the gateway's SSRF/allowlist/audit boundary; the gateway would
audit only the hop to the bridge. That is the "separate egress-broker service"
shape ADR 0014 explicitly rejected, wearing an MCP costume. And the capabilities
this feature actually needs—matter sync, a live document index, capability-aware
UX, provenance-stamped writes—all require first-class backend code regardless of
transport, so MCP saves less than it appears to.

Kept honest: an operator can already connect any PMS MCP server that exists through
the shipped MCP subsystem, with generic chat-tool access. This ADR does not close
that path; it builds what that path cannot deliver. If a vendor ships an official
hosted MCP server, revisit for that vendor.

### C. Backend-direct vendor calls from `api/` (rejected)

Violates ADR 0014. Named only to name it.

### D. Extend ADR 0021's content-source registry (rejected)

The two registries differ on every axis that matters: direction (read-only vs
bidirectional), data class (public authority vs client-confidential), auth (operator
key vs per-user OAuth or service account), and failure mode (missing citation vs
confidentiality incident). Merging them forces conditionals through every code path
of a shipped, security-reviewed subsystem. Sibling, not extension.

## Decisions

### D1. PMS vendors are first-class gateway tool-provider types; a sibling backend registry holds vendor semantics

Gateway side: `tool_providers` entries with `type: clio | filevine | mycase`,
adapters in `gateway/app/providers/tool/`. Every outbound call passes
`validate_egress_target`; per-provider token buckets honor vendor rate headers (Clio:
50 req/min per token at peak, `Retry-After` on 429); every call writes
`tool_egress_log`—counts and types only, per P3. Regional base URLs are gateway-owned
defaults keyed by a region enum, never client-supplied (the same `extra="forbid"`
SSRF backstop the existing `/api/v1/admin/tool-providers` surface uses).

Backend side: `api/app/pms/registry.py` mirrors `research/registry.py`—a `PMSSpec`
per type carrying vendor name, capability set (`list_matters`, `push_document`,
`create_note`, `fetch_document`), auth model (`per_user_oauth` for
Clio and MyCase; `org_service_account` for Filevine), and the response adapter that
normalizes vendor payloads to LQ.AI domain models with a `vendor_native`
passthrough. The live registry is the join against `list_tool_providers()`:
configured AND adapter-shipped means available; registered-but-unconfigured is
reported unavailable with a reason, never silently dropped.

Capability declaration is load-bearing, not decorative. Filevine supports plain
document upload (so it declares `push_document`) but has no server-side DocGen;
MyCase declares its narrower surface. The UI and service refuse up front—"this
adapter cannot do X"—rather than failing mid-operation.

### D2. v1 is UI-driven; the model gets no PMS access

Every PMS action in v1 is a human clicking something: sync matters, push a document,
write a note. The REST surface calls the gateway the way `research/service.py`
does; the gateway audits egress; api-side `audit_action` rows record who did what.

No additions to the chat tool-loop allowlist, no new `ToolIntent` members, no
`PHASE_GRANTS` changes. Client-confidential egress stays out of the model's hands
entirely in v1, the ADR 0015 surface goes untouched (a smaller security review), and
the human-gate requirement is satisfied by construction: the human initiates every
action, and writes get an explicit confirmation on top (D5). Model-driven PMS access
is a future DE with its own design cycle.

### D3. Two-layer credentials, reusing the shipped machinery

Layer 1—deployment registration (admin, once per vendor). OAuth client ID and
secret (Clio, MyCase) or a service-account PAT (Filevine), plus region. Stored
gateway-side via the existing Fernet paths (`api_key_encrypted` /
`LQ_AI_GATEWAY_MASTER_KEY`; the config schema gains an `oauth` sub-block for the
client-credential pair). Configured at runtime through a constrained admin proxy
mirroring `/api/v1/admin/tool-providers`: accepted fields are `type`, credentials,
and `region`—base URLs and allowlists stay gateway-owned. A missing master key
surfaces as the gateway's existing typed 400, and the settings UI explains it
instead of failing obscurely.

Layer 2—per-user connection (Clio and MyCase). The authorization-code round
trip reuses the MCP OAuth flow skeleton: single-use TTL'd state rows binding
callback to user, origin-validated `return_url`, status and disconnect endpoints,
token bytes never returned to any client. Tokens land in a NEW sibling table,
`pms_oauth_tokens` (settled 2026-08-18)—same `(user_id, provider_name)` key, same
Fernet encryptor, its own cascade semantics so removing a vendor cleanly deletes its
tokens. Two deltas from the MCP flow, both gateway-side: the vendor token exchange
needs a client secret, which the gateway injects in `oauth_passthrough` so the
secret never transits `api/`; and PMS vendors publish static authorize/token
endpoints rather than RFC 9728 discovery, so the adapter carries per-region
constants. A couple of real changes, but both live at the boundary that was built
for exactly this. At call time the api forwards the user's decrypted access token per
request (the existing `user_token` parameter on the tool-provider ABC); the gateway
injects vendor headers (`Authorization`, plus Filevine's `x-fv-orgId` /
`x-fv-userId`).

The Filevine asymmetry is modeled, not flattened: Layer-1-only
(`org_service_account`), no per-user connect surface, every vendor-side action
attributed to the integration user. Consequences pinned in D7.

### D4. v1 read path: sync all the matters, index every document, pull content only on selection

Settled 2026-08-18 (revised same day): the read path has three layers, and only the
third moves document content.

1. Matter sync, bulk, at connect. All the vendor's matters map into LQ.AI's
   matters—which are Projects (`web/src/routes/lq-ai/matters` lists Projects)—by
   creating a Project or linking an existing one. The link is a `pms_matter_links`
   row: `(provider, external_matter_id) ↔ project_id`, plus synced metadata
   (matter name, number, status) and sync provenance (who, when). This bulk
   mapping happens once; there is no ongoing full re-sync.
2. A document index per linked matter. `pms_document_index` holds metadata only:
   names, folders, modified dates, a `version_marker`, and a nullable
   `pulled_file_id`. The index refreshes as often as the vendor allows—webhook
   ingress where offered (Clio publishes Documents/Matters created/updated/deleted
   events with signed payloads; Filevine publishes `document.uploaded` and
   friends), polling where not. The inbound webhook receiver is a genuinely new
   surface for this codebase (everything existing is egress): a public api
   endpoint that verifies the vendor signature and updates the index, nothing
   else—no vendor calls, no secrets—isolated in its own security-reviewed PR.
3. Pull on selection. When a user selects a document from the index, the content
   pulls through the normal path: `File` → ingestion → `Document` with
   `normalized_content` and character offsets, exactly like an upload, so
   citations verify through the existing KB cascade with zero new verification
   machinery. (The ADR 0021 D3 refinement's in-memory-target path is not used
   here: that path avoids persisting ephemeral authority, and a pulled matter file
   is the opposite—persistent work product the user wants in the Project. The
   NOT-NULL `source_file_id` "collision" that forced the refinement is, for
   pulls, just correct behavior.) The `version_marker` gives dedupe and re-pull:
   an unchanged document is a no-op with an "already current" surface; a changed
   one pulls as a new version through the existing file lifecycle.

Nobody bulk-loads a 40,000-document repository they will never read; nobody waits
on a sync to analyze the one pleading they care about.

One practice reality, pinned now: the pipeline has no OCR (DE-320;
`was_ocrd=False` unconditionally), and PMS repositories are full of scanned
pleadings, stamped orders, and faxed records. A pull whose ingestion yields no
extractable text is marked "no extractable text—not citable" at pull time, never
discovered downstream as a silent citation failure.

Scoping rules: bulk sync and matter linking are admin or project-owner acts; the
document index and pull are available to members of the linked Project; a synced
Project carries the existing `privileged` / `minimum_inference_tier` controls,
surfaced at sync time with a recommendation. The matter link doubles as the
addressing layer for D5: anything generated in a linked Project pushes to the
right PMS matter automatically—no target-picking at push time, no mis-filed work
product.

### D5. Write path: document push and note creation, per-action confirmation, provenance stamped

- Surface: `push_document` and `create_note`, addressed through the D4 matter link.
  Explicitly excluded from v1: time entries, billing, tasks, contacts, and
  calendar/deadline writes (deadline writes are malpractice-adjacent and deserve
  their own design cycle).
- Confirmation: every push renders an explicit confirmation naming the target
  matter, filename, and destination folder before execution. No batch writes.
- Provenance is a separate requirement from confirmation. The gate answers "did a
  human approve this"; provenance answers "what is this, six months later, sitting
  in the matter folder looking like attorney work product." Every pushed document
  carries a filename convention marking AI-assisted origin, plus a companion
  activity note on the matter recording that it was generated with LQ.AI
  assistance, the routed model tier, the acting LQ.AI user, and the session/chat id.
  Clio and Filevine expose note endpoints; where a vendor offers none, provenance
  rides in metadata/filename and the gap is documented.
- Never autonomous. Write-capable specs are marked `destructive` +
  `requires_confirmation`; per ADR 0015 D4 they are excluded from autonomous grants
  categorically, and per D2 they are not model-callable in chat either.

### D6. Index freshness: webhooks where offered, polling everywhere

Settled 2026-08-18: webhooks are in scope, because they are how the document index
(D4 layer 2) stays honest without hammering vendor rate limits. Clio's webhook API
covers the Documents and Matters models (created/updated/deleted, signed payloads,
exponential-backoff retries); Filevine's covers `document.uploaded` plus
project/note/task/deadline events with per-subscription signing keys. The receiver
verifies the signature, updates `pms_document_index` / `pms_matter_links`, and
does nothing else. Polling (through the gateway, rate-limit-respecting) is the
fallback for deployments without a publicly reachable callback URL—which also
makes the hosting guide load-bearing for freshness, not just for OAuth. Conflict
resolution on divergent edits stays out of scope; the index is a mirror of the
vendor's list, never an authority.

### D7. Confidentiality posture

- Egress tier: 2 (settled 2026-08-18; operator-overridable). The destination is
  the client's own contractually-bound system of record, not a public API—public
  authority sources sit at 4. However, the api-side per-session ceiling machinery
  is passed `None` everywhere in v1; the gateway-side declared tier and audit row
  still apply, and D2 keeps PMS calls out of model-driven paths regardless.
- Anonymization: `anonymize_outbound: false`, as the explicit audited
  per-provider override ADR 0014 D5 provides. Outbound arguments are identifiers
  and queries against the system that already holds the client's data;
  pseudonymizing them breaks lookups and protects nothing. Inbound pulled content
  (D4 layer 3) is ordinary KB content: the M2 layer applies at inference egress
  and the M2-1 verbatim-retrieval precedent is unchanged.
- Filevine org-wide visibility: the service account sees every matter in the
  org, so LQ.AI must not become a privilege-escalation path. The org-wide matter
  list is admin/project-owner-only; ordinary users work only within Projects
  already linked. Vendor-side audit trails will attribute everything to the
  integration user—LQ.AI's `audit_action` rows carry the real acting user, and
  Filevine push-provenance notes name that user in the note body. Documented
  prominently as an operator trade-off.

### D8. Off by default; honest state; clean uninstall

No PMS type ships enabled; unconfigured means unavailable-with-reason. The master
admin toggle gates UI visibility only—the enforcement is, as everywhere, the gateway
config. Each adapter lands in `HONEST-STATE.md` with a verification path; MyCase
ships explicitly labeled unverified, with the row naming what an operator with an
Advanced tenant must run to promote it. Disabling a provider makes it unavailable
immediately; per-user tokens are retained encrypted until an explicit "disconnect
all users" (with a surfaced count), and removing a vendor's registration
cascade-deletes its `pms_oauth_tokens` rows. Synced matter links and the document
index deactivate but are not destroyed (they are provenance); pulled documents are
the firm's work product and remain, governed by the existing ADR 0005 lifecycle.
Switching vendors is disconnect-all plus fresh setup, with a warning—a migration
flow is a DE, not a v1 feature.

## What still needs an outside answer

1. Committee acceptance. The five forks are settled on the proposer's side; the
   project has not seen any of it. Per GOVERNANCE ("How decisions are made" #1,
   agreed at the 2026-07-19 committee call), architectural questions are
   ADR-first: this document goes up as its own PR for community comment, and
   implementation PRs wait for it. The Phase-0 issue presents the settled forks
   as proposed decisions the committee can override—the DE-206/DE-040
   reconciliation especially. Scope decisions land at the weekly Sunday call or
   async in the tracking issue, with 7-day ratification on minutes.
2. Clio redirect-URI policy for private apps. The callback is the deployment's
   api URL as reached by the attorney's browser, so a LAN or Tailscale hostname
   suffices IF Clio's registration accepts it. The docs confirm redirect URIs are
   an app-settings allow-list but never say whether `localhost` registers
   (researched 2026-08-18); ten minutes in a free developer account settles it.
   This decides the hosting guide's default path.
3. Vendor-hosted MCP servers. Researched 2026-08-18: third-party SELF-HOSTED
   servers exist for all three vendors; vendor-hosted servers exist for none, so
   alternative B stays rejected. If a vendor ships a hosted server later, B
   reopens for that vendor.
4. Tracked as DE-388 in PRD §9 (settled 2026-08-18; new DE, not a broadened
   DE-206). Numbering verified against open PRs 2026-08-18: ADR 0026 is claimed
   by BOTH PR 528 and PR 418 (a collision those PRs will sort out between
   themselves), ADR 0027 by PR 430, and DE-387 by PR 528—so this one is
   0028/DE-388.
   Re-check at PR-open time; these numbers move with the merge queue.

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
- Mini-PRD: [`docs/proposals/practice-management-integration.md`](../proposals/practice-management-integration.md).
- Precedent code: `api/app/research/registry.py` + `service.py`,
  `api/app/api/mcp_oauth.py` + `api/app/models/mcp_oauth.py`,
  `gateway/app/providers/tool/` (`egress.py`, `mcp.py`, `oauth_passthrough.py`),
  `api/app/api/admin.py` (tool-providers proxy),
  `web/src/routes/lq-ai/admin/research-sources/+page.svelte`.
