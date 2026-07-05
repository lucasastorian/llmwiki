"""Supavault MCP Server — knowledge vault tools for Claude."""

import importlib.util
import os
from pathlib import Path

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
from tools import register
from tools.ingest import register as register_ingest
from vaultfs import PostgresVaultFS


def _load_local_settings():
    """Load mcp/config.py even when another top-level `config` is cached."""
    spec = importlib.util.spec_from_file_location(
        "llmwiki_mcp_config",
        Path(__file__).with_name("config.py"),
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load MCP config")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.settings


settings = _load_local_settings()

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

def _build_allowed_hosts(mcp_url: str) -> list[str]:
    """Build the allowed_hosts list for TransportSecuritySettings.

    Returns both the bare hostname and the ``host:*`` port-wildcard form so
    that requests reaching the MCP server inside a container network — where
    the Host header includes the internal port (e.g. ``llmwiki-mcp:8080``) —
    are not rejected as 421 Misdirected Request. External requests routed
    through a reverse proxy on ports 80/443 present a port-less Host header
    and are matched by the bare entry, so this is backwards compatible.
    """
    host = urlparse(mcp_url).hostname or "localhost"
    return [host, f"{host}:*"]


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
        allowed_hosts=_build_allowed_hosts(settings.MCP_URL),
    ),
    # Stateless: in-memory sessions die on every Railway restart/redeploy, and the
    # idle SSE stream has no keepalive so the edge proxy cuts it — both drop clients.
    stateless_http=True,
)

def _get_user_id(ctx):
    from mcp.server.auth.middleware.auth_context import get_access_token
    access_token = get_access_token()
    if not access_token:
        raise RuntimeError("Not authenticated")
    if access_token.client_id:
        return access_token.client_id
    raise RuntimeError("No user identifier in token")


def _fs_factory(user_id: str) -> PostgresVaultFS:
    return PostgresVaultFS(user_id)


register(mcp, _get_user_id, _fs_factory)
# URL ingestion calls the hosted API; the local stdio server never registers it.
register_ingest(mcp, _get_user_id, _fs_factory)


async def health(request):
    return PlainTextResponse("OK")


# RFC 9728 mounts the metadata at /.well-known/oauth-protected-resource/mcp;
# ChatGPT also probes the un-suffixed root and treats the 404 as a dead server.
def _root_protected_resource_route() -> Route:
    from mcp.server.auth.handlers.metadata import ProtectedResourceMetadataHandler
    from mcp.server.auth.routes import cors_middleware
    from mcp.shared.auth import ProtectedResourceMetadata

    metadata = ProtectedResourceMetadata(
        resource=AnyHttpUrl(settings.MCP_URL),
        authorization_servers=[AnyHttpUrl(f"{settings.SUPABASE_URL}/auth/v1")],
    )
    handler = ProtectedResourceMetadataHandler(metadata)
    return Route(
        "/.well-known/oauth-protected-resource",
        endpoint=cors_middleware(handler.handle, ["GET", "OPTIONS"]),
        methods=["GET", "OPTIONS"],
    )


app = mcp.streamable_http_app()
app.router.routes.insert(0, Route("/health", health))
app.router.routes.insert(1, _root_protected_resource_route())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
