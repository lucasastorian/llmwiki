"""Supavault MCP Server — knowledge vault tools for Claude."""

import os

import logfire
import sentry_sdk
import uvicorn
from urllib.parse import urlparse

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from auth import SupabaseTokenVerifier
from config import settings
from tools import register
from vaultfs import PostgresVaultFS

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        send_default_pii=True,
        traces_sample_rate=0.1,
        environment=settings.STAGE,
    )

if settings.LOGFIRE_TOKEN:
    logfire.configure(token=settings.LOGFIRE_TOKEN, service_name="supavault-mcp")
    logfire.instrument_asyncpg()

_mcp_host = urlparse(settings.MCP_URL).hostname or "localhost"

mcp = FastMCP(
    "LLM Wiki",
    instructions=(
        "You are connected to an LLM Wiki workspace. The user has uploaded files, notes, "
        "and documents that you can read, search, edit, and organize. Your job is to work "
        "with these materials — answer questions, take notes, and compile structured wiki "
        "pages from the raw sources. Call the `guide` tool first to see available knowledge "
        "bases and learn the full workflow."
    ),
    token_verifier=SupabaseTokenVerifier(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(f"{settings.SUPABASE_URL}/auth/v1"),
        resource_server_url=AnyHttpUrl(settings.MCP_URL),
    ),
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[_mcp_host],
    ),
)

def _get_user_id(ctx):
    from mcp.server.auth.middleware.auth_context import get_access_token
    access_token = get_access_token()
    if not access_token:
        raise RuntimeError("Not authenticated")
    if access_token.client_id:
        return access_token.client_id
    raise RuntimeError("No user identifier in token")


register(mcp, _get_user_id, lambda user_id: PostgresVaultFS(user_id))


async def health(request):
    return PlainTextResponse("OK")


app = mcp.streamable_http_app()
app.router.routes.insert(0, Route("/health", health))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
