# Skill-Authoring Guide

This guide documents the conventions for authoring high-quality skills in LQ.AI. It is a working document — the conventions are derived from the patterns established in the M1 starter skills, and they will refine as the skill library grows. Contributions to this guide via PR are welcome.

The audience is anyone authoring a skill containing legal substance: practicing attorneys, legal-ops practitioners, or engineers pairing with attorneys. Engineers contributing pure technical-utility skills should read but not necessarily follow every convention here — many are calibrated to the legal-substance use case.

For the contribution process (claim, draft, attest, review, merge), see [`skills/CONTRIBUTING.md`](../skills/CONTRIBUTING.md). This guide focuses on **how to author the skill itself** — what goes in `SKILL.md`, what goes in `reference/`, what goes in `examples/`, and what conventions the project expects.

---

## Skill anatomy

A skill is a folder. The structure:

```
my-skill/
├── SKILL.md              # Required. Main instruction file with frontmatter.
├── reference/            # Optional. Reference material the skill cites.
│   ├── severity_rubric.md
│   ├── report_structure.md
│   └── ...
├── examples/             # Required for review. Worked examples.
│   ├── example_perspective_a.md
│   └── example_perspective_b.md
└── scripts/              # Rare. Executable helpers (Python).
    └── ...
```

`SKILL.md` is the operational instruction the model executes when the skill is attached to a chat. Everything in `SKILL.md` becomes part of the prompt; everything in `reference/` is optionally surfaced when the skill's workflow references it. `examples/` are documentation for users and reviewers; they do not become part of the prompt by default.

