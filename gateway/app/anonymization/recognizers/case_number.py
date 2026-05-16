"""Case-number recognizer — M2-B2.

Matches the citation forms that show up in legal prose with enough
structural specificity that the false-positive rate stays low:

* **Canonical reporter cites** — ``Party v. Party, NNN Reporter NNN
  (Court Year)``. The reporter abbreviation is the load-bearing
  signal; we enumerate the common federal + state reporters
  explicitly so bare ``v.``  in prose ("John v. the system") doesn't
  trigger.
* **Docket numbers** — ``Case No. 1:24-cv-00123``, ``No. 24-1234``.
  The case-prefix + colon/hyphen-separated digits structure is also
  highly specific.

We intentionally **don't** match bare case captions (``Smith v.
Jones`` without a reporter or docket). The false-positive surface in
prose is too high — every ``X v. Y`` rhetorical comparison would
hit. Operators whose corpus benefits from caption-only matching can
add a deployment-specific recognizer per
``docs/security/anonymization.md``.

Reporter list focuses on what produces practical matches in modern
US legal practice. We don't try to cover every historical reporter
(``Wheat.``, ``Cranch.``, ``Dall.``) — those are vanishingly rare in
contemporary briefs and adding them increases the regex's
maintenance surface without helping the M2-F2 acceptance corpus.
"""

from __future__ import annotations

from presidio_analyzer import Pattern, PatternRecognizer

# Reporter abbreviations covered by the canonical-cite pattern.
# The order in the alternation matters in regex: longer/more-specific
# alternatives must precede shorter ones (``F\.Supp\.3d`` before
# ``F\.Supp\.``) so the engine commits to the longest match.
_FEDERAL_REPORTERS = (
    r"F\.Supp\.3d"
    r"|F\.Supp\.2d"
    r"|F\.Supp\."
    r"|F\.4th"
    r"|F\.3d"
    r"|F\.2d"
    r"|F\."
    r"|U\.S\."
    r"|S\.Ct\."
    r"|L\.Ed\.2d"
    r"|L\.Ed\."
)

_STATE_REPORTERS = (
    # West regional reporters
    r"A\.3d|A\.2d|A\."
    r"|N\.E\.3d|N\.E\.2d|N\.E\."
    r"|N\.W\.3d|N\.W\.2d|N\.W\."
    r"|P\.3d|P\.2d|P\."
    r"|S\.E\.3d|S\.E\.2d|S\.E\."
    r"|S\.W\.3d|S\.W\.2d|S\.W\."
    r"|So\.3d|So\.2d|So\."
    # Common official state reporters (small set; operators can extend)
    r"|Cal\.App\.(?:5th|4th|3d|2d)?|Cal\.Rptr\.(?:3d|2d)?"
    r"|N\.Y\.S\.(?:3d|2d)?"
    r"|Ill\.App\.(?:3d|2d)?"
)

_REPORTER_GROUP = rf"(?:{_FEDERAL_REPORTERS}|{_STATE_REPORTERS})"

# Capitalized party-name component. Allows multi-word parties like
# "United States" and "Doe Industries Inc." plus the "In re X" idiom.
# Conservative: requires the leading word to start with an uppercase
# letter so we don't drag in mid-sentence verbs.
_PARTY = r"(?:In re\s+)?[A-Z][A-Za-z.'\-]+(?:\s+(?:of\s+)?[A-Z][A-Za-z.'\-]+)*"

# Canonical reporter-cite pattern:
#   <Party> v. <Party>, <Volume> <Reporter> <Page>[, <Pinpoint>] [(Court Year) | (Year)]
# Where the trailing parenthetical is optional in unusual styles but the
# volume + reporter + page triple is mandatory. That triple is what
# anchors the false-positive rate at near-zero on legal prose.
_CANONICAL_CITE_RE = (
    rf"{_PARTY}\s+v\.\s+{_PARTY},\s+"
    rf"\d+\s+{_REPORTER_GROUP}\s+\d+"
    r"(?:,\s*\d+)?"
    r"(?:\s+\([^)]+\))?"
)

# "In re X, vol Reporter page (Court Year)" — the bankruptcy /
# probate / class-action idiom that has no ``v.`` separator. Same
# reporter-anchored structure as the canonical pattern; the leading
# ``In re`` is the discriminator that prevents collision with the
# main pattern's ``<Party> v. <Party>`` form.
_IN_RE_CITE_RE = (
    r"In re\s+[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+)*,\s+"
    rf"\d+\s+{_REPORTER_GROUP}\s+\d+"
    r"(?:,\s*\d+)?"
    r"(?:\s+\([^)]+\))?"
)

# Docket-number pattern: optionally preceded by "Case ", then "No. ",
# then either ``<int>:<2-digit>-<2-4 alpha>-<3-6 digits>`` (federal-
# court docket form) OR ``<2-3 alpha?>-<3-6 digits>`` (short appellate
# docket). The ``(?<!\w)`` word-boundary lookbehind prevents matches
# inside longer identifiers.
_DOCKET_RE = (
    r"(?<!\w)(?:Case\s+)?No\.\s+"
    r"(?:\d{1,2}:\d{2}-[a-z]{2,4}-\d{3,6}|\d{2,4}-[a-z]{2,4}-\d{3,6}|\d{2,4}-\d{3,6})"
)


class CaseNumberRecognizer(PatternRecognizer):
    """Recognize legal case citations as the ``CASE_NUMBER`` entity.

    Two pattern families with different confidence scores:

    * Canonical reporter cite — 0.9. The reporter + volume + page
      structure is highly specific; false positives are essentially
      zero on legal prose.
    * Docket number — 0.85. The case-prefix + colon/hyphen + digits
      structure is also specific; the slight score reduction reflects
      the small risk of confusion with similarly-structured
      non-docket identifiers (e.g. an arbitrary "No. 24-1234" tag).
    """

    def __init__(self) -> None:
        patterns = [
            Pattern(
                name="canonical_reporter_cite",
                regex=_CANONICAL_CITE_RE,
                score=0.9,
            ),
            Pattern(
                name="in_re_reporter_cite",
                regex=_IN_RE_CITE_RE,
                score=0.9,
            ),
            Pattern(
                name="docket_number",
                regex=_DOCKET_RE,
                score=0.85,
            ),
        ]
        super().__init__(
            supported_entity="CASE_NUMBER",
            name="CaseNumberRecognizer",
            patterns=patterns,
        )
