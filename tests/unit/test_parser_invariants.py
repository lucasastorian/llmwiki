"""Properties every production parse must hold, over the frozen real pages and hand-written hostile HTML.

Each document is parsed twice in a resource-limited child process (tests/support/isolated_parse.py),
so a hang, OOM or native stack crash fails that document's tests instead of killing the runner.
"""
from __future__ import annotations

import random
import re
from collections import Counter
from functools import cache

import pytest
from html_parser import Parser
from markdown_it import MarkdownIt
from markdown_it.token import Token

from tests.support.adversarial_html import adversarial_cases
from tests.support.isolated_parse import run_isolated
from tests.support.real_pages import load_pages
from tests.support.types import HtmlDocument, IsolatedRun, ParseOutcome

INTERNAL_MARKER_CHARS = re.compile("[\x00-\x08]")
# Escaping at most doubles a character; anything beyond that must be paid for from the parser's output budget.
MARKDOWN_GROWTH_FACTOR = 2
MARKDOWN_OUTPUT_BUDGET = 20_000_000
SPANS_PER_DOCUMENT = 20
SPAN_ATTEMPTS = 400
MIN_SPAN_CHARS = 4
MAX_SPAN_CHARS = 120
CONTEXT_CHARS = 32
# Each locate rescans the whole plaintext, so huge documents get fewer sampled spans (but always at least one).
HIGHLIGHT_SCAN_BUDGET_CHARS = 2_000_000
ZERO_WIDTH = "​﻿"
_whitespace_run = re.compile(r"\s+")

DOCUMENTS: dict[str, HtmlDocument] = {
    **{f"real:{page['id']}": HtmlDocument(html=page["html"], url=page["url"]) for page in load_pages()},
    **{f"adversarial:{name}": case for name, case in adversarial_cases().items()},
}

# (invariant, document id) -> exact current failure; strict, so a fix forces the entry's removal.
KNOWN_FAILURES: dict[tuple[str, str], str] = {}

_viewer_markdown = MarkdownIt("js-default", {"html": False})


def _documents(invariant: str) -> list:
    return [
        pytest.param(
            doc_id,
            id=doc_id,
            marks=[pytest.mark.xfail(strict=True, reason=KNOWN_FAILURES[(invariant, doc_id)])]
            if (invariant, doc_id) in KNOWN_FAILURES else [],
        )
        for doc_id in DOCUMENTS
    ]


@pytest.mark.parametrize("doc_id", [doc_id for doc_id in DOCUMENTS if doc_id.startswith("adversarial:")])
def test_adversarial_case_meets_its_expected_outcome(doc_id: str) -> None:
    document = DOCUMENTS[doc_id]
    outcome = _outcomes(doc_id)[0]
    if document.expects_limit_error:
        assert outcome.is_limit_error, f"expected the typed limit error, got {outcome.error_type or 'success'}"
        return
    assert document.sentinels, "an adversarial case must name the visible text a correct parse keeps"
    assert outcome.error_type is None, f"raised {outcome.error_type}: {outcome.error_message}"
    for sentinel in document.sentinels:
        assert sentinel in outcome.plaintext, f"visible text {sentinel!r} is missing from the plaintext"
    for secret in document.hidden:
        assert secret not in outcome.plaintext and secret not in outcome.markdown, f"hidden text {secret!r} rendered"


@pytest.mark.parametrize("doc_id", _documents("only_limit_error"))
def test_only_the_typed_limit_error_escapes(doc_id: str) -> None:
    for outcome in _outcomes(doc_id):
        assert outcome.error_type is None or outcome.is_limit_error, (
            f"raised {outcome.error_type}: {outcome.error_message}"
        )


@pytest.mark.parametrize("doc_id", _documents("no_internal_markers"))
def test_output_has_no_internal_marker_chars(doc_id: str) -> None:
    outcome = _rendered(doc_id)
    if outcome is None:
        return
    for field, text in (("markdown", outcome.markdown), ("plaintext", outcome.plaintext)):
        leaked = INTERNAL_MARKER_CHARS.search(text)
        assert leaked is None, f"{field} leaks {leaked.group()!r} near {text[max(0, leaked.start() - 40):leaked.end() + 40]!r}"


@pytest.mark.parametrize("doc_id", _documents("utf8_encodable"))
def test_output_is_utf8_encodable(doc_id: str) -> None:
    outcome = _rendered(doc_id)
    if outcome is None:
        return
    outcome.markdown.encode("utf-8")
    outcome.plaintext.encode("utf-8")


@pytest.mark.parametrize("doc_id", _documents("table_cells"))
def test_markdown_table_rows_are_plaintext_lines(doc_id: str) -> None:
    outcome = _rendered(doc_id)
    if outcome is None:
        return
    markdown_rows = Counter(_markdown_table_rows(outcome.markdown))
    plaintext_lines = Counter(_collapse(line) for line in outcome.plaintext.split("\n"))
    missing = markdown_rows - plaintext_lines
    assert not missing, f"markdown table rows absent from plaintext: {list(missing.elements())[:5]}"


@pytest.mark.parametrize("doc_id", _documents("bounded_growth"))
def test_markdown_growth_is_bounded(doc_id: str) -> None:
    outcome = _rendered(doc_id)
    if outcome is None:
        return
    bound = MARKDOWN_GROWTH_FACTOR * len(DOCUMENTS[doc_id].html) + MARKDOWN_OUTPUT_BUDGET
    assert len(outcome.markdown) <= bound


