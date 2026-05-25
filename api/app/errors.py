"""Backend exception hierarchy — the api/ side of `lq_ai.errors`.

Per :doc:`docs/adr/0003-error-handling.md` (Option B), each subsystem owns
its own typed exception hierarchy. The cross-subsystem contract is the
error-code enum in the OpenAPI sketches; this module names the codes the
backend emits, and the FastAPI exception handler in :mod:`app.main`
translates them to the wire shape documented in
``docs/api/backend-openapi.yaml`` as the ``Error`` schema:

.. code-block:: json

    {
      "detail": {
        "code": "<stable code>",
        "message": "<human-readable explanation>",
        "details": { ... }
      }
    }

Why this shape rather than ``{"error": {...}}`` (the gateway's choice):

* Matches FastAPI's native ``HTTPException`` response shape, so tooling
  that already understands FastAPI errors works without translation.
* Matches the existing B2 forced-password-change pattern.
* Matches what the OpenWebUI fork's auth-delegation glue already reads.

The two wrappers (backend ``detail`` vs. gateway ``error``) are
deliberately different; the inner ``code`` / ``message`` / ``details``
shape is the binding contract and is identical on both sides. See ADR
0003 for the rationale.

Usage::

    from app.errors import GatewayUnreachable

    raise GatewayUnreachable(
        message="Inference Gateway did not respond within timeout",
        details={"timeout_seconds": 30.0},
    )

The handler in :mod:`app.main` catches every :class:`LQAIError`,
serializes the canonical envelope, and returns the right HTTP status.
"""

from __future__ import annotations

from typing import Any, ClassVar

from fastapi import status

# --- Canonical error-code enum -----------------------------------------------
# Every value here is part of the cross-subsystem contract verified by
# tests/test_error_code_contract.py. New codes added on the backend that
# do NOT cross the gateway boundary (e.g., password_change_required) are
# legitimate backend-only codes; new codes that DO cross the boundary
# must also appear in gateway/app/errors.py.

# Backend-only codes ----------------------------------------------------------
CODE_UNAUTHORIZED = "unauthorized"
CODE_FORBIDDEN = "forbidden"
CODE_NOT_FOUND = "not_found"
CODE_VALIDATION_ERROR = "validation_error"
CODE_RATE_LIMITED = "rate_limited"
CODE_INTERNAL_ERROR = "internal_error"
CODE_PASSWORD_CHANGE_REQUIRED = "password_change_required"
CODE_PAYLOAD_TOO_LARGE = "payload_too_large"
CODE_CONFLICT = "conflict"
CODE_MFA_ENROLLMENT_REQUIRED = "mfa_enrollment_required"

# Backend↔gateway crossing codes (also declared in gateway/app/errors.py).
# These propagate from gateway responses into backend exceptions; the
# conformance test enforces the codes match across subsystems.
CODE_GATEWAY_UNREACHABLE = "gateway_unreachable"
CODE_GATEWAY_TIMEOUT = "gateway_timeout"
CODE_GATEWAY_INVALID_RESPONSE = "gateway_invalid_response"
CODE_PROVIDER_UNAVAILABLE = "provider_unavailable"
CODE_TIER_BELOW_MINIMUM = "tier_below_minimum"
CODE_INVALID_MODEL = "invalid_model"

# C2 — skill prompt-assembly failure modes. The gateway raises these
# during prompt assembly; the backend's GatewayClient maps them via
# map_gateway_error_code to the corresponding backend exception class
# below.
CODE_SKILL_NOT_FOUND = "skill_not_found"
CODE_SKILL_FETCH_FAILED = "skill_fetch_failed"
CODE_SKILL_INPUT_MISSING = "skill_input_missing"

