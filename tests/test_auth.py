"""Tests for auth module."""
import time
import jwt as pyjwt
import pytest
from unittest.mock import patch
from auth import _decode_token, require_auth, optional_auth, is_admin

SECRET = "test-jwt-secret-for-testing-only-32chars!"


def _token(overrides=None, secret=SECRET):
    payload = {
        "sub": "user1", "email": "user@test.com",
        "aud": "authenticated", "role": "authenticated",
        "exp": int(time.time()) + 3600, "iat": int(time.time()),
        "app_metadata": {}, "user_metadata": {},
    }
    if overrides:
        payload.update(overrides)
    return pyjwt.encode(payload, secret, algorithm="HS256")


def test_decode_valid_token():
    token = _token()
    result = _decode_token(token)
    assert result["sub"] == "user1"
    assert result["email"] == "user@test.com"


def test_decode_expired_token():
    token = _token({"exp": int(time.time()) - 100})
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        _decode_token(token)
    assert exc.value.status_code == 401
    assert "expired" in exc.value.detail.lower()


def test_decode_invalid_token():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        _decode_token("garbage.token.here")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_require_auth_valid():
    token = _token()
    result = await require_auth(f"Bearer {token}")
    assert result["sub"] == "user1"


@pytest.mark.asyncio
async def test_require_auth_invalid_scheme():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await require_auth("Basic abc123")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_require_auth_no_secret():
    with patch("auth.SUPABASE_JWT_SECRET", ""):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await require_auth("Bearer sometoken")
        assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_optional_auth_missing():
    result = await optional_auth(None)
    assert result is None


@pytest.mark.asyncio
async def test_optional_auth_invalid():
    result = await optional_auth("Bearer invalid.token.here")
    assert result is None


def test_is_admin_via_app_metadata():
    user = {"app_metadata": {"role": "admin"}, "email": "nobody@test.com"}
    assert is_admin(user) is True


def test_is_admin_via_email_fallback():
    user = {"app_metadata": {}, "email": "admin@example.com"}
    assert is_admin(user) is True


def test_is_admin_false():
    user = {"app_metadata": {}, "email": "user@test.com"}
    assert is_admin(user) is False


def test_is_admin_user_metadata_not_trusted():
    """user_metadata is user-editable and should NOT grant admin."""
    user = {"app_metadata": {}, "user_metadata": {"role": "admin"}, "email": "user@test.com"}
    assert is_admin(user) is False
