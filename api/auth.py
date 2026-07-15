import asyncio
import logging
import time
from collections import OrderedDict

import httpx
import jwt
from config import settings
from fastapi import HTTPException, Request
from jwt import PyJWK

logger = logging.getLogger(__name__)

# Bounded TTL ensures we periodically pick up Supabase key rotations.
_jwks_cache: dict[str, PyJWK] = {}
_jwks_last_fetch: float = 0
_jwks_last_refresh_attempt: float = 0
_JWKS_TTL_SECONDS = 15 * 60
_JWKS_MIN_REFRESH_SECONDS = 10
_jwks_lock = asyncio.Lock()

# Unknown key IDs are attacker-controlled because the JWT header is parsed
# before signature verification. Keep a small negative cache so repeated misses
# fail locally, and bound it so random kids cannot grow process memory forever.
_UNKNOWN_KID_TTL_SECONDS = 30
_UNKNOWN_KID_CACHE_MAX = 256
_unknown_kids: OrderedDict[str, float] = OrderedDict()

_MAX_TOKEN_LENGTH = 16 * 1024
_MAX_KID_LENGTH = 256


def _jwks_is_stale() -> bool:
    return time.monotonic() - _jwks_last_fetch >= _JWKS_TTL_SECONDS


async def _fetch_jwks() -> None:
    global _jwks_last_fetch
    url = f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=10)
        resp.raise_for_status()
    data = resp.json()
    new_cache: dict[str, PyJWK] = {}
    for key_data in data.get("keys", []):
        kid = key_data.get("kid")
        if kid:
            new_cache[kid] = PyJWK(key_data)
    _jwks_cache.clear()
    _jwks_cache.update(new_cache)
    for kid in new_cache:
        _unknown_kids.pop(kid, None)
    _jwks_last_fetch = time.monotonic()
    logger.info("Fetched %d JWKS keys from Supabase", len(_jwks_cache))


async def _refresh_jwks_if_needed(force: bool = False, kid: str | None = None) -> None:
    """Refresh JWKS at most once per cooldown, including unknown-kid misses.

    ``kid`` lets a waiter re-check whether another request already fetched the
    key after acquiring the single-flight lock.
    """
    global _jwks_last_refresh_attempt
    async with _jwks_lock:
        if kid and kid in _jwks_cache:
            return

        now = time.monotonic()
        if now - _jwks_last_refresh_attempt < _JWKS_MIN_REFRESH_SECONDS:
            return
        if not force and not _jwks_is_stale():
            return

        # Record attempts, not only successful fetches. Otherwise a JWKS outage
        # turns every authentication request into another outbound HTTP call.
        _jwks_last_refresh_attempt = now
        try:
            await _fetch_jwks()
        except Exception:
            logger.exception("JWKS refresh failed; keeping previous cache")


async def prefetch_jwks() -> None:
    """Eager fetch at app startup so the first request doesn't pay cold-cache cost."""
    global _jwks_last_refresh_attempt
    _jwks_last_refresh_attempt = time.monotonic()
    try:
        await _fetch_jwks()
    except Exception:
        logger.exception("Initial JWKS fetch failed; will retry on first auth")


_EXPECTED_ISSUER = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1"


async def verify_token(token: str) -> str:
    """Verify a Supabase JWT and return the user_id (sub claim). Raises ValueError on failure."""
    if not token or len(token) > _MAX_TOKEN_LENGTH:
        raise ValueError("Invalid token")

    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError:
        raise ValueError("Invalid token")

    kid = header.get("kid")
    if not isinstance(kid, str) or not kid or len(kid) > _MAX_KID_LENGTH:
        raise ValueError("Token missing kid header")

    if _jwks_is_stale():
        await _refresh_jwks_if_needed()

    if kid not in _jwks_cache:
        now = time.monotonic()
        negative_until = _unknown_kids.get(kid)
        if negative_until is not None:
            if negative_until > now:
                raise ValueError("Unknown signing key")
            _unknown_kids.pop(kid, None)

        await _refresh_jwks_if_needed(force=True, kid=kid)
        if kid not in _jwks_cache:
            _unknown_kids[kid] = time.monotonic() + _UNKNOWN_KID_TTL_SECONDS
            _unknown_kids.move_to_end(kid)
            while len(_unknown_kids) > _UNKNOWN_KID_CACHE_MAX:
                _unknown_kids.popitem(last=False)
            raise ValueError("Unknown signing key")

    jwk = _jwks_cache[kid]
    try:
        payload = jwt.decode(
            token,
            jwk.key,
            algorithms=["ES256"],
            audience="authenticated",
            issuer=_EXPECTED_ISSUER,
            leeway=30,
            options={
                "require": ["exp", "iat", "sub", "aud", "iss"],
                "verify_exp": True,
                "verify_iat": True,
                "verify_nbf": True,
            },
        )
    except jwt.InvalidTokenError as e:
        logger.debug("JWT verification failed: %s", e)
        raise ValueError("Invalid token")

    user_id = payload.get("sub")
    if not user_id:
        raise ValueError("Token missing sub claim")

    return user_id


async def get_current_user(request: Request) -> str:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")

    token = auth_header.removeprefix("Bearer ").strip()
    try:
        return await verify_token(token)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token")
