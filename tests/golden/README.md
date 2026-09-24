# Skill golden harness (DE-231)

Golden/snapshot testing for the 10 starter skills. Each skill ships an
`skills/<skill>/acceptance/` corpus of **fully synthetic** input fixtures and
**structural** golden snapshots; this harness runs each fixture through the
normal api chat-send path against a live compose stack and asserts the output's
*structure* — never its wording — stays inside documented ranges. A drop below
threshold on the nightly run auto-files a release-blocking issue
(`.github/workflows/skill-golden.yml`).

## Layout

```
skills/<skill>/acceptance/
├── fixtures/<id>.md            # YAML frontmatter + synthetic document body
└── snapshots/<id>.golden.json  # structural expectations for that fixture

tests/golden/
├── golden_lib.py               # loading + markdown extraction + evaluation
├── live_client.py              # auth + chat-send client for the live stack
├── test_golden_inventory.py    # keyless: corpus format + heuristics (always runs)
└── test_skill_goldens.py       # golden_live: one test per fixture (opt-in)
```

## Fixture format

`fixtures/<id>.md` — YAML frontmatter, then the document body verbatim:

```yaml
---
fixture: baseline-mutual            # must equal the file stem
skill: nda-review                   # must equal the skill folder name
description: One-line purpose, usually citing a test-plan.md scenario.
synthetic: >
  All parties, names, and facts are fully synthetic test data authored for
  DE-231. Not a real document, not legal advice, not attorney work product.
prompt: |
  The instruction sent ahead of the document (perspective, question, etc.).
skill_inputs:                       # bound via skill_inputs on chat-send;
  perspective: mutual               # required inputs MUST be bound or the
  document: Provided in the message below.   # gateway 400s (SkillInputMissing)
# model: smart                      # optional per-fixture override
---
<the synthetic document text>
```

The message sent is `prompt + "\n\n---\n\n" + document`. Note that skill-input
bindings are a *validation gate* (ADR 0007): the starter skills' bodies contain
no `{{var}}` placeholders, so document text must live in the message content,
and required inputs still need non-empty bindings.

**Fixtures are synthetic test data.** They must contain no real names,
companies, or matters (use obviously synthetic parties — "Meridian Holdings
LLC", "Atlas Biotech Inc"). They are attorney-reviewable but are not attested
skill content; the skills/CONTRIBUTING.md attestation flow does not apply to
them.

## Snapshot format and threshold semantics (schema_version 1)

```json
{
  "schema_version": 1,
  "skill": "nda-review",
  "fixture": "baseline-mutual",
  "status": "provisional",
  "provenance": "Ranges derived from skills/nda-review/SKILL.md (Output) and test-plan.md Scenario 1; NOT observed from a live run.",
  "assertions": {
    "required_sections": ["Bottom line", "Recommended next steps"],
    "metrics": [
      {"id": "critical_issues", "kind": "section_items", "section": "Critical issues", "min": 0, "max": 0},
      {"id": "clause_citations", "kind": "citation_count", "min": 3, "max": null}
    ],
    "min_chars": 800,
    "max_chars": null
  }
}
```

Semantics:

- **All ranges are inclusive**; `"max": null` (or omitted `max`) means
  unbounded above; omitted `min` means 0.
- **`required_sections`** — each entry must match a `##`–`####` heading,
  case-insensitively, by normalized *prefix* (so `"NDA Review"` matches
  `# NDA Review: Meridian Holdings LLC`). List only sections the SKILL.md
  output contract makes unconditional — skills legitimately omit empty
  severity sections ("do not pad").
- **Metric kinds** (extraction heuristics implemented in `golden_lib.py`):
  - `section_items` — items under the named section: child headings if any,
    else top-level bullet/numbered lines. A **missing section counts 0** (use
    `required_sections` to assert presence).
  - `regex_count` — case-insensitive, multiline match count of `pattern`.
  - `citation_count` — clause/section-reference heuristic (`§ 4`, `Section 2`,
    `Clause 3`, `Article 28`, `Sec. 5`, `Paragraph 2`) across the whole output.
  - `blockquote_lines` — lines starting with `>` (contract-qa's mandatory
    verbatim block quotes).
  - `table_rows` — markdown table body rows, header/rule rows excluded
    (dpa-checklist-review's compliance checklist).
- **`min_chars` / `max_chars`** — output length bounds; the cheap guard
  against degenerate/refusal responses.
- A snapshot must be impossible to satisfy with an empty response (the keyless
  inventory test enforces this).

## Provisional vs calibrated — the honesty rule

`"status": "provisional"` means the ranges were derived from the skill's own
documented behavior — the SKILL.md output contract and test-plan.md calibration
bands — because no live run has been recorded yet. Provisional provenance must
say "NOT observed". **Never author "observed" numbers by hand.**

Calibration flow:

1. Run live with `LQ_GOLDEN_RECORD=1` — each fixture writes
   `snapshots/<id>.observed.json` (observed metrics + full response) and range
   misses warn instead of failing.
2. A maintainer reviews the sidecars, folds real observations into the
   `.golden.json` ranges, flips `status` to `"calibrated"`, and deletes the
   sidecars.
3. From then on the nightly gate is calibrated-range regression detection.

Provisional ranges are deliberately wider than the test-plan bands where the
short (~1–2 page) fixtures cannot plausibly hit documented finding densities
that assume 8–30 page instruments.

## Running

Keyless (always green — this is what CI collection relies on):

```bash
pytest tests/golden -q            # live tests skip; inventory tests run
```

Live, against a booted compose stack (`docker compose up -d --wait`) whose
`.env` carries a real provider key:

```bash
export LQ_GOLDEN_LIVE=1
export ANTHROPIC_API_KEY=...        # or OPENAI_API_KEY; gateway must match
export LQ_GOLDEN_PASSWORD=...       # api login (default email admin@lq.ai)
pytest tests/golden -m golden_live -q
```

The login user must have cleared the first-run `must_change_password` gate;
the harness refuses (rather than silently rotating credentials) otherwise.
Useful knobs: `LQ_GOLDEN_API_URL`, `LQ_GOLDEN_EMAIL`, `LQ_GOLDEN_MODEL`
(default `smart`), `LQ_GOLDEN_TIMEOUT`, `LQ_GOLDEN_SKILLS=nda-review,...`
(filter), `LQ_GOLDEN_RECORD=1` (record mode), `LQ_GOLDEN_REPORT_DIR`
(default `./golden-report`).

Every live test writes a machine-readable JSON report (pass or fail) to the
report dir: fixture, skill, routed model/provider, per-check failures with
expected range vs observed value. The nightly workflow attaches these to the
release-blocking issue it files on failure.

## What this harness does not do

- It does not judge legal substance, wording, or correctness — that is
  DE-236's attorney-reviewed acceptance testing.
- It does not run models in per-PR CI; live runs are nightly/dispatch-only
  and require operator-configured provider keys. Without keys the workflow
  reports "skipped: no keys configured" — it never pretends to have run.
- It does not cover the multi-model regression matrix yet (DE-231's full
  scope); the harness runs one alias (`smart` by default) per run, and the
  matrix is a follow-up once snapshots are calibrated.
