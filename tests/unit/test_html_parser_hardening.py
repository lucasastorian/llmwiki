"""Hostile-input invariants for the HTML parser: markers, URLs, tables, depth, budgets, styles and noise filtering."""

import re
import time
import warnings
from functools import partial
from html import escape

import pytest
from html_parser import ParseLimitExceededError, Parser
from html_parser.parser import MAX_OUTPUT_CHARS, MAX_RENDER_DEPTH

from tests.support.scaling import assert_linear_scaling, best_seconds

MARKER_CHARS = [chr(code) for code in range(0x00, 0x09)]
ATTRIBUTE_TEMPLATES = [
    '<p><a href="https://x.com/a{c}7{c}b">link</a> tail</p>',
    '<p><a href="https://x.com/a b{c}">link</a></p>',
    '<p><a href="/rel{c}">link</a></p>',
    '<p>See <img src="https://x.com/{c}.png" alt="al{c}t"> now</p>',
    '<p><img srcset="https://x.com/{c}a.png 1x, /b{c}.png 2x"> now</p>',
    '<form action="/s{c}"><input name="q{c}" placeholder="pl{c}ace"><input type="submit" value="Go{c}"></form>',
    '<p><code title="t{c}">x</code> <button value="v{c}">b</button></p>',
]


def _parse(html: str, url: str = "", content_only: bool = False) -> tuple[str, str]:
    result = Parser(html, url=url, content_only=content_only).parse()
    return result.content, result.plaintext


def _without_marker(html: str, marker: str) -> str:
    """lxml already turns NUL into U+FFFD; every other marker is scrubbed by the parser."""
    return html.replace(marker, "�" if marker == "\x00" else "")


@pytest.mark.parametrize("url", ["", "https://example.com/dir/page"])
@pytest.mark.parametrize("template", ATTRIBUTE_TEMPLATES)
@pytest.mark.parametrize("marker", MARKER_CHARS, ids=[f"x{ord(c):02x}" for c in MARKER_CHARS])
def test_marker_chars_in_attributes_are_inert(marker: str, template: str, url: str) -> None:
    html = template.replace("{c}", marker)
    assert _parse(html, url) == _parse(_without_marker(html, marker), url)


@pytest.mark.parametrize("html", [
    '<p>keep <a href="HTTP://[broken">text</a></p>',
    '<p>keep <a href="//[broken">text</a></p>',
])
@pytest.mark.parametrize("url", ["", "https://example.com/"])
def test_malformed_link_url_keeps_text_and_drops_link(html: str, url: str) -> None:
    assert _parse(html, url) == ("keep text", "keep text")


@pytest.mark.parametrize("url", ["", "https://example.com/"])
def test_malformed_image_urls_drop_only_the_bad_candidate(url: str) -> None:
    parser = Parser(
        '<p>a <img src="HTTPS://[x"> b <img srcset="HTTP://[x 1x, https://ok.example/i.png 2x"> c</p>', url=url,
    )
    result = parser.parse()
    assert result.content == "a  b![](llmwiki-image://IMG1)c"
    assert [image.url for image in result.images] == ["https://ok.example/i.png"]
    assert result.plaintext == "a b\n\nc"


def test_malformed_urls_survive_dom_url_rewrite() -> None:
    parser = Parser('<p><a href="/[x">t</a><img src="/ok.png" srcset="//[y 1x"></p>', url="https://example.com/")
    parser.parse()
    assert parser.soup.img["src"] == "https://example.com/ok.png"


def _markdown_cell_words(markdown: str) -> list[str]:
    """Words of every table cell, or of the whole line where a table was rendered as blocks."""
    words: list[str] = []
    for line in markdown.split("\n"):
        if re.fullmatch(r"\|(---\|)+", line):
            continue
        cells = re.split(r"(?<!\\)\|", line)[1:-1] if line.startswith("|") else [line]
        for cell in cells:
            words.extend(cell.split())
    return sorted(words)


