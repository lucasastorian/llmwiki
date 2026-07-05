"""Unit tests for html_parser plaintext extraction + highlight locator (V2A).

The plaintext output has to match what TipTap's `doc.textBetween` would
produce on the parsed markdown — markdown punctuation removed, block
separation preserved, inline spans flattened.
"""

import socket

import pytest
from html_parser import Parser

# ── Plaintext extraction ──────────────────────────────────


def _plain(html: str) -> str:
    return Parser(html)._to_plaintext()


def test_plain_paragraph():
    assert _plain("<p>Hello world</p>") == "Hello world"


def test_plain_heading_and_paragraph_separated_by_blank_line():
    out = _plain("<h1>Title</h1><p>Body.</p>")
    assert out == "Title\n\nBody."


def test_plain_strips_inline_formatting():
    out = _plain('<p>The <strong>key</strong> insight is <em>that</em>.</p>')
    assert out == "The key insight is that."


def test_plain_keeps_link_text_drops_href():
    out = _plain('<p>Read <a href="https://x.com">the paper</a>.</p>')
    assert out == "Read the paper."


def test_plain_list_one_item_per_line():
    out = _plain("<ul><li>First</li><li>Second</li></ul>")
    assert out == "First\nSecond"


def test_plain_ordered_list_no_numbers():
    out = _plain("<ol><li>One</li><li>Two</li></ol>")
    assert out == "One\nTwo"


def test_plain_table_cells_space_separated():
    html = "<table><tr><th>A</th><th>B</th></tr><tr><td>x</td><td>y</td></tr></table>"
    assert _plain(html) == "A B\nx y"


def test_plain_blockquote():
    out = _plain("<blockquote><p>Quoted.</p></blockquote>")
    assert out == "Quoted."


def test_plain_image_emits_empty():
    """Images are leaf nodes in ProseMirror with no rendered text content.
    Plaintext drops them entirely so the client walker matches."""
    out = _plain('<p>See <img src="x.png" alt="diagram"/> for details.</p>')
    assert out == "See for details."


def test_plain_image_no_alt_also_empty():
    out = _plain('<p>Before <img src="x.png"/> after.</p>')
    assert out == "Before after."


def test_plain_br_is_newline():
    out = _plain("<p>line one<br/>line two</p>")
    assert out == "line one\nline two"


def test_plain_collapses_multiple_blank_lines():
    out = _plain("<div></div><p>One</p><div></div><p>Two</p>")
    assert out == "One\n\nTwo"


def test_plain_drops_script_and_style():
    html = "<p>Visible</p><script>alert(1)</script><style>p{color:red}</style>"
    assert _plain(html) == "Visible"


# ── Tagged HTML sanitization ──────────────────────────────


def test_sanitized_html_strips_executable_attributes_and_urls():
    html = """
    <html><head><base href="https://evil.example/"><meta http-equiv="refresh" content="0"></head>
    <body>
      <p onclick="alert(1)" style="background:url(javascript:alert(2))">
        <a href="javascript:alert(3)" target="_blank">bad link</a>
        <a href="https://example.com/safe" target="_blank">safe link</a>
        <img src="x.png" onerror="alert(4)" srcdoc="<script>alert(5)</script>" />
      </p>
      <iframe srcdoc="<script>alert(6)</script>"></iframe>
    </body></html>
    """
    parser = Parser(html, url="https://source.example/article", content_only=True)
    parser.parse()

    out = parser.html(sanitize=True)

    assert "onclick" not in out
    assert "onerror" not in out
    assert "style=" not in out
    assert "srcdoc" not in out
    assert "javascript:" not in out
    assert "<iframe" not in out
    assert "<base" not in out
    assert "<meta" not in out
    assert 'href="https://example.com/safe"' in out
    assert 'rel="noopener noreferrer"' in out
    assert 'src="https://source.example/x.png"' in out


def test_sanitized_html_allows_only_safe_image_data_urls():
    html = """
    <p>
      <img src="data:image/png;base64,AAAA" />
      <img src="data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9YWxlcnQoMSk+" />
      <img src="data:text/html,<script>alert(1)</script>" />
    </p>
    """
    parser = Parser(html)
    parser.parse()

    out = parser.html(sanitize=True)

    assert "data:image/png;base64,AAAA" in out
    assert "data:image/svg+xml" not in out
    assert "data:text/html" not in out


def test_sanitized_html_filters_srcset_entries():
    html = """
    <p>
      <img
        src="safe.png"
        srcset="safe-1.png 1x, javascript:alert(1) 2x, data:image/webp;base64,AAAA 3x, data:text/html,evil 4x"
      />
    </p>
    """
    parser = Parser(html, url="https://source.example/post")
    parser.parse()

    out = parser.html(sanitize=True)

    assert "srcset=" not in out
    assert "javascript:" not in out
    assert "AAAA 3x" not in out
    assert "data:text/html" not in out


