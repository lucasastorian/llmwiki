"""Availability guards around pre-auth rate limiting and JWKS rotation."""

import asyncio
import time
from unittest.mock import AsyncMock, Mock

import auth
import jwt
import pytest
from fastapi import Request
from infra.rate_limit import _user_or_ip


def _unsigned_for_unknown_kid(kid: str, sub: str = "attacker") -> str:
    # Signature validity is irrelevant: unknown-kid handling occurs before the
    # signing key is available, exactly as it does for an attacker request.
    return jwt.encode(
        {"sub": sub},
        "test-signing-key-that-is-at-least-32-bytes",
        algorithm="HS256",
        headers={"kid": kid},
    )


def _request(token: str, ip: str = "203.0.113.10") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
        "client": (ip, 12345),
    })


@pytest.fixture(autouse=True)
def reset_auth_caches():
    original_cache = dict(auth._jwks_cache)
    original_last_fetch = auth._jwks_last_fetch
    original_last_attempt = auth._jwks_last_refresh_attempt
    original_unknown = auth._unknown_kids.copy()
    auth._jwks_cache.clear()
    auth._unknown_kids.clear()
    auth._jwks_last_fetch = time.monotonic()
    auth._jwks_last_refresh_attempt = 0
    try:
        yield
    finally:
        auth._jwks_cache.clear()
        auth._jwks_cache.update(original_cache)
        auth._unknown_kids.clear()
        auth._unknown_kids.update(original_unknown)
        auth._jwks_last_fetch = original_last_fetch
        auth._jwks_last_refresh_attempt = original_last_attempt


async def test_distinct_unknown_kids_share_one_refresh_cooldown(monkeypatch):
    fetch = AsyncMock()
    monkeypatch.setattr(auth, "_fetch_jwks", fetch)

    for kid in ("random-one", "random-two", "random-three"):
        with pytest.raises(ValueError, match="Unknown signing key"):
            await auth.verify_token(_unsigned_for_unknown_kid(kid))

    fetch.assert_awaited_once()


async def test_concurrent_unknown_kids_use_single_flight(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_fetch():
        started.set()
        await release.wait()

    fetch = AsyncMock(side_effect=slow_fetch)
    monkeypatch.setattr(auth, "_fetch_jwks", fetch)

    first = asyncio.create_task(auth.verify_token(_unsigned_for_unknown_kid("kid-a")))
    await started.wait()
    second = asyncio.create_task(auth.verify_token(_unsigned_for_unknown_kid("kid-b")))
    release.set()
    results = await asyncio.gather(first, second, return_exceptions=True)

    assert all(isinstance(result, ValueError) for result in results)
    fetch.assert_awaited_once()


async def test_repeated_unknown_kid_is_negative_cached(monkeypatch):
    fetch = AsyncMock()
    monkeypatch.setattr(auth, "_fetch_jwks", fetch)
    token = _unsigned_for_unknown_kid("repeat-me")

    for _ in range(3):
        with pytest.raises(ValueError, match="Unknown signing key"):
            await auth.verify_token(token)

    fetch.assert_awaited_once()
    assert "repeat-me" in auth._unknown_kids


async def test_failed_refresh_attempt_is_still_rate_limited(monkeypatch):
    fetch = AsyncMock(side_effect=RuntimeError("JWKS unavailable"))
    monkeypatch.setattr(auth, "_fetch_jwks", fetch)

    for kid in ("outage-a", "outage-b"):
        with pytest.raises(ValueError, match="Unknown signing key"):
            await auth.verify_token(_unsigned_for_unknown_kid(kid))

    fetch.assert_awaited_once()


async def test_oversized_bearer_is_rejected_before_jwt_parsing(monkeypatch):
    parse_header = Mock(wraps=auth.jwt.get_unverified_header)
    monkeypatch.setattr(auth.jwt, "get_unverified_header", parse_header)

    with pytest.raises(ValueError, match="Invalid token"):
        await auth.verify_token("x" * (auth._MAX_TOKEN_LENGTH + 1))

    parse_header.assert_not_called()


def test_pre_auth_rate_limit_ignores_unverified_subject():
    one = _user_or_ip(_request(_unsigned_for_unknown_kid("one", sub="alice")))
    two = _user_or_ip(_request(_unsigned_for_unknown_kid("two", sub="bob")))

    assert one == two == "ip:203.0.113.10"


def test_pre_auth_rate_limit_still_separates_addresses():
    token = _unsigned_for_unknown_kid("one")

    assert _user_or_ip(_request(token, "203.0.113.10")) != _user_or_ip(
        _request(token, "203.0.113.11")
    )
