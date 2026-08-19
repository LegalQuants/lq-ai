# Practice Management System Integration: scope, work breakdown, and Phase-0 issue

> Status: Proposal, proposer-settled 2026-08-18 (revised same day after maintainer-side
> review of the first draft). Companion to
> [ADR 0028 (draft)](../adr/0028-practice-management-integration.md). Maintainer
> acceptance is still the gate; the Phase-0 issue is filed as
> [issue 529](https://github.com/legalquants/lq-ai/issues/529). Derived
> from an external scope brief, verified against the repository at `main`
> (2026-08-18)—where the brief and the code disagreed, the code won.

---

## 1. Where the brief's assumptions diverged from the code

The brief was substantially accurate. The verified deltas, most consequential first:

1. The project's published integration posture is "via MCP"—the brief missed this.
   PRD §9 has no PMS DE, but
   [DE-206](../PRD.md#de-206--document-store-connectors-via-mcp) commits
   document-store connectors via MCP, and
   [DE-040](../PRD.md#de-040--direct-clm-integration) says "the MCP path (M5+) is
   the integration story" for CLMs. To be clear about where we landed: we are NOT
   doing MCPs; we are doing fully connected, first-class adapters. Third-party
   self-hosted MCP servers do exist for all three vendors (§7), but a self-hosted
   bridge moves the real vendor egress outside the gateway's audited boundary, which
   is the exact shape ADR 0014 rejected. Only a vendor-HOSTED MCP server would
   change the calculus, and none exists.
2. Per-user OAuth is more finished than the brief assumed, with two gaps. In plain
   terms: when an attorney clicks "Connect," LQ.AI already knows how to walk them
   through a vendor login and store the resulting token encrypted—that machinery
   shipped with the MCP work. The gaps: (a) the shipped flow assumes the app itself
   never has to prove its identity (it uses one-time codes instead—"public client"
   PKCE), while Clio and MyCase require the app to present its own secret when it
   swaps the login code for a token ("confidential client"); and (b) the shipped
   flow asks the server where to send logins at runtime (RFC 9728 discovery), while
   PMS vendors just publish fixed URLs. Both fixes live in the gateway, and both
   are small: inject the secret at the gateway so it never touches `api/`, and
   carry the fixed URLs as per-region constants.
3. A runtime admin surface for turning on a source already exists, and it is the
   pattern to copy. Today an admin can enable a research source and set its key
   from the app, at runtime, no YAML edit (`POST /api/v1/admin/tool-providers`).
   The part worth understanding: that endpoint deliberately REFUSES any attempt to
   set the URL the gateway will call. The URLs are hard-coded server-side per
   vendor, so no one—not even an admin—can point the gateway at a lookalike host
   and exfiltrate data. The PMS settings surface copies this exactly: admins supply
   credentials and a region; the gateway owns every URL. There is also an existing
   admin page to mirror (`web/src/routes/lq-ai/admin/research-sources/+page.svelte`).
4. UI-driven gateway calls are an established, lighter pattern than the brief's
   tool-loop framing, and the plumbing is straightforward. The flow, plumbed out:
   the user clicks → an api endpoint checks project membership → `pms/service.py`
   calls `gateway.call_tool` (the same shape `research/service.py` uses) → the
   gateway attaches the user's decrypted token, checks the host allowlist, makes
   the vendor call, and writes a `tool_egress_log` row → the api writes an
   `audit_action` row recording who clicked. Every hop already exists for research
   sources; PMS reuses the lane. The model-driven path (`governed_tool_invocation`,
   `ToolIntent`s, confirmation gates) stays untouched because no model ever
   initiates a PMS call in v1.
5. The read path, corrected (2026-08-18): connect ALL the matters, index every
   document, pull content only on selection. On connect, a bulk sync maps the
   vendor's matters to LQ.AI matters (which are Projects—`/lq-ai/matters` lists
   Projects) and pulls a document LIST for each: names, folders, modified dates.
   No document content moves yet. The list stays as fresh as the vendor allows
   (webhooks where offered, polling where not—§5.7). When a user selects a
   document from the list, THEN the content pulls in through the normal ingestion
   pipeline, lands as a real `File` in the Project, and becomes citable through
   the existing verification cascade. Nobody bulk-loads a 40,000-document
   repository they will never read; nobody waits on a sync to analyze the one
   pleading they care about.
6. The OCR gap is exactly as briefed. DE-320 confirms `was_ocrd=False`
   unconditionally, and the citation cascade's OCR-confusion handling is already
   gated on the flag. A selected document whose ingestion yields no extractable
   text (scanned pleadings, stamped orders, faxed records) gets marked "no
   extractable text—not citable" at pull time, never discovered downstream as a
   silent citation failure.
7. Tier semantics, plainly: LOWER numbers are MORE trusted. The egress tier is a
   risk score for where the data is headed, 0 through 5; a call is refused when
   the destination's score exceeds what the caller is cleared to send. Public
   legal APIs (CourtListener, GovInfo) score 4; an unknown provider fails safe to
   5, the most restricted. So the 2 we assigned the PMS providers is near the
   trusted end—third rung from the top—which is right: the destination is the
   client's own contractually-bound system of record. Not the second least
   secure; close to the second MOST.
8. Destructive tools are already categorically excluded from the autonomous layer
   (ADR 0015 D4). The only open question was chat vs UI, and UI won.
9. On "80% coverage": test coverage is the percentage of the code's lines that
   the automated test suite actually executes. CONTRIBUTING sets 80% as the
   target for `api/` and `gateway/`; the point of the divergence note is that CI
   does not currently enforce that number, so our write-up should say "tested to
   the project's 80% target" rather than implying a CI gate that does not exist.

## 2. The settled decisions (2026-08-18, revised same day)

1. Registry, not MCP. First-class `tool_providers` types per vendor, sibling
   backend registry. The egress-bridge argument carried it, and the existence of
   third-party self-hosted MCP servers (§7) does not change it—those bridges are
   the problem, not the answer.
2. Sibling token table. `pms_oauth_tokens`—same key shape and encryptor as
   `mcp_oauth_tokens`, its own cascade semantics on vendor removal.
3. UI-driven v1 with the three-layer read path: bulk matter sync on connect (all
   matters, mapped to Projects via `pms_matter_links`); a continuously-refreshed
   document index per matter (`pms_document_index`: names, folders, modified
   dates—metadata only); content pull on user selection, through the normal
   ingestion pipeline. The matter link doubles as the addressing layer for
   writes: anything generated in a linked Project pushes to the right PMS matter
   automatically, no target-picking at push time.
4. Egress tier 2 for PMS providers, operator-overridable; the sync UI surfaces
   the Project's existing `privileged` / `minimum_inference_tier` controls with a
   recommendation rather than inventing auto-floor policy.
5. New DE: DE-388 (not a broadened DE-206).

Answers to the brief's remaining open questions—anonymization
(`anonymize_outbound: false`, the audited ADR 0014 D5 override), ledger semantics
(a pull is egress-audited provenance, not a ledger event; documents enter the
ledger when a turn actually cites them), the Filevine org-visibility mitigation
(org-wide operations are admin/owner-gated; users work inside linked Projects),
and the uninstall story (tokens cascade-delete with the vendor registration;
matter links deactivate but survive as provenance)—are pinned in ADR 0028 D4-D8.

## 3. File-by-file implementation plan

Complexity: S ≤ ~150 LOC, M ~150-500, L > 500, tests included. Everything under
`gateway/` and the credential surfaces routes to security review via CODEOWNERS;
gateway diffs stay isolated in their own PRs on purpose.

### PR-1—Registry + domain models + ADR (no vendor code)

| File | Change | Size |
|---|---|---|
| `docs/adr/0028-practice-management-integration.md` | Draft → maintainer-revised | n/a |
| `api/app/pms/` (new package), `registry.py` | `PMSSpec` (type, capabilities, auth_model, adapter) + `resolve_available_pms()` join, mirroring `research/registry.py` | M |
| `api/app/pms/models.py`, `api/app/schemas/pms.py` | Domain models (`Matter`, `PMSDocumentRef`, `NoteRef`, capability enum, `vendor_native` passthrough) + response schemas (never secrets) | M |
| `api/tests/test_pms_registry.py` | Join semantics, unavailable-with-reason, capability reporting | M |

### PR-2—Gateway: Clio adapter + confidential-client OAuth (security-reviewed)

| File | Change | Size |
|---|---|---|
| `gateway/app/config.py` | `oauth` sub-block on `tool_providers` (client id/secret via existing Fernet paths); `region` enum → gateway-owned base URLs | M |
| `gateway/app/providers/tool/clio.py` | `list_matters` / `list_documents` / `get_document` ToolSpecs (`read_only=True`); rate-limit headers + `Retry-After`; region routing | L |
| `gateway/app/providers/tool/oauth_passthrough.py` | Static-endpoint flow + client-secret injection at token exchange | M |
| `gateway/tests/` | Recorded fixtures; egress-guard conformance; secret never in errors or logs | L |

### PR-3—Backend: connect + matter sync + document index + on-demand pull

| File | Change | Size |
|---|---|---|
| `api/app/pms/oauth.py` | Vendor OAuth flow on the MCP state/encryptor skeleton; static endpoints | M |
| `api/app/models/pms.py` + migration | `pms_oauth_tokens`; `pms_matter_links` (provider + external matter ↔ `project_id`, metadata, sync provenance); `pms_document_index` (per-matter document metadata + `version_marker` + nullable `pulled_file_id`) | M |
| `api/app/pms/service.py` | Bulk matter sync; index refresh (poll-based here; webhooks in PR-6); on-demand pull → existing file-create + ingestion, dedupe via `version_marker`, "no extractable text" surfacing | L |
| `api/app/api/pms.py`, `pms_oauth.py` | REST: registry status, sync, matter/document listing, pull; authorize/callback/status/disconnect | M |
| `api/tests/` + `IMPLEMENTED_ROUTES` / `EXPECTED_PATHS` + path-count bumps | Handler + integration + OpenAPI conformance; the collision guards per CLAUDE.md | L |
| `docs/api/backend-openapi.yaml`, `docs/db-schema.md` | New endpoints + tables | S |

### PR-4—Admin surface + settings/browse UI

| File | Change | Size |
|---|---|---|
| `gateway/app/main.py` (admin/v1) | Runtime PMS registration: constrained fields (type, creds, region), hot-apply | M |
| `api/app/api/admin_pms.py` | Proxy mirroring the tool-providers proxy (`extra="forbid"`); typed 400 on missing master key | S |
| `web/src/routes/lq-ai/admin/pms/+page.svelte` (+ components) | Master toggle → vendor selector → single-vendor config: write-only masked creds, redirect-URI display + copy, region, Test Connection, status | L |
| `web/.../PMSConnectCard.svelte` + settings route | Per-user connect/disconnect (Clio); `return_url` flow reuse | M |
| `web/.../MatterDocuments*.svelte` | Per-matter document browser: the index list, freshness stamp, pull-on-select, pulled/not-pulled state | M |
| Cypress + axe specs | Settings, connect, browse, and pull flows; WCAG 2.1 AA parity | M |

### PR-5—Clio write path

| File | Change | Size |
|---|---|---|
| `gateway/app/providers/tool/clio.py` | `push_document` / `create_note` ToolSpecs (`destructive`, `requires_confirmation`) | M |
| `api/app/pms/service.py`, `api/app/api/pms.py` | Push endpoint: auto-target via `pms_matter_links`; explicit confirm payload (matter, filename, folder); provenance note (model tier, acting user, session id); audit | M |
| `web/.../SendToPMS*.svelte` | Confirmation dialog naming matter, filename, destination | M |
| Tests | Push + provenance-note fixtures; confirm-required enforcement | M |

### PR-6—Webhook ingress for index freshness (Clio)

Clio webhooks cover the Documents and Matters models with created/updated/deleted
events, signed payloads, and exponential-backoff retries (§7). This PR adds the
inbound receiver: a public api endpoint that verifies the signature, updates
`pms_document_index` / `pms_matter_links`, and nothing else—no vendor calls, no
secrets. Inbound webhooks are a NEW surface for this codebase (everything so far
is egress), so it gets its own small, security-reviewed PR, and polling from PR-3
remains the fallback for deployments without a public callback URL. M.

### PR-7—Filevine adapter

"Proves the abstraction" means this: with one vendor built, the adapter protocol
is untested—it might be Clio-shaped rather than PMS-shaped. Filevine is the
stress test, because it breaks Clio's assumptions on purpose. Service-account
auth instead of per-user OAuth; a PAT-to-bearer token exchange at
`identity.filevine.com` instead of authorization-code; `x-fv-orgId` /
`x-fv-userId` headers on every call; upload but no DocGen. If the protocol
survives Filevine without hacks, a fourth vendor is cheap.

The Filevine build-out inventory (endpoints verified against
`developer.filevine.io`, §7):

| Piece | Filevine surface | Size |
|---|---|---|
| Auth | PAT → `identity.filevine.com/connect/token` exchange; org/user headers; space-delimited scopes | M |
| Matter sync | Projects list endpoints → `pms_matter_links` | S |
| Document index | Project documents/folders listing → `pms_document_index` | M |
| On-demand pull | Document fetch/download flow | M |
| Push | Upload-URL request → byte POST → project/folder attach | M |
| Notes | `note.created`-compatible note post (provenance notes) | S |
| Webhooks | Subscription + Filevine Identity Signature verification (`document.uploaded`, `project.created/updated`) | M |
| Registry + tests | `PMSSpec` (org_service_account, no per-user connect), recorded fixtures | M |

### PR-8—MyCase (documentation-driven), docs, HONEST-STATE

`mycase.py` + registry entry built against the Stoplight docs (M);
`docs/practice-management.md` operator guide with the callback-hosting section,
cheapest option first (M); HONEST-STATE rows per adapter including the explicit
MyCase-unverified row and its promotion path (S); PRD §9 DE-388 + README (S).

## 4. Speed: the compressed plan

First, a correction on the estimates themselves (2026-08-18): the earlier 31-44
focused days were manual-coding numbers, and that is not how this gets built. The
build is Claude Code-driven—agent-written code and tests, human-reviewed before
anything ships under a DCO sign-off. On that basis a PR like PR-3 is a day or two
of supervised agent work, not four to six of hand-writing; the honest recalibrated
build effort is 10-15 supervised days serial. What AI does NOT compress: maintainer
and security review latency on an external repo, vendor account acquisition (Clio
trial, Filevine tenant, the MyCase support ticket), OAuth debugging against live
sandboxes (the loop is bounded by the vendor's round trips, not typing speed), and
actually reading every line before it goes out under my name. The bottleneck was
never build time; it is review latency. How we compress what remains:

1. Open the Phase-0 intake first: two artifacts, per GOVERNANCE. First, the
   tracking issue—filed as issue 529 on 2026-08-18. GitHub Discussions are not
   enabled on the repo (verified via the repo API), so the issue doubles as the
   "discussion first" boundary thread GOVERNANCE asks for on anything
   architectural. The project's own stated pattern is "asynchronously in a
   tracking issue." It also carries the claim once DE-388 exists. Second, ADR
   0028 opened as its OWN PR for community
   comment (the ADR-first rule from the 2026-07-19 committee call—implementation
   PRs wait for their anchor ADR). Scope decisions land at the weekly Sunday
   committee call (2pm GMT) or async, with 7-day ratification, so filing early
   buys a full cycle. Every day before the committee responds is a free day of
   parallel prep that costs nothing if the answer changes details.
2. Stack the PRs; don't wait for merges. PR-1 through PR-5 develop in parallel
   worktrees against recorded fixtures; each submits as soon as its parent is
   review-ready, not merged. Reviews overlap instead of queueing.
3. Parallelize the build itself. Registry (PR-1), gateway adapter (PR-2), and the
   UI (PR-4) share almost no files; three parallel agent worktrees with the
   protocol pinned in PR-1's first commit take the 10-15 supervised days to
   roughly 5-8 calendar days of building.
4. Get the Clio developer account on day one (free trial). Recorded fixtures come
   from a real sandbox early, so nothing gets rebuilt when reality disagrees with
   the docs.
5. Sequence MyCase last and let it slip. It is documentation-driven anyway; it
   can land well after the demo loop is live without weakening anything.
6. Ask the maintainer for a review-bandwidth commitment in the Phase-0 issue.
   Naming the PR count and sizes up front ("eight PRs, gateway diffs isolated and
   small") is the single best thing we can do for review speed.

Compressed target: about a week of building, 3-5 weeks end-to-end with review
latency dominating—versus the 2.5-4 calendar months the manual-serial numbers
implied. The demo loop (connect → sync → browse → pull → generate → push with
provenance) is intact either way.

## 5. Scope decisions (vs the original brief)

1. Document pull is IN v1—on-demand, per selection. What stays out is bulk
   content loading: the index knows about every document; content crosses only
   when a user selects one.
2. No model-driven PMS access. No `ToolIntent`s, no chat-loop changes, no gate
   plumbing; a materially smaller security review.
3. No `list_contacts` / `list_tasks` / `list_deadlines` in the adapter protocol.
   Their consumers are out of scope, and carrying dead protocol surface violates
   the honest-state posture. The capability enum grows when a consumer exists.
4. No scope-selection UI—fixed minimal per-vendor scope sets, documented.
5. No vendor-switch flow—switching is disconnect-all plus fresh setup, with a
   warning. A migration flow is a DE.
6. Hosting guide per the brief's own §10 rework: cheapest first
   (localhost-if-permitted → the existing `deploy/` Caddy/Tailscale recipe → one
   vendor-neutral VM section). MyCase's support-gated redirect URI stated plainly
   up front: the callback hostname must be stable BEFORE requesting credentials,
   and every change costs a support ticket.
7. Webhooks are IN scope (revised 2026-08-18): they are how the document index
   stays fresh where the vendor offers them (Clio: Documents/Matters events;
   Filevine: `document.uploaded` and friends), with polling as the fallback.
   Bulk sync happens ONCE, at connect—matter mapping and initial document
   lists—and never as an ongoing full re-sync. Still out: conflict resolution on
   divergent edits, and any bulk CONTENT loading.

## 6. The Phase-0 issue

Filed as [issue 529](https://github.com/legalquants/lq-ai/issues/529) on
2026-08-18. The issue carries the use case, the manual round-trip pain this
replaces, the proposed approach, and the claim. It also carries the alternatives
argument: why first-class provider types beat MCP bridges for
client-confidential egress. This
document and [ADR 0028](../adr/0028-practice-management-integration.md) are the
issue's supporting record; the ADR travels as its own PR per the ADR-first rule.

## 7. External verification: what the web says, and what remains open

Researched 2026-08-18. Sources at the bottom of this section.

Clio redirect URIs—PARTIALLY resolved. Clio's docs confirm redirect URIs are
an explicit allow-list set in the app's settings, and that apps without a web
server may use `https://app.clio.com/oauth/approval`, a special URI that embeds
the authorization code in the page title for manual copy. That special URI does
not fit an automated server flow, and the docs never say whether a plain
`http://localhost` URI is registerable. Open: try registering
`http://localhost:<port>/api/v1/pms/oauth/clio/callback` in a free developer
account, and if it rejects, ask api@clio.com. Ten minutes of clicking settles
what the documentation will not; the answer decides the hosting guide's default
path (PR-8).

MCP servers—resolved, and it mattered for decision 1. They exist for all
three: Oktopeak's `clio-mcp` (26 tools, on the Anthropic MCP Registry, MIT) and
`filevine-mcp` (15 tools, same registry), and RosenAdvertising's `mycase-mcp`.
Every one is a self-hosted local bridge; none is vendor-hosted. The registry
decision was conditioned on the egress argument, not on nonexistence, so it
stands—and the existence of these servers is disclosed in issue 529 so the
committee sees it before agreeing.

Clio webhooks—resolved, in our favor. Webhooks cover the Documents and
Matters models with created/updated/deleted events, signed payloads, and
exponential-backoff retry; a 410 response auto-disables a subscription. That is
exactly the document-index freshness mechanism §5.7 needs. Caveat: webhooks
require a callback URL Clio can reach, which makes the hosting guide
load-bearing; polling stays the fallback.

Filevine—largely resolved. The auth chain is confirmed (PAT →
`identity.filevine.com/connect/token` → bearer + `x-fv-orgId` / `x-fv-userId` on
every call). Webhooks are confirmed with per-subscription signing keys and a
`document.uploaded` event among project/note/task/deadline events. Document
upload and fetch flows are documented (upload is real; DocGen is not). Open:
confirm in a real Filevine tenant that a customer org can self-generate the
client id/secret for an internal integration (the docs say yes; a live tenant
closes it), and provision an "Adhoc" service account to capture the exact steps
for the operator guide.

MyCase—resolved, and it is the operational headache expected. The API is
Advanced-tier only; credentials are issued by support after the use case is
presented; and the redirect URI can only be set or CHANGED by MyCase support.
Token lifetimes (~24h access / ~2-week refresh, per vendor reports) still want
confirmation at onboarding. Open: verification requires an Advanced-tier tenant
(roughly $109/user/month) plus a support ticket, with the permanent callback
hostname decided BEFORE the ticket. Until then MyCase ships
documentation-driven and honestly labeled unverified, which the project's
culture explicitly supports.

Sources: [Clio redirect URIs](https://developers.support.clio.com/hc/en-us/articles/1260800469910-How-to-Set-Redirect-URIs),
[Clio authorization docs](https://docs.developers.clio.com/api-docs/clio-manage/authorization/),
[Clio private apps](https://docs.developers.clio.com/handbook/getting-started/building-private-apps/),
[Clio webhooks guide](https://rollout.com/integration-guides/clio/quick-guide-to-implementing-webhooks-in-clio),
[oktopeak/clio-mcp](https://github.com/oktopeak/clio-mcp),
[oktopeak/filevine-mcp](https://github.com/oktopeak/filevine-mcp),
[RosenAdvertising/mycase-mcp](https://github.com/RosenAdvertising/mycase-mcp),
[Filevine API v2](https://developer.filevine.io/docs/v2-us/a917e89715b00-filevine-api-gateway),
[Filevine webhook security](https://developer.filevine.io/docs/v2-ca/branches/main/15de82e461c3e-webhook-security),
[Filevine webhook subscriptions](https://support.filevine.com/hc/en-us/articles/13644331859611-Webhooks-Subscriptions),
[MyCase getting started](https://mycaseapi.stoplight.io/docs/mycase-api-documentation/k5xpc4jyhkom7-getting-started),
[MyCase Open API help](https://supportcenter.mycase.com/en/articles/9370198-open-api).
