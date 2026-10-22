"""Rendered text of a document's chunks, for locating highlight quotes the way the viewers display them."""
from __future__ import annotations

import html
import re
from bisect import bisect_right

from markdown_it import MarkdownIt

from .types import ChunkRecord

CONTEXT_CHARS = 24
MAX_OCCURRENCES = 500
PROBE_WORDS = 2
# Unspaced scripts (CJK) form one long run; shorter pieces are unlikely to straddle inline markup.
MAX_PROBE_CHARS = 8

# The viewers' markdown-it setup: CommonMark with html and linkify off, plus GFM tables and strikethrough.
_MARKDOWN = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable(["table", "strikethrough"])
_TEXT_TOKENS = {"text", "code_inline"}
_CODE_BLOCK_TOKENS = {"fence", "code_block"}
# Viewers and Markdown disagree on block separators, never on the visible characters, so matching ignores whitespace.
_INVISIBLE_RE = re.compile(r"[\s\u200b\ufeff]+")
_NON_ALNUM_RE = re.compile(r"[\W_]+")
_UNESCAPED_ENTITY_RE = re.compile(r"(?<!\\)&#?\w+;")


class ChunkTextIndex:
    """Chunk text rendered lazily, once per highlight recomputation, and shared by every highlight in it."""

    def __init__(self, chunks: list[ChunkRecord]) -> None:
        self.chunks = chunks
        self._rendered: dict[int, str] = {}
        self._overlaps: dict[int, int] = {}
        self._probe_streams: list[tuple[str, list[int]]] = []

    def chunks_quoting(self, quote: str, prefix: str | None, suffix: str | None) -> list[ChunkRecord]:
        """Chunks spanned by the best-in-context occurrence of `quote`; empty when it occurs nowhere."""
        target = _compact(quote)
        if not target:
            return []
        context = (_compact(prefix or "")[-CONTEXT_CHARS:], _compact(suffix or "")[:CONTEXT_CHARS])
        best: tuple[tuple[int, int], list[int]] | None = None
        for index in self._candidate_indexes(quote):
            for score, spanned in self._occurrences_around(index, target, context):
                rank = (score, -spanned[0])
                if best is None or rank > best[0]:
                    best = (rank, spanned)
        return [self.chunks[i] for i in best[1]] if best else []

    def _candidate_indexes(self, quote: str) -> list[int]:
        """Chunks whose raw letters contain one of the quote's longest words: a cheap filter before rendering."""
        probes = _probe_words(quote)
        if not probes:
            return list(range(len(self.chunks)))
        found: set[int] = set()
        for stream, starts in self._built_probe_streams():
            for probe in probes:
                found.update(_chunks_containing(stream, starts, probe))
        return sorted(found)

    def _built_probe_streams(self) -> list[tuple[str, list[int]]]:
        """Raw chunk letters with entities decoded, and as written (inside code spans they stay literal)."""
        if not self._probe_streams:
            decoded = [_loose(_UNESCAPED_ENTITY_RE.sub(_decode_entity, c.source_content)) for c in self.chunks]
            literal = [_loose(c.source_content) for c in self.chunks]
            self._probe_streams = [_joined_with_starts(decoded), _joined_with_starts(literal)]
        return self._probe_streams

    def _occurrences_around(
        self, index: int, target: str, context: tuple[str, str],
    ) -> list[tuple[int, list[int]]]:
        window, spans = self._window(index, len(target) + CONTEXT_CHARS)
        own_start, own_end = spans[index]
        found: list[tuple[int, list[int]]] = []
        position = window.find(target, max(0, own_start - len(target) + 1))
        while position != -1 and position < own_end and len(found) < MAX_OCCURRENCES:
            end = position + len(target)
            found.append((_context_score(window, position, end, context), _spanned(spans, position, end)))
            position = window.find(target, position + 1)
        return found

    def _window(self, index: int, reach: int) -> tuple[str, dict[int, tuple[int, int]]]:
        """Rendered text around chunk `index`, extended through neighbours by `reach` chars each way, with chunk spans."""
        window = self._rendered_at(index)
        spans = {index: (0, len(window))}
        low = high = index
        while spans[index][0] < reach and low > 0:
            low -= 1
            piece = self._rendered_at(low)
            shift = len(piece) - self._overlap_after(low)
            spans = {j: (start + shift, end + shift) for j, (start, end) in spans.items()}
            spans[low] = (0, len(piece))
            window = piece + window[self._overlap_after(low):]
        while len(window) - spans[index][1] < reach and high < len(self.chunks) - 1:
            overlap = self._overlap_after(high)
            high += 1
            piece = self._rendered_at(high)
            start = len(window) - overlap
            spans[high] = (start, start + len(piece))
            window += piece[overlap:]
        return window, spans

    def _rendered_at(self, index: int) -> str:
        if index not in self._rendered:
            self._rendered[index] = _compact(_render(self.chunks[index].source_content))
        return self._rendered[index]

    def _overlap_after(self, index: int) -> int:
        """Rendered chars that chunk `index + 1` repeats from chunk `index` (the chunker's overlap), 0 if unverifiable."""
        if index not in self._overlaps:
            self._overlaps[index] = self._measure_overlap(index)
        return self._overlaps[index]

    def _measure_overlap(self, index: int) -> int:
        first, second = self.chunks[index], self.chunks[index + 1]
        if first.start_char is None or second.start_char is None:
            return 0
        shared_chars = first.start_char + len(first.source_content) - second.start_char
        if shared_chars <= 0 or shared_chars > len(first.source_content):
            return 0
        shared = first.source_content[-shared_chars:]
        if not second.source_content.startswith(shared):
            return 0
        rendered = _compact(_render(shared))
        if self._rendered_at(index).endswith(rendered) and self._rendered_at(index + 1).startswith(rendered):
            return len(rendered)
        return 0


