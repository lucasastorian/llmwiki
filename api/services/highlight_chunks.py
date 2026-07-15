"""Mapping + builder helpers for materializing highlights onto document_chunks.

A chunk's `content` column carries `source_content` plus an optional
materialized footnote block of highlights/comments that touch this chunk.
The highlight CRUD service methods call into the helpers here, in the same
transaction as the canonical `documents.highlights` write, to keep the
denormalized chunk fields consistent.

See `docs/highlights-in-search-spec.md` for the full design.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass
class ChunkRecord:
    """Minimal chunk shape needed for highlight → chunk mapping.

    Hydrated from either the Postgres `document_chunks` row or its SQLite
    counterpart. `start_char` may be None for chunks created before the
    `_enforce_max_chars` fix; treat None as 0.
    """
    id: str
    chunk_index: int
    source_content: str
    page: int | None
    start_char: int | None


_WS_RE = re.compile(r"\s+")


def _normalize_ws(value: str) -> str:
    return _WS_RE.sub(" ", value).strip()


def chunks_for_highlight(h: dict, chunks: list[ChunkRecord]) -> list[ChunkRecord]:
    """Return the chunks of `chunks` that this highlight touches.

    Dispatches by anchor type. Empty list = no chunks; that's a real result
    (e.g. orphaned highlight from re-OCR, doc with no chunks yet) and
    caller should leave existing chunks untouched.
    """
    if h.get("pdfAnchor"):
        return _chunks_for_pdf_highlight(h, chunks)
    if h.get("textAnchor"):
        return _chunks_for_text_highlight(h, chunks)
    if h.get("anchor"):
        return _chunks_by_text_match(h["anchor"].get("textContent"), chunks)
    return []


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
            # An exact quote is stronger than offsets produced by a different
            # PDF text extractor. Prefer the tightest containing chunk.
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
    # Legacy/unalignable anchors remain page-level, but keep the projection
    # bounded to one chunk so one note cannot pollute every search chunk on a
    # long page. The canonical sidecar still preserves the annotation.
    return candidates[:1]


def _chunks_for_text_highlight(h: dict, chunks: list[ChunkRecord]) -> list[ChunkRecord]:
    anchor = h.get("textAnchor") or {}
    ts = anchor.get("textStart")
    te = anchor.get("textEnd")
    if ts is None or te is None:
        # No usable range; try plain text match.
        return _chunks_by_text_match(anchor.get("textContent"), chunks)

    quoted = _normalize_ws(anchor.get("textContent") or "")
    scored: list[tuple[int, ChunkRecord]] = []
    for c in chunks:
        cs = c.start_char or 0
        ce = cs + len(c.source_content)
        overlap = max(0, min(te, ce) - max(ts, cs))
        if overlap <= 0:
            continue
        score = overlap
        if quoted and quoted in _normalize_ws(c.source_content):
            # Exact text match wins decisively over a coincidental overlap.
            score += 1_000_000
        scored.append((score, c))

    if not scored:
        return _chunks_by_text_match(quoted, chunks)
    scored.sort(key=lambda t: t[0], reverse=True)
    top_score = scored[0][0]
    # Single-chunk bias unless ≥2 candidates have comparable overlap.
    return [c for s, c in scored if s >= top_score / 2]


def _chunks_by_text_match(text: str | None, chunks: list[ChunkRecord]) -> list[ChunkRecord]:
    target = _normalize_ws(text or "")
    if not target:
        return []
    matches = [c for c in chunks if target in _normalize_ws(c.source_content)]
    # Prefer the smallest chunk that contains the text (tightest match).
    matches.sort(key=lambda c: len(c.source_content))
    return matches[:1]


def assign_highlights_to_chunks(
    chunks: list[ChunkRecord],
    highlights: list[dict],
) -> dict[str, list[dict]]:
    """Build a chunk_id → list of highlights touching that chunk.

    Single O(highlights × chunks) pass; callers index by chunk_id to look up
    what each chunk's annotations_text should contain.
    """
    out: dict[str, list[dict]] = {}
    for h in highlights:
        for c in chunks_for_highlight(h, chunks):
            out.setdefault(c.id, []).append(h)
    return out


def all_affected_chunks(
    chunks: list[ChunkRecord],
    old_highlights: list[dict],
    new_highlights: list[dict],
) -> set[str]:
    """Return chunks touched by EITHER the old or new highlight set.

    Using the union catches deletions: a removed highlight was in `old` but
    not in `new`; without revisiting its chunk we'd leave stale annotations.
    """
    old_map = assign_highlights_to_chunks(chunks, old_highlights)
    new_map = assign_highlights_to_chunks(chunks, new_highlights)
    return set(old_map.keys()) | set(new_map.keys())


def _sorted_for_render(highlights: list[dict]) -> list[dict]:
    """Stable sort by (createdAt, id) so renders are deterministic."""
    return sorted(
        highlights,
        key=lambda h: (h.get("createdAt") or "", h.get("id") or ""),
    )


def _escape_for_quote(text: str) -> str:
    # Quote with straight double quotes; escape internal double quotes.
    return text.replace("\\", "\\\\").replace("\"", "\\\"")


def build_annotations_text(highlights: list[dict]) -> str | None:
    """Render the materialized footnote-body block for a chunk.

    Format (one line per highlight):
        [^user-N]: User highlighted "{quoted text}" — user note: {comment}

    The "user note: ..." suffix is omitted when no comment exists.
    IDs are sequential per chunk, 1-indexed. Returns None when the list is
    empty so the caller can write a NULL into `annotations_text`.
    """
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
    """Concatenate source + annotations into the chunk's materialized
    `content` column. Empty annotations → unchanged source."""
    if not annotations_text:
        return source_content
    return f"{source_content}\n\n{annotations_text}"


def iter_chunks_with_annotations(
    chunks: list[ChunkRecord],
    affected_ids: Iterable[str],
    new_highlights: list[dict],
) -> Iterable[tuple[ChunkRecord, str | None, bool, str]]:
    """For each affected chunk, yield (chunk, annotations_text, has_highlight, new_content).

    Caller writes these four fields in a single UPDATE per chunk."""
    affected = set(affected_ids)
    if not affected:
        return
    assignments = assign_highlights_to_chunks(chunks, new_highlights)
    for chunk in chunks:
        if chunk.id not in affected:
            continue
        relevant = assignments.get(chunk.id, [])
        annotations_text = build_annotations_text(relevant)
        has_highlight = annotations_text is not None
        new_content = build_chunk_content(chunk.source_content, annotations_text)
        yield chunk, annotations_text, has_highlight, new_content
