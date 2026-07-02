# LQ-AI ask — three refinements to the `/api/v1/research` surface for Donna

> **✅ RESOLVED — the `/api/v1/research` surface shipped across PR3b/#161, #163, and the PR6 series (#188–#193); migration head `0055`.** Retained as the consumer-requirement record that informed the final shape. The "ideally before PR3b merges / otherwise a fast-follow" timing language below is historical. See [HONEST-STATE.md §5.5](../HONEST-STATE.md) for the shipped surface.

**Filed:** 2026-06-17 · **From:** Donna (consumer) · **For:** Donna Slice A — the case-law research
workspace (frontend for the legal-research milestone). · **Timing:** ideally folded into **PR3b**
(branch `feat/research-api`, where the surface is being built) *before* it merges, so Donna builds
against the final shape; otherwise a small fast-follow. None of these block the merge.

The LQ-AI session works in `/Users/kevinkeller/Code/lq-ai` (absolute paths below; it can't see Donna
branches). All three are grounded in the current `feat/research-api` source.

## Context

Donna is building a reading-first **Research workspace** over `/api/v1/research/*`: search → read an
opinion in the doc panel → find-in-case → verify citations. The contract as drafted
(`/Users/kevinkeller/Code/lq-ai/api/app/api/research.py`,
`/Users/kevinkeller/Code/lq-ai/api/app/schemas/research.py`) is a clean fit. These three refinements
remove a heuristic and two guesses on the Donna side — they make the UI honest and let Donna drop a
hand-parser. Listed in priority order.

---

## Ask 1 (most valuable) — an explicit "is research enabled?" signal

**The gap.** CourtListener is feature-flagged off until the operator declares a `courtlistener`
tool-provider (with `COURTLISTENER_API_TOKEN`) in `gateway.yaml`. When it's *not* configured, a Donna
user hitting `/research` should see a calm "Case-law research isn't enabled on this server" gate — not
an error. But today Donna can only **infer** that from a failed/empty response, which is
indistinguishable from a transient gateway/network failure. There is no capabilities or health
endpoint that reports it (`grep` for `capabilities`/`/health` in
`/Users/kevinkeller/Code/lq-ai/api/app/api/` finds only MFA-related `*_enabled` fields).

**The ask.** A deterministic signal Donna can read at page load. Any of these works; (a) is cleanest:

- **(a)** `GET /api/v1/research/capabilities` → `{ enabled: bool, providers: [{ name, type }] }` (or a
  minimal `{ research_enabled: bool }`). Active-user auth, no secrets — just whether a `courtlistener`
  tool-provider is wired.
- **(b)** Fold a `research` flag into an existing capabilities/feature-flags endpoint if one is
  planned.
- **(c)** At minimum, a **distinct, documented error code** when the provider is unconfigured (e.g.
  `503 research_not_configured` / a typed `code`), so Donna distinguishes "off" from "broke." This is
  the cheapest option but leaves Donna gating on an error path rather than a positive signal.

**Why it matters.** Without this, Donna's not-enabled gate is heuristic and could mis-render a real
outage as "not enabled" (or vice-versa). A positive capability signal makes the gate correct.

## Ask 2 (easy win) — type the `verify-citations` response

**The gap.** `VerifyCitationsResponse.citations` is `list[dict[str, Any]]`
(`/Users/kevinkeller/Code/lq-ai/api/app/schemas/research.py`), so it lands in OpenAPI — and Donna's
`gen:api` — as an untyped blob. Donna must hand-write a defensive parser for it.

**But the shape is already deterministic.** The gateway adapter builds each item explicitly
(`/Users/kevinkeller/Code/lq-ai/gateway/app/providers/tool/courtlistener.py:206-222`):

```jsonc
{
  "citation": "576 U.S. 644",
  "normalized_citations": ["576 U.S. 644"],
  "status": 200,                       // CourtListener citation-lookup status (200 found, 404 not, …)
  "error_message": null,
  "clusters": [{ "id": 123, "case_name": "Obergefell v. Hodges", "absolute_url": "/opinion/…/" }]
}
```

**The ask.** Promote that to a typed Pydantic model — e.g. `VerifiedCitation { citation: str|None,
normalized_citations: list[str], status: int|None, error_message: str|None, clusters:
list[CitationCluster] }` with `CitationCluster { id: int, case_name: str|None, absolute_url:
str|None }` — and set `VerifyCitationsResponse.citations: list[VerifiedCitation]`. The adapter already
emits exactly this; it's a schema-layer change. Donna then derives the type from `gen:api` and drops
the hand-parser (matches the project preference: typed contract over hand-fork).

If the upstream CourtListener payload is considered too unstable to pin, a documented note to that
effect is enough — Donna keeps the parser but at least knows it's deliberate.

## Ask 3 (small) — document the `text_field_used` value set

**The gap.** Opinions/clusters carry `text_field_used: str | None`
(`schemas/research.py`; set from the adapter). Donna wants to label the reader honestly — e.g.
"plain text" vs "HTML-derived" — but the set of possible values isn't documented in the contract.

**It's already a closed set** in the adapter's preference order
(`/Users/kevinkeller/Code/lq-ai/gateway/app/providers/tool/courtlistener.py:35-41`):
`html_with_citations`, `html_columbia`, `html_lawbox`, `html_anon_2020`, `html`, `plain_text`.

**The ask.** Either type it as a `Literal[...]`/enum in the schema, or document the value set in the
OpenAPI field description. Either lets Donna map values to honest, friendly source labels (and treat
the `html_*` family as "HTML-derived, formatting normalized") rather than displaying a raw token.

---

## Conventions Donna will follow regardless

- Donna consumes only the published API (re-runs `gen:api` after the pin bump; the merged shape wins
  over this ask). Where a field stays loose, Donna keeps a defensive parser and says so in a comment.
- No behavior change requested to the read/search/find endpoints themselves — they're a good fit as
  drafted.
