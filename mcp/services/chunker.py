"""Text chunker for wiki pages + notes created via MCP.

Mirrors api/services/chunker.py so MCP-created content shows up in
keyword search alongside API-created content. Splits content into
~512 token chunks with ~128 token overlap, tracking markdown headers
for breadcrumb context. Persists into `document_chunks` (Postgres via
asyncpg, SQLite via aiosqlite — chunks_fts is kept in sync by triggers
in the local schema).
"""

import json
import logging
import re
from dataclasses import dataclass

import aiosqlite
import asyncpg

logger = logging.getLogger(__name__)

CHUNK_SIZE = 512
CHUNK_OVERLAP = 128
MIN_CHUNK_TOKENS = 32
MAX_CHUNK_CHARS = 10_000  # matches DB constraint chk_chunks_content_length

SENTENCE_RE = re.compile(r"(?<=[.!?。！？])\s+")
HEADER_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass
class Chunk:
    index: int
    content: str
    page: int | None
    start_char: int
    token_count: int
    header_breadcrumb: str = ""


def chunk_text(
    content: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
    page: int | None = None,
) -> list[Chunk]:
    if not content or not content.strip():
        return []

    paragraphs = _split_paragraphs(content)
    header_stack: list[tuple[int, str]] = []
    chunks: list[Chunk] = []
    current_blocks: list[str] = []
    current_tokens = 0
    current_start = 0
    char_pos = 0

    for para in paragraphs:
        para_tokens = _estimate_tokens(para)

        m = HEADER_RE.match(para)
        if m:
            level = len(m.group(1))
            heading = m.group(2).strip()
            header_stack = [(l, t) for l, t in header_stack if l < level]
            header_stack.append((level, heading))

        if current_tokens + para_tokens > chunk_size and current_blocks:
            text = "\n\n".join(current_blocks)
            if _estimate_tokens(text) >= MIN_CHUNK_TOKENS:
                breadcrumb = " > ".join(t for _, t in header_stack)
                chunks.append(Chunk(
                    index=len(chunks),
                    content=text,
                    page=page,
                    start_char=current_start,
                    token_count=_estimate_tokens(text),
                    header_breadcrumb=breadcrumb,
                ))
            overlap_blocks, overlap_tokens = _get_overlap(current_blocks, overlap)
            current_blocks = overlap_blocks
            current_tokens = overlap_tokens
            current_start = char_pos - sum(len(b) + 2 for b in overlap_blocks)

        current_blocks.append(para)
        current_tokens += para_tokens
        char_pos += len(para) + 2

    if current_blocks:
        text = "\n\n".join(current_blocks)
        if _estimate_tokens(text) >= MIN_CHUNK_TOKENS:
            breadcrumb = " > ".join(t for _, t in header_stack)
            chunks.append(Chunk(
                index=len(chunks),
                content=text,
                page=page,
                start_char=current_start,
                token_count=_estimate_tokens(text),
                header_breadcrumb=breadcrumb,
            ))

    return _enforce_max_chars(chunks)


def _enforce_max_chars(chunks: list[Chunk]) -> list[Chunk]:
    """Split any chunk whose content exceeds MAX_CHUNK_CHARS.

    Paragraph-based chunking emits one chunk per paragraph when the paragraph
    is bigger than CHUNK_SIZE. CJK text and long code blocks routinely blow
    past the 10k-char DB constraint. Split on sentence boundaries; hard-slice
    only if no break is available.
    """
    if not any(len(c.content) > MAX_CHUNK_CHARS for c in chunks):
        return chunks

    result: list[Chunk] = []
    for c in chunks:
        if len(c.content) <= MAX_CHUNK_CHARS:
            result.append(Chunk(
                index=len(result), content=c.content, page=c.page,
                start_char=c.start_char, token_count=c.token_count,
                header_breadcrumb=c.header_breadcrumb,
            ))
            continue
        for piece in _split_oversized(c.content):
            result.append(Chunk(
                index=len(result), content=piece, page=c.page,
                start_char=c.start_char, token_count=_estimate_tokens(piece),
                header_breadcrumb=c.header_breadcrumb,
            ))
    return result


def _split_oversized(text: str) -> list[str]:
    parts = SENTENCE_RE.split(text)
    pieces: list[str] = []
    current = ""
    for part in parts:
        candidate = (current + " " + part).strip() if current else part
        if len(candidate) <= MAX_CHUNK_CHARS:
            current = candidate
        else:
            if current:
                pieces.append(current)
            if len(part) <= MAX_CHUNK_CHARS:
                current = part
            else:
                for i in range(0, len(part), MAX_CHUNK_CHARS):
                    pieces.append(part[i:i + MAX_CHUNK_CHARS])
                current = ""
    if current:
        pieces.append(current)
    return pieces


async def store_chunks_pg(
    conn: asyncpg.Connection,
    document_id: str,
    user_id: str,
    knowledge_base_id: str,
    chunks: list[Chunk],
) -> None:
    await conn.execute("DELETE FROM document_chunks WHERE document_id = $1", document_id)
    if not chunks:
        return
    await conn.executemany(
        "INSERT INTO document_chunks "
        "(document_id, user_id, knowledge_base_id, chunk_index, content, page, start_char, "
        " token_count, header_breadcrumb) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
        [
            (document_id, user_id, knowledge_base_id, c.index, c.content, c.page,
             c.start_char, c.token_count, c.header_breadcrumb)
            for c in chunks
        ],
    )


async def store_chunks_sqlite(
    db: aiosqlite.Connection,
    document_id: str,
    chunks: list[Chunk],
) -> None:
    """SQLite variant. Triggers on chunks_fts keep the FTS index in sync."""
    await db.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
    if chunks:
        await db.executemany(
            "INSERT INTO document_chunks "
            "(document_id, chunk_index, content, page, start_char, token_count, header_breadcrumb) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (document_id, c.index, c.content, c.page, c.start_char, c.token_count,
                 c.header_breadcrumb)
                for c in chunks
            ],
        )


def _split_paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def _get_overlap(blocks: list[str], target_tokens: int) -> tuple[list[str], int]:
    result: list[str] = []
    tokens = 0
    for block in reversed(blocks):
        bt = _estimate_tokens(block)
        if tokens + bt > target_tokens:
            break
        result.insert(0, block)
        tokens += bt
    return result, tokens