def test_sanitized_html_keeps_safe_srcset_without_data_urls():
    html = '<p><img src="safe.png" srcset="safe-1.png 1x, https://cdn.example/safe-2.png 2x" /></p>'
    parser = Parser(html, url="https://source.example/post")
    parser.parse()

    out = parser.html(sanitize=True)

    assert 'srcset="https://source.example/safe-1.png 1x, https://cdn.example/safe-2.png 2x"' in out


@pytest.mark.asyncio
async def test_webclip_image_materialization_rewrites_markdown_to_relative_asset_path():
    from services.webclip_assets import materialize_webclip_assets

    png_1x1 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )
    html = f'<p>Lead image:</p><img alt="Tiny image" src="data:image/png;base64,{png_1x1}">'
    result = Parser(html, url="https://source.example/post").parse()

    markdown, assets = await materialize_webclip_assets(
        result.content,
        result.images,
        "article.assets",
    )

    assert "llmwiki-image://" not in markdown
    assert "![Tiny image](./article.assets/image-01.png)" in markdown
    assert len(assets) == 1
    assert assets[0].filename == "image-01.png"
    assert assets[0].content_type == "image/png"


@pytest.mark.asyncio
async def test_webclip_image_materialization_preserves_source_dimensions():
    from services.webclip_assets import materialize_webclip_assets

    png_1x1 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )
    html = (
        f'<img alt="Inline logo" width="42" height="24" '
        f'src="data:image/png;base64,{png_1x1}">'
    )
    result = Parser(html, url="https://source.example/post").parse()

    _, assets = await materialize_webclip_assets(
        result.content,
        result.images,
        "article.assets",
    )

    assert assets[0].metadata()["width"] == 42
    assert assets[0].metadata()["height"] == 24


def test_parser_prefers_srcset_candidates_over_placeholder_src():
    html = """
    <img
      src="https://cdn.example/image/-1x-1.webp"
      srcset="https://cdn.example/image/220x147.webp 220w,
              https://cdn.example/image/1200x801.webp 1200w"
      alt="Hero"
    />
    """

    result = Parser(html, url="https://source.example/post").parse()

    assert result.images[0].candidate_urls[0] == "https://cdn.example/image/1200x801.webp"
    assert result.images[0].candidate_urls[-1] == "https://cdn.example/image/-1x-1.webp"
    assert result.images[0].width == 1200
    assert result.images[0].height == 801


@pytest.mark.asyncio
async def test_webclip_asset_materialization_fetches_remote_images(monkeypatch):
    import base64 as _b64

    from html_parser.models import Image
    from services import webclip_assets
    from services.webclip_assets import materialize_webclip_assets

    png_1x1 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )
    png_bytes = _b64.b64decode(png_1x1)

    async def fake_remote(url: str):
        return png_bytes, "image/png"

    monkeypatch.setattr(webclip_assets, "_fetch_remote_image", fake_remote)

    markdown, assets = await materialize_webclip_assets(
        "![Hero](llmwiki-image://IMG1)",
        [Image(url="https://cdn.example/hero.png", alt="Hero", ref="IMG1")],
        "article.assets",
    )

    assert "llmwiki-image://" not in markdown
    assert "![Hero](./article.assets/image-01.png)" in markdown
    assert len(assets) == 1
    assert assets[0].content_type == "image/png"
    assert assets[0].original_url == "https://cdn.example/hero.png"


@pytest.mark.asyncio
async def test_webclip_asset_materialization_drops_remote_images_when_fetch_fails(monkeypatch):
    from html_parser.models import Image
    from services import webclip_assets
    from services.webclip_assets import materialize_webclip_assets

    async def fake_remote(url: str):
        return None  # paywalled / unreachable / SSRF-blocked

    monkeypatch.setattr(webclip_assets, "_fetch_remote_image", fake_remote)

    markdown, assets = await materialize_webclip_assets(
        "![Hero](llmwiki-image://IMG1)",
        [Image(url="https://cdn.example/hero.png", alt="Hero", ref="IMG1")],
        "article.assets",
    )

    assert markdown == ""
    assert assets == []


@pytest.mark.parametrize("ip", ["127.0.0.1", "169.254.169.254", "10.0.0.5", "192.168.1.1", "::1"])
def test_resolve_public_ip_rejects_internal_addresses(monkeypatch, ip):
    from infra import safe_fetch

    def fake_getaddrinfo(host, *args, **kwargs):
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(safe_fetch.socket, "getaddrinfo", fake_getaddrinfo)
    assert safe_fetch.resolve_public_ip("evil.example") is None


