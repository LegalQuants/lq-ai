"""LQ.AI Teams Bridge — FastAPI entry point (M3-D3).

The bridge surface is intentionally tiny at v0.3.0:

* ``GET  /healthz`` — liveness. Always 200 once the process is up.
* ``GET  /readyz`` — readiness. 200 when ``LQ_AI_BACKEND_URL`` is
  reachable; 503 otherwise.
* ``GET  /teams/oauth/install`` — kicks off the Microsoft identity
  platform admin-consent flow. See ``app.oauth``.
* ``GET  /teams/oauth/callback`` — receives Microsoft's redirect
  after the tenant admin consents.

Everything else — slash commands, Bot Framework activity routing,
per-user identity binding — is M3-D2 (descoped, see DE-288) / M3-D4
(admin UI) / community contribution scope.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from .config import Settings, get_settings
from .oauth import router as oauth_router
from .observability import init_otel

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application.

    Factored out of module-level instantiation so tests can construct
    isolated app instances with their own ``Settings`` overrides.
    """

    cfg = settings or get_settings()

    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    app = FastAPI(
        title="LQ.AI Teams Bridge",
        version="0.1.0",
        description=(
            "OAuth admin-consent + tenant persistence for the LQ.AI "
            "Microsoft Teams integration. M3-D3 plumbing. Slash-command "
            "surface deferred to M4 / community per DE-288."
        ),
    )

    init_otel(cfg)
    FastAPIInstrumentor.instrument_app(app)

    app.include_router(oauth_router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        """Readiness check — verifies the LQ.AI api is reachable.

        The bridge is useless without the api: every OAuth callback
        ends with a POST to the api's bridge-facing persistence
        endpoint. If the api is down, the bridge should report
        unready so operators see the dependency failure rather than
        a confusing OAuth callback error.
        """

        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(f"{cfg.lq_ai_backend_url}/healthz")
                if res.status_code != 200:
                    return JSONResponse(
                        status_code=503,
                        content={
                            "status": "unready",
                            "reason": f"backend returned {res.status_code}",
                        },
                    )
        except (httpx.HTTPError, OSError) as exc:
            return JSONResponse(
                status_code=503,
                content={"status": "unready", "reason": f"backend unreachable: {exc}"},
            )
        return JSONResponse(content={"status": "ok"})

    return app


app = create_app()
