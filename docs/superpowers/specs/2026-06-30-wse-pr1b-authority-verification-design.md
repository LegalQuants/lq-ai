# WS-E PR1b — Fetched-authority verification + ledger-backing (design)

**Status:** Draft for review (2026-06-30). Realizes **DE-369** (durable fetched-authority content provenance — the PR1a deferral, made a tracked mandate) and **ADR 0021 D3** (the 2026-06-29 "mirror-the-caselaw-path" refinement). Security-gated per CODEOWNERS (`api/app/autonomous/**`, `api/app/citation/**`, a migration).

**Companion slice:** **PR1c** (separate spec/plan) adds the **chat** consumer — exposing `get_authority`/`search_authority` in the chat tool-loop + a chat-finalize `verify_and_persist_authority_citations` hook — reusing the substrate this PR builds. PR1b stands alone and closes DE-369 for the **autonomous** path; PR1c closes it for chat.

---

## 1. Goal

After PR1a, the autonomous matter loop can *fetch* US federal statutes/regs from GovInfo, but the fetched text is **undurable and unverified**: it lives only in loop-local `EvidenceItem.content` + the `tool_call_log` audit row, and a quote the model draws from it is never char-fidelity-checked, never ledger-backed, never counted by the fiduciary gate.

PR1b makes a fetched-authority quote a **first-class verified citation**, exactly like a CourtListener caselaw quote or an uploaded-file quote:

- the fetched authority body is **durably stored** (object storage + a metadata cache row), keyed by `(source_type, external_ref)`;
- a quote the model attributes to that authority is **char-fidelity-verified** against the stored body via the **shared `verify()` cascade** (no new verifier);
- a verified/failed quote becomes a **`message_authority_citations`** row, routed into the **existing citation ledger** via a new FK slot, and **counted by the existing fiduciary gate**.

**Reuse, never fork** (ADR 0016 P6 / 0018): one verifier core, one ledger, one gate. PR1b adds a citation *type* and a content *cache*, not parallel machinery.

### DE-369 acceptance criteria (this PR must satisfy all four, for the autonomous path)
1. Fetched-authority **text is durably persisted** (object-storage body + `authority_text_cache` metadata row), and the verifier reads from it.
2. A **`message_authority_citations` table** (migration `0064`) backs verified authority quotes, char-verified against the stored body via the existing cascade.
3. The **`citation_ledger_entry`** 4th FK slot references authority citations, so a delivered matter session's ledger (`build_session_ledger`) includes authority-backed findings and the **fiduciary gate counts them**.
4. **P3 preserved** — audit/ledger rows carry no raw payload; the body is a content store read at trace time.

---

## 2. Background — the caselaw path this mirrors (verified against code)

| Concern | Caselaw (the template) | Authority (this PR) |
|---|---|---|
| Body storage | object storage (`upload_bytes`/`storage_path`) + `ResearchOpinionMetadata` row (`opinion_id` PK, `cluster_id`, `storage_path`, `char_length`), written at `get_cluster` dispatch (`research/service.py:154-184`) | object storage + new `authority_text_cache` row (`source_type`,`external_ref`,`storage_path`,`char_length`,`retrieved_at`), written at authority *fetch* |
| In-memory verify target | `opinion_target(opinion_id, text) -> _OpinionVerificationTarget` (uuid5, `normalized_content`; duck-types `verification._DocumentProtocol`) — `citation/caselaw.py:143-167` | `authority_target(source_type, external_ref, text)` — identical shape, new namespace uuid5 |
| Shared core | `verify(candidate, document, *, gateway, judge_model, ensemble_config) -> VerificationResult` — `citation/verification.py:545` | **same function, unchanged** |
| Citation rows | `MessageCaselawCitation` (mig 0057): `message_id` NOT NULL FK, `opinion_id`/`cluster_id` (int), `source_offset_*`, `source_text`, `verified`, `verification_method` ∈ {exact_match,tolerant_match,paraphrase_judge}, `confidence`, `partial` | `MessageAuthorityCitation` (mig 0064): same columns, **`source_type`+`external_ref` (str)** replace the int ids |
| Autonomous delivery build | `build_caselaw_citations(...)` in `autonomous/ledger_bridge.py:181` (locate→target→candidate→verify→rows), called from `build_session_ledger` against the **manufactured** message | `build_authority_citations(...)` — same shape |
| Ledger assembly | `assemble_ledger_entries` caselaw branch (`citation/ledger.py:84-97`) → `source_kind="caselaw"`, `message_caselaw_citation_id` | 4th branch → `source_kind` ∈ {statute,regulation}, `message_authority_citation_id` |
| Gate | `compute_and_record_gate` buckets `verification_status` (= the method) into PASS/SUPPORTED/FAIL (`citation/gate.py:25-30`) | **unchanged** — authority reuses the same method names → same buckets |

