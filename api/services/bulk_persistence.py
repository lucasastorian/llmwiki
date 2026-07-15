"""Set-based Postgres writes shared by hosted document processors."""

import json
from typing import Any


async def insert_pages(
    conn,
    document_id: str,
    pages: list[tuple[int, str, dict | None]],
) -> None:
    if not pages:
        return
    await conn.execute(
        "INSERT INTO document_pages (document_id, page, content, elements) "
        "SELECT $1::uuid, row.page, row.content, row.elements "
        "FROM UNNEST($2::int[], $3::text[], $4::jsonb[]) "
        "AS row(page, content, elements)",
        document_id,
        [page for page, _, _ in pages],
        [content for _, content, _ in pages],
        [json.dumps(elements) if elements else None for _, _, elements in pages],
    )


async def insert_assets(
    conn,
    kb_id: str,
    user_id: str,
    assets: list[Any],
) -> None:
    if not assets:
        return
    await conn.execute(
        "INSERT INTO documents "
        "(id, knowledge_base_id, user_id, filename, path, title, file_type, file_size, "
        " status, content, tags, metadata) "
        "SELECT row.id, $1::uuid, $2::uuid, row.filename, row.path, row.filename, "
        "       row.file_type, row.file_size, 'ready', NULL, '{}'::text[], row.metadata "
        "FROM UNNEST($3::uuid[], $4::text[], $5::text[], $6::text[], $7::bigint[], $8::jsonb[]) "
        "AS row(id, filename, path, file_type, file_size, metadata)",
        kb_id,
        user_id,
        [asset.document_id for asset in assets],
        [asset.filename for asset in assets],
        [asset.path for asset in assets],
        [asset.file_type for asset in assets],
        [len(asset.data) for asset in assets],
        [json.dumps(asset.metadata()) for asset in assets],
    )
