"""Repository protocol definitions for the database layer.

Each protocol defines operations, not SQL. Postgres and SQLite implementations
write their own native queries behind these interfaces.
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DocumentRepository(Protocol):

    async def list_by_kb(self, kb_id: str, *, path: str | None = None, archived: bool = False) -> list[dict]:
        """List documents in a knowledge base, optionally filtered by path."""
        ...

    async def get(self, doc_id: str) -> dict | None:
        """Get document metadata by ID."""
        ...

    async def get_content(self, doc_id: str) -> dict | None:
        """Get document content + version by ID. Returns {id, content, version}."""
        ...

    async def get_for_url(self, doc_id: str) -> dict | None:
        """Get minimal fields needed for URL generation: {id, user_id, filename, file_type}."""
        ...

    async def find_by_path(
        self, kb_id: str, user_id: str, filename: str, path: str,
    ) -> dict | None:
        """Find a non-archived document by filename and path."""
        ...

    async def create_note(
        self, kb_id: str, user_id: str, filename: str, path: str,
        title: str, content: str, tags: list[str],
    ) -> dict:
        """Create a markdown note. Returns the full document row."""
        ...

    async def update_content(self, doc_id: str, user_id: str, content: str) -> dict | None:
        """Update document content, bump version. Returns {id, content, version} or None."""
        ...

    async def update_metadata(self, doc_id: str, user_id: str, **fields: Any) -> dict | None:
        """Update document metadata fields (filename, path, title, tags, date, metadata)."""
        ...

    async def archive(self, doc_id: str, user_id: str) -> bool:
        """Soft-delete a document. Returns True if a row was updated."""
        ...

    async def bulk_archive(self, doc_ids: list[str], user_id: str) -> None:
        """Soft-delete multiple documents."""
        ...

    async def get_kb_id(self, doc_id: str) -> str | None:
        """Get the knowledge_base_id for a document."""
        ...

    async def update_status(self, doc_id: str, status: str, **fields: Any) -> None:
        """Update document processing status and optional fields (content, page_count, parser, error_message)."""
        ...

    async def get_for_processing(self, doc_id: str, user_id: str) -> dict | None:
        """Get fields needed for OCR: {filename, file_type, knowledge_base_id}."""
        ...

    async def create_upload(
        self, doc_id: str, kb_id: str, user_id: str, filename: str,
        path: str, title: str, file_type: str, file_size: int,
    ) -> None:
        """Create a pending document row for a file upload."""
        ...


@runtime_checkable
class KBRepository(Protocol):

    async def list_all(self, user_id: str) -> list[dict]:
        """List all knowledge bases for a user, with source/wiki counts."""
        ...

    async def get(self, kb_id: str, user_id: str) -> dict | None:
        """Get a single knowledge base by ID."""
        ...

    async def get_owner(self, kb_id: str) -> str | None:
        """Get the user_id that owns a KB. Used for ownership checks."""
        ...

    async def create(
        self, user_id: str, name: str, slug: str, description: str | None,
    ) -> dict:
        """Create a KB. Returns the row. Caller handles scaffold docs separately."""
        ...

    async def update(self, kb_id: str, user_id: str, **fields: Any) -> dict | None:
        """Update KB fields (name, slug, description)."""
        ...

    async def delete(self, kb_id: str, user_id: str) -> bool:
        """Delete a KB and cascade. Returns True if a row was deleted."""
        ...

    async def count_users(self) -> int:
        """Count total distinct users. Used for global capacity checks."""
        ...


@runtime_checkable
class ChunkRepository(Protocol):

    async def store(self, doc_id: str, user_id: str, kb_id: str, chunks: list) -> None:
        """Delete existing chunks for doc, then bulk-insert new ones."""
        ...

    async def search_fulltext(
        self, kb_id: str, query: str, *, limit: int = 20,
        path_filter: str | None = None, user_id: str | None = None,
    ) -> list[dict]:
        """Full-text search across chunks. Returns rows with content, page, score, doc metadata."""
        ...


@runtime_checkable
class PageRepository(Protocol):

    async def get_pages(self, doc_id: str, pages: list[int]) -> list[dict]:
        """Get specific pages by number. Returns [{page, content, elements}]."""
        ...

    async def get_all_pages(self, doc_id: str) -> list[dict]:
        """Get all pages for a document, ordered by page number."""
        ...

    async def store_pages(self, doc_id: str, pages: list[tuple]) -> None:
        """Delete existing pages, then bulk-insert. Each tuple: (page, content, elements_json)."""
        ...


@runtime_checkable
class UserRepository(Protocol):

    async def get(self, user_id: str) -> dict | None:
        """Get user profile."""
        ...

    async def get_limits(self, user_id: str) -> dict | None:
        """Get {page_limit, storage_limit_bytes}."""
        ...

    async def get_usage(self, user_id: str) -> dict:
        """Get {total_pages, total_storage_bytes}."""
        ...

    async def set_onboarded(self, user_id: str) -> None:
        """Mark user as onboarded."""
        ...

    async def ensure_exists(self, user_id: str, email: str = "local@localhost") -> None:
        """Create user if not exists (for local mode bootstrap)."""
        ...