# M4 autonomous-layer control-flow codes. These are BACKEND-ONLY and do
# NOT cross the gateway boundary. They are raised inside the autonomous
# executor to halt the LangGraph run; the executor catches them so they
# rarely surface on the HTTP wire.
CODE_AUTONOMOUS_HALTED = "autonomous_halted"
CODE_AUTONOMOUS_TOOL_NOT_GRANTED = "autonomous_tool_not_granted"
CODE_AUTONOMOUS_COST_CAP_REACHED = "autonomous_cost_cap_reached"


# --- Base class --------------------------------------------------------------


class LQAIError(Exception):
    """Base class for all typed errors raised inside the api/ subsystem.

    Carries a stable ``code`` (rendered as the inner ``code`` field), a
    public-safe ``message``, an HTTP status code, and an optional
    ``details`` dict. ``details`` MUST NOT contain secrets or PII; it
    surfaces in the response body sent to the caller.

    The default ``http_status`` and ``code`` come from class attributes
    so subclasses can declare them once::

        class GatewayTimeout(LQAIError):
            code = CODE_GATEWAY_TIMEOUT
            http_status = status.HTTP_504_GATEWAY_TIMEOUT

    Instances may override either at construction time when the
    declarative defaults aren't right for a specific occurrence.
    """

    code: ClassVar[str] = CODE_INTERNAL_ERROR
    """Stable error code; rendered as ``detail.code`` in the response."""

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
        # Per-instance overrides take precedence over the class defaults.
        # We keep both attribute names usable so a handler can read the
        # effective values without remembering whether to consult the
        # instance or the class.
        self._http_status = http_status if http_status is not None else self.__class__.http_status
        self._code = code if code is not None else self.__class__.code

    @property
    def effective_http_status(self) -> int:
        return self._http_status

    @property
    def effective_code(self) -> str:
        return self._code

    def to_envelope(self) -> dict[str, Any]:
        """Render the canonical wire shape ``{"detail": {...}}``.

        The handler in :mod:`app.main` calls this; tests use it to
        assert the structured error body without going through the HTTP
        layer.
        """

        return {
            "detail": {
                "code": self.effective_code,
                "message": self.message,
                "details": dict(self.details),
            }
        }


# --- Backend-only subclasses -------------------------------------------------


class Unauthorized(LQAIError):
    """Authentication failure — 401."""

    code = CODE_UNAUTHORIZED
    http_status = status.HTTP_401_UNAUTHORIZED


class Forbidden(LQAIError):
    """Authorization failure — 403."""

    code = CODE_FORBIDDEN
    http_status = status.HTTP_403_FORBIDDEN


class NotFound(LQAIError):
    """Resource does not exist — 404."""

    code = CODE_NOT_FOUND
    http_status = status.HTTP_404_NOT_FOUND


class ValidationError(LQAIError):
    """Request fails domain validation — 400.

    Distinct from FastAPI's pydantic-derived 422; this is for
    business-rule violations (e.g., new password matches old).
    """

    code = CODE_VALIDATION_ERROR
    http_status = status.HTTP_400_BAD_REQUEST


class RateLimited(LQAIError):
    """Caller exceeded a rate limit — 429."""

    code = CODE_RATE_LIMITED
    http_status = status.HTTP_429_TOO_MANY_REQUESTS


class InternalError(LQAIError):
    """Unexpected server error — 500.

    Use sparingly; an internal error usually means a bug. Set
    ``details`` to something operators can grep for in logs, but never
    include stack traces or secrets.
    """

    code = CODE_INTERNAL_ERROR
    http_status = status.HTTP_500_INTERNAL_SERVER_ERROR


class PasswordChangeRequired(LQAIError):
    """The user must change their password before proceeding — 403.

    Surfaced by the must-change-password gate (B2). The body's ``code``
    is the stable string the OpenWebUI fork's auth-delegation glue
    branches on to redirect to the change-password flow.
    """

    code = CODE_PASSWORD_CHANGE_REQUIRED
    http_status = status.HTTP_403_FORBIDDEN


