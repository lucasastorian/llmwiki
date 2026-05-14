"""One-shot backfill: chunk + index wiki pages that have no chunks yet.

The MCP service previously created wiki pages without populating
`document_chunks`, so they were invisible to keyword search. Run this
after deploying the chunking fix to backfill the existing pages.

Usage:
  cd api
  DATABASE_URL=postgres://... python -m scripts.backfill_wiki_chunks
  DATABASE_URL=postgres://... python -m scripts.backfill_wiki_chunks --dry-run
"""

import argparse
import asyncio
import logging
import os
import sys

import asyncpg

# Add api/ to path so we can import services.chunker when run as a module.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.chunker import chunk_text, store_chunks  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def find_unchunked_wiki_pages(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT d.id, d.user_id, d.knowledge_base_id, d.path, d.filename, d.content "
        "FROM documents d "
        "WHERE NOT d.archived "
        "  AND d.file_type IN ('md', 'txt') "
        "  AND d.content IS NOT NULL "
        "  AND length(d.content) > 0 "
        "  AND NOT EXISTS (SELECT 1 FROM document_chunks dc WHERE dc.document_id = d.id) "
        "ORDER BY d.created_at"
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report what would be chunked, write nothing.")
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set")
        return 1

    conn = await asyncpg.connect(db_url)
    try:
        rows = await find_unchunked_wiki_pages(conn)
        logger.info("Found %d unchunked md/txt document(s)", len(rows))

        if args.dry_run:
            wiki = sum(1 for r in rows if r["path"].startswith("/wiki/"))
            other = len(rows) - wiki
            logger.info("Would backfill %d wiki page(s) and %d note(s)", wiki, other)
            for r in rows[:10]:
                logger.info("  %s%s (%d chars)", r["path"], r["filename"], len(r["content"]))
            if len(rows) > 10:
                logger.info("  ... %d more", len(rows) - 10)
            return 0

        processed = 0
        empty = 0
        for r in rows:
            chunks = chunk_text(r["content"])
            if not chunks:
                empty += 1
                continue
            async with conn.transaction():
                await store_chunks(
                    conn,
                    str(r["id"]),
                    str(r["user_id"]),
                    str(r["knowledge_base_id"]),
                    chunks,
                )
            processed += 1
            if processed % 100 == 0:
                logger.info("  ... %d/%d", processed, len(rows))

        logger.info("Done. Backfilled %d document(s), skipped %d empty.", processed, empty)
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