@pytest.mark.parametrize("html", [
    "<table><tr><td rowspan=2>A<td>B<tr><td>C<td>D</table>",
    "<table><tr><td rowspan=3>A<td>B</tr><tr></tr><tr><td>C<td>D</tr></table>",
    "<table><tr><th>H1<th colspan=2>H2</tr><tr><td colspan=2>A<td>B<td>C</tr></table>",
    "<table><tr><th>H</th></tr><tr><td>A<table><tr><td>N1</td><td>N2</td></tr></table></td><td>B</td></tr></table>",
    "<table><thead><tr><th>H1<th>H2</thead><tbody><tr><td rowspan=2>A<td>B<tr><td>C</tbody></table>",
    pytest.param(
        "<table>" + "<tr><td rowspan=1000 colspan=1000>X</td><td>Y</td></tr>" + "<tr><td>Z</td></tr>" * 300 + "</table>",
        id="over-budget-spans",
    ),
])
def test_table_markdown_and_plaintext_hold_the_same_cells(html: str) -> None:
    markdown, plaintext = _parse(html)
    assert _markdown_cell_words(markdown) == sorted(plaintext.split())


def test_rowspan_into_a_wider_row_keeps_every_cell() -> None:
    markdown, _ = _parse("<table><tr><td rowspan=2>A<td>B<tr><td>C<td>D</table>")
    assert markdown == "| A | B |  |\n|---|---|---|\n|  | C | D |"


def test_nested_table_cells_are_not_duplicated_in_the_outer_table() -> None:
    markdown, plaintext = _parse(
        "<table><tr><th>H</th></tr><tr><td>A<table><tr><td>N</td></tr></table></td></tr></table>",
    )
    assert markdown.count("N") == 1
    assert plaintext.count("N") == 1


def test_deeply_nested_tables_parse_in_linear_time() -> None:
    html = "<table><tr><td>" * 80 + "x" + "</td></tr></table>" * 80
    start = time.monotonic()
    markdown, plaintext = _parse(html)
    assert time.monotonic() - start < 2
    assert (markdown, plaintext) == ("x", "x")


def test_relative_link_amplification_hits_the_output_budget_quickly() -> None:
    base_url = "https://example.com/" + "a" * 2000 + "/"
    html = "<p>" + "<a href=b>b</a> " * 70_000 + "</p>"
    start = time.monotonic()
    with pytest.raises(ParseLimitExceededError):
        Parser(html, url=base_url).parse()
    assert time.monotonic() - start < 15