**Why the autonomous path can satisfy `message_id NOT NULL`:** `build_session_ledger` (`autonomous/ledger_bridge.py:309`) *manufactures* a hidden `Chat` + assistant `Message` (`autonomous_session_id=session.id`) at delivery and runs the chat-path stack against that real `message.id`. So the authority citation table needs no nullable-FK special-casing — it mirrors caselaw exactly.

---

## 3. Architecture (PR1b scope — autonomous only)

```
retrieve_authority fetch (autonomous loop, guard._handle_retrieve_authority)
   │  PR1a: returns ToolResult.data["authority"]; db reserved for PR1b
   └─► PR1b: store_authority_text(db, source_type, external_ref, citable_text)
              ├─ upload_bytes(storage_path)            # object storage (body)
              └─ upsert AuthorityTextCache row         # metadata + retrieved_at (TTL)

… loop runs, synthesis produces findings with {quote, source:int} citations …

delivery (build_session_ledger)
   ├─ split citations by evidence kind  →  NEW "authority" branch collects (quote, source_type, external_ref)
   ├─ manufacture hidden Chat + Message
   ├─ build_kb_citations / build_caselaw_citations / **build_authority_citations(message_id, items, …)**
   │        for each (quote, source_type, external_ref):
   │          body = load_authority_text(db, source_type, external_ref)   # cache → object storage
   │                 ?? fallback to carried EvidenceItem.content           # non-fatal defense
   │          target = authority_target(source_type, external_ref, body)
   │          off = locate_passage(quote, body)
   │          result = await verify(candidate, target, gateway, judge_model)
   │          db.add(MessageAuthorityCitation(...))
   ├─ assemble_ledger_entries(message_id)        # NEW authority branch → ledger rows
   └─ compute_and_record_gate(message_id)        # unchanged; authority rows counted
```

The **cache is fully exercised within PR1b**: the autonomous fetch *writes* it; the delivery verifier *reads* it (the in-memory carried `EvidenceItem.content` is kept only as a non-fatal fallback if the cache row is missing/expired). This makes DE-369 criterion 1 literally true and avoids shipping write-only machinery.

---

## 4. Components & interfaces

### 4.1 Migration `0064` (down_revision `0063`)

Three schema changes in one migration:

1. **`message_authority_citations`** — mirror `message_caselaw_citations` (mig 0057), substituting the source key:
   - `id` UUID PK (`gen_random_uuid()`), `message_id` UUID NOT NULL FK→`messages.id` ON DELETE CASCADE.
   - **`source_type` Text NOT NULL** (the registry source, e.g. `"govinfo"` — half the cache key + provenance), **`external_ref` Text NOT NULL** (the GovInfo package_id — the other half), **`content_kind` Text NOT NULL** (`statute`/`regulation`/`unknown` — the ledger `source_kind` label). These three replace caselaw's int `opinion_id`/`cluster_id`.
   - `source_offset_start` Int NOT NULL, `source_offset_end` Int NOT NULL, `source_text` Text NOT NULL (the cited passage).
   - `verified` bool NOT NULL default false, `verification_method` Text NULL, `verification_confidence` Float NULL, `partial` bool NOT NULL default false, `created_at` timestamptz NOT NULL default now().
   - CHECKs (mirror caselaw): offset_start ≥ 0; offset_end > offset_start; `verification_method IS NULL OR IN ('exact_match','tolerant_match','paraphrase_judge')`; confidence NULL or 0..1; `(verified=false) OR (verification_method IS NOT NULL)`.
   - Index on `message_id`.
2. **`authority_text_cache`** — content store (mirror `ResearchOpinionMetadata`, NOT an audit table):
   - `source_type` Text NOT NULL, `external_ref` Text NOT NULL, **unique `(source_type, external_ref)`**.
   - `storage_path` Text NOT NULL, `char_length` Int NOT NULL, `retrieved_at` timestamptz NOT NULL (TTL anchor), `created_at` timestamptz NOT NULL.
   - Index on `(source_type, external_ref)`.
3. **Alter `citation_ledger_entry`** — add `message_authority_citation_id` UUID NULL FK→`message_authority_citations.id` ON DELETE CASCADE; **drop + recreate** `chk_citation_ledger_entry_exactly_one_source` as the 4-term sum `= 1`.

