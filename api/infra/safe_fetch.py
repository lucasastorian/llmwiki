"""SSRF-guarded outbound HTTP primitives shared by server-side URL fetchers."""

import ipaddress
import socket
from urllib.parse import ParseResult, urljoin, urlparse

import httpx

DEFAULT_PORTS = {"http": 80, "https": 443}
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
    host_header = parsed.hostname if parsed.port is None else f"{parsed.hostname}:{parsed.port}"
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