def test_unrendered_links_still_charge_the_budget_through_dom_url_rewrite() -> None:
    base_url = "https://example.com/" + "a" * 2000 + "/"
    html = "<p>x" + "<a href=b></a>" * (MAX_OUTPUT_CHARS // 2000 + 10) + "</p>"
    with pytest.raises(ParseLimitExceededError):
        Parser(html, url=base_url).parse()


def test_many_highlights_on_a_large_page_map_quickly() -> None:
    paragraph = "<p>" + "lorem ipsum dolor sit amet " * 40 + "</p>"
    html = paragraph * 1200 + "<p>needle phrase here</p>"
    highlights = [{"anchor": {"textContent": "needle phrase here"}} for _ in range(200)]
    start = time.monotonic()
    result = Parser(html).parse(highlights=highlights)
    assert time.monotonic() - start < 10
    assert all(h.text_anchor is not None for h in result.highlights)


@pytest.mark.parametrize("html", [
    pytest.param("<div>" * 300 + "x" + "</div>" * 300, id="300-divs"),
    pytest.param("<div>" * 700 + "x" + "</div>" * 700, id="700-divs"),
    pytest.param("<blockquote>" * 200 + "x" + "</blockquote>" * 200, id="200-blockquotes"),
    pytest.param("<ul><li>" * 200 + "x" + "</li></ul>" * 200, id="200-bullet-lists"),
    pytest.param("<ol><li>" * 200 + "x" + "</li></ol>" * 200, id="200-ordered-lists"),
    pytest.param("<table><tr><td>" * 100 + "x" + "</td></tr></table>" * 100, id="100-tables"),
    pytest.param("<h2>" + "<span>" * 400 + "x" + "</span>" * 400 + "</h2>", id="400-spans-in-heading"),
    pytest.param("<p>" + "<a href='/a'>" * 300 + "x" + "</a>" * 300 + "</p>", id="300-links"),
])
def test_deep_nesting_renders_without_recursion_errors(html: str) -> None:
    markdown, plaintext = _parse(html)
    assert "x" in markdown
    assert plaintext == "x"


def test_flattened_deep_subtree_keeps_block_and_image_boundaries() -> None:
    deep = "<div>" * (MAX_RENDER_DEPTH + 20)
    closing = "</div>" * (MAX_RENDER_DEPTH + 20)
    html = (
        f"{deep}<p>first <b>bold</b></p><p>second</p><img src='https://x.com/i.png'>"
        f"<span hidden>secret</span><ul><li>item</li></ul>{closing}"
    )
    markdown, plaintext = _parse(html)
    assert markdown == "first bold\n\nsecond\n\n![](llmwiki-image://IMG1)\n\nitem"
    assert plaintext == "first bold\n\nsecond\n\nitem"


@pytest.mark.parametrize("html", [
    "<template><p>hidden</p></template><p>visible</p>",
    "<!DOCTYPE html><html><body><template id='B:0'></template><p>visible</p></body></html>",
])
def test_template_contents_are_not_rendered(html: str) -> None:
    assert _parse(html) == ("visible", "visible")


def test_doctype_is_not_rendered_as_text() -> None:
    assert _parse("<!DOCTYPE html><title>T</title>") == ("T", "T")


def test_leading_xml_declaration_is_stripped_without_a_warning() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert _parse('<?xml version="1.0" encoding="utf-8"?><html><body><p>x</p></body></html>') == ("x", "x")


@pytest.mark.parametrize("href", [
    "java&amp;#115;cript:alert(1)",
    "javascript&amp;colon;alert(1)",
    "javascript&colon;alert(1)",
    "&amp;#106;avascript:alert(1)",
    "java\x01script:alert(1)",
])
def test_entity_encoded_unsafe_schemes_keep_text_only(href: str) -> None:
    assert _parse(f'<p><a href="{href}">Open me</a></p>') == ("Open me", "Open me")


def test_link_destinations_escape_entity_like_ampersands() -> None:
    markdown, _ = _parse('<p><a href="https://x.com/?a=1&amp;amp;b=2&amp;copy;">t</a></p>')
    assert markdown == "[t](https://x.com/?a=1&amp;amp;b=2&amp;copy;)"


def test_plain_query_string_ampersands_are_left_alone() -> None:
    markdown, _ = _parse('<p><a href="https://x.com/?a=1&amp;b=2">t</a></p>')
    assert markdown == "[t](https://x.com/?a=1&b=2)"


@pytest.mark.parametrize(("html", "markdown"), [
    ('<p><b style="font-weight:normal" id="docs-internal-guid-1"><span>plain</span></b></p>', "plain"),
    ('<p><strong style="font-weight: 400">plain</strong></p>', "plain"),
    ('<p><span style="font-weight: bold">B</span> <span style="font-style: italic">I</span></p>', "**B** *I*"),
    ('<p><span style="FONT-WEIGHT: 700 !important">B</span></p>', "**B**"),
    ('<p><span style="font-weight:600">B</span> <span style="font-weight:500">n</span></p>', "**B** n"),
    ('<p><span style="font-weight:bolder">B</span></p>', "**B**"),
    ('<p><em style="font-style:normal">n</em></p>', "n"),
    ('<p><span style="--mobile-display:none">kept</span></p>', "kept"),
    ('<p><span style="--font-weight:700">plain</span></p>', "plain"),
    ('<p><span style="x-display:none; display : none">gone</span>shown</p>', "shown"),
    ('<p><span style="visibility: hidden">gone</span>shown</p>', "shown"),
])
def test_inline_styles_use_exact_declarations(html: str, markdown: str) -> None:
    assert _parse(html)[0] == markdown


ARTICLE_TEXT = "This is the real article body. " * 12


def test_content_only_keeps_articles_inside_banner_classes() -> None:
    markdown, _ = _parse(f'<div class="banner"><article><p>{ARTICLE_TEXT}</p></article></div>', content_only=True)
    assert markdown == ARTICLE_TEXT.strip()


@pytest.mark.parametrize("token", ["navbar", "mobile-nav", "dropdown-menu", "mega-menu", "w-nav"])
def test_content_only_drops_navigation_class_tokens(token: str) -> None:
    html = f'<div class="{token}"><a href="/x">Menu link</a></div><article><p>{ARTICLE_TEXT}</p></article>'
    markdown, _ = _parse(html, content_only=True)
    assert "Menu link" not in markdown


def test_react_streamed_hidden_segments_are_rendered() -> None:
    html = f'<main><template id="B:0"></template></main><div hidden id="S:0"><p>{ARTICLE_TEXT}</p></div><div hidden><p>x</p></div>'
    markdown, plaintext = _parse(html, content_only=True)
    assert markdown == ARTICLE_TEXT.strip()
    assert plaintext == ARTICLE_TEXT.strip()


def test_thin_content_only_result_falls_back_to_the_whole_page() -> None:
    parser = Parser(f'<div class="overlay"><article><p>{ARTICLE_TEXT}</p></article></div>', content_only=True)
    result = parser.parse()
    assert result.content == ARTICLE_TEXT.strip()
    assert result.plaintext == ARTICLE_TEXT.strip()
    assert "data-webmd-block" in parser.html()


@pytest.mark.asyncio
async def test_hosted_web_clip_over_the_output_budget_is_413(monkeypatch) -> None:
    from fastapi import HTTPException
    from services.hosted import HostedDocumentService

    class KbPool:
        async def fetchval(self, query: str, *args: object) -> object:
            return args[0]

    monkeypatch.setattr("html_parser.parser.MAX_OUTPUT_CHARS", 50)
    service = HostedDocumentService(pool=KbPool(), user_id="user-a", s3=None)
    with pytest.raises(HTTPException) as exc:
        await service.create_web_clip("kb-a", "https://example.com", "Title", "<p>" + "word " * 100 + "</p>")
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_local_web_clip_over_the_output_budget_is_413(monkeypatch) -> None:
    from fastapi import HTTPException
    from services.local import LocalDocumentService

    monkeypatch.setattr("html_parser.parser.MAX_OUTPUT_CHARS", 50)
    service = LocalDocumentService(db=None, user_id="user-a")
    with pytest.raises(HTTPException) as exc:
        await service.create_web_clip("kb-a", "https://example.com", "Title", "<p>" + "word " * 100 + "</p>")
    assert exc.value.status_code == 413


def test_web_clip_payload_replaces_lone_surrogates() -> None:
    from services.types import CreateWebClip

    clip = CreateWebClip.model_validate({
        "url": "https://example.com",
        "title": "T\ud800",
        "html": "<p>a\udc00b</p>",
        "highlights": [{
            "id": "h1",
            "anchor": {"xpath": "/p", "startOffset": 0, "endOffset": 1, "textContent": "a\ud83d", "prefix": "\udfff"},
            "comment": "c\ud800",
            "replies": [{"id": "r1", "text": "r\udc00", "createdAt": "now"}],
            "createdAt": "now",
        }],
    })
    highlight = clip.highlights[0]
    assert (clip.title, clip.html) == ("T�", "<p>a�b</p>")
    assert (highlight.anchor.textContent, highlight.anchor.prefix) == ("a�", "�")
    assert (highlight.comment, highlight.replies[0].text) == ("c�", "r�")
    assert Parser(clip.html).parse().content == "a�b"


def test_parser_replaces_lone_surrogates_in_markup() -> None:
    assert _parse("<p>a\ud800b \U0001f600</p>") == ("a�b \U0001f600", "a�b \U0001f600")


def _nested_blockquote_lines(depth: int, lines: int) -> str:
    body = "<br>".join(f"line {i}" for i in range(lines))
    return "<blockquote>" * depth + body + "</blockquote>" * depth


def test_nested_quote_depth_does_not_multiply_the_cost_per_line() -> None:
    shallow = best_seconds(partial(_parse, _nested_blockquote_lines(40, 1000)))
    deep = best_seconds(partial(_parse, _nested_blockquote_lines(160, 1000)))
    assert deep / shallow < 3


def test_deeply_quoted_line_flood_hits_the_output_budget_quickly() -> None:
    start = time.monotonic()
    with pytest.raises(ParseLimitExceededError):
        Parser(_nested_blockquote_lines(120, 100_000)).parse()
    assert time.monotonic() - start < 30


def test_table_whose_rows_cross_the_depth_limit_is_flattened_whole() -> None:
    table = "<table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>"
    html = "<div>" * (MAX_RENDER_DEPTH - 4) + table + "</div>" * (MAX_RENDER_DEPTH - 4)
    assert _parse(html) == ("a\n\nb\n\nc\n\nd", "a\n\nb\n\nc\n\nd")


def test_oversized_table_renders_a_block_per_cell_in_both_walkers() -> None:
    html = "<table><tr>" + "<td>x</td>" * 400 + "</tr>" + "<tr><td>y<img src='https://x.com/i.png'></td></tr>" * 400 + "</table>"
    markdown, plaintext = _parse(html)
    assert "|" not in markdown
    assert markdown.split("\n\n") == ["x"] * 400 + [f"y![](llmwiki-image://IMG{i})" for i in range(1, 401)]
    assert plaintext.split("\n\n") == ["x"] * 400 + ["y"] * 400


@pytest.mark.parametrize("html", [
    pytest.param("<pre>" + "x" * 2000 + "</pre>", id="pre"),
    pytest.param("<p><code>" + "x" * 2000 + "</code></p>", id="inline-code"),
    pytest.param("<table><tr><th>h</th></tr><tr><td><pre>" + "x" * 2000 + "</pre></td></tr></table>", id="pre-in-cell"),
    pytest.param("<p><code>" + "`" * 600 + "</code></p>", id="backtick-fence"),
])
def test_code_bodies_and_fences_are_charged_to_the_output_budget(html: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("html_parser.parser.MAX_OUTPUT_CHARS", 1000)
    with pytest.raises(ParseLimitExceededError):
        Parser(html).parse()


def _parse_srcset_image(candidates: int) -> None:
    srcset = ", ".join(f"i{i}.png {i + 1}w" for i in range(candidates))
    Parser(f'<p><img srcset="{srcset}"></p>', url="https://example.com/" + "a" * 200 + "/").parse()


def test_srcset_candidates_scale_linearly() -> None:
    assert_linear_scaling(_parse_srcset_image, 1000)


def _parse_nested_headers(depth: int) -> None:
    Parser("<header>" * depth + "<h1>Title</h1>" + "</header>" * depth, content_only=True).parse()


def test_nested_header_noise_checks_scale_linearly() -> None:
    assert_linear_scaling(_parse_nested_headers, 250)


@pytest.mark.parametrize("html", [
    pytest.param("<ul><li>a</li><li hidden>SECRET</li></ul>", id="list-item"),
    pytest.param("<ol><li aria-hidden='true'>SECRET</li><li>a</li></ol>", id="aria-hidden-item"),
    pytest.param("<p><code>a<span hidden>SECRET</span>b</code></p>", id="inline-code"),
    pytest.param("<pre>a<span style='display:none'>SECRET</span>b</pre>", id="pre"),
    pytest.param("<p><button>ok<span hidden>SECRET</span></button></p>", id="button-label"),
    pytest.param("<p><select><option hidden>SECRET</option><option>a</option></select></p>", id="select-option"),
    pytest.param("<table><tr><th>h</th></tr><tr><td hidden>SECRET</td><td>a</td></tr></table>", id="table-cell"),
    pytest.param("<table><tr><th>h</th></tr><tr style='visibility:hidden'><td>SECRET</td></tr></table>", id="table-row"),
])
@pytest.mark.parametrize("content_only", [False, True])
def test_hidden_content_never_renders(html: str, content_only: bool) -> None:
    markdown, plaintext = _parse(html, content_only=content_only)
    assert "SECRET" not in markdown
    assert "SECRET" not in plaintext


@pytest.mark.parametrize(("style", "is_visible"), [
    ("display:none!important;display:block", False),
    ("display:none !IMPORTANT; display:block !important", True),
    ("--data:\";display:none;\"", True),
    ("--data:';display:none;'", True),
    ("color:red /* ; display:none */", True),
    ("background:url(a;display:none)", True),
    ("display:block;display:none", False),
])
def test_inline_style_tokenizing_and_importance(style: str, is_visible: bool) -> None:
    markdown, _ = _parse(f'<p><span style="{escape(style)}">shown</span> tail</p>')
    assert ("shown" in markdown) is is_visible


def test_site_header_with_only_a_hidden_heading_is_still_noise() -> None:
    html = f'<header><h1 hidden>Brand</h1><a href="/login">Log in</a></header><article><p>{ARTICLE_TEXT}</p></article>'
    markdown, _ = _parse(html, content_only=True)
    assert markdown == ARTICLE_TEXT.strip()
