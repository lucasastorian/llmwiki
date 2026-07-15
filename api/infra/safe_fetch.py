"""SSRF-guarded outbound HTTP primitives shared by server-side URL fetchers."""

import asyncio
import ipaddress
import socket
from urllib.parse import ParseResult, urljoin, urlparse

import httpx

DEFAULT_PORTS = {"http": 80, "https": 443}
SAFE_IMAGE_MIME_TYPES = frozenset({
    "image/avif",
    "image/bmp",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
})
BLOCKED_HOSTNAMES = {
    "internal",
    "local",
    "localhost",
    "localdomain",
    "metadata.amazonaws.com",
}
BLOCKED_HOSTNAME_SUFFIXES = (
    ".internal",
    ".local",
    ".localhost",
    ".localdomain",
)


def is_blocked_address(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # IPv6 transition formats can embed an internal IPv4 target inside an
    # otherwise-global outer address (for example, 6to4 under 2002::/16).
    if isinstance(addr, ipaddress.IPv6Address) and (
        addr.ipv4_mapped is not None
        or addr.sixtofour is not None
        or addr.teredo is not None
    ):
        return True

    # not is_global also catches shared address space (100.64.0.0/10, CGNAT) —
    # which is what Railway's internal network uses.
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
        or not addr.is_global
    )


def resolve_public_ip(host: str) -> str | None:
    """Resolve a host, returning its first address only if every resolved address is publicly routable."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return None
    addresses: list[str] = []
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return None
        if is_blocked_address(addr):
            return None
        addresses.append(ip)
    return addresses[0] if addresses else None


def is_blocked_hostname(host: str) -> bool:
    normalized = host.rstrip(".").lower()
    return normalized in BLOCKED_HOSTNAMES or normalized.endswith(BLOCKED_HOSTNAME_SUFFIXES)


def parse_public_fetch_url(url: str) -> ParseResult | None:
    """Parse a URL that server-side fetchers are allowed to request."""
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme not in DEFAULT_PORTS or not parsed.hostname:
        return None
    if is_blocked_hostname(parsed.hostname):
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if port is not None and port != DEFAULT_PORTS[parsed.scheme]:
        return None
    return parsed


def build_pinned_request(
    client: httpx.AsyncClient,
    parsed: ParseResult,
    ip: str,
    headers: dict[str, str],
) -> httpx.Request:
    """Build a request whose connection targets the validated IP while keeping the original Host and SNI."""
    display_host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    host_header = display_host if parsed.port is None else f"{display_host}:{parsed.port}"
    literal = f"[{ip}]" if ":" in ip else ip
    netloc = literal if parsed.port is None else f"{literal}:{parsed.port}"
    pinned_url = parsed._replace(netloc=netloc).geturl()
    request_headers = {**headers, "Host": host_header}
    extensions = {"sni_hostname": parsed.hostname} if parsed.scheme == "https" else {}
    return client.build_request("GET", pinned_url, headers=request_headers, extensions=extensions)


def redirect_location(resp: httpx.Response, base_url: str) -> str | None:
    if not resp.is_redirect:
        return None
    location = resp.headers.get("location")
    return urljoin(base_url, location) if location else None


def sniff_image_mime(data: bytes) -> str | None:
    """Return the MIME type identified by a safe raster image signature."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in {b"avif", b"avis"}:
        return "image/avif"
    if data.startswith(b"BM"):
        return "image/bmp"
    return None


async def _read_image_response(resp: httpx.Response, max_bytes: int) -> tuple[bytes, str] | None:
    if resp.status_code != 200:
        return None

    content_encoding = resp.headers.get("content-encoding", "").strip().lower()
    if content_encoding not in {"", "identity"}:
        return None

    content_length = resp.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > max_bytes:
        return None

    chunks = bytearray()
    async for chunk in resp.aiter_bytes(chunk_size=65536):
        if len(chunks) + len(chunk) > max_bytes:
            return None
        chunks.extend(chunk)

    data = bytes(chunks)
    declared_mime = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if declared_mime not in SAFE_IMAGE_MIME_TYPES:
        return None
    if sniff_image_mime(data) != declared_mime:
        return None
    return data, declared_mime


async def fetch_public_image(
    url: str,
    *,
    max_bytes: int,
    timeout: float,
    max_redirects: int = 3,
    headers: dict[str, str] | None = None,
) -> tuple[bytes, str] | None:
    """Fetch a public raster image without exposing internal network targets.

    DNS is resolved and validated before every hop, then the request is pinned
    to that address while retaining the original Host header and TLS SNI. The
    response is streamed under ``max_bytes`` and its declared MIME type must
    match a safe raster image signature.
    """
    if max_bytes <= 0 or timeout <= 0 or max_redirects < 0:
        return None

    request_headers = {
        **(headers or {}),
        "Accept": "image/*",
        "Accept-Encoding": "identity",
    }
    current = url
    try:
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
                verify=True,
            ) as client:
                for _ in range(max_redirects + 1):
                    parsed = parse_public_fetch_url(current)
                    if not parsed:
                        return None
                    ip = await asyncio.to_thread(resolve_public_ip, parsed.hostname)
                    if not ip:
                        return None

                    request = build_pinned_request(client, parsed, ip, request_headers)
                    try:
                        resp = await client.send(request, stream=True)
                    except (httpx.HTTPError, ValueError):
                        return None
                    try:
                        redirect = redirect_location(resp, current)
                        if redirect:
                            current = redirect
                            continue
                        return await _read_image_response(resp, max_bytes)
                    finally:
                        await resp.aclose()
    except (TimeoutError, httpx.HTTPError, OSError, ValueError):
        return None
    return None
