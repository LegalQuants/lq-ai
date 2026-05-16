"""Custom legal recognizers — populated in M2-B2.

Presidio ships with a default recognizer set (US-centric PII like SSN,
phone, email, credit card, etc.). The legal domain needs more:

* **Contract numbers.** Per-firm or industry-specific patterns
  (``CONTRACT-2025-001``, ``Agreement No. 7-A-238``, etc.).
* **Party block patterns.** The "Party A / Party B" or
  ``[Buyer] / [Seller]`` placeholder shapes used in template
  contracts.
* **Court docket numbers.** ``Case No. 1:24-cv-00123`` and the
  federal/state variants.
* **Bates numbers.** Standard production-set identifiers
  (``ABC000123``).
* Anything else surfaced by the M2-F2 acceptance corpus.

This package is intentionally empty in M2-A3 — the structure is
created so M2-B2 can drop recognizer modules in without a follow-on
scaffold task.
"""
