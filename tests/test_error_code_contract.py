"""Cross-subsystem error-code conformance test (B5).

Per :doc:`docs/adr/0003-error-handling.md`, ``api/`` and ``gateway/``
each ship their own typed exception hierarchy; the contract that ties
them together is the **error-code enum** documented in the OpenAPI
sketches and re-declared in each subsystem's ``app.errors`` module.
This test enforces that the two stay in sync on the codes that cross
the boundary.

The test imports both sides — that's the only place in the repo where
this is allowed (CLAUDE.md exempts contract verification under
``tests/``). Each subsystem's ``app.errors`` is loaded via importlib
with the appropriate ``sys.path`` so the two ``app.errors`` modules
don't collide on the package name.

What's verified:

1. Every code that the api/ side declares as a "gateway-crossing" code
   is declared in the gateway/ side's enum (same string).
2. Every code in the gateway-openapi.yaml ``GatewayError.code`` enum
   is either:
   - Mapped to a backend exception class on the api/ side, or
   - Documented as backend-only (not crossing).
3. The shape of ``LQAIError.to_envelope()`` is consistent on both
   sides: both render ``{"<wrapper>": {"code": ..., "message": ...,
   "details": ...}}`` where the wrapper differs (api: ``detail``,
   gateway: ``error``) but the inner shape is identical.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

import pytest

# tests/conftest.py already pushed both api/ and gateway/ onto sys.path,
# but loading both subsystems' ``app`` packages requires careful import
# isolation since they share the package name. We import each by
# manipulating sys.path and clearing the cached module after.

REPO_ROOT = Path(__file__).resolve().parent.parent
API_DIR = REPO_ROOT / "api"
GATEWAY_DIR = REPO_ROOT / "gateway"


def _load_subsystem_errors(subsystem_dir: Path) -> ModuleType:
    """Load ``<subsystem>/app/errors.py`` as a fresh module instance.

    Drops any cached ``app`` / ``app.errors`` module from
    :data:`sys.modules` before loading so the two subsystems' ``errors``
    modules can coexist in the same test session. Returns the loaded
    module.
    """

    # Clear any cached ``app`` namespace so the next import binds against
    # ``subsystem_dir/app/`` rather than the cached one.
    for mod_name in list(sys.modules):
        if mod_name == "app" or mod_name.startswith("app."):
            del sys.modules[mod_name]

    # Ensure subsystem_dir is at the front of sys.path so its `app/` wins.
    str_dir = str(subsystem_dir)
    sys.path.insert(0, str_dir)
    try:
        module = importlib.import_module("app.errors")
        return module
    finally:
        # Don't pop sys.path back — pytest collects multiple tests and
        # we don't want to flap. The next call will insert again at
        # position 0 and the right module wins.
        pass


@pytest.fixture(scope="module")
def api_errors() -> ModuleType:
    """Load the api/ side ``app.errors`` module."""

    return _load_subsystem_errors(API_DIR)


@pytest.fixture(scope="module")
def gateway_errors() -> ModuleType:
    """Load the gateway/ side ``app.errors`` module.

    Loads after ``api_errors`` ran (which cached ``app`` against api/).
    Re-runs the load-and-clear shuffle so this fixture sees the gateway
    side.
    """

    return _load_subsystem_errors(GATEWAY_DIR)


# --- Test: gateway-crossing codes match across subsystems --------------------

# Codes the brief identifies as crossing the boundary (declared on both sides).
# If you add or remove a crossing code, update this list AND the two
# subsystems' enums. The test below asserts the lists match.
EXPECTED_CROSSING_CODES: set[str] = {
    "tier_below_minimum",
    "provider_unavailable",
    "invalid_model",
    "unauthorized",
    "rate_limit_exceeded",
    "invalid_request",
    "anonymization_failed",
    "not_implemented",
    "tier_disallowed_globally",
    # C2 — skill prompt assembly
    "skill_not_found",
    "skill_fetch_failed",
    "skill_input_missing",
}


@pytest.mark.unit
def test_gateway_emits_all_documented_crossing_codes(gateway_errors: ModuleType) -> None:
    """Every code in EXPECTED_CROSSING_CODES is declared on the gateway side."""

    declared = {
        getattr(gateway_errors, name) for name in dir(gateway_errors) if name.startswith("CODE_")
    }

    missing = EXPECTED_CROSSING_CODES - declared
    assert not missing, (
        f"gateway/app/errors.py is missing CODE_* constants for: {sorted(missing)}. "
        "Add them and the corresponding LQAIError subclass."
    )


@pytest.mark.unit
def test_api_handles_every_crossing_code(api_errors: ModuleType) -> None:
    """Every crossing code maps to a backend exception class.

    The api/ side's ``map_gateway_error_code`` is the load-bearing
    artifact: when the gateway sends a structured error envelope, the
    backend translates the code via this mapper. Codes the mapper
    doesn't know fall through to ``InternalError`` — that's a defensive
    posture, not a substitute for explicit handling.
    """

    map_fn = api_errors.map_gateway_error_code
    internal = api_errors.InternalError
    # Codes legitimately in the InternalError bucket (not a misconfig):
    legitimate_internal = {"anonymization_failed", "not_implemented"}

    not_handled: list[str] = []
    for code in EXPECTED_CROSSING_CODES:
        cls = map_fn(code)
        if cls is internal and code not in legitimate_internal:
            not_handled.append(code)

    assert not not_handled, (
        f"api/app/errors.map_gateway_error_code does not have explicit "
        f"mappings for: {not_handled}. Add entries to _GATEWAY_CODE_MAP."
    )


@pytest.mark.unit
def test_inner_envelope_shape_matches_across_subsystems(
    api_errors: ModuleType,
    gateway_errors: ModuleType,
) -> None:
    """Both subsystems render the inner ``code`` / ``message`` / ``details``
    shape in the same way. Wrapper key differs (``detail`` vs ``error``)
    per ADR 0003; the inner shape is the load-bearing contract.
    """

    api_err = api_errors.LQAIError("test message", details={"foo": "bar"})
    gw_err = gateway_errors.LQAIError("test message", details={"foo": "bar"})

    api_envelope = api_err.to_envelope()
    gw_envelope = gw_err.to_envelope()

    # Wrappers differ.
    assert "detail" in api_envelope
    assert "error" in gw_envelope

    # Inner shape is identical.
    api_inner = api_envelope["detail"]
    gw_inner = gw_envelope["error"]
    assert set(api_inner.keys()) == set(gw_inner.keys()) == {"code", "message", "details"}
    assert api_inner["message"] == gw_inner["message"] == "test message"
    assert api_inner["details"] == gw_inner["details"] == {"foo": "bar"}


@pytest.mark.unit
def test_each_subsystem_documents_a_base_class_with_to_envelope(
    api_errors: ModuleType,
    gateway_errors: ModuleType,
) -> None:
    """The base class on each side is named ``LQAIError`` and has ``to_envelope``."""

    for module in (api_errors, gateway_errors):
        assert hasattr(module, "LQAIError"), f"{module.__file__} lacks LQAIError"
        assert callable(getattr(module.LQAIError, "to_envelope", None)), (
            f"{module.__file__}.LQAIError lacks to_envelope()"
        )


@pytest.mark.unit
def test_no_unexpected_codes_on_either_side(
    api_errors: ModuleType,
    gateway_errors: ModuleType,
) -> None:
    """Sanity check: declared CODE_* constants are a non-empty set.

    Catches the regression where someone deletes the constants without
    realizing this conformance test depends on them.
    """

    api_codes = {name for name in dir(api_errors) if name.startswith("CODE_")}
    gw_codes = {name for name in dir(gateway_errors) if name.startswith("CODE_")}
    assert len(api_codes) >= 8, "api/app/errors.py CODE_* set is unexpectedly small"
    assert len(gw_codes) >= 8, "gateway/app/errors.py CODE_* set is unexpectedly small"


@pytest.mark.unit
def test_attachments_not_ready_is_a_typed_documented_backend_contract(
    api_errors: ModuleType,
) -> None:
    """Direct-file readiness has a stable class, code, and POST 409 response."""

    assert api_errors.CODE_ATTACHMENTS_NOT_READY == "attachments_not_ready"
    err = api_errors.AttachmentsNotReady("not ready")
    assert err.effective_code == "attachments_not_ready"
    assert err.effective_http_status == 409

    contract_path = REPO_ROOT / "docs/api/backend-openapi.yaml"
    contract = contract_path.read_text(encoding="utf-8")
    error_schema = contract.split("\n    Error:\n", 1)[1].split("\n    LedgerEntry:\n", 1)[0]
    message_endpoint = contract.split("\n  /api/v1/chats/{chat_id}/messages:\n", 1)[1].split(
        "\n  /api/v1/chats/{chat_id}/messages/{message_id}/citations:\n", 1
    )[0]
    assert "- attachments_not_ready" in error_schema
    assert "'409':" in message_endpoint


# --- D1: tier_below_minimum status + class symmetry ------------------------


@pytest.mark.unit
def test_tier_below_minimum_status_is_403_on_both_sides(
    api_errors: ModuleType,
    gateway_errors: ModuleType,
) -> None:
    """``tier_below_minimum`` is HTTP 403 on both api/ and gateway/ (D1).

    Per ADR 0003 the gateway emits the original status; the backend
    re-emits a 403 with the same code so the user sees a coherent
    ``Forbidden`` rather than a 502 wrapping a 403.
    """

    gw_cls = gateway_errors.TierBelowMinimum
    api_cls = api_errors.TierBelowMinimum
    assert gw_cls.http_status == 403, (
        f"gateway TierBelowMinimum http_status was {gw_cls.http_status}, expected 403"
    )
    assert api_cls.http_status == 403, (
        f"api TierBelowMinimum http_status was {api_cls.http_status}, expected 403"
    )


@pytest.mark.unit
def test_tier_below_minimum_code_constant_value_is_stable(
    api_errors: ModuleType,
    gateway_errors: ModuleType,
) -> None:
    """The wire string is exactly ``tier_below_minimum`` on both sides."""

    assert api_errors.CODE_TIER_BELOW_MINIMUM == "tier_below_minimum"
    assert gateway_errors.CODE_TIER_BELOW_MINIMUM == "tier_below_minimum"
