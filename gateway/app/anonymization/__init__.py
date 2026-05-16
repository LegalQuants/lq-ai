"""Anonymization Layer — gateway pre/post middleware (PRD §4.7).

Pseudonymizes sensitive entities in outbound LLM requests and rehydrates
the originals on the response path so:

* The model provider only sees pseudonyms (``PERSON_0001``,
  ``ORGANIZATION_0003``, etc.). Real names, account numbers, and other
  PII never leave the deployment's security boundary.
* The user's prose-level reading experience is unchanged — the
  rehydration step on the way back substitutes originals back in
  before the response is returned to the api/.

Per decision M2-1 (locked at M2 kickoff): only chat/skill content is
pseudonymized. Retrieved-document content stays un-pseudonymized so
the existing retrieval surface continues to render real document text
to the user. The alternative (Option A — pseudonymize the document
corpus too) is filed as DE-269 for future consideration.

Module layout:

* :mod:`mapper` — :class:`PseudonymMapper`, the per-request mapping data
  structure (M2-A3; this milestone task).
* :mod:`engine` — :class:`Anonymizer`, the top-level façade that wires
  Presidio's :class:`AnalyzerEngine` + custom legal recognizers + the
  mapper (scaffolded in M2-A3; Presidio integration lands in M2-B3).
* :mod:`recognizers` — custom legal recognizers populated in M2-B2
  (contract numbers, party block patterns, court docket numbers, etc.).

Heavy imports (presidio/spaCy) are deferred to the module that needs
them so the gateway boots even before the spaCy model is downloaded.
The mapper itself is dependency-free and is what M2-A3 ships.
"""

from app.anonymization.mapper import PseudonymMapper

__all__ = ["PseudonymMapper"]
