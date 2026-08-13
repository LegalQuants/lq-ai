# ADR 0024 — Reserved terminology and user-facing names

**Status:** Proposed (2026-07-30)
**Date:** 2026-07-30
**Owner:** External documentation site (`iris-ng/lq-website`); no issue filed yet
**Relates to:** [ADR 0011](0011-transparency-first-model-selection.md) (tier
disclosure), [ADR 0016](0016-transparency-and-governance-invariants.md) (the
invariants), [ADR 0018](0018-citation-ledger-and-fiduciary-grade-output.md) D3
(the gate), [ADR 0019](0019-transparent-validity-treatment-layer.md) D5
(treatment taxonomy), [ADR 0021](0021-content-source-registry-and-free-source-expansion.md)
(the source registry)

## Context

**Four unrelated things in LQ.AI are called "tier", and three legal words are
used in senses a lawyer will read differently from how the code means them.**

| "Tier" | Where | Means |
|---|---|---|
| Inference tier 1–5 | `minimum_inference_tier`, `routed_inference_tier`; PRD §1.5, §4 | the confidentiality ladder |
| Verdict tier | ADR 0018 D3, `gate_status` | PASS / SUPPORTED / FAIL on a citation |
| Egress tier | `gateway.yaml`, `egress_tier` | a *use* of the 1–5 scale |
| Fallback tier 1/2 | playbook executor | rank among fallback positions |

A reader learns that the scale runs 1–5 and that **lower is stronger** — Tier 1
local and air-gapped, Tier 5 blocked by default for client work. They then meet
"verdict-tier parity gaps remain" and reasonably conclude something is wrong
with how privileged work is routed. Nothing is. Two of the four senses have
nothing to do with confidentiality.

The three legal words:

- **"Precedent"** — the autonomous layer's `propose_precedent` means *a
  recurring pattern the system noticed*, not a binding prior decision. Never
  disambiguated.
- **"Authority"** — the source registry admits SEC 10-K and 8-K filings as
  `content_kinds: ["sec_filing"]`. A 10-K is evidence, not authority.
- **"Fiduciary"** — ADR 0018 driver 4 already says "a computed gate, not a
  marketing label", and that is fair. The narrower problem: the gate is
  arithmetic over quote matches, and the borrowed word names a *duty*. A memo
  can compute `fiduciary_grade` with every quote verbatim and still breach that
  duty — wrong jurisdiction, missed controlling authority, undisclosed
  conflict. The name promises a scope the computation does not cover.

A public documentation site for practising lawyers is being built now. Every
page inherits this vocabulary, so the cost of leaving it compounds. No prior
ADR decides naming policy; nearest canon is ADR 0011, ADR 0016, and CLAUDE.md's
decide-once rule.

Why act rather than disambiguate in prose: the project's verification argument
depends on a reader matching what the docs say to what the code does. Fixing
only the docs leaves two vocabularies and no way to tell which is
authoritative. And false friends are worse than jargon — an unfamiliar word
prompts a lookup, a familiar word in an unfamiliar sense produces silent
misunderstanding.

## Decisions

### D1 — "Tier" means one thing

Reserved for the confidentiality ladder. The others are renamed:

| Today | Becomes |
|---|---|
| Verdict tier | **cite-check result** |
| Fallback tier 1/2 | **fallback position** |
| Egress tier | folded into the confidentiality scale |

`egress_tier` stays as a config key, documented as "the confidentiality level a
connector may egress at" — not its own axis.

### D2 — The scale gets names, and the numbers leave the interface

The ladder is the **confidentiality scale**, with five named bands:

**Sealed · Private · Enterprise · Standard · Consumer**

**The numbers are retired from every user-facing surface** — UI, docs,
explainers, error messages. They remain in the API, database and config, where
`minimum_inference_tier` and friends are unchanged.

Two reasons. "Lower is stronger" is an inversion the reader must be taught and
can forget. And a five-point numeric scale invites the hotel-star reading: a
lawyer sees "Level 5" and infers *best*, when Tier 5 is the one blocked by
default for client work. A named band carries its direction in the name and
cannot be misread that way.

