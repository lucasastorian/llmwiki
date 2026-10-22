"""Hand-written hostile HTML documents for parser invariant tests."""
from __future__ import annotations

from tests.support.types import HtmlDocument

BASE_URL = "https://example.com/base/"
C0_CONTROLS = "".join(chr(code) for code in range(0x00, 0x20))
C1_CONTROLS = "".join(chr(code) for code in range(0x7F, 0xA0))
INTERNAL_MARKERS = "".join(chr(code) for code in range(0x00, 0x09))
MARKER_ENTITIES = "".join(f"&#{code};" for code in range(0x00, 0x09)) + "&#x80;&#x9F;"
UNICODE_SPACES = "                 　﻿​"
ASTRAL_TEXT = "\U0001f469‍\U0001f4bb \U0001f1fa\U0001f1f8 \U0001d518\U0001d52b \U00020000 é ‮RTL‬"
LONG_RUN = 20_000
DEEP_DIVS = 700
DEEP_CONTAINERS = 200
DEEP_TABLES = 100
LINK_AMPLIFICATION_LINKS = 20_000
QUOTED_FLOOD_LINES = 5_000
LONG_PAGE_URL = BASE_URL + "p/" + "a" * 2_000 + "/"


def adversarial_cases() -> dict[str, HtmlDocument]:
    return {
        "controls_in_text": _case(_controls_in_text(), "title", "graph", "formatted", "entities"),
        "markers_in_attributes": _case(_markers_in_attributes(), "link", "[Form: POST /f"),
        "marker_placeholders_as_text": _case(_marker_placeholders_as_text(), "before", "real code"),
        "lone_surrogates": _case(_lone_surrogates(), "high \ufffd low", "reversed", "head"),
        "malformed_urls": _case(_malformed_urls(), "link 0", "link 20"),
        "entity_encoded_schemes": _case(_entity_encoded_schemes(), "entity link 0", "entity link 9"),
        "malformed_tables": _case(_malformed_tables(), "after empty rows", "inner c", "list in cell", "next | pipe"),
        "huge_spans": _case(_huge_spans(), "giant", "c999", "past the cell budget"),
        "deep_divs": _case(_wrap("<div>", "</div>", DEEP_DIVS, "bottom of the divs"), "bottom of the divs"),
        "deep_lists": _case(_deep_lists(), "level 0", f"level {DEEP_CONTAINERS - 1}", "deep"),
        "deep_blockquotes": _case(_deep_blockquotes(), "line 0", "line 199", "code"),
        "deep_quoted_line_flood": _case(_deep_quoted_line_flood(), "line 0", f"line {QUOTED_FLOOD_LINES - 1}"),
        "deep_tables": _case(
            _wrap("<table><tr><td>", "</td></tr></table>", DEEP_TABLES, "innermost cell"), "innermost cell",
        ),
        "deep_mixed_containers": _case(_deep_mixed_containers(), "m0", f"m{DEEP_CONTAINERS - 1}", "cell", "heading"),
        "nested_code_amplification": _case(_nested_code_amplification(), "x x x"),
        "deep_emphasis": _case(_wrap("<b><i>", "</i></b>", DEEP_CONTAINERS, "deep emphasis"), "deep emphasis"),
        "split_syntax": _case(_split_syntax(), "1. x", "123) x", "# heading?", "indented?"),
        "relative_link_amplification": HtmlDocument(html=_relative_links(), url=LONG_PAGE_URL, expects_limit_error=True),
        "long_delimiter_runs": _case(_long_delimiter_runs(), "*" * 100, "#" * 100, "|" * 100),
        "unicode_whitespace_runs": _case(_unicode_whitespace_runs(), "lead and trail", "heading", "cell"),
        "emoji_and_astral": _case(_emoji_and_astral(), "\U0001f600", "RTL"),
        "code_and_pre": _case(_code_and_pre(), "fence inside", "code heading", "CRLF"),
        "forms": _case(_forms(), "[Form: POST /submit]", "[opt 0]"),
        "headings": _case(_headings(), "trailing ###", "table in heading"),
        "hidden_content_in_tables": HtmlDocument(
            html=_hidden_content_in_tables(), url=BASE_URL, sentinels=("shown", "visible", "streamed"),
            hidden=("hidden cell", "hidden attr", "hidden row", "aria"),
        ),
        "many_hard_breaks": _case("<p>" + "x <br> " * LONG_RUN + "</p>", "x\nx\nx"),
        "many_paragraphs": _case(
            "".join(f"<p>paragraph {i}</p>" for i in range(LONG_RUN)), "paragraph 0", f"paragraph {LONG_RUN - 1}",
        ),
        "document_shell_noise": HtmlDocument(
            html=_document_shell_noise(), url=BASE_URL, sentinels=("body", "after"),
            hidden=("template", "noscript", "svg", "cdata", "comment", "p{}"),
        ),
    }


