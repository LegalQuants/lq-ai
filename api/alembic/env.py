"""Alembic environment script.

Reads DATABASE_URL from the environment. Supports both sync and async
SQLAlchemy URLs — `alembic upgrade head` runs the migrations using the
sync driver under the hood, but the same env.py is reusable from async
contexts (e.g., test fixtures).

To run migrations:
    DATABASE_URL=postgresql+asyncpg://... alembic upgrade head

The application's DATABASE_URL typically uses asyncpg for runtime; for
migrations we strip the `+asyncpg` suffix so Alembic uses psycopg2 (sync).
This avoids needing a separate sync DATABASE_URL env var.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import every model module so SQLAlchemy registers them with Base.metadata.
# This is what `autogenerate` reads to compare schema vs. database state.
from app.db.base import Base
from app.models import AuditLog, InferenceRoutingLog, User, UserSession  # noqa: F401

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False so configuring alembic's own loggers does
    # not silence already-imported application loggers (e.g. app.citation.*).
    # Without this, running migrations mid-session (the test suite's per-session
    # alembic upgrade) disables every app.* logger, dropping their records and
    # breaking unrelated caplog-based tests downstream.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _resolve_database_url() -> str:
    """Resolve the DATABASE_URL for migrations.

    Strips the asyncpg dialect tag if present — Alembic runs sync.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Set it in your environment or .env "
            "before running alembic migrations."
        )
    # Convert postgresql+asyncpg:// → postgresql:// for Alembic's sync engine
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emits SQL to stdout, no DB connection."""
    url = _resolve_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _resolve_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
