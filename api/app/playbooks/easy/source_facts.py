"""Bounded source facts for the specific Easy Playbook comparison failures.

These rules recognize explicit wording, not legal equivalence. Ambiguous or
conditional language stays with the normal drafting and review path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.playbooks.easy.issue_identity import issue_identity


def _text(value: str) -> str:
    return " ".join(value.split())


def source_issue(label: str, language: str) -> str:
    """Keep explicit technical safeguards out of disclosure-prohibition groups."""
    identity = issue_identity(label)
    if identity not in {"Non-Disclosure Obligation", "Standard of Care"}:
        return label
    text = _text(language).casefold()
    controls = bool(re.search(r"\b(?:encrypt\w*|access controls?|technical safeguards?)\b", text))
    if not controls:
        return label
    disclosure_ban = bool(
        re.search(
            r"\b(?:not|never)\s+(?:disclose|copy|distribute)\b|\bprohibit\w*\s+disclos"
            r"|\bneither\b.{0,50}\bdisclos|\bonly\b.{0,30}\bdisclos|\bdisclos\w*.{0,30}\bonly\b",
            text,
        )
    )
    care_benchmark = bool(
        re.search(
            r"\breasonable care\b|\b(?:degree|standard|level) of care\b|\bcare.{0,60}\bown\b", text
        )
    )
    if disclosure_ban:
        return "Non-Disclosure and Security Safeguards"
    if care_benchmark:
        return "Standard of Care" if identity == "Non-Disclosure Obligation" else label
    return "Security Safeguards"


_NUMBERS = dict(
    zip(
        [
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
            "twenty",
        ],
        range(1, 21),
        strict=True,
    )
)
_DURATION = re.compile(
    r"(?<![\w./-])(?P<number>\d+|" + "|".join(_NUMBERS) + r")"
    r"(?:\s*\((?P<digits>\d+)\))?\s+(?P<unit>years?|months?|days?)\b",
    re.I,
)


def _duration(language: str) -> str | None:
    matches = list(_DURATION.finditer(language))
    if len(matches) != 1:
        return None
    match = matches[0]
    if re.search(
        r"\b(?:at least|at most|up to|no less than|no more than|approximately|about|between|"
        + "|".join(_NUMBERS)
        + r")\s*$",
        language[: match.start()],
        re.I,
    ):
        return None
    number = match["number"].casefold()
    value = int(number) if number.isdigit() else _NUMBERS[number]
    if value < 1:
        return None
    if match["digits"] and int(match["digits"]) != value:
        return None
    unit = match["unit"].casefold().rstrip("s")
    word = next((word for word, n in _NUMBERS.items() if n == value), str(value))
    return f"{word} {unit}{'' if value == 1 else 's'}"


def _agreement_duration(language: str) -> str | None:
    text = _text(language)
    if re.search(
        r"\b(?:renew\w*|notice|unless|whichever|earlier|later|provided|subject to|until|if)\b",
        text,
        re.I,
    ):
        return None
    if not re.search(
        r"\b(?:this|the) agreement\b.{0,80}\b(?:remain in effect|continue in effect|be effective)\b",
        text,
        re.I,
    ):
        return None
    return _duration(text)


@dataclass(frozen=True)
class _Survival:
    timing: str
    duration: str = ""


def _general_survival(language: str) -> _Survival | None:
    text = _text(language).casefold()
    parts = re.split(r"\([a-z]\)", text)
    general = [
        part for part in parts if re.search(r"\ball other\b|\bnon[- ]trade[- ]secret\b", part)
    ]
    if len(general) == 1:
        scope = general[0]
    elif "otherwise" in text:
        scope = text.split("otherwise", 1)[1]
    elif not re.search(r"trade secrets?", text) or re.search(
        r"same .{0,30}period governs all", text
    ):
        scope = text
    else:
        return None
    if re.search(r"\b(?:not|may|unless|whichever|earlier|later|provided|subject to|if)\b", scope):
        return None
    if re.search(r"\b(?:full|duration of the|duration of this) term\b", scope) or re.search(
        r"\b(?:terminate\w*|expire\w*)\b.{0,30}\bupon expiration\b", scope
    ):
        return _Survival("during_term")
    duration = _duration(scope)
    if duration and re.search(
        r"\b(?:following|after)\b.{0,35}\b(?:expiration|termination|expiry)\b", scope
    ):
        return _Survival("after_term", duration)
    return None


def _acknowledger(language: str) -> str | None:
    text = _text(language)
    if re.search(r"\b(?:not|if|unless|provided|subject to)\b", text, re.I):
        return None
    if not re.search(r"irreparable (?:harm|injury)", text, re.I):
        return None
    match = re.search(
        r"\b(?:the )?(parties|both parties|each party|receiving party|disclosing party) acknowledg\w*\b",
        text,
        re.I,
    )
    if not match:
        return None
    actor = match[1].casefold()
    return {
        "parties": "both parties",
        "both parties": "both parties",
        "each party": "both parties",
        "receiving party": "the Receiving Party",
        "disclosing party": "the Disclosing Party",
    }[actor]


def _own_and_reasonable_care(language: str) -> bool:
    text = _text(language).casefold()
    if re.search(
        r"\b(?:may|unless|except|provided|not required|not use|no obligation|only if)\b", text
    ):
        return False
    return bool(
        re.search(r"\breasonable care\b", text)
        and re.search(r"\bown\b.{0,100}\binformation\b", text)
        and (
            (
                re.search(r"\bat least the same\b.{0,70}\bcare\b.{0,100}\bown\b", text)
                and re.search(r"\bin no event less than reasonable care\b", text)
            )
            or re.search(
                r"\buse reasonable care\b.{0,180}\bwhich shall in no event be less than\b"
                r".{0,90}\bown\b",
                text,
            )
        )
    )


def _while_trade_secret(language: str) -> bool:
    text = _text(language).casefold()
    # Isolate the trade-secret item so a separate general-information period
    # cannot be mistaken for a cap on trade-secret protection.
    parts = re.split(r"\([a-z]\)", text)
    scope = next((p for p in parts if "trade secret" in p and "qualif" in p), text)
    if re.search(r"\b(?:not|may|unless|provided|subject to|maximum|whichever|until)\b", scope):
        return False
    return bool(
        _duration(scope) is None
        and not re.search(r"\b(?:years?|months?|days?)\b", scope)
        and re.search(
            r"\bfor (?:so|as) long as\b.{0,100}\bqualif\w*\b.{0,35}\btrade secret\b", scope
        )
    )


def _return_election(language: str) -> str | None:
    text = _text(language).casefold()
    if not re.search(r"\ball confidential information\b", text) or re.search(
        r"\b(?:except|excluding|unless|provided|retain)\b", text
    ):
        return None
    explicit = re.search(
        r"\bat (?:the )?(disclosing|receiving) party's (?:option|election)\b", text
    )
    if explicit:
        return "the " + explicit[1].title() + " Party"
    if re.search(r"\bthe receiving party shall,? at its option,?\b", text):
        return "the Receiving Party"
    return None


def tier_comparison(issue: str, standard: str, alternative: str) -> str | None:
    """Describe unambiguous source facts in ALTERNATIVE-versus-STANDARD order.

    State only recognized source facts, including when those facts are the
    same. Do not invent a difference or compare a different issue from a
    shared source paragraph.
    """
    identity = issue_identity(issue)
    if identity == "Term":
        before, after = _agreement_duration(standard), _agreement_duration(alternative)
        if before and after and before != after:
            return f"Agreement term: {after} in the alternative, compared with {before} in the standard."
    if identity == "Survival of General Information":
        before_period, after_period = _general_survival(standard), _general_survival(alternative)
        if before_period and before_period == after_period:
            if before_period.timing == "during_term":
                return "Both clauses limit protection for general confidential information to the agreement term."
            return f"Both clauses continue protection for general confidential information for {before_period.duration} after the agreement ends."
        if before_period and after_period and before_period != after_period:
            if before_period.timing == "during_term" and after_period.timing == "after_term":
                return (
                    f"The alternative adds {after_period.duration} of protection after the agreement ends "
                    "for general confidential information; the standard limits that protection to the agreement term."
                )
            if before_period.timing == "after_term" and after_period.timing == "during_term":
                return (
                    "The alternative limits protection for general confidential information to the agreement term; "
                    f"the standard continues it for {before_period.duration} after the agreement ends."
                )
            if before_period.timing == after_period.timing == "after_term":
                return (
                    "Post-termination protection for general confidential information: "
                    f"{after_period.duration} in the alternative versus {before_period.duration} in the standard."
                )
    if identity == "Survival of Trade Secrets" and all(
        _while_trade_secret(s) for s in [standard, alternative]
    ):
        return "Both tie continuing trade-secret protection to the information continuing to qualify as a trade secret."
    if identity == "Standard of Care" and all(
        _own_and_reasonable_care(s) for s in [standard, alternative]
    ):
        return "Both clauses require at least reasonable care and at least the care used for the Receiving Party's own similar confidential information."
    if identity == "Return or Destruction":
        before_election, after_election = _return_election(standard), _return_election(alternative)
        if before_election and after_election and before_election != after_election:
            return f"The alternative gives {after_election} the return-or-destroy election; the standard gives it to {before_election}. Both cover all Confidential Information."
    if identity == "Remedies":
        before_actor, after_actor = _acknowledger(standard), _acknowledger(alternative)
        if before_actor and after_actor and before_actor != after_actor:
            return (
                f"Acknowledgement of irreparable harm: {after_actor} in the alternative, "
                f"compared with {before_actor} in the standard."
            )
    return None


def unsupported_court_type(sources: list[str], prose: str) -> bool:
    """Reject introduced court-type qualifiers, without inferring court hierarchy."""
    terms = {"district", "appellate", "supreme", "bankruptcy", "magistrate", "chancery"}
    source_words = set(re.findall(r"[a-z]+", " ".join(sources).casefold()))
    prose_words = set(re.findall(r"[a-z]+", prose.casefold()))
    return bool((prose_words & terms) - source_words)


def position_source_summary(issue: str, source: str) -> str | None:
    """Issue-scoped fallback for explicit survival rules; never change source language.

    Only recognized, unambiguous rules are summarized. Other language retains
    the existing extractive fallback and human review path.
    """
    identity = issue_identity(issue)
    if identity == "Survival of General Information":
        rule = _general_survival(source)
        if rule and rule.timing == "during_term":
            return "Obligations for general confidential information last for the agreement term."
        if rule and rule.timing == "after_term":
            return f"Obligations for general confidential information continue for {rule.duration} after expiration or termination."
    if identity == "Survival of Trade Secrets" and _while_trade_secret(source):
        return "Trade-secret obligations continue for so long as the information continues to qualify as a trade secret."
    return None


def unsupported_metadata(issue: str, sources: list[str], prose: str) -> bool:
    """Catch the remaining explicit wording mismatches from the live draft.

    These checks reject prose through the existing source fallback; they do not
    infer alternative obligations or replace drafting for unrelated issues.
    """
    if unsupported_court_type(sources, prose):
        return True
    identity = issue_identity(issue)
    source = _text(" ".join(sources)).casefold()
    text = _text(prose).casefold()
    if identity == "Remedies":
        entitlement = r"\b(?:entitled|entitlement|right)\s+to\s+(?!seek\b|request\b|apply\b)(?:\w+\s+){0,3}?(?:injunctive|equitable|injunction)\b"
        if (
            all(
                re.search(r"\bseek\b.{0,50}\b(?:injunctive|equitable)\b", _text(s), re.I)
                for s in sources
            )
            and not re.search(entitlement, source)
            and re.search(entitlement, text)
        ):
            return True
    if identity == "Survival of General Information" and re.search(r"\btrade[- ]secrets?\b", text):
        return True
    if identity == "Survival of Trade Secrets":
        if re.search(r"\b(?:general|all other|other confidential)\b.{0,35}\binformation\b", text):
            return True
        if (
            len(sources) == 1
            and _while_trade_secret(sources[0])
            and re.search(r"\b(?:indefinit\w*|surviv\w*|continu\w*)\b", text)
            and not re.search(
                r"\b(?:continu\w*|remain\w*)\b.{0,35}\bqualif\w*\b|\bfor (?:so|as) long as\b.{0,70}\bqualif\w*\b",
                text,
            )
        ):
            return True
    if identity == "Standard of Care":
        return any(word in text and word not in source for word in ("customary", "industry"))
    if identity == "No License":
        negative = (
            r"\bno licen[cs]e\b.{0,180}\bgrant|\bnothing\b.{0,80}\bgrants?\b|\bdoes not grant\b"
        )
        if all(re.search(negative, _text(s), re.I) for s in sources):
            if (
                all("otherwise" in _text(s).casefold() for s in sources)
                and re.search(
                    r"\b(?:narrow\w*|restrict\w*|exclud\w*|rather than|instead of)\b", text
                )
                and any(
                    word in text and word not in source for word in ("express", "direct", "implied")
                )
            ):
                return True
            return bool(
                re.search(
                    r"\b(?:limits?|narrows?|restricts?|extends?|expands?|permits?|allows?)\b"
                    r".{0,30}\blicen[cs]e grant\b",
                    text,
                )
            )
    if identity == "Return or Destruction":
        alternative = _text(sources[-1]).casefold()
        return bool(
            "all confidential information" in alternative
            and not re.search(r"\b(?:except|excluding|other than)\b", alternative)
            and re.search(r"\bexclud\w*\b.{0,90}\b(?:extracts?|derivative)\b", text)
        )
    if identity == "Jurisdiction":
        conditional_federal = any(
            re.search(
                r"\bif\b.{0,70}\blacks\b.{0,40}\bjurisdiction\b.{0,30}\bfederal courts\b",
                _text(s),
                re.I,
            )
            for s in sources
        )
        return bool(
            conditional_federal
            and "chancery" in text
            and "federal" in text
            and not re.search(r"\b(?:if|when|conditional\w*|fallback)\b", text)
        )
    if identity == "Exclusions from Confidential Information":
        claim = r"\blegally\b|\bstatutor(?:y|ily)\b|\b(?:law|legislation) (?:requires?|exempts?)\b"
        return bool(re.search(claim, text) and not re.search(claim, source))
    return False
