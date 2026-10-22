"""Paragraph chunker with token overlap that tracks markdown headers as per-chunk breadcrumbs."""

import hashlib
import logging
import re
from dataclasses import dataclass

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
        breadcrumb = " > ".join(t for _, t in header_stack)

        header_match = HEADER_RE.match(para)
        if header_match:
            level = len(header_match.group(1))
            heading = header_match.group(2).strip()
            header_stack = [(existing_level, t) for existing_level, t in header_stack if existing_level < level]
            header_stack.append((level, heading))

        pending_text = "\n\n".join(current_blocks)
        if current_tokens + para_tokens > chunk_size and _estimate_tokens(pending_text) >= MIN_CHUNK_TOKENS:
            chunks.append(Chunk(
                index=len(chunks),
                content=pending_text,
                page=page,
                start_char=current_start,
                token_count=_estimate_tokens(pending_text),
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
        final_text = "\n\n".join(current_blocks)
        chunks.append(Chunk(
            index=len(chunks),
            content=final_text,
            page=page,
            start_char=current_start,
            token_count=_estimate_tokens(final_text),
            header_breadcrumb=" > ".join(t for _, t in header_stack),
        ))

    return _enforce_max_chars(chunks)


def _enforce_max_chars(chunks: list[Chunk]) -> list[Chunk]:
    """Split oversized chunks (CJK paragraphs, long code) on sentences, else hard slices."""
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
        # Distinct start_char per piece so consumers can derive its end as start_char + len(content).
        base = c.start_char or 0
        offset = 0
        for piece in _split_oversized(c.content):
            result.append(Chunk(
                index=len(result), content=piece, page=c.page,
                start_char=base + offset, token_count=_estimate_tokens(piece),
                header_breadcrumb=c.header_breadcrumb,
            ))
            offset += len(piece)
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
            async with conn.transaction():
                await _lock_document(conn, document_id)
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
    # ponytail: keeps only the unchanged prefix; mid-document edits still rewrite the tail.
    kept = await _count_unchanged_prefix(conn, document_id, chunks)
    await conn.execute(
        "DELETE FROM document_chunks WHERE document_id = $1 AND chunk_index >= $2", document_id, kept,
    )
    changed = chunks[kept:]
    if not changed:
        return

    # source_content is immutable; content diverges once highlight annotations are materialized.
    await conn.execute(
        "INSERT INTO document_chunks "
        "(document_id, user_id, knowledge_base_id, chunk_index, content, source_content, "
        " page, start_char, token_count, header_breadcrumb) "
        "SELECT $1::uuid, $2::uuid, $3::uuid, row.chunk_index, row.content, row.content, "
        "       row.page, row.start_char, row.token_count, row.header_breadcrumb "
        "FROM UNNEST($4::int[], $5::text[], $6::int[], $7::int[], $8::int[], $9::text[]) "
        "AS row(chunk_index, content, page, start_char, token_count, header_breadcrumb)",
        document_id,
        user_id,
        knowledge_base_id,
        [c.index for c in changed],
        [c.content for c in changed],
        [c.page for c in changed],
        [c.start_char for c in changed],
        [c.token_count for c in changed],
        [c.header_breadcrumb for c in changed],
    )
    logger.info("Stored %d of %d chunks for doc %s", len(changed), len(chunks), document_id[:8])


async def _count_unchanged_prefix(conn: asyncpg.Connection, document_id: str, chunks: list[Chunk]) -> int:
    """Count leading stored chunks identical to the new ones, so they can be left in place."""
    rows = await _fetch_chunk_fingerprints(conn, document_id)
    kept = 0
    for row, chunk in zip(rows, chunks, strict=False):
        if tuple(row) != _chunk_fingerprint(chunk):
            break
        kept += 1
    return kept


def _chunk_fingerprint(chunk: Chunk) -> tuple:
    digest = hashlib.md5(chunk.content.encode()).hexdigest()
    # Annotated chunks never count as unchanged: highlight assignment can move when other chunks change.
    return (chunk.index, digest, chunk.page, chunk.start_char, chunk.token_count, chunk.header_breadcrumb, False)


async def _lock_document(conn: asyncpg.Connection, document_id: str) -> None:
    await conn.execute("SELECT 1 FROM documents WHERE id = $1 FOR NO KEY UPDATE", document_id)


async def _fetch_chunk_fingerprints(conn: asyncpg.Connection, document_id: str) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT chunk_index, md5(source_content), page, start_char, token_count, header_breadcrumb, has_highlight "
        "FROM document_chunks WHERE document_id = $1 ORDER BY chunk_index",
        document_id,
    )


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