@pytest.mark.parametrize("doc_id", _documents("deterministic"))
def test_parse_is_deterministic(doc_id: str) -> None:
    first, second = _outcomes(doc_id)
    assert first == second


@pytest.mark.parametrize("doc_id", _documents("highlight_round_trip"))
def test_highlight_anchors_slice_their_span(doc_id: str) -> None:
    outcome = _rendered(doc_id)
    if outcome is None:
        return
    plaintext = outcome.plaintext
    spans = _sample_unique_spans(plaintext, doc_id) or _leading_span(plaintext)
    assert spans or not _collapse(plaintext), "no selectable span sampled from a non-empty plaintext"
    mapped = Parser.map_highlights(plaintext, [_highlight_payload(plaintext, start, end) for start, end in spans])
    for (start, end), highlight in zip(spans, mapped, strict=True):
        anchor = highlight.text_anchor
        span = plaintext[start:end]
        assert anchor is not None, f"span {span!r} at {start} was not located"
        assert (anchor.text_start, anchor.text_end) == (_utf16_len(plaintext[:start]), _utf16_len(plaintext[:end])), (
            f"span {span!r} anchored at {anchor.text_start}:{anchor.text_end}"
        )
        assert _utf16_slice(plaintext, anchor.text_start, anchor.text_end) == span
        assert anchor.text_content == span


def _outcomes(doc_id: str) -> list[ParseOutcome]:
    run = _run(doc_id)
    assert run.failure is None, run.failure
    return run.outcomes


@cache
def _run(doc_id: str) -> IsolatedRun:
    """One child per document, shared by every invariant, so a hang costs one timeout rather than one per test."""
    document = DOCUMENTS[doc_id]
    return run_isolated(document.html, document.url)


def _rendered(doc_id: str) -> ParseOutcome | None:
    """The first parse's output, or None when it raised (judged by the error-type test alone)."""
    outcome = _outcomes(doc_id)[0]
    return None if outcome.error_type else outcome


def _markdown_table_rows(markdown: str) -> list[str]:
    """Each table row's rendered cell texts, space-joined the way the plaintext writes a row."""
    rows: list[str] = []
    cells: list[str] | None = None
    for token in _viewer_markdown.parse(markdown):
        if token.type == "tr_open":
            cells = []
        elif token.type == "inline" and cells is not None:
            cells.append(_inline_text(token))
        elif token.type == "tr_close" and cells is not None:
            rows.append(_collapse(" ".join(cells)))
            cells = None
    return [row for row in rows if row]


def _inline_text(token: Token) -> str:
    parts: list[str] = []
    for child in token.children or []:
        if child.type in {"text", "code_inline"}:
            parts.append(child.content)
        elif child.type in {"softbreak", "hardbreak", "image"}:
            parts.append(" ")
    return "".join(parts)


def _collapse(text: str) -> str:
    return _whitespace_run.sub(" ", text.translate({ord(char): None for char in ZERO_WIDTH})).strip()


def _sample_unique_spans(plaintext: str, seed: str) -> list[tuple[int, int]]:
    """Spans a user could select (no edge whitespace) that occur once even after collapsing whitespace."""
    wanted = max(1, min(SPANS_PER_DOCUMENT, HIGHLIGHT_SCAN_BUDGET_CHARS // max(1, len(plaintext))))
    collapsed = _collapse(plaintext)
    rng = random.Random(seed)
    spans: list[tuple[int, int]] = []
    for _ in range(SPAN_ATTEMPTS):
        if len(spans) >= wanted or len(plaintext) < MIN_SPAN_CHARS:
            break
        start = rng.randrange(len(plaintext) - MIN_SPAN_CHARS + 1)
        end = min(len(plaintext), start + rng.randint(MIN_SPAN_CHARS, MAX_SPAN_CHARS))
        span = plaintext[start:end]
        if _is_selectable(span) and collapsed.count(_collapse(span)) == 1:
            spans.append((start, end))
    return spans


def _leading_span(plaintext: str) -> list[tuple[int, int]]:
    """The first selectable text, for documents too repetitive to sample a unique span; context picks occurrence one."""
    start = next((i for i, char in enumerate(plaintext) if not (char.isspace() or char in ZERO_WIDTH)), None)
    if start is None:
        return []
    end = min(len(plaintext), start + MAX_SPAN_CHARS)
    while plaintext[end - 1].isspace() or plaintext[end - 1] in ZERO_WIDTH:
        end -= 1
    return [(start, end)]


def _is_selectable(span: str) -> bool:
    return not any(edge.isspace() or edge in ZERO_WIDTH for edge in (span[0], span[-1]))


def _highlight_payload(plaintext: str, start: int, end: int) -> dict:
    return {
        "anchor": {
            "textContent": plaintext[start:end],
            "prefix": plaintext[max(0, start - CONTEXT_CHARS):start],
            "suffix": plaintext[end:end + CONTEXT_CHARS],
        },
    }


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _utf16_slice(text: str, start: int, end: int) -> str:
    return text.encode("utf-16-le")[start * 2:end * 2].decode("utf-16-le")