class MfaEnrollmentRequired(LQAIError):
    """The user must enroll in MFA before proceeding — 403.

    Surfaced by the MFA-mandatory gate (M-Sec.1) when the deployment
    is configured with ``LQ_AI_MFA_MANDATORY=true`` and the calling
    user has ``mfa_enabled=False``. The body's ``code`` is the stable
    string the client branches on to redirect to the MFA-setup flow.
    """

    code = CODE_MFA_ENROLLMENT_REQUIRED
    http_status = status.HTTP_403_FORBIDDEN


class PayloadTooLarge(LQAIError):
    """Request body exceeds the configured upload-size limit — 413.

    Raised by the file-upload handler (C4) when the streamed body grows
    past ``LQ_AI_MAX_UPLOAD_SIZE_MB``. ``details`` carries
    ``{"limit_bytes": ..., "received_bytes": ...}`` so clients can show
    a useful "your file is too large" message.
    """

    code = CODE_PAYLOAD_TOO_LARGE
    http_status = status.HTTP_413_CONTENT_TOO_LARGE


class Conflict(LQAIError):
    """Request collides with current resource state — 409.

    Used for uniqueness collisions (e.g., a project slug already in use
    by the caller for an active project) and idempotency-violating
    operations (e.g., attaching a file or skill that's already attached
    to a project). Backend-only code; does not cross the gateway
    boundary.
    """

    code = CODE_CONFLICT
    http_status = status.HTTP_409_CONFLICT


# --- M4 autonomous-layer brake exceptions ------------------------------------
# Raised inside the autonomous executor to halt the LangGraph run.
# The executor catches them; they do NOT normally surface on the HTTP wire.
# They follow the LQAIError pattern so the canonical handler can serialise
# them if they do reach the wire (e.g., during development or in tests).


class AutonomousBrake(LQAIError):
    """Base for all autonomous-executor halt exceptions.

    Raised by the chokepoint (:func:`~app.autonomous.nodes.guarded_tool_call`,
    M4-A3) to stop a LangGraph run. The executor catches subclasses of this
    class and persists the appropriate halt state on the session row.

    HTTP status defaults to 409 CONFLICT — a brake is a state conflict —
    but these rarely reach the wire.
    """

    code: ClassVar[str] = CODE_AUTONOMOUS_HALTED
    http_status: ClassVar[int] = status.HTTP_409_CONFLICT


class SessionHalted(AutonomousBrake):
    """The session was halted externally or by an idle-timeout (M4 R1/R2).

    ``reason`` is a short slug (``"external_halt"``, ``"idle_timeout"``)
    stored in ``details`` so the executor audit row and the wire envelope
    carry it without parsing the message string.
    """

    code = CODE_AUTONOMOUS_HALTED
    http_status = status.HTTP_409_CONFLICT

    def __init__(
        self,
        message: str,
        *,
        reason: str = "external_halt",
        details: dict[str, Any] | None = None,
        http_status: int | None = None,
        code: str | None = None,
    ) -> None:
        merged: dict[str, Any] = dict(details) if details else {}
        merged["reason"] = reason
        super().__init__(message, details=merged, http_status=http_status, code=code)


class ToolNotGranted(AutonomousBrake):
    """The requested tool intent is not in the phase-grant set (M4 R3).

    ``intent`` is the :class:`~app.autonomous.enums.ToolIntent` value
    (as a string) and ``phase`` is the current
    :class:`~app.schemas.autonomous.Phase` value (as a string). Both
    land in ``details`` for the audit envelope.
    """

    code = CODE_AUTONOMOUS_TOOL_NOT_GRANTED
    http_status = status.HTTP_409_CONFLICT

    def __init__(
        self,
        message: str,
        *,
        intent: str = "",
        phase: str = "",
        details: dict[str, Any] | None = None,
        http_status: int | None = None,
        code: str | None = None,
    ) -> None:
        merged: dict[str, Any] = dict(details) if details else {}
        merged["intent"] = intent
        merged["phase"] = phase
        super().__init__(message, details=merged, http_status=http_status, code=code)


