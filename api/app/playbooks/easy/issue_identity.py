"""Conservative issue identities: similarity alone cannot establish equivalence."""

from __future__ import annotations

import re

# Bounded synonyms, not a cap on the issues a contract may contain. Unknown
# labels remain independent. In particular, governing law != forum, definitions
# != exclusions, permission != compulsion, and remedies != recipient liability.
_FAMILIES = (
    (
        "Definition of Confidential Information",
        "Confidential Information Definition",
        "Confidential Information — Definition",
        "Definition of Confidential Info",
    ),
    (
        "Exclusions from Confidential Information",
        "Exceptions to Confidential Information",
        "Confidential Information Exceptions",
        "Confidential Information — Exclusions",
        "Confidential Information Exclusions",
    ),
    ("Permitted Disclosures", "Permitted Recipients", "Authorized Recipients"),
    (
        "Compelled Disclosure",
        "Compelled Disclosures",
        "Legally Required Disclosure",
        "Mandatory Disclosure",
    ),
    (
        "Recipient Liability",
        "Liability for Disclosees",
        "Responsibility for Permitted Disclosures",
        "Liability for Recipients",
        "Liability for Permitted Disclosures",
        "Liability for Employees",
        "Liability for Disclosures to Third Parties",
    ),
    ("Standard of Care", "Duty of Care", "Confidentiality Standard of Care", "Degree of Care"),
    (
        "Term",
        "Term of Agreement",
        "Agreement Term",
        "Agreement Duration",
        "NDA Duration",
        "Term Duration",
    ),
    (
        "Term of Confidentiality Obligation",
        "Term of Confidentiality",
        "Survival of Obligations",
        "Survival of Confidentiality Obligations",
        "Survival",
        "Confidentiality Survival",
    ),
    (
        "Survival of Trade Secrets",
        "Survival for Trade Secrets",
        "Trade Secret Survival",
        "Confidentiality Survival (Trade Secrets)",
    ),
    (
        "Survival of General Information",
        "Survival for Non-Trade Secret Information",
        "Survival of General Confidential Information",
        "Survival for General Confidential Information",
        "Confidentiality Survival (General)",
    ),
    (
        "Remedies",
        "Injunctive Relief",
        "Equitable Relief",
        "Equitable Remedies",
        "Remedies; Injunctive Relief",
    ),
    ("Governing Law", "Applicable Law"),
    (
        "Jurisdiction",
        "Jurisdiction and Venue",
        "Forum Selection",
        "Dispute Resolution / Forum",
        "Forum and Jurisdiction",
        "Venue",
        "Forum or Venue",
        "Forum",
        "Forum/Venue",
        "Forum and Venue",
    ),
    ("Permitted Use", "Use Limitation", "Restriction on Use", "Use Restriction"),
    ("Non-Disclosure Obligation", "Restriction on Disclosure", "Prohibition on Disclosure"),
    (
        "Return or Destruction",
        "Return or Destruction of Materials",
        "Return or Destruction of Information",
        "Return or Destruction of Confidential Information",
    ),
    (
        "Archival Copy Exception",
        "Retention of Records",
        "Retention of Backup Information",
        "Retention of Confidential Information",
        "Retained Copy",
        "Retention of Archival Copy",
    ),
    (
        "No License",
        "No Implied License",
        "No License or Transfer",
        "No License or Other Rights",
        "No License Granted",
        "No License / No Rights Granted",
        "No Transfer of Rights / No License",
    ),
)


def _alias_key(label: str) -> str:
    return re.sub(r"[\W_]+", " ", label.casefold()).strip()


_IDENTITIES = {_alias_key(label): family[0] for family in _FAMILIES for label in family}


def issue_identity(label: str) -> str:
    """Return a known identity, or the unchanged normalized unknown label."""
    return _IDENTITIES.get(_alias_key(label), "unknown:" + " ".join(label.casefold().split()))


def compatible_issues(left: str, right: str) -> bool:
    return issue_identity(left) == issue_identity(right)
