# Practice Management System Integration: product specification (mini-PRD)

> Status: v2, revised 2026-08-20 after first maintainer review
> ([issue 529](https://github.com/legalquants/lq-ai/issues/529),
> [PR 530](https://github.com/legalquants/lq-ai/pull/530)). Per that review, the
> split is now clean: [ADR 0028](../adr/0028-practice-management-integration.md)
> carries the vendor-agnostic ARCHITECTURE; this document carries the specific
> PRODUCT—what ships, for whom, in what order, verified how. Committee
> acceptance of the ADR gates all implementation.

---

## 1. The product

A firm connects the practice management system it already runs, and LQ.AI works
against live matter data instead of stray copies.

- An admin flips one toggle, picks the firm's PMS from the supported list, and
  registers it once: credentials and a region, nothing else. URLs stay
  gateway-owned; there is nothing to misconfigure into an exfiltration path.
- Each attorney clicks "Connect your account" and does a normal vendor login
  (where the vendor's model is per-user; org-service-account vendors skip this).
- On connect, the vendor's matters sync into LQ.AI matters—create a Project or
  link an existing one—and every linked matter gets a document INDEX: names,
  folders, modified dates. No content moves.
- The index stays as fresh as the vendor allows: webhooks where offered,
  polling where not.
- When a user selects a document from the index, THEN it pulls in through the
  existing ingestion pipeline, lands as a real File in the Project, and cites
  like any uploaded file. Image-only scans get flagged "no extractable
  text—not citable" at pull time (DE-320) instead of failing silently later.
- Anything generated in a linked matter pushes back to the right PMS matter
  automatically—no target-picking—behind an explicit confirmation naming the
  matter, filename, and destination folder, stamped with AI provenance: a
  filename convention plus an activity note carrying the model tier, the
  acting user, and the session id.

Nobody bulk-loads a 40,000-document repository they will never read; nobody
waits on a sync to analyze the one pleading they care about; and nothing the
model generates can land in a matter file unmarked.

## 2. Who this serves, and why it matters

At the majority of firms that run on a PMS, the team does not have the time or
money to move an entire operation onto a new platform—and small firms are the
great majority of firms. Today the only bridge is a four-leg manual round trip
(download from the PMS, upload to LQ.AI, download the work product, re-file it
by hand). Every leg loses provenance. The practical result: documents do
not make the trip, and the AI platform gets used on whatever is lying around
rather than the live matter file. A native connector that enforces LQ.AI's
security and audit posture flips the cost of adoption—the firm keeps its
system of record and gains LQ.AI against live matter data. No choosing between
the two.

## 3. Scope

IN scope for v1:

1. The PMS registry, adapter protocol, capability declaration, and auth-model
   enum (ADR 0028 D1/D3).
2. Deployment registration (admin, runtime, constrained fields) and per-user
   connect/disconnect where the vendor supports it.
3. Bulk matter sync at connect; `pms_matter_links` addressing.
4. The per-matter document index with webhook-plus-polling freshness,
   including the inbound webhook receiver (its own security-reviewed PR).
5. Pull-on-selection through the existing ingestion pipeline, with dedupe,
   re-pull on version change, and the no-extractable-text flag.
6. Document push and note creation, per-action confirmed, provenance-stamped.
7. Admin settings UI, per-user connect UI, per-matter document browser—WCAG
   2.1 AA like every shipped surface.
8. Operator documentation including the callback-hosting guide, cheapest
   option first.

OUT of scope for v1 (each deliberate, most recorded in ADR 0028):

1. Model-driven PMS access—no new `ToolIntent`s, no chat-tool exposure.
2. Bulk CONTENT loading; the index knows everything, content moves on
   selection only.
3. Time entries, billing, tasks, contacts, calendar/deadline writes.
4. Contacts/tasks/deadlines in the adapter protocol at all (the capability
   enum grows when a consumer exists).
5. Scope-selection UI; fixed minimal per-vendor scope sets, documented.
6. Vendor-switch migration; switching is disconnect-all plus fresh setup.
7. Conflict resolution on divergent edits; the index mirrors, never
   arbitrates.
8. Ongoing full re-sync; bulk sync happens once, at connect.

## 4. Reference adapters: selection criteria, then vendors

The project prefers no vendor (ADR 0028 D2), and this section is sequencing,
not endorsement. The initial adapters were chosen against four checkable
criteria: (a) a documented, versioned public API; (b) credentials a firm can
obtain for its own account; (c) market coverage, so the connector actually
opens doors for small firms; and (d) auth-shape DIVERSITY. The second and
third adapters exist partly to prove the abstraction is PMS-shaped rather
than shaped like the first vendor. Any vendor meeting (a) and (b) can be
contributed under ADR 0028 without a new ADR.

Three adapters ship first, at three verification maturities:

| | Clio | Filevine | MyCase |
|---|---|---|---|
| Market footprint | The most widely adopted PMS: Clio reports 400,000+ legal professionals across 130+ countries | Roughly 6,000 law firms and legal teams as of late 2025, nearly doubled from ~3,400 in mid-2024; dominant in plaintiff-side injury practice, where small firms adopt AI fastest | 19,000+ firms, 65,000+ legal professionals, primarily US |
| Auth model | `per_user_oauth` (confidential authorization-code; its own OAuth idioms) | `org_service_account` (PAT → identity-endpoint bearer exchange; org/user headers on every call) | `per_user_oauth` (confidential; credentials issued by support) |
| Credential access | Self-serve developer account, free trial | Customer orgs self-generate for internal integrations | Advanced tier (~$109/user/month) plus a support ticket; redirect URI settable only by support |
| Webhooks | Documents/Matters models, signed, created/updated/deleted | `document.uploaded` plus project/note/task events, per-subscription signing keys | Not relied on in v1 |
| Verification maturity | Thoroughly tested end to end against a developer-tools sandbox; the demo vendor | Pseudo-tested: recorded fixtures from documented shapes, informed by prior hands-on work with Filevine's auth flow | Built to documentation, shipped labeled UNVERIFIED in HONEST-STATE with its promotion path named |
| Notable caveats | Regional portals; verify localhost redirect-URI policy (§7) | Space-delimited scopes; upload but no DocGen; all vendor-side actions attribute to the integration user | Support-gated redirect URI means the callback hostname must be stable BEFORE requesting credentials |

Priority order is Clio → Filevine → MyCase, and the reasons are the criteria:
Clio has the widest coverage and the most accessible developer story; Filevine
breaks Clio's auth assumptions on purpose, which is what proves the protocol;
MyCase adds real coverage but cannot be verified without a paid tenant, so it
ships honestly labeled rather than falsely implied. All three auth flows
differ from one another—which is exactly why ADR 0028 D3 enumerates auth
models instead of assuming one.

## 5. Delivery plan and acceptance criteria

Eight PRs, gateway diffs isolated and small for security review. Build is
Claude Code-driven: agent-written code and tests, human-reviewed before
anything ships under a DCO sign-off. Figure 10-15 supervised days serial,
roughly a week across three parallel worktrees; end-to-end 3-5 weeks, review
latency dominating.

| PR | Contents | Done when |
|---|---|---|
| 1 | Backend registry, `PMSSpec`, domain models, capability + auth-model enums | Registry join reports available/unavailable-with-reason correctly under test; no vendor code |
| 2 | Gateway: first vendor adapter (read ops) + confidential-client OAuth + region enum (security-reviewed) | Recorded-fixture suite green; egress-guard conformance; no secret in any error or log |
| 3 | Backend: per-user connect, bulk matter sync, document index, pull-on-selection into ingestion | Connect → sync → browse → pull works against the sandbox; OpenAPI conformance + collision guards green |
| 4 | Admin settings UI, per-user connect, per-matter document browser | Cypress + axe clean; masked write-only credentials; Test Connection works |
| 5 | Write path: push + provenance note, confirmation dialog | Push lands in the sandbox matter with provenance note; confirm-required enforced under test |
| 6 | Inbound webhook receiver (security-reviewed) | Signature verification under test; index updates on events; polling fallback intact |
| 7 | Second adapter (org-service-account vendor) | Same fixture bar; protocol revisions the asymmetry forces are folded back into PR 1 shapes |
| 8 | Third adapter (documentation-driven) + operator guide + HONEST-STATE rows + PRD §9 entry | Docs review; the unverified row names its promotion path |

Compression levers, in order of value: file early against the Sunday committee
cadence; stack the PRs so reviews overlap instead of queueing; develop the
independent streams in parallel worktrees; get the first vendor's sandbox
account on day one so fixtures come from reality; let the third adapter slip—
it is documentation-driven anyway. Phases 1-5 alone (connect, sync, browse,
pull, generate, push with provenance, one vendor) are a complete, demoable
product if the committee wants narrower scope.

## 6. Maintainability commitments

This is the answer to "what happens when a vendor changes its API" (raised in
first review, issue 529). Four commitments, all architectural rather than
aspirational—ADR 0028 D9 pins them:

1. Each adapter pins a documented, versioned vendor API surface, asserted in
   its tests. All three initial vendors publish stable versioned APIs; auth
   flows in particular have historically outlived response-shape changes.
2. Recorded-fixture suites double as drift detectors: a vendor shape change
   fails loudly in CI, in that adapter only. The blast radius of drift is one
   adapter, by construction.
3. The HONEST-STATE row is the maintenance contract—a named verification path
   an operator can run. An adapter nobody can verify anymore degrades to
   unavailable-with-reason, never to silently wrong.
4. A vendor that ships an official hosted MCP server reopens the MCP
   alternative for that vendor, and its adapter can retire in favor of the
   vendor-maintained surface.

## 7. External verification: what the web says, and what remains open

Researched 2026-08-18; market figures re-verified 2026-08-20. Sources at the
bottom of this section.

Clio redirect URIs—PARTIALLY resolved. Clio's docs confirm redirect URIs are
an explicit allow-list set in the app's settings, and that apps without a web
server may use `https://app.clio.com/oauth/approval`, a special URI that embeds
the authorization code in the page title for manual copy. That special URI does
not fit an automated server flow, and the docs never say whether a plain
`http://localhost` URI is registerable. Open: try registering
`http://localhost:<port>/api/v1/pms/oauth/clio/callback` in a free developer
account, and if it rejects, ask api@clio.com. Ten minutes of clicking settles
what the documentation will not; the answer decides the hosting guide's default
path (PR 8).

MCP servers—resolved, and disclosed. Third-party self-hosted servers exist for
all three initial vendors: Oktopeak's `clio-mcp` (26 tools, on the Anthropic
MCP Registry, MIT) and `filevine-mcp` (15 tools, same registry), and
RosenAdvertising's `mycase-mcp`. Every one is a self-hosted local bridge; none
is vendor-hosted. The registry decision was conditioned on the egress argument,
not on nonexistence, so it stands—and the existence of these servers is
disclosed in issue 529 so the committee sees it before agreeing.

Clio webhooks—resolved, in our favor. Webhooks cover the Documents and Matters
models with created/updated/deleted events, signed payloads, and
exponential-backoff retry; a 410 response auto-disables a subscription. That is
exactly the index-freshness mechanism §3 item 4 needs. Caveat: webhooks require
a callback URL Clio can reach, which makes the hosting guide load-bearing;
polling stays the fallback.

Filevine—largely resolved. The auth chain is confirmed (PAT →
`identity.filevine.com/connect/token` → bearer + `x-fv-orgId` / `x-fv-userId`
on every call). Webhooks are confirmed with per-subscription signing keys and a
`document.uploaded` event among project/note/task/deadline events. Document
upload and fetch flows are documented (upload is real; DocGen is not). Open:
confirm in a live tenant that a customer org can self-generate the client
id/secret for an internal integration (the docs say yes), and provision an
"Adhoc" service account to capture the exact steps for the operator guide.

MyCase—resolved, and it is the operational headache expected. The API is
Advanced-tier only; credentials are issued by support after the use case is
presented; and the redirect URI can only be set or CHANGED by MyCase support.
Token lifetimes (~24h access / ~2-week refresh, per vendor reports) still want
confirmation at onboarding. Open: verification requires an Advanced-tier tenant
plus a support ticket, with the permanent callback hostname decided BEFORE the
ticket. Until then MyCase ships documentation-driven and honestly labeled
unverified, which the project's culture explicitly supports.

Market figures, sourced: Clio reports 400,000+ legal professionals across 130+
countries (its consistent 2026 claim across its site and press); MyCase reports 19,000+ firms and 65,000+ legal professionals;
Filevine serves roughly 6,000 law firms
and legal teams as of late 2025, nearly doubled from ~3,400 in mid-2024, with
its strength concentrated in plaintiff-side injury practice.

Sources: [Clio redirect URIs](https://developers.support.clio.com/hc/en-us/articles/1260800469910-How-to-Set-Redirect-URIs),
[Clio authorization docs](https://docs.developers.clio.com/api-docs/clio-manage/authorization/),
[Clio private apps](https://docs.developers.clio.com/handbook/getting-started/building-private-apps/),
[Clio webhooks guide](https://rollout.com/integration-guides/clio/quick-guide-to-implementing-webhooks-in-clio),
[Clio](https://www.clio.com/),
[Clio × Jurisage coverage](https://www.lawnext.com/2026/06/clio-acquires-jurisage-paving-the-way-for-canadian-launch-of-clio-work-and-other-canadian-ai-tools.html),
[oktopeak/clio-mcp](https://github.com/oktopeak/clio-mcp),
[oktopeak/filevine-mcp](https://github.com/oktopeak/filevine-mcp),
[RosenAdvertising/mycase-mcp](https://github.com/RosenAdvertising/mycase-mcp),
[Filevine API v2](https://developer.filevine.io/docs/v2-us/a917e89715b00-filevine-api-gateway),
[Filevine webhook security](https://developer.filevine.io/docs/v2-ca/branches/main/15de82e461c3e-webhook-security),
[Filevine webhook subscriptions](https://support.filevine.com/hc/en-us/articles/13644331859611-Webhooks-Subscriptions),
[Filevine about](https://www.filevine.com/about/),
[Filevine growth figures (Sacra)](https://sacra.com/c/filevine/),
[MyCase vs Filevine](https://www.mycase.com/comparison/mycase-vs-filevine/),
[MyCase getting started](https://mycaseapi.stoplight.io/docs/mycase-api-documentation/k5xpc4jyhkom7-getting-started),
[MyCase Open API help](https://supportcenter.mycase.com/en/articles/9370198-open-api).

## 8. Phase-0 record

Filed as [issue 529](https://github.com/legalquants/lq-ai/issues/529) on
2026-08-18; the anchor ADR travels as
[PR 530](https://github.com/legalquants/lq-ai/pull/530) per the ADR-first rule
(2026-07-19 committee call). First maintainer review received 2026-08-19; this
v2 is the response. Numbering (ADR 0028 / DE-388) was checked against open PRs
on 2026-08-18—ADR 0026 claimed by both PR 528 and PR 418, ADR 0027 by PR 430,
DE-387 by PR 528—and moves with the merge queue. The PRD §9 DE-388 entry lands
with the first implementation PR once the ADR is accepted and the number holds.
