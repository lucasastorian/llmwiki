import asyncio
import logging

import jwt as pyjwt
from jwt import PyJWKClient
from mcp.server.auth.provider import AccessToken, TokenVerifier

from config import settings

logger = logging.getLogger(__name__)

_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        jwks_url = f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        _jwks_client = PyJWKClient(jwks_url)
    return _jwks_client


class SupabaseTokenVerifier(TokenVerifier):

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            signing_key = await asyncio.to_thread(
                _get_jwks_client().get_signing_key_from_jwt, token
            )
            payload = pyjwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "ES256"],
                audience="authenticated",
            )
        except Exception as e:
            logger.debug("JWT verification failed: %s", e)
            return None

        sub = payload.get("sub", "")
        if not sub:
            logger.warning("JWT has no sub claim")
            return None

        scopes = []
        scope_str = payload.get("scope", "")
        if isinstance(scope_str, str) and scope_str:
            scopes = scope_str.split()

        logger.info("MCP auth: %s", sub)
        return AccessToken(
            token=token,
            client_id=sub,
            scopes=scopes,
            extra={"claims": payload},
        )
