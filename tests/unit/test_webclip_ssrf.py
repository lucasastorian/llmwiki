"""SSRF guard tests for the web-clip image fetcher.

Server-side fetchers hit user-controlled URLs, so these guards (now shared via
infra.safe_fetch) are the highest-stakes code in the API. These tests pin the
invariants that matter: the address blocklist, the
all-resolved-addresses-must-be-public rule (which defeats DNS rebinding),
connection pinning to the validated IP, redirect re-validation, and data-URI
content validation. No live network — getaddrinfo and the httpx transport are
mocked.
"""

import base64
import ipaddress
import socket

import httpx
import pytest

import infra.safe_fetch as sf
import services.webclip_assets as w

_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _gai_return(*ips: str) -> list:
    """Shape a socket.getaddrinfo return for the given addresses."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]


def _fake_getaddrinfo(mapping: dict[str, list[str]]):
    def _gai(host, *args, **kwargs):
        if host in mapping:
            return _gai_return(*mapping[host])
        raise socket.gaierror(f"unknown host {host}")
    return _gai


def _client_with_transport(handler):
    """Replacement for httpx.AsyncClient that routes through a MockTransport."""
    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)
    return factory


class TestBlockedAddresses:

    @pytest.mark.parametrize("ip", [
        "127.0.0.1",           # loopback
        "10.0.0.1",            # private (RFC 1918)
        "172.16.0.1",          # private
        "192.168.1.1",         # private
        "169.254.169.254",     # link-local — cloud metadata endpoint
        "0.0.0.0",             # unspecified
        "224.0.0.1",           # multicast
        "240.0.0.1",           # reserved
        "100.64.0.1",          # shared/CGNAT — Railway's internal network
        "100.127.255.254",     # shared/CGNAT upper bound
        "::1",                 # IPv6 loopback
        "fc00::1",             # IPv6 unique-local
        "fe80::1",             # IPv6 link-local
    ])
    def test_blocks_non_public(self, ip):
        assert sf.is_blocked_address(ipaddress.ip_address(ip)) is True

    @pytest.mark.parametrize("ip", [
        "8.8.8.8",
        "1.1.1.1",
        "93.184.216.34",
        "2606:2800:220:1:248:1893:25c8:1946",
    ])
    def test_allows_public(self, ip):
        assert sf.is_blocked_address(ipaddress.ip_address(ip)) is False


class TestResolvePublicIP:

    def test_public_host_resolves(self, monkeypatch):
        monkeypatch.setattr(sf.socket, "getaddrinfo", _fake_getaddrinfo({"example.com": ["93.184.216.34"]}))
        assert sf.resolve_public_ip("example.com") == "93.184.216.34"

    def test_private_host_blocked(self, monkeypatch):
        monkeypatch.setattr(sf.socket, "getaddrinfo", _fake_getaddrinfo({"internal.test": ["10.0.0.5"]}))
        assert sf.resolve_public_ip("internal.test") is None

    def test_mixed_public_and_private_blocked(self, monkeypatch):
        """A host with one public and one private A record must be rejected
        entirely — this is the DNS-rebinding shape."""
        monkeypatch.setattr(
            sf.socket, "getaddrinfo",
            _fake_getaddrinfo({"rebind.test": ["93.184.216.34", "10.0.0.5"]}),
        )
        assert sf.resolve_public_ip("rebind.test") is None

    def test_unresolvable_host_returns_none(self, monkeypatch):
        def boom(*args, **kwargs):
            raise socket.gaierror("name resolution failed")
        monkeypatch.setattr(sf.socket, "getaddrinfo", boom)
        assert sf.resolve_public_ip("nx.test") is None


class TestParsePublicFetchURL:

    @pytest.mark.parametrize("url", [
        "http://example.com/a.png",
        "https://example.com/a.png",
        "http://example.com:80/a.png",
        "https://example.com:443/a.png",
    ])
    def test_accepts_http_https_default_ports(self, url):
        assert sf.parse_public_fetch_url(url) is not None

    @pytest.mark.parametrize("url", [
        "file:///etc/passwd",
        "ftp://example.com/a.png",
        "http://user@example.com/a.png",
        "https://user:pass@example.com/a.png",
        "http://example.com:81/a.png",
        "https://example.com:444/a.png",
        "http://example.com:bad/a.png",
        "https://api.railway.internal/a.png",
        "https://metadata.amazonaws.com/latest/meta-data",
        "http://localhost/a.png",
    ])
    def test_rejects_unsafe_fetch_urls(self, url):
        assert sf.parse_public_fetch_url(url) is None


class TestFetchRemoteImage:

    async def test_success_pins_ip_and_preserves_host(self, monkeypatch):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url_host"] = request.url.host
            captured["host_header"] = request.headers.get("host")
            return httpx.Response(200, headers={"content-type": "image/png"}, content=png)

        monkeypatch.setattr(sf.socket, "getaddrinfo", _fake_getaddrinfo({"cdn.test": ["93.184.216.34"]}))
        monkeypatch.setattr(w.httpx, "AsyncClient", _client_with_transport(handler))

        result = await w._fetch_remote_image("http://cdn.test/a.png")

        assert result == (png, "image/png")
        # Connection targets the validated IP; original Host is preserved.
        assert captured["url_host"] == "93.184.216.34"
        assert captured["host_header"] == "cdn.test"

    async def test_initial_private_host_never_sends(self, monkeypatch):
        sent = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            sent["count"] += 1
            return httpx.Response(200, content=b"x")

        monkeypatch.setattr(sf.socket, "getaddrinfo", _fake_getaddrinfo({"evil.test": ["169.254.169.254"]}))
        monkeypatch.setattr(w.httpx, "AsyncClient", _client_with_transport(handler))

        result = await w._fetch_remote_image("http://evil.test/latest/meta-data")

        assert result is None
        assert sent["count"] == 0

    @pytest.mark.parametrize("url", [
        "http://cdn.test:8080/a.png",
        "http://user:pass@cdn.test/a.png",
        "http://api.railway.internal/a.png",
    ])
    async def test_rejects_unsafe_url_shape_without_sending(self, monkeypatch, url):
        sent = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            sent["count"] += 1
            return httpx.Response(200, content=b"x")

        monkeypatch.setattr(sf.socket, "getaddrinfo", _fake_getaddrinfo({"cdn.test": ["93.184.216.34"]}))
        monkeypatch.setattr(w.httpx, "AsyncClient", _client_with_transport(handler))

        result = await w._fetch_remote_image(url)

        assert result is None
        assert sent["count"] == 0

    async def test_redirect_to_private_host_blocked(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "http://meta.test/latest"})

        monkeypatch.setattr(
            sf.socket, "getaddrinfo",
            _fake_getaddrinfo({
                "cdn.test": ["93.184.216.34"],
                "meta.test": ["169.254.169.254"],
            }),
        )
        monkeypatch.setattr(w.httpx, "AsyncClient", _client_with_transport(handler))

        result = await w._fetch_remote_image("http://cdn.test/a.png")

        assert result is None

    async def test_redirect_to_unsafe_port_blocked(self, monkeypatch):
        sent_urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent_urls.append(str(request.url))
            return httpx.Response(302, headers={"location": "http://cdn.test:8080/private"})

        monkeypatch.setattr(sf.socket, "getaddrinfo", _fake_getaddrinfo({"cdn.test": ["93.184.216.34"]}))
        monkeypatch.setattr(w.httpx, "AsyncClient", _client_with_transport(handler))

        result = await w._fetch_remote_image("http://cdn.test/a.png")

        assert result is None
        assert len(sent_urls) == 1

    async def test_redirect_to_internal_hostname_blocked(self, monkeypatch):
        sent_urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent_urls.append(str(request.url))
            return httpx.Response(302, headers={"location": "http://api.railway.internal/private"})

        monkeypatch.setattr(sf.socket, "getaddrinfo", _fake_getaddrinfo({"cdn.test": ["93.184.216.34"]}))
        monkeypatch.setattr(w.httpx, "AsyncClient", _client_with_transport(handler))

        result = await w._fetch_remote_image("http://cdn.test/a.png")

        assert result is None
        assert len(sent_urls) == 1

    async def test_content_type_must_match_sniffed_bytes(self, monkeypatch):
        """A response claiming image/png but carrying non-image bytes is dropped."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "image/png"}, content=b"not really a png")

        monkeypatch.setattr(sf.socket, "getaddrinfo", _fake_getaddrinfo({"cdn.test": ["93.184.216.34"]}))
        monkeypatch.setattr(w.httpx, "AsyncClient", _client_with_transport(handler))

        assert await w._fetch_remote_image("http://cdn.test/a.png") is None

    async def test_oversized_response_dropped_by_streaming(self, monkeypatch):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 256

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "image/png"}, content=png)

        monkeypatch.setattr(w, "MAX_IMAGE_BYTES", 16)
        monkeypatch.setattr(sf.socket, "getaddrinfo", _fake_getaddrinfo({"cdn.test": ["93.184.216.34"]}))
        monkeypatch.setattr(w.httpx, "AsyncClient", _client_with_transport(handler))

        assert await w._fetch_remote_image("http://cdn.test/a.png") is None