P3 note: `authority_text_cache` is a **content store** (like `ResearchOpinionMetadata`), not an audit/ledger model — it is **outside** the no-raw-payload tripwire (`_AUDIT_MODELS`), exactly as opinion text is today. `message_authority_citations` joins the citation-surface set the ledger reads, carrying only the cited passage (`source_text`) + offsets — same posture as `MessageCaselawCitation`.

### 4.2 Models (`api/app/models/`)
- `message_authority_citation.py` — `MessageAuthorityCitation` (mirror `message_caselaw_citation.py`).
- `authority_text_cache.py` — `AuthorityTextCache`.

### 4.3 `api/app/citation/authority.py` (new — the substrate)
- `authority_target(source_type: str, external_ref: str, text: str) -> _AuthorityVerificationTarget` — uuid5 over a new namespace + `(source_type, external_ref)`; `normalized_content`; duck-types `verification._DocumentProtocol`. (Mirror `caselaw.opinion_target`.)
- Reuse `caselaw.locate_passage` (exact-substring) and `verification.verify` — **import, do not re-implement**.
- `async store_authority_text(db, *, source_type, external_ref, text) -> None` — normalize, `upload_bytes` to a deterministic `storage_path` (e.g. `authority/{source_type}/{external_ref}`), upsert the `AuthorityTextCache` row (set `retrieved_at`=now). Idempotent (re-fetch within TTL overwrites/refreshes).
- `async load_authority_text(db, *, source_type, external_ref) -> str | None` — read the metadata row; if missing or older than `AUTHORITY_TEXT_TTL` (default **30 days**, mirror WS-G), return `None`; else stream the body from `storage_path`. (`_default_load_authority_text` is the injectable hook, mirroring `caselaw._default_load_opinion_text`.)

### 4.4 Autonomous fetch → cache (`api/app/autonomous/guard.py`)
- `_handle_retrieve_authority` (PR1a) gains: after `from_response`, `await store_authority_text(db, source_type=params["source"], external_ref=authority.external_ref, text=authority.citable_text)`. **Non-fatal** (try/except → log; a cache-write failure must not poison the session or fail the fetch — the WS-D invariant). `db` is the param PR1a reserved.
- `ToolResult.data["authority"]` gains a **`"source"`** key (= `params["source"]`, the registry source name) so delivery can key the cache. (`content_kind` is already in `data["authority"]`.)
- **`EvidenceItem` gains an optional `source: str | None = None`** field (loop-local, not persisted — P3 unaffected). `collect_evidence`'s authority branch (`planner.py`) sets `source=data["authority"]["source"]`; `ref` stays `external_ref`; `content` stays `citable_text` (the non-fatal fallback body). For PR1b `source` is always `"govinfo"`, but threading it keeps delivery forward-compatible with WS-E PR2's additional sources rather than hard-coding the single source.

### 4.5 Autonomous delivery (`api/app/autonomous/ledger_bridge.py`)
- The citation-split loop (`:347-355`) currently **drops** `kind=="authority"`. Add the branch: collect an item `(quote, source=ev["source"], external_ref=ev["ref"], content_kind=<from ev/display>, carried_text=ev["content"])` per authority citation.
- `build_authority_citations(db, *, message_id, items, load_authority_text=_default_load_authority_text, gateway, judge_model) -> int` — mirror `build_caselaw_citations`: per item, `body = await load_authority_text(db, source_type=item.source, external_ref=item.external_ref) or item.carried_text`; if no body → skip (non-fatal); `off = locate_passage(quote, body)`; build the `_AuthorityCandidate` against `authority_target(item.source, item.external_ref, body)`; `result = await verify(candidate, target, gateway=gateway, judge_model=judge_model)`; `db.add(MessageAuthorityCitation(message_id, source_type=item.source, external_ref=item.external_ref, content_kind=item.content_kind, source_offset_*, source_text=quote, verified, verification_method, confidence, partial))`. Unverified → a FAIL row (`verified=False, method=NULL`), mirroring caselaw's `_fail_row`, so a fabricated authority quote flags the gate.
- Call it alongside `build_caselaw_citations` (`:376-381`), before `assemble_ledger_entries`.

