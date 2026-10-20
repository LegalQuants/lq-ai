# WS-E PR2b — EUR-Lex authority source

> **Status:** Design (approved 2026-07-01). Milestone: Fiduciary-grade agentic legal work → Phase 2 → WS-E (content-source registry + free-source expansion).
> **Anchor ADR:** [ADR 0021 — Content-source registry & free-source expansion](../../adr/0021-content-source-registry-and-free-source-expansion.md), decision **D6** (phasing) explicitly names EUR-Lex. **No new ADR/amendment.**
> **Predecessors:** WS-E PR1a/PR1b/PR1c (registry + GovInfo + authority verify + chat consumer) and **PR2a (#254, SEC EDGAR)** — which generalized the chat authority wiring to be registry-driven. PR2b reuses all of it.

## 1. Summary

Add **EUR-Lex** (EU legislation + CJEU case law) as the third free authoritative research source, completing WS-E PR2's "≥2 new free sources" (GovInfo + SEC EDGAR + EUR-Lex = three). PR2b is **retrieve-and-verify by CELEX identifier only** (`get_authority`); it reuses the entire registry + `retrieve_authority` + mirror-the-caselaw verify + cache + ledger substrate. Because PR2a made the chat authority wiring registry-driven, EUR-Lex needs **no new chat tool surface** — only registration plus one honest per-op refinement (below).

EU legal documents are fetched from the **Cellar** service (`publications.europa.eu`) via content-negotiation by CELEX id. Auth is a descriptive `User-Agent` (no API key) — the same posture as EDGAR.

### Non-goals (PR2b)
- **Full-text / phrase search** (`search_authority`). EUR-Lex's only free search is the Cellar SPARQL endpoint (structured metadata query, not phrase search) and is a heavier, different beast than EDGAR's REST full-text search → **DE-374**. PR2b ships `ops=("get_authority",)`.
- **Treaty & corrigendum CELEX** whose ids contain `/` or `()` (violating the cache-key charset) → rejected cleanly, deferred to **DE-375**.
- Languages beyond English (default `eng`).
- No new migration, route, ADR, brake, or change to `gate.py`/`ledger.py`/`alembic`.

## 2. Constraints & invariants (must hold)

- **No new ADR** (ADR 0021 D6). **No migration** — reuses `message_authority_citations` + `authority_text_cache` (mig 0064); `content_kind` is free Text (no DB CHECK).
- **`gate.py`, `ledger.py`, `alembic/**` untouched** — provable via `git diff --name-only main..HEAD`.
- **Reuse / never bypass:** every EUR-Lex call goes through `guarded_tool_call` → R5/R6/R4 → `governed_tool_invocation` → gateway. No new egress path or verifier.
- **Honest verification:** a quote verifies only on a real verbatim/paraphrase match against the cached EUR-Lex body; unmatched → dropped, never asserted. `eu_*` content kinds must be in `_VERIFIABLE_CONTENT_KINDS` or quotes silently drop (no false claim, but no citation).
- **Free source:** no `cost_per_call` → `estimate_tool_cost` returns `Decimal("0")` → R4 stays a no-op (DE-344 unchanged).
- **EUR-Lex auth = descriptive `User-Agent`, no API key.** Host allowlist `[publications.europa.eu]`. `skip_anonymization=True` (public EU legal text). `read_only=True`.
- **`external_ref` charset:** the `authority_text_cache` key guard permits only `[A-Za-z0-9._-]`. Plain legislation/caselaw CELEX (`32016R0679`, `62014CJ0362`) satisfy it; an unsafe CELEX (treaty/corrigendum) is rejected at the gateway before any cache/URL use.
- **Security-gated** (gateway egress + citation surface, and a shared-schema touch) → Kevin/security merges, no self-merge; mirror `origin`→`tucuxi` after.

## 3. Architecture — automatic vs. built (post-PR2a)

| Concern | Status in PR2b |
|---|---|
| Chat tool dispatch (`_dispatch_authority` → `SOURCE_REGISTRY[source].adapter`) | **Automatic** — registry-driven since PR2a. |
| Autonomous planner source list, `guard._handle_retrieve_authority`, `_resolve_external_call` | **Automatic** — registry-driven; `guard` validates `op ∈ spec.ops`, so a `search_authority` attempt on EUR-Lex is a non-fatal failed observation. |
| Cost / R4 / availability join / ledger construction / content_kind carry-through | **Automatic** — generic. |
| Durable text cache (`store/load_authority_text`) | **Automatic** — keyed on `(source_type, external_ref)`; only the charset guard constrains us. |
| **Gateway `EurLexToolAdapter`** | **BUILD** (§4). |
| **Backend `EurLexAdapter` + registry entry** | **BUILD** (§5). |
| **Per-op chat tool schemas** (a source appears under an op only if its `ops` include it) | **BUILD — small refinement** (§6). |
| **`_VERIFIABLE_CONTENT_KINDS` += eu_* kinds** | **BUILD** (§7). |
| **`gateway.yaml.example` block + PRD** | **BUILD** (§8). |

## 4. Gateway — `EurLexToolAdapter`

Mirror `gateway/app/providers/tool/edgar.py`.

- **Provider type:** add `"eurlex"` to `ToolProviderType` (`gateway/app/config.py`). Reuse the existing optional `user_agent` field on `ToolProviderConfig` (added for EDGAR).
- **New module** `gateway/app/providers/tool/eurlex.py`, class `EurLexToolAdapter(ToolProviderAdapter)`:
  - `from_config(provider)` — guards `provider.type == "eurlex"`; requires `user_agent`; no API key.
  - `list_tools()` — declares **only** `get_authority` (`read_only=True`), param `external_ref` (a CELEX id).
  - `invoke_tool("get_authority", {"external_ref": celex})` → `_get_authority`.
  - `_get_authority`:
    1. **Validate the CELEX against `^[A-Za-z0-9._-]+$`**; if it contains `/`/`()`/other unsafe chars, raise `ToolProviderInvalidRequestError(upstream_status=400)` with a message noting treaty/corrigendum CELEX are not yet supported (DE-375). This runs *before* any URL build or egress.
    2. `GET https://publications.europa.eu/resource/celex/{CELEX}` with headers `Accept: application/xhtml+xml`, `Accept-Language: eng`, `User-Agent: <configured>`. (Prefer `https`; the recon verified `http` returns 200 — the plan confirms `https` works live before pinning. The SSRF allowlist matches on host, `publications.europa.eu`, regardless of scheme.)
    3. **`follow_redirects=True`** (Cellar 303-redirects to the concrete manifestation) **and re-run `validate_egress_target(str(resp.url), allowlist)` on the final URL** after the redirect chain — SSRF re-check on the resolved target (both are `publications.europa.eu`, but the re-check is required, not optional).
    4. Tag-strip the XHTML to plaintext (reuse EDGAR's `_TAG_RE`/whitespace-collapse pattern).
    5. Return `payload = {"external_ref": celex, "title": <celex or doc title>, "url": <canonical eur-lex url>, "text": <plaintext>, "content_kind": <derived, see §5>}`.
  - `_request`/`_result` mirror EDGAR: SSRF-guard every outbound URL via `validate_egress_target`; map 401/403→Auth, 429→HTTP, 4xx→InvalidRequest, 5xx→HTTP; `_result(..., skip_anonymization=True)`.
- **SSRF allowlist:** `[publications.europa.eu]`.
- **Registration:** export in `gateway/app/providers/tool/__init__.py`; add an `elif provider.type == "eurlex"` branch (+ import) to `build_tool_adapter` in `gateway/app/main.py`.

> **Note (redirect delta):** EDGAR's client uses the httpx default `follow_redirects=False`; EUR-Lex requires following the 303. The redirect target is re-validated against the allowlist — do not follow redirects without the SSRF re-check.

### Verified live facts (2026-07-01, pin in the plan + adapter tests)
- `GET publications.europa.eu/resource/celex/32016R0679` + `Accept: application/xhtml+xml` + `Accept-Language: eng` → **200 `application/xhtml+xml`, ~806 KB** (GDPR), 303→`/cellar/<uuid>/DOC_1`.
- Omitting `Accept-Language` → **404** (mandatory). Nonexistent CELEX → **404** (clean not-found mapping).

## 5. Backend — `EurLexAdapter` + registry entry

- **`EurLexAdapter.from_response(op, payload) -> FetchedAuthority`** (`api/app/research/adapters.py`), mirroring `EdgarAdapter`:
  - `get_authority` → `FetchedAuthority(citable_text=payload["text"], label=<celex + type>, subtitle=<content kind>, url=payload["url"], external_ref=payload["external_ref"], content_kind=payload["content_kind"])`.
- **content_kind derivation from the CELEX descriptor** (a helper, mirroring GovInfo's `_content_kind_from_id`): parse `S YYYY T NNNN`:
  - sector `3` + type `R` → `eu_regulation`; type `L` → `eu_directive`; type `D` → `eu_decision`.
  - sector `6` → `eu_caselaw`.
  - anything else (incl. sectors 1/2 treaties/agreements that slip through) → **`eu_legislation`** (honest fallback).
  The gateway computes this in `_get_authority` and returns it in the payload; the backend adapter carries it through. (Keeping the derivation in the gateway matches how GovInfo/EDGAR set `content_kind` at the adapter that has the raw id.)
- **`SOURCE_REGISTRY["eurlex"]`** (`api/app/research/registry.py`):
  ```python
  "eurlex": SourceSpec(
      type="eurlex",
      jurisdiction="eu",
      coverage="EU legislation & CJEU case law via EUR-Lex/Cellar — retrieve by CELEX id",
      content_kinds=("eu_regulation", "eu_directive", "eu_decision", "eu_caselaw", "eu_legislation"),
      ops=("get_authority",),
      adapter=EurLexAdapter(),
  )
  ```

## 6. Per-op chat tool schemas (honest get-only exposure)

EUR-Lex is the first source with `ops=("get_authority",)` (no `search_authority`). The generic chat schema builder must expose a source under an op **only if its registry `ops` include that op**, so:
- `get_authority`'s `source` enum = {govinfo, edgar, eurlex}
- `search_authority`'s `source` enum = {govinfo, edgar}

Confirm the current `build_authority_tool_schemas`/`assemble_allowlist` behavior (`api/app/chat/tool_schemas.py`): if the `source` enum is currently built once and shared across both tools (assuming every authority source supports both ops), refine it to compute a **per-op** enabled-source list (intersect each op against each spec's `ops`). If a tool ends up with an empty source enum, omit that tool. This is a small, principled generalization — no behavior change for GovInfo/EDGAR (both support both ops). The autonomous path already validates `op ∈ spec.ops` in `guard`, so it needs no change.

## 7. Verify wiring

Extend `_VERIFIABLE_CONTENT_KINDS` (`api/app/citation/authority.py`):
```python
_VERIFIABLE_CONTENT_KINDS = {
    "statute", "regulation", "sec_filing",
    "eu_regulation", "eu_directive", "eu_decision", "eu_caselaw", "eu_legislation",
}
```
Update the adjacent comment (EUR-Lex now covered; DE-375 treaty/corrigendum still pending). Autonomous carry-through is already generic (`ledger_bridge` uses the evidence `content_kind`).

## 8. Config & docs

- **`gateway.yaml.example`** — commented `eurlex-prod` block: `type: eurlex`, `base_url: https://publications.europa.eu` (Cellar, https-preferred; note eur-lex.europa.eu is the HTML fallback, not used), `user_agent` required (no `api_key_env`), `egress_tier: 4`, `allowlist.hosts: [publications.europa.eu]`, `rate_limit.requests_per_minute: 60`, `anonymize_outbound: false`, no `cost_per_call`.
- **`docs/PRD.md`** — WS-E status: EUR-Lex shipped (PR2b), completing WS-E PR2's ≥2-free-sources goal (GovInfo + EDGAR + EUR-Lex); note get-only + English + safe-CELEX scope. File **DE-374** (SPARQL full-text search for EUR-Lex) and **DE-375** (treaty/corrigendum CELEX support).

## 9. Testing & gates

- **Gateway:** `EurLexToolAdapter` unit tests with mocked Cellar responses — get by CELEX (XHTML → tag-stripped body + derived content_kind), `Accept-Language: eng` + `User-Agent` sent, **redirect followed + SSRF re-validated on the final URL**, **unsafe CELEX (`12016E/TXT`, `...R(01)`) rejected with a 400 before egress**, 404→not-found, `skip_anonymization=True`, `read_only=True`, only `get_authority` in `list_tools`.
- **Backend:** `EurLexAdapter.from_response` (get → body + correct content_kind); content_kind derivation per CELEX (`32016R0679`→`eu_regulation`, `32011L0083`→`eu_directive`, a decision→`eu_decision`, `62014CJ0362`→`eu_caselaw`, unknown→`eu_legislation`); registry test (eurlex present with `ops=("get_authority",)`).
- **Chat schema:** per-op source enums — EUR-Lex under `get_authority` only, GovInfo/EDGAR under both; GovInfo/EDGAR behavior unchanged.
- **Verify:** an `eu_regulation` quote against a cached EUR-Lex body → VERIFIED row.
- **No new route** → `test_openapi`/`test_endpoints` counts unchanged; **the DE-373 drift-guard (`test_openapi_export`) stays green** (PR2b adds no route/schema).
- **Gates (repo root):** full DB-backed SOLO api suite (`DATABASE_URL` set — real gate, not skip-hollow-green); `ruff check` + `ruff format --check api scripts`; `mypy app`; gateway suite + `mypy --strict` + `ruff format --check gateway`. Never run concurrent pytest against the shared DB (DE-368).

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| No free phrase search → model must supply a CELEX | Documented get-only scope (DE-374 for SPARQL search); honest tool/coverage descriptions so the model/planner knows it's retrieve-by-CELEX. Well-known instruments (GDPR = `32016R0679`) are citable directly. |
| Cellar 303 redirect + SSRF | `follow_redirects=True` **and** re-validate the final URL against the allowlist; explicit test. |
| CELEX charset (treaty/corrigenda `/`,`()`) | Reject at the gateway with a clear 400 before any cache/URL use; DE-375 for full support; explicit test. |
| Large XHTML bodies (~800 KB) | Tag-strip to plaintext; `authority_text_cache` (30d TTL) bounds refetch; paraphrase judge bounded by `AUTHORITY_CONTENT_JUDGE_BUDGET_USD`. |
| `Accept-Language` mandatory | Always send `eng`; test that omitting would 404 (documents the requirement). |
| Per-op schema change touches shared chat code | Behavior-preserving for GovInfo/EDGAR (both support both ops); covered by tests + Opus whole-branch review. |

## 11. Delivery

- Build via `superpowers:subagent-driven-development` (per-task implement → spec + quality review → fix → re-review), then an Opus whole-branch review.
- Refresh `.superpowers/sdd/progress.md` Branch/Base to this branch before Task 1.
- Ship: `git commit -s` + co-author trailer, push `origin` + `tucuxi`, open the security-gated PR, watch CI, Kevin/security merges (no self-merge), mirror `origin`→`tucuxi`, delete the branch.

### Provisional task decomposition (finalized in the plan)
1. Gateway: `type` enum + `EurLexToolAdapter` (get-by-CELEX, redirect+SSRF, unsafe-CELEX reject, tag-strip) + registration.
2. Backend: `EurLexAdapter` + CELEX→content_kind derivation + `SOURCE_REGISTRY` entry.
3. Per-op chat tool schemas (get-only source exposure), behavior-preserving for GovInfo/EDGAR.
4. Verify content-kind set (eu_* kinds).
5. `gateway.yaml.example` block + PRD (WS-E status; file DE-374, DE-375).

## 12. DE / follow-ups
- **DE-374** — EUR-Lex full-text/phrase `search_authority` via Cellar SPARQL (structured query surface; the harder half deferred from PR2b).
- **DE-375** — treaty/corrigendum CELEX support (reversible `external_ref` encoding for `/`,`()`).
- Multi-language beyond English (Cellar `Accept-Language`) if ever wanted.
