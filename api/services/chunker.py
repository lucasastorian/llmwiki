"""Text chunker with header breadcrumb tracking.

Splits document content into ~512 token chunks with ~128 token overlap.
Tracks markdown headers to build breadcrumb context per chunk.
"""

import re
import logging
from dataclasses import dataclass, field

import asyncpg

logger = logging.getLogger(__name__)

CHUNK_SIZE = 512
CHUNK_OVERLAP = 128
MIN_CHUNK_TOKENS = 32
MAX_CHUNK_CHARS = 10_000  # matches DB constraint chk_chunks_content_length

SENTENCE_RE = re.compile(r'(?<=[.!?。！？])\s+')
HEADER_RE = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)


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
    start_char_offset: int = 0,
) -> list[Chunk]:
    """Chunk a text string into overlapping segments with header tracking."""
    if not content or not content.strip():
        return []

    paragraphs = _split_paragraphs(content)
    header_stack: list[tuple[int, str]] = []
    chunks: list[Chunk] = []
    current_blocks: list[str] = []
    current_tokens = 0
    current_start = start_char_offset
    char_pos = start_char_offset

    for para in paragraphs:
        para_tokens = _estimate_tokens(para)

        header_match = HEADER_RE.match(para)
        if header_match:
            level = len(header_match.group(1))
            heading = header_match.group(2).strip()
            header_stack = [(l, t) for l, t in header_stack if l < level]
            header_stack.append((level, heading))

        if current_tokens + para_tokens > chunk_size and current_blocks:
            chunk_text_str = "\n\n".join(current_blocks)
            if _estimate_tokens(chunk_text_str) >= MIN_CHUNK_TOKENS:
                breadcrumb = " > ".join(t for _, t in header_stack)
                chunks.append(Chunk(
                    index=len(chunks),
                    content=chunk_text_str,
                    page=page,
                    start_char=current_start,
                    token_count=_estimate_tokens(chunk_text_str),
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
        chunk_text_str = "\n\n".join(current_blocks)
        if _estimate_tokens(chunk_text_str) >= MIN_CHUNK_TOKENS:
            breadcrumb = " > ".join(t for _, t in header_stack)
            chunks.append(Chunk(
                index=len(chunks),
                content=chunk_text_str,
                page=page,
                start_char=current_start,
                token_count=_estimate_tokens(chunk_text_str),
                header_breadcrumb=breadcrumb,
            ))

    return _enforce_max_chars(chunks)


def _enforce_max_chars(chunks: list[Chunk]) -> list[Chunk]:
    """Split any chunk whose content exceeds MAX_CHUNK_CHARS.

    The paragraph-based chunker emits one chunk per paragraph when a single
    paragraph is bigger than CHUNK_SIZE — fine for English wiki text, but CJK
    paragraphs and long code blocks routinely exceed the 10k-char DB limit.
    Split such chunks on sentence boundaries; fall back to fixed-size slices
    if no sentence break is available.
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
                # Sentence-split didn't help — hard-slice.
                for i in range(0, len(part), MAX_CHUNK_CHARS):
                    pieces.append(part[i:i + MAX_CHUNK_CHARS])
                current = ""
    if current:
        pieces.append(current)
    return pieces


def chunk_pages(page_contents: list[tuple[int, str]]) -> list[Chunk]:
    """Chunk multiple pages, preserving page numbers. Each (page_number, content) tuple."""
    all_chunks: list[Chunk] = []
    for page_num, content in page_contents:
        page_chunks = chunk_text(content, page=page_num)
        for c in page_chunks:
            c.index = len(all_chunks)
            all_chunks.append(c)
    return all_chunks


async def store_chunks(
    pool_or_conn,
    document_id: str,
    user_id: str,
    knowledge_base_id: str,
    chunks: list[Chunk],
):
    if isinstance(pool_or_conn, asyncpg.Connection):
        await _store_chunks_on_conn(pool_or_conn, document_id, user_id, knowledge_base_id, chunks)
    else:
        conn = await pool_or_conn.acquire()
        try:
            await _store_chunks_on_conn(conn, document_id, user_id, knowledge_base_id, chunks)
        finally:
            await pool_or_conn.release(conn)


async def _store_chunks_on_conn(
    conn: asyncpg.Connection,
    document_id: str,
    user_id: str,
    knowledge_base_id: str,
    chunks: list[Chunk],
):
    await conn.execute("DELETE FROM document_chunks WHERE document_id = $1", document_id)

    if not chunks:
        return

    await conn.executemany(
        "INSERT INTO document_chunks "
        "(document_id, user_id, knowledge_base_id, chunk_index, content, page, start_char, token_count, header_breadcrumb) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
        [
            (document_id, user_id, knowledge_base_id, c.index, c.content, c.page, c.start_char, c.token_count, c.header_breadcrumb)
            for c in chunks
        ],
    )
    logger.info("Stored %d chunks for doc %s", len(chunks), document_id[:8])


def _split_paragraphs(text: str) -> list[str]:
    """Split on double newlines, preserving paragraph structure."""
    parts = re.split(r'\n\s*\n', text)
    return [p.strip() for p in parts if p.strip()]


def _get_overlap(blocks: list[str], target_tokens: int) -> tuple[list[str], int]:
    """Get trailing blocks that fit within target_tokens for overlap."""
    result: list[str] = []
    tokens = 0
    for block in reversed(blocks):
        block_tokens = _estimate_tokens(block)
        if tokens + block_tokens > target_tokens:
            break
        result.insert(0, block)
        tokens += block_tokens
    return result, tokens
