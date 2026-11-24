# ADR 0046: Preserve issue identity and source-grounded playbook output

Status: Coverage decision accepted by the maintainer on 2026-11-22;
implementation and legal taxonomy await review/attestation.

On 2026-11-25 the maintainer confirmed retaining the existing drafting
behavior and fixing the specific observed defects. There is no source-only
default, new manual workflow, or independently configured judge in this change.

## Context

The live Qwen/nomic walkthrough on PR #419 produced 17 positions. It merged
definitions with exclusions and permitted with compelled disclosures, folded
recipient liability into remedies, published stitched excerpts and inaccurate
offsets, and generated a survival description contrary to its standard.
Centroid thresholds alone did not establish semantic equivalence.

## Decision

Preserve coherent issues and genuine outliers. The historical 5–10 count is
a diagnostic, not a cap or a reason to discard clauses. Use a bounded set of
known equivalent issue labels before centroid merging or low-support folding.
Different identities cannot merge/fold, even with identical embeddings.
Unknown labels remain independent. Keep the original pre-fold standard and
label selection. This registry is conservative and visible work product;
expanding it needs examples showing equivalent issues and separate controls.

The next walkthrough exposed an incorrect initial label: a technical-security
clause was called a disclosure prohibition. For those known labels, explicit
encryption/access-control wording without a direct disclosure restriction or
care benchmark becomes Security Safeguards. A combined restriction-and-security
clause remains a separate combined issue; source text and offsets are unchanged.

Derive quotations and offsets from actual contiguous document slices.
Normalize only PDF whitespace/hyphen wrapping for matching; publish the exact
original slice. Require complete sentence/list-item boundaries rather than
fragments that omit conditions or negation. Ignore model offsets, rebase
verified offsets across chunks, and deduplicate overlapping-span repeats.
An ordinary PDF line wrap is not a new clause boundary; numbered section
headings and sentence/list-item boundaries provide the structural signal.
Re-extract unsupported quotes once using the original source, supplying
complete surrounding source context when the rejected fragment is locatable. If repair
fails or loses the requested issues, fail generation; do not stitch or invent
text. A complete sentence may support multiple issues with overlapping source
spans when that is necessary to retain its conditions and context.

Generate descriptions/redline strategies from the selected standard alone.
Describe fallback differences without asserting legal acceptability. Batch a
separate consistency check in bounded six-item batches against the selected source(s), with strict boolean
verdicts and source-matched evidence. Missing, duplicate, malformed, unanchored,
or unsupported verdicts fall back to literal source text and neutral review
instructions. A deterministic expiry/survival inversion guard applies even
when the model approves a description. This is a consistency check, not a
legal verification guarantee; the attorney still reviews the output.

Use bounded explicit source facts to correct the observed reversed comparisons:
simple agreement durations, during-term versus post-expiry general-information
protection, and the actor acknowledging irreparable harm. These comparisons
remain readable descriptions of the alternative versus the standard, and
outrank a mistaken model verdict. Conditional or ambiguous facts are not guessed;
other descriptions keep the normal drafting/check/fallback path. Tier writers
and checkers receive the issue and explicit source roles. Introduced court-type
qualifiers absent from both sources are rejected.

The 2026-11-25 rerun corrected those failures but exposed four further metadata
mismatches: a no-license clause described as a license grant, own-information
care described as customary care, a conditional federal-court fallback described
as an unrestricted alternative, and contractual exclusions given an unsupported
legal rationale. Targeted checks reject those phrases through the existing
source-text/neutral-strategy fallback, even after an affirmative model verdict.
Supported generated prose remains unchanged. Both completed attempts and their
exact failed comparisons are retained as evidence and regression fixtures.

The first full-corpus consistency request exhausted its 8,192-token response
budget and conservatively replaced all prose with source text. Bound each
check to six items and 4,096 response tokens; an invalid or truncated batch
falls back only for its own items. Returned IDs from another batch are ignored.

The per-Easy-Playbook worker timeout is configurable (60–7200 seconds,
default 900). Other task timeouts are unchanged. A slower local-model
walkthrough may use a longer recorded timeout; this does not establish the
default-model performance target.

## Verification

Regression cases include high-similarity distinct concepts, unknown outliers,
same-identity aliases, quoted source coordinates, lost-negation fragments,
stitching repairs and failures, selected-standard-only description prompts,
and false/malformed/unanchored consistency verdicts. Captured live outputs
provide a diagnostic replay; a fresh full live walkthrough is separate
acceptance evidence. No position-count ceiling substitutes for these checks.
