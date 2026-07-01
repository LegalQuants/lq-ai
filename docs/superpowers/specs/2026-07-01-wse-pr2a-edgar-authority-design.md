# WS-E PR2a — SEC EDGAR authority source (+ chat authority wiring generalization)

> **Status:** Design (approved 2026-07-01). Milestone: Fiduciary-grade agentic legal work → Phase 2 → WS-E (content-source registry + free-source expansion).
> **Anchor ADR:** [ADR 0021 — Content-source registry & free-source expansion](../../adr/0021-content-source-registry-and-free-source-expansion.md), decision **D6** (phasing). **No new ADR or amendment required** — EDGAR is explicitly in-plan for WS-E PR2.
> **Predecessors:** WS-E PR1a (#245, registry + GovInfo + `retrieve_authority` + DE-344 cost), PR1b (#246, authority verify + ledger, mig 0064), PR1c (#251, chat authority consumer). This PR reuses **all** of that substrate.

## 1. Summary

Add **SEC EDGAR** as the second free authoritative research source (GovInfo is the first; CourtListener is caselaw), on the same registry + `retrieve_authority` intent + mirror-the-caselaw verify path. EDGAR company filings (10-K, 8-K, S-1, …) become searchable and quote-verifiable in **both** autonomous matter sessions and chat.

Because the autonomous authority path is already registry-driven, EDGAR lights up there almost for free once registered. The substantive new work is: the **gateway EDGAR adapter**, the **backend adapter + registry entry**, **generalizing the chat authority wiring** from GovInfo-hardcoded to registry-driven (so EDGAR — and later EUR-Lex — work in chat), and **extending the verify content-kind set** (DE-371).

This is **PR2a** of a two-source split: **PR2b** adds EUR-Lex on the clean generic base and will require essentially zero new chat wiring.

### Non-goals (PR2a)
- EUR-Lex (→ PR2b).
- Jurisdiction-aware planner routing (ADR 0021 open item; stays deferred unless separately pulled in).
- Per-form-type EDGAR content-kind taxonomy (single `sec_filing` kind; DE if ever needed).
- Any new migration, new route, new brake machinery, or change to `gate.py` / `ledger.py`.
- Metered-source R4 exercise — EDGAR is free (no `cost_per_call`), so R4 stays a correct no-op (DE-344 unchanged).

## 2. Constraints & invariants (must hold)

- **No new ADR** (ADR 0021 D6). **No migration** — reuses `message_authority_citations` + `authority_text_cache` (mig 0064); `content_kind` is free Text (no DB CHECK), so a new kind needs no schema change.
- **`gate.py`, `ledger.py`, and `alembic/` remain untouched** (provable via `git diff --name-only`).
- **Reuse / never bypass** (ADR 0021 D7): every EDGAR call goes through `guarded_tool_call` → R5/R6/R4 → `governed_tool_invocation` → gateway. No new egress path or verifier.
- **Conservative posture:** honest `coverage` string (D5, no overclaiming); an unmatched quote is dropped, never asserted; a content kind outside the verifiable set is silently not verified (no false claim), which is why we must add `sec_filing` to that set.
- **Chat generalization is behavior-preserving for GovInfo** — GovInfo becomes `source:"govinfo"` under the generalized tools; its existing behavior and tests must stay green.
- **Security-gated** (citation surface + governed egress + touches shipped chat code) → Kevin/security merges, no self-merge, mirror `origin`→`tucuxi` after.

## 3. Architecture — automatic vs. built

| Concern | Status in PR2a |
|---|---|
| Autonomous planner source list + prompt | **Automatic** — `build_planner_messages` injects enabled sources from `resolve_available_sources`. |
| Autonomous `guard._resolve_external_call` / `_handle_retrieve_authority` | **Automatic** — registry-driven; normalizes via `spec.adapter.from_response`, writes the TTL cache. |
| `estimate_tool_cost` / R4 / provider-cost caches | **Automatic** — free source → `Decimal("0")` → R4 no-op. |
| `resolve_available_sources` / `GET /research/sources` | **Automatic** — generic; EDGAR appears when configured. |
| Ledger entry construction | **Automatic** — `content_kind` flows through to `CitationLedgerEntry.source_kind`. |
| **Gateway adapter** (transport, ops, auth, SSRF) | **BUILD** (§4). |
| **Backend adapter + registry entry** | **BUILD** (§5). |
| **Chat authority wiring** (tool schemas + dispatch) | **BUILD — generalize** (§6). |
| **Verify content-kind set** (DE-371) + autonomous content_kind carry-through | **BUILD** (§7). |
| **`gateway.yaml.example`** provider block | **BUILD** (§8). |

## 4. Gateway — `EdgarToolAdapter`

Mirror `gateway/app/providers/tool/govinfo.py`.

- **Provider type:** add `"edgar"` to `ToolProviderType` (`gateway/app/config.py`).
- **New module** `gateway/app/providers/tool/edgar.py`, class `EdgarToolAdapter(ToolProviderAdapter)`:
  - `from_config(provider)` — guards `provider.type == "edgar"`. **Auth delta from GovInfo: no API key.** SEC's fair-access policy requires a descriptive `User-Agent` (e.g. `"AcmeLegal admin@acme.example"`). Resolve a `user_agent` value from the provider config; `from_config` must **not** require `api_key_env`/`api_key_encrypted`.
  - `validate_base_url` / `_request` — `validate_egress_target(url, allowlist)` on **every** call (SSRF). Set the `User-Agent` header on every request. Map upstream 401/403 → auth error, 429 → rate-limit, 4xx → invalid-request, 5xx → HTTP error.
  - `list_tools` — declare the two ops as `ToolSpec` with JSON-schema `parameters`, `read_only=True`.
  - `invoke_tool` — dispatch `search_authority` / `get_authority`.
  - `_search_authority` — EDGAR full-text search (host `efts.sec.gov`). Normalize to `{results: [{external_ref, form_type, company, filed_date, title}], count}`.
  - `_get_authority` — fetch the specific filing document text (host `www.sec.gov`, `/Archives/edgar/...`). Normalize to `{external_ref, title, url, text, content_kind: "sec_filing"}`.
  - `_result` — `ToolResult(..., skip_anonymization=True)` (public filing text must reach the verifier verbatim, ADR 0014 D5).
- **SSRF allowlist:** `[efts.sec.gov, www.sec.gov]`.
- **Registration:** export in `gateway/app/providers/tool/__init__.py`; add an `elif provider.type == "edgar"` branch (+ import) to `build_tool_adapter` in `gateway/app/main.py`.

> **⚠️ Live-shape verification (impl step, not a design unknown):** the exact EFTS query params and the accession-number → primary-document path are confirmed against the live EDGAR API during implementation — the same way PR1a verified GovInfo's `POST /search` + `GET /packages/{id}/summary`→`download.txtLink`. The verified request/response shapes get pinned into the implementation plan and the adapter tests mock those exact shapes.

### EDGAR endpoint notes (to verify-live and pin in the plan)
- Full-text search: `efts.sec.gov/LATEST/search-index?q=...` (JSON hits carry accession + document ids). Map a hit's identifier → `external_ref`.
- Filing document: `www.sec.gov/Archives/edgar/data/{cik}/{accession-no-dashes}/{primary_doc}` → HTML/text. The adapter extracts plaintext for the citable body (EDGAR primary docs are HTML; strip to text for verbatim offset matching).
- No key; descriptive `User-Agent` required; SEC requests ≤ 10 req/s (respect `rate_limit.requests_per_minute`).

## 5. Backend — registry entry + `EdgarAdapter`

- **`SOURCE_REGISTRY["edgar"]`** (`api/app/research/registry.py`):
  ```python
  "edgar": SourceSpec(
      type="edgar",
      jurisdiction="us-federal",
      coverage="U.S. SEC EDGAR company filings (10-K, 8-K, S-1, etc.) — full-text search + retrieval",
      content_kinds=("sec_filing",),
      ops=("search_authority", "get_authority"),
      adapter=EdgarAdapter(),
  )
  ```
- **`EdgarAdapter`** (`api/app/research/adapters.py`) implements `from_response(op, payload) -> FetchedAuthority`:
  - `get_authority` → `FetchedAuthority(citable_text=payload["text"], label=<company + form type>, subtitle=<form + filed date>, url=payload["url"], external_ref=payload["external_ref"], content_kind="sec_filing")`.
  - `search_authority` → `FetchedAuthority` per hit with `citable_text` = the title/snippet (search results are not quotable bodies; only `get_authority` yields a verifiable body — same contract as GovInfo).
  - `label`/`subtitle`/`url` matter — the ledger renders them.
- **Content-kind decision:** single `"sec_filing"`. Form type (10-K/8-K/…) is carried in `label`/`subtitle`, not the content kind. Rationale: conservative, YAGNI; the fiduciary value is "this quote appears in that filing," which one kind captures.

## 6. Chat authority wiring — generalize to registry-driven

**Problem (from PR1a/PR1c):** the chat path hardcodes GovInfo in two places, so a second source can't appear in chat:
- `api/app/chat/tool_schemas.py` — `AUTHORITY_TOOL_SCHEMAS`/`AUTHORITY_OPS` are GovInfo-specific; `assemble_allowlist` hardcodes `type == "govinfo"` / `provider="govinfo"`.
- `api/app/chat/tool_loop.py` — `_dispatch_authority` hardcodes `GovInfoAdapter()`.

**Chosen approach (a): one pair of tools with a `source` argument.**
- Generalize the chat authority tools to `search_authority(source, query)` / `get_authority(source, ref)`, where **`source` is an enum built from the enabled authority sources in the registry** (those whose `SourceSpec.ops` include the authority ops). This mirrors the autonomous intent shape `retrieve_authority(source, op, args)` and scales to N sources with a single schema.
- `assemble_allowlist` iterates enabled authority sources from the registry instead of hardcoding `govinfo`; the tool schema's `source` enum is populated from that set (so a source only appears when configured + registered).
- `_dispatch_authority` resolves the adapter via `SOURCE_REGISTRY[source].adapter` instead of `GovInfoAdapter()`, and threads `source` through to `retrieve_authority`.
- **Rejected (b):** per-source tool names (`search_edgar`, …) — tool sprawl, more model confusion, doesn't scale.

**Behavior-preservation:** with only GovInfo configured, the generalized tools expose `source:"govinfo"` and behave exactly as today. Existing GovInfo chat tests must stay green; add tests for the multi-source case and the `source` enum.

## 7. Verify wiring (DE-371) + autonomous content-kind carry-through

- Extend the verifiable set in `api/app/citation/authority.py`:
  ```python
  _VERIFIABLE_CONTENT_KINDS = {"statute", "regulation", "sec_filing"}
  ```
  Without this, EDGAR quotes are silently dropped (no `MessageAuthorityCitation`, no ledger entry, nothing to the gate) — a conservative under-citation, not a crash, but wrong for PR2a.
- **Autonomous carry-through:** confirm `api/app/autonomous/ledger_bridge.build_authority_citations` uses the adapter/evidence `content_kind` rather than defaulting to `"statute"` (recon flagged a default around line 521). If it defaults, thread the real `content_kind` through so EDGAR autonomous citations are labeled `sec_filing`, not `statute`. Regression-test this.
- content_kind flow (unchanged shape): adapter `FetchedAuthority.content_kind` → `data["authority"]["content_kind"]` → `ToolSourceRecord.source_kind` → verify filter → `MessageAuthorityCitation.content_kind` → `CitationLedgerEntry.source_kind` + `_resolve_source` block `kind`.

## 8. Config / feature-flag posture

The "feature flag" is the existing D5 mechanism — **EDGAR is off unless the operator configures it.** Add a commented `edgar-prod` block to `gateway.yaml.example`:
```yaml
#   - name: edgar-prod
#     type: edgar                  # shipped in WS-E PR2a; uncomment to enable
#     base_url: https://efts.sec.gov          # full-text search host; get_authority reaches www.sec.gov
#     user_agent: "YourOrg legal-ops@yourorg.example"   # SEC fair-access policy — REQUIRED, no API key
#     egress_tier: 4               # public filing data (ADR 0014 D4)
#     allowlist:
#       hosts: [efts.sec.gov, www.sec.gov]
#     rate_limit:
#       requests_per_minute: 300   # SEC allows ~10 req/s
#     anonymize_outbound: false    # public filings; skip_anonymization=True on results
#     # (no api_key_env — EDGAR needs only a User-Agent)
#     # (no cost_per_call — free source; R4 stays a no-op)
```
This requires the gateway `ToolProviderConfig` to accept a `user_agent` field (and to allow a provider with neither `api_key_env` nor `api_key_encrypted` for `type: edgar`). Free source → no `cost_per_call` → DE-344 cost model unchanged.

## 9. Testing & gates

Mirror PR1a/1b/1c coverage:
- **Gateway:** `EdgarToolAdapter` unit tests with mocked live shapes (search + get, User-Agent header set, SSRF rejection of a non-allowlisted host, auth/rate/4xx/5xx mapping), `read_only` and `skip_anonymization` assertions.
- **Backend:** `EdgarAdapter.from_response` (get → quotable body + `sec_filing`; search → title-only body); registry test (EDGAR present with `enabled` reflecting gateway config; excluded when unconfigured); `resolve_available_sources` includes EDGAR.
- **Chat:** `tool_schemas`/`assemble_allowlist` generalization — `source` enum built from enabled authority sources; GovInfo-only case unchanged; multi-source case exposes both; `_dispatch_authority` resolves the right adapter per `source`.
- **Verify:** authority verify with `sec_filing` (verbatim → VERIFIED; whole-body paraphrase judge → SUPPORTED); autonomous `content_kind` carry-through regression.
- **Integration:** finalize wiring produces an EDGAR `MessageAuthorityCitation` + ledger entry (chat) and via `build_authority_citations` (autonomous).
- **No new route** → `test_openapi`/`test_endpoints` path counts unchanged (`/research/sources` already exists; it just lists one more source when configured).
- **Gates (from repo root, CI scope):** full DB-backed SOLO api suite (`DATABASE_URL` set — the real gate, not a skip-hollow-green), `ruff check` + `ruff format --check api scripts` + `mypy app`, and the gateway suite + `mypy --strict` + `ruff format --check gateway`.

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| EDGAR live request/response shapes differ from assumptions | Verify-live during impl (as PR1a did for GovInfo); pin shapes in the plan; adapter tests mock the verified shapes. |
| EDGAR primary docs are large HTML (10-Ks) | Strip to plaintext for offset matching; the paraphrase-judge is bounded by `AUTHORITY_CONTENT_JUDGE_BUDGET_USD`; `authority_text_cache` (30d TTL) bounds refetch. Confirm large-body handling in the plan. |
| Chat generalization regresses shipped GovInfo behavior | Behavior-preserving refactor; existing GovInfo chat tests must stay green; whole-branch Opus review before merge. |
| SEC fair-access blocks a missing/invalid `User-Agent` | `user_agent` is required in the provider block; adapter sends it on every call; document in `gateway.yaml.example`. |

## 11. Delivery

- Build via `superpowers:subagent-driven-development` (per-task implement → spec-compliance review → code-quality review → fix → re-review), then an Opus whole-branch review (has caught a gate-passing defect on every slice this milestone).
- Refresh `.superpowers/sdd/progress.md` Branch/Base lines to this branch before starting Task 1.
- Ship: `git commit -s` + co-author trailer, push `origin` + `tucuxi`, open the security-gated PR, watch CI, Kevin/security merges (no self-merge), mirror `origin`→`tucuxi`, delete the branch.

### Provisional task decomposition (finalized in the plan)
1. Gateway: `type` enum + `user_agent` config field + `EdgarToolAdapter` + registration.
2. Backend: `EdgarAdapter` + `SOURCE_REGISTRY` entry.
3. Chat wiring generalization (`tool_schemas` + `assemble_allowlist` + `_dispatch_authority`), behavior-preserving for GovInfo.
4. Verify content-kind set (DE-371) + autonomous `content_kind` carry-through + regression tests.
5. `gateway.yaml.example` block + docs (PRD WS-E status; mark DE-371 addressed for `sec_filing`).

## 12. DE / follow-ups

- **DE-371** — partially addressed here (adds `sec_filing` to `_VERIFIABLE_CONTENT_KINDS`); EUR-Lex kinds still to be added in PR2b. The autonomous SUPPORTED-tier + dead-`gateway=`-arg portion of DE-371 remains open.
- File a DE if per-form-type EDGAR taxonomy is ever wanted.
- Jurisdiction-aware planner routing stays deferred (ADR 0021 open item).
