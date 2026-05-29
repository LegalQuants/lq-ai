# LQ.AI Open Roadmap

> Live punch list of work on the LQ.AI development roadmap that has **not yet shipped**. Curated so a prospective contributor (or maintainer planning the next milestone) can see, at a glance, what is open, roughly when it should land, and what kind of background it takes to ship.

## What this is

This document distills four other sources into one ordered, labelled list:

- [`docs/PRD.md` §8 Roadmap](PRD.md#8-roadmap) — the milestone plan (M1 → M7).
- [`docs/PRD.md` §9 Deferred Enhancements](PRD.md#9-deferred-enhancements-and-identified-future-work) — the DE-XXX backlog (~150 entries).
- [`docs/HONEST-STATE.md`](HONEST-STATE.md) — what is shipped today vs. deferred.
- The active milestone plans: [M3](M3-IMPLEMENTATION-PLAN.md), [M4](M4-IMPLEMENTATION-PLAN.md), and the [mini-PRD list](contribute/EASIEST-CONTRIBUTIONS.md) for contributor-ready work.

If a row in this doc disagrees with the canonical source, the source wins. Treat this as a navigation aid, not the source of truth — the source documents above are.

## How this is ordered

Within each section, items are listed in the order they should be picked up. Across sections, the ordering reflects the maintainer team's view of dependency and value:

1. **Active milestone work** — finish what's in flight (M4 close-out).
2. **PRD-committed deferrals** — capabilities the PRD promised but punted (M3 descopes that landed on the M4 / community contribution path; M4 Contract Repository).
3. **Contributor-ready mini-PRDs** — short-cycle pickups where the foundation is already in source.
4. **Engineering discipline & operability** — measurable rigor that the project commits to but does not yet enforce.
5. **Compliance & procurement** — framework-mapped docs that unlock procurement conversations.
6. **Skill, UI, provider, and infrastructure expansions** — broad backlog from PRD §9.
7. **Forward-looking M5+** — community-driven workflow intelligence; architectural slots exist.

## Legend

**Complexity** (conceptual difficulty)

- 🟢 **Low** — well-bounded, follows an existing pattern, mostly mechanical.
- 🟡 **Medium** — requires judgment, integration across 2–3 subsystems, or domain context.
- 🔴 **High** — novel work, architectural decisions, or hard cross-cutting interactions.

**Effort** (time for a competent contributor)

- **S** — under a day.
- **M** — a few days.
- **L** — 1–2 weeks.
- **XL** — multi-week / requires sustained focus.

**Skill profile** (who can pick this up)

- **Junior** — first PR territory; rubric is clear, scope is small.
- **Mid** — needs comfort in the relevant subsystem (FastAPI, SvelteKit, LangGraph, Office.js, etc.).
- **Senior** — architectural judgment required; touches the security boundary or load-bearing paths.
- Specialty tags: `Frontend` (SvelteKit), `Backend` (FastAPI / Python), `Gateway` (Python, security-sensitive), `DevOps` (Docker / Helm / CI), `Security`, `AI/ML`, `Legal-domain` (practicing attorney or in-house counsel), `Compliance`, `Office.js`, `Design`.

Items that touch the Inference Gateway, authentication, audit logging, or cryptography require security review per [`.github/CODEOWNERS`](../.github/CODEOWNERS).

---

## 1. Active milestone work — M4 close-out

The Autonomous Layer is the in-flight milestone. M4 Phase A (substrate + brakes), Phase B (four primitives — memory, precedent, schedules, watches), Phase C (notifications + web dashboard), and M4-D1 (Learn-tab visualization) have all shipped. The remaining work is the executor uplift, the acceptance lap, and the Contract Repository capability that lives alongside the Autonomous Layer in M4 scope.

| # | Item | Source | Complexity | Effort | Skill | Notes |
|---|---|---|---|---|---|---|
| 1.1 | **Wire real in-loop agentic work into the executor** | [M4 plan](M4-IMPLEMENTATION-PLAN.md) + commits `d1293b4`, `7da5c47` | 🔴 High | XL | Senior, Backend, AI/ML | Design landed; implementation in progress on the active feature branch. Replaces the placeholder loop in the executor with real per-step tool dispatch through `guarded_tool_call`. |
| 1.2 | **M4-D2 — Boundary-registers flip + docs finalization + fresh-install acceptance** | [M4 §M4-D2](M4-IMPLEMENTATION-PLAN.md) | 🟡 Medium | M | Mid, Backend + Docs | The acceptance lap that flips PRD §3.10 status to "Shipped (v0.4.0)" and runs a clean-stack walkthrough of every M4 surface. |
| 1.3 | **Contract Repository — Auto-Relationship Detection (M4)** | [PRD §3.16](PRD.md#316-contract-repository--auto-relationship-detection-m4); HONEST-STATE §4 | 🔴 High | XL | Senior, Backend + AI/ML | Not yet started in source (no `contract_relationships` table). Pipeline produces a relationship graph (amendments, restatements, references, master/sub) over a KB; user-confirmable edges; operative-document-chain reasoning. Largest single capability still on the M4 plate. |
| 1.4 | DE-293 — Autonomous-layer restraints (R4 economic, R5 temporal, R6 contextual) follow-through | [PRD §9 DE-293](PRD.md#de-293--autonomous-layer-restraints-r4-economic-r5-temporal-r6-contextual) | 🟡 Medium | M | Senior, Backend + Security | Chokepoint shipped; remaining work is the second-pass tuning + per-deployment policy surfaces. |
| 1.5 | DE-294 — Cross-agent handoff validation for autonomous multi-agent flows | [PRD §9 DE-294](PRD.md#de-294--cross-agent-handoff-validation-for-autonomous-multi-agent-flows) | 🔴 High | L | Senior, Backend | Lands once the single-agent v1 (M4-1) is stable; foundation for M5+ multi-agent direction. |
| 1.6 | DE-321 — Watch firing under a future KB-sharing model | [PRD §9 DE-321](PRD.md#de-321--watch-firing-under-a-future-kb-sharing-model-m4-b4-finding) | 🟡 Medium | M | Mid, Backend | Identified during M4-B4; lands when KB sharing across users becomes a thing. |
| 1.7 | DE-322 — Validate playbook/project FK ownership on schedule + watch create | [PRD §9 DE-322](PRD.md#de-322--validate-playbookproject-fk-ownership-on-schedule--watch-create-m4-b3b4-finding) | 🟢 Low | S | Junior, Backend | Authorization tightening at the create endpoints. |
| 1.8 | DE-323 — Surface autonomous context proposals on the Matter detail page | [PRD §9 DE-323](PRD.md#de-323--surface-autonomous-context-proposals-on-the-matter-detail-page-m4-c2-finding) | 🟡 Medium | M | Mid, Frontend | Deferred from M4-C2 dashboard; needs a small UI surface on `/lq-ai/matters/[id]`. |
| 1.9 | DE-324 — Global-chrome notification bell for autonomous notifications | [PRD §9 DE-324](PRD.md#de-324--global-chrome-notification-bell-for-autonomous-notifications-m4-c2-finding) | 🟡 Medium | M | Mid, Frontend | Adds a top-chrome bell with the unread count from `/api/v1/notifications`. |

---

## 2. PRD-committed capabilities deferred to M4 / community

M3 shipped most of its plate (Playbooks, Tabular Review, the M3 plumbing for Slack/Teams and the Word add-in), but three user-facing surfaces were intentionally descoped during M3 to keep the milestone scoped to the engine work + plumbing. These are the highest-leverage community pickups today.

| # | Item | Source | Complexity | Effort | Skill | Notes |
|---|---|---|---|---|---|---|
| 2.1 | **DE-287 — Word add-in feature surface (chat, skills, playbooks, tier badge)** | [PRD §9 DE-287](PRD.md#de-287--word-add-in-feature-surface-chat-skills-playbooks-tier-badge--deferred-to-m4--community-contribution); [M3 §M3-B3..B6](M3-IMPLEMENTATION-PLAN.md) | 🔴 High | XL | Senior, Office.js + Frontend | The scaffold, OAuth, and version handshake ship in v0.3.0 (M3-B1/B2/B8). What remains: chat against the open doc, apply skills to selection or document, execute Playbooks with tracked-changes redlines + Word comments, and the inference-tier badge in the task pane. |
| 2.2 | **DE-288 — Slack/Teams `/lq` slash command + `/lq ask` quick-skill flow** | [PRD §9 DE-288](PRD.md#de-288--slackteams-lq-slash-command--quick-skill-flow--deferred-to-m4--community-contribution); [M3 §M3-D2/D3](M3-IMPLEMENTATION-PLAN.md) | 🟡 Medium | L | Mid, Backend (`slack-bridge`/`teams-bridge` services) | OAuth install + identity mapping plumbing shipped in M3-D1/D3. What remains: the `/lq` (forward-as-chat) and `/lq ask` (quick-skill) flows on both bridges + the admin UI dropdown to pick a quick-ask skill. |
| 2.3 | **DE-295 — Word add-in code-signing certificate + signed manifest CI** | [PRD §9 DE-295](PRD.md#de-295--word-add-in-code-signing-certificate--signed-manifest-ci-community-led) | 🟡 Medium | M | Mid, DevOps + Office.js | The unsigned-manifest sideload path ships in v0.3.0. What remains: cert procurement (community Phase A), CI integration for signed manifest builds, distribution package. Removes the "unsigned add-in" warning in Microsoft 365 Admin Center. |
| 2.4 | DE-296 — Tabular Review document-source surface: Project-scoped + free-pick | [PRD §9 DE-296](PRD.md#de-296--tabular-review-document-source-surface-project-scoped--free-pick-deferred-from-m3-c3) | 🟡 Medium | M | Mid, Frontend + Backend | Deferred from M3-C3; replaces the document-id paste-in with a real picker. |
| 2.5 | DE-297 — Table-mode skill authoring UI in `/skills/new` (column editor) | [PRD §9 DE-297](PRD.md#de-297--table-mode-skill-authoring-ui-in-skillsnew-column-editor-deferred-from-m3-c3) | 🟡 Medium | M | Mid, Frontend | Column-editor UX so attorneys can author tabular skills without hand-editing YAML. |
| 2.6 | DE-298 — Tabular Review built-ins browser polish on `/skills` page | [PRD §9 DE-298](PRD.md#de-298--tabular-review-built-ins-browser-polish-on-skills-page-deferred-from-m3-c3) | 🟢 Low | S | Junior, Frontend | UI polish on the skill catalog so table skills are discoverable. |
| 2.7 | DE-304 — Tabular Review bulk operations: redline-per-row + summarize-column | [PRD §9 DE-304](PRD.md#de-304--tabular-review-bulk-operations-redline-per-row--summarize-column-deferred-from-m3-c4) | 🔴 High | L | Senior, Backend + Frontend | Extends the tabular workflow with bulk redline / summarize actions. |
| 2.8 | DE-309 — Tabular cells: real Citation-Engine-backed provenance | [PRD §9 DE-309](PRD.md#de-309--tabular-cells-real-citation-engine-backed-provenance-m3-e1-finding-f6-follow-on) | 🟡 Medium | M | Mid, Backend | Routes tabular cell extraction through the M2 Citation Engine cascade instead of the placeholder. |
| 2.9 | DE-310 — Tabular per-cell `tier_used` + `cost_usd` propagation from the gateway | [PRD §9 DE-310](PRD.md#de-310--tabular-per-cell-tier_used--cost_usd-propagation-from-the-gateway-m3-e1-finding-f6-telemetry) | 🟡 Medium | M | Mid, Backend + Gateway | Surfaces per-cell tier + cost in the tabular results envelope. |
| 2.10 | DE-308 — Easy Playbook clustering over-segments and can miss a designed axis | [PRD §9 DE-308](PRD.md#de-308--easy-playbook-clustering-over-segments-and-can-miss-a-designed-axis-m3-e1-finding-f5) | 🟡 Medium | M | Mid, AI/ML + Backend | Tuning pass on the Easy Playbook clustering pipeline; needs eval against a corpus. |

---

## 3. Contributor-ready mini-PRDs

Curated short-cycle pickups maintained at [`docs/contribute/EASIEST-CONTRIBUTIONS.md`](contribute/EASIEST-CONTRIBUTIONS.md). Each links to a mini-PRD with scope, acceptance criteria, and a "Where to start" section.

| # | Item | Source | Complexity | Effort | Skill | Notes |
|---|---|---|---|---|---|---|
| 3.1 | Procurement-Readiness Pack (SIG Lite + CAIQ Lite + cover letter) | [mini-PRD](contribute/mini-prds/procurement-readiness-pack.md); [DE-086](PRD.md#de-086--procurement-readiness-pack) / [DE-235](PRD.md#de-235--procurement-readiness-pack-sig-lite--caiq) | 🟡 Medium | M | Legal-domain / Compliance (in-house counsel) | M2-D3 starter shipped (privileged-matter scope only). Full pack is the deliverable. |
| 3.2 | OWASP LLM Top 10 mapping | [mini-PRD](contribute/mini-prds/owasp-llm-top10-mapping.md); [DE-224](PRD.md#de-224--owasp-llm-top-10-mitigation-mapping) | 🟡 Medium | S–M | Security-aware engineer | Maps every OWASP LLM Top 10 risk to a specific LQ.AI mitigation with source pointer. |
| 3.3 | Acceptance tests for built-in skills | [mini-PRD](contribute/mini-prds/skill-acceptance-tests.md); [DE-051](PRD.md#de-051--acceptance-testing-for-the-m1-skill-set-against-real-documents) / [DE-236](PRD.md#de-236--acceptance-tests-for-the-10-starter-skills) | 🟡 Medium | M (per skill) | Practicing attorney | Per-skill pickups; the 10 starter skills each have a `test-plan.md` waiting for a corpus run. |
| 3.4 | OpenSSF Scorecard + Best Practices badges | [mini-PRD](contribute/mini-prds/openssf-scorecard-and-badges.md); [DE-222](PRD.md#de-222--openssf-scorecard-published-in-readme-and-automated-in-ci) / [DE-223](PRD.md#de-223--openssf-best-practices-badge-passing--silver--gold) | 🟢 Low | S | Junior-to-mid engineer | Scorecard workflow + Best Practices Badge submission. Target: Passing at M1, Silver at M2. |
| 3.5 | Air-gap install verification CI test | [mini-PRD](contribute/mini-prds/air-gap-install-verification.md); [DE-032](PRD.md#de-032--air-gap-install-verification) / [DE-233](PRD.md#de-233--air-gap-install-verification-ci-test) | 🟡 Medium | S–M | Mid engineer w/ Docker networking | Sealed-network CI test that proves the stack stands up without internet. |
| 3.6 | NIST AI RMF 1.0 Profile mapping | [mini-PRD](contribute/mini-prds/nist-ai-rmf-profile.md); [DE-225](PRD.md#de-225--nist-ai-rmf-10-profile-commitments) | 🟡 Medium | M | AI-governance / compliance professional | Pre-populated framework mapping for operator AI governance teams. |
| 3.7 | Reverse-proxy + TLS deployment recipes (Caddy, Traefik, nginx) | [mini-PRD](contribute/mini-prds/reverse-proxy-tls-deployment-recipes.md); [DE-031](PRD.md#de-031--reverse-proxy--tls-recipes) / [DE-234](PRD.md#de-234--reverse-proxy-and-tls-deployment-recipes-caddy-traefik-nginx) | 🟢 Low | S | Junior-to-mid DevOps | Three drop-in recipes with auto-TLS, OIDC pass-through notes. |
| 3.8 | Community skill installer (admin UI) | [mini-PRD](contribute/mini-prds/community-skill-installer-ui.md); [DE-263](PRD.md#de-263--community-skill-installer-admin-ui) | 🟡 Medium | M | Mid-level engineer (Svelte + FastAPI) | Browse + install community skills from the admin UI; submodule-update workflow today is the gap. |

---

## 4. Engineering discipline & quality

The project commits to measurable rigor; today many of these are documented intent rather than enforced gates. Closing them turns the engineering posture from "asserted" into "verifiable."

| # | Item | Source | Complexity | Effort | Skill | Notes |
|---|---|---|---|---|---|---|
| 4.1 | Documented E2E coverage matrix per surface (`docs/test-strategy.md`) | HONEST-STATE §6 (M1 deliverable still open) | 🟢 Low | S | Mid + Docs | M1 deliverable that didn't ship; per-surface smoke / happy-path / edge-cases matrix with milestone tags. |
| 4.2 | Cypress in CI | HONEST-STATE §6 | 🟡 Medium | M | DevOps | E2E suite runs locally; CI integration is the gap. |
| 4.3 | Coverage gate (PRD §5.8 target: 80% api / 90% gateway) | HONEST-STATE §6 | 🟢 Low | S | DevOps | Workflow runs pytest; add the threshold-enforcing gate. |
| 4.4 | DE-229 — Mutation testing in CI with per-release scores published | [DE-229](PRD.md#de-229--mutation-testing-in-ci-with-per-release-scores-published) | 🟡 Medium | M | Mid, Backend + DevOps | `mutmut` or `cosmic-ray`; publish score per release. |
| 4.5 | DE-230 — Property-based testing (Hypothesis) for Citation Engine + Anonymization invariants | [DE-230](PRD.md#de-230--property-based-testing-for-citation-engine-and-anonymization-layer-invariants) | 🟡 Medium | M | Mid, Backend + AI/ML | High-value for the load-bearing M2 capabilities. |
| 4.6 | DE-231 — Golden / snapshot testing for built-in skills with model-version regression | [DE-231](PRD.md#de-231--golden--snapshot-testing-for-built-in-skills-with-model-version-regression) | 🟡 Medium | L | Mid, Backend + AI/ML | Catches silent regressions when provider model strings flip. |
| 4.7 | DE-232 — WCAG 2.1 AA accessibility audit and CI gate | [DE-232](PRD.md#de-232--wcag-21-aa-accessibility-audit-and-ci-gate) | 🟡 Medium | M | Mid, Frontend + a11y | axe-core CI gate; documented manual audit per release. |
| 4.8 | DE-237 — Eval harness with held-out test sets and inter-rater agreement | [DE-237](PRD.md#de-237--eval-harness-with-held-out-test-sets-and-inter-rater-agreement) | 🔴 High | XL | Senior, AI/ML + Legal-domain | The infrastructure that makes 4.6 + DE-236 systematic; needs design first. |
| 4.9 | DE-238 — Public skill-quality leaderboard | [DE-238](PRD.md#de-238--public-skill-quality-leaderboard) | 🟡 Medium | M | Mid, Frontend + Backend | Depends on 4.8. |
| 4.10 | DE-239 — Prompt-injection detection rates published per skill and per release | [DE-239](PRD.md#de-239--prompt-injection-detection-rates-published-per-skill-and-per-release) | 🟡 Medium | M | Mid, AI/ML + Security | Per-skill rate measurement + release-note publication. |
| 4.11 | DE-240 — PII leakage testing with measurable rates | [DE-240](PRD.md#de-240--pii-leakage-testing-with-measurable-rates) | 🟡 Medium | M | Mid, AI/ML + Security | Depends on the Anonymization Layer (shipped). Pairs with DE-282 below. |
| 4.12 | DE-244 — Signed commits enforced on the main branch | [DE-244](PRD.md#de-244--signed-commits-enforced-on-the-main-branch) | 🟢 Low | S | DevOps | DCO is enforced; this adds cryptographic signing. |
| 4.13 | DE-262 — OpenWebUI fork TypeScript-check migration | [DE-262](PRD.md#de-262--openwebui-fork-typescript-check-migration) | 🔴 High | XL | Senior, Frontend | ~9,359 upstream errors. Prerequisite for OpenSSF Silver badge tier. Long-tail; can be tackled in chunks. |
| 4.14 | DE-282 — Anonymization Layer empirical validation on legal-document corpus | [DE-282](PRD.md#de-282--anonymization-layer-empirical-validation-on-legal-document-corpus) | 🟡 Medium | L | AI/ML + Legal-domain | Closes the "recognizer accuracy empirically unmeasured" caveat on the M2 Anonymization Layer. |
| 4.15 | DE-284 — Tighten `api/tests/` mypy coverage | [DE-284](PRD.md#de-284--tighten-apitests-mypy-coverage) | 🟢 Low | S | Junior, Backend | Bring tests into the typecheck. |
| 4.16 | DE-291 — R1 codification: rules of restraint in the skill-authoring guide + golden tests for starter skills | [DE-291](PRD.md#de-291--r1-codification-rules-of-restraint-in-the-skill-authoring-guide-and-golden-tests-for-starter-skills) | 🟡 Medium | M | Mid, AI/ML + Legal-domain | Codifies the alignment-contract restraints in the skill convention. |
| 4.17 | DE-292 — Playbook executor retrofit: declared tool grants + schema-validated step handoffs + per-execution cost cap | [DE-292](PRD.md#de-292--playbook-executor-retrofit-declared-tool-grants--schema-validated-step-handoffs--per-execution-cost-cap) | 🔴 High | L | Senior, Backend | Brings the M3 Playbook executor up to the alignment-contract bar that M4-A3 set. |
| 4.18 | DE-253 — Consumer-driven contract testing between services | [DE-253](PRD.md#de-253--consumer-driven-contract-testing-between-services) | 🟡 Medium | M | Mid, Backend | Pact-style contracts between `api/` ↔ `gateway/`. |
| 4.19 | DE-252 — Fuzz testing extended to document parsers and anonymization paths | [DE-252](PRD.md#de-252--fuzz-testing-extended-to-document-parsers-and-anonymization-paths) | 🟡 Medium | M | Mid, Backend + Security | Atheris / hypothesis fuzz on the highest-risk parsers. |
| 4.20 | DE-251 — Chaos and fault injection for the gateway and document pipeline | [DE-251](PRD.md#de-251--chaos-and-fault-injection-for-the-gateway-and-document-pipeline) | 🔴 High | L | Senior, DevOps + Backend | Adds toxiproxy / chaos-mesh scenarios to CI. |
| 4.21 | DE-250 — Performance regression with historical tracking | [DE-250](PRD.md#de-250--performance-regression-with-historical-tracking) | 🟡 Medium | M | Mid, DevOps + Backend | Per-PR benchmark with trend chart. |
| 4.22 | DE-254 — Cypress shared helpers extracted to `support/` | [DE-254](PRD.md#de-254--cypress-shared-helpers-extracted-to-support) | 🟢 Low | S | Junior, Frontend | Refactor finding from M1 wave-D2. |
| 4.23 | DE-255 — Add `responseTimeout: 90000` to `cypress.config.ts` | [DE-255](PRD.md#de-255--add-responsetimeout-90000-to-cypressconfigts) | 🟢 Low | S | Junior, Frontend | Single-line config change. |
| 4.24 | DE-256 — KB attach interceptor added to `wave-m1-final-surfaces.cy.ts` Test 2 | [DE-256](PRD.md#de-256--kb-attach-interceptor-added-to-wave-m1-final-surfacescyts-test-2) | 🟢 Low | S | Junior, Frontend | Test reliability patch. |

---

## 5. Observability deepening

OTel SDK ships at M1; the deepening mini-PRD broke out the operator-facing gaps as DE-299..303 + DE-314..318.

| # | Item | Source | Complexity | Effort | Skill | Notes |
|---|---|---|---|---|---|---|
| 5.1 | DE-299 — OTel instrumentation for SQLAlchemy + ARQ workers | [DE-299](PRD.md#de-299--otel-instrumentation-for-sqlalchemy--arq-workers-otel-deepening-de-a) | 🟡 Medium | M | Mid, Backend + DevOps | Closes the DB + worker span gap. |
| 5.2 | DE-300 — Log-trace correlation via structured-logger trace_id / span_id injection | [DE-300](PRD.md#de-300--log-trace-correlation-via-structured-logger-trace_id--span_id-injection-otel-deepening-de-b) | 🟢 Low | S | Junior, Backend | Add the IDs to every log record. |
| 5.3 | DE-301 — OTel MeterProvider for metrics export | [DE-301](PRD.md#de-301--otel-meterprovider-for-metrics-export-otel-deepening-de-c) | 🟡 Medium | M | Mid, Backend | Metrics path alongside the existing traces path. |
| 5.4 | DE-302 — Reconcile OTel with the OpenWebUI fork's inherited telemetry | [DE-302](PRD.md#de-302--reconcile-otel-with-the-openwebui-forks-inherited-telemetry-otel-deepening-de-d) | 🟡 Medium | M | Mid, Frontend | Reconcile the two telemetry stacks in the fork. |
| 5.5 | DE-303 — Browser RUM via OpenTelemetry SDK | [DE-303](PRD.md#de-303--browser-rum-via-opentelemetry-sdk-otel-deepening-de-e) | 🟡 Medium | M | Mid, Frontend | Real User Monitoring for the SvelteKit app. |
| 5.6 | DE-314 — Tabular executions: skill linkage for the `tabular.skill_id` span attribute | [DE-314](PRD.md#de-314--tabular-executions-have-no-skill-linkage-for-the-tabularskill_id-span-attribute-otel-deepening) | 🟢 Low | S | Junior, Backend | Span-attribute fix. |
| 5.7 | DE-315 — Streaming-rehydration per-chunk spans (anonymization) | [DE-315](PRD.md#de-315--streaming-rehydration-per-chunk-spans-otel-deepening-anonymization) | 🟢 Low | S | Junior, Gateway | Adds a child span per rehydrated chunk. |
| 5.8 | DE-316 — Promote skill `author` to the `Skill` / `SkillSummary` wire shape | [DE-316](PRD.md#de-316--promote-skill-author-to-the-skill--skillsummary-wire-shape-otel-deepening-skill-spans) | 🟢 Low | S | Junior, Backend | Wire-shape addition. |
| 5.9 | DE-317 — `inference.dispatch` span on the streaming path | [DE-317](PRD.md#de-317--inferencedispatch-span-on-the-streaming-path-otel-deepening) | 🟢 Low | S | Junior, Gateway | Adds a missing span. |
| 5.10 | DE-318 — `playbook.position` child spans on the redline node | [DE-318](PRD.md#de-318--playbookposition-child-spans-on-the-redline-node-otel-deepening) | 🟢 Low | S | Junior, Backend | Adds a missing child span. |
| 5.11 | DE-245 — Published SLOs / SLIs | [DE-245](PRD.md#de-245--published-service-level-objectives-and-indicators) | 🟡 Medium | M | Mid, DevOps | Lands once 5.3 (metrics path) is in place. |
| 5.12 | DE-246 — Error budget policy | [DE-246](PRD.md#de-246--error-budget-policy) | 🟢 Low | S | DevOps + Docs | Policy doc; pairs with 5.11. |
| 5.13 | DE-247 — Public postmortems within 14 days | [DE-247](PRD.md#de-247--public-postmortems-within-14-days) | 🟢 Low | S | Docs | Template + commitment in `docs/`. |

---

## 6. Compliance & procurement documentation

Compliance Alignment Pack docs are stubs at v1 launch; per-framework alignment docs land as M1 and M2 ship. Some have contributor-friendly mini-PRDs (see §3 above); the rest are listed here for completeness.

| # | Item | Source | Complexity | Effort | Skill | Notes |
|---|---|---|---|---|---|---|
| 6.1 | SOC 2 Type II alignment | HONEST-STATE §5 (`soc2-alignment.md` stub) | 🟡 Medium | L | Compliance | Maps Trust Services Criteria to LQ.AI design choices (Customer Responsibility Matrix style). |
| 6.2 | ISO/IEC 27001:2022 alignment | HONEST-STATE §5 | 🟡 Medium | L | Compliance | Annex A controls mapped to LQ.AI design. |
| 6.3 | DE-024 / ISO/IEC 42001:2023 alignment | [DE-024](PRD.md#de-024--iso-42001-ai-management-system-alignment-documentation) | 🟡 Medium | L | Compliance + AI-governance | Competitive parity with Legora / Legalfly. |
| 6.4 | GDPR readiness | HONEST-STATE §5 | 🟡 Medium | M | Compliance + Legal-domain | Article-by-article readiness; Articles 6, 25, 28, 30, 32, 35, 15–22. |
| 6.5 | HIPAA Security + Privacy Rule alignment | HONEST-STATE §5 | 🟡 Medium | M | Compliance + Legal-domain | Walks operator through HIPAA-eligible deployment. |
| 6.6 | FedRAMP Moderate alignment / DE-113 | [DE-113](PRD.md#de-113--fedramp-aligned-deployment-recipe) | 🔴 High | L | Compliance + DevOps | Gov-tier deployment recipe + controls mapping. |
| 6.7 | DE-226 — MITRE ATLAS threat-model mapping | [DE-226](PRD.md#de-226--mitre-atlas-threat-model-mapping) | 🟡 Medium | M | Security + AI/ML | Extends STRIDE threat model with AI-specific ATLAS tactics. |
| 6.8 | DE-227 — Annual third-party penetration test with public summary | [DE-227](PRD.md#de-227--annual-third-party-penetration-test-with-public-summary) | 🟡 Medium | L | Vendor engagement | First engagement targeted 90 days post-M1. |
| 6.9 | DE-228 — Annual adversarial-AI red-team engagement | [DE-228](PRD.md#de-228--annual-adversarial-ai-red-team-engagement) | 🟡 Medium | L | Vendor engagement | Pairs with 6.8. |
| 6.10 | DE-115 — Formal Vulnerability Disclosure Program | [DE-115](PRD.md#de-115--formal-vulnerability-disclosure-program-vdp) | 🟢 Low | S | Security + Docs | Builds on SECURITY.md; formal VDP + safe-harbor language. |
| 6.11 | DE-313 — Compliance Alignment Pack: reflect M3 external trust boundaries | [DE-313](PRD.md#de-313--compliance-alignment-pack-reflect-the-m3-external-trust-boundaries-m3-e2b-finding) | 🟢 Low | S | Compliance + Docs | Pack update to reflect Word add-in + Slack/Teams trust boundaries. |

---

## 7. Security hardening

| # | Item | Source | Complexity | Effort | Skill | Notes |
|---|---|---|---|---|---|---|
| 7.1 | DE-100 — Tamper-evident audit log | [DE-100](PRD.md#de-100--tamper-evident-audit-log) | 🔴 High | L | Senior, Backend + Security | Hash-chained audit records with periodic anchoring. |
| 7.2 | DE-101 — Cryptographic timestamping of work product | [DE-101](PRD.md#de-101--cryptographic-timestamping-of-work-product) | 🟡 Medium | M | Backend + Security | RFC 3161 TSA integration. |
| 7.3 | DE-102 — HSM and Vault integration | [DE-102](PRD.md#de-102--hardware-security-module-hsm-and-vault-integration) | 🔴 High | L | Senior, Gateway + Security | Alternative to the Fernet master-key path; for HSM-mandated operators. |
| 7.4 | DE-103 — IP allowlisting and geo-restriction | [DE-103](PRD.md#de-103--ip-allowlisting-and-geo-restriction) | 🟡 Medium | M | Backend + Security | Per-user / per-org allowlist enforcement. |
| 7.5 | DE-104 — Just-in-time admin elevation | [DE-104](PRD.md#de-104--just-in-time-admin-elevation) | 🟡 Medium | M | Backend + Security | Time-boxed admin promotion with audit trail. |
| 7.6 | DE-105 — Outbound proxy support | [DE-105](PRD.md#de-105--outbound-proxy-support) | 🟢 Low | S | Gateway + DevOps | Operator-configurable egress proxy. |
| 7.7 | DE-106 — Configurable retention policies | [DE-106](PRD.md#de-106--configurable-retention-policies) | 🟡 Medium | M | Backend | Per-resource TTLs + scheduled deletion job. |
| 7.8 | DE-107 — Operator-side data subject rights tooling | [DE-107](PRD.md#de-107--operator-side-data-subject-rights-tooling) | 🟡 Medium | M | Backend | DSAR fulfilment UI for the operator's admin. |
| 7.9 | DE-108 — Backup encryption with rotation | [DE-108](PRD.md#de-108--backup-encryption-with-rotation) | 🟡 Medium | M | DevOps + Security | Encrypted-at-rest backups + key rotation. |
| 7.10 | DE-109 — Litigation hold support | [DE-109](PRD.md#de-109--litigation-hold-support) | 🟡 Medium | M | Backend + Legal-domain | Per-user / per-matter hold flag that overrides retention. |
| 7.11 | DE-110 — Prompt-injection pattern library | [DE-110](PRD.md#de-110--prompt-injection-pattern-library) | 🟡 Medium | M | AI/ML + Security | Reusable pattern library for skills + gateway. |
| 7.12 | DE-111 — Output-validation guardrails (generalized) | [DE-111](PRD.md#de-111--output-validation-guardrails-generalized) | 🟡 Medium | M | Backend + AI/ML | Generalizes the Citation Engine pattern to other output types. |
| 7.13 | DE-112 — Model checksum verification for local models | [DE-112](PRD.md#de-112--model-checksum-verification-for-local-models) | 🟢 Low | S | Gateway + DevOps | Pin + verify Ollama model digests. |
| 7.14 | DE-114 — Reproducible builds | [DE-114](PRD.md#de-114--reproducible-builds) | 🔴 High | L | Senior, DevOps | Bit-for-bit reproducible container builds. |
| 7.15 | DE-241 — Distroless / minimal container base images | [DE-241](PRD.md#de-241--distroless--minimal-container-base-images) | 🟢 Low | S | DevOps + Security | Switch base images; CVE-surface reduction. |
| 7.16 | DE-242 — mTLS between internal services | [DE-242](PRD.md#de-242--mtls-between-internal-services) | 🟡 Medium | M | DevOps + Security | api ↔ gateway ↔ worker mTLS. |
| 7.17 | DE-243 — Pod Security Standards (Restricted) profile for the Helm chart | [DE-243](PRD.md#de-243--pod-security-standards-restricted-profile-for-the-helm-chart) | 🟢 Low | S | DevOps | Helm chart hardening pass. |
| 7.18 | DE-266 — Tier-floor warning surface for privileged matters | [DE-266](PRD.md#de-266--tier-floor-warning-surface-for-privileged-matters) | 🟢 Low | S | Frontend | UI banner / pre-flight warning. |
| 7.19 | DE-268 — Skill-capture prompt-injection sanitization | [DE-268](PRD.md#de-268--skill-capture-prompt-injection-sanitization) | 🟡 Medium | M | Backend + Security | Sanitization pass on chat-captured skill content. |
| 7.20 | DE-270 — Cryptography review: Fernet vs modern AEAD | [DE-270](PRD.md#de-270--cryptography-review-fernet-vs-modern-aead) | 🟡 Medium | M | Security | Decision-doc + migration path. |
| 7.21 | DE-274 — Anonymization pseudonym-collision in source documents | [DE-274](PRD.md#de-274--anonymization-pseudonym-collision-in-source-documents) | 🟡 Medium | M | Gateway + Security | Per-request salt on the pseudonym format. |

---

## 8. Provider, deployment, and operational infrastructure

| # | Item | Source | Complexity | Effort | Skill | Notes |
|---|---|---|---|---|---|---|
| 8.1 | DE-034 — Google Vertex AI provider adapter (Anthropic on Vertex) | [DE-034](PRD.md#de-034--google-vertex-ai-provider-adapter-anthropic-on-vertex) | 🟡 Medium | M | Mid, Gateway | Wire-format spec complete; contributor-friendly. |
| 8.2 | DE-035 — AWS Bedrock provider adapter (Anthropic on Bedrock) | [DE-035](PRD.md#de-035--aws-bedrock-provider-adapter-anthropic-on-bedrock) | 🟡 Medium | L | Mid, Gateway + AWS | Fully spec'd with Event Stream parser + SigV4 acceptance criteria. |
| 8.3 | DE-278 — Azure OpenAI AD authentication (managed identity / service principal) | [DE-278](PRD.md#de-278--azure-openai-ad-authentication-managed-identity--service-principal) | 🟡 Medium | M | Mid, Gateway + Azure | Extends the M2-shipped Azure OpenAI adapter with AD auth. |
| 8.4 | DE-030 — Helm chart for Kubernetes deployment (production-ready) | [DE-030](PRD.md#de-030--helm-chart-for-kubernetes-deployment) | 🟡 Medium | L | DevOps | Drafted chart exists; production-ready hardening + values matrix is the gap. |
| 8.5 | DE-033 — Backup and restore tooling | [DE-033](PRD.md#de-033--backup-and-restore-tooling) | 🟡 Medium | M | DevOps | `pg_dump` + MinIO snapshot wrapper + restore drill script. |
| 8.6 | DE-248 — Disaster recovery test cadence | [DE-248](PRD.md#de-248--disaster-recovery-test-cadence) | 🟢 Low | S | DevOps + Docs | Cadence doc + test recipe. |
| 8.7 | DE-249 — Runbooks for operational tasks | [DE-249](PRD.md#de-249--runbooks-for-operational-tasks) | 🟡 Medium | M | Docs + DevOps | Per-task runbooks in a new `docs/runbooks/`. |
| 8.8 | DE-305 — Bridge env vars use `${VAR:?}` and break all Compose commands when unset | [DE-305](PRD.md#de-305--bridge-env-vars-use-var-and-break-all-compose-commands-when-unset-m3-e1-finding-f1) | 🟢 Low | S | DevOps | One-line Compose fix from M3 acceptance. |
| 8.9 | DE-306 — Fresh-install host-port collision needs prominent quickstart callout | [DE-306](PRD.md#de-306--fresh-install-host-port-collision-needs-prominent-quickstart-callout-m3-e1-finding-f2) | 🟢 Low | S | Docs | Quickstart edit. |
| 8.10 | DE-311 — Single source of truth for the application version | [DE-311](PRD.md#de-311--single-source-of-truth-for-the-application-version-m3-e1-finding-f3-follow-on) | 🟢 Low | S | Backend + DevOps | Consolidate version reads. |
| 8.11 | DE-312 — Slack + Teams bridge OAuth end-to-end tunnel verification | [DE-312](PRD.md#de-312--slack--teams-bridge-oauth-end-to-end-tunnel-verification-m3-e1-finding) | 🟡 Medium | M | Backend + DevOps | Adds a recipe + smoke test for the public-tunnel OAuth dance. |
| 8.12 | DE-319 — Migrate LangGraph 0.2 → 1.x | [DE-319](PRD.md#de-319--migrate-langgraph-02--1x-re-type-the-executors) | 🟡 Medium | M | Mid, Backend | Re-types the M3/M4 executors against LangGraph 1.x. |

---

## 9. Skill ecosystem expansions

| # | Item | Source | Complexity | Effort | Skill | Notes |
|---|---|---|---|---|---|---|
| 9.1 | DE-001 — Additional starter skills beyond the M1 set | [DE-001](PRD.md#de-001--additional-starter-skills-beyond-the-m1-set) | 🟡 Medium | M (per skill) | Legal-domain + Backend | Per-skill pickups; rubric in [`skills/CONTRIBUTING.md`](../skills/CONTRIBUTING.md). |
| 9.2 | DE-002 — Additional regimes for DPA Checklist Review | [DE-002](PRD.md#de-002--additional-regimes-for-dpa-checklist-review) | 🟡 Medium | M | Legal-domain | Non-EU regimes; CCPA, LGPD, PIPL, etc. |
| 9.3 | DE-003 — Additional worked examples for DPA Checklist Review | [DE-003](PRD.md#de-003--additional-worked-examples-for-dpa-checklist-review) | 🟢 Low | S | Legal-domain | Adds to the examples library. |
| 9.4 | DE-004 — NDA Review redlined-document output mode | [DE-004](PRD.md#de-004--nda-review-redlined-document-output-mode) | 🟡 Medium | M | Backend + Legal-domain | Adds a redline-output mode to the M1 skill. |
| 9.5 | DE-005 — Defined-Terms Consistency Check (skill) | [DE-005](PRD.md#de-005--defined-terms-consistency-check-skill) | 🟡 Medium | M | Legal-domain | New skill. |
| 9.6 | DE-006 — Cross-Document Comparison (skill) | [DE-006](PRD.md#de-006--cross-document-comparison-skill) | 🟡 Medium | M | Legal-domain | New skill. |
| 9.7 | DE-007 — Issue List Generator (skill output mode) | [DE-007](PRD.md#de-007--issue-list-generator-skill-output-mode) | 🟡 Medium | M | Backend + Legal-domain | New output mode. |
| 9.8 | DE-008 — Self-serve business-user contract generation (skill family) | [DE-008](PRD.md#de-008--self-serve-business-user-contract-generation-skill-family) | 🔴 High | L | Senior, Legal-domain + Backend | Skill family. |
| 9.9 | DE-020 — Standardize the optional-input pattern across skills | [DE-020](PRD.md#de-020--standardize-the-optional-input-pattern-across-skills) | 🟢 Low | S | Backend | Cross-skill consistency pass. |
| 9.10 | DE-021 — Skill versioning and publishing flow | [DE-021](PRD.md#de-021--skill-versioning-and-publishing-flow) | 🟡 Medium | L | Mid, Backend + Frontend | Semantic-version publish flow. |
| 9.11 | DE-022 — Skill performance and quality measurement | [DE-022](PRD.md#de-022--skill-performance-and-quality-measurement) | 🟡 Medium | M | Mid, AI/ML | Per-skill quality metrics surfaced in UI. |
| 9.12 | DE-023 — External-Counsel Collaboration Boundary | [DE-023](PRD.md#de-023--external-counsel-collaboration-boundary) | 🔴 High | L | Senior, Backend + Legal-domain | New isolation primitive. |
| 9.13 | DE-050 — Skill quality bar / review process for community contributions | [DE-050](PRD.md#de-050--skill-quality-bar--review-process-for-community-contributions) | 🟡 Medium | M | Maintainer + Docs | Process doc + reviewer guide. |
| 9.14 | DE-060 — Multi-document Q&A for Contract QA | [DE-060](PRD.md#de-060--multi-document-qa-for-contract-qa) | 🟡 Medium | M | Backend + Legal-domain | Extends Contract QA across N docs. |
| 9.15 | DE-061 — Contract QA acceptance testing | [DE-061](PRD.md#de-061--contract-qa-acceptance-testing) | 🟡 Medium | M | Legal-domain | Per-skill acceptance suite. |
| 9.16 | DE-070 — Dedicated Order Form / SOW Review skill | [DE-070](PRD.md#de-070--dedicated-order-form--sow-review-skill) | 🟡 Medium | M | Legal-domain | New skill. |
| 9.17 | DE-071 — Additional MSA review variants | [DE-071](PRD.md#de-071--additional-msa-review-variants) | 🟡 Medium | M | Legal-domain | Industry-specific variants. |
| 9.18 | DE-072 — MSA Review acceptance testing against real document corpus | [DE-072](PRD.md#de-072--msa-review-acceptance-testing-against-real-document-corpus) | 🟡 Medium | M | Legal-domain | Per-skill acceptance suite. |
| 9.19 | DE-080 — Shared infrastructure for contract-review skill family | [DE-080](PRD.md#de-080--shared-infrastructure-for-contract-review-skill-family) | 🔴 High | L | Senior, Backend | Refactor pass once 9.5–9.8 ship. |
| 9.20 | DE-081 — Obligation Tracking / Renewal Calendar | [DE-081](PRD.md#de-081--obligation-tracking--renewal-calendar) | 🔴 High | L | Senior, Backend + Legal-domain | New capability — depends on Autonomous Layer (M4). |
| 9.21 | DE-082 — Regulatory Monitoring with Proactive Alerts | [DE-082](PRD.md#de-082--regulatory-monitoring-with-proactive-alerts) | 🔴 High | L | Senior, Backend + Legal-domain | Depends on Autonomous Layer + the M5+ signal aggregation work. |
| 9.22 | DE-083 — Google Docs Add-On (M3 sister to the Word Add-In) | [DE-083](PRD.md#de-083--google-docs-add-on-m3-sister-to-the-word-add-in) | 🔴 High | XL | Senior, Frontend (Apps Script) | Sister to DE-287. |
| 9.23 | DE-084 — Email-as-Intake Bridge | [DE-084](PRD.md#de-084--email-as-intake-bridge) | 🟡 Medium | L | Mid, Backend | Cousin to the M3 Slack/Teams bridge. |
| 9.24 | DE-085 — Operational Analytics for Legal Ops | [DE-085](PRD.md#de-085--operational-analytics-for-legal-ops) | 🟡 Medium | L | Mid, Frontend + Backend | Dashboard for legal-ops analytics. |
| 9.25 | DE-219 — Wave G community-skill installer + first port batch | [DE-219](PRD.md#de-219--wave-g-community-skill-installer--first-port-batch) | 🟡 Medium | M | Frontend + Backend | Pairs with 3.8 community installer UI. |
| 9.26 | DE-220 — Organization Profile singleton skill (per-firm playbook) | [DE-220](PRD.md#de-220--organization-profile-singleton-skill-per-firm-playbook) | 🟡 Medium | M | Backend + Legal-domain | Already-stubbed; substantive content needed. |
| 9.27 | DE-264 — LegalQuants ecosystem integration (PrivacyQuant statutory graph + MCP path) | [DE-264](PRD.md#de-264--legalquants-ecosystem-integration-privacyquant-statutory-graph--mcp-path) | 🔴 High | L | Senior, Backend | Depends on MCP subsystem (M5). |
| 9.28 | DE-285 — First-run sample-NDA knowledge base for the Easy Playbook wizard | [DE-285](PRD.md#de-285--first-run-sample-nda-knowledge-base-for-the-easy-playbook-wizard) | 🟢 Low | S | Backend + Legal-domain | Adds a sample KB for first-run UX. |
| 9.29 | DE-286 — Cross-document label normalization on richer contract types (Easy Playbook clustering tuning) | [DE-286](PRD.md#de-286--cross-document-label-normalization-on-richer-contract-types-easy-playbook-clustering-tuning) | 🟡 Medium | M | AI/ML + Legal-domain | Tuning pass for non-NDA document types. |

---

## 10. Application UI enhancements

| # | Item | Source | Complexity | Effort | Skill | Notes |
|---|---|---|---|---|---|---|
| 10.1 | DE-010 — Skill input form rendering for any skill | [DE-010](PRD.md#de-010--skill-input-form-rendering-for-any-skill) | 🟡 Medium | M | Frontend | Dynamic form generation from skill frontmatter. |
| 10.2 | DE-011 — Reasoning visibility configuration for Enhance Prompt | [DE-011](PRD.md#de-011--reasoning-visibility-configuration-for-enhance-prompt) | 🟢 Low | S | Frontend | Toggle + UI surface. |
| 10.3 | DE-012 — Skill inspector side panel | [DE-012](PRD.md#de-012--skill-inspector-side-panel) | 🟡 Medium | M | Frontend | Side panel that surfaces the SKILL.md + references. |
| 10.4 | DE-014 — Tone / Audience Settings on Skills | [DE-014](PRD.md#de-014--tone--audience-settings-on-skills) | 🟢 Low | S | Backend + Frontend | Per-skill tone defaults. |
| 10.5 | DE-015 — Voice / Dictation Input | [DE-015](PRD.md#de-015--voice--dictation-input) | 🟡 Medium | L | Mid, Frontend | Web Speech API integration with privacy posture. |
| 10.6 | DE-265 — In-app "unverified citation" badging until Citation Engine ships | [DE-265](PRD.md#de-265--in-app-unverified-citation-badging-until-citation-engine-ships) | 🟢 Low | S | Frontend | Closed by M2 if not already removed; verify status before claiming. |
| 10.7 | DE-272 — Admin AliasForm: model dropdown autocomplete population | [DE-272](PRD.md#de-272--admin-aliasform-model-dropdown-autocomplete-population) | 🟢 Low | S | Junior, Frontend | One-prop wiring fix called out in HONEST-STATE §1. |
| 10.8 | DE-273 — Audit log API: server-side actor enrichment | [DE-273](PRD.md#de-273--audit-log-api-server-side-actor-enrichment) | 🟢 Low | S | Junior, Backend | Server-side enrichment fix. |
| 10.9 | DE-275 — Embed M2 citations in chat-message envelope | [DE-275](PRD.md#de-275--embed-m2-citations-in-chat-message-envelope) | 🟡 Medium | M | Backend + Frontend | Avoids the per-message follow-up `/citations` call. |
| 10.10 | DE-276 — Ingest observability: surface silent embed/parse failures | [DE-276](PRD.md#de-276--ingest-observability-surface-silent-embedparse-failures) | 🟡 Medium | M | Mid, Backend | Pre-M3 hardening item per M3 Phase 0; verify status. |
| 10.11 | DE-277 — Citation extractor: fallback to document scan on chunk-boundary miss | [DE-277](PRD.md#de-277--citation-extractor-fallback-to-document-scan-on-chunk-boundary-miss) | 🟡 Medium | M | Mid, Backend + AI/ML | Known M2 limitation; failing test is pinned and waiting for the fix. |
| 10.12 | DE-279 — Case citation validation (Bluebook resolution via CourtListener) | [DE-279](PRD.md#de-279--case-citation-validation-bluebook-resolution-via-courtlistener) | 🔴 High | L | Senior, Backend + Legal-domain | New verification capability. |
| 10.13 | DE-280 — Case-content accuracy (statement vs judicial opinion) | [DE-280](PRD.md#de-280--case-content-accuracy-statement-vs-judicial-opinion) | 🔴 High | L | Senior, AI/ML + Legal-domain | Companion to 10.12. |
| 10.14 | DE-281 — Citation Engine operational-telemetry calibration | [DE-281](PRD.md#de-281--citation-engine-operational-telemetry-calibration-tolerant_match_threshold--aggregation_rule) | 🟡 Medium | M | Mid, AI/ML | Per-deployment tuning of the cascade thresholds. |
| 10.15 | DE-283 — Fresh-install login UX: surface the bootstrap-password path on first 401 | [DE-283](PRD.md#de-283--fresh-install-login-ux-surface-the-bootstrap-password-path-on-first-401) | 🟢 Low | S | Junior, Frontend | M3 Phase 0 hardening item; verify status. |
| 10.16 | DE-257 — `/api/v1/audit-health` endpoint for AmbientFooter signal | [DE-257](PRD.md#de-257--apiv1audit-health-endpoint-for-ambientfooter-signal) | 🟢 Low | S | Junior, Backend | Endpoint + footer wiring. |
| 10.17 | DE-258 — KB embedding-progress percentage aggregation | [DE-258](PRD.md#de-258--kb-embedding-progress-percentage-aggregation) | 🟢 Low | S | Junior, Backend | Aggregation endpoint. |
| 10.18 | DE-259 — KB attached-matters reverse-lookup | [DE-259](PRD.md#de-259--kb-attached-matters-reverse-lookup) | 🟢 Low | S | Junior, Backend | Reverse-lookup endpoint. |
| 10.19 | DE-260 — Receipts assistant-side skill event deduplication | [DE-260](PRD.md#de-260--receipts-assistant-side-skill-event-deduplication) | 🟢 Low | S | Junior, Backend | Dedup pass. |
| 10.20 | DE-261 — `api/client.ts` `errorFor` swallows string-shaped FastAPI detail bodies | [DE-261](PRD.md#de-261--apiclientts-errorfor-swallows-string-shaped-fastapi-detail-bodies) | 🟢 Low | S | Junior, Frontend | Single-function fix. |
| 10.21 | DE-307 — `File` API schema exposes `page_count`/`character_count` that never populate | [DE-307](PRD.md#de-307--file-api-schema-exposes-page_countcharacter_count-that-never-populate-m3-e1-finding-f4) | 🟢 Low | S | Junior, Backend | Either populate or remove from schema. |

---

## 11. Forward-looking — M5+ Workflow Intelligence

**Status:** Community-driven; not committed in v1–v4. The maintainer team will coordinate direction; the architectural slots needed (the MCP-client subsystem; the Autonomous Layer extensibility) are committed in M1–M4 so this work is community-extensible rather than requiring core refactoring. See [PRD §8.5](PRD.md#m5m7--forward-looking-workflow-intelligence-community-driven-not-committed).

| # | Item | Source | Complexity | Effort | Skill | Notes |
|---|---|---|---|---|---|---|
| 11.1 | DE-200 — MCP-client subsystem in the LQ.AI backend | [DE-200](PRD.md#de-200--mcp-client-subsystem-in-the-lq-ai-backend) | 🔴 High | XL | Senior, Backend | Architectural slot scheduled for M2; full operationalization is M5. Foundation for M5+ connectors. |
| 11.2 | DE-201 — Signal Aggregation Service | [DE-201](PRD.md#de-201--signal-aggregation-service) | 🔴 High | XL | Senior, Backend | Skeleton service in M5. Depends on 11.1. |
| 11.3 | DE-202 — Email connector via MCP | [DE-202](PRD.md#de-202--email-connector-via-mcp) | 🔴 High | L | Senior, Backend | Gmail / Outlook / IMAP. Depends on 11.1. |
| 11.4 | DE-203 — Calendar connector via MCP | [DE-203](PRD.md#de-203--calendar-connector-via-mcp) | 🟡 Medium | L | Mid, Backend | Google Calendar / Outlook Calendar. Depends on 11.1. |
| 11.5 | DE-204 — Task system connectors via MCP | [DE-204](PRD.md#de-204--task-system-connectors-via-mcp) | 🟡 Medium | L | Mid, Backend | Linear or Asana (community-driven choice). |
| 11.6 | DE-205 — CRM connector via MCP | [DE-205](PRD.md#de-205--crm-connector-via-mcp) | 🟡 Medium | L | Mid, Backend | Per-CRM. |
| 11.7 | DE-206 — Document store connectors via MCP | [DE-206](PRD.md#de-206--document-store-connectors-via-mcp) | 🟡 Medium | L | Mid, Backend | NetDocuments / iManage / SharePoint / Google Drive. |
| 11.8 | DE-207 — Prioritization Engine | [DE-207](PRD.md#de-207--prioritization-engine) | 🔴 High | XL | Senior, AI/ML + Backend | M6 — depends on Signal Aggregation. |
| 11.9 | DE-208 — Today View UI surface | [DE-208](PRD.md#de-208--today-view-ui-surface) | 🟡 Medium | L | Mid, Frontend | M5 basic; M6 advanced. |
| 11.10 | DE-209 — Email Triage Skill | [DE-209](PRD.md#de-209--email-triage-skill) | 🟡 Medium | M | Mid, Backend + Legal-domain | Depends on 11.3. |
| 11.11 | DE-210 — Calendar Prep Skill | [DE-210](PRD.md#de-210--calendar-prep-skill) | 🟡 Medium | M | Mid, Backend + Legal-domain | Depends on 11.4. |
| 11.12 | DE-211 — Agent Execution Framework | [DE-211](PRD.md#de-211--agent-execution-framework) | 🔴 High | XL | Senior, Backend | M6 — multi-step agents with approval gates. Extends M4 Autonomous Layer. |
| 11.13 | DE-212 — Voice mode for the Today View | [DE-212](PRD.md#de-212--voice-mode-for-the-today-view) | 🟡 Medium | L | Mid, Frontend | Web Speech / wake-word. |
| 11.14 | DE-213 — Cross-matter pattern recognition | [DE-213](PRD.md#de-213--cross-matter-pattern-recognition) | 🔴 High | L | Senior, AI/ML | M7. |
| 11.15 | DE-214 — Counterparty intelligence | [DE-214](PRD.md#de-214--counterparty-intelligence) | 🔴 High | L | Senior, AI/ML + Backend | M7. |
| 11.16 | DE-215 — Negotiation-state tracking | [DE-215](PRD.md#de-215--negotiation-state-tracking) | 🟡 Medium | L | Mid, Backend + Legal-domain | M7. |
| 11.17 | DE-216 — Personal decision history | [DE-216](PRD.md#de-216--personal-decision-history) | 🟡 Medium | L | Mid, Backend | M7. |
| 11.18 | DE-217 — Time-blocked work mode | [DE-217](PRD.md#de-217--time-blocked-work-mode) | 🟡 Medium | M | Mid, Frontend + Backend | M7. |
| 11.19 | DE-218 — Async team handoff briefs | [DE-218](PRD.md#de-218--async-team-handoff-briefs) | 🟡 Medium | M | Mid, Backend | M7. |
| 11.20 | DE-221 — Managed-Agents-equivalent (scheduled-agent runtime) | [DE-221](PRD.md#de-221--managed-agents-equivalent-scheduled-agent-runtime) | 🔴 High | XL | Senior, Backend | Architectural extension of M4 Autonomous Layer. |

---

## 12. Out-of-scope / Permanently deferred

These appear in PRD §9 but the project does not currently plan to implement them. Listed here for completeness; do not claim without an upfront maintainer discussion to confirm fit.

| # | Item | Source | Reason out of scope |
|---|---|---|---|
| 12.1 | DE-040 — Direct CLM integration | [DE-040](PRD.md#de-040--direct-clm-integration) | LQ.AI is not a CLM; MCP path (M5+) is the integration story. |
| 12.2 | DE-041 — E-discovery capabilities | [DE-041](PRD.md#de-041--e-discovery-capabilities) | Different domain; outside the in-house-counsel value prop. |
| 12.3 | DE-042 — Mobile applications | [DE-042](PRD.md#de-042--mobile-applications) | PWA path via the web app for v1–v4. |
| 12.4 | DE-013 — Saved Prompts Library | [DE-013](PRD.md#de-013--saved-prompts-library) | Shipped in M1 — confirm before claiming. |
| 12.5 | DE-289 — Lavern as design reference for the Autonomous Layer / full-path ensemble / MCP catalog | [DE-289](PRD.md#de-289--lavern-as-design-reference-for-the-autonomous-layer-full-path-ensemble-and-mcp-catalog) | Design reference, not an implementation item. |
| 12.6 | DE-290 — Boundary-registers posture document | [DE-290](PRD.md#de-290--boundary-registers-posture-document--shipped-with-this-pr) | Shipped. |
| 12.7 | DE-267 — Azure OpenAI provider adapter | [DE-267](PRD.md#de-267--azure-openai-provider-adapter--closed-in-m2-e1-2026-05-17) | Shipped in M2-E1. |

---

## How to claim work

1. Find an item that matches your skills and bandwidth using the labels above.
2. Open a GitHub issue with the item ID (e.g., "DE-103" or "1.3 Contract Repository") as the title.
3. Comment "I'd like to take this." A maintainer responds within ~7 days.
4. Follow the source mini-PRD (where one exists) or the PRD §9 entry for scope + acceptance criteria.
5. Engineering process: [`CONTRIBUTING.md`](../CONTRIBUTING.md). Skill content: [`skills/CONTRIBUTING.md`](../skills/CONTRIBUTING.md) — the practicing-attorney attestation applies.

For larger items (XL, or anything tagged "Senior, Architectural"), open a discussion first so the maintainer team can confirm fit and resolve any open design questions in writing before you spend a weekend.

---

## How this doc is maintained

This document is regenerated against the source-of-truth docs (PRD §8, PRD §9, HONEST-STATE, the milestone plans) when items ship or when new gaps are identified. The expectation is **a refresh per release** (and when a community PR closes a row, the row moves out and a maintainer updates this doc as part of the PR).

If a row in this doc is wrong — the item shipped, the scope changed, the labels are off — the source document is canonical. Open an issue or, even better, a PR fixing this doc alongside the source update.

**Last regenerated:** 2026-05-29.

**Source-of-truth documents:**

- [`docs/PRD.md` §8 Roadmap](PRD.md#8-roadmap)
- [`docs/PRD.md` §9 Deferred Enhancements](PRD.md#9-deferred-enhancements-and-identified-future-work)
- [`docs/HONEST-STATE.md`](HONEST-STATE.md)
- [`docs/M3-IMPLEMENTATION-PLAN.md`](M3-IMPLEMENTATION-PLAN.md)
- [`docs/M4-IMPLEMENTATION-PLAN.md`](M4-IMPLEMENTATION-PLAN.md)
- [`docs/contribute/EASIEST-CONTRIBUTIONS.md`](contribute/EASIEST-CONTRIBUTIONS.md)
