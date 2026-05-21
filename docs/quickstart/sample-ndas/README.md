# Sample NDA corpus

Five synthetic mutual NDAs designed to exercise LQ.AI's Easy Playbook wizard (M3-A6) and the built-in `nda-review-mutual` skill. They share a common base structure but vary intentionally on five negotiation axes, so the wizard's clustering algorithm has meaningful within-corpus variation to work with — the output should surface each axis as a distinct position with the modal value as the standard and the off-modal variants as fallback tiers.

These NDAs are **synthetic and for testing only**. They are not real agreements between real parties and they should not be used as drafting templates for actual transactions. Names, addresses, and signatories are invented.

## How to use

### With the Easy Playbook wizard

1. Log in to LQ.AI.
2. Open **Playbooks** → click **Generate from prior agreements**.
3. Pick contract type `NDA` (or `NDA — Mutual`).
4. Upload all five PDFs from this directory.
5. Click **Generate playbook**. The wizard uploads → polls until each file is parsed → kicks off generation → polls every 5 seconds until the worker completes.
6. The Step 3 inline editor should surface ~5–10 positions. Expect at least the five variant axes below to appear as distinct positions, each with the modal value in `standard_language` and the off-modal variants in `fallback_tiers`.
7. Edit / approve / save.

Typical end-to-end runtime against the default `smart` alias: 3–6 minutes for the five-document corpus.

### With the built-in `nda-review-mutual` playbook

Upload any one of the five PDFs to a knowledge base, then apply the built-in `NDA — Mutual` playbook against it. The execution result will show how that NDA scores against the curated baseline. Comparing the wizard's auto-generated playbook to the built-in is itself an interesting exercise — they cover similar terrain via different methods.

## The 5 variant axes

Each NDA holds the other axes roughly constant and varies on the listed dimensions:

| NDA | Term | Definition of Confidential Info | Standard of care | Survival of trade secrets | Permitted disclosures |
|---|---|---|---|---|---|
| **1. Acme ↔ Beta** | 3 years | Broad (oral + written, marked-or-not) | Reasonable care | 5 years post-term | Employees + professional advisors |
| **2. Cypress ↔ Delta** | 2 years | Narrow (written + marked only, oral confirmed in 30 days) | Industry standard | Same as general term (no separate survival) | Employees only |
| **3. Echo ↔ Foxtrot** | 5 years | Broad with explicit categories enumerated | Same as own confidential info | Indefinite (for as long as trade-secret status holds) | Employees + advisors + affiliates |
| **4. Gamma ↔ Helix** | 1 year | Broad (oral + written, no marking required) | Highest commercial reasonable care | 3 years post-term | Employees only |
| **5. Indigo ↔ Juniper** | 4 years | Medium (oral confirmed within 30 days) | Reasonable care | Indefinite | Employees + advisors + contractors |

### What a good wizard run should produce

A wizard run against this corpus should surface (at minimum) these five positions, each with:

- **Issue**: a coherent label (e.g., "Term of Agreement," "Definition of Confidential Information").
- **Standard language**: the modal phrasing across the five — usually the value that appears 2-3 times.
- **Fallback tiers**: ranked by acceptability. For "Term," the modal might be 3yr → fallback 1: 2yr → fallback 2: 5yr → fallback 3: 1yr or 4yr.
- **Detection keywords**: tokens that distinguish this clause (e.g., for "Standard of care": "reasonable care," "industry standard," "same care").

If the wizard *misses* an axis — e.g., conflates "permitted disclosures" with "obligations of receiving party" — that's a real signal worth either editing in Step 3 or filing as a clustering-quality bug.

## What this corpus does NOT test

- **Wide-form-variation handling**: the corpus is all mutual NDAs with consistent boilerplate. A real operator's library has form variation (different lawyers, different decades, different deal types) that this corpus doesn't stress.
- **Edge cases in extraction**: e.g., NDAs where the definition is split across multiple sections, or where the standard of care is embedded in the obligations clause without its own heading. The synthetic corpus uses clean section structure.
- **Unilateral NDAs**: all five are mutual. The wizard's clustering on a mixed mutual + unilateral corpus is a separate test.
- **Very long agreements**: each is ~2 pages. The 50,000-character chunking limit in `extractor.py` only kicks in on much longer documents.

For a "harder" smoke test, mix in a real-form NDA or two and observe whether the wizard's clusters degrade gracefully.

## Source files

- `nda-N-*.md` — the markdown source for each agreement. Edit these and re-run `render.py` (in `/tmp/lq-ai-test-ndas/`) to regenerate PDFs.
- `nda-N-*.pdf` — the rendered PDFs the wizard ingests. Roughly 95–110 KB each, 1–2 pages.

## See also

- The two built-in NDA playbooks (`skills/nda-review-mutual` and `skills/nda-review-unilateral` — seeded via migration 0032).
- The M3-A6 Easy Playbook wizard (`web/src/routes/lq-ai/playbooks/easy/+page.svelte`).
- The clustering algorithm (`api/app/playbooks/easy/clustering.py`).
