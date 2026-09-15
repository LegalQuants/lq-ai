"""Unit tests for the api/ side of the lq_ai.errors hierarchy.

Per ADR 0003, the backend exception hierarchy renders to the canonical
``{"detail": {"code": ..., "message": ..., "details": ...}}`` envelope.
These tests pin the envelope shape, the HTTP-status mapping, and the
gateway-error code translation so regressions in the wire shape fail
loudly and are easy to fix.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient

from app.errors import (
    CODE_CONFLICT,
    CODE_GATEWAY_INVALID_RESPONSE,
    CODE_GATEWAY_TIMEOUT,
    CODE_GATEWAY_UNREACHABLE,
    CODE_INTERNAL_ERROR,
    CODE_INVALID_MODEL,
    CODE_PASSWORD_CHANGE_REQUIRED,
    CODE_PAYLOAD_TOO_LARGE,
    CODE_PROVIDER_UNAVAILABLE,
    CODE_RATE_LIMITED,
    CODE_TIER_BELOW_MINIMUM,
    CODE_UNAUTHORIZED,
    CODE_VALIDATION_ERROR,
    Conflict,
    Forbidden,
    GatewayInvalidResponse,
    GatewayTimeout,
    GatewayUnreachable,
    InternalError,
    InvalidModel,
    LQAIError,
    NotFound,
    PasswordChangeRequired,
    PayloadTooLarge,
    ProviderUnavailable,
    RateLimited,
    TierBelowMinimum,
    Unauthorized,
    ValidationError,
    map_gateway_error_code,
)
from app.main import app

# --- Construction & envelope shape -------------------------------------------


@pytest.mark.unit
def test_base_carries_message_and_details() -> None:
    err = LQAIError("boom", details={"hint": "check the logs"})
    assert err.message == "boom"
    assert err.details == {"hint": "check the logs"}
    assert err.effective_code == CODE_INTERNAL_ERROR
    assert err.effective_http_status == status.HTTP_500_INTERNAL_SERVER_ERROR


@pytest.mark.unit
def test_envelope_uses_detail_wrapper_with_inner_code_message_details() -> None:
    err = ValidationError("password too short", details={"min": 12})
    envelope = err.to_envelope()
    assert "detail" in envelope
    inner = envelope["detail"]
    assert inner["code"] == CODE_VALIDATION_ERROR
    assert inner["message"] == "password too short"
    assert inner["details"] == {"min": 12}


@pytest.mark.unit
def test_envelope_carries_empty_details_when_none_supplied() -> None:
    err = NotFound("nope")
    assert err.to_envelope() == {"detail": {"code": "not_found", "message": "nope", "details": {}}}


@pytest.mark.unit
def test_per_instance_overrides_take_precedence() -> None:
    err = LQAIError("oops", code=CODE_INVALID_MODEL, http_status=499)
    assert err.effective_code == CODE_INVALID_MODEL
    assert err.effective_http_status == 499
    assert err.to_envelope()["detail"]["code"] == CODE_INVALID_MODEL


@pytest.mark.unit
def test_details_dict_is_copied_so_mutation_doesnt_leak_back() -> None:
    source = {"k": 1}
    err = LQAIError("x", details=source)
    source["k"] = 2
    assert err.details == {"k": 1}, "constructor must copy the details dict"


# --- HTTP-status mapping per subclass ----------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("cls", "expected_status", "expected_code"),
    [
        (Unauthorized, status.HTTP_401_UNAUTHORIZED, CODE_UNAUTHORIZED),
        (Forbidden, status.HTTP_403_FORBIDDEN, "forbidden"),
        (NotFound, status.HTTP_404_NOT_FOUND, "not_found"),
        (ValidationError, status.HTTP_400_BAD_REQUEST, CODE_VALIDATION_ERROR),
        (RateLimited, status.HTTP_429_TOO_MANY_REQUESTS, CODE_RATE_LIMITED),
        (InternalError, status.HTTP_500_INTERNAL_SERVER_ERROR, CODE_INTERNAL_ERROR),
        (PasswordChangeRequired, status.HTTP_403_FORBIDDEN, CODE_PASSWORD_CHANGE_REQUIRED),
        (PayloadTooLarge, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, CODE_PAYLOAD_TOO_LARGE),
        (Conflict, status.HTTP_409_CONFLICT, CODE_CONFLICT),
        (GatewayUnreachable, status.HTTP_503_SERVICE_UNAVAILABLE, CODE_GATEWAY_UNREACHABLE),
        (GatewayTimeout, status.HTTP_504_GATEWAY_TIMEOUT, CODE_GATEWAY_TIMEOUT),
        (GatewayInvalidResponse, status.HTTP_502_BAD_GATEWAY, CODE_GATEWAY_INVALID_RESPONSE),
        (ProviderUnavailable, status.HTTP_502_BAD_GATEWAY, CODE_PROVIDER_UNAVAILABLE),
        (TierBelowMinimum, status.HTTP_403_FORBIDDEN, CODE_TIER_BELOW_MINIMUM),
        (InvalidModel, status.HTTP_400_BAD_REQUEST, CODE_INVALID_MODEL),
    ],
)
def test_each_subclass_has_documented_code_and_status(
    cls: type[LQAIError], expected_status: int, expected_code: str
) -> None:
    err = cls("test")
    assert err.effective_http_status == expected_status
    assert err.effective_code == expected_code


# --- FastAPI exception handler round-trip ------------------------------------


@pytest.mark.unit
async def test_handler_renders_canonical_envelope_for_arbitrary_lqai_error() -> None:
    """The handler in app.main converts LQAIError instances correctly."""

    # Build a tiny app with a handler that raises a known subclass; verify
    # the canonical envelope comes out the wire.
    test_app = FastAPI()
    # Reuse the registered handler from the real app by re-registering on
    # this throwaway app — keeps the test exercising the real handler code.
    from app.main import _lqai_error_handler

    # Starlette types add_exception_handler as taking a handler of the base
    # Exception; a narrower LQAIError handler is fine at runtime.
    test_app.add_exception_handler(LQAIError, _lqai_error_handler)  # type: ignore[arg-type]

    @test_app.get("/raise-gateway-unreachable")
    async def _raise_gw() -> None:
        raise GatewayUnreachable(
            "gateway not responding",
            details={"upstream_status": 503},
        )

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/raise-gateway-unreachable")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    body = response.json()
    assert body == {
        "detail": {
            "code": CODE_GATEWAY_UNREACHABLE,
            "message": "gateway not responding",
            "details": {"upstream_status": 503},
        }
    }


@pytest.mark.unit
async def test_app_main_handler_is_registered() -> None:
    """The real app has the LQAIError handler wired."""

    assert LQAIError in app.exception_handlers


# --- Gateway-code → backend-class map ---------------------------------------


@pytest.mark.unit
def test_map_gateway_error_code_known() -> None:
    assert map_gateway_error_code("provider_unavailable") is ProviderUnavailable
    assert map_gateway_error_code("tier_below_minimum") is TierBelowMinimum
    assert map_gateway_error_code("invalid_model") is InvalidModel
    assert map_gateway_error_code("rate_limit_exceeded") is RateLimited
    assert map_gateway_error_code("unauthorized") is Unauthorized
    assert map_gateway_error_code("invalid_request") is ValidationError


@pytest.mark.unit
def test_map_gateway_error_code_unknown_returns_internal() -> None:
    assert map_gateway_error_code("totally-made-up") is InternalError


@pytest.mark.unit
def test_map_gateway_error_code_covers_every_documented_gateway_code() -> None:
    """Every code in the gateway-openapi GatewayError enum must map.

    The cross-subsystem conformance test under tests/ exercises the
    full enum; this one is a fast in-process sanity check that the
    backend's mapping table covers what the gateway documents.
    """

    # Codes documented in docs/api/gateway-openapi.yaml's GatewayError.
    documented = {
        "tier_below_minimum",
        "tier_disallowed_globally",
        "anonymization_failed",
        "invalid_model",
        "provider_unavailable",
        "rate_limit_exceeded",
        "invalid_request",
        "not_implemented",
        "unauthorized",
    }
    for code in documented:
        assert map_gateway_error_code(code) is not InternalError or code in {
            # InternalError is the legitimate fallback for these — adapter
            # internals we treat as opaque server problems on the backend.
            "anonymization_failed",
            "not_implemented",
        }, f"code {code!r} must have an explicit backend mapping"
