"""Matter-number recognizer — M2-B2.

Matter numbers are deployment-specific by nature — every firm has
its own numbering convention. We ship a conservative default set
covering the two most common shapes:

* **Alpha-year-sequence:** ``LQ-2026-0042``, ``ABC-2024-1``,
  ``ABCD-2026-0001``. Two-to-four-letter prefix + 4-digit year +
  hyphenated sequence (≥ 1 digit).
* **Dotted year-sequence:** ``2026.0042``, ``2024.1``. 4-digit year
  + dot + sequence (≥ 1 digit).

Operators whose convention differs (``M-2024-001234`` with longer
sequences, ``YYYY/NNNN`` slash-separated, ``NN-NNNN`` per-jurisdiction
prefix, etc.) should add a deployment-specific recognizer per
``docs/security/anonymization.md``. The default set is deliberately
narrow to keep the false-positive surface small; the operator's guide
is the right place to widen it for their corpus.

Conservative posture: every pattern carries an anchoring
non-digit-adjacent guard so we don't match inside currency strings
($1,200,000.00), ZIP+4 (90210-1234), ISO dates (2024-05-16), or
phone numbers (555-1234).
"""

from __future__ import annotations

from presidio_analyzer import Pattern, PatternRecognizer

# Alpha-year-sequence — ``LQ-2026-0042``-style.
#
# Anchoring:
#   * ``(?<![A-Za-z0-9])`` left boundary so we don't match inside
#     a longer identifier.
#   * ``[A-Z]{2,4}`` prefix — two-to-four uppercase letters. Excludes
#     single-letter prefixes (too noisy) and very long prefixes
#     (rare and ambiguous with words).
#   * ``\d{4}`` year — restricted to plausible years 1900-2099
#     numerically (we use ``(?:19|20)\d{2}``) so phone-shaped
#     ``555-1234`` doesn't accidentally match.
#   * ``\d+`` sequence — at least one digit, no upper bound; matters
#     vary in sequence length.
_ALPHA_YEAR_SEQUENCE_RE = r"(?<![A-Za-z0-9])[A-Z]{2,4}-(?:19|20)\d{2}-\d+(?![\d])"

# Dotted year-sequence — ``2026.0042``-style.
#
# Anchoring:
#   * Year restricted to ``(?:19|20)\d{2}`` to exclude arbitrary
#     4-digit numbers.
#   * The trailing sequence runs to a non-digit-or-dot boundary so
#     we don't grab a longer decimal value (currency, version).
_DOTTED_YEAR_SEQUENCE_RE = r"(?<![\d.])(?:19|20)\d{2}\.\d+(?![\d.])"


class MatterNumberRecognizer(PatternRecognizer):
    """Recognize internal matter numbers as the ``MATTER_NUMBER`` entity.

    Conservative-by-default: only the two most common shapes are
    matched. Operators tune the recognizer set for their numbering
    convention per ``docs/security/anonymization.md``.

    Confidence scores:

    * ``alpha_year_sequence`` — 0.85. The alpha prefix + year + dash
      structure is specific.
    * ``dotted_year_sequence`` — 0.8. Slightly lower because the
      shape can collide with version numbers (``2026.0042`` could in
      principle be a software version, though the year range
      restriction makes it implausible).
    """

    def __init__(self) -> None:
        patterns = [
            Pattern(
                name="alpha_year_sequence",
                regex=_ALPHA_YEAR_SEQUENCE_RE,
                score=0.85,
            ),
            Pattern(
                name="dotted_year_sequence",
                regex=_DOTTED_YEAR_SEQUENCE_RE,
                score=0.8,
            ),
        ]
        super().__init__(
            supported_entity="MATTER_NUMBER",
            name="MatterNumberRecognizer",
            patterns=patterns,
        )
