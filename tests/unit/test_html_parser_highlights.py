"""Unit tests for html_parser plaintext extraction + highlight locator (V2A).

The plaintext output has to match what TipTap's `doc.textBetween` would
produce on the parsed markdown — markdown punctuation removed, block
separation preserved, inline spans flattened.
"""

from html_parser import Parser
from html_parser.models import TextAnchor


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
