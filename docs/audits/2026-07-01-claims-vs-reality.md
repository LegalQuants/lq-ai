# Claims-vs-reality audit — Direction A (docs → code verdicts)

> Part of DE-365 sub-project 1 (docs-only honesty audit). This worksheet is Direction A:
> every existing capability/status claim in `README.md`, `docs/HONEST-STATE.md`, and
> `docs/ROADMAP.md`, checked against the code that is actually in the tree today, with a
> verdict and a concrete resolution. Direction B (capabilities the code has that the docs
> don't mention yet — principally the fiduciary-grade milestone, ADRs 0018–0021) is a
> separate task; where a row below is **Stale** because of that milestone, the resolution
> says "resolved by Direction-B additions" rather than drafting new prose here.
>
> Verdict legend: **Accurate** / **Overstated** (claims more than the code does) /
> **Understated** (the code does more, or a shipped thing is filed under roadmap) /
> **Stale** (the framing is outdated, usually because a newer milestone superseded it).
>
> Pinned facts verified while building this worksheet (2026-07-01, branch
> `feat/de365-sub1-docs-honesty-audit`): latest migration = `0064` (confirmed —
> `api/alembic/versions/0064_authority_citations_and_text_cache.py`); `SOURCE_REGISTRY`
> = `govinfo` / `edgar` / `eurlex` (confirmed — `api/app/research/registry.py`); ADRs
> 0018 (citation ledger + fiduciary gate), 0019 (transparent validity/treatment layer),
> 0020 (governed agentic legal-matter sessions), 0021 (content source registry) all
> exist and are Accepted; open DEs 370/371/374/375/376 confirmed in `docs/PRD.md`.
> **None of README.md, docs/HONEST-STATE.md, or docs/ROADMAP.md mention the
> fiduciary-grade milestone or ADRs 0018–0021 anywhere** (`grep -n -i "fiduciary"` across
> all three returns nothing) — this is the single biggest finding of this pass and is
> called out on every row it touches.

## Link-check helper output (Step 2)

`docs/audits/check_doc_links.py` was run against all three audited docs:

```
$ python3 docs/audits/check_doc_links.py README.md
DANGLING: README.md: docs/playbook-authoring-guide.md -> /Users/kevinkeller/Code/lq-ai/docs/playbook-authoring-guide.md
DANGLING: README.md: docs/deployment-cookbook.md -> /Users/kevinkeller/Code/lq-ai/docs/deployment-cookbook.md
FAIL: 2 dangling link(s)

$ python3 docs/audits/check_doc_links.py docs/HONEST-STATE.md docs/ROADMAP.md
OK: 0 dangling link(s)
```

**Pre-existing finding (not fixed here, per task scope):** README.md links to
`docs/playbook-authoring-guide.md` (in the "Documentation" list) and
`docs/deployment-cookbook.md` (same list) — neither file exists in the repo. These are
unrelated to the fiduciary-grade staleness finding; they are captured as rows 39–40
below for Tasks 3–5 to resolve (write the doc or drop the link) rather than fixed here.

---

## Direction-A table — `README.md`

| claim | where | artifact | verdict | resolution |
|---|---|---|---|---|
| 1. Citation Engine: character-verifiable citations, four-stage cascade (exact → tolerant → paraphrase judge → ensemble) | README "What it does" / Citation Engine (M2) | `api/app/citation/verification.py` (all four stage functions present); `docs/citation-engine.md` | Accurate | attach proving link (already linked) — no change |
| 2. Anonymization Layer: Presidio + spaCy + custom `CaseNumberRecognizer`/`MatterNumberRecognizer`, streaming-aware rehydration, privileged-project skip, retrieval-context skip | README "What it does" / Anonymization Layer (M2) | `gateway/app/anonymization/middleware.py`, `gateway/app/anonymization/engine.py`; `docs/security/anonymization.md` | Accurate | no change |
| 3. Projects: matter-scoped containers with attached files/skills/context, `privileged: true` flag forcing tier floor | README "What it does" / Projects | `api/app/api/projects.py`; `gateway/app/tier_floor.py` | Accurate | no change |
| 4. Organization Profile: singleton skill capturing org voice/jurisdiction/standards | README "What it does" / Organization Profile | `api/app/api/organization_profile.py`, `api/app/models/organization_profile.py` | Accurate | attach proving link — no change |
| 5. Inference Tier Awareness + tier-floor enforcement (403 `tier_below_minimum`) | README "What it does" / Inference Tier Awareness | `gateway/app/tier_floor.py` | Accurate | no change |
| 6. Audit log: append-only `audit_log`, admin-gated `GET /admin/audit-log`, cross-references gateway `inference_routing_log` via `request_id` | README "What it does" / Audit log | `api/app/audit.py` | Accurate | no change |
| 7. Files/Knowledge Bases: hybrid vector + FTS retrieval, Docling + PyMuPDF ingestion, OCR not yet implemented (DE-320) | README "What it does" / Files / Knowledge Bases | `api/app/pipeline/parsers.py`, `api/app/workers/document_pipeline.py` | Accurate | no change — the DE-320 caveat is itself honest and current |
| 8. Playbooks (M3, shipped): LangGraph executor + Easy Playbook wizard, 5 built-in playbooks seeded | README "What it does" / Playbooks | `api/app/api/playbooks.py`; migrations `0031`/`0032`/`0033`/`0035`; `docs/playbooks.md` | Accurate | no change |
| 9. Word Add-In (M3, plumbing shipped): installable, authenticated scaffold; substantive in-pane feature surface deferred (DE-287) | README "What it does" / Word Add-In | `word-addin/manifest.xml`, `word-addin/src/taskpane/`; `docs/word-addin.md` | Accurate | no change — matches HONEST-STATE §4.3 exactly |
| 10. Tabular / Multi-Document Review (M3, shipped): row-per-document grid, per-cell citations navigable, per-column ensemble honored | README "What it does" / Tabular Review | `api/app/api/tabular.py`; `docs/tabular-review.md` | Accurate | no change |
| 11. Slack / Teams Light Intake Bridge (M3, plumbing shipped): OAuth install + admin surface; `/lq` slash-command inert (DE-288); live OAuth round-trip unverified (DE-312) | README "What it does" / Slack/Teams | `slack-bridge/`, `teams-bridge/`; `api/app/api/integrations_slack.py`, `api/app/api/integrations_teams.py` | Accurate | no change — matches HONEST-STATE §4.4 |
| 12. Autonomous Layer (M4, shipped): five-phase executor (intake→analysis→drafting→ethics_review→delivery), `guarded_tool_call` chokepoint, R4/R5/R6 brakes, four primitives | README "What it does" / Autonomous Layer | `api/app/autonomous/executor.py`, `api/app/autonomous/guard.py`; `docs/autonomous-layer.md` | **Understated** | The description is accurate for the M4-close state but does not mention that the analysis phase is no longer a single scripted LLM call — WS-D (ADR 0020, shipped, `api/app/autonomous/planner.py`) replaced it with a governed plan→act→observe→replan loop plus plain-language matter intake, and WS-D PR2 wired the citation ledger + fiduciary gate into autonomous sessions (`api/app/autonomous/ledger_bridge.py`). Resolved by Direction-B additions (new paragraph or amendment to this one). |
| 13. "Legal research + connectors (MCP), gateway-brokered": CourtListener, MCP client, governed tool-loop, case-law provenance | README "What it does" / Legal research + connectors | `gateway/app/providers/tool/courtlistener.py`, `gateway/app/providers/tool/mcp.py`; ADR 0014/0015 | **Understated** | Accurate as far as it goes, but the tool-provider set has grown beyond CourtListener/MCP: `SOURCE_REGISTRY` (`api/app/research/registry.py`) now also carries `govinfo` (US Code/CFR statutes+regs, shipped WS-E PR1a) and `eurlex` (EU legislation/CJEU case law by CELEX, shipped WS-E PR2b) alongside `courtlistener`, plus `edgar` (SEC filings, shipped WS-E PR2a) — a "content source registry" concept (ADR 0021) this paragraph doesn't mention at all. Resolved by Direction-B additions. |
| 14. Contract Repository — Auto-Relationship Detection: "roadmap... Not yet built — there is no `contract_relationships` table" | README "What it does" / Contract Repository | `find api/alembic/versions -iname "*contract_relationship*"` → no results | Accurate | no change — still genuinely unbuilt |
| 15. Forward-looking (M5–M7, community-driven): workflow-aware context layer, Workspace Concierge, agent dispatch | README "What it does" / Forward-looking | `docs/PRD.md` §8.5 | Accurate | no change |
| 16. "Ten starter skills ship with the M1 release" (table lists exactly 10) | README "Starter skills (ship with M1)" | `skills/*/SKILL.md` | **Understated** | `skills/` actually loads 15 built-in `SKILL.md` skills into the registry, not 10: the 10 listed here, plus `case-law-research` (mentioned elsewhere in README/HONEST-STATE as part of the MCP milestone) and four more the README never names anywhere — `contract-snapshot`, `msa-snapshot`, `nda-snapshot` (table-mode reference skills for M3-C), and `playbook-easy-extract` (internal, feeds the Easy Playbook pipeline). Resolution: add a one-line note under the starter-skills table — "5 additional built-in skills also ship in `skills/`: `case-law-research` (legal research) and four table-mode/internal reference skills (`contract-snapshot`, `msa-snapshot`, `nda-snapshot`, `playbook-easy-extract`) — see `skills/*/SKILL.md`." |
| 17. Community skill catalog: "30+ additional skills... 17+ jurisdictions" via `LegalQuants/lq-skills` submodule | README "Community skills" | `.gitmodules` / `skills/community/` submodule pointer | Accurate (not independently re-counted; submodule content is a separate repo, out of this audit's blast radius) | attach proving link — no change |
| 18. "M1 through M4 shipped." (opening sentence of Project status) | README "Project status" prose | ADRs 0001–0015 + all four milestone docs | Accurate | no change |
| 19. "After M4, a gateway-brokered legal-research + connectors (MCP) milestone shipped" — implicitly framed as the **current** shipped state | README "Project status" prose | `docs/HONEST-STATE.md` §5.5; but also ADRs 0018–0021 (fiduciary-grade milestone, merged, postdates the MCP milestone) | **Stale** | The "current shipped" framing stops at the legal-research+MCP milestone and never mentions the fiduciary-grade milestone (citation ledger + fiduciary gate, transparent treatment layer, governed agentic matter sessions, content source registry — ADRs 0018–0021, all merged) that shipped after it. Resolved by Direction-B additions: add a milestone paragraph/row for the fiduciary-grade work and move the "current shipped" pointer forward. |
| 20. Roadmap table rows M1–M4 (all "✓ Shipped", with caveats noted for M3) | README "Project status" → Roadmap table | ADRs + migrations for each milestone | Accurate | no change |
| 21. Roadmap table row "Legal research + connectors (MCP)" — "✓ Shipped (after M4)" | README "Project status" → Roadmap table | `docs/HONEST-STATE.md` §5.5 | **Stale** | Accurate as a historical record of that milestone, but the table has no row at all for what shipped *after* it (the fiduciary-grade milestone). Resolution: add a new table row "Fiduciary-grade agentic legal work" (or similar) between this row and the M5–M7 row, status "✓ Shipped" with ADR 0018–0021 links — a Direction-B addition. |
| 22. Roadmap table row "M5–M7 — Forward-Looking Workflow Intelligence... TBD" | README "Project status" → Roadmap table | `docs/PRD.md` §8.5 | Accurate | no change — still correctly the next horizon after the row above gets added |
| 23. "The PRD is at v0.2" (shield badge + prose) | README badge + "Project status" prose | `docs/PRD.md` line 6: `**PRD Version:** 0.2` | Accurate | no change |
| 24. Documentation list: link to `docs/playbook-authoring-guide.md` | README "Documentation" | `test -e docs/playbook-authoring-guide.md` → **fails, file does not exist** | Overstated | Either author the missing guide, or drop the link/rename it to point at the actual authoring reference (`docs/playbooks.md` covers authoring informally today). Pre-existing dangling link, confirmed by the link-check helper (Step 2 above), not caused by this milestone. |
| 25. Documentation list: link to `docs/deployment-cookbook.md` | README "Documentation" | `test -e docs/deployment-cookbook.md` → **fails, file does not exist** | Overstated | Either author the missing cookbook, or drop the link. Pre-existing dangling link, confirmed by the link-check helper. |
| 26. Google Vertex AI / AWS Bedrock adapters "on the deferred-enhancement list (DE-034/DE-035)" | README "Providers and air-gapped deployments" | `gateway/app/providers/` — no `vertex.py` / `bedrock.py`; `docs/PRD.md` DE-034/DE-035 | Accurate | no change |
| 27. "Enabling legal-research connectors" section: CourtListener opt-in via `.env` + `gateway.yaml`, off by default | README "Enabling legal-research connectors" | `gateway.yaml.example`; `api/app/api/research.py` (`/research/capabilities`) | Accurate | no change |

---

## Direction-A table — `docs/HONEST-STATE.md`

| claim | where | artifact | verdict | resolution |
|---|---|---|---|---|
| 28. "**Current as of the legal-research + connectors (MCP) milestone close (#158–#193); migration head `0055`.**" | HONEST-STATE header (line 3) | `api/alembic/versions/` latest file is `0064_authority_citations_and_text_cache.py`, not `0055` | **Stale** | Update the header to the fiduciary-grade milestone close and migration head `0064`. Resolved by Direction-B additions (the header rewrite is the natural home for the new milestone summary). |
| 29. §12 Maintenance note: "Last rewritten at the M4 close... reconciled against... the legal-research + connectors (MCP) milestone (#158–#193; migration head `0055`...)" | HONEST-STATE §12 | Same as row 28 | **Stale** | Same fix as row 28 — append a third reconciliation pass for the fiduciary-grade milestone, migration head `0064`. Resolved by Direction-B additions. |
| 30. §1–§5.5 capability tables (M1–M4 + legal-research/MCP) | HONEST-STATE §1–§5.5 | Verified spot-check: `api/app/api/chats.py`, `api/app/autonomous/guard.py`, `api/app/chat/tool_loop.py`, migrations `0048`–`0055` all exist as cited | Accurate | no change — the per-row verification paths in these sections check out |
| 31. Entire document has **no section** for the fiduciary-grade milestone (citation ledger, fiduciary gate, treatment layer, matter sessions, content source registry) | HONEST-STATE (document-wide) | ADRs 0018/0019/0020/0021; migrations `0058`–`0064`; `api/app/citation/ledger.py`, `api/app/citation/gate.py`, `api/app/citation/treatment.py`, `api/app/autonomous/planner.py`, `api/app/research/registry.py` all exist and are wired | **Understated** (a whole shipped capability set is entirely missing from the "shipped" catalog) | Add a new "§5.6 Fiduciary-grade agentic legal work" section (mirroring the §5.5 structure) cataloging the citation ledger + gate (WS-A/WS-B, ADR 0018), the treatment layer (WS-G, ADR 0019), governed matter sessions (WS-D, ADR 0020), and the content source registry / authority sources govinfo+edgar+eurlex (WS-E, ADR 0021). This is Direction-B's primary deliverable; flagged here so Tasks 3–5 know exactly where the gap is. |
| 32. §1 table row: "Ingest formats — PDF... and plain text/Markdown... DOCX is roadmap." | HONEST-STATE §1 | `api/app/pipeline/parsers.py` line ~61: still raises for DOCX/RTF; no pandoc-based parser found despite ADR 0017 (`docs/adr/0017-docx-ingest-via-pandoc.md`) existing as an accepted proposal | Accurate | no change — ADR 0017 documents a *decision*, not a *build*; the PRD/DE tracking (memory: "DOCX accepted, build pending") confirms this is still correctly roadmap |
| 33. §6 "Capabilities not yet started in source": in-Word feature surfaces, `/lq` slash-command, Contract Repository graph | HONEST-STATE §6 | `word-addin/` tabs are deep-link cards (`word-addin/src/taskpane/`); no `contract_relationships` table | Accurate | no change |
| 34. §5.5 caveats: "Chat-side governed tool calls... do not yet emit a dedicated OTel `chat.tool_call` span (deferred)" | HONEST-STATE §5.5 caveats | Not independently re-verified (OTel instrumentation not in this task's grep pass) | Accurate (as documented; not re-verified) | attach proving link if re-verified in a future pass — no change now |
| 35. §8 Engineering-discipline state: "183 `test_*.py` files in `api/tests/`... 64 in `gateway/tests/`... 76 `*.test.ts`... 17 Cypress specs" | HONEST-STATE §8 | Counts not re-run in this pass (would require `find | wc -l` against current tree, which has grown since #193 per the WS-A–WS-G/WS-D/WS-E commits) | **Stale** (counts are almost certainly higher now, given ~9 more migrations and multiple new subsystems since the doc's stated baseline) | Re-run `find api/tests -name 'test_*.py' | wc -l` etc. and update the four counts as part of the same Direction-B rewrite (row 31); do not hand-edit without re-running the counts. |

---

## Direction-A table — `docs/ROADMAP.md`

| claim | where | artifact | verdict | resolution |
|---|---|---|---|---|
| 36. "**Last regenerated:** 2026-05-29." | ROADMAP.md "How this doc is maintained" | Git log shows WS-A through WS-G, WS-D, and WS-E (PR1a–PR2b) all merged after this date (commits `b08e178` 2026-06-26 onward through `c138ed0` today) | **Stale** | Regenerate the date and re-derive §1 "Active milestone work" against the fiduciary-grade milestone's actual remaining items (see row 37) rather than the stale M4 close-out framing. Resolved by Direction-B additions / a Task 3–5 edit pass, not drafted here. |
| 37. §1.1 "Wire real in-loop agentic work into the executor... Design landed; implementation in progress on the active feature branch. Replaces the placeholder loop..." | ROADMAP.md §1 "Active milestone work — M4 close-out" | `api/app/autonomous/planner.py` (WS-D PR1, commit `c7a493e feat(autonomous): governed plan-act-observe-replan loop in the analysis phase`) — the plan→act→observe→replan loop **has shipped**, not "in progress" | **Stale** | Remove or mark this row done; it describes exactly what WS-D (ADR 0020) shipped. Resolution: strike §1.1 from the open punch list (or move it to a "recently shipped" note) once Direction-B documents WS-D. |
| 38. §1 heading frames the active milestone as "M4 close-out" with no mention of the fiduciary-grade milestone (WS-A through WS-G, WS-D, WS-E) that is now largely shipped and partially still in flight (WS-E PR2c+/DE-374 etc.) | ROADMAP.md §1 header/intro | ADRs 0018–0021; `docs/proposals/fiduciary-grade-agentic-legal-work.md`; open DEs 370/371/374/375/376 in `docs/PRD.md` | **Stale** | Replace the §1 header and its items with the fiduciary-grade milestone's actual remaining open items (DE-370, DE-371, DE-374, DE-375, DE-376 per `docs/PRD.md`, all confirmed still open) — a Direction-B/Task-3-5 rewrite, not performed here. |
| 39. §1.3 "Contract Repository — Auto-Relationship Detection (M4)... Not yet started in source" | ROADMAP.md §1.3 | No `contract_relationships` table in `api/alembic/versions/` | Accurate | no change — still genuinely open and correctly labeled |
| 40. §11.1 "DE-200 — MCP-client subsystem in the LQ.AI backend... Architectural slot scheduled for M2; full operationalization is M5" (listed under "Forward-looking — M5+ Workflow Intelligence, not committed") | ROADMAP.md §11.1 | `docs/HONEST-STATE.md` §5.5 itself states "MCP client subsystem — gateway adapter... shipped"; `gateway/app/providers/tool/mcp.py` exists and is tested | **Overstated** (in the "not yet done" direction — i.e. the roadmap overstates how *undone* this is; effectively a Stale/Understated-elsewhere item) | The MCP client subsystem already shipped (legal-research+MCP milestone, pre-dating this ROADMAP entry's "M5" framing) — remove DE-200 from the forward-looking section or re-scope it to name only what's genuinely still open (individual MCP *connectors* — email/calendar/task/CRM/doc-store, DE-202–DE-206 — which are correctly still unbuilt). This is a pre-existing inconsistency, not caused by the fiduciary-grade milestone, but caught in this pass. |

---

## Summary

- **40 rows** across the three documents.
- Verdict distribution: **25 Accurate**, **8 Stale**, **4 Understated**, **3 Overstated**.
- The dominant finding, by design of this task, is staleness: none of the three docs
  mention the fiduciary-grade milestone (ADRs 0018–0021) anywhere, even though all four
  ADRs are Accepted and their implementations (citation ledger, fiduciary gate,
  treatment layer, governed matter sessions, content source registry with
  govinfo/edgar/eurlex) are in `main` as of migration `0064`. Every row marked
  **Stale** or **Understated** that says "resolved by Direction-B additions" is
  intentionally *not* resolved in this worksheet — that is the next task's job. This
  worksheet's job was to locate and verdict every existing claim; Tasks 3–5 consume the
  `resolution` column as their edit list once Direction B supplies the new-capability
  prose to insert alongside these fixes.
- Two rows (24, 25) are pre-existing dangling links unrelated to milestone staleness,
  surfaced by the link-check helper exactly as the brief anticipated.

---

## Direction B — code→docs (shipped-but-undocumented)

> Direction B works the opposite direction from Direction A: instead of checking existing
> doc claims against code, it enumerates what the code (and the ADRs that govern it)
> actually ships, and records the anchor artifact, an honest caveat, and where each
> capability belongs in the docs. This is the fiduciary-grade milestone (ADRs 0018–0021,
> all `Status: Accepted`, all merged to `main` as of migration `0064`) that Direction A's
> row 19/31/37/38 findings identified as entirely absent from README/HONEST-STATE/ROADMAP.
> Read in full for this pass: `docs/adr/0018-citation-ledger-and-fiduciary-grade-output.md`,
> `docs/adr/0019-transparent-validity-treatment-layer.md`,
> `docs/adr/0020-governed-agentic-legal-matter-sessions.md`,
> `docs/adr/0021-content-source-registry-and-free-source-expansion.md`,
> `api/app/research/registry.py`, `api/app/citation/ledger.py`, `api/app/citation/gate.py`,
> `api/app/citation/treatment.py`, `api/app/citation/authority.py`,
> `api/app/tools/governance.py`, and the open-DE entries in `docs/PRD.md` §9.
>
> Every anchor below was independently verified to exist (`test -e`, or a direct `grep`
> for the named symbol) before being cited — see the verification notes under each row
> group and in the task report. No capability row is asserted from the ADR text alone
> without a matching code artifact.

| capability | anchor | honest caveat | add-to |
|---|---|---|---|
| Citation Ledger | ADR 0018; `api/app/citation/ledger.py` | references content by id/offset only — no raw payloads in the audit layer (P3, ADR 0016) | README narrative + status; HONEST-STATE |
| Fiduciary-grade gate | ADR 0018; `api/app/citation/gate.py` | chat vs autonomous parity gaps: DE-370, DE-371 still open | README narrative + status; HONEST-STATE |
| Governed agentic matter sessions | ADR 0020; PRs #239/#240 | on the autonomous layer under R5→R6→R4 brakes; no dedicated matter-intake UI yet | README status/roadmap; HONEST-STATE (UI gap) |
| Content-source registry + free authority sources | ADR 0021; `SOURCE_REGISTRY` | behind operator config; EUR-Lex get-by-CELEX only (search=DE-374; treaty=DE-375) | README narrative + status; ROADMAP |
| Validity / treatment layer | ADR 0019; `api/app/citation/treatment.py` | "derived, not editorial," not an authoritative citator; per-case judge budget | README narrative + status; HONEST-STATE |
| Governed egress cost model | DE-344; `api/app/tools/governance.py` | configured per-call rate, not response-parsed; fails-open on gateway-config failure | README status |

### Verification notes (Step 1 detail)

- **Citation Ledger.** ADR 0018 is `Status: Accepted (2026-06-24)`. `api/app/citation/ledger.py`
  exists and implements `assemble_ledger_entries`/`resolve_ledger_entries`; ADR 0018 D5 pins
  the no-raw-payload guarantee ("ids, offsets, status labels, confidence numbers, provenance
  metadata, and timestamps — never raw passages or tool payloads") and states the ledger is
  added to the `test_transparency_invariants.py` no-raw-payload tripwire — matches the row's
  caveat exactly.
- **Fiduciary-grade gate.** `api/app/citation/gate.py` exists; `compute_and_record_gate` buckets
  ledger entries into `PASS_STATUSES`/`FAIL_STATUSES` and upserts one
  `WorkProductFiduciaryGate` verdict per assistant message (ADR 0018 D3). `docs/PRD.md`
  confirms DE-370 ("Attributed-authority FAIL tier (chat)") and DE-371 ("Autonomous-path
  authority SUPPORTED tier") are both still open (listed under the un-shipped
  deferred-enhancements section, no SHIPPED marker on either DE header) — the chat/autonomous
  parity gap is real and current.
- **Governed agentic matter sessions.** ADR 0020 is `Status: Accepted (2026-06-28)`; D1–D2 pin
  the governed `plan → act → observe → replan` loop confined to the `analysis` phase under the
  existing R5→R6→R4 brakes (`guarded_tool_call`, unchanged). `web/src/routes/lq-ai/autonomous/`
  ships session list/detail, schedules, watches, and a `configure/` page, but no
  plain-language "describe your matter" intake flow was found (`grep -rn "matter.intake\|
  MatterIntake" web/src` → no matches) — ADR 0020 D3's plain-language intake is a backend
  seam (`query` on session state feeding the `intake` phase), not yet a dedicated UI
  affordance. The caveat is accurate.
- **Content-source registry + free authority sources.** `api/app/research/registry.py`
  `SOURCE_REGISTRY` has four keys: `courtlistener` (pre-existing), `govinfo`, `edgar`, `eurlex`
  (WS-E PR1a/PR2a/PR2b). The `eurlex` entry's `ops=("get_authority",)` only — no
  `search_authority` — confirming get-by-CELEX-only; `docs/PRD.md` DE-374 ("EUR-Lex full-text
  search via Cellar SPARQL") and DE-375 ("EUR-Lex treaty/corrigendum CELEX support") are both
  open, matching the caveat verbatim. Every source in the registry additionally requires an
  operator-configured `tool_providers` entry in `gateway.yaml` (ADR 0021 D1/D5) — "behind
  operator config" is accurate, not merely a formality (a registry entry with no matching
  gateway provider is reported unavailable, never fabricated).
- **Validity / treatment layer.** ADR 0019 is `Status: Accepted (2026-06-26)`; D1 states the
  binding posture verbatim: "It never emits a definitive 'good law / bad law' verdict. Every
  derived signal is labeled 'derived, not editorial.'" `api/app/citation/treatment.py` exists
  and implements `derive_treatment_for_message`/`_run_judge_pass`, reading citing opinions via
  `research_service.get_citing_opinions` (itself confirmed live in
  `api/app/research/service.py` and `gateway/app/providers/tool/courtlistener.py`). ADR 0019 D4
  ("WS-G PR2 ... a hard cap N, bounded by a per-case cost budget") confirms the per-case judge
  budget caveat.
- **Governed egress cost model.** `api/app/tools/governance.py` `_load_provider_tier_cache`
  reads `cost_per_call` off each `tool_providers` gateway entry into `_provider_cost_cache`
  (a configured rate, never parsed from a provider's response) and wraps the entire fetch in
  `try/except Exception` — on failure it logs a warning and leaves the cost/tier caches empty,
  so cost lookups silently fall back to their defaults (`Decimal("0")` per the module's own
  comment) rather than blocking egress. That is "fails-open on gateway-config failure" exactly.

### Additional capabilities considered and not added as separate rows

Two capabilities surfaced during Step 1 reading that overlap the six above closely enough that
a separate row would duplicate rather than add information; noted here so Tasks 3–5 know they
were considered:

- **One-click citation trace read model** (ADR 0018 D4) — `GET /api/v1/chats/{chat_id}/ledger`
  exists (`api/app/api/chats.py:1796`; also `GET /api/v1/autonomous/sessions/{session_id}/ledger`,
  `api/app/api/autonomous.py:660`) and is documented in `docs/api/backend-openapi.yaml`. This is
  folded into the **Citation Ledger** row above rather than broken out, since it is the ledger's
  read surface, not a distinct capability.
- **`get_citing_opinions` citing-graph egress operation** (ADR 0019 D3) — confirmed live in
  `gateway/app/providers/tool/courtlistener.py` and wired through
  `api/app/research/service.py`. Folded into the **Validity / treatment layer** row above, since
  it is the data source the treatment judge reads, not a user-facing capability of its own.

No further shipped-but-undocumented capabilities beyond the six (plus the two folded items
above) were found in this pass.

### Reconciliation notes

- **Row 19** (README "Project status" prose frames the legal-research+MCP milestone as the
  current shipped state) is resolved by the **Citation Ledger**, **Fiduciary-grade gate**,
  **Governed agentic matter sessions**, **Content-source registry**, and **Validity/treatment
  layer** rows above — Task 3's README edit should add a milestone paragraph naming all four
  ADRs (0018–0021) and move the "current shipped" pointer forward, per row 19's resolution.
- **Row 21** (README roadmap table has no row for what shipped after the MCP milestone) is
  resolved by the same five rows — Task 3 adds one "Fiduciary-grade agentic legal work" table
  row citing ADR 0018–0021, per row 21's resolution text.
- **Row 31** (HONEST-STATE has no section for the fiduciary-grade milestone at all) is resolved
  by all six Direction-B rows together — Task 4's new "§5.6 Fiduciary-grade agentic legal work"
  section should cover each of the six capabilities, carrying forward each row's honest caveat
  verbatim (the DE-370/DE-371 gate parity gap, the no-matter-intake-UI gap, the EUR-Lex
  get-by-CELEX-only scope, the "derived, not editorial" treatment posture, and the fails-open
  cost model) rather than a bare "shipped" claim.
- **Row 28/29** (HONEST-STATE header/§12 pin migration head `0055` and the MCP milestone as the
  last reconciliation pass) are resolved procedurally, not by a specific capability row — Task
  4 updates the header to migration `0064` and adds a third reconciliation pass referencing this
  worksheet.
- **Row 37** (ROADMAP §1.1 describes the plan→act→observe→replan loop as "in progress") is
  resolved by the **Governed agentic matter sessions** row — that loop is exactly ADR 0020's
  D1, shipped, not in progress; Task 5 should strike or mark it done.
- **Row 38** (ROADMAP §1 header frames the active milestone as "M4 close-out" with no mention of
  the fiduciary-grade work) is resolved by all six rows collectively, with the **Content-source
  registry** row's DE-374/DE-375 caveats and the **Fiduciary-grade gate** row's DE-370/DE-371
  caveats supplying the "actual remaining open items" row 38 asks for — Task 5's rewrite should
  list DE-370, DE-371, DE-374, DE-375, DE-376 explicitly (all confirmed open, see Step 1 grep
  below) as the milestone's genuine punch list, not a generic "M4 close-out" placeholder.
- **No contradictions found.** Every Direction-A row that deferred to "Direction-B additions"
  is fully covered by at least one Direction-B row above; no Direction-B row above conflicts
  with a Direction-A "Accurate" verdict (the six new capabilities are additions to the docs,
  not corrections of existing accurate claims).
- **Open-DE confirmation (re-verified for this section):** `grep -n "DE-37[0-6]" docs/PRD.md`
  returns DE-370 through DE-376 with no SHIPPED marker on any of DE-370, DE-371, DE-374,
  DE-375, or DE-376 (DE-372 and DE-373 are also open but were not part of the six-capability
  caveats above; DE-344 itself is SHIPPED, which is why it anchors the **Governed egress cost
  model** row rather than appearing as an open caveat).

### Link-check helper (Direction-B pass)

```
$ python3 docs/audits/check_doc_links.py docs/audits/2026-07-01-claims-vs-reality.md
OK: 0 dangling link(s)
```
