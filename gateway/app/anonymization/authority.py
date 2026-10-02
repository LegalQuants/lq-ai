"""Bound authority arguments: pseudonymize prose, never rewrite reference IDs.

Only registered authority operations have a supported argument shape here. No
recursive passthrough of arbitrary tool JSON, and no response rehydration: public
authority evidence must retain the source's wording (ADR 0014 D5).
"""

from __future__ import annotations

import re
from typing import Any

from app.anonymization.engine import Anonymizer
from app.anonymization.mapper import PseudonymMapper


class AuthorityAnonymizationRefused(ValueError):
    pass


def anonymize_authority_args(
    provider_type: str, tool: str, args: dict[str, Any], *, anonymizer: Anonymizer
) -> dict[str, Any]:
    """Return a fresh bounded argument object or refuse before any provider I/O.

    IDs and filters must match their supported syntax and pass entity detection
    unchanged. A detected entity in an ID is refused, not replaced with an ID
    for a different document. The mapper exists only during this call.
    """
    try:
        allowed: set[str]
        if tool == "search_authority" and provider_type in {"govinfo", "edgar"}:
            allowed = (
                {"query", "collection", "page_size"}
                if provider_type == "govinfo"
                else {"query", "forms"}
            )
        elif tool == "get_authority" and provider_type in {"govinfo", "edgar", "eurlex"}:
            allowed = (
                {"package_id", "granule_id"} if provider_type == "govinfo" else {"external_ref"}
            )
        else:
            raise ValueError("unsupported authority operation")
        if args.keys() - allowed:
            raise ValueError("unknown authority arguments")
        mapper = PseudonymMapper()
        result = dict(args)

        def text(name: str, limit: int) -> str:
            value = args.get(name)
            if not isinstance(value, str) or not value.strip() or len(value.encode()) > limit:
                raise ValueError("invalid authority argument")
            return value

        def identifier(name: str, pattern: str) -> None:
            value = text(name, 512)
            if re.fullmatch(pattern, value) is None:
                raise ValueError("invalid authority reference or filter")
            if anonymizer.pseudonymize_into(value, mapper) != value:
                raise ValueError("authority reference or filter contains detected entities")

        if tool == "search_authority":
            result["query"] = anonymizer.pseudonymize_into(text("query", 8192), mapper)
            if provider_type == "govinfo":
                if args.get("collection") not in ("USCODE", "CFR"):
                    raise ValueError("unsupported collection")
                if "page_size" in args and (
                    type(args["page_size"]) is not int or not 1 <= args["page_size"] <= 100
                ):
                    raise ValueError("invalid page size")
            elif "forms" in args:
                identifier("forms", r"[A-Z0-9][A-Z0-9/-]*(?:,[A-Z0-9][A-Z0-9/-]*)*")
        elif provider_type == "govinfo":
            # Both spellings are accepted by the adapter, but ambiguity is not.
            if len(args) != 1:
                raise ValueError("one authority reference is required")
            identifier(next(iter(args)), r"[A-Za-z0-9][A-Za-z0-9._-]*")
        elif provider_type == "edgar":
            identifier("external_ref", r"[0-9]+_[0-9]+_[A-Za-z0-9][A-Za-z0-9._-]*")
        else:
            identifier("external_ref", r"[0-9][0-9]{4}[A-Z]{1,2}[A-Za-z0-9._-]*")
        return result
    except Exception:
        # Validation/recognizer failures may embed matter text. Neither logs nor
        # error responses receive those exceptions or the request-local mapper.
        raise AuthorityAnonymizationRefused(
            "Authority argument anonymization unavailable"
        ) from None
