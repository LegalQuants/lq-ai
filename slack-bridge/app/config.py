"""Runtime configuration for the LQ.AI Slack Bridge.

Loaded from environment variables via ``pydantic-settings`` (same
pattern as ``api/`` and ``gateway/``). All Slack secrets are supplied
by the operator; the bridge holds nothing baked into the image.

The fields divide into three groups:

* **Slack-side credentials** — ``SLACK_CLIENT_ID``, ``SLACK_CLIENT_SECRET``,
  ``SLACK_SIGNING_SECRET``. These come from the operator's Slack App
  admin UI (one Slack App per LQ.AI deployment that uses Slack).
* **LQ.AI-side coordinates** — ``LQ_AI_BACKEND_URL`` (where the api is
  reachable from inside the compose network) and ``LQ_AI_BRIDGE_TOKEN``
  (shared secret for the internal bridge → api channel).
* **Bridge public URL** — ``LQ_AI_BRIDGE_PUBLIC_URL`` is the externally
  reachable base URL of the bridge itself (e.g. ``https://lqai.example.com/slack``).
  Slack's OAuth flow needs a public callback URL; the bridge builds it
  by appending ``/slack/oauth/callback`` to this base.

All fields are required EXCEPT for the OTel exporter URL (opt-in per
PRD §5.7's "no telemetry by default" promise) and the log level
(defaults to INFO).
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Bridge runtime configuration."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    slack_client_id: str = Field(..., description="Slack App OAuth client id.")
    slack_client_secret: str = Field(..., description="Slack App OAuth client secret.")
    slack_signing_secret: str = Field(
        ...,
        description=(
            "Slack signing secret — verifies inbound webhook requests "
            "via the X-Slack-Signature + X-Slack-Request-Timestamp pair."
        ),
    )

    lq_ai_backend_url: str = Field(
        ...,
        description=(
            "Base URL of the LQ.AI api as reachable from inside the "
            "bridge's network (e.g. http://api:8000 in compose)."
        ),
    )
    lq_ai_bridge_token: str = Field(
        ...,
        description=(
            "Shared secret the bridge sends on every internal call to "
            "the api. The api verifies this matches its own "
            "LQ_AI_BRIDGE_TOKEN env var at every bridge-facing endpoint."
        ),
    )
    lq_ai_bridge_public_url: str = Field(
        ...,
        description=(
            "Externally reachable base URL of the bridge itself. Slack's "
            "OAuth flow needs this to construct the callback URL "
            "(LQ_AI_BRIDGE_PUBLIC_URL + /slack/oauth/callback)."
        ),
    )

    # Observability — opt-in per PRD §5.7.
    otel_exporter_otlp_endpoint: str | None = Field(
        default=None,
        description=(
            "OpenTelemetry collector endpoint. If unset, the bridge does "
            "not initialise the TracerProvider — no telemetry leaves the "
            "deployment (PRD §5.7 no-telemetry-by-default)."
        ),
    )
    otel_service_name: str = Field(
        default="lq-ai-slack-bridge",
        description="Resource attribute reported on every span.",
    )

    log_level: str = Field(
        default="INFO",
        description="Python logging level for the bridge process.",
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return a process-cached :class:`Settings` instance.

    Cached so the env-var read happens once at process start. Tests
    that need a different value should construct ``Settings(...)``
    directly via the FastAPI dependency override mechanism.
    """

    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