class CostCapReached(AutonomousBrake):
    """The projected cost of the next tool call would exceed the session cap (M4 R4).

    ``projected_usd`` is a float carrying the pre-flight cost estimate
    that tripped the cap, stored in ``details`` for the audit envelope.
    """

    code = CODE_AUTONOMOUS_COST_CAP_REACHED
    http_status = status.HTTP_409_CONFLICT

    def __init__(
        self,
        message: str,
        *,
        projected_usd: float = 0.0,
        details: dict[str, Any] | None = None,
        http_status: int | None = None,
        code: str | None = None,
    ) -> None:
        merged: dict[str, Any] = dict(details) if details else {}
        merged["projected_usd"] = projected_usd
        super().__init__(message, details=merged, http_status=http_status, code=code)


# --- Gateway-crossing subclasses ---------------------------------------------
# Raised by the GatewayClient (or by handlers that translate gateway
# responses) when the backend↔gateway hop fails or surfaces a structured
# error. The codes match those in gateway/app/errors.py for the codes that
# cross the boundary.


class GatewayUnreachable(LQAIError):
    """Backend could not reach the gateway (network / DNS / TCP / TLS / 5xx).

    Maps to 503 — the operator should see "service unavailable" rather
    than the underlying network detail (which would be operator-only,
    not user-actionable). Logged at WARNING level by the handler.
    """

    code = CODE_GATEWAY_UNREACHABLE
    http_status = status.HTTP_503_SERVICE_UNAVAILABLE


class GatewayTimeout(LQAIError):
    """Backend's request to the gateway timed out — 504."""

    code = CODE_GATEWAY_TIMEOUT
    http_status = status.HTTP_504_GATEWAY_TIMEOUT


class GatewayInvalidResponse(LQAIError):
    """Gateway returned an unparseable / malformed response — 502.

    Indicates a contract drift between api/ and gateway/. Should be rare;
    when it fires, there's a bug in one of the two subsystems' wire-shape
    handling.
    """

    code = CODE_GATEWAY_INVALID_RESPONSE
    http_status = status.HTTP_502_BAD_GATEWAY


class ProviderUnavailable(LQAIError):
    """The gateway reported a provider-side failure — 502.

    Backend pass-through of the gateway's ``provider_unavailable`` code.
    The gateway has already exhausted fallback; there's nothing the
    backend can do but surface it.
    """

    code = CODE_PROVIDER_UNAVAILABLE
    http_status = status.HTTP_502_BAD_GATEWAY


class TierBelowMinimum(LQAIError):
    """Gateway refused — request's tier floor exceeds resolved tier — 403.

    Pass-through of the gateway's ``tier_below_minimum`` (D1). B5 carries
    the code through; D1 wires the actual refusal logic on the gateway.
    """

    code = CODE_TIER_BELOW_MINIMUM
    http_status = status.HTTP_403_FORBIDDEN


class InvalidModel(LQAIError):
    """Gateway could not resolve the requested model — 400.

    Pass-through of the gateway's ``invalid_model``.
    """

    code = CODE_INVALID_MODEL
    http_status = status.HTTP_400_BAD_REQUEST


class SkillNotFound(LQAIError):
    """The gateway reported that an attached skill is not in the registry — 404.

    Pass-through of the gateway's ``skill_not_found`` (C2). Distinct
    from a generic NotFound so callers can branch on "the chat had a
    skill attached that doesn't exist" without parsing details.
    """

    code = CODE_SKILL_NOT_FOUND
    http_status = status.HTTP_404_NOT_FOUND


class SkillFetchFailed(LQAIError):
    """The gateway could not fetch a skill from the backend (operational) — 502.

    Pass-through of the gateway's ``skill_fetch_failed`` (C2). Indicates
    a transport / timeout / 5xx between the gateway and the backend's
    internal-skills endpoint, OR a malformed response. Cleared by
    addressing the underlying problem on the backend side.
    """

    code = CODE_SKILL_FETCH_FAILED
    http_status = status.HTTP_502_BAD_GATEWAY