def test_resolve_public_ip_allows_public_address(monkeypatch):
    from infra import safe_fetch

    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(safe_fetch.socket, "getaddrinfo", fake_getaddrinfo)
    assert safe_fetch.resolve_public_ip("example.com") == "93.184.216.34"


def test_resolve_public_ip_rejects_when_any_resolved_address_is_internal(monkeypatch):
    from infra import safe_fetch

    def fake_getaddrinfo(host, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0)),
        ]

    monkeypatch.setattr(safe_fetch.socket, "getaddrinfo", fake_getaddrinfo)
    assert safe_fetch.resolve_public_ip("rebind.example") is None


@pytest.mark.asyncio
async def test_build_pinned_request_targets_ip_but_keeps_host_and_sni():
    from urllib.parse import urlparse

    from infra import safe_fetch

    async with safe_fetch.httpx.AsyncClient() as client:
        parsed = urlparse("https://cdn.example/hero.png")
        request = safe_fetch.build_pinned_request(client, parsed, "93.184.216.34", {"Accept": "image/*"})

    assert request.url.host == "93.184.216.34"
    assert request.headers["host"] == "cdn.example"
    assert request.extensions.get("sni_hostname") == "cdn.example"


@pytest.mark.asyncio
async def test_fetch_remote_image_blocks_metadata_endpoint(monkeypatch):
    from infra import safe_fetch
    from services import webclip_assets

    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))]

    monkeypatch.setattr(safe_fetch.socket, "getaddrinfo", fake_getaddrinfo)

    async def fail_send(*args, **kwargs):
        raise AssertionError("must not issue HTTP to a blocked host")

    monkeypatch.setattr(webclip_assets.httpx.AsyncClient, "send", fail_send)

    result = await webclip_assets._fetch_remote_image("http://169.254.169.254/latest/meta-data/")
    assert result is None


@pytest.mark.asyncio
async def test_webclip_asset_materialization_rejects_mismatched_image_bytes():
    from html_parser.models import Image
    from services.webclip_assets import materialize_webclip_assets

    markdown, assets = await materialize_webclip_assets(
        "![Logo](llmwiki-image://IMG1)",
        [
            Image(
                url="data:image/png;base64,bm90LWFjdHVhbGx5LXBuZw==",
                alt="Logo",
                ref="IMG1",
            )
        ],
        "article.assets",
    )

    assert markdown == ""
    assert assets == []


@pytest.mark.asyncio
async def test_webclip_asset_materialization_has_no_image_count_cap():
    from html_parser.models import Image
    from services.webclip_assets import materialize_webclip_assets

    png_1x1 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )
    images = [
        Image(
            url=f"data:image/png;base64,{png_1x1}",
            alt=f"image {i}",
            ref=f"IMG{i}",
        )
        for i in range(20)
    ]
    markdown = "\n".join(f"![Image {i}](llmwiki-image://IMG{i})" for i in range(20))

    rewritten, assets = await materialize_webclip_assets(
        markdown,
        images,
        "article.assets",
    )

    assert len(assets) == 20
    assert "llmwiki-image://" not in rewritten
    assert "![Image 19](./article.assets/image-20.png)" in rewritten


def test_webclip_path_normalization_restricts_to_webclipper_root():
    from fastapi import HTTPException
    from services.hosted import _normalize_webclip_path

    assert _normalize_webclip_path(None) == "/webclipper/"
    assert _normalize_webclip_path("webclipper/research") == "/webclipper/research/"
    assert _normalize_webclip_path("/webclipper//research/") == "/webclipper/research/"

    for bad_path in ["/", "/wiki/", "/sources/", "/webclipper/../wiki/", "/webclipper\\x"]:
        with pytest.raises(HTTPException):
            _normalize_webclip_path(bad_path)


def test_parser_instances_are_single_use():
    parser = Parser(
        "<p>x</p>",
        url="https://source.example/post",
    )
    parser.parse()

    with pytest.raises(RuntimeError):
        parser.parse()


