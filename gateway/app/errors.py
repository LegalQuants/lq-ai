"""Gateway exception hierarchy — the gateway/ side of `lq_ai.errors`.

Per :doc:`docs/adr/0003-error-handling.md` (Option B), each subsystem owns
its own typed exception hierarchy. The cross-subsystem contract is the
error-code enum in the OpenAPI sketches. This module names the codes the
gateway emits and the FastAPI exception handler in :mod:`app.main`
translates them to the wire shape documented in
``docs/api/gateway-openapi.yaml`` as the ``GatewayError`` schema:

.. code-block:: json

    {
      "error": {
        "code": "<stable code>",
        "message": "<human-readable explanation>",
        "details": { ... }
      }
    }

The gateway's existing :class:`app.providers.base.ProviderAdapterError`
hierarchy is **not** replaced — adapters keep raising those, and the
route handler maps them to ``LQAIError`` subclasses at the boundary.
This keeps adapter-internal error semantics close to the adapter while
still routing every error through the canonical exception envelope.

Note on the wrapper key: backend uses ``{"detail": {...}}`` and gateway
uses ``{"error": {...}}`` — see ADR 0003 for the rationale (FastAPI
native shape vs. shipped OpenAPI schema; the inner shape is identical
across both sides).
"""

from __future__ import annotations

from typing import Any, ClassVar

from fastapi import status

# --- Canonical error-code enum ----------------------------------------------
# These match docs/api/gateway-openapi.yaml's GatewayError.code enum.
# The cross-subsystem conformance test in tests/test_error_code_contract.py
# verifies these stay in sync with api/app/errors.py.

# Gateway-only codes (do not cross to backend)
CODE_TIER_DISALLOWED_GLOBALLY = "tier_disallowed_globally"
CODE_ANONYMIZATION_FAILED = "anonymization_failed"
CODE_INVALID_REQUEST = "invalid_request"
CODE_NOT_IMPLEMENTED = "not_implemented"
CODE_RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"

# C2 — skill prompt assembly. Raised by the backend HTTP client and the
# prompt assembler. ``skill_not_found`` and ``skill_fetch_failed`` cross
# into the backend's chat endpoint as 404 / 502 respectively (the
# backend's GatewayClient maps them via app.errors.map_gateway_error_code).
CODE_SKILL_NOT_FOUND = "skill_not_found"
CODE_SKILL_FETCH_FAILED = "skill_fetch_failed"
CODE_SKILL_INPUT_MISSING = "skill_input_missing"

# Codes that cross to the backend (also declared in api/app/errors.py).
CODE_TIER_BELOW_MINIMUM = "tier_below_minimum"
CODE_PROVIDER_UNAVAILABLE = "provider_unavailable"
CODE_INVALID_MODEL = "invalid_model"
CODE_UNAUTHORIZED = "unauthorized"


# --- Base class --------------------------------------------------------------


class LQAIError(Exception):
    """Base class for all typed errors raised inside the gateway/ subsystem.

    Carries a stable ``code`` (rendered as the inner ``code`` field), a
    public-safe ``message``, an HTTP status code, and an optional
    ``details`` dict. ``details`` MUST NOT contain provider keys, full
    upstream request bodies, or PII; it surfaces in the response body.
    """

    code: ClassVar[str] = "internal_error"
    """Stable error code; rendered as ``error.code`` in the response."""

    http_status: ClassVar[int] = status.HTTP_500_INTERNAL_SERVER_ERROR
    """Default HTTP status for this exception class."""

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        http_status: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = dict(details) if details else {}
        self._http_status = http_status if http_status is not None else self.__class__.http_status
        self._code = code if code is not None else self.__class__.code

    @property
    def effective_http_status(self) -> int:
        return self._http_status

    @property
    def effective_code(self) -> str:
        return self._code

    def to_envelope(self) -> dict[str, Any]:
        """Render the canonical wire shape ``{"error": {...}}`` per GatewayError."""

        return {
            "error": {
                "code": self.effective_code,
                "message": self.message,
                "details": dict(self.details),
            }
        }


# --- Subclasses --------------------------------------------------------------


class TierBelowMinimum(LQAIError):
    """Request's resolved tier is below the request's minimum_inference_tier.

    D1 wires the refusal; B5 just declares the class so the contract is
    in place.
    """

    code: ClassVar[str] = CODE_TIER_BELOW_MINIMUM
    http_status: ClassVar[int] = status.HTTP_403_FORBIDDEN


class TierDisallowedGlobally(LQAIError):
    """Resolved tier is disallowed by the global tier policy."""

    code: ClassVar[str] = CODE_TIER_DISALLOWED_GLOBALLY
    http_status: ClassVar[int] = status.HTTP_403_FORBIDDEN


