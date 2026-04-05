import hashlib
import logging
import time

import asyncpg
import httpx
import jwt
from jwt import PyJWK
from fastapi import HTTPException, Request

from config import settings

logger = logging.getLogger(__name__)

_jwks_cache: dict[str, PyJWK] = {}
_jwks_last_fetch: float = 0
_JWKS_REFRESH_INTERVAL = 300
_JWKS_MIN_REFRESH = 10


async def _fetch_jwks() -> None:
    """Fetch JWKS from Supabase and cache the signing keys."""
    global _jwks_last_fetch
    if not settings.SUPABASE_URL:
        return
    url = f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=10)
        resp.raise_for_status()
    data = resp.json()
    _jwks_cache.clear()
    for key_data in data.get("keys", []):
        kid = key_data.get("kid")
        if kid:
            _jwks_cache[kid] = PyJWK(key_data)
    _jwks_last_fetch = time.monotonic()
    logger.info("Fetched %d JWKS keys from Supabase", len(_jwks_cache))


async def get_current_user(request: Request, pool: asyncpg.Pool) -> str:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")

    token = auth_header.removeprefix("Bearer ").strip()

    user_id = await _try_jwt(token)
    if user_id:
        return user_id

    user_id = await _try_api_key(token, pool)
    if user_id:
        return user_id

    raise HTTPException(status_code=401, detail="Invalid credentials")


async def _try_jwt(token: str) -> str | None:
    # Try ES256 via JWKS (new Supabase projects)
    if settings.SUPABASE_URL:
        user_id = await _try_jwt_jwks(token)
        if user_id:
            return user_id

    # Fallback to HS256 with shared secret (legacy Supabase projects)
    if settings.SUPABASE_JWT_SECRET:
        try:
            payload = jwt.decode(
                token,
                settings.SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
            )
            return payload.get("sub")
        except jwt.InvalidTokenError:
            pass

    return None


async def _try_jwt_jwks(token: str) -> str | None:
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not kid:
            return None

        if kid not in _jwks_cache:
            if time.monotonic() - _jwks_last_fetch >= _JWKS_MIN_REFRESH:
                await _fetch_jwks()
            if kid not in _jwks_cache:
                return None

        jwk = _jwks_cache.get(kid)
        if not jwk:
            return None

        payload = jwt.decode(
            token,
            jwk.key,
            algorithms=["ES256"],
            audience="authenticated",
        )
        return payload.get("sub")
    except (jwt.InvalidTokenError, Exception) as e:
        logger.debug("JWKS JWT verification failed: %s", e)
        return None


async def _try_api_key(token: str, pool: asyncpg.Pool) -> str | None:
    key_hash = hashlib.sha256(token.encode()).hexdigest()
    row = await pool.fetchrow(
        "UPDATE api_keys SET last_used_at = now() "
        "WHERE key_hash = $1 AND revoked_at IS NULL "
        "RETURNING user_id",
        key_hash,
    )
    if row:
        return str(row["user_id"])
    return None