def _render(markdown: str) -> str:
    """Text the viewers display: inline text and code verbatim, no syntax, no image alt."""
    parts: list[str] = []
    for token in _MARKDOWN.parse(markdown):
        if token.type == "inline":
            parts.extend(child.content for child in token.children or [] if child.type in _TEXT_TOKENS)
        elif token.type in _CODE_BLOCK_TOKENS:
            parts.append(token.content)
    return "".join(parts)


def _compact(text: str) -> str:
    return _INVISIBLE_RE.sub("", text)


def _loose(text: str) -> str:
    return _NON_ALNUM_RE.sub("", text)


def _probe_words(quote: str) -> list[str]:
    """The quote's longest letter/digit runs, which Markdown syntax almost never splits."""
    pieces = [
        word[i:i + MAX_PROBE_CHARS]
        for word in _NON_ALNUM_RE.split(quote)
        for i in range(0, len(word), MAX_PROBE_CHARS)
    ]
    return sorted((piece for piece in pieces if piece), key=len, reverse=True)[:PROBE_WORDS]


def _decode_entity(match: re.Match[str]) -> str:
    return html.unescape(match.group())


def _joined_with_starts(parts: list[str]) -> tuple[str, list[int]]:
    starts: list[int] = []
    total = 0
    for part in parts:
        starts.append(total)
        total += len(part)
    return "".join(parts), starts


def _chunks_containing(stream: str, starts: list[int], probe: str) -> list[int]:
    """Indexes of chunks where `probe` starts, scanning each chunk at most once."""
    found: list[int] = []
    position = stream.find(probe)
    while position != -1:
        chunk = bisect_right(starts, position) - 1
        found.append(chunk)
        if chunk + 1 >= len(starts):
            break
        position = stream.find(probe, starts[chunk + 1])
    return found


def _context_score(window: str, start: int, end: int, context: tuple[str, str]) -> int:
    prefix, suffix = context
    return (bool(prefix) and window.endswith(prefix, 0, start)) + (bool(suffix) and window.startswith(suffix, end))


def _spanned(spans: dict[int, tuple[int, int]], start: int, end: int) -> list[int]:
    """One chunk holding the whole match if any (overlaps repeat text), else every chunk the match crosses."""
    holding = sorted(j for j, (s, e) in spans.items() if s <= start and end <= e)
    if holding:
        return holding[:1]
    return sorted(j for j, (s, e) in spans.items() if s < end and start < e)
