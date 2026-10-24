---
name: comms-improver
description: Use when the user has a piece of legal-jargon-heavy text and wants it rewritten in plain language for a specified non-legal audience. Common scenarios — email to a business stakeholder, legal disclaimer for a customer-facing page, memo for a non-legal audience, explanation of a contract clause for a deal team, summary of a regulatory development for an executive briefing. Produces the rewritten text plus a brief explanation of what was changed and why, including any preservation-of-meaning concerns where the rewrite required interpretation. Does not draft from scratch; the input is text that exists.
lq_ai:
  title: Comms Improver
  version: 1.0.0
  author: LegalQuants
  tags: [communications, plain-language, transformation, drafting]
  jurisdiction: agnostic
  trigger_examples:
    - "rewrite this in plain language"
    - "make this less lawyerly"
    - "translate this for the sales team"
    - "explain this clause to the deal team"
    - "simplify this disclaimer"
    - "make this readable for a non-lawyer"
  inputs:
    required:
      - name: text
        type: text
        description: The legal text to rewrite. Can be an email draft, contract clause, disclaimer, memo, regulatory summary, or any other legal text. The skill works from text that exists; it does not draft from scratch.
      - name: audience
        type: text
        description: Who the rewrite is for. Examples — "executive briefing for CEO and CFO; one-paragraph version for board read-out", "sales team; need them to understand what they can and can't say to prospects", "customer-facing disclaimer for product page; non-technical consumers", "deal team (commercial counsel and product manager); explaining a specific contract clause", "engineering team; explaining a privacy obligation that affects feature design", "vendor counterparty's procurement contact; not a lawyer". The audience determines tone, length, terminology, and detail level. If not provided, the skill asks before proceeding.
    optional:
      - name: purpose
        type: text
        description: What the rewrite is intended to accomplish. Examples — "decision input — they need to decide whether to approve", "informational only — they just need to understand the obligation", "action prompt — they need to do something specific", "risk warning — they need to take a particular concern seriously". Affects how the rewrite frames the bottom line.
      - name: length_constraint
        type: text
        description: Length constraints if any. Examples — "one paragraph max", "single sentence", "fits in a Slack message", "two pages or less". If not provided, the skill matches the original's approximate length adjusted for audience.
      - name: tone
        type: text
        description: Specific tone preference if any. Examples — "warm and conversational", "neutral and businesslike", "urgent — they need to take this seriously", "reassuring — they're worried and we're calming them down". If not provided, the skill defaults to neutral businesslike.
      - name: preserve_specific_terms
        type: text
        description: Specific terms or phrases that must be preserved exactly (legal terms of art, defined contract terms, regulatory language that has specific legal meaning). Example — "preserve 'material breach' as written; that's a defined term that affects remedies". Without this input, the skill may simplify legal terms whose precise wording matters; the explanation flags where simplification occurred.
  output_format: markdown
  self_improvement: false
---

# Comms Improver

Rewrite legal text in plain language for a specified non-legal audience. The output preserves meaning while changing form: shorter sentences, common words instead of jargon, active voice instead of passive, concrete examples instead of abstract formulations. The skill is transformation, not drafting from scratch.

This skill is for the everyday in-house counsel task of translating between legal precision and non-legal accessibility. Lawyers spend significant time rewriting their own work — or reviewing others' rewrites — for executive readouts, sales communications, customer disclosures, deal-team briefings, and engineering specs. The skill does this rewriting (or supports the user's rewriting) while flagging where translation involved interpretation.

## When this skill applies

Apply when the user has legal-jargon-heavy text and wants it rewritten for a specified non-legal audience. Common inputs:

- Email drafts to non-legal business stakeholders.
- Contract clauses to be explained to a deal team or product team.
- Legal disclaimers to be rewritten for customer-facing surfaces.
- Memos to be summarized for executive readouts.
- Regulatory developments to be communicated to affected business functions.
- Compliance obligations to be translated for the operational owner.

Do not apply when:

