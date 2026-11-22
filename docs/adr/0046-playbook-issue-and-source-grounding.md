# ADR 0046: Preserve issue identity and source-grounded playbook output

Status: Coverage decision accepted by the maintainer on 2026-11-22;
implementation and legal taxonomy await review/attestation.

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

Derive quotations and offsets from actual contiguous document slices.
Normalize only PDF whitespace/hyphen wrapping for matching; publish the exact
original slice. Require complete sentence/list-item boundaries rather than
fragments that omit conditions or negation. Ignore model offsets, rebase
verified offsets across chunks, and deduplicate overlapping-span repeats.
Re-extract unsupported quotes once using the original source, supplying
complete surrounding source context when the rejected fragment is locatable. If repair
fails or loses the requested issues, fail generation; do not stitch or invent
text. A complete sentence may support multiple issues with overlapping source
spans when that is necessary to retain its conditions and context.

Generate descriptions/redline strategies from the selected standard alone.
Describe fallback differences without asserting legal acceptability. Batch a
separate consistency check against the selected source(s), with strict boolean
verdicts and source-matched evidence. Missing, duplicate, malformed, unanchored,
or unsupported verdicts fall back to literal source text and neutral review
instructions. A deterministic expiry/survival inversion guard applies even
when the model approves a description. This is a consistency check, not a
legal verification guarantee; the attorney still reviews the output.

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