@pytest.mark.asyncio
async def test_hosted_webclip_records_storage_size_for_markdown_artifact():
    from services.hosted import HostedDocumentService

    class Tx:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeConn:
        def __init__(self):
            self.insert_args = None

        def transaction(self):
            return Tx()

        async def execute(self, query, *args):
            return None

        async def fetchrow(self, query, *args):
            if "storage_limit_bytes" in query:
                return {"storage_limit_bytes": 100_000}
            if "INSERT INTO documents" in query:
                self.insert_args = args
                return {
                    "id": "doc-a",
                    "knowledge_base_id": args[1],
                    "user_id": args[2],
                    "filename": args[3],
                    "path": args[4],
                    "title": args[5],
                    "file_type": "md",
                    "status": "ready",
                    "tags": [],
                    "date": None,
                    "metadata": {},
                    "error_message": None,
                    "version": 0,
                    "document_number": 1,
                    "archived": False,
                    "created_at": None,
                    "updated_at": None,
                }
            return None

        async def fetchval(self, query, *args):
            if "FROM knowledge_bases" in query:
                return args[0]
            if "SUM(file_size)" in query:
                return 0
            return None

    class FakePool(FakeConn):
        def __init__(self):
            super().__init__()
            self.conn = FakeConn()

        async def acquire(self):
            return self.conn

        async def release(self, conn):
            return None

    class FakeS3:
        async def upload_bytes(self, key, data, content_type):
            return None

    pool = FakePool()
    service = HostedDocumentService(pool=pool, user_id="user-a", s3=FakeS3())
    await service.create_web_clip("kb-a", "https://example.com", "Title", "<p>Hello</p>")

    assert pool.conn.insert_args is not None
    assert pool.conn.insert_args[4] == "/webclipper/"
    file_size = pool.conn.insert_args[6]
    assert isinstance(file_size, int)
    assert file_size > 0


@pytest.mark.asyncio
async def test_hosted_webclip_rejects_when_storage_quota_exceeded():
    from fastapi import HTTPException
    from services.hosted import HostedDocumentService

    class FakePool:
        async def fetchrow(self, query, *args):
            if "storage_limit_bytes" in query:
                return {"storage_limit_bytes": 3}
            return None

        async def fetchval(self, query, *args):
            if "FROM knowledge_bases" in query:
                return args[0]
            if "SUM(file_size)" in query:
                return 0
            return None

    service = HostedDocumentService(pool=FakePool(), user_id="user-a", s3=None)

    with pytest.raises(HTTPException) as exc:
        await service.create_web_clip("kb-a", "https://example.com", "Title", "<p>Hello</p>")

    assert exc.value.status_code == 413


# ── Highlight locator ─────────────────────────────────────


def test_locate_single_match():
    plaintext = "The quick brown fox jumps over the lazy dog."
    a = Parser._locate_highlight(plaintext, {"textContent": "brown fox"})
    assert a is not None
    assert plaintext[a.text_start:a.text_end] == "brown fox"


def test_locate_normalizes_whitespace_in_input():
    plaintext = "The quick brown fox."
    # Caller passes unnormalized text — locator should still find it
    a = Parser._locate_highlight(plaintext, {"textContent": "  quick   brown  "})
    assert a is not None
    assert a.text_content == "quick brown"
    assert plaintext[a.text_start:a.text_end] == "quick brown"


def test_locate_no_match_returns_none():
    plaintext = "Hello world."
    a = Parser._locate_highlight(plaintext, {"textContent": "absent text"})
    assert a is None


def test_locate_disambiguates_via_prefix():
    plaintext = "The cat sat on the mat. The cat ran away."
    a = Parser._locate_highlight(
        plaintext,
        {"textContent": "The cat", "prefix": "mat. ", "suffix": " ran"},
    )
    assert a is not None
    # Should match the second occurrence (after "mat. ")
    assert a.text_start == plaintext.index("The cat", 10)


def test_locate_no_context_picks_first():
    plaintext = "The cat sat on the mat. The cat ran away."
    a = Parser._locate_highlight(plaintext, {"textContent": "The cat"})
    assert a is not None
    assert a.text_start == 0


def test_locate_empty_text_content():
    plaintext = "Hello."
    a = Parser._locate_highlight(plaintext, {"textContent": ""})
    assert a is None


def test_locate_whitespace_only_text_content():
    plaintext = "Hello."
    a = Parser._locate_highlight(plaintext, {"textContent": "   \n  "})
    assert a is None


# ── End-to-end: parse with highlights ─────────────────────


def test_parse_with_highlights_returns_mapped():
    html = (
        "<html><body>"
        "<h1>Title</h1>"
        '<p>The <strong>key</strong> insight is that <a href="https://x.com">attention</a> matters.</p>'
        "</body></html>"
    )
    p = Parser(html)
    result = p.parse(highlights=[
        {"id": "h1", "anchor": {"textContent": "key insight"}},
        {"id": "h2", "anchor": {"textContent": "attention matters"}},
    ])

    assert result.plaintext == "Title\n\nThe key insight is that attention matters."
    assert len(result.highlights) == 2
    assert result.highlights[0].text_anchor is not None
    assert result.highlights[0].text_anchor.text_content == "key insight"
    assert result.highlights[1].text_anchor is not None
    assert result.highlights[1].text_anchor.text_content == "attention matters"


