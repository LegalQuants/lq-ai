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
    if re.search(r"\b(?:unless|whichever|earlier|later|provided|subject to|if)\b", scope):
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
    if re.search(r"\b(?:if|unless|provided|subject to)\b", text, re.I):
        return None
    if not re.search(r"irreparable harm", text, re.I):
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


def tier_comparison(issue: str, standard: str, alternative: str) -> str | None:
    """Describe unambiguous source facts in ALTERNATIVE-versus-STANDARD order.

    Limit this correction to explicit agreement durations, general-information
    survival timing, and acknowledgement actors. Do not guess at other effects.
    """
    identity = issue_identity(issue)
    if identity == "Term":
        before, after = _agreement_duration(standard), _agreement_duration(alternative)
        if before and after and before != after:
            return f"Agreement term: {after} in the alternative, compared with {before} in the standard."
    if identity == "Survival of General Information":
        before_period, after_period = _general_survival(standard), _general_survival(alternative)
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