class AnonymizationFailed(LQAIError):
    """The M2 anonymization middleware refused to forward the request."""

    code: ClassVar[str] = CODE_ANONYMIZATION_FAILED
    http_status: ClassVar[int] = status.HTTP_502_BAD_GATEWAY


class InvalidModel(LQAIError):
    """Requested model does not resolve to any configured alias or native model."""

    code: ClassVar[str] = CODE_INVALID_MODEL
    http_status: ClassVar[int] = status.HTTP_400_BAD_REQUEST


class ProviderUnavailable(LQAIError):
    """Upstream provider is not reachable, returned 5xx, has no adapter, or
    accepted the request and returned no content.

    The last case is :class:`app.providers.base.ProviderEmptyResponseError`
    (issue #503): the provider answered and produced nothing, which the
    client must not read as a thin answer. It reuses this wire code rather
    than adding to the cross-subsystem enum (ADR 0003).

    The handler picks 502 for upstream-induced and 503 for adapter-not-
    instantiated; the class default is 502 and the route can override.
    """

    code: ClassVar[str] = CODE_PROVIDER_UNAVAILABLE
    http_status: ClassVar[int] = status.HTTP_502_BAD_GATEWAY


class RateLimitExceeded(LQAIError):
    """Upstream provider returned 429."""

    code: ClassVar[str] = CODE_RATE_LIMIT_EXCEEDED
    http_status: ClassVar[int] = status.HTTP_429_TOO_MANY_REQUESTS


class InvalidRequest(LQAIError):
    """Caller's request body fails validation."""

    code: ClassVar[str] = CODE_INVALID_REQUEST
    http_status: ClassVar[int] = status.HTTP_400_BAD_REQUEST


class NotImplemented_(LQAIError):
    """Surface exists but the implementation has not landed yet."""

    code: ClassVar[str] = CODE_NOT_IMPLEMENTED
    http_status: ClassVar[int] = status.HTTP_501_NOT_IMPLEMENTED


class Unauthorized(LQAIError):
    """Gateway-side auth failure (e.g., upstream 401, missing gateway key)."""

    code: ClassVar[str] = CODE_UNAUTHORIZED
    http_status: ClassVar[int] = status.HTTP_502_BAD_GATEWAY


# --- C2 (skill prompt assembly) ----------------------------------------------


class SkillNotFound(LQAIError):
    """The named skill is not in the backend's registry (HTTP 404 from the
    backend's internal-skills endpoint).

    Surfaces as 404 to the chat-completion caller. The backend's
    GatewayClient maps the same code to a backend NotFound (404) so the
    user sees a clean "skill not found" rather than a wrapped 502.
    """

    code: ClassVar[str] = CODE_SKILL_NOT_FOUND
    http_status: ClassVar[int] = status.HTTP_404_NOT_FOUND


class SkillFetchFailed(LQAIError):
    """The gateway could not fetch a skill from the backend (transport,
    timeout, 5xx, malformed body, etc.).

    Distinct from SkillNotFound — this is the operational failure mode,
    not the "skill doesn't exist" mode. Surfaces as 502 because the
    skill content is part of the assembled prompt; we cannot dispatch
    to the model without it.
    """

    code: ClassVar[str] = CODE_SKILL_FETCH_FAILED
    http_status: ClassVar[int] = status.HTTP_502_BAD_GATEWAY


class SkillInputMissing(LQAIError):
    """A required skill input was not supplied in the request.

    Raised by the prompt assembler when a skill's ``inputs.required``
    list contains a name that the request's ``lq_ai_skill_inputs`` did
    not bind. Surfaces as 400 with the missing field names in
    ``details.missing``.
    """

    code: ClassVar[str] = CODE_SKILL_INPUT_MISSING
    http_status: ClassVar[int] = status.HTTP_400_BAD_REQUEST


# --- Public re-exports -------------------------------------------------------
__all__ = [
    "CODE_ANONYMIZATION_FAILED",
    "CODE_INVALID_MODEL",
    "CODE_INVALID_REQUEST",
    "CODE_NOT_IMPLEMENTED",
    "CODE_PROVIDER_UNAVAILABLE",
    "CODE_RATE_LIMIT_EXCEEDED",
    "CODE_SKILL_FETCH_FAILED",
    "CODE_SKILL_INPUT_MISSING",
    "CODE_SKILL_NOT_FOUND",
    "CODE_TIER_BELOW_MINIMUM",
    "CODE_TIER_DISALLOWED_GLOBALLY",
    "CODE_UNAUTHORIZED",
    "AnonymizationFailed",
    "InvalidModel",
    "InvalidRequest",
    "LQAIError",
    "NotImplemented_",
    "ProviderUnavailable",
    "RateLimitExceeded",
    "SkillFetchFailed",
    "SkillInputMissing",
    "SkillNotFound",
    "TierBelowMinimum",
    "TierDisallowedGlobally",
    "Unauthorized",
]
