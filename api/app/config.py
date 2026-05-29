"""Application configuration via pydantic-settings.

All values are loaded from environment variables (or a `.env` file) and
validated by Pydantic. The variable names match the inventory in
`.env.example` so a deployment configured per the documented quickstart
flows directly into this object.

The settings object is cached via `lru_cache` so importing modules can
call `get_settings()` cheaply; tests that need a different configuration
clear the cache via `get_settings.cache_clear()` after monkeypatching env.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["debug", "info", "warning", "warn", "error", "critical"]


class Settings(BaseSettings):
    """Backend API configuration.

    Field grouping mirrors `.env.example`. Only fields the backend reads are
    declared here — provider keys and Mode-2 / Ollama variables are read by
    the gateway, not by `api/`.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ----- Postgres -----
    # SQLAlchemy async URL form, e.g. postgresql+asyncpg://user:pass@host:5432/db.
    # In Compose this is composed in docker-compose.yml; in local dev it is
    # typically taken straight from .env.
    database_url: str = Field(
        default="postgresql+asyncpg://lq_ai:lq_ai@localhost:5432/lq_ai",
        description="Async SQLAlchemy URL for Postgres.",
    )

    # ----- Redis -----
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis URL used for sessions, queues, and rate limits.",
    )

    # ----- MinIO / S3 -----
    s3_endpoint_url: str = Field(
        default="http://localhost:9000",
        description="S3-compatible endpoint URL (MinIO in Compose; S3 in prod).",
    )
    s3_access_key: str = Field(default="", description="S3 access key.")
    s3_secret_key: str = Field(default="", description="S3 secret key.")
    s3_bucket: str = Field(default="lq-ai-files", description="S3 bucket for uploaded files.")
    s3_region: str = Field(default="us-east-1", description="S3 region.")

    # ----- File upload limits (Task C4) -----
    # Per-request cap on uploaded-file size. Documented in `.env.example`
    # as ``LQ_AI_MAX_UPLOAD_SIZE_MB``. The handler streams the body and
    # raises 413 (PayloadTooLarge) the instant the running byte count
    # exceeds the limit; we never load the full body into memory just to
    # check the size. Operators raising this should ensure their reverse
    # proxy / ingress (nginx/Traefik) raises its own ``client_max_body_size``
    # in step.
    lq_ai_max_upload_size_mb: int = Field(
        default=100,
        description=(
            "Per-request cap on uploaded-file size in MB. M1 default: 100. "
            "Streamed enforcement; never loads the body into memory to "
            "measure. Operators raising this must also raise their "
            "ingress's body-size limit."
        ),
    )

    # ----- Document pipeline (Task C5) -----
    # Concurrency: how many ingest jobs the arq worker runs in parallel.
    # 2 is the conservative default for M1 — both Docling and PyMuPDF are
    # CPU-bound and we don't want to starve the host. Operators with
    # multi-core dedicated hosts should bump this.
    lq_ai_ingest_worker_concurrency: int = Field(
        default=2,
        description=(
            "Concurrency of the document-pipeline arq worker. Each job runs "
            "Docling + PyMuPDF (CPU-bound); 2 is conservative."
        ),
    )

    # Docling can take a while on multi-page PDFs (legal contracts run
    # 20-100 pages routinely). 5 minutes per file is a generous default;
    # operators with structurally larger documents should raise.
    lq_ai_docling_timeout_seconds: int = Field(
        default=300,
        description=(
            "Per-job timeout for the document pipeline (Docling + PyMuPDF + "
            "chunking + persistence). Default 300 seconds."
        ),
    )

    # When False, skip the Docling pass entirely and run PyMuPDF only.
    # Useful for environments where Docling can't be installed (e.g.
    # constrained Python builds or CI runners without HuggingFace
    # network access).
    lq_ai_docling_enabled: bool = Field(
        default=True,
        description=(
            "When True (default), run Docling for structured-content "
            "extraction. When False, skip Docling and use PyMuPDF only "
            "for offsets and content."
        ),
    )

    # Chunker target / overlap. The defaults are tuned for ~500-token
    # chunks at the typical English-prose char/token ratio.
    lq_ai_chunk_target_chars: int = Field(
        default=2_000,
        description=(
            "Target chunk size in characters. The chunker snaps the actual "
            "boundary to a sentence terminator within a 200-char lookback "
            "when possible."
        ),
    )
    lq_ai_chunk_overlap_chars: int = Field(
        default=200,
        description=(
            "Characters of overlap between consecutive chunks. Aids "
            "boundary-spanning citations during retrieval."
        ),
    )

    # ----- Inference Gateway -----
    lq_ai_gateway_url: str = Field(
        default="http://localhost:8001",
        description="Inference Gateway base URL.",
    )
    lq_ai_gateway_key: str = Field(
        default="",
        description="Shared secret for backend ↔ gateway. Required in prod.",
    )

    # ----- JWT (per ADR 0002 — backend owns auth) -----
    jwt_secret: str = Field(
        default="dev-jwt-secret-change-me",
        description="Signing secret for JWT access and refresh tokens.",
    )
    jwt_access_token_ttl_seconds: int = Field(
        default=900,
        description="Access-token TTL in seconds. Default: 15 minutes.",
    )
    jwt_refresh_token_ttl_seconds: int = Field(
        default=604800,
        description="Refresh-token TTL in seconds. Default: 7 days.",
    )

    # M-Sec.1 — session timeouts per PRD §5.1. Both are configurable;
    # defaults match the PRD's stated floor (8h absolute, 30m idle).
    # The refresh handler enforces both; access tokens themselves use
    # ``jwt_access_token_ttl_seconds``. Setting either timeout shorter
    # than the access-token TTL effectively means "the access token
    # outlives the session" — operators tuning the absolute below
    # ``jwt_access_token_ttl_seconds`` should also shorten the access
    # token to match (or accept the implicit drift).
    session_absolute_timeout_seconds: int = Field(
        default=28800,  # 8h
        description=(
            "Absolute session timeout in seconds. Copied verbatim "
            "across refresh-token rotations; the refresh endpoint "
            "401s when exceeded. PRD §5.1 default: 8 hours."
        ),
    )
    session_idle_timeout_seconds: int = Field(
        default=1800,  # 30m
        description=(
            "Idle session timeout in seconds. Refreshing the access "
            "token resets the clock; the refresh endpoint 401s when "
            "exceeded. PRD §5.1 default: 30 minutes."
        ),
    )

    # ----- Autonomous (M4) -----
    # Global fallback cap on per-session cost for autonomous sessions
    # whose spawning trigger (watch or schedule) did not specify
    # ``max_cost_usd``. Mirrors the gateway.yaml default. R4 (the
    # economic brake) trips when projected cost would exceed this cap.
    autonomous_default_max_cost_usd: Decimal = Field(
        default=Decimal("5.00"),
        description=(
            "Global default per-session cost cap (USD) for autonomous sessions "
            "spawned by a watch or schedule that did not set max_cost_usd. "
            "Mirrors the gateway.yaml default. R4 (economic brake) trips when "
            "projected cost would exceed this cap."
        ),
        validation_alias=AliasChoices("LQ_AI_AUTONOMOUS_DEFAULT_MAX_COST_USD"),
    )

    # Default model the analysis node passes to the gateway when neither
    # the spawning trigger (watch/schedule ``params["model"]``) nor the
    # target skill/playbook pinned one. Mirrors the gateway.yaml deployment
    # default. Operators may override via the env var; the value must be a
    # model identifier the gateway recognises in its routing table.
    autonomous_default_model: str = Field(
        default="claude-opus-4-7",
        description=(
            "Fallback chat-completion model used by the autonomous "
            "analysis node when ``params['model']`` is not set on the "
            "session. Must be a model id the gateway can route."
        ),
        validation_alias=AliasChoices("LQ_AI_AUTONOMOUS_DEFAULT_MODEL"),
    )

    # M-Sec.1 — MFA-mandatory deployment flag per PRD §5.1. When True,
    # the backend treats any authenticated user without MFA enrolled
    # as not-fully-authenticated for normal endpoints — they can only
    # call the MFA enrollment flow (and a small whitelist of safe
    # endpoints like ``/users/me`` and ``/auth/logout``). Operators
    # handling client-confidential data are expected to enable this.
    mfa_mandatory: bool = Field(
        default=False,
        description=(
            "Require MFA enrollment for every user. When True, "
            "non-enrolled users are gated to the MFA-setup endpoints "
            "until they enroll."
        ),
    )

    # ----- Password hashing (per ADR 0002) -----
    # Default 12 rounds matches bcrypt's library default and the OWASP
    # password-storage recommendation. Operators may tune downward in CI
    # (where speed matters and threat-model is internal) or upward for
    # high-assurance deployments. The cost factor is per-hash; verifying
    # an existing hash respects whatever cost factor it was minted with.
    bcrypt_rounds: int = Field(
        default=12,
        description="Bcrypt cost factor for password hashing. Default 12.",
    )

    # ----- First-run admin (per Task B2) -----
    # Email used for the auto-created first-run admin. Operators can override
    # this via environment before the first `docker compose up` to control
    # which address the bootstrapped admin uses. The email is never changed
    # after first-run by the bootstrap (only by manual operator action).
    first_run_admin_email: str = Field(
        default="admin@lq.ai",
        description=(
            "Email for the auto-created first-run admin user. Set before "
            "first deployment; ignored on subsequent restarts."
        ),
    )

    # Minimum length for user-set passwords (the change-password endpoint
    # rejects shorter inputs). 12 is a reasonable floor for an admin tool;
    # individual operators may raise but should not lower it.
    password_min_length: int = Field(
        default=12,
        description="Minimum length for user-set passwords. Default: 12 characters.",
    )

    # ----- MFA challenge token (per ADR 0002 / PRD §5.1) -----
    # Issued by /auth/login when the user has mfa_enabled=true; redeemed
    # by /auth/mfa/verify (D5) within this window. Short-lived: 5 minutes
    # is enough for a user to fish their TOTP code out of an authenticator
    # app and submit it; longer windows widen the replay surface.
    mfa_token_ttl_seconds: int = Field(
        default=300,
        description="MFA challenge token TTL in seconds. Default: 5 minutes.",
    )

    # ----- GDPR Article 17 grace period (per Task D6 / PRD §5.3) -----
    # When a user calls /users/me/delete, deletion_scheduled_at is set to
    # now() + this many days. The hard-delete worker scans daily and only
    # touches users whose schedule has elapsed. 30 days is the GDPR-typical
    # default; operators with stricter retention policies may shorten it,
    # and tests use 0 to exercise the cascade path immediately.
    gdpr_grace_period_days: int = Field(
        default=30,
        ge=0,
        description=(
            "Days between a user's account-deletion request and hard "
            "deletion. 0 hard-deletes on the next worker tick; the GDPR-"
            "typical default is 30."
        ),
    )

    # ----- Skill registry (per Task C1 / ADR 0004) -----
    # Filesystem path the skill loader walks at startup (and re-walks on
    # SIGHUP). Defaults to the repo's `skills/` directory; in tests and
    # operator-side overlays this is overridden to a fixture or merged
    # directory. Resolved against the process working directory if
    # relative — the API container's WORKDIR is `/app`, so a relative
    # default is anchored there.
    skills_dir: str = Field(
        default="../skills",
        description=(
            "Filesystem directory the skill loader walks at startup and "
            "on SIGHUP. Default is the repo's `skills/` folder."
        ),
    )

    # Optional override for the community skills directory. When unset (the
    # default), the loader auto-discovers the community submodule at
    # ``<skills_dir>/community/skills/`` (i.e., ``skills/community/skills/``
    # relative to the repo root). Set this to a different path if you mount
    # the community corpus at a custom location. An empty string or a path
    # that does not exist disables community skill loading silently.
    community_skills_dir: str | None = Field(
        default=None,
        description=(
            "Override for the community skills directory. Defaults to "
            "`skills/community/skills/` relative to the repo root. "
            "Set to an empty string to disable community skill loading."
        ),
    )

    # ----- M3-D1 slack-bridge integration -----
    # The slack-bridge runs the OAuth dance with Slack then POSTs the
    # resulting workspace record to
    # ``POST /api/v1/integrations/slack/workspaces``. Both secrets here
    # live on the api ONLY (NOT on the gateway): the gateway has no
    # role in the Slack OAuth surface, and keeping its secret surface
    # minimal is a load-bearing posture. Different from the gateway's
    # ``LQ_AI_GATEWAY_MASTER_KEY`` on purpose — Slack bot tokens enable
    # bot impersonation; provider keys enable inference routing.
    # Different blast radii → different keys.
    lq_ai_bridge_token: str = Field(
        default="",
        description=(
            "Shared bearer token the slack-bridge presents on POSTs to "
            "/api/v1/integrations/slack/workspaces. Constant-time matched."
        ),
    )
    lq_ai_bridge_master_key: str = Field(
        default="",
        description=(
            "urlsafe-base64 Fernet master key used to encrypt Slack bot "
            "tokens at rest (and any future bridge-issued secret)."
        ),
    )

    # ----- Operational -----
    log_level: LogLevel = Field(default="info", description="Log level for the api/ service.")
    lq_ai_dev_mode: bool = Field(
        default=False,
        description="When true, relax some safety checks for local development.",
    )

    # ----- SMTP / email transport (M4-C1) -----
    # Optional best-effort email transport for autonomous notifications.
    # Email is enabled IFF ``smtp_host`` is set; with it unset the notify
    # handler's email step is a clean no-op (the durable in-app row is the
    # record regardless). No new dependency — the sender uses stdlib
    # ``smtplib`` run via ``asyncio.to_thread`` (CLAUDE.md SBOM posture).
    smtp_host: str | None = Field(
        default=None,
        description=(
            "SMTP server hostname for autonomous-notification email. "
            "Unset disables email transport (in-app notifications still work)."
        ),
    )
    smtp_port: int = Field(
        default=587,
        description="SMTP server port. Default 587 (STARTTLS submission).",
    )
    smtp_username: str | None = Field(
        default=None,
        description="SMTP auth username. Unset skips login (open relay / no auth).",
    )
    smtp_password: str | None = Field(
        default=None,
        description="SMTP auth password. Unset skips login.",
    )
    smtp_from: str | None = Field(
        default=None,
        description=(
            "From address for notification email. Falls back to ``smtp_username`` when unset."
        ),
    )
    smtp_use_tls: bool = Field(
        default=True,
        description="Issue STARTTLS after connecting. Default True.",
    )
    smtp_timeout: int = Field(
        default=10,
        description=(
            "Socket timeout (seconds) for the SMTP connection — applies to "
            "connect, STARTTLS, and send. Bounds the best-effort send so a "
            "hung/black-holing mail server can't tie up a worker thread."
        ),
    )

    # ----- CORS -----
    # Comma-separated list of origins allowed to call the api from the
    # browser. Production deployments typically front web + api at the
    # same origin via a reverse proxy and leave this UNSET (no CORS).
    # Local Compose dev needs http://localhost:3000 because web (:3000)
    # and api (:8000) live at different origins.
    lq_ai_cors_origins: str = Field(
        default="",
        description=(
            "Comma-separated allowed origins for CORS. Empty disables CORS. "
            "For local Compose dev set to http://localhost:3000."
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached Settings instance.

    Tests that need a different config call `get_settings.cache_clear()` after
    monkeypatching environment variables.
    """
    return Settings()
