"""LQ.AI Slack Bridge — FastAPI entry point (M3-D1).

The bridge surface is intentionally tiny at v0.3.0:

* ``GET  /healthz`` — liveness. Always 200 once the process is up.
* ``GET  /readyz`` — readiness. 200 when ``LQ_AI_BACKEND_URL`` is
  reachable; 503 otherwise. Operators wire this into their orchestrator
  to gate traffic to the bridge.
* ``GET  /slack/oauth/install`` — kicks off the OAuth install flow.
  See ``app.oauth``.
* ``GET  /slack/oauth/callback`` — receives Slack's redirect after the
  user consents.
* ``POST /slack/events`` — inbound webhook from Slack. At v0.3.0 the
  bridge verifies the signature and returns 200; the handler stub is
  the foundation M3-D2 (slash commands, descoped to M4 per DE-288)
  will fill in.

Everything else — slash commands, message handlers, per-user identity
binding — is M3-D2 / M3-D4 / community contribution scope.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import FastAPI, HTTPException, Request
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
        title="LQ.AI Slack Bridge",
        version="0.1.0",
        description=(
            "OAuth install + workspace persistence for the LQ.AI Slack "
            "integration. M3-D1 plumbing. Slash-command surface deferred "
            "to M4 / community per DE-288."
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
        endpoint. If the api is down, the bridge should report unready
        so operators see the dependency failure rather than a
        confusing OAuth callback error.
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

    @app.post("/slack/events")
    async def slack_events(request: Request) -> dict[str, str]:
        """Inbound webhook stub.

        Verifies the Slack signature (per the Events API requirement)
        and returns 200. The handler body is left for M3-D2 / community
        contribution to fill in once the slash-command surface lands.

        Even at v0.3.0, signature verification matters: it prevents an
        attacker from POSTing fake events at the bridge and getting
        any observable response. The signature check is the substrate
        the slash-command handler will rely on.
        """

        from .signing import verify_slack_signature

        body = await request.body()
        timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
        signature = request.headers.get("X-Slack-Signature", "")
        if not verify_slack_signature(
            signing_secret=cfg.slack_signing_secret,
            timestamp=timestamp,
            body=body,
            signature=signature,
        ):
            raise HTTPException(status_code=401, detail="invalid Slack signature")

        # Slack's "url_verification" handshake — Slack sends a one-off
        # POST with `{"type":"url_verification","challenge":"..."}`
        # when the operator configures the Events API URL. Responding
        # with the challenge value confirms the URL belongs to the
        # bridge.
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if isinstance(payload, dict) and payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge", "")}

        # All other event types are a no-op at v0.3.0 — M3-D2 will
        # extend this branch.
        return {"status": "ok"}

    return app


app = create_app()
