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
