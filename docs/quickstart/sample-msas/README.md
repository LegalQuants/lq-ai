# Sample MSA corpus

Five synthetic mutual Master Services Agreements (MSAs) designed to exercise LQ.AI's Easy Playbook wizard (M3-A6) and to validate that the wizard's clustering algorithm generalizes beyond the NDA corpus in `docs/quickstart/sample-ndas/`. They share a common base structure (engagement, payment, IP, warranties, indemnification, limitation of liability, term and termination, confidentiality, governing law, miscellaneous) but vary intentionally on five deal axes that real MSA negotiations turn on.

These MSAs are **synthetic and for testing only**. They are not real agreements between real parties and should not be used as drafting templates for actual transactions. Names, addresses, and signatories are invented.

## Why this corpus exists separately from the NDAs

The NDA corpus exercises the wizard on a shorter, single-topic contract type with five well-bounded variant axes. The MSA corpus tests:

- **Different shape of contract.** MSAs reference SOWs, have payment/milestone structures, allocate IP across three categories, and balance risk across indemnification + limitation of liability — a different cognitive shape than an NDA's confidentiality-focused brief.
- **Generalization of clustering.** If the wizard's centroid-based label-merge algorithm (`docs/PRD.md DE-???` once filed) produces a tight ~15-20-position playbook on the NDA corpus but balloons to 40+ positions or misses obvious merges on the MSA corpus, that's a signal the algorithm overfits to NDA-shape clauses.
- **Different vocabulary across positions.** "Payment Terms," "Indemnification," "Limitation of Liability," "IP Ownership" — the wizard needs to handle longer, more structurally varied clauses than NDAs typically carry.

## How to use

### With the Easy Playbook wizard

1. Log in to LQ.AI.
2. Open **Playbooks** → click **Generate from prior agreements**.
3. Pick contract type `MSA` (or `MSA-Services`).
4. Upload all five PDFs from this directory.
5. Click **Generate playbook**. The wizard uploads → polls until each file is parsed → kicks off generation → polls every 5 seconds until the worker completes.
6. The Step 3 inline editor should surface positions across each of the five variant axes documented below.
7. Edit / approve / save.

Typical end-to-end runtime against the default `smart` alias: 4-8 minutes for the 5-document MSA corpus (longer than the NDA corpus because MSAs are longer documents and produce more clauses per document).

### With the built-in `msa-saas-review` or `msa-commercial-purchase-review` playbooks

These synthetic MSAs are **commercial-services** in shape (vendor provides consulting/professional services to customer under SOWs) — distinct from the M3-A5 SaaS-subscription MSA built-in (which assumes a vendor-hosted product subscription) and from the commercial-purchase built-in (which assumes goods-supply). The built-in playbooks may run against these but the operator should expect lower match rates than against form contracts the built-ins were calibrated against. The corpus is primarily for wizard testing.

## The 5 variant axes

Each MSA holds the other axes roughly constant and varies on the listed dimensions:

| MSA | Payment terms | IP ownership of Deliverables | Warranty scope | Termination triggers | Indemnification scope |
|---|---|---|---|---|---|
| **1. Acme ↔ Northstar** | Net 30, 1.5%/mo late fee | Work-for-hire (Customer owns); Vendor retains background IP | Express + implied (non-disclaimable) | For-cause + 60-day convenience | Mutual, capped at 12-mo SOW fees |
| **2. Blackbird ↔ Zenith** | Net 45, no late fee | Vendor retains; Customer perpetual non-exclusive license | Express only; "as is" otherwise | For-cause only (no convenience) | One-way (Vendor → Customer), IP-indemnity uncapped |
| **3. Cypress ↔ Pinnacle** | Net 60, can invoice in advance | Vendor retains; Customer broader perpetual license (no resale) | Express only; full disclaimer of implied | For-cause + 90-day convenience + change-of-control | Mutual, IP cap-tied, willful-misconduct carve-out |
| **4. Delta ↔ Foxtrot** | Net 15, milestone-based | Work-for-hire (Customer owns); Vendor retains background IP | Express + fitness-for-intended-purpose + compliance | For-cause + 30-day convenience | One-way (Vendor → Customer), capped at 2x SOW fees |
| **5. Evergreen ↔ Horizon** | Monthly retainer + milestone-based | Customer owns specific deliverables; **joint ownership** of jointly-developed IP | Express + compliance + security; non-disclaimable implied | For-cause + 180-day convenience + auto-renewal opt-out (180-day notice) | Mutual including mutual IP indemnity, capped at 24-mo fees |

### What a good wizard run should produce

A wizard run against this corpus should surface (at minimum) these five core positions, each with the modal phrasing as `standard_language` and the off-modal variants as fallback tiers:

1. **Payment terms** — modal probably Net 30 (most common across the corpus), with Net 45/60 as fallbacks and milestone-based as a distinct fallback.
2. **IP ownership of Deliverables** — modal likely "Customer owns work-for-hire" or "Vendor retains with license," depending on which appears more frequently in the corpus.
3. **Warranty scope** — modal likely "express plus implied" with "express only / as-is disclaimer" as fallbacks.
4. **Termination triggers** — modal likely "for-cause plus convenience with N-day notice" with "for-cause only" and "change-of-control" as fallbacks.
5. **Indemnification scope + cap** — modal likely "mutual capped at 12-mo fees" with "one-way uncapped IP" and "2x cap" as fallbacks.

Plus other meaningful clauses the corpus carries:
- Limitation of Liability (cap structure varies)
- Confidentiality (term varies 2yr/3yr/5yr/indefinite)
- Governing Law (Delaware predominant, New York as variant)
- Statements of Work / Engagement structure
- Independent Contractor
- Assignment

If the wizard *misses* one of these axes — e.g., conflates "payment terms" with "fees and expenses," or splits "IP ownership" across three orphan positions — that's a real signal worth filing as a clustering-quality bug.

## What this corpus does NOT test

- **Wide-form-variation handling.** All five MSAs are commercial-services MSAs with consistent boilerplate structure (engagement → payment → IP → warranties → indemnification → LoL → term → confidentiality → governing law → miscellaneous). A real operator's library has wide form variation across vendors, decades, and deal types.
- **SaaS-specific or goods-supply MSAs.** This corpus is professional-services-shaped. Wizard runs on SaaS subscription MSAs or goods-supply MSAs may surface different clause families.
- **Edge cases in extraction.** E.g., MSAs where the warranty section is split across multiple sections, or where IP ownership is buried in an SOW exhibit rather than the master agreement.
- **Very long agreements.** Each MSA is ~3-4 pages. The 50,000-character chunking limit in `extractor.py` only kicks in on much longer documents (e.g., 50-page MSAs with extensive exhibits).

For a "harder" smoke test, mix in a real-form MSA or two and observe whether the wizard's clusters degrade gracefully.

## Source files

- `msa-N-*.md` — the markdown source for each agreement. Edit these and re-run `render.py` to regenerate PDFs.
- `msa-N-*.pdf` — the rendered PDFs the wizard ingests. Roughly 115-125 KB each, 2-3 pages.
- `render.py` — the markdown→HTML→Chrome-headless→PDF rendering script. Mirrors the NDA-corpus `render.py` exactly.

## See also

- The companion NDA corpus at `docs/quickstart/sample-ndas/`.
- The two built-in MSA playbooks (`skills/msa-review-saas`, `skills/msa-review-commercial-purchase` — seeded via migration 0033).
- The M3-A6 Easy Playbook wizard (`web/src/routes/lq-ai/playbooks/easy/+page.svelte`).
- The clustering algorithm (`api/app/playbooks/easy/clustering.py`).
