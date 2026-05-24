"""Runtime configuration for the LQ.AI Teams Bridge.

Loaded from environment variables via ``pydantic-settings`` (same
pattern as ``api/``, ``gateway/``, and ``slack-bridge/``).

The fields divide into three groups:

* **Microsoft-side credentials** — ``MICROSOFT_APP_ID`` (Azure AD
  multi-tenant app client_id) + ``MICROSOFT_APP_PASSWORD`` (client
  secret). These come from the operator's Azure AD admin portal.
* **LQ.AI-side coordinates** — ``LQ_AI_BACKEND_URL`` (where the api
  is reachable from inside the bridge's network) and
  ``LQ_AI_BRIDGE_TOKEN`` (shared bearer with slack-bridge per M3-D3
  decision #2).
* **Bridge public URL** — ``LQ_AI_TEAMS_BRIDGE_PUBLIC_URL`` is the
  externally reachable base URL of this bridge. Microsoft's OAuth
  flow needs a public callback URL; the bridge builds it by
  appending ``/teams/oauth/callback`` to this base.

All fields are required EXCEPT for the OTel exporter URL (opt-in per
PRD §5.7's "no telemetry by default" promise) and the log level
(defaults to INFO).
"""

from __future__ import annotations

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Bridge runtime configuration."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    microsoft_app_id: str = Field(..., description="Azure AD multi-tenant app client_id.")
    microsoft_app_password: str = Field(
        ...,
        description="Azure AD app client secret (sometimes called `MICROSOFT_APP_PASSWORD`).",
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
            "LQ_AI_BRIDGE_TOKEN env var. **Reused** with slack-bridge "
            "per M3-D3 decision #2."
        ),
    )
    lq_ai_teams_bridge_public_url: str = Field(
        ...,
        description=(
            "Externally reachable base URL of the teams-bridge itself. "
            "Microsoft's OAuth flow needs this to construct the callback "
            "URL (LQ_AI_TEAMS_BRIDGE_PUBLIC_URL + /teams/oauth/callback)."
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
        default="lq-ai-teams-bridge",
        description="Resource attribute reported on every span.",
    )

    log_level: str = Field(
        default="INFO",
        description="Python logging level for the bridge process.",
    )

    @field_validator(
        "microsoft_app_id",
        "microsoft_app_password",
        "lq_ai_bridge_token",
        "lq_ai_teams_bridge_public_url",
    )
    @classmethod
    def _required_when_teams_enabled(cls, value: str, info: ValidationInfo) -> str:
        """Reject empty operator credentials at bridge startup.

        These vars use the ``${VAR:-}`` (empty-default) form in
        ``docker-compose.yml`` so a default ``docker compose up`` with the
        ``teams`` profile inactive does not abort at interpolation time
        (DE-305 — Compose interpolates every service before profile
        filtering). The "required when the profile is active" guarantee
        moves here: the bridge only constructs ``Settings`` when its
        container starts (i.e. when the ``teams`` profile is enabled), so
        an empty value fails fast with a clear message instead of starting
        a broken bridge that only errors later at OAuth time.
        """

        if not value or not value.strip():
            raise ValueError(f"{info.field_name} is required when the teams profile is enabled")
        return value


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return a process-cached :class:`Settings` instance."""

    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