def _case(html: str, *sentinels: str) -> HtmlDocument:
    return HtmlDocument(html=html, url=BASE_URL, sentinels=sentinels)


def _wrap(opening: str, closing: str, depth: int, text: str) -> str:
    return opening * depth + text + closing * depth


def _controls_in_text() -> str:
    noise = C0_CONTROLS + C1_CONTROLS
    return (
        f"<h1>title{noise}end</h1><p>para{noise}graph</p>"
        f"<ul><li>item{noise}</li><li>{INTERNAL_MARKERS}</li></ul>"
        f"<table><tr><th>head{noise}</th></tr><tr><td>cell{noise}</td></tr></table>"
        f"<pre>pre{noise}formatted</pre><p><code>code{noise}</code> <a href='/x'>link{noise}</a></p>"
        f"<blockquote>quote{noise}</blockquote><p>{MARKER_ENTITIES}entities</p>"
    )


def _markers_in_attributes() -> str:
    return (
        f"<p><img alt='alt{INTERNAL_MARKERS}]' src='/img{INTERNAL_MARKERS}.png' "
        f"srcset='/a{INTERNAL_MARKERS}.png 100w, /b.png{INTERNAL_MARKERS} 200w'></p>"
        f"<p><a href='/l{INTERNAL_MARKERS}' title='t{INTERNAL_MARKERS}'>link</a></p>"
        f"<form action='/f\x03{INTERNAL_MARKERS}' method='po\x06st'>"
        f"<input name='n{INTERNAL_MARKERS}' placeholder='ph{INTERNAL_MARKERS}'>"
        f"<input type='submit' value='go{INTERNAL_MARKERS}'>"
        f"<textarea placeholder='{MARKER_ENTITIES}'></textarea>"
        f"<select><option>opt{INTERNAL_MARKERS}</option></select><button>b{INTERNAL_MARKERS}</button></form>"
        f"<p><img alt='{MARKER_ENTITIES}' src='{MARKER_ENTITIES}'></p>"
    )


def _marker_placeholders_as_text() -> str:
    placeholders = "\x030\x03 \x080\x08 \x06**x**\x07 \x05 \x02 \x00"
    entity_placeholders = "&#3;0&#3; &#8;0&#8; &#6;**y**&#7; &#5;"
    return (
        f"<p>before <pre>real code</pre> {placeholders} {entity_placeholders}</p>"
        f"<p><code>c</code>{entity_placeholders}<code>d</code></p>"
        f"<table><tr><td>{entity_placeholders}<pre>x</pre></td></tr></table>"
        f"<ul><li>{entity_placeholders}<pre>y</pre></li></ul>"
    )


def _lone_surrogates() -> str:
    return (
        "<p>high \ud800 low \udfff pair-ish 􏰀 reversed \udc00\ud800</p>"
        "<p><a href='/s\ud800'>link\udfff</a><img alt='\ud83d' src='/i.png'></p>"
        "<table><tr><td>\ud800</td><td>&#xD800;&#xDFFF;</td></tr></table>"
        "<h2>head \udc00</h2><pre>code \ud800</pre>"
    )


def _malformed_urls() -> str:
    hrefs = [
        "HTTP://[x", "http://[::1", "https://[", "//[y", "http://a b/c", "http:", "http://", "https:///x",
        " java\tscript:alert(1)", "javascript:alert(1)", "data:text/html,x", "vbscript:x", "[", "]",
        "%", "?q=<x>", "#frag", "mailto:a@b", "ftp://x", "http://example.com/a(b)c", "http://[1:2:3:4:5:6:7:8:9]",
    ]
    links = "".join(f"<p><a href='{href}'>link {i}</a></p>" for i, href in enumerate(hrefs))
    srcsets = [
        "HTTP://[x 1x", "http://[x 100w, , ,  //[y 2w", "a.png 10w, b.png", ",,,", "x 9999999999999w",
        "data:image/png;base64,AAAA 3w, HTTP://[z 4w",
    ]
    images = "".join(f"<p><img alt='img {i}' srcset='{srcset}'></p>" for i, srcset in enumerate(srcsets))
    return links + images + "<p><img src='HTTP://[x' alt='bad src'><img src='//[x' alt='proto relative'></p>"


def _entity_encoded_schemes() -> str:
    hrefs = [
        "java&amp;#115;cript:alert(1)", "&#106;avascript:alert(1)", "jav&#x09;ascript:x", "java&#0;script:x",
        "&amp;#x6A;avascript:x", "javascript&colon;x", "java&NewLine;script:x", "http://x/?a=&amp;#115;",
        "&amp;amp;#115;", "%6A%61%76%61script:x",
    ]
    return "".join(f"<p><a href=\"{href}\">entity link {i}</a> &amp;#115; text</p>" for i, href in enumerate(hrefs))


