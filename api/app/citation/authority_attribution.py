"""Deterministic citation-attribution parser for chat authority quotes (DE-370).

Binds each markdown blockquote passage in an assistant answer to nearby
legal-citation references, so that a quote *attributed* to a fetched
authority that cannot be verified against that authority's text can FAIL
the fiduciary gate instead of being silently dropped.

Recognized citation forms (all parsed with bounded, linear-time regexes —
no nested unbounded quantifiers; see the Onyx ReDoS lesson in
``_run/RESEARCH/citation-provenance.md``):

* **US Code** — ``17 U.S.C. § 107``, ``17 USC 107``, ``17 U.S.C. §§ 107-108``
  (``§§`` ranges with numeric endpoints record the endpoints and the numeric
  range).
* **CFR** — ``40 CFR 1500.1``, ``40 C.F.R. § 1500.1``, ``29 C.F.R. part 1910``.
* **EU / CELEX** — raw CELEX ids (``32016R0679``) and EU instrument citations
  that map to a CELEX id *deterministically*: ``Regulation (EU) 2016/679``,
  ``Regulation (EC) No 45/2001``, ``Directive 95/46/EC``,
  ``Directive (EU) 2016/680``, ``Decision (EU) 2015/1814``.  Textual forms
  that would require a name registry (``"the GDPR"``, ``"Article 6(1)(a)
  GDPR"``) are intentionally NOT mapped — guessing would create exactly the
  false-positive FAIL this tier must avoid, so they stay unattributed.

**Window rule** ("nearby"): a citation attributes a blockquote iff it lies
entirely inside the blockquote block itself, or entirely inside the
``ATTRIBUTION_WINDOW_CHARS`` (300) characters of raw assistant text
immediately preceding the block's first line or immediately following the
block's last line.  Both windows are clamped at adjacent blockquote blocks,
so a citation inside (or beyond) a neighboring quote never leaks into this
one's window.  300 chars is roughly two to three sentences — enough for the
common ``"Under 17 U.S.C. § 107, ...:"`` intro line and the trailing
``"— 17 U.S.C. § 107"`` attribution line, without picking up citations from
distant paragraphs.  References are ordered by proximity to the block
(in-block first, then by character distance).

Attribution alone never FAILs anything: the caller
(:func:`app.citation.authority.verify_and_persist_authority_citations`)
only counts an attribution when the parsed reference matches an authority
actually fetched this turn (:func:`reference_matches_external_ref`), so
uploaded-document or caselaw quotes can never FAIL spuriously.

Pure functions, no I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

ATTRIBUTION_WINDOW_CHARS = 300
"""Chars of raw text before/after a blockquote block scanned for citations."""

# ---------------------------------------------------------------------------
# Citation grammars (bounded quantifiers only — ReDoS-safe by construction)
# ---------------------------------------------------------------------------

# "17 U.S.C. § 107" / "17 USC 107" / "17 U. S. C. §§ 107-108".
# The trailing (?!\d) forbids truncating a longer digit run (e.g. never parse
# "§ 1078" as section 107).
_USC_RE = re.compile(
    r"(?<![\w.])"
    r"(?P<title>\d{1,3})\s{0,3}"
    r"U\.?\s{0,2}S\.?\s{0,2}C\.?"
    r"(?:\s{0,3}(?P<sigil>§§|§|[Ss]ections?|[Ss]ecs?\.?))?"
    r"\s{0,3}"
    r"(?P<section>\d{1,5}[a-z]{0,2}(?:[-–—]\d{1,5}[a-z]{0,2}){0,2})"  # noqa: RUF001
    r"(?!\d)"
)

# "40 CFR 1500.1" / "40 C.F.R. § 1500.1" / "29 C.F.R. part 1910".
_CFR_RE = re.compile(
    r"(?<![\w.])"
    r"(?P<title>\d{1,3})\s{0,3}"
    r"C\.?\s{0,2}F\.?\s{0,2}R\.?"
    r"\s{0,3}(?:§§?\s{0,3})?(?:[Pp]arts?\s{1,3})?"
    r"(?P<section>\d{1,5}(?:\.\d{1,4}){0,3})"
    r"(?!\d)"
)

# Raw CELEX id, e.g. "32016R0679": sector digit + 4-digit year + 1-2 letter
# document type + 4-digit number.
_CELEX_RAW_RE = re.compile(r"(?<!\w)(?P<celex>[1-9]\d{4}[A-Z]{1,2}\d{4})(?!\w)")

# EU instrument citations. Mapping to CELEX happens in _map_eu_instrument;
# forms without any EU marker ((EU)/(EC)/(EEC) prefix, "No", or /EC-style
# suffix) are rejected there to avoid parsing prose like "Directive 12/34".
_EU_INSTRUMENT_RE = re.compile(
    r"(?P<type>Regulation|Directive|Decision)\s{1,3}"
    r"(?:\((?P<community>EU|EC|EEC)\)\s{1,3})?"
    r"(?P<no>No\.?\s{1,3})?"
    r"(?P<a>\d{2,4})/(?P<b>\d{1,4})"
    r"(?:/(?P<suffix>EC|EEC|EU))?"
    r"(?!\d)"
)

_EU_TYPE_LETTER = {"Regulation": "R", "Directive": "L", "Decision": "D"}

# ---------------------------------------------------------------------------
# external_ref shape parsers (the shapes actually produced by the gateway
# tool providers: GovInfo package/granule ids, EUR-Lex CELEX ids)
# ---------------------------------------------------------------------------

# GovInfo USCODE package ids: "USCODE-2022-title17"; granule ids append
# subdivision segments, e.g. "USCODE-2022-title17-chap1-sec107".
_USCODE_REF_RE = re.compile(r"^USCODE-\d{4}-title(\d{1,3})(?:-|$)", re.IGNORECASE)
# GovInfo CFR package ids: "CFR-2023-title40" (often "-vol33" etc. appended);
# granules may carry "-part1500" or "-sec1500-1" segments.
_CFR_REF_RE = re.compile(r"^CFR-\d{4}-title(\d{1,3})(?:-|$)", re.IGNORECASE)
_REF_SEC_RE = re.compile(
    r"-sec(\d{1,5}[a-z]{0,2}(?:[-.]\d{1,4}[a-z]{0,2}){0,2})(?:-(?=[a-z])|$)",
    re.IGNORECASE,
)
_REF_PART_RE = re.compile(r"-part(\d{1,5})(?:-|$)", re.IGNORECASE)
# A CELEX-shaped external_ref (EUR-Lex): sector + year + type letters + number.
_CELEX_REF_RE = re.compile(r"^\d{5}[A-Z]{1,2}\d{4}$")


@dataclass(frozen=True, slots=True)
class ParsedAuthorityReference:
    """One recognized legal-citation reference found in the assistant text.

    :attr kind: ``"usc"`` | ``"cfr"`` | ``"celex"``.
    :attr raw: The citation text exactly as written.
    :attr title: USC/CFR title number (leading zeros stripped); ``None`` for CELEX.
    :attr sections: Normalized section tokens, lowercase, en/em dashes and
        (for CFR) dots normalized to ``-`` (``"1500.1"`` → ``"1500-1"``).
    :attr section_range: Inclusive numeric endpoints of a ``§§ X-Y`` range,
        when both endpoints are purely numeric; ``None`` otherwise.
    :attr celex: Canonical uppercase CELEX id for ``kind="celex"``.
    """

    kind: str
    raw: str
    title: str | None = None
    sections: tuple[str, ...] = ()
    section_range: tuple[int, int] | None = None
    celex: str | None = None


@dataclass(frozen=True, slots=True)
class AttributedAuthorityPassage:
    """A blockquote passage with its nearby citation references.

    ``passage`` is byte-identical to the corresponding entry of
    :func:`app.citation.caselaw.extract_blockquote_passages` (same
    line-walk, same join).  ``references`` is ordered by proximity to the
    blockquote (in-block first, then ascending character distance) and
    deduplicated; empty when no recognized citation is nearby — the
    false-positive guard: an unattributed passage never FAILs.
    """

    passage: str
    references: tuple[ParsedAuthorityReference, ...] = field(default=())


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_DASHES_RE = re.compile(r"[–—]")  # noqa: RUF001 — en/em dash normalization is the point


def _parse_usc(m: re.Match[str]) -> ParsedAuthorityReference:
    title = m.group("title").lstrip("0") or "0"
    sigil = (m.group("sigil") or "").lower().rstrip(".")
    token = _DASHES_RE.sub("-", m.group("section").lower())
    plural = sigil in {"§§", "sections", "secs"}
    sections: tuple[str, ...]
    section_range: tuple[int, int] | None = None
    parts = token.split("-")
    all_numeric = len(parts) == 2 and all(p.isdigit() for p in parts)
    # "§§ 107-108" (or the sigil-less "17 USC 107-108") with numeric endpoints
    # is a range; a dashed token with letters ("1681s-2") is a single section.
    if all_numeric and (plural or sigil in {"", "§", "section", "sec"}):
        lo, hi = int(parts[0]), int(parts[1])
        if lo < hi:
            sections = (parts[0], parts[1])
            section_range = (lo, hi)
        else:
            sections = (token,)
    else:
        sections = (token,)
    return ParsedAuthorityReference(
        kind="usc",
        raw=m.group(0),
        title=title,
        sections=sections,
        section_range=section_range,
    )


def _parse_cfr(m: re.Match[str]) -> ParsedAuthorityReference:
    title = m.group("title").lstrip("0") or "0"
    token = m.group("section").lower().replace(".", "-")
    return ParsedAuthorityReference(
        kind="cfr",
        raw=m.group(0),
        title=title,
        sections=(token,),
    )


def _plausible_year(token: str) -> int | None:
    """Return the 4-digit year ``token`` encodes, or None (EU law: 1952+)."""
    if len(token) == 4 and token.isdigit() and 1952 <= int(token) <= 2099:
        return int(token)
    return None


def _map_eu_instrument(m: re.Match[str]) -> str | None:
    """Deterministically map an EU instrument citation to a CELEX id, or None.

    Rules (all deterministic, no name registry):

    * ``No X/YYYY`` (old style, e.g. "Regulation (EC) No 45/2001") — number
      then 4-digit year.
    * first component a 4-digit year (post-2015 style, e.g. "(EU) 2016/679")
      — year then number.
    * second component a 4-digit year — number then year.
    * 2-digit first component with an ``/EC``-style suffix (classic
      directives, e.g. "Directive 95/46/EC") — 19xx year then number.

    Anything else (no EU marker at all, ambiguous year positions, numbers
    that cannot fit CELEX's 4-digit field) returns None — do NOT guess.
    """
    letter = _EU_TYPE_LETTER[m.group("type")]
    a, b = m.group("a"), m.group("b")
    has_no = m.group("no") is not None
    has_marker = m.group("community") is not None or m.group("suffix") is not None or has_no
    if not has_marker:
        return None
    year_a, year_b = _plausible_year(a), _plausible_year(b)
    year: int
    num: str
    if has_no:
        if year_b is None:
            return None
        year, num = year_b, a
    elif year_a is not None:
        year, num = year_a, b
    elif year_b is not None:
        year, num = year_b, a
    elif len(a) == 2 and a.isdigit() and m.group("suffix") is not None:
        year, num = 1900 + int(a), b
    else:
        return None
    if not num.isdigit() or len(num) > 4 or int(num) == 0:
        return None
    return f"3{year}{letter}{int(num):04d}"


def _scan_references(text: str) -> list[tuple[int, int, ParsedAuthorityReference]]:
    """All recognized citations in ``text`` as (start, end, reference), sorted."""
    found: list[tuple[int, int, ParsedAuthorityReference]] = []
    for m in _USC_RE.finditer(text):
        found.append((m.start(), m.end(), _parse_usc(m)))
    for m in _CFR_RE.finditer(text):
        found.append((m.start(), m.end(), _parse_cfr(m)))
    for m in _CELEX_RAW_RE.finditer(text):
        found.append(
            (
                m.start(),
                m.end(),
                ParsedAuthorityReference(kind="celex", raw=m.group(0), celex=m.group("celex")),
            )
        )
    for m in _EU_INSTRUMENT_RE.finditer(text):
        celex = _map_eu_instrument(m)
        if celex is None:
            continue  # not deterministically mappable — leave unattributed
        found.append(
            (
                m.start(),
                m.end(),
                ParsedAuthorityReference(kind="celex", raw=m.group(0), celex=celex),
            )
        )
    found.sort(key=lambda t: (t[0], t[1]))
    return found


# Line-boundary characters str.splitlines splits on (a char in this set can
# never appear mid-line, so rstrip is exact).
_LINE_BREAK_CHARS = "\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029"


def _blockquote_blocks(text: str) -> list[tuple[int, int, str]]:
    """Blockquote blocks as (start_offset, end_offset, joined_passage).

    Mirrors :func:`app.citation.caselaw.attribute_passages`' walk exactly
    (consecutive ``>`` lines join with a single space; empty joins are kept
    here with passage ``""`` so neighbor-clamping still sees the block).
    Offsets are char positions in ``text``: start of the block's first line
    to end of its last line's content.
    """
    blocks: list[tuple[int, int, str]] = []
    parts: list[str] = []
    start: int | None = None
    end = 0
    pos = 0
    for line in text.splitlines(keepends=True):
        line_start = pos
        pos += len(line)
        content = line.rstrip(_LINE_BREAK_CHARS)
        stripped = content.lstrip()
        if stripped.startswith(">"):
            if start is None:
                start = line_start
            parts.append(stripped[1:].strip())
            end = line_start + len(content)
            continue
        if start is not None:
            blocks.append((start, end, " ".join(p for p in parts if p).strip()))
            parts, start = [], None
    if start is not None:
        blocks.append((start, end, " ".join(p for p in parts if p).strip()))
    return blocks


def attribute_authority_passages(assistant_text: str) -> list[AttributedAuthorityPassage]:
    """Bind each blockquote passage to the recognized citations in its window.

    Returns one entry per non-empty blockquote passage, in document order —
    the passage strings (and their order) are identical to
    :func:`app.citation.caselaw.extract_blockquote_passages`'s output for the
    same text.  See the module docstring for the window rule.
    """
    blocks = _blockquote_blocks(assistant_text)
    if not blocks:
        return []
    refs = _scan_references(assistant_text)
    out: list[AttributedAuthorityPassage] = []
    for i, (b_start, b_end, passage) in enumerate(blocks):
        if not passage:
            continue  # empty blockquote — extract_blockquote_passages skips it too
        prev_end = blocks[i - 1][1] if i > 0 else 0
        next_start = blocks[i + 1][0] if i + 1 < len(blocks) else len(assistant_text)
        pre_lo = max(prev_end, b_start - ATTRIBUTION_WINDOW_CHARS)
        post_hi = min(next_start, b_end + ATTRIBUTION_WINDOW_CHARS)
        candidates: list[tuple[int, int, ParsedAuthorityReference]] = []  # (dist, pos, ref)
        for r_start, r_end, ref in refs:
            if b_start <= r_start and r_end <= b_end:
                candidates.append((0, r_start, ref))
            elif pre_lo <= r_start and r_end <= b_start:
                candidates.append((b_start - r_end, r_start, ref))
            elif b_end <= r_start and r_end <= post_hi:
                candidates.append((r_start - b_end, r_start, ref))
        candidates.sort(key=lambda t: (t[0], t[1]))
        deduped: list[ParsedAuthorityReference] = []
        seen: set[ParsedAuthorityReference] = set()
        for _dist, _pos, ref in candidates:
            key = ParsedAuthorityReference(
                kind=ref.kind,
                raw="",  # identity excludes the raw spelling
                title=ref.title,
                sections=ref.sections,
                section_range=ref.section_range,
                celex=ref.celex,
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(ref)
        out.append(AttributedAuthorityPassage(passage=passage, references=tuple(deduped)))
    return out


# ---------------------------------------------------------------------------
# Matching parsed references against fetched external_refs
# ---------------------------------------------------------------------------


def _usc_section_matches(ref: ParsedAuthorityReference, ref_sec: str) -> bool:
    if ref_sec in ref.sections:
        return True
    if ref.section_range is not None and ref_sec.isdigit():
        lo, hi = ref.section_range
        return lo <= int(ref_sec) <= hi
    return False


def reference_matches_external_ref(ref: ParsedAuthorityReference, external_ref: str) -> bool:
    """True iff ``ref`` denotes the authority identified by ``external_ref``.

    Matching is shape-based on the external_ref itself (GovInfo
    ``USCODE-…``/``CFR-…`` package or granule ids, EUR-Lex CELEX ids), so a
    reference can never match an id of a different provider family (e.g. an
    EDGAR accession number).  Title-level GovInfo packages match on title
    alone (the fetched body is the whole title, so the cited section's text —
    if genuine — must appear in it); granule-level ids additionally require
    the section/part to match.
    """
    if ref.kind == "celex":
        return _CELEX_REF_RE.match(external_ref) is not None and external_ref.upper() == ref.celex
    if ref.kind == "usc":
        m = _USCODE_REF_RE.match(external_ref)
        if m is None or (m.group(1).lstrip("0") or "0") != ref.title:
            return False
        sec_m = _REF_SEC_RE.search(external_ref)
        if sec_m is None:
            return True  # title-level package: title match suffices
        return _usc_section_matches(ref, sec_m.group(1).lower())
    if ref.kind == "cfr":
        m = _CFR_REF_RE.match(external_ref)
        if m is None or (m.group(1).lstrip("0") or "0") != ref.title:
            return False
        cited = ref.sections[0] if ref.sections else ""
        cited_part = cited.split("-", 1)[0]
        sec_m = _REF_SEC_RE.search(external_ref)
        if sec_m is not None:
            ref_sec = sec_m.group(1).lower().replace(".", "-")
            # Exact section match, or a part-level cite ("40 CFR part 1500")
            # covering a section granule within that part.
            return cited == ref_sec or ("-" not in cited and cited == ref_sec.split("-", 1)[0])
        part_m = _REF_PART_RE.search(external_ref)
        if part_m is not None:
            return cited_part == (part_m.group(1).lstrip("0") or "0")
        return True  # title-level package: title match suffices
    return False
