"""Postgres + S3 implementation of VaultFS."""

import logging

import aioboto3

from config import settings
from db import scoped_query, scoped_queryrow, service_queryrow, service_execute
from .base import VaultFS

logger = logging.getLogger(__name__)

_s3_session = None


def _get_s3_session():
    global _s3_session
    if _s3_session is None and settings.AWS_ACCESS_KEY_ID:
        _s3_session = aioboto3.Session(
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )
    return _s3_session


class PostgresVaultFS(VaultFS):
    """Postgres + S3 vault."""

    def __init__(self, user_id: str):
        self.user_id = user_id


    async def resolve_kb(self, slug: str) -> dict | None:
        return await scoped_queryrow(
            self.user_id,
            "SELECT id, name, slug FROM knowledge_bases WHERE slug = $1 AND user_id = $2",
            slug, self.user_id,
        )

    async def list_knowledge_bases(self) -> list[dict]:
        return await scoped_query(
            self.user_id,
            "SELECT name, slug, created_at FROM knowledge_bases WHERE user_id = $1 ORDER BY created_at DESC",
            self.user_id,
        )


    async def get_document(self, kb_id: str, filename: str, dir_path: str) -> dict | None:
        return await scoped_queryrow(
            self.user_id,
            "SELECT id, user_id, filename, title, path, content, tags, version, file_type, "
            "page_count, created_at, updated_at "
            "FROM documents WHERE knowledge_base_id = $1 AND filename = $2 AND path = $3 AND NOT archived AND user_id = $4",
            kb_id, filename, dir_path, self.user_id,
        )

    async def find_document_by_name(self, kb_id: str, name: str) -> dict | None:
        return await scoped_queryrow(
            self.user_id,
            "SELECT id, user_id, filename, title, path, content, tags, version, file_type, "
            "page_count, created_at, updated_at "
            "FROM documents WHERE knowledge_base_id = $1 AND (filename = $2 OR title = $2) AND NOT archived AND user_id = $3",
            kb_id, name, self.user_id,
        )

    async def create_document(self, kb_id: str, filename: str, title: str, dir_path: str, file_type: str, content: str, tags: list[str], date: str | None = None, metadata: dict | None = None) -> dict:
        import json as _json
        return await service_queryrow(
            "INSERT INTO documents (knowledge_base_id, user_id, filename, title, path, "
            "file_type, status, content, tags, date, metadata, version) "
            "VALUES ($1, $2, $3, $4, $5, $6, 'ready', $7, $8, $9, $10::jsonb, 0) RETURNING id, filename, path",
            kb_id, self.user_id, filename, title, dir_path, file_type, content, tags,
            date, _json.dumps(metadata) if metadata else None,
        )

    async def update_document(self, doc_id: str, content: str, tags: list[str] | None = None, title: str | None = None, date: str | None = None, metadata: dict | None = None) -> dict | None:
        import json as _json
        # Build SET clauses dynamically based on what's provided
        sets = ["content = $1", "version = version + 1", "updated_at = now()"]
        args: list = [content, doc_id, self.user_id]
        idx = 4  # next param index

        if title is not None:
            sets.append(f"title = ${idx}")
            args.append(title)
            idx += 1
        if tags is not None:
            sets.append(f"tags = ${idx}")
            args.append(tags)
            idx += 1
        if date is not None:
            sets.append(f"date = ${idx}")
            args.append(date)
            idx += 1
        if metadata is not None:
            sets.append(f"metadata = ${idx}::jsonb")
            args.append(_json.dumps(metadata))
            idx += 1

        sql = f"UPDATE documents SET {', '.join(sets)} WHERE id = $2 AND user_id = $3"
        if title is not None:
            sql += " RETURNING id, filename, path"
            return await service_queryrow(sql, *args)
        await service_execute(sql, *args)
        return None

    async def archive_documents(self, doc_ids: list[str]) -> int:
        result = await service_execute(
            "UPDATE documents SET archived = true, updated_at = now() "
            "WHERE id = ANY($1::uuid[]) AND user_id = $2",
            doc_ids, self.user_id,
        )
        return int(result.split()[-1]) if result else 0


    async def list_documents(self, kb_id: str) -> list[dict]:
        return await scoped_query(
            self.user_id,
            "SELECT id, filename, title, path, file_type, tags, page_count, updated_at "
            "FROM documents WHERE knowledge_base_id = $1 AND NOT archived AND user_id = $2 "
            "ORDER BY path, filename",
            kb_id, self.user_id,
        )

    async def list_documents_with_content(self, kb_id: str) -> list[dict]:
        return await scoped_query(
            self.user_id,
            "SELECT id, filename, title, path, content, tags, file_type, page_count "
            "FROM documents WHERE knowledge_base_id = $1 AND NOT archived AND user_id = $2 "
            "ORDER BY path, filename",
            kb_id, self.user_id,
        )


    async def get_pages(self, doc_id: str, page_nums: list[int]) -> list[dict]:
        return await scoped_query(
            self.user_id,
            "SELECT page, content, elements FROM document_pages "
            "WHERE document_id = $1 AND page = ANY($2) ORDER BY page",
            doc_id, page_nums,
        )

    async def get_all_pages(self, doc_id: str) -> list[dict]:
        return await scoped_query(
            self.user_id,
            "SELECT page, content, elements FROM document_pages "
            "WHERE document_id = $1 ORDER BY page",
            doc_id,
        )


    async def search_chunks(self, kb_id: str, query: str, limit: int, path_filter: str | None = None) -> list[dict]:
        path_clause = ""
        if path_filter == "wiki":
            path_clause = " AND d.path LIKE '/wiki/%%'"
        elif path_filter == "sources":
            path_clause = " AND d.path NOT LIKE '/wiki/%%'"

        return await scoped_query(
            self.user_id,
            f"SELECT dc.content, dc.page, dc.header_breadcrumb, dc.chunk_index, "
            f"  d.filename, d.title, d.path, d.file_type, d.tags, "
            f"  pgroonga_score(dc.tableoid, dc.ctid) AS score "
            f"FROM document_chunks dc "
            f"JOIN documents d ON dc.document_id = d.id "
            f"WHERE dc.knowledge_base_id = $1 "
            f"  AND dc.content &@~ $2 "
            f"  AND NOT d.archived"
            f"  AND d.user_id = $3"
            f"{path_clause} "
            f"ORDER BY score DESC, dc.chunk_index "
            f"LIMIT $4",
            kb_id, query, self.user_id, limit,
        )


    async def load_source_bytes(self, doc: dict) -> bytes | None:
        file_type = doc.get("file_type", "")
        s3_key = f"{self.user_id}/{doc['id']}/source.{file_type}"
        return await self._load_s3(s3_key)

    async def load_image_bytes(self, doc_id: str, image_id: str) -> bytes | None:
        s3_key = f"{self.user_id}/{doc_id}/images/{image_id}"
        return await self._load_s3(s3_key)

    async def _load_s3(self, key: str) -> bytes | None:
        session = _get_s3_session()
        if not session:
            return None
        try:
            async with session.client("s3") as s3:
                resp = await s3.get_object(Bucket=settings.S3_BUCKET, Key=key)
                return await resp["Body"].read()
        except Exception as e:
            logger.warning("Failed to load S3 key %s: %s", key, e)
            return None


    def write_to_disk(self, dir_path: str, filename: str, content: str) -> bool:
        return True

    def delete_from_disk(self, docs: list[dict]) -> None:
        pass


    async def delete_references(self, source_doc_id: str) -> None:
        await service_execute(
            "DELETE FROM document_references WHERE source_document_id = $1",
            source_doc_id,
        )

    async def upsert_reference(self, source_id: str, target_id: str, kb_id: str, ref_type: str, page: int | None) -> None:
        try:
            await service_execute(
                "INSERT INTO document_references "
                "(source_document_id, target_document_id, knowledge_base_id, reference_type, page) "
                "VALUES ($1, $2, $3, $4, $5) "
                "ON CONFLICT (source_document_id, target_document_id, reference_type) DO UPDATE "
                "SET page = EXCLUDED.page, created_at = now()",
                source_id, target_id, kb_id, ref_type, page,
            )
        except Exception as e:
            logger.warning("Failed to insert reference %s -> %s: %s", source_id[:8], target_id[:8], e)

    async def propagate_staleness(self, doc_id: str) -> None:
        await service_execute(
            "UPDATE documents SET stale_since = now() "
            "WHERE id IN ("
            "  SELECT source_document_id FROM document_references "
            "  WHERE target_document_id = $1 AND reference_type = 'links_to'"
            ") AND stale_since IS NULL AND user_id = $2",
            doc_id, self.user_id,
        )

    async def get_backlinks(self, doc_id: str) -> list[dict]:
        return await scoped_query(
            self.user_id,
            "SELECT d.path, d.filename, d.title, dr.reference_type "
            "FROM document_references dr "
            "JOIN documents d ON dr.source_document_id = d.id "
            "WHERE dr.target_document_id = $1 AND NOT d.archived AND d.user_id = $2 "
            "ORDER BY d.path, d.filename",
            doc_id, self.user_id,
        )

    async def get_forward_references(self, doc_id: str) -> list[dict]:
        return await scoped_query(
            self.user_id,
            "SELECT d.filename, d.title, d.path, dr.reference_type, dr.page "
            "FROM document_references dr "
            "JOIN documents d ON dr.target_document_id = d.id "
            "WHERE dr.source_document_id = $1 AND NOT d.archived AND d.user_id = $2 "
            "ORDER BY dr.reference_type, d.path, d.filename",
            doc_id, self.user_id,
        )

    async def find_uncited_sources(self, kb_id: str) -> list[dict]:
        return await scoped_query(
            self.user_id,
            "SELECT d.filename, d.title, d.path, d.file_type "
            "FROM documents d "
            "WHERE d.knowledge_base_id = $1 AND NOT d.archived AND d.user_id = $2 "
            "  AND d.path NOT LIKE '/wiki/%%' "
            "  AND d.id NOT IN (SELECT target_document_id FROM document_references WHERE reference_type = 'cites') "
            "ORDER BY d.filename",
            kb_id, self.user_id,
        )

    async def find_stale_pages(self, kb_id: str) -> list[dict]:
        return await scoped_query(
            self.user_id,
            "SELECT d.filename, d.title, d.path, d.stale_since "
            "FROM documents d "
            "WHERE d.knowledge_base_id = $1 AND NOT d.archived AND d.user_id = $2 "
            "  AND d.stale_since IS NOT NULL "
            "ORDER BY d.stale_since DESC",
            kb_id, self.user_id,
        )
