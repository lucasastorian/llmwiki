"""Guards for the unauthenticated local API: loopback Host only; browser writes only from trusted origins."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
EXTENSION_ORIGIN_PATTERN = r"(?:chrome-extension|moz-extension)://[A-Za-z0-9._-]+"
_EXTENSION_ORIGIN_RE = re.compile(EXTENSION_ORIGIN_PATTERN)
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _host_name(value: str) -> str | None:
    """Return a normalized Host hostname, rejecting malformed authorities."""
    authority = value.strip()
    if not authority or any(char.isspace() for char in authority):
        return None

    if authority.startswith("["):
        closing = authority.find("]")
        if closing < 0:
            return None
        hostname = authority[1:closing].lower()
        suffix = authority[closing + 1 :]
        if suffix and (not suffix.startswith(":") or not suffix[1:].isdigit()):
            return None
        port = suffix[1:] if suffix else None
    else:
        if authority.count(":") > 1:
            return None
        hostname, separator, port = authority.partition(":")
        hostname = hostname.lower()
        if separator and not port.isdigit():
            return None
        port = port if separator else None

    if port is not None and (len(port) > 5 or not (0 < int(port) <= 65535)):
        return None
    return hostname or None


def _http_origin_key(value: str) -> tuple[str, str, int] | None:
    """Normalize a serialized HTTP(S) origin for exact comparison."""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None

    scheme = parsed.scheme.lower()
    if (
        scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return None
    return scheme, parsed.hostname.lower(), port or (443 if scheme == "https" else 80)


def normalize_extension_origins(origins: tuple[str, ...]) -> frozenset[str]:
    """Keep only well-formed, serialized extension origins."""
    return frozenset(
        origin
        for origin in origins
        if _EXTENSION_ORIGIN_RE.fullmatch(origin) is not None
    )


def extension_origin_regex(origins: tuple[str, ...]) -> str:
    """Build an exact CORS regex for the configured extension IDs."""
    normalized = normalize_extension_origins(origins)
    if not normalized:
        # A never-matching expression is safer than reverting to all IDs.
        return r"(?!)"
    return "(?:" + "|".join(re.escape(origin) for origin in sorted(normalized)) + ")"


def is_allowed_local_origin(
    origin: str,
    app_origin: str,
    extension_origins: tuple[str, ...] = (),
) -> bool:
    """Allow the configured web UI and explicitly trusted extension IDs."""
    origin_key = _http_origin_key(origin)
    app_origin_key = _http_origin_key(app_origin)
    if (
        origin_key is not None
        and origin_key == app_origin_key
        and app_origin_key[1] in LOOPBACK_HOSTS
    ):
        return True
    return origin in normalize_extension_origins(extension_origins)


class LocalHTTPBoundaryMiddleware:
    """Protect local mode from DNS rebinding and cross-site browser writes."""

    def __init__(
        self,
        app: ASGIApp,
        app_origin: str,
        extension_origins: tuple[str, ...] = (),
    ) -> None:
        self.app = app
        self.app_origin = app_origin
        self.extension_origins = extension_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        host_values = [
            value.decode("latin-1")
            for name, value in scope.get("headers", [])
            if name.lower() == b"host"
        ]
        if len(host_values) != 1 or _host_name(host_values[0]) not in LOOPBACK_HOSTS:
            response = PlainTextResponse("Invalid Host header", status_code=400)
            await response(scope, receive, send)
            return

        if scope.get("method", "GET").upper() not in _SAFE_METHODS:
            origin_values = [
                value.decode("latin-1")
                for name, value in scope.get("headers", [])
                if name.lower() == b"origin"
            ]
            if len(origin_values) > 1 or (
                origin_values
                and not is_allowed_local_origin(
                    origin_values[0],
                    self.app_origin,
                    self.extension_origins,
                )
            ):
                response = PlainTextResponse("Origin not allowed", status_code=403)
                await response(scope, receive, send)
                return

            # If an intermediary strips Origin, Sec-Fetch-Site still tells browsers from CLI/MCP clients.
            if not origin_values:
                fetch_site = next(
                    (
                        value.decode("latin-1").lower()
                        for name, value in scope.get("headers", [])
                        if name.lower() == b"sec-fetch-site"
                    ),
                    None,
                )
                if fetch_site == "cross-site":
                    response = PlainTextResponse("Origin not allowed", status_code=403)
                    await response(scope, receive, send)
                    return

        await self.app(scope, receive, send)