**Where skills live.** Built-in skills are filesystem-canonical under `skills/<slug>/SKILL.md` in this repo. Community skills come from the [`LegalQuants/lq-skills`](https://github.com/LegalQuants/lq-skills) git submodule mounted at `skills/community/` — **empty on a fresh clone until you run `git submodule update --init --remote skills/community`**. At startup the loader (`api/app/skills/loader.py`) walks built-in skills first, then community skills, with **built-in winning on slug collision**. User- and team-authored skills are a separate path entirely: they live in the `user_skills` database table (created via the wizard UI or `POST /api/v1/user-skills`), not on the filesystem — see [User-scope skills](#user-scope-skills-slash_alias-forked_from-and-capture-from-chat-wave-d2) below.

---

## SKILL.md frontmatter

Every skill's `SKILL.md` starts with YAML frontmatter. The fields:

```yaml
---
name: my-skill-name
description: One-sentence description of when this skill should be applied.
lq_ai:
  title: My Skill Title
  version: 1.0.0
  author: <Your name or LegalQuants>
  tags: [contracts, nda, review]
  jurisdiction: <regime-aware | us | eu | global | other>
  trigger_examples:
    - "..."
  inputs:
    required:
      - name: document
        type: document
        description: ...
    optional:
      - name: perspective
        type: enum
        values: [discloser, recipient, mutual]
        description: ...
  output_format: report     # report | table | issues_list | redline
  minimum_inference_tier: 2 # optional; defaults to no minimum
  ensemble_verification: true  # optional; M2-D1; default false
  use_organization_profile: true   # default true
  is_organization_profile: false   # singleton; only true on the org profile
  self_improvement: false   # default false for v1.0.0 skills
---
```

### Required fields

- **`name`** — kebab-case, globally unique within the skill library. Used as the folder name and the skill's identifier. Match the folder name exactly.
- **`description`** — one sentence. Used by the application and by the model itself to decide when the skill applies. Should be specific enough to differentiate from similar skills (e.g., "Reviews mutual or unilateral NDAs for unusual provisions" not just "Reviews NDAs").
- **`lq_ai.title`** — human-readable display name. Used in the UI.
- **`lq_ai.version`** — semver. `1.0.0` for first stable release.
- **`lq_ai.author`** — your name (or a co-authoring pair, separated by " and "), or "LegalQuants" for skills authored by the project team.
- **`lq_ai.tags`** — array of tags for skill discovery. See the [tag conventions](#tag-conventions) section below.
- **`lq_ai.jurisdiction`** — what jurisdiction the skill is calibrated to. The parser treats this as a free-form string; the M1 corpus uses a range of values (`us`, `US-default`, `agnostic`, `regime-aware`, etc.). The conventional values to prefer:
  - `us` — US-law-focused.
  - `eu` — EU-focused.
  - `regime-aware` — the skill takes a `regulatory_regime` input or similar to handle multiple regimes.
  - `global` (or `agnostic`) — explicitly jurisdiction-agnostic (rare; most skills are at minimum US-law-defaults).
  - `other` — for specific jurisdictions (Brazil, India, etc.); spell out in skill body.
- **`lq_ai.trigger_examples`** — at least three example prompts that should trigger this skill. The application uses these for skill matching; the model uses them to disambiguate between skills.
- **`lq_ai.inputs`** — required and optional inputs (see [Input design](#input-design) below).
- **`lq_ai.output_format`** — the conventional values are `report` (default markdown), `table` (structured grid for Tabular Review), `issues_list` (structured JSON for issue-tracker piping), and `redline` (Word tracked-changes mode). The frontmatter parser treats this field as a free-form string (the M1 starter skills predate this guide and use a wider range of values — e.g. `markdown`, `structured_checklist`, `adaptive`); only `table` is load-bearing. New skills should prefer the conventional values above, but the loader will not reject an unrecognized one. See `api/app/skills/schema.py`.

### Optional fields

- **`lq_ai.minimum_inference_tier`** — refuses to run if the chat's routed Inference Tier is below this. Use for skills that handle particularly sensitive content; default is no minimum.
- **`lq_ai.ensemble_verification`** — when `true`, the Citation Engine runs **Stage 4 (ensemble verification)** on every citation the model produces while this skill is applied. Stage 4 dispatches the paraphrase judge in parallel across N models (configured deployment-side in `gateway.yaml`'s `citation_engine.ensemble_verification.judge_models`) and aggregates the verdicts under the operator-chosen rule (`strict` = all judges must agree; `majority` = simple majority wins). The persisted citation row carries `verification_method='ensemble_strict'` or `'ensemble_majority'` plus the maximum tier across the judge ensemble. Use for skills whose output is especially high-stakes (regulatory filings, board materials) and where multi-model agreement materially raises confidence. Default `false`. NOTE: ensemble verification implies each citation is sent to N providers; the privacy envelope is the *weakest* tier in the configured judge set (e.g., a Tier 4 commercial-cloud judge bumps the envelope to Tier 4 even if the primary judge is Tier 3 ZDR-enterprise). The `message_citations.tier_envelope` audit column captures this per row.
- **`lq_ai.use_organization_profile`** — defaults to `true`. Set to `false` only for skills that should run independent of organization-specific context (rare).
- **`lq_ai.is_organization_profile`** — set to `true` only for the singleton Organization Profile skill. Every other skill leaves this `false` or omits it.
- **`lq_ai.self_improvement`** — defaults to `false` for v1.0.0 skills. Self-improvement is a deferred enhancement; v1.0.0 skills are stable artifacts under semver, not learning systems.
- **`lq_ai.columns`** — required when `output_format: table`; ignored otherwise. List of `{name, query, ensemble_verification?, minimum_inference_tier?}` specs. See [Table-mode skills](#table-mode-skills) below.

### Table-mode skills

Setting `output_format: table` opts the skill into the Tabular / Multi-Document Review surface (M3-C, see [PRD §3.14](PRD.md#314-tabular--multi-document-review-m3)). A table-mode skill produces a row-per-document × column-per-spec grid; each cell is a Citation-Engine-grounded extraction. The frontmatter needs a `columns` block:

```yaml
output_format: table
columns:
  - name: Term
    query: What is the term length of this agreement?
  - name: Survival
    query: What confidentiality obligations survive termination?
    ensemble_verification: true   # cell-level override
  - name: Governing Law
    query: What jurisdiction governs this agreement?
    minimum_inference_tier: 3     # cell-level override
```

**Required per column:** `name` (the grid header) + `query` (the per-row prompt instantiated against each document).

**Optional per column:** `ensemble_verification` and `minimum_inference_tier` override the skill-level fields. Use the overrides sparingly — high-stakes columns (e.g., survival periods, indemnification caps) benefit from the extra rigor of Stage 4 ensemble verification or a Tier 4+ floor; routine columns should inherit the skill defaults to keep cost predictable.

**Constraints:**

- `columns` must be non-empty when `output_format: table`. The skill loader rejects malformed table skills at load time (WARNING in container logs, skill skipped).
- Every cell is a string in v0.3.0; column types (number / date / boolean) are a deferred enhancement filed at Phase C close if user-attorney walkthrough surfaces the need.
- Bulk operations (M3-C4) run on top of a tabular execution's grid — they don't change the column spec; they spawn sibling executions.

The reference skill at [`skills/contract-snapshot/SKILL.md`](../skills/contract-snapshot/SKILL.md) demonstrates the four-column NDA grid (Term / Survival / Carveouts / Governing Law) with two per-column overrides — fork it as a starting point for your own contract types.

### Tag conventions

Tags are used for skill discovery and for grouping in the Skill Library UI. Use lowercase, hyphenated, specific. The conventions established by M1:

- **Domain tags:** `contracts`, `privacy`, `regulatory`, `compliance`, `corporate`, `employment`, `ip`, `litigation` (rarely; out of scope for v1).
- **Document-type tags:** `nda`, `msa`, `dpa`, `policy`, `disclaimer`, `agreement`, `memo`, `alert`.
- **Operation tags:** `review`, `qa`, `extraction`, `transformation`, `triage`, `drafting`, `comparison`.
- **Audience tags:** `customer-perspective`, `vendor-perspective`, `non-legal-audience`, `executive`.
- **Capability tags:** `meta` (for meta-skills like Skill Creator), `prompt-engineering`, `due-diligence`.

Skills typically carry 3–6 tags. Too few makes them hard to discover; too many dilutes the discovery signal.

---

## Input design

Inputs are the most consequential design choice in a skill. The patterns from M1:

### Required inputs are minimal

A skill should require only what it cannot do without. For most skills, this is the document being analyzed (or in some cases, no required inputs at all — the skill operates conversationally).

```yaml
inputs:
  required:
    - name: document
      type: document
      description: The contract to review.
```

Avoid requiring inputs that "would be nice to have." If the skill can produce useful output with reasonable defaults, the input belongs in `optional`, not `required`.

### Optional inputs change *analytical depth*, not just *report format*

This is the most important convention from the M1 starter skills. Optional inputs should be evaluated against the test:

> *"Does providing this input change the substance of the analysis, not just the presentation?"*

Examples of well-designed optional inputs:

- **NDA Review's `perspective`** (`discloser | recipient | mutual`) — changes which provisions are favorable, which severity calibrations apply, what the recommended language looks like. The substance of the analysis differs; the report shape is similar across perspectives.
- **DPA Checklist Review's `regulatory_regime`** (`gdpr | us-state-privacy | hipaa-baa | general-commercial`) — changes which checklist items apply, which red flags are critical vs. minor, what the operational checklist for compliance looks like. Substance changes.
- **MSA Review's `prior_agreements`** (text or attached files) — changes the calibration of "is this provision unusual" by anchoring against the user's actual prior practice. Substance changes.
- **Action Items from Client Alert's `applicable_jurisdictions`** — filters the extracted action items to those applicable to the user's footprint. Items not surfaced are a substantive change, not a presentation change.

Examples of inputs that *don't* meet the test (and shouldn't be optional inputs — they should be inferred or omitted):

- "Verbose mode." If verbosity changes only how much text the report contains without changing what the report identifies, it's presentation, not substance.
- "Include disclaimer at the bottom." Style preference; not a skill input.
- "Show me severity scores in red." UI preference; not a skill input.

### Default behavior should be honest about defaults

When optional inputs are not provided, the skill should:

1. Use a default value or generic calibration.
2. Note the default explicitly in the report ("Analyzed from a generic commercial-counterparty perspective; specify a perspective for tailored analysis.").
3. Flag where the absence of the input genuinely limits the analysis ("Without a specified regulatory regime, regime-specific compliance gaps are not evaluated.").

The user should always know when the skill's analysis is calibrated to their inputs versus running on defaults.

### Input naming

- **`document`** for the primary document being analyzed.
- **`perspective`** for review skills with side-of-the-deal perspective branching.
- **`regulatory_regime`** for skills with regime-specific calibration.
- **`prior_agreements`** for skills that benchmark against the user's own prior practice.
- **`audience`** for transformation skills (rewriting for executive vs. sales team vs. customer-facing).
- **`jurisdiction`** for skills that handle multiple jurisdictions and need to know which applies.

Match these conventions when your skill has the same kind of input. Diverge with intent — divergent naming makes skill chaining harder.

---

## SKILL.md body structure

The body of `SKILL.md` follows a consistent structure across the M1 starter skills. The sections, in order:

### 1. Opening paragraph (no header)

One to three sentences setting up what the skill does. Direct, operational. Not a marketing description; this paragraph is part of the model's prompt.

> *"Conduct a triage review of a non-disclosure agreement for unusual provisions, perspective-calibrated risks, and recommended position. Output is a structured markdown report; ..."*

### 2. "When this skill applies"

Describes the trigger conditions in operational terms. Not a list of trigger examples (those are in frontmatter); this is the substantive scoping.

> *"Apply when the user provides an NDA or confidentiality agreement and asks for a review, redline, or risk assessment. Common triggers: ..."*

### 3. "When this skill does NOT apply"

Equally important. The skill should be explicit about what it does not handle so it doesn't run on inputs it isn't calibrated for.

> *"Do not apply when: the document is not an NDA (e.g., it's an MSA with confidentiality clauses — the MSA Review skills handle that). ..."*

### 4. "Inputs"

Describes the inputs and how they affect the analysis. Mirrors the frontmatter but in prose, with the substantive impact of each optional input spelled out.

> *"`perspective` materially affects the analysis. From the discloser's perspective, the skill calibrates as follows: ..."*

### 5. "Workflow"

The operational flow the model follows. Numbered steps, with sub-steps where useful. This is the most consequential section of the skill — it's what the model actually does.

> *"Step 1: ...
> Step 2: ...
> Step 3: ..."*

The workflow should be specific enough that two people reading the same `SKILL.md` would produce the same output on the same input, but not so prescriptive that it breaks under reasonable variations in input.

### 6. "Output"

Describes the output format. For `output_format: report` skills, this is a markdown structure with section headings. For `output_format: table` and `output_format: issues_list` skills, this is the schema.

> *"Output structure:
> 
> ```markdown
> # NDA Review: <document name>
> 
> **Perspective:** [from input]
> ...
> 
> ## Bottom line
> [Two-three sentences leading with recommendation, not analysis.]
> 
> ## Findings
> ..."*

The "Bottom line opens with recommendation, not analysis" convention applies broadly — readers' attention is at the top.

### 7. "Edge cases and refusals"

Specific situations the skill should handle differently. Refusals (situations where the skill should explicitly decline) are valuable — they prevent the skill from running when it shouldn't.

> *"- The document is not in English: stop and ask the user to confirm whether the analysis should proceed in the document's language; the skill is not validated for non-English documents.
> - The document references external materials the user hasn't provided: note the references; recommend the user provide them; do not invent the missing content."*

### 8. "What this skill does not do"

Explicit enumeration of out-of-scope items. This is conservative-posture; it tells the user when to escalate.

> *"This skill does not:
> - Provide enforceability opinions on specific provisions.
> - Substitute for review by qualified legal counsel.
> - Make jurisdiction-specific assertions outside the skill's documented jurisdiction calibration.
> ..."*

### 9. (Optional) "Reference materials"

Pointers to files in `reference/` the skill draws on.

> *"This skill references:
> - `reference/severity_rubric.md` — Critical / Material / Minor calibration.
> - `reference/report_structure.md` — output format conventions.
> ..."*

### 10. (Optional) "Examples"

Pointers to files in `examples/`. Useful for skills with perspective branching or regime selection.

---

## Severity rubric (for review skills)

Review skills (NDA, MSA, DPA, etc.) use a three-tier severity rubric: **Critical / Material / Minor**. The conventions:

- **Critical** — issue requires escalation to expert legal counsel before the user proceeds. Examples: missing IP indemnification clause in a vendor agreement; one-way confidentiality where mutual was expected; unlimited liability for the customer; ML training rights on customer data without opt-out.
- **Material** — issue should be addressed in negotiation but does not necessarily require escalation. Examples: liability cap below market; survival period unusually long; jurisdiction or governing law unfavorable; lack of right to audit.
- **Minor** — issue is worth flagging for the user's awareness but does not warrant active negotiation in most cases. Examples: stylistic concerns in clause drafting; non-material differences from prior practice; minor ambiguities that are unlikely to become operative.

The rubric should be calibrated and documented in `reference/severity_rubric.md`. The calibration should reflect actual practice, not theoretical exposure — if a "critical" rating triggers on every routine NDA, the rubric is uncalibrated and the skill is not useful.

**Calibration check expectation:** when authoring a review skill, run it against at least three real (anonymized) documents in scope and confirm the severity distribution makes operational sense. A 30-NDA test corpus that produces 50 critical findings is uncalibrated; a corpus that produces 5–10 material findings and 20–30 minor flags is in the right zone.

---

## Conservative posture

Skills do not assert legal substance they cannot back up. The conventions:

- **Skills surface patterns, not opinions.** "This clause is unusual relative to market" not "this clause is unenforceable."
- **Skills defer enforceability questions.** Enforceability depends on jurisdiction, fact pattern, and case law that a skill cannot fully evaluate. Flag the question; recommend escalation.
- **Skills do not invent statutory citations.** If a citation is not in the source document or in the skill's reference materials, the skill does not include it.
- **Skills explicitly enumerate "what this skill does not do."** This is a feature, not a defensive disclaimer. It tells users when to escalate to expert legal counsel.
- **Skills with perspective branching apply the user's stated perspective consistently.** A skill running from the customer's perspective should not occasionally lapse into vendor-favorable analysis.
- **Skills handling sensitive regimes (HIPAA, GDPR, FedRAMP, etc.) explicitly note the limits of the analysis.** "This skill applies HIPAA BAA pattern checking; it does not constitute a HIPAA compliance audit."

The conservative posture is what makes skills usable in real practice. A skill that overclaims is worse than a skill that underclaims — overclaim leads users to rely on output they shouldn't.

---

## Optional-input pattern: changing analytical depth

One pattern emerged repeatedly during M1 authoring: the most valuable optional inputs are those that meaningfully change what the skill analyzes, not just how the analysis is presented.

NDA Review's `deal_type` input is a good example. Without it, the skill applies generic NDA-review logic. With it (set to "M&A diligence" or "vendor procurement"), the skill applies deal-type-specific calibration:

- M&A diligence NDAs typically have longer-term carveouts for residuals, broader permitted purposes, and more scrutiny of non-solicitation provisions.
- Vendor procurement NDAs typically focus on data security, return/destruction, and supplier-side breach notification.

The deal-type input doesn't change the *report shape* — both still produce the same markdown structure with the same sections. It changes the *analysis substance* — different findings, different severity calibrations, different recommended language.

When designing optional inputs, apply the test: "Would two skill runs on the same document but with different values for this input produce *meaningfully different findings* — not just different report formatting?" If yes, the input is well-designed. If no, the input is presentation-level and should either be removed or moved out of the skill's interface (e.g., to user preferences).

---

## Worked examples

Every skill should have at least one worked example in `examples/`. Examples serve three purposes:

1. **Documentation for users** — show what the skill does on a representative input.
2. **Calibration verification** — running the skill on the example input should produce output close to the documented output. Drift indicates a maintenance issue.
3. **Reviewer reference** — practicing-attorney reviewers can verify the skill's substantive output matches their expectations on the same inputs.

Examples are markdown files with a structure like:

```markdown
# Example: NDA Review from Recipient Perspective

## Input

[Description of the input scenario; the document used; the perspective and other inputs.]

## Output

[The actual output the skill produced on this input.]

## What this example demonstrates

[A few bullets explaining what the example illustrates: severity calibration, perspective handling, edge case treatment.]
```

For skills with perspective branching, multiple examples (one per perspective) are strongly preferred. For skills with regime selection, multiple examples (one per regime) are strongly preferred. The Action Items from Client Alert skill ships with three examples (clear-deadline alert, vague alert, multi-jurisdiction alert) demonstrating different output shapes from the same skill.

---

## Reference materials

For complex skills, the body of `SKILL.md` becomes unwieldy if every operational detail lives in it. Pull operational checklists, severity rubrics, and substantive content into `reference/` files.

Conventions from the contract-review skills:

- **`reference/severity_rubric.md`** — the Critical / Material / Minor calibration with examples for each tier.
- **`reference/report_structure.md`** — the output format conventions (section headings, severity-tag formatting, citation conventions).
- **`reference/perspective_lens.md`** — for skills with perspective branching, how each perspective changes the analysis.
- **`reference/recommended_language.md`** — preferred clause language for the perspective the skill represents.
- **`reference/<regime>_requirements.md`** — for regime-aware skills, the specific requirements per regime.
- **`reference/<scenario>_handling.md`** — for skills with multiple scenarios, the per-scenario logic.

The body of `SKILL.md` references these files: "See `reference/severity_rubric.md` for the calibration tiers and examples." The model loads the referenced files as part of the skill's operational context.

The DPA Checklist Review skill is a good example of multi-regime reference structure — separate `reference/gdpr_requirements.md`, `reference/us_state_privacy_requirements.md`, `reference/hipaa_baa_requirements.md`, etc.

---

## Output format conventions

Different `output_format` values have different conventions:

### `output_format: report` (default)

Markdown output structured by sections. Conventions:

- **First section is "Bottom line"** — two-three sentences leading with recommendation, not analysis. Reader's attention is at the top.
- **Sections use `##` headings** for major sections, `###` for sub-sections.
- **Severity-tagged findings** use a consistent prefix: `**[Critical]**`, `**[Material]**`, `**[Minor]**`.
- **Citations** use the application's citation syntax: `[Doc1, p.3]` or similar; the Citation Engine handles rendering.
- **Recommended language** is set off in code blocks or block quotes for easy copying.

### `output_format: table`

Structured grid output. Used by Tabular Review and similar bulk-document skills. Conventions:

- **Each row is a document**; each column is a question or extraction target.
- **Cells contain citation-grounded answers**, with a "verify" affordance if the extraction is uncertain.
- **Failed extractions render as "not found"**, never as a confident wrong answer.
- **Cost-preview** before execution for large grids (200+ docs × 10+ columns).

### `output_format: issues_list`

Structured JSON output following the `issues_list` schema. Suitable for piping into a tracker (Jira, Linear, GitHub Issues). Conventions:

- **Each issue is an object** with `id`, `severity`, `title`, `description`, `recommendation`, `source_citation`, `status` fields.
- **Severity uses the same Critical / Material / Minor rubric** as the markdown report variant.
- **The web UI renders the issues as a sortable table** with bulk export.

### `output_format: redline`

Tracked-changes output for Word documents. Used by skills that produce direct redlines. Conventions:

- **Output is structured tracked changes** that the Word add-in applies to the document.
- **Each change has a comment** explaining the rationale.
- **Severity is reflected in comment formatting** (color-coding by severity).

---

## User-scope skills: slash_alias, forked_from, and capture-from-chat (Wave D.2)

This section documents features added in Wave D.2 for user-authored skills stored in the `user_skills` table (per ADR 0012). These features apply to skills created through the skill wizard UI or the `POST /api/v1/user-skills` endpoint — not to filesystem-canonical built-ins.

### slash_alias semantics

A `slash_alias` is an optional chat-composer trigger for a user skill. When set, the user can type the alias (e.g., `/nda`) in the chat input to attach the skill without typing the full slug.

**Validation rules:**

- Format: `/` followed by 1–32 lowercase alphanumeric or dash characters. Regex: `^/[a-z0-9-]{1,32}$`.
- Unique per owner within the active (non-archived) set. Two different users may use the same alias; the constraint is per-owner.
- Collision returns 422: `"slash_alias '<alias>' is already used by another of your skills."` The error is surfaced inline near the alias field in the wizard (`lq-ai-wizard-slash-alias`), not in the generic save-error banner.

**Wizard field:** `data-testid="lq-ai-wizard-slash-alias"` (referenced in `wave-d2-skill-creator.cy.ts`).

**Autocomplete behavior:** `GET /api/v1/skills/autocomplete?q=<prefix>` ranks matches with slash-alias prefix > slug prefix > title substring. An empty `q` returns the user's most-recently-used skills. See `docs/api/backend-openapi.yaml` (after Wave 9.1) for the full endpoint shape.

### forked_from semantics

`forked_from` records the slug of the source skill when a row was created by forking a built-in or another user skill via the skill detail page. It is:

- Set on create only (from the fork request or the wizard's capture flow).
- Read-only after creation.
- Stored as plain text — the source may be a filesystem-canonical built-in with no corresponding DB row (per ADR 0004).
- Displayed in the wizard and the skill detail page to communicate provenance.
- Carried in the `POST /api/v1/user-skills` request body as `forked_from`.

### source_message_id semantics

`source_message_id` is a request-body field on `POST /api/v1/user-skills` used when a skill is created from the capture-from-chat flow (see below). It is not stored as a dedicated column; it is written into the `audit_log.details` bag as `user_message_id` on the `user_skill.created` action. This gives the audit trail provenance: the capture can be traced back to the assistant message that seeded it.

The receipts builder (Wave 7.2) joins `audit_log` rows to `chat_messages` via `details->>'user_message_id'` to correlate receipt entries with their originating user message.

### Capture-from-chat flow

The capture-from-chat flow lets a user turn any assistant message into a new user skill without leaving the chat.

**Entry point:** each assistant message in the chat view exposes an inline capture button (`data-testid="lq-ai-message-capture-inline"`). Clicking it opens the capture modal.

**Modal (`data-testid="lq-ai-capture-skill-modal"`):**

- Pre-populates the skill name and body from the assistant message content.
- The user fills in a display name, optional slash alias, and optional description.
- Two actions:
  - **Save** — calls `POST /api/v1/user-skills` with `source_message_id` set to the assistant message's UUID; creates the skill immediately and closes the modal.
  - **Edit in wizard** — carries the same draft to the full skill wizard (`/lq-ai/skills/new`) for further editing before saving.

**Audit trail:** the created skill's audit row (`user_skill.created`) carries `user_message_id` in `details`, pointing to the originating assistant message. See the `audit_log` `details` JSONB conventions in `docs/db-schema.md`.

**Endpoint reference:** `POST /api/v1/user-skills` — see `docs/api/backend-openapi.yaml` for the full request/response shape including `slash_alias`, `forked_from`, and `source_message_id` fields.

## Self-improvement (deferred)

The frontmatter field `lq_ai.self_improvement` defaults to `false` for v1.0.0 skills. Self-improvement — skills that ask the user for feedback after execution and update themselves — is a deferred enhancement. The reasoning:

- v1.0.0 skills are stable artifacts under semver. Users rely on them; they should not change unexpectedly.
- Self-improvement requires audit trails and review processes that don't exist in v1.
- Skills that "learn" without explicit user guidance can drift in ways that are hard to detect and worse to fix.

For v1.0.0, skills are stable. Improvements happen through versioned releases, not through silent self-modification. If you have a self-improvement use case in mind, file an issue describing it; it's a candidate for the deferred-enhancements list.

---

## Skill chaining

Multiple skills can be attached to a single chat. The application concatenates their `SKILL.md` instructions in attach order, with delimiters. The model is instructed to apply all skills.

Skill-chaining considerations:

- **Skills should not assume they're running alone.** Even single-purpose skills may be chained with another skill in production.
- **Skills should not contradict each other within the same chain.** If you author a skill that conflicts with a starter skill (different severity rubric, different perspective convention), document the conflict and recommend not chaining.
- **Skills with `output_format` other than `report` interact specifically with the application UI.** A `table` skill chained with a `report` skill produces the union; the application shows both.
- **The Organization Profile is always at the head of the prompt** unless a skill sets `use_organization_profile: false`. The Profile shapes everything downstream.

Skill chaining is a power-user feature; most skills should work well alone and not assume chaining context.

---

## Versioning

Skills carry semver in `lq_ai.version`:

- **`1.0.0`** — first stable release.
- **`1.0.x`** — patch updates: typo fixes, reference material updates, additional examples, expanded edge cases.
- **`1.x.0`** — minor updates: new optional input, new perspective, new output mode.
- **`2.0.0`** — major updates: removed inputs, changed defaults, materially different output structure.

Bump versions per the conventions when you update a skill. Update the `version` field; describe the change in the commit message; reference the prior version's behavior if the change is a behavior change.

---

## Authoring checklist

Before submitting a skill PR, verify:

- [ ] `SKILL.md` has complete frontmatter (every applicable `lq_ai:` field).
- [ ] `name` matches the folder name.
- [ ] `version` is `1.0.0` (or appropriately incremented for an update).
- [ ] `description` is one sentence and specific enough to differentiate from similar skills.
- [ ] `trigger_examples` has at least three examples.
- [ ] Inputs are designed per the [Input design](#input-design) conventions — required inputs minimal, optional inputs change analytical depth.
- [ ] Body covers: when this applies, when not to apply, inputs, workflow, output format, edge cases, what this does not do.
- [ ] At least one worked example in `examples/`. For skills with perspective branching or regime selection, multiple examples (one per branch).
- [ ] Reference materials in `reference/` for complex skills (severity rubric, report structure, etc.).
- [ ] Conservative posture maintained throughout — no enforceability opinions, no invented citations, explicit "what this does not do."
- [ ] Severity rubric (for review skills) is calibrated against real documents.
- [ ] `self_improvement: false` for v1.0.0 skills unless there's a specific deferred-enhancement-candidate use case.
- [ ] Skill runs on a representative input and produces output matching the documented examples.
- [ ] PR description includes the [attestation](../skills/CONTRIBUTING.md#3-attest) for skills containing legal substance.

---

## Examples to read

The M1 starter skills demonstrate the conventions documented above. To read them in priority order based on the skill you're authoring:

| If you're authoring | Read these first |
|---|---|
| A new contract review skill | NDA Review (perspective branching, severity rubric); MSA Review — SaaS (full-scale review, Playbook integration) |
| A new privacy / regulatory review skill | DPA Checklist Review (regime selection, multi-regime reference structure); Vendor Privacy Policy First Pass (triage shape) |
| A new Q&A skill | Contract QA (adaptive Q&A; six question types) |
| A new extraction skill | Action Items from Client Alert (deadline categorization, jurisdiction filtering) |
| A new transformation skill | Comms Improver (audience calibration, preservation-of-meaning) |
| A new meta-skill | Skill Creator (conversation-driven authoring); Enhance Prompt (prompt rewriting) |

The skill folders are at `skills/<skill-name>/`. Open `SKILL.md` first, then the worked examples, then the reference files.

---

*This guide is a working document. Conventions refine as the skill library grows. Contributions to this guide via PR are welcome — the same DCO sign-off applies.*
