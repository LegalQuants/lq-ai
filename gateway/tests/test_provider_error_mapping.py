"""Unit tests for provider-error classification (P1 error-code accuracy).

The load-bearing contract these tests pin:

* An upstream **4xx** (the provider rejected the request we assembled) is
  a request-side, non-retryable failure → ``invalid_request`` / HTTP 400,
  NOT the outage code ``provider_unavailable`` / 502. This stops clients
  retrying a request that can never succeed and keeps outage dashboards
  free of caller/config errors.
* Upstream **5xx** and network failures remain ``provider_unavailable``.
* 429, the invalid_model 404, auth, and unsupported keep their dedicated
  mappings.
* The classification is applied on BOTH the non-streaming mapper and the
  routing-log failure-reason builder (so a streaming 4xx is logged as a
  rejection, not an outage).
"""

from __future__ import annotations

import json

import pytest

from app.api.inference import (
    _classify_provider_error,
    _failure_reason,
    _map_provider_error_to_response,
)
from app.providers.base import (
    ProviderAdapterError,
    ProviderAuthError,
    ProviderHTTPError,
    ProviderNetworkError,
    ProviderUnsupportedError,
)


def _decode(exc: ProviderAdapterError) -> tuple[int, str]:
    response = _map_provider_error_to_response(exc)
    body = json.loads(bytes(response.body))
    return response.status_code, body["error"]["code"]


@pytest.mark.unit
@pytest.mark.parametrize("upstream", [400, 403, 404, 413, 422, 499])
def test_upstream_4xx_maps_to_invalid_request(upstream: int) -> None:
    """Any non-429 upstream 4xx is a request-side 400, not an outage."""

    status_code, code = _decode(ProviderHTTPError("bad request", upstream_status=upstream))
    assert status_code == 400
    assert code == "invalid_request"


@pytest.mark.unit
@pytest.mark.parametrize("upstream", [500, 502, 503, 504])
def test_upstream_5xx_stays_provider_unavailable(upstream: int) -> None:
    """Upstream 5xx is a genuine outage → provider_unavailable / 502."""

    status_code, code = _decode(ProviderHTTPError("svc down", upstream_status=upstream))
    assert status_code == 502
    assert code == "provider_unavailable"


@pytest.mark.unit
def test_upstream_429_stays_rate_limit_exceeded() -> None:
    status_code, code = _decode(ProviderHTTPError("slow down", upstream_status=429))
    assert status_code == 429
    assert code == "rate_limit_exceeded"


@pytest.mark.unit
def test_invalid_model_404_keeps_dedicated_mapping() -> None:
    """A 404 the adapter tagged invalid_model still surfaces as invalid_model/400."""

    exc = ProviderHTTPError("model not pulled", upstream_status=404)
    exc.code = "invalid_model"
    status_code, code = _decode(exc)
    assert status_code == 400
    assert code == "invalid_model"


@pytest.mark.unit
def test_network_error_stays_provider_unavailable_503() -> None:
    status_code, code = _decode(ProviderNetworkError("dns failure"))
    assert status_code == 503
    assert code == "provider_unavailable"


@pytest.mark.unit
def test_auth_error_stays_unauthorized_502() -> None:
    status_code, code = _decode(ProviderAuthError("bad key"))
    assert status_code == 502
    assert code == "unauthorized"


@pytest.mark.unit
def test_unsupported_stays_not_implemented_501() -> None:
    status_code, code = _decode(ProviderUnsupportedError("no embeddings"))
    assert status_code == 501
    assert code == "not_implemented"


@pytest.mark.unit
def test_classifier_is_pure_tuple() -> None:
    """The shared classifier returns (code, status) without building a response."""

    assert _classify_provider_error(ProviderHTTPError("x", upstream_status=400)) == (
        "invalid_request",
        400,
    )
    assert _classify_provider_error(ProviderHTTPError("x", upstream_status=503)) == (
        "provider_unavailable",
        502,
    )


@pytest.mark.unit
def test_failure_reason_records_classified_code_and_upstream_status() -> None:
    """Routing-log reason distinguishes a 4xx rejection from a 5xx outage."""

    rejected = _failure_reason(ProviderHTTPError("bad", upstream_status=400))
    assert rejected == "upstream_error:invalid_request:status=400"

    outage = _failure_reason(ProviderHTTPError("down", upstream_status=503))
    assert outage == "upstream_error:provider_unavailable:status=503"

    network = _failure_reason(ProviderNetworkError("dns"))
    assert network == "upstream_error:provider_unavailable"
