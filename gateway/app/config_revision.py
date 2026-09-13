"""Opaque revision of validated configuration; never emit its source values."""

import hashlib
import json
import re

from pydantic import BaseModel

REVISION_HEADER = "X-LQ-AI-Config-Revision"


class ConfigRevisionMismatch(ValueError):
    pass


def configuration_revision(config: BaseModel) -> str:
    # Include credential configuration so a rotation also invalidates an old
    # binding. Only the digest crosses the boundary, never credential values.
    return hashlib.sha256(
        json.dumps(
            config.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def require_revision(expected: str, config: BaseModel) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", expected) is None or expected != configuration_revision(
        config
    ):
        raise ConfigRevisionMismatch("Gateway configuration changed before dispatch")