class SkillInputMissing(LQAIError):
    """A required skill input was not supplied — 400.

    Pass-through of the gateway's ``skill_input_missing`` (C2). The
    ``details.missing`` list names the unbound required inputs so the
    UI can prompt the user.
    """

    code = CODE_SKILL_INPUT_MISSING
    http_status = status.HTTP_400_BAD_REQUEST


# --- Code → exception class registry -----------------------------------------
# Used by the gateway-response translator (in app.clients.gateway) to map
# a structured gateway error envelope into the right LQAIError subclass.

_GATEWAY_CODE_MAP: dict[str, type[LQAIError]] = {
    "unauthorized": Unauthorized,
    "provider_unavailable": ProviderUnavailable,
    "rate_limit_exceeded": RateLimited,
    "tier_below_minimum": TierBelowMinimum,
    "tier_disallowed_globally": Forbidden,
    "anonymization_failed": InternalError,
    "invalid_model": InvalidModel,
    "invalid_request": ValidationError,
    "not_implemented": InternalError,
    "skill_not_found": SkillNotFound,
    "skill_fetch_failed": SkillFetchFailed,
    "skill_input_missing": SkillInputMissing,
    # D0.5: admin alias CRUD surfaces. The gateway emits these on the
    # admin/v1/aliases path; the backend's admin proxy passes them
    # through with the matching backend-side typed exception.
    "not_found": NotFound,
    "conflict": Conflict,
}


def map_gateway_error_code(code: str) -> type[LQAIError]:
    """Map a gateway-emitted error code to the appropriate backend exception class.

    Unknown codes fall back to :class:`InternalError` — a defensive
    posture rather than a guess. The handler logs the unknown code at
    WARNING so operators see the drift quickly.
    """

    return _GATEWAY_CODE_MAP.get(code, InternalError)


# --- Public re-exports -------------------------------------------------------
# Keep this list explicit so ``from app.errors import *`` is well-defined.
__all__ = [
    "CODE_AUTONOMOUS_COST_CAP_REACHED",
    "CODE_AUTONOMOUS_HALTED",
    "CODE_AUTONOMOUS_TOOL_NOT_GRANTED",
    "CODE_CONFLICT",
    "CODE_FORBIDDEN",
    "CODE_GATEWAY_INVALID_RESPONSE",
    "CODE_GATEWAY_TIMEOUT",
    "CODE_GATEWAY_UNREACHABLE",
    "CODE_INTERNAL_ERROR",
    "CODE_INVALID_MODEL",
    "CODE_MFA_ENROLLMENT_REQUIRED",
    "CODE_NOT_FOUND",
    "CODE_PASSWORD_CHANGE_REQUIRED",
    "CODE_PAYLOAD_TOO_LARGE",
    "CODE_PROVIDER_UNAVAILABLE",
    "CODE_RATE_LIMITED",
    "CODE_SKILL_FETCH_FAILED",
    "CODE_SKILL_INPUT_MISSING",
    "CODE_SKILL_NOT_FOUND",
    "CODE_TIER_BELOW_MINIMUM",
    "CODE_UNAUTHORIZED",
    "CODE_VALIDATION_ERROR",
    "AutonomousBrake",
    "Conflict",
    "CostCapReached",
    "Forbidden",
    "GatewayInvalidResponse",
    "GatewayTimeout",
    "GatewayUnreachable",
    "InternalError",
    "InvalidModel",
    "LQAIError",
    "MfaEnrollmentRequired",
    "NotFound",
    "PasswordChangeRequired",
    "PayloadTooLarge",
    "ProviderUnavailable",
    "RateLimited",
    "SessionHalted",
    "SkillFetchFailed",
    "SkillInputMissing",
    "SkillNotFound",
    "TierBelowMinimum",
    "ToolNotGranted",
    "Unauthorized",
    "ValidationError",
    "map_gateway_error_code",
]
