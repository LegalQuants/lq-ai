"""Response adapters for external authority sources (WS-E).

Each adapter normalises a gateway tool-call payload into a ``FetchedAuthority``
so the rest of the research pipeline works against a single canonical shape.

The ``SourceAdapter`` Protocol defines the contract; concrete adapters
(currently ``GovInfoAdapter``) implement it.  A ``None`` adapter on a
``SourceSpec`` means the caselaw passthrough path — no normalisation needed
because the gateway payloads are already structured for direct use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class FetchedAuthority:
    """Normalised authority text returned by a ``SourceAdapter``.

    :attr citable_text: The full text suitable for citation extraction.
    :attr label:        Short citation label (e.g. "15 U.S.C. § 1").
    :attr subtitle:     Longer title / section heading.
    :attr url:          Canonical URL for the authority document.
    :attr external_ref: Provider-specific stable ID (e.g. GovInfo package_id).
    :attr content_kind: "statute", "regulation", or "caselaw".
    """

    citable_text: str
    label: str
    subtitle: str
    url: str
    external_ref: str
    content_kind: str


@runtime_checkable
class SourceAdapter(Protocol):
    """Protocol for gateway-payload normalisation adapters."""

    def from_response(self, op: str, payload: dict[str, Any]) -> FetchedAuthority:
        """Normalise a gateway tool-call payload to ``FetchedAuthority``.

        :param op:      The tool operation name (e.g. ``"get_authority"``).
        :param payload: The raw ``payload`` dict from the gateway response.
        """
        ...


def _content_kind_from_id(identifier: str) -> str:
    """Derive content_kind from a GovInfo package_id or granule_id."""
    upper = identifier.upper()
    if "USCODE" in upper:
        return "statute"
    if "CFR" in upper:
        return "regulation"
    # Fallback — unknown collection; callers should prefer the
    # collection field when available (search_authority path).
    return "statute"


def _content_kind_from_collection(collection: str, fallback_id: str = "") -> str:
    """Derive content_kind from a GovInfo collection string."""
    upper = collection.upper()
    if "USCODE" in upper:
        return "statute"
    if "CFR" in upper:
        return "regulation"
    # Fall back to parsing the identifier.
    return _content_kind_from_id(fallback_id)


class GovInfoAdapter:
    """Normalises GovInfo gateway payloads into ``FetchedAuthority`` objects.

    Handles the two GovInfo tool operations exposed by the gateway:

    ``get_authority``
        Payload: ``{package_id, title, citation?, url, text}``
        Returns a fully-hydrated ``FetchedAuthority`` with the full statutory
        or regulatory text.

    ``search_authority``
        Payload: ``{results: [{package_id|granule_id, title, collection, date?}], count}``
        Returns a ``FetchedAuthority`` from the *first* result.  Callers that
        need all results should iterate the raw payload directly; this adapter
        path is for single-target extraction in the agentic loop.

    ``content_kind`` derivation:

    * ``get_authority`` — parsed from ``package_id`` (USCODE→"statute", CFR→"regulation").
    * ``search_authority`` — parsed from ``collection`` first, then ``package_id``/``granule_id``.
    """

    def from_response(self, op: str, payload: dict[str, Any]) -> FetchedAuthority:
        if op == "get_authority":
            return self._from_get_authority(payload)
        if op == "search_authority":
            return self._from_search_authority(payload)
        raise ValueError(f"GovInfoAdapter: unsupported op {op!r}")

    def _from_get_authority(self, payload: dict[str, Any]) -> FetchedAuthority:
        package_id: str = payload.get("package_id") or ""
        title: str = payload.get("title") or ""
        citation: str = payload.get("citation") or title
        url: str = payload.get("url") or ""
        text: str = payload.get("text") or ""
        content_kind = _content_kind_from_id(package_id)
        return FetchedAuthority(
            citable_text=text,
            label=citation,
            subtitle=title,
            url=url,
            external_ref=package_id,
            content_kind=content_kind,
        )

    def _from_search_authority(self, payload: dict[str, Any]) -> FetchedAuthority:
        results: list[dict[str, Any]] = payload.get("results") or []
        if not results:
            raise ValueError("GovInfoAdapter: search_authority payload has no results")
        first = results[0]
        package_id: str = first.get("package_id") or first.get("granule_id") or ""
        title: str = first.get("title") or ""
        collection: str = first.get("collection") or ""
        date: str = first.get("date") or ""
        content_kind = _content_kind_from_collection(collection, fallback_id=package_id)
        return FetchedAuthority(
            citable_text=title,
            label=title,
            subtitle=date,
            url="",
            external_ref=package_id,
            content_kind=content_kind,
        )