def _malformed_tables() -> str:
    return (
        "<table><tr></tr><tr><td></td></tr><tr><td>after empty rows</td></tr></table>"
        "<table><tr><td rowspan='3' colspan='2'>span</td><td>a</td></tr><tr><td>b</td></tr><tr></tr>"
        "<tr><td colspan='-4'>neg</td><td rowspan='0'>zero</td><td colspan='2abc'>junk</td></tr></table>"
        "<table><tr><th>h1</th><th>h2</th></tr><tr><td>only one</td></tr>"
        "<tr><td>1</td><td>2</td><td>3</td><td>4</td></tr></table>"
        "<td>orphan cell</td><tr><td>orphan row</td></tr>"
        "<table><tr><td>outer<table><tr><td rowspan='2'>inner a</td><td>inner b</td></tr>"
        "<tr><td>inner c</td></tr></table>tail</td><td>next | pipe</td></tr></table>"
        "<table><thead><tr><th></th><th></th></tr></thead><tbody><tr><td> </td><td>&nbsp;</td></tr></tbody></table>"
        "<table><tr><td><p>block</p><ul><li>list in cell</li></ul><br>broken<br></td><td>x</td></tr></table>"
        "<table><caption>cap</caption><colgroup><col span='99999'></colgroup><tr><td>c</td></tr></table>"
    )


def _huge_spans() -> str:
    wide = "<tr>" + "".join(f"<td>c{i}</td>" for i in range(1_000)) + "</tr>"
    return (
        "<table><tr><td rowspan='99999' colspan='99999'>giant</td><td>b</td></tr>"
        "<tr><td>c</td></tr></table>"
        "<table>" + wide * 5 + "</table>"
        "<table>" + "<tr><td colspan='1000'>x</td><td>past the cell budget</td></tr>" * 200 + "</table>"
    )


def _deep_lists() -> str:
    opening = "".join(f"<{'ol' if depth % 2 else 'ul'}><li>level {depth}" for depth in range(DEEP_CONTAINERS))
    closing = "".join(f"</li></{'ol' if depth % 2 else 'ul'}>" for depth in reversed(range(DEEP_CONTAINERS)))
    return opening + "<pre>deep\ncode</pre>" + closing


def _deep_blockquotes() -> str:
    lines = "<br>".join(f"line {i}" for i in range(200))
    return _wrap("<blockquote>", "</blockquote>", DEEP_CONTAINERS, f"<p>{lines}</p><pre>q\ncode</pre>")


def _deep_quoted_line_flood() -> str:
    lines = "<br>".join(f"line {i}" for i in range(QUOTED_FLOOD_LINES))
    return _wrap("<blockquote>", "</blockquote>", DEEP_TABLES + 20, lines)


def _nested_code_amplification() -> str:
    return _wrap("<blockquote>", "</blockquote>", DEEP_TABLES + 20, "<pre>" + "x\n" * 100_000 + "</pre>")


def _deep_mixed_containers() -> str:
    layers = [("<ul><li>", "</li></ul>"), ("<blockquote>", "</blockquote>"), ("<ol><li>", "</li></ol>"), ("<div>", "</div>")]
    opening = "".join(layers[depth % len(layers)][0] + f"m{depth} " for depth in range(DEEP_CONTAINERS))
    closing = "".join(layers[depth % len(layers)][1] for depth in reversed(range(DEEP_CONTAINERS)))
    return opening + "<table><tr><td>cell</td></tr></table><h2>heading</h2>" + closing


def _split_syntax() -> str:
    fragments = [
        "<span>1</span>. x", "1<!-- c -->. x", "12<span>3</span>) x", "<b>#</b> heading?", "-<!---->- -",
        "<span>&gt;</span> quote?", "*<i>a</i>*", "[<a href='/y'>y</a>](z)", "<code>a</code><code>b</code>",
        "!<img src='/i.png' alt='i'>[a](b)", "&lt;<span>div</span>&gt;", "<span>-</span> item?",
        "<span>+</span><span> </span>item?", "=<!---->==", "<span>|</span> a | b", "<span>`</span>code<span>`</span>",
        "<i>*</i>x<i>*</i>", "_<b>a</b>_", "<s>~</s>~strike~~", "1<br>. after break", "<span>    </span>indented?",
        "<b>bold </b><b> bold</b>", "<i>a</i><i>b</i>", "<a href='/a'>a</a><a href='/b'>b</a>",
    ]
    return "".join(f"<p>{fragment}</p><div>{fragment}</div><li>{fragment}</li>" for fragment in fragments)