"Mode" stays reserved for the PRD §1.5 deployment split (Mode 1 cloud keys,
Mode 2 local inference) and is not reused for the scale.

### D3 — Cite-check labels name the method, not a grade

| Today | Becomes | Means |
|---|---|---|
| PASS (`exact_match`) | **Quoted** | the words are in the source, byte-identical |
| PASS (`tolerant_match`) | **Quoted (normalised)** | matched after whitespace, smart-quote and OCR folding — not shown as verbatim |
| SUPPORTED | **Judged** | a language model concluded the source supports the claim |
| FAIL (`unverified`) | **Not confirmed** | the cascade could not confirm it |
| FAIL (`failed`) | **Check failed** | the check errored — not a negative result |
| — | **Contradicted** | *new*: the source says the opposite |

"Fiduciary" is retired from user-facing surfaces. A grade word is avoided
because a grade implies a judgment the computation cannot make: a document can
be fully Quoted and still be bad advice.

`Contradicted` needs a judge-verdict change, so it is scoped as a follow-up.
Named here so the vocabulary is settled once.

### D4 — The reserved-word list is canon

`docs/contribute/terminology-style-guide.md` holds the reserved words, the
forbidden reuses, and each false friend with an explicit "this does not
mean…" line. `docs/glossary.md` holds the public definitions. Both linked from
`CONTRIBUTING.md`. A new user-facing noun that collides with a reserved word is
a review finding.

### D5 — Renames land in the product, not only the docs

User-visible strings and API-visible values are renamed. Any renamed API value
is aliased for one release and recorded as a breaking change. Stored enum
values needing a migration are noted and deferred rather than blocking.

## Alternatives considered

- **Disambiguate in prose; change nothing.** Cheapest, and the docs site could
  survive by always writing "inference tier" in full. Rejected: the collision
  stays in the product, so a reader moving between UI, API and docs still meets
  a bare "tier" with four meanings — and it relies on discipline forever.
- **Rename in the docs only.** Fastest coherent site. Rejected: a procurement
  reader who reads both sees two vocabularies and cannot tell which is
  authoritative, which damages the verification argument the project rests on.
- **Keep the numbers, fix the inversion with a diagram.** Cheap, matches the
  API exactly. Rejected as the primary presentation: correct reading becomes
  dependent on having seen the diagram. Compatible with D2 as a fallback if the
  bands prove contentious.
- **Invert the scale so 5 is strongest.** Removes the inversion, keeps numbers.
  Rejected: it silently changes the meaning of every stored
  `minimum_inference_tier`, every config file in the field, and every existing
  document — the worst failure mode for a confidentiality control.
- **Rename "fiduciary-grade" only.** Addresses the sharpest overclaim for least
  work. Rejected as insufficient: "tier" is the collision that misleads about
  confidentiality, which is the higher-stakes misunderstanding.

## Consequences

- The docs site is written against one vocabulary, and its glossary becomes a
  real artifact rather than a disambiguation table.
- Every future contribution gets cheaper: a contributor writing a skill or page
  looks a word up instead of inferring which sense applies. That matters most
  for the contributors the project most wants — practising lawyers who are not
  reading the source.
- One-time costs: a prose sweep across `docs/`; string changes in `web/`; label
  changes across the Learn explainers; one aliasing release for renamed API
  values; PRD §1.5 and §4 updated so spec and code agree.
- ADR 0018 D3 and ADR 0019 D5 are amended in their **naming only**. Both stand
  as to what they compute.
- Retiring "fiduciary" costs the project its most quotable phrase for this
  capability. Intended trade: the phrase is a liability with the audience it was
  written for, and "every quote traced to its source" is both more accurate and
  more persuasive.
- The three false-friend glossary entries should be reviewed by a practising
  attorney before merge, since the claim is precisely that the current senses
  mislead one.
- Follow-up, **not decided here**: adding `Contradicted`; adding direct
  appellate history classes to the ADR 0019 D5 taxonomy; whether the source
  registry should separate authority from evidence.

---

*Drafted from a terminology review conducted while scoping the external
documentation site; proposed for committee comment. No implementing PR exists.*