def test_parse_unmapped_highlight_keeps_payload():
    html = "<html><body><p>Hello world.</p></body></html>"
    p = Parser(html)
    result = p.parse(highlights=[
        {"id": "h1", "anchor": {"textContent": "missing phrase"}},
    ])
    assert len(result.highlights) == 1
    assert result.highlights[0].text_anchor is None
    assert result.highlights[0].payload["id"] == "h1"


def test_parse_no_highlights_returns_empty():
    p = Parser("<p>x</p>")
    result = p.parse()
    assert result.highlights == []
    assert result.plaintext == "x"


def test_content_only_preserves_article_header_title():
    html = """
    <html><body>
      <header role="banner"><nav>Site nav</nav></header>
      <article>
        <header>
          <p>Supported by</p>
          <h1>Trump Administration Sees Striking Exodus of Legal Talent</h1>
          <p>By Eileen Sullivan and Andrea Fuller</p>
        </header>
        <p>President Trump's upheaval of the federal government has led to an exodus.</p>
      </article>
    </body></html>
    """
    result = Parser(html, content_only=True).parse()

    assert "Site nav" not in result.content
    assert "# Trump Administration Sees Striking Exodus of Legal Talent" in result.content
    assert "President Trump's upheaval" in result.content


def test_parse_highlight_across_inline_tags():
    """Highlight spans a <strong> boundary in the source HTML.
    In plaintext the inline tag is gone, so the highlight matches cleanly."""
    html = "<p>The <strong>quick</strong> brown fox.</p>"
    p = Parser(html)
    result = p.parse(highlights=[
        {"id": "x", "anchor": {"textContent": "quick brown"}},
    ])
    a = result.highlights[0].text_anchor
    assert a is not None
    assert result.plaintext[a.text_start:a.text_end] == "quick brown"


def test_parse_handles_image_in_highlight_range():
    """User selected text that crossed an image. Image emits empty in
    plaintext, so the surrounding text concatenates and the highlight
    locates as expected."""
    html = '<p>Look at <img src="x.png" alt="diagram"/> here.</p>'
    p = Parser(html)
    result = p.parse(highlights=[
        {"id": "x", "anchor": {"textContent": "Look at here"}},
    ])
    a = result.highlights[0].text_anchor
    assert a is not None
    # Plaintext is "Look at  here." (two spaces where image was);
    # locator finds the normalized phrase
    assert "Look at" in result.plaintext[a.text_start:a.text_end]
    assert "here" in result.plaintext[a.text_start:a.text_end]


def test_parse_cross_block_highlight():
    """Selection spans paragraphs. range.toString() gives newline-collapsed
    text but plaintext keeps `\\n\\n` between paragraphs. The locator's
    normalize-with-index-map handles this."""
    html = "<p>End of first paragraph.</p><p>Start of second paragraph.</p>"
    p = Parser(html)
    result = p.parse(highlights=[
        # Extension might capture this as collapsed-whitespace text
        {"id": "x", "anchor": {"textContent": "first paragraph. Start of"}},
    ])
    a = result.highlights[0].text_anchor
    assert a is not None
    # Maps back to original plaintext offsets, which span the paragraph break
    span = result.plaintext[a.text_start:a.text_end]
    assert "first paragraph" in span
    assert "Start of" in span
    assert "\n\n" in span  # paragraph break preserved


def test_parse_short_highlight_no_context_unlocated():
    """Single common word with multiple occurrences and no prefix/suffix
    leaves the highlight unlocated rather than guessing."""
    html = "<p>The cat sat on the mat. The dog ran on the rug.</p>"
    p = Parser(html)
    result = p.parse(highlights=[
        {"id": "x", "anchor": {"textContent": "the"}},  # ambiguous, no context
    ])
    assert result.highlights[0].text_anchor is None


def test_parse_short_highlight_with_prefix_locates():
    """Same short text but with prefix becomes locatable."""
    html = "<p>The cat sat on the mat. The dog ran on the rug.</p>"
    p = Parser(html)
    result = p.parse(highlights=[
        {"id": "x", "anchor": {
            "textContent": "the",
            "prefix": "ran on ",
        }},
    ])
    a = result.highlights[0].text_anchor
    assert a is not None
    # Should land on "the" before "rug", not the first occurrence
    assert result.plaintext[a.text_start:a.text_start + 7] == "the rug"
