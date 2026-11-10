"""JWT credential-version validation; no database required."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.config import get_settings
from app.security.jwt import (
    create_access_token,
    create_mfa_token,
    decode_access_token,
    decode_mfa_token,
)


@pytest.mark.parametrize("kind", ["access", "mfa"])
@pytest.mark.parametrize("version", [None, -1, True, "1", 1.0])
def test_invalid_or_missing_credential_version_is_rejected(kind: str, version: object) -> None:
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid.uuid4()),
        "email": "user@example.com",
        "is_admin": False,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=1)).timestamp()),
        "typ": kind,
    }
    if version is not None:
        payload["credential_version"] = version
    token = jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")
    decoder = decode_access_token if kind == "access" else decode_mfa_token
    assert decoder(token) is None


def test_tokens_carry_the_current_credential_version() -> None:
    user_id = uuid.uuid4()
    access = decode_access_token(
        create_access_token(user_id, "user@example.com", is_admin=False, credential_version=4)
    )
    mfa = decode_mfa_token(create_mfa_token(user_id, credential_version=4))
    assert access is not None and access.credential_version == 4
    assert mfa is not None and mfa.credential_version == 4
    assert access.expires_at > access.issued_at
    assert mfa.expires_at > mfa.issued_at