def _relative_links() -> str:
    hrefs = ["?", "", ".", "./", "x", "#", "?q"]
    return "<p>" + "".join(
        f"<a href='{hrefs[i % len(hrefs)]}'>l</a>" for i in range(LINK_AMPLIFICATION_LINKS)
    ) + "</p>"


def _long_delimiter_runs() -> str:
    parts = []
    for char in ("*", "_", "`", "\\", "[", "<", "&lt;", "]", "#", "~", "|", "!"):
        run = char * LONG_RUN
        parts.append(f"<p>{run}</p><p><b>{run}</b></p><p><i>x{run}y</i></p><p><code>{run}</code></p>")
    parts.append("<p>" + "*_" * LONG_RUN + "</p><pre>" + "`" * LONG_RUN + "</pre>")
    parts.append("<table><tr><td>" + "\\|" * LONG_RUN + "</td></tr></table>")
    return "".join(parts)


def _unicode_whitespace_runs() -> str:
    run = UNICODE_SPACES * 50
    return (
        f"<p>{run}lead and trail{run}</p><p>a{run}b</p><p><b>{run}bold{run}</b></p>"
        f"<h2>{run}heading{run}</h2><ul><li>{run}item{run}</li></ul>"
        f"<table><tr><td>{run}cell{run}</td><td>{run}</td></tr></table>"
        f"<p><a href='/w'>{run}link{run}</a></p><blockquote>{run}</blockquote><p>{run}</p>"
        + "".join(f"<p>single{space}separator{space}{ord(space):04x}</p>" for space in UNICODE_SPACES)
    )


def _emoji_and_astral() -> str:
    return (
        f"<h1>{ASTRAL_TEXT}</h1><p>{ASTRAL_TEXT}</p><p><b>{ASTRAL_TEXT}</b> <i>\U0001f600</i>x</p>"
        f"<ul><li>{ASTRAL_TEXT}</li></ul><table><tr><td>{ASTRAL_TEXT}</td></tr></table>"
        f"<p><a href='/\U0001f600'>{ASTRAL_TEXT}</a></p><pre>{ASTRAL_TEXT}</pre>"
        + "<p>" + "\U0001f600" * LONG_RUN + "</p>"
    )


def _code_and_pre() -> str:
    return (
        "<pre>```\nfence inside\n````\n</pre><pre>\n\n\n</pre><pre></pre><p><code>   </code></p>"
        "<p><code>`edge`</code> <code>a``b</code></p><ul><li><blockquote><pre>nested\n  pre</pre></blockquote></li></ul>"
        "<table><tr><td><pre>cell\npre</pre></td><td><code>|</code></td></tr></table>"
        "<pre><b>bold</b> in <a href='/p'>pre</a>\r\nCRLF\rCR</pre><h2><code>code heading</code></h2>"
    )


def _forms() -> str:
    options = "".join(f"<option>opt {i}</option>" for i in range(500))
    return (
        f"<form action='/submit' method='post'><select name='s'>{options}</select>"
        "<input placeholder='[bracket]'><input type='hidden' value='h'><button>*go*</button>"
        "<textarea name='t'># not heading</textarea></form><form></form><form action='java&#115;cript:x'><input name='q'></form>"
    )


def _headings() -> str:
    return (
        "<h1>trailing ###</h1><h2>a<br>b</h2><h3></h3><h4>   </h4><h5># hash</h5><h6>- dash</h6>"
        "<h1><img src='/i.png' alt='only image'></h1><h2><a href='/h'>linked</a> ##</h2>"
        "<h3><ul><li>list in heading</li></ul></h3><h1><table><tr><td>table in heading</td></tr></table></h1>"
    )


def _hidden_content_in_tables() -> str:
    return (
        "<table><tr><td>shown</td><td style='display:none'>hidden cell</td><td hidden>hidden attr</td></tr>"
        "<tr style='visibility:hidden'><td>hidden row</td></tr><tr><td aria-hidden='true'>aria</td>"
        "<td><span style='display: none !important'>x</span>visible</td></tr></table>"
        "<table><tr><td><div hidden id='S:1'>streamed</div></td></tr></table>"
    )


def _document_shell_noise() -> str:
    return (
        "<?xml version='1.0'?><!DOCTYPE html><html><head><title>t</title><base href='https://evil.example/'>"
        "<style>p{}</style></head><body><![CDATA[cdata]]><?pi x?><!-- comment --><p>body</p>"
        "<template><p>template</p></template><noscript><p>noscript</p></noscript><svg><text>svg</text></svg>"
        "<math><mi>x</mi></math><p>after</p></body></html><p>after html</p>"
    )
