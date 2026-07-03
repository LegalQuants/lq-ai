# LQ.AI → Donna: Fiduciary-Grade Auditability Integration Reference

> **Produced:** 2026-07-01, for the Donna auditability/features integration.
> **Audience:** Donna CC (SvelteKit BFF that consumes lq-ai via the published API + pinned submodule).
> **Method:** every claim below is verified against the lq-ai source at `file:line`. Where a
> guarantee does **not** exist, this doc says so plainly rather than let you guess — that is the
> whole point of a fiduciary-grade contract.

## How to read this doc — shipped vs. in-progress legend

| Tag | Meaning |
|---|---|
| **🟢 SHIPPED** | On `main` today (pin ≈ `36b5126`). Buildable now. |
| **🟡 IN REVIEW (#251)** | On branch `feat/wse-pr1c-chat-authority` (HEAD `a8e9f56`), security-gated PR **#251**, not yet merged. Lands at the squash SHA once merged. |
| **🟡 branch `feat/cross-user-auditor-role`** | A second, unrelated in-progress branch (§2.6a only — the cross-user `auditor` role). Not yet a numbered PR as of this note. Lands at its own squash SHA once merged. |

**The one thing gated behind #251** is *chat-turn* authority (statute/regulation) citation verification.
Everything else in this doc — the ledger, the fiduciary gate, provenance, caselaw citations,
the treatment layer, the authority substrate for **autonomous** sessions, and `/research/sources` —
is 🟢 shipped on `main`, **except §2.6a** (the cross-user `auditor` role), which is on its own
in-progress branch per the second 🟡 row above.

## The two sections that actually de-risk your build

You correctly called these out; they're where fiduciary features go wrong if guessed:

1. **§3 Semantics & guarantees (the integrity model).** Read this first. Short version: the trail is
   **append-only by convention, not cryptographically enforced** — there is **no hash-chaining, no
   signatures, no HMAC** on the audit/ledger trail today. Do not build a "tamper-proof / verified
   integrity" UI affordance; build an "honest provenance record" UI. Details and the one caveat
   (`content_hash`) below.
2. **§2.4 Real example payloads.** Reconstructed from the actual integration-test assertions.

---

# §1 — Capability inventory (the "what")

Each capability, who it's for, and the user-facing question it answers.

### 1.1 The Citation Ledger 🟢
One row per *(assistant turn, source consulted)*. Each entry records the source's identity, the exact
passage(s) the model quoted, whether that quote was verified against the real source text, the
verification method, and provenance (provider, retrieval time). **For:** the end user and any
fiduciary reviewer. **Answers:** *"For this answer, what sources were used, what exactly was quoted
from each, and was each quote actually found in the real source?"*

### 1.2 The Fiduciary-Grade Gate 🟢
One verdict per assistant turn, computed deterministically from the ledger: `fiduciary_grade`,
`supported_only`, or `flagged`, plus pass/supported/fail counts and a mean confidence. **For:** the
end user (a trust signal) and the reviewer (a triage filter). **Answers:** *"Can I trust this turn at
a glance — were all quoted claims verified, only paraphrase-supported, or did something fail?"*

### 1.3 Provenance / "sources consulted" 🟢
`MessageToolSource` rows: every tool-retrieved source (caselaw clusters, MCP connector results) with a
label, subtitle, URL, and provider — distinct from *verified quotes*. These are "consulted," not
"asserted," and are **excluded from the gate**. **For:** end user. **Answers:** *"What did the
assistant look at, even if it didn't quote it?"*

### 1.4 Caselaw citation verification 🟢
Verbatim + paraphrase-judge verification of quoted caselaw against the actual opinion text
(CourtListener). **For:** end user / reviewer. **Answers:** *"Is this quote really in that case?"*

### 1.5 Authority (statute / regulation) citation verification
Same verification, for statutory/regulatory text fetched from GovInfo (U.S. Code, CFR).
**Autonomous-session path: 🟢 SHIPPED (PR1b).** **Chat-turn path: 🟡 IN REVIEW (#251).**
**Answers:** *"Is this quote really in that statute/regulation?"*

### 1.6 Transparent validity / treatment layer (KeyCite analog) 🟢
Per cited case, a *derived* (never asserted) treatment signal: citation-graph "cited by N" + an
LLM-judge classification of how later cases treated it (followed / distinguished / criticized /
questioned / overruled / superseded / neutral), with a strongest-negative rollup and per-signal
justifications. Labeled **"derived, not editorial."** Computed **asynchronously** off the turn's
critical path. **For:** the reviewer especially. **Answers:** *"Is this case still good law — and can
I see why the system thinks so, linked to the citing cases?"*

### 1.7 Autonomous matter-session ledger + receipt 🟢
The same ledger + gate for a governed agentic legal-matter session, plus a **receipt** that (uniquely)
exposes cost. **For:** reviewer / admin. **Answers:** *"What did this autonomous session do, on whose
behalf, at what cost, and is its output fiduciary-grade?"*

### 1.8 Research source registry 🟢
`GET /research/sources` — which authoritative sources are available, their jurisdiction, coverage,
content kinds, egress tier, and enabled flag (auth keys and cost never exposed). **For:** end user /
admin. **Answers:** *"What authoritative sources can this instance actually reach right now?"*

---

# §2 — The API contract (the "how you consume it")

## 2.1 Endpoint list

| Method & path | Response typed? | Auth | Tag |
|---|---|---|---|
| `GET /api/v1/chats/{chat_id}/ledger` | **No** (`dict[str,Any]`, no `response_model`) | owner-scoped | 🟢 |
| `GET /api/v1/chats/{chat_id}/messages/{message_id}/sources` | **No** (array of dicts) | owner-scoped | 🟢 |
| `GET /api/v1/autonomous/sessions/{session_id}/ledger` | **No** (`dict[str,Any]`) | owner-scoped | 🟢 |
| `GET /api/v1/autonomous/sessions/{session_id}` (→ `receipt`, incl. cost) | Yes | owner-or-admin | 🟢 |
| `GET /api/v1/research/sources` | **Yes** (`SourcesResponse` Pydantic) | active user | 🟢 |
| `GET /api/v1/chats/{chat_id}/receipts/export.jsonl` | JSONL stream | owner-or-admin | 🟢 |
| `POST /api/v1/users/me/export` + `GET /api/v1/users/me/export/{job_id}` | Yes | self | 🟢 |

> ⚠️ **Codegen caveat.** The three ledger/sources endpoints return hand-built `dict[str, Any]` with
> **no `response_model`**, so their OpenAPI schema is empty `{}`. `npm run gen:api` will **not** give
> you types for these bodies. Hand-write parsers from §2.3/§2.4. Only `/research/sources` and the
> autonomous receipt have real generated types.

## 2.2 The ledger response — the core object

`GET /chats/{chat_id}/ledger` and `GET /autonomous/sessions/{session_id}/ledger` return the **identical
shape** `{chat_id, entries[], gates[]}`. One renderer serves both. Differences:
- The chat endpoint accepts `?message_id=<uuid>` to narrow to one turn; the session endpoint takes no query params.
- In the session response, `chat_id` is the *hidden session-owned* chat's id, and `gates[]` always has exactly one element.

### Entry object
`id, message_id, source_kind, verification_status, confidence, provider, retrieved_at, treatment_id, treatment, created_at, source`

- `source_kind` — **open string** (no DB CHECK): `kb_document`, `caselaw`, `statute`, `regulation`,
  `unknown`, `mcp`, or a future kind. Treat as open enum.
- `verification_status` — the `verification_method` if the quote verified, else `"unverified"`; for
  provenance/tool-source rows it is the literal `"provenance"`. Enum values below.
- `confidence` — `number | null` (float 0–1). Null for provenance rows, unverified rows, or when unset.
- `provider` — `null` (kb_document) | `"courtlistener"` (caselaw) | the authority `source_type`
  (authority) | the tool provider (provenance).
- `treatment` — present (object) only for caselaw entries whose async treatment derivation has
  completed; **`null` otherwise** (see §4 — this is eventually-consistent).
- `source` — **polymorphic; branch on `source.kind`** (key sets differ):
  - `kb_document`: `{kind, source_file_id, passages:[{text, offset_start, offset_end, page}]}`
  - `caselaw`: `{kind, opinion_id, cluster_id, passages:[{text, offset_start, offset_end}]}` (no `page`)
  - authority: `{kind:<content_kind>, external_ref, provider, passages:[{text, offset_start, offset_end, verified, method}]}`
  - tool source: `{kind:<source_kind>, label, subtitle, url, external_ref, tool}` — **no `passages`**

**`verification_status` / `verification_method` enums (closed, DB-CHECK'd):**
- kb_document: `exact_match, tolerant_match, llm_judge, paraphrase_judge, ensemble_strict, ensemble_majority, failed`
- caselaw & authority: `exact_match, tolerant_match, paraphrase_judge`
- plus the derived values `unverified` and `provenance` (ledger-level, not a DB column)

### Gate object
`message_id, gate_status, pass_count, supported_count, fail_count, total_assertions, confidence, created_at`

- `gate_status` — **closed enum, three values only: `fiduciary_grade`, `supported_only`, `flagged`.**
  **⚠️ There is no field named `verdict`** — switch on `gate_status`.
  - `flagged` — at least one FAIL (`unverified`/`failed`).
  - `supported_only` — no FAIL, at least one SUPPORTED (paraphrase/ensemble).
  - `fiduciary_grade` — all PASS **or zero assertions** (see the honesty note below).
- `confidence` — `number | null` (mean of the non-null per-entry confidences; null when none).
- Provenance/tool-source rows are **excluded** from all counts.

> 🔑 **Honesty nuance you must render correctly.** `total_assertions == 0` also yields
> `gate_status: "fiduciary_grade"` with `confidence: null`. That means *"this turn made no verifiable
> claims,"* **not** *"claims were verified."* Distinguish these in the UI (use `total_assertions`):
> "no verifiable assertions" is a different, weaker statement than "N assertions, all verified." Do
> not show a green "verified" badge on a turn that verified nothing.

## 2.3 `/research/sources`, `/sources`, and the receipt

**`GET /research/sources`** → `{ "sources": [ {name, type, jurisdiction, coverage, content_kinds[], enabled, egress_tier} ] }`.
`name` and `egress_tier` are nullable; auth keys and cost are never included. Registered-but-unconfigured
sources appear with `enabled: false` (never omitted).

**`GET /chats/{chat_id}/messages/{message_id}/sources`** → JSON **array** of
`{id, message_id, source_kind, label, subtitle, url, external_ref, provider, tool, created_at}`.
Returns `[]` for a turn that consulted nothing. This surfaces only `MessageToolSource` (provenance);
**caselaw/authority quote citations are surfaced only through `/ledger`.**

**Autonomous receipt** (`GET /autonomous/sessions/{session_id}` → `receipt`) is the **only client-facing
cost surface**: top-level `cost_total_usd`, `max_cost_usd`, `cost_cap_reached`, and per-audit-entry
`cost_usd`. Chat/ledger endpoints expose **no cost**.

## 2.4 Real example payloads

**`GET /chats/{chat_id}/ledger`** — a turn with one verified KB quote and one caselaw quote with derived treatment:

```json
{
  "chat_id": "6f1c2a90-1111-4aaa-bbbb-000000000001",
  "entries": [
    {
      "id": "a1000000-0000-4000-8000-000000000001",
      "message_id": "b2000000-0000-4000-8000-000000000002",
      "source_kind": "kb_document",
      "verification_status": "exact_match",
      "confidence": 1.0,
      "provider": null,
      "retrieved_at": null,
      "treatment_id": null,
      "treatment": null,
      "created_at": "2026-06-30T12:00:00+00:00",
      "source": {
        "kind": "kb_document",
        "source_file_id": "c3000000-0000-4000-8000-000000000003",
        "passages": [
          { "text": "This Agreement shall be governed by", "offset_start": 0, "offset_end": 35, "page": null }
        ]
      }
    },
    {
      "id": "a1000000-0000-4000-8000-000000000004",
      "message_id": "b2000000-0000-4000-8000-000000000002",
      "source_kind": "caselaw",
      "verification_status": "tolerant_match",
      "confidence": 0.9,
      "provider": "courtlistener",
      "retrieved_at": "2026-06-30T11:59:00+00:00",
      "treatment_id": "d4000000-0000-4000-8000-000000000005",
      "treatment": {
        "cited_by_count": 214,
        "as_of": "2026-06-30T12:05:02.100000+00:00",
        "derived_method": "citation_graph+judge",
        "citing": [
          { "opinion_id": 998877, "case_name": "Later v. Case", "court": "ca9", "date_filed": "2019-03-02" }
        ],
        "strongest_negative_class": "overruled",
        "judged_count": 6,
        "judge_as_of": "2026-06-30T12:05:03.500000+00:00",
        "per_class_counts": { "overruled": 1, "followed": 3, "neutral": 2 },
        "case_confidence": 0.85,
        "signals": [
          { "citing_opinion_id": 998877, "classification": "overruled", "confidence": 0.85,
            "justification": "The later panel expressly overrules the cited holding on the standing question." },
          { "citing_opinion_id": 776655, "classification": "followed", "confidence": 0.7,
            "justification": "Applies the cited case's test without qualification." }
        ]
      },
      "created_at": "2026-06-30T12:00:01+00:00",
      "source": {
        "kind": "caselaw",
        "opinion_id": 2812209,
        "cluster_id": 654321,
        "passages": [ { "text": "The court held that...", "offset_start": 40, "offset_end": 120 } ]
      }
    }
  ],
  "gates": [
    {
      "message_id": "b2000000-0000-4000-8000-000000000002",
      "gate_status": "supported_only",
      "pass_count": 1,
      "supported_count": 0,
      "fail_count": 0,
      "total_assertions": 1,
      "confidence": 0.95,
      "created_at": "2026-06-30T12:00:02+00:00"
    }
  ]
}
```

**Graph-only (not-yet-judged) treatment** — how a caselaw entry looks before the async judge pass completes:
```json
"treatment": {
  "cited_by_count": 88, "as_of": "2026-06-30T12:00:10+00:00", "derived_method": "citation_graph",
  "citing": [], "strongest_negative_class": null, "judged_count": null, "judge_as_of": null,
  "per_class_counts": {}, "case_confidence": null, "signals": []
}
```
…and before *any* derivation completes, the whole `treatment` field is `null`.

**Authority `source` variant** (🟡 chat path via #251; 🟢 already possible on the autonomous path):
```json
"source": {
  "kind": "statute", "external_ref": "USCODE-2022-title15", "provider": "govinfo",
  "passages": [ { "text": "Every contract...", "offset_start": 0, "offset_end": 40, "verified": true, "method": "exact_match" } ]
}
```

**`flagged` gate** (a failed/unverified quote present):
```json
{ "message_id": "…", "gate_status": "flagged", "pass_count": 1, "supported_count": 0,
  "fail_count": 1, "total_assertions": 2, "confidence": 1.0, "created_at": "…" }
```

**`GET /chats/{chat_id}/messages/{message_id}/sources`:**
```json
[
  { "id": "dd44…", "message_id": "b2…", "source_kind": "caselaw", "label": "Miranda v. Arizona",
    "subtitle": "U.S. Supreme Court · 1966-06-13", "url": "https://www.courtlistener.com/opinion/…",
    "external_ref": "10648", "provider": "courtlistener", "tool": "search_case_law",
    "created_at": "2026-07-01T12:00:00+00:00" }
]
```

**`GET /research/sources`** (govinfo configured, courtlistener not):
```json
{ "sources": [
    { "name": null, "type": "courtlistener", "jurisdiction": "us-federal",
      "coverage": "U.S. federal & state appellate caselaw (operator CourtListener key)",
      "content_kinds": ["caselaw"], "enabled": false, "egress_tier": null },
    { "name": "govinfo-prod", "type": "govinfo", "jurisdiction": "us-federal",
      "coverage": "U.S. Code + Code of Federal Regulations",
      "content_kinds": ["statute", "regulation"], "enabled": true, "egress_tier": 2 }
] }
```

## 2.5 Pagination / filtering / sorting

- **No pagination** on any ledger/sources endpoint — no cursor, no `limit`/`offset`. The full ledger
  for the chat (or session) is returned in one response. (For very long chats this is worth noting;
  there is no server-side page today — file an upstream request if you need one.)
- **Filtering:** only `?message_id=<uuid>` on the chat ledger. No source_kind/status/date filters.
- **Ordering:** entries and gates are `ORDER BY created_at, id` **ascending (oldest first)**. Timestamps
  are server-generated Postgres `timestamptz`, serialized ISO-8601 with offset (`+00:00`). Ordering is
  deterministic (id tiebreak).

## 2.6 Auth & RBAC

- All ledger/sources endpoints require an **active bearer-JWT user** (`ActiveUser`) and are
  **owner-scoped**: access is filtered by `Chat.owner_id == user.id`. A foreign or missing chat both
  return **404** (deliberate — no existence leak). Malformed `chat_id`/`message_id` → **400** on the
  chat endpoint; malformed `session_id` → **422** on the autonomous endpoint.
- **There is no dedicated auditor / compliance / fiduciary-reviewer role.** The role model is
  `{admin, member, viewer}` (`user.role`, plus a legacy `is_admin` bool). `viewer` is a generic
  read-only login (writes rejected), **but it is still owner-scoped** — a viewer cannot read another
  user's ledger. No role can read a foreign user's ledger via the API.
- **The ledger endpoint has no admin bypass** — even an admin gets 404 on someone else's chat. (Note
  the asymmetry: the *receipts* endpoints *do* allow an admin bypass; the *ledger* does not.)
- New scopes/permissions the UI must respect: **none new.** Gate write endpoints on `viewer` (they're
  already blocked server-side); surface the ledger/gate read-only to whoever owns the chat.

  > ⚠️ **Superseded by §2.6a below.** The three paragraphs above describe the state before this PR
  > (branch `feat/cross-user-auditor-role`). A dedicated `auditor` role now exists, and the ledger
  > endpoints **do** have a privileged bypass. Read §2.6a for the current contract; the paragraphs
  > above are left in place only as the "before" reference the PR diff makes sense against.

## 2.6a Cross-user auditor role — delivered contract (🟡 branch `feat/cross-user-auditor-role`, not yet merged)

This is new since the rest of §2 was written, and it changes two of the "no admin bypass" / "no
auditor role" claims above. Build against this; it will supersede §2.6 once merged.

**Role.** A new `auditor` value in the `users.role` enum (alongside `admin`, `member`, `viewer`;
migration `0065`). It is a **read-only, deployment-wide compliance/reviewer role**, distinct from
`admin` — `is_admin` stays `False` for an auditor. It carries no mutating rights: `auditor` is
excluded from `_MUTATING_ROLES` the same way `viewer` is, so all POST/PATCH/DELETE endpoints reject
it exactly as they reject `viewer` today.

**Grant.** Same admin-only endpoint you already use for `viewer`/`member`: `PATCH
/api/v1/admin/users/{user_id}/role` with body `{"role": "auditor"}`. No new endpoint.

**What it unlocks — the "privileged reader" set = `{admin, auditor}`.** A single predicate,
`is_privileged_reader(user) = user.is_admin or user.role == "auditor"`, now gates cross-user read on:
- `GET /chats/{chat_id}/ledger`
- `GET /chats/{chat_id}/messages/{message_id}/sources`
- `GET /autonomous/sessions/{session_id}/ledger`
- `GET /chats/{chat_id}/receipts` and `GET /chats/{chat_id}/receipts/export.jsonl` (these already had
  an admin bypass; `auditor` now joins it — no behavior change for admins)

The fiduciary gate is embedded in the ledger/session-ledger response bodies (§2.2's `gates[]`), so no
separate endpoint is needed to audit gate verdicts cross-user.

**Failure-mode matrix:**

| Caller | Resource | Result |
|---|---|---|
| Owner | any of the above | `200`, no audit row written |
| Privileged (`admin` or `auditor`), non-owner | ledger / sources / session-ledger | `200` **+ one `audit_log` row** |
| Privileged (`admin` or `auditor`), non-owner | receipts (read or export) | `200` **+ one `audit_log` row** (unchanged shape from the existing admin bypass) |
| Non-privileged (`member`/`viewer`), non-owner | ledger / sources / session-ledger | **`404`** — indistinguishable from a nonexistent id (existence-safe; unchanged posture from §2.6) |
| Non-privileged (`member`/`viewer`), non-owner | receipts | **`403`** — unchanged; receipts never adopted the existence-safe 404 redesign |
| anyone | nonexistent id | `404` |

**Audit-the-auditor.** Every privileged cross-user read (never an owner read) writes one `audit_log`
row via a shared wrapper (`app/auditor_audit.py`), then the handler `await`s `db.commit()`. `action` is
one of a closed set: `auditor.ledger_viewed`, `auditor.sources_viewed`,
`auditor.session_ledger_viewed`, `auditor.receipts_viewed`, `auditor.receipts_exported`. `details`
carries `{"viewed_user_id": "<owner's user id>"}`. There is no separate "auditor activity" API —
consume this the same way you'd consume any other `audit_log` row.

**Out of scope — be honest about this with your users.**
- **No cross-user listing/discovery.** An auditor (or admin) reads a chat/session/message by *known*
  id only. List endpoints (e.g. the chats list) stay owner-scoped; there is no "browse all chats"
  affordance. If Donna needs discovery, that's an upstream feature request, not something this PR
  provides.
- **No per-matter / per-org scoping.** `auditor` is a single global role — an auditor can read *any*
  user's ledger/sources/session-ledger/receipts on this deployment, not a scoped subset. If you need
  scoped auditors, treat that as a future ask.
- **Writes stay owner-scoped.** `auditor` cannot mutate another user's (or their own delegated) data —
  it is rejected by `_MUTATING_ROLES` identically to `viewer`. True global read-only *enforcement*
  beyond the endpoints listed above is tracked as **DE-378** (some read paths may not yet route
  through `is_privileged_reader`; don't assume every GET endpoint in the system has been audited for
  this bypass — only the five listed above are confirmed).

**Pin.** Not yet merged as of this note. Once merged to `main`, this section will list the squash SHA
— bump your pin to it to build against this contract; today it exists only on branch
`feat/cross-user-auditor-role`.

## 2.7 Loosely-typed fields — hand-write defensive parsers here

The persistence models are strongly typed (no `dict[str,Any]` columns, no `extra="allow"`), **but** the
following reach you as open/free-form and must be parsed defensively:

1. **`entry.treatment.citing`** — a JSONB array of free-form objects (`list[dict[str,Any]]`). Observed
   keys (`opinion_id`/`cluster_id`, `case_name`, `court`, `date_filed`) are **convention, not enforced**.
   Assume keys may be absent/typed differently. *This is the loosest field in the whole surface.*
2. **`entry.treatment.per_class_counts`** — an object with **dynamic string keys** (treatment class
   names) → int; `{}` when no signals.
3. **`entry.source`** — polymorphic; branch on `source.kind` before reading (§2.2).
4. **`source_kind`, authority `content_kind`, authority `source_type`** — open strings with **no DB
   CHECK**; handle unknown values, including the literal `"unknown"`.
5. **Whole ledger/sources responses** are unvalidated `dict[str,Any]` (no `response_model`) — field
   presence rests on server code, not a runtime-enforced schema. Parse tolerantly.
6. **Confidence type mismatch:** `confidence` is a JSON **number** in the ledger and gate, but the raw
   `message_citations.verification_confidence` model field is a `Numeric(3,2)` serialized as a JSON
   **string** (project Decimal-as-string convention). You'll only see the number form on these
   endpoints, but be aware if you ever touch the raw citation rows.

---

# §3 — Semantics & guarantees (the fiduciary part)

## 3.1 Immutability / integrity model — read carefully; do not overclaim

**There is NO cryptographic integrity mechanism on the audit/citation trail today.** No hash-chaining,
no Merkle log, no digital signatures, no HMAC on ledger entries, gate rows, citation rows, or the
`audit_log`. Verified by exhaustive search.

What actually exists, per record type:

| Record | Integrity posture |
|---|---|
| `citation_ledger_entry` | **Append-only by convention.** Written once per turn at finalize; never updated/deleted by app code. But there is **no unique constraint / idempotency guard**, so it is not *enforced* immutability — a re-finalize would append duplicates rather than being rejected. |
| `work_product_fiduciary_gate` | **NOT history — a current-value cell.** Upserted via DELETE+INSERT per turn. The ledger is the history; the gate is the latest verdict. |
| `citation_treatment` / `_signal` | **Refreshed** (DELETE+INSERT) on re-derivation. Not append-only. |
| `audit_log` | **Append-only at the application layer only** (documented convention) — no DB trigger, no signing. |
| `WorkProductAttribution.content_hash` | The **one** tamper-evidence primitive: a per-message SHA-256 of the assistant message content. **Unchained and unsigned.** The code itself documents the Merkle-chaining layer as *"future M2+"* — it does not exist yet. |

**What this means for your UI:** show an **honest provenance record**, not a "tamper-proof / verified
integrity" claim. Safe language: *"Every source and quote is recorded and independently
re-verifiable against the original."* Unsafe language to avoid: *"cryptographically verified,"*
*"tamper-proof,"* *"signed audit trail."* If/when the Merkle layer ships, we'll bump the pin and update
this section — build the affordance so it can light up later, but don't assert it now.

**The "P3 no-raw-payload tripwire"** is a **privacy** guarantee, not an integrity one: a CI structural
test asserting the audit/ledger tables have no column *named* like a raw payload (`body`, `content`,
`payload`, `text`, …). It ensures raw egress payloads aren't persisted in audit rows; it does **not**
sign anything, and it does not inspect JSONB *contents* (e.g. `audit_log.details` passes by name).

## 3.2 Provenance chain shape

It is a **linkable graph, resolved at read time**, not a flat log:

```
message (assistant turn)
  └─ citation_ledger_entry[]           ← one per (turn, source)
       ├─ source_kind + verification_status + confidence + provider + retrieved_at
       ├─ → message_citation | message_caselaw_citation | message_authority_citation | message_tool_source
       │       (exactly one; the quoted passages live here, resolved into entry.source at read time)
       └─ treatment_id → citation_treatment → citation_treatment_signal[]   (caselaw only, async)
  └─ work_product_fiduciary_gate (1:1)  ← the turn's verdict, derived from the entries
  └─ work_product_attribution (1:1)     ← tier/provider/model/skills + content_hash (in user-export)
```

- **Acting principal / "on behalf of":** the chat/session `owner_id` is the principal. Autonomous
  sessions add the plan trace + cost in the **receipt**. There is no separate "on behalf of a client"
  party field in the data model today — the principal is the owning user.
- **Model / skill used:** carried on the message + the SSE `complete` frame (`applied_skills`,
  `routed_inference_tier`, `routed_provider`) and in `WorkProductAttribution`.
- **Cost / consent:** cost is exposed only via the autonomous receipt (§2.3); chat cost is not yet
  surfaced. There is no explicit consent record in this surface.

## 3.3 Ordering & time semantics
Server-generated Postgres `timestamptz`, serialized ISO-8601 with `+00:00` offset (UTC). Ledger/gate
lists are ordered ascending by `created_at, id`; ordering is deterministic.

## 3.4 Export
**No dedicated ledger/gate export endpoint exists (signed or unsigned).** You must assemble any ledger
export in Donna from `GET /chats/{chat_id}/ledger`. Two adjacent exports exist but **both exclude the
citation ledger and the fiduciary gate:**
- `GET /chats/{chat_id}/receipts/export.jsonl` — messages + applied_skills + inference_routing_log +
  audit_log only. Unsigned.
- `POST /users/me/export` (GDPR Art. 20) — bundles user/chats/messages/projects/files/audit_log +
  `work_product_attribution.json` (with the unsigned `content_hash`). No ledger, no gate. ZIP, unsigned,
  24h presigned URL, bytes retained 7 days.

So the closest thing to an exportable integrity artifact is `work_product_attribution.json`'s per-message
`content_hash` — which is unsigned and unchained (§3.1). If Donna needs a signed attestation, that's an
upstream feature request, not something to synthesize client-side and present as authoritative.

## 3.5 Retention / redaction
- **Nothing must be hidden** — the API is designed so everything it returns is display-safe (no secret
  columns, no auth keys, no cost in the ledger). Caveat: `passages[].text` is **third-party quoted
  content** (statute/opinion/KB excerpts) — content, not metadata — so treat it as copyrighted quote
  material, but it is meant to be shown (it's the whole point of the trace).
- **TTL:** the 30-day TTL applies to the cached fetched-authority **body in object storage** (drives
  re-verification staleness) — **not** to audit/citation metadata, which has **no TTL** and is deleted
  only by FK CASCADE when the parent chat/message/user is deleted (GDPR-style, not time-based).

---

# §4 — Delivery mechanics

## 4.1 Live vs. static
- **Real-time transport is SSE only** (OpenAI-style `data: {json}\n\n` frames on the chat send
  endpoint, terminated by a `type:"complete"` frame then a literal `data: [DONE]`). **No webhooks**
  (the one `webhook` enum value in autonomous notifications is reserved/unimplemented).
- **The final `complete` frame does echo `applied_*` at top level** — your existing handler is correct.
  Exact top-level fields: `type`, `lq_ai_message_id`, `message{…}`, `applied_skills[]`,
  `applied_file_ids[]`, `routed_inference_tier`, `routed_provider`, and `citations` (**always `[]` on
  the frame**).
- **Gate/ledger/treatment do NOT ride the SSE channel.** Fetch them via `GET /ledger` after the turn.

## 4.2 Latency — when to fetch, when to poll
- **Ledger + gate + caselaw/authority citations are written synchronously at finalize**, before the
  JSON body / `complete` frame is returned. So a `GET /ledger` **immediately after** the turn completes
  returns them — **no polling needed** for ledger, gate, and quote citations.
- **Treatment is the one eventually-consistent field.** It is computed by an async arq worker
  (`treatment_derivation_job`) off the critical path. A freshly answered caselaw turn shows
  `treatment: null` until the job finishes. **The client must poll `GET /ledger`.** Helpfully, each
  `/ledger` read **lazily re-enqueues** derivation for any missing/stale caselaw entry (DE-363), so the
  poll itself drives progress. There is no push and no explicit "pending" flag — **`treatment: null` on
  a caselaw entry is the only "not ready" signal.** Suggested UX: render the entry immediately, show a
  subtle "checking treatment…" state while `treatment` is null, and re-fetch on an interval (or on panel
  open) until it populates.

---

# §5 — Ops / integration

## 5.1 Pin
- **For everything except chat-turn authority citations:** pin to current `main` (≈ `36b5126`).
- **For chat-turn authority (statute/regulation) verification:** bump to the **PR #251 squash SHA once
  merged** (branch `feat/wse-pr1c-chat-authority`). PR1c adds **no migration** — it reuses the PR1b
  substrate (mig 0064) already on `main`.

## 5.2 Migrations (Donna's api service is the sole migrator; rebuild api + arq-worker + ingest-worker together)
Latest revision = **0064**. Relevant chain:

| Rev | Adds |
|---|---|
| 0057 | `message_caselaw_citations` |
| 0058 | `citation_ledger_entry` (the ledger) |
| 0059 | `work_product_fiduciary_gate` (the gate) |
| 0060 | relax caselaw method CHECK to allow `paraphrase_judge` (no new table) |
| 0061 | `citation_treatment` (graph signal) |
| 0062 | `citation_treatment_signal` + rollup columns |
| 0063 | `chats.autonomous_session_id` column (hidden session chats) |
| 0064 | `message_authority_citations` + `authority_text_cache`; extends `citation_ledger_entry` to a 4th (authority) source FK |

PR1c (#251): **no new migration.**

## 5.3 Config / env to turn features on
- **CourtListener** (caselaw + treatment graph): gateway provider `type: courtlistener`, key via
  `COURTLISTENER_API_TOKEN`. Operator-key-gated ("free" = no LQ.AI-side license cost, not zero setup).
- **GovInfo** (statute/regulation authority): gateway provider `type: govinfo`, key via
  `GOVINFO_API_KEY` (api.data.gov key). Data is free.
- **Judge model** (caselaw paraphrase + treatment judge): `citation_engine.judge_model` (e.g. `fast`).
  If the gateway/judge model can't be resolved, treatment degrades to graph-only automatically.
- Optional Stage-4 ensemble verification is off by default (`ensemble_verification.default_enabled:
  false`, empty `judge_models`).

## 5.4 RBAC seed / e2e admin fixture
- No standalone role-seed script. Roles = `is_admin` bool + `user.role` string (`admin`/`member`/`viewer`).
- **First-run admin bootstrap:** on an empty DB, one admin is minted (`admin@lq.ai`, override
  `LQ_AI_FIRST_RUN_ADMIN_EMAIL`, `must_change_password=True`, random password logged).
- No shared pytest admin fixture — tests mint tokens per module via `create_access_token(user.id,
  user.email, is_admin=…)`. JWT claims: `sub, email, is_admin, iat, exp, typ` (**no `role` claim** — do
  admin gating on `is_admin` from the `/auth` responses).

---

# §6 — Our take on the fiduciary-user experience (optional, adapt freely)

You asked for our mental model of the data; adapt it to Donna's receipt-chain / doc-panel / honest-
degradation patterns. Three core views:

### 6.1 Per-turn "fiduciary receipt" (the primary view)
A trust pill on each assistant turn driven by `gate_status` → three states (`fiduciary_grade` = sage,
`supported_only` = amber, `flagged` = red). Clicking expands a one-click trace: each ledger `entry` as
a row = source identity (from `source`, branched on `kind`) + the quoted `passages[].text` + a
verification chip (from `verification_status`). This mirrors what lq-ai's own web UI does
(`TrustPill` + `CitationLedgerPanel`).
- **Critical honesty detail:** when `total_assertions == 0`, do **not** show a green "verified" pill.
  Render a neutral "no verifiable claims in this turn" state. Green must mean "claims verified," never
  "nothing to verify."
- Provenance ("sources consulted") rows (`verification_status: "provenance"`) belong in a separate,
  visually-lighter group — they were *looked at*, not *asserted*.

### 6.2 Matter-level audit timeline (autonomous sessions)
For a governed matter session, a chronological timeline built from
`GET /autonomous/sessions/{id}/ledger` (entries oldest-first) alongside the **receipt** — which uniquely
adds cost (`cost_total_usd`, `cost_cap_reached`) and the plan trace. This is the "who did what, in what
order, on whose behalf, at what cost" view a reviewer wants. The session's single gate is the headline
verdict.

### 6.3 Treatment (validity) surfacing — derive-don't-assert
Where an entry has `treatment`, show a muted "⚖ Cited by N · derived <as_of>" line with a disclosure of
the `signals[]` (classification + justification, linked to the citing opinion). **Never color a case
"good/bad law"** and never assert editorial authority — the data is deliberately "derived, not
editorial," and absence of a negative signal is not an endorsement. While `treatment` is null on a
caselaw entry, show an unobtrusive "checking treatment…" state and re-poll (§4.2).

### 6.4 Export / attestation — be honest about what it is
If you build an "export this trace" affordance, assemble it client-side from `/ledger` and label it
honestly as a **provenance record**, not a signed attestation — there is no server-side signed export
today (§3.4). Design the button so it can later point at a real signed-export endpoint if/when one
ships, but don't imply cryptographic integrity now.

---

## Appendix — quick "does it exist?" answers to your specific questions

- Audit trail append-only? **By convention, not enforced** (ledger); the gate is an upsert cell.
- Hash-chained / signed? **No** (only an unchained per-message `content_hash`; Merkle log is future).
- Client-verifiable integrity mechanism? **No** — don't build a "verify integrity" button yet.
- Provenance: flat log or graph? **Linkable graph, resolved at read time.**
- Ordering guaranteed? **Yes**, ascending `created_at, id`, UTC `timestamptz`.
- Signed/exportable trail endpoint? **No** — assemble in Donna.
- Anything to never display / redact? **No hidden fields**; `passages[].text` is quoted content (show it).
- Real-time channel? **SSE only, no webhooks.** Audit does not ride SSE.
- Sync or eventual writes? **Ledger + gate: synchronous. Treatment: eventual (poll).**
- New role/scope to respect? **Yes, as of §2.6a** (🟡 not yet merged) — a read-only `auditor` role
  now grants cross-user read on ledger/sources/session-ledger/receipts, audited every time.
