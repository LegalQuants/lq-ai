"""Frozen deployment-migration chain."""

from importlib import import_module
from typing import Any


def ordered_migrations() -> tuple[Any, ...]:
    """Return migrations in their immutable linear order."""

    return (import_module("app.ops.migrations.0001_object_store_minio_to_rustfs"),)


__all__ = ["ordered_migrations"]
