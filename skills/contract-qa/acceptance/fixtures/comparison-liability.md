---
fixture: comparison-liability
skill: contract-qa
description: >
  Type C comparison/unusualness question with a perspective input: is
  the liability cap unusual? Expects a verdict word, a quoted clause,
  and a perspective-calibrated read (SKILL.md Type C format).
synthetic: >
  All parties, names, addresses, and facts are fully synthetic test data
  authored for DE-231. Not a real document, not legal advice, not
  attorney work product.
prompt: |
  We are the customer under the attached agreement. Is the limitation
  of liability in this agreement unusual, and in whose favor does it
  run?
skill_inputs:
  document: Provided in full in the message below.
  question: Is the limitation of liability in this agreement unusual, and in whose favor does it run?
  perspective: our_side
---

# DATA SERVICES AGREEMENT

This Data Services Agreement (this "Agreement") is entered into as of
March 18, 2026 between **Larkspur Financial Services Inc.**, a Delaware
corporation ("Customer"), and **Cobalt Peak Software Inc.**, a Delaware
corporation ("Provider").

**1. Services.** Provider will provide Customer with access to its
hosted transaction-monitoring platform and related support services.

**2. Fees.** Customer pays an annual platform fee of $180,000, invoiced
annually in advance, net thirty (30) days.

**3. Term.** Two (2) years from the Effective Date, renewing annually
unless either party gives sixty (60) days' notice of non-renewal.

**4. Data.** Customer retains ownership of Customer Data. Provider may
use Customer Data solely to provide the services.

**5. Warranties.** Provider warrants the services will conform
materially to the documentation. All other warranties are disclaimed.

**6. Indemnification.** Provider will defend Customer against
third-party IP-infringement claims arising from the platform. Customer
will defend Provider against claims arising from Customer Data.

**7. Limitation of Liability.**
(a) Neither party is liable for indirect, incidental, special, or
consequential damages.
(b) Provider's aggregate liability under this Agreement is capped at
one (1) month of platform fees, regardless of the form of action.
(c) Customer's aggregate liability is capped at two (2) times the
annual platform fee.
(d) The caps in this Section 7 apply to all claims, including breach of
confidentiality, breach of Section 4 (Data), and each party's
indemnification obligations.

**8. Confidentiality.** Each party protects the other's non-public
information with reasonable care for three (3) years after disclosure.

**9. Termination.** Either party may terminate for material breach
uncured within thirty (30) days of notice. Customer may terminate for
convenience on ninety (90) days' notice without refund of prepaid fees.

**10. General.** Governed by Delaware law; venue Wilmington, Delaware.
Entire agreement; written amendments only.

**LARKSPUR FINANCIAL SERVICES INC.**   **COBALT PEAK SOFTWARE INC.**
By: /s/ Emerson Hypothetical           By: /s/ Morgan Sample
Title: SVP Procurement                 Title: Chief Revenue Officer