### 4.6 Ledger wiring (`api/app/citation/ledger.py`)
- `assemble_ledger_entries` — 4th branch: query `MessageAuthorityCitation` by `message_id`; per row append a `CitationLedgerEntry` with `source_kind = ac.content_kind` (statute/regulation), `message_authority_citation_id=ac.id`, `verification_status = ac.verification_method if ac.verified else "unverified"`, `provider = ac.source_type` (e.g. "govinfo"), `retrieved_at=ac.created_at`.
- `resolve_ledger_entries` — add `authority_ids` collection + a bulk-fetch dict + an `entry.message_authority_citation_id is not None` branch in `_resolve_source` returning the cited passage (`source_text` + offsets) for the trace.
- `gate.py` — **no change** (the method strings already bucket; `statute`/`regulation` `source_kind` is descriptive, not a gate input).

### 4.7 Tests
- **Migration/model:** the 4-term exactly-one CHECK rejects 0 and 2 non-null FKs and accepts each of the 4 singly (mirror the PR1a/A2 Postgres CHECK test); `authority_text_cache` unique `(source_type, external_ref)`.
- **Substrate (`authority.py`):** `store`→`load` round-trip; TTL expiry returns `None`; `authority_target` + `verify` exact/tolerant/paraphrase-judge/miss against a fixture body (mirror caselaw verifier tests).
- **Autonomous integration:** a delivered session whose finding cites a fetched authority verbatim → a `verified` `MessageAuthorityCitation` → a ledger entry (`source_kind=statute`) → the session gate counts it PASS; a *fabricated* quote → an unverified row → gate `flagged`. Cache-miss fallback to carried content path. Gateway-down judge → degrade (no crash).
- **P3:** the ledger/audit surface for an authority citation carries no raw body; the body is only in object storage / read at trace time.

---

## 5. Invariants (binding)
- **One verifier, one ledger, one gate** (ADR 0016 P6 / 0018) — reuse `verify()`, `assemble_ledger_entries`, `compute_and_record_gate`; no parallel path.
- **Never poison the session** (WS-D PR1-C1) — the cache write and `build_authority_citations` are best-effort: any failure drops to a non-fatal skip / fallback, never an exception that aborts delivery or poisons the `AsyncSession`. (Mirror the existing `build_caselaw_citations` try/except posture and `build_session_ledger`'s SAVEPOINT isolation.)
- **P3** — body in the content store (object storage), read at trace time; audit/ledger rows reference the citation row + offsets only; `authority_text_cache` is outside `_AUDIT_MODELS`.
- **Honest verification** — only an explicit verbatim/judge hit sets `verified=True` with a method; everything else is an unverified FAIL row that flags the gate (reuse caselaw's conservative `_parse_judge_response`/`_fail_row` posture — a fabricated authority quote must surface, never silently pass).
- **No new egress** — PR1b fetches nothing; it stores/verifies what PR1a already fetched through the gateway.
- **Migration discipline** — `0064` down_revision `0063`; rebuild api+arq-worker+ingest-worker together; verify on a throwaway pgvector, never host-`alembic` against the dev DB.

## 6. Out of scope (→ PR1c / later)
- **Chat consumer** (PR1c): `get_authority`/`search_authority` tool schemas, `ToolSpec.kind="authority"`, `_dispatch_authority` (chat writes the cache + `MessageToolSource` provenance — chat *has* a `message_id`), `collect_tool_sources` authority branch, and `verify_and_persist_authority_citations` in the chat finalize trio (`chats.py` stream + non-stream). Reuses §4.1–4.3, §4.6 substrate verbatim.
- `search_authority` quote verification — `search_authority` returns only titles in `citable_text` (`adapters.py:131`); only `get_authority` bodies are quotable. PR1c gates accordingly.
- A cache **eviction/cleanup job** for expired `authority_text_cache` rows (TTL is enforced read-side; a sweeper is a later DE if storage pressure warrants).
- SEC EDGAR / EUR-Lex sources (WS-E PR2).

## 7. Open questions resolved
- **Body storage:** object storage + metadata row (maintainer 2026-06-30) — authority bodies can be MB-scale; mirror the proven caselaw pattern, keep Postgres lean.
- **PR split:** PR1b (substrate + autonomous) + PR1c (chat consumer) (maintainer 2026-06-30) — two reviewable security-gated slices; both ship this milestone.
- **Cache consumer in PR1b:** the autonomous path writes (fetch) **and** reads (delivery) the cache, with carried `EvidenceItem.content` as a non-fatal fallback — the cache is load-bearing in PR1b, not write-only.
- **Cache key:** `(source_type, external_ref)` — `source_type` (the registry source, "govinfo") threaded onto `ToolResult.data["authority"]["source"]` → `EvidenceItem.source` so delivery can key it; `external_ref` is the GovInfo package_id. `content_kind` (statute/regulation) is stored separately on the citation row as the ledger `source_kind` label — distinct from `source_type` (the cache/provenance key).
