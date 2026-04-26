import logging
import time

import httpx
import jwt
from jwt import PyJWK
from fastapi import HTTPException, Request

from config import settings

logger = logging.getLogger(__name__)

_jwks_cache: dict[str, PyJWK] = {}
_jwks_last_fetch: float = 0
_JWKS_MIN_REFRESH = 10


async def _fetch_jwks() -> None:
    global _jwks_last_fetch
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


async def verify_token(token: str) -> str:
    """Verify a Supabase JWT and return the user_id (sub claim).

    Raises ValueError on any verification failure. Use this for non-HTTP contexts
    (e.g. WebSocket auth) where HTTPException is not appropriate.
    """
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError:
        raise ValueError("Invalid token")

    kid = header.get("kid")
    if not kid:
        raise ValueError("Token missing kid header")

    if kid not in _jwks_cache:
        if time.monotonic() - _jwks_last_fetch >= _JWKS_MIN_REFRESH:
            await _fetch_jwks()
        if kid not in _jwks_cache:
            raise ValueError("Unknown signing key")

    jwk = _jwks_cache[kid]
    try:
        payload = jwt.decode(
            token,
            jwk.key,
            algorithms=["ES256"],
            audience="authenticated",
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
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