- **The user wants to draft text from scratch.** Out of scope — the skill rewrites existing text. Drafting from scratch is a different shape (drafting skill candidate; deferred enhancement).
- **The user wants to translate between languages** (e.g., English to Spanish). Out of scope.
- **The user wants legal review of someone else's plain-language rewrite.** Out of scope; that's review, not rewriting. The user can paste both versions and ask whether the rewrite preserves meaning, but the skill is calibrated for the rewriting task.
- **The text is already plain language and the user wants a different style.** Out of scope; that's editing for style, not rewriting for accessibility.
- **The user wants to "make this sound more legal" or "add legal weight."** Out of scope — the skill goes from legal to plain, not the other direction. Adding legal precision to plain text is a different task with different risks (introducing meaning the original didn't carry).

## Inputs

The skill requires the text and the audience. If audience is not provided:

> "Before I rewrite, who is this for? The audience determines tone, length, and detail level. Examples:
> - 'Executive readout for CEO/CFO — single paragraph'
> - 'Sales team — they need to understand what they can say to prospects'
> - 'Customer-facing disclaimer — non-technical consumers'
> - 'Deal team — commercial counsel plus product manager'
> - 'Engineering team — explaining a privacy obligation that affects design'"

Optional inputs (`purpose`, `length_constraint`, `tone`, `preserve_specific_terms`) refine the output. The most consequential is `preserve_specific_terms` — without it, the skill may simplify legal terms whose precise wording carries legal weight. The skill flags where simplification occurred so the user can verify.

## Workflow

The workflow has three steps.

### Step 1: Read the original carefully

Before rewriting:

- Identify what the text is doing — informing, advising, requiring, warning, summarizing, etc.
- Identify the legal terms of art, defined terms, and regulatory language that may have precise meaning. These are the candidates for `preserve_specific_terms` treatment.
- Identify ambiguities, conditional structures, and qualifications that require interpretation to translate. ("subject to applicable law and regulatory guidance" might mean something specific in context, or might be CYA language that adds little.)
- Identify the bottom-line point. Plain-language rewrites lead with the bottom line; legal-jargon-heavy text often buries it.

Use `reference/legal_to_plain_patterns.md` for common transformations.

### Step 2: Rewrite for the audience

Apply transformations appropriate to the audience:

- **Sentence length:** legal writing often has long compound sentences; plain language uses shorter sentences (typically 15-20 words average).
- **Voice:** prefer active over passive ("we must notify the customer" vs. "the customer shall be notified").
- **Word choice:** replace legal terms with everyday equivalents where the precise meaning is preserved (for terms where precise meaning matters, see "preserve specific terms" below).
- **Concrete over abstract:** "if a customer asks for their data, we have 30 days to respond" vs. "data subject access requests must be fulfilled within applicable statutory timeframes."
- **Direct over indirect:** "you can't share customer data with third parties" vs. "third-party data sharing is impermissible absent the requisite authorizations."
- **Lead with the bottom line:** the audience's first read should answer their primary question.

Calibrate the level of transformation to the audience:

- **Executive briefing audiences** want the bottom line in one sentence and the reasoning in two-three more. Detail goes in an appendix or follow-up if requested.
- **Operational owners** (sales, engineering, support) want enough detail to act on the obligation. Include the specific actions and the boundary conditions ("yes you can do X; no you can't do Y; if you encounter Z, escalate to legal").
- **Customer-facing audiences** want the substance without the legalese. Use second person ("you can request your data") and direct verbs ("we delete your data within 30 days of your request").
- **Deal-team audiences** (commercial counsel, product) often need the legal substance preserved but in efficient prose. Less compression than executive briefing, more compression than the original legal text.

When `preserve_specific_terms` is provided, those terms appear verbatim in the rewrite. Without `preserve_specific_terms`, the skill applies judgment about which terms to preserve and flags choices in the explanation.

### Step 3: Produce the rewrite plus explanation

Produce the rewritten text first, followed by a brief explanation of what was changed and why. The explanation:

- Identifies the structural changes (sentence length, ordering, lead with bottom line, etc.).
- Notes any terms that were simplified and confirms whether the simplification preserved meaning.
- Flags any preservation-of-meaning concerns — places where the original was ambiguous, where simplification required interpretation, or where the user should verify the rewrite captures their intent.
- Suggests follow-up rewrites if the audience pushes back or asks questions.

The explanation should be substantially shorter than the rewrite. The rewrite is the deliverable; the explanation is the show-your-work.

## Output

Produce the output in markdown with this structure:

```markdown
# Comms Improver: [Brief description of the text]

**Audience:** [from input]
**Purpose:** [from input, or inferred]
**Length constraint:** [from input, or "matched to original"]
**Tone:** [from input, or "neutral businesslike"]

## Rewritten text

[The rewrite. Set off as a code block or quote block so the user can copy it directly. Multiple variants if the user wants alternatives — e.g., "one-sentence version" and "one-paragraph version" for executive briefing audiences.]

## What was changed

[Brief explanation of structural changes — sentence shortening, voice changes, ordering, etc. 2-4 bullets typical.]

## Terms simplified or preserved

[For terms that have legal weight: which were preserved verbatim, which were simplified and why. If `preserve_specific_terms` was provided, confirm those terms appear verbatim. If not provided, flag which terms might need preservation depending on the use case.]

## Preservation-of-meaning concerns

[Any places where the rewrite required interpretation, where the original was ambiguous, or where the user should verify the rewrite captures intent. If none, this section can be a single sentence: "No preservation-of-meaning concerns; the rewrite is a straightforward transformation of the original."]

## Suggested follow-ups

[Brief — typically 1-3 items. What to do if the audience pushes back, how to handle common follow-up questions, whether a longer or shorter version might be useful.]
```

The output should be proportional to the input. A one-paragraph original produces a brief output (rewrite plus a few-sentence explanation). A multi-page memo produces a longer output. Don't pad short rewrites; don't truncate substantial ones.

## Edge cases and refusals

- **Original text is itself unclear or ambiguous.** The skill rewrites what's there, flags the ambiguity, and notes that the rewrite cannot be clearer than the source. If the user wants disambiguation, that requires substantive understanding of the source's intent — the skill can ask, or recommend the user clarify the original first.
- **Audience is too vague to calibrate** ("just make it simpler"). The skill produces a default audience calibration (neutral businesslike, single-paragraph, mid-detail) and notes the assumption.
- **Original text is very short** (a sentence). The skill rewrites and notes that for short text the explanation may be longer than the rewrite — that's appropriate; the explanation surfaces what was preserved.
- **Original text contains specific legal language the user is going to send to a lawyer counterparty.** Plain-language rewrite may be inappropriate; the original may have been drafted with that audience in mind. The skill notes this concern and asks the user to confirm the audience.
- **Original text contains text the user shouldn't be sending at all** (legally inadvisable, factually inaccurate, or exposing the user's organization to risk). The skill rewrites for plain language but flags substantive concerns separately. The skill is not a substantive review; if substantive concerns are visible, they're flagged but the user is responsible for substantive review.
- **Audience is hostile or adversarial** (counterparty in a dispute, regulator, opposing counsel). Plain-language rewrites for adversarial audiences require careful handling — simplification can lose hedging that's protective. The skill notes this consideration and recommends user verification.

## What this skill does not do

- **Draft text from scratch.** The skill rewrites existing text.
- **Substantive review.** Plain-language rewrite is a transformation, not a substantive check on whether the underlying advice is correct.
- **Translation between languages.** Out of scope.
- **Style editing for already-plain text.** Out of scope.
- **Generate "more legal" versions of plain text.** Out of scope; that's a different skill with different risks.
- **Multiple-audience optimization in a single rewrite.** Each rewrite targets one audience. If the user has multiple audiences, run the skill multiple times.

## Reference materials

- `reference/legal_to_plain_patterns.md` — common transformations from legal jargon to plain language.
- `reference/audience_calibration.md` — how to calibrate tone, length, and detail for different audience types.
- `examples/example_executive_briefing.md` — worked example: contract concern translated for CEO/CFO.
- `examples/example_sales_team.md` — worked example: regulatory restriction translated for sales team.
- `examples/example_customer_disclaimer.md` — worked example: legal disclaimer rewritten for customer-facing page.

## Acceptance

Attorney-reviewed acceptance results: `acceptance/results.md`.
