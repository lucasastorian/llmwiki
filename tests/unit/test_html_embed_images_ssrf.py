"""Security regressions for HTML image embedding.

No live network is used: DNS and the httpx transport are replaced so these
tests exercise URL validation, address pinning, redirect handling, and body
validation deterministically.
"""

import asyncio
import socket

import httpx
import pytest
from html_parser import Parser
from infra import safe_fetch

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _getaddrinfo(mapping: dict[str, list[str]]):
    def fake(host, *args, **kwargs):
        if host not in mapping:
            raise socket.gaierror(f"unknown host {host}")
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 0))
            for ip in mapping[host]
        ]

    return fake


def _mock_client(handler, constructor_args: dict | None = None):
    def factory(*args, **kwargs):
        if constructor_args is not None:
            constructor_args.update(kwargs)
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)

    return factory


async def _fetch(url: str, *, max_bytes: int = 1024):
    return await safe_fetch.fetch_public_image(
        url,
        max_bytes=max_bytes,
        timeout=1,
    )


@pytest.mark.parametrize(
    ("url", "addresses"),
    [
        ("http://cdn.test/image.png", ["100.64.0.1"]),
        ("http://cdn.test/image.png", ["93.184.216.34", "10.0.0.5"]),
        ("http://cdn.test/image.png", ["2002:a9fe:a9fe::"]),
        ("http://cdn.test:8080/image.png", ["93.184.216.34"]),
    ],
)
async def test_html_image_fetch_rejects_cgnat_mixed_dns_and_arbitrary_ports(
    monkeypatch,
    url,
    addresses,
):
    sent = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent += 1
        return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)

    monkeypatch.setattr(safe_fetch.socket, "getaddrinfo", _getaddrinfo({"cdn.test": addresses}))
    monkeypatch.setattr(safe_fetch.httpx, "AsyncClient", _mock_client(handler))

    assert await _fetch(url) is None
    assert sent == 0


async def test_html_image_redirect_is_revalidated_before_second_request(monkeypatch):
    sent_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_hosts.append(request.headers["host"])
        return httpx.Response(302, headers={"location": "http://internal.test/secret.png"})

    monkeypatch.setattr(
        safe_fetch.socket,
        "getaddrinfo",
        _getaddrinfo({
            "cdn.test": ["93.184.216.34"],
            "internal.test": ["169.254.169.254"],
        }),
    )
    monkeypatch.setattr(safe_fetch.httpx, "AsyncClient", _mock_client(handler))

    assert await _fetch("http://cdn.test/image.png") is None
    assert sent_hosts == ["cdn.test"]


async def test_html_image_https_pins_ip_and_preserves_tls_sni(monkeypatch):
    captured: dict = {}
    constructor_args: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url_host"] = request.url.host
        captured["host_header"] = request.headers["host"]
        captured["sni_hostname"] = request.extensions.get("sni_hostname")
        captured["accept_encoding"] = request.headers["accept-encoding"]
        return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)

    monkeypatch.setattr(
        safe_fetch.socket,
        "getaddrinfo",
        _getaddrinfo({"cdn.test": ["93.184.216.34"]}),
    )
    monkeypatch.setattr(
        safe_fetch.httpx,
        "AsyncClient",
        _mock_client(handler, constructor_args),
    )

    assert await _fetch("https://cdn.test/image.png") == (PNG, "image/png")
    assert captured == {
        "url_host": "93.184.216.34",
        "host_header": "cdn.test",
        "sni_hostname": "cdn.test",
        "accept_encoding": "identity",
    }
    assert constructor_args["verify"] is True
    assert constructor_args["trust_env"] is False
    assert constructor_args["follow_redirects"] is False


@pytest.mark.parametrize(
    ("content_type", "body"),
    [
        ("image/png", b"<html>not an image</html>"),
        ("text/html", PNG),
        ("image/svg+xml", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"),
    ],
)
async def test_html_image_fetch_rejects_spoofed_or_unsafe_mime(
    monkeypatch,
    content_type,
    body,
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": content_type}, content=body)

    monkeypatch.setattr(
        safe_fetch.socket,
        "getaddrinfo",
        _getaddrinfo({"cdn.test": ["93.184.216.34"]}),
    )
    monkeypatch.setattr(safe_fetch.httpx, "AsyncClient", _mock_client(handler))

    assert await _fetch("http://cdn.test/image") is None


async def test_html_image_fetch_stops_streaming_over_size_limit(monkeypatch):
    class ChunkedBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield PNG[:10]
            yield PNG[10:]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "image/png"},
            stream=ChunkedBody(),
        )

    monkeypatch.setattr(
        safe_fetch.socket,
        "getaddrinfo",
        _getaddrinfo({"cdn.test": ["93.184.216.34"]}),
    )
    monkeypatch.setattr(safe_fetch.httpx, "AsyncClient", _mock_client(handler))

    assert await _fetch("http://cdn.test/image.png", max_bytes=16) is None


async def test_embed_images_enforces_aggregate_budget_and_concurrency(monkeypatch):
    active = 0
    max_active = 0
    fetch_count = 0

    async def fake_fetch(url: str, **kwargs):
        nonlocal active, max_active, fetch_count
        fetch_count += 1
        active += 1
        max_active = max(max_active, active)
        try:
            await asyncio.sleep(0.01)
            return PNG, "image/png"
        finally:
            active -= 1

    monkeypatch.setattr(safe_fetch, "fetch_public_image", fake_fetch)
    monkeypatch.setattr(Parser, "_EMBED_CONCURRENCY", 2)
    monkeypatch.setattr(Parser, "_MAX_TOTAL_BYTES", len(PNG))

    parser = Parser("".join(f'<img src="https://cdn.test/{i}.png">' for i in range(8)))
    await parser.embed_images()

    embedded = [
        img["src"]
        for img in parser.soup.find_all("img")
        if img["src"].startswith("data:image/png;base64,")
    ]
    assert len(embedded) == 1
    assert max_active == 2
    # Once the aggregate budget is full, queued downloads are skipped.
    assert fetch_count == 2


async def test_embed_images_caps_failed_remote_fetch_fanout(monkeypatch):
    calls = 0

    async def failed_fetch(url: str, **kwargs):
        nonlocal calls
        calls += 1
        return None

    monkeypatch.setattr(safe_fetch, "fetch_public_image", failed_fetch)
    monkeypatch.setattr(Parser, "_MAX_EMBED_IMAGES", 3)

    parser = Parser(
        "".join(f'<img src="https://cdn.test/{i}.png">' for i in range(20))
    )
    await parser.embed_images()

    assert calls == 3
