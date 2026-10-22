"""Materialize highlights into chunk `content` as a footnote block appended to `source_content`."""
from __future__ import annotations

import re
from collections.abc import Iterable

from .chunk_text_index import ChunkTextIndex
from .types import ChunkRecord

_WS_RE = re.compile(r"\s+")


def _normalize_ws(value: str) -> str:
    return _WS_RE.sub(" ", value).strip()


def chunks_for_highlight(h: dict, index: ChunkTextIndex) -> list[ChunkRecord]:
    """Chunks this highlight touches; empty (orphaned or unchunked) means leave existing chunks alone."""
    if h.get("pdfAnchor"):
        return _chunks_for_pdf_highlight(h, index.chunks)
    anchor = h.get("textAnchor") or h.get("anchor")
    if not isinstance(anchor, dict):
        return []
    # Text anchor offsets count plaintext UTF-16 units, not chunk Markdown chars, so only the quote and context locate it.
    return index.chunks_quoting(anchor.get("textContent") or "", anchor.get("prefix"), anchor.get("suffix"))


def _chunks_for_pdf_highlight(h: dict, chunks: list[ChunkRecord]) -> list[ChunkRecord]:
    pdf = h.get("pdfAnchor") or {}
    page = pdf.get("page")
    if page is None:
        return []
    candidates = [c for c in chunks if c.page == page]
    if not candidates:
        return []
    target = _normalize_ws(pdf.get("textContent") or "")
    if target:
        exact = [c for c in candidates if target in _normalize_ws(c.source_content)]
        if exact:
            # An exact quote beats offsets produced by a different PDF text extractor.
            exact.sort(key=lambda c: len(c.source_content))
            return exact[:1]
    ts = pdf.get("textStart")
    te = pdf.get("textEnd")
    if ts is not None and te is not None:
        scored: list[tuple[int, ChunkRecord]] = []
        for c in candidates:
            cs = c.start_char or 0
            ce = cs + len(c.source_content)
            overlap = max(0, min(te, ce) - max(ts, cs))
            if overlap > 0:
                scored.append((overlap, c))
        if scored:
            scored.sort(key=lambda item: item[0], reverse=True)
            top_score = scored[0][0]
            return [c for score, c in scored if score >= top_score / 2]
    # Unalignable anchors project onto one chunk so a note can't pollute every chunk of a long page.
    return candidates[:1]


def assign_highlights_to_chunks(
    index: ChunkTextIndex,
    highlights: list[dict],
) -> dict[str, list[dict]]:
    """Map chunk_id → the highlights touching that chunk."""
    out: dict[str, list[dict]] = {}
    for h in highlights:
        for c in chunks_for_highlight(h, index):
            out.setdefault(c.id, []).append(h)
    return out


def all_affected_chunks(
    index: ChunkTextIndex,
    old_highlights: list[dict],
    new_highlights: list[dict],
) -> set[str]:
    """Chunk ids touched by old ∪ new highlights; the union revisits chunks whose highlight was deleted."""
    old_map = assign_highlights_to_chunks(index, old_highlights)
    new_map = assign_highlights_to_chunks(index, new_highlights)
    return set(old_map.keys()) | set(new_map.keys())


def _sorted_for_render(highlights: list[dict]) -> list[dict]:
    """Stable sort by (createdAt, id) so renders are deterministic."""
    return sorted(
        highlights,
        key=lambda h: (h.get("createdAt") or "", h.get("id") or ""),
    )


def _escape_for_quote(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\"", "\\\"")


def build_annotations_text(highlights: list[dict]) -> str | None:
    """Render one `[^user-N]: User highlighted "..." — user note: ...` line per highlight, or None."""
    if not highlights:
        return None
    lines: list[str] = []
    for i, h in enumerate(_sorted_for_render(highlights), start=1):
        quoted = _extract_quoted_text(h)
        if not quoted:
            continue
        comment = (h.get("comment") or "").strip()
        line = f'[^user-{i}]: User highlighted "{_escape_for_quote(quoted)}"'
        if comment:
            line += f" — user note: {comment}"
        lines.append(line)
    if not lines:
        return None
    return "\n".join(lines)


def _extract_quoted_text(h: dict) -> str:
    """Pull the textContent from whichever anchor type carries it."""
    for key in ("pdfAnchor", "textAnchor", "anchor"):
        anchor = h.get(key)
        if not isinstance(anchor, dict):
            continue
        text = anchor.get("textContent")
        if text:
            return text
    return ""


def build_chunk_content(source_content: str, annotations_text: str | None) -> str:
    """Append the annotations block, if any, to the source content."""
    if not annotations_text:
        return source_content
    return f"{source_content}\n\n{annotations_text}"


def iter_chunks_with_annotations(
    index: ChunkTextIndex,
    affected_ids: Iterable[str],
    new_highlights: list[dict],
) -> Iterable[tuple[ChunkRecord, str | None, bool, str]]:
    """Yield (chunk, annotations_text, has_highlight, new_content) for each affected chunk."""
    affected = set(affected_ids)
    if not affected:
        return
    assignments = assign_highlights_to_chunks(index, new_highlights)
    for chunk in index.chunks:
        if chunk.id not in affected:
            continue
        relevant = assignments.get(chunk.id, [])
        annotations_text = build_annotations_text(relevant)
        has_highlight = annotations_text is not None
        new_content = build_chunk_content(chunk.source_content, annotations_text)
        yield chunk, annotations_text, has_highlight, new_content