class TestDataURIImages:

    def test_valid_png_decoded(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        uri = "data:image/png;base64," + base64.b64encode(png).decode()
        assert w._decode_data_image(uri) == (png, "image/png")

    def test_mime_payload_mismatch_rejected(self):
        uri = "data:image/png;base64," + base64.b64encode(b"not an image").decode()
        assert w._decode_data_image(uri) is None

    def test_non_image_mime_rejected(self):
        assert w._decode_data_image("data:text/html,<b>hi</b>") is None

    def test_oversized_rejected(self, monkeypatch):
        monkeypatch.setattr(w, "MAX_IMAGE_BYTES", 4)
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        uri = "data:image/png;base64," + base64.b64encode(png).decode()
        assert w._decode_data_image(uri) is None


class TestSniffImageType:

    @pytest.mark.parametrize("data,expected", [
        (b"\x89PNG\r\n\x1a\n\x00\x00", "image/png"),
        (b"\xff\xd8\xff\xe0\x00\x10", "image/jpeg"),
        (b"GIF89a\x01\x00", "image/gif"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"\x00\x00\x00\x20ftypavif\x00\x00", "image/avif"),
        (b"<svg xmlns=", None),
        (b"", None),
    ])
    def test_magic_bytes(self, data, expected):
        assert w._sniff_image_type(data) == expected
