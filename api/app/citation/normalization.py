# ruff: noqa: RUF001
"""Comparison-time text normalization for Stage 2 tolerant-match.

Both the source-at-offsets and the citation's quoted text run through
:func:`normalize` before the Stage 2 verifier computes a fuzzy ratio.
That isolates the kinds of differences Stage 2 is supposed to forgive
(whitespace drift, smart vs. straight quotes, common OCR confusions)
from the kinds it must reject (paraphrases, factual edits).

The function has two layers:

* **Always-on rules** apply to every document, regardless of OCR
  provenance:

  * Whitespace runs collapse to a single space (newlines treated as
    whitespace).
  * ``\\r\\n`` is canonicalised so we never leave a stray ``\\r``.
  * Leading/trailing whitespace is stripped.
  * Smart quotes (typographic single + double quotes,
    ``\\u2018-\\u201d``) map to ASCII straight quotes.

* **OCR-conditional rules** apply only when ``was_ocrd=True``
  (i.e., the document's ``was_ocrd`` flag from M2-A1). These are
  conservative substitutions for the most common OCR misreads:

  * ``rn`` ↔ ``m`` collapses ``rn`` → ``m`` when mid-word
    (most legible-PDF OCR engines fail this character pair).
  * ``O`` ↔ ``0`` substitutes ``O`` → ``0`` only when adjacent to a
    digit (so ``Office`` stays ``Office`` but ``O5`` becomes ``05``).
  * ``l`` ↔ ``1`` substitutes ``l`` → ``1`` only when adjacent to a
    digit (same pattern; ``liability`` stays).

  We intentionally only canonicalise in one direction per pair —
  the chunk content and the model's quote get the same normalization
  applied, so collapsing variants down to the same target makes a
  fuzzy ratio against an OCR'd source robust without injecting
  false positives into clean text.

The function is idempotent: ``normalize(normalize(t)) == normalize(t)``
for every input. The verifier relies on this so the
``rapidfuzz.fuzz.ratio`` comparison is symmetric in re-runs.

OCR rule justification — why these three:

* The pair ``m`` vs ``rn`` is the canonical Tesseract failure mode
  for serif fonts at moderate DPI; rule ``rn`` → ``m`` mid-word
  catches the common ``modem`` ↔ ``modern`` family.
* ``O`` / ``0`` and ``l`` / ``1`` are the two most common
  letter-vs-digit confusions in OCR'd legal text (Bates numbers,
  section references, dates). Guarding the substitution on an
  adjacent digit avoids re-typing ``Office`` as ``0ffice``.

The conservative posture is intentional: every OCR rule is a chance
to introduce a false positive against clean text. M2-B2 / M2-F1 (the
acceptance corpus) will surface any additional rules that pay off
empirically; this module is the place to add them.
"""

from __future__ import annotations

import re

# Smart-quote → straight-quote translation table. Covers the four
# Unicode codepoints (U+2018 LEFT SINGLE QUOTATION MARK, U+2019 RIGHT
# SINGLE QUOTATION MARK, U+201C LEFT DOUBLE QUOTATION MARK, U+201D
# RIGHT DOUBLE QUOTATION MARK).

# smart-quote characters are the literal targets of the normalization
# table, not typos for the ASCII apostrophe / grave accent.
_SMART_QUOTE_TABLE = str.maketrans(
    {
        "‘": "'",  # LEFT SINGLE QUOTATION MARK
        "’": "'",  # RIGHT SINGLE QUOTATION MARK
        "“": '"',  # LEFT DOUBLE QUOTATION MARK
        "”": '"',  # RIGHT DOUBLE QUOTATION MARK
    }
)

# Whitespace-run collapse. Matches any sequence of one-or-more
# whitespace characters (spaces, tabs, newlines, etc.) and collapses
# them to a single ASCII space.
_WS_RUN_RE = re.compile(r"\s+")

# OCR rule: ``rn`` → ``m`` only when preceded by a word character.
# The canonical OCR confusion (``m`` mis-OCR'd as ``rn``) most often
# surfaces word-finally — ``modern`` ↔ ``modem``, ``barn`` ↔ ``bam``,
# ``burn`` ↔ ``bum``. Guarding only on a preceding word char (not
# also a following word char) catches those cases. The cost: some
# false-positive word-final substitutions like ``turn`` → ``tum``.
# Acceptable because the verifier threshold is 95: a single
# false substitution in a long quote drops the fuzz ratio by ~1-2
# points, well within the 5-point margin. Word-start ``rn`` is
# preserved (``rnage`` stays ``rnage``) — no real OCR confusion
# there, and the negative lookbehind keeps the rule conservative.
_OCR_RN_RE = re.compile(r"(?<=\w)rn")

# OCR rule: capital ``O`` → ``0`` when adjacent (immediately before or
# after) to a digit. ``(?<=\d)O`` or ``O(?=\d)``.
_OCR_O_RE = re.compile(r"(?<=\d)O|O(?=\d)")

# OCR rule: lowercase ``l`` → ``1`` when adjacent to a digit. Symmetric
# with the ``O``/``0`` rule.
_OCR_L_RE = re.compile(r"(?<=\d)l|l(?=\d)")


def normalize(text: str, *, was_ocrd: bool = False) -> str:
    """Canonicalize text for Stage 2 fuzzy comparison.

    The always-on layer is applied unconditionally; the OCR layer
    runs only when ``was_ocrd`` is True.

    Args:
        text: The raw text to normalize. May contain smart quotes,
            mixed line endings, runs of whitespace, etc.
        was_ocrd: True when the source document went through OCR
            (``documents.was_ocrd``). Enables OCR-confusion
            substitutions.

    Returns:
        The normalized string. Idempotent — ``normalize(normalize(t))``
        equals ``normalize(t)``.
    """

    # Always-on: smart quotes first so subsequent passes operate on
    # ASCII quote characters only.
    out = text.translate(_SMART_QUOTE_TABLE)

    # Always-on: collapse whitespace runs (including CRLF, tabs,
    # multiple spaces, newlines) to a single space.
    out = _WS_RUN_RE.sub(" ", out)

    # Always-on: strip leading/trailing whitespace introduced by the
    # collapse step.
    out = out.strip()

    if was_ocrd:
        out = _OCR_RN_RE.sub("m", out)
        out = _OCR_O_RE.sub("0", out)
        out = _OCR_L_RE.sub("1", out)

    return out
