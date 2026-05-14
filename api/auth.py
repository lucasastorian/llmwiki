import asyncio
import logging
import time

import httpx
import jwt
from jwt import PyJWK
from fastapi import HTTPException, Request

from config import settings

logger = logging.getLogger(__name__)

# Bounded TTL ensures we periodically pick up Supabase key rotations.
_jwks_cache: dict[str, PyJWK] = {}
_jwks_last_fetch: float = 0
_JWKS_TTL_SECONDS = 15 * 60
_JWKS_MIN_REFRESH_SECONDS = 10
_jwks_lock = asyncio.Lock()


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
    _jwks_last_fetch = time.monotonic()
    logger.info("Fetched %d JWKS keys from Supabase", len(_jwks_cache))


async def _refresh_jwks_if_needed(force: bool = False) -> None:
    """Serialize concurrent refreshes; force=True bypasses staleness check (used when kid is unknown)."""
    async with _jwks_lock:
        elapsed = time.monotonic() - _jwks_last_fetch
        # MIN_REFRESH only gates non-forced calls; an unknown kid (force=True)
        # bypasses it so a freshly rotated key resolves immediately.
        if not force and elapsed < _JWKS_MIN_REFRESH_SECONDS:
            return
        if not force and not _jwks_is_stale():
            return
        try:
            await _fetch_jwks()
        except Exception:
            logger.exception("JWKS refresh failed; keeping previous cache")


async def prefetch_jwks() -> None:
    """Eager fetch at app startup so the first request doesn't pay cold-cache cost."""
    try:
        await _fetch_jwks()
    except Exception:
        logger.exception("Initial JWKS fetch failed; will retry on first auth")


_EXPECTED_ISSUER = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1"


async def verify_token(token: str) -> str:
    """Verify a Supabase JWT and return the user_id (sub claim). Raises ValueError on failure."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError:
        raise ValueError("Invalid token")

    kid = header.get("kid")
    if not kid:
        raise ValueError("Token missing kid header")

    if _jwks_is_stale():
        await _refresh_jwks_if_needed()

    if kid not in _jwks_cache:
        await _refresh_jwks_if_needed(force=True)
        if kid not in _jwks_cache:
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
