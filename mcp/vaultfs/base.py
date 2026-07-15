from abc import ABC, abstractmethod


class DuplicateDocumentError(Exception):
    """Raised when create_document hits a uniqueness constraint on (kb, path, filename)."""

    def __init__(self, dir_path: str, filename: str):
        self.dir_path = dir_path
        self.filename = filename
        super().__init__(f"document already exists at {dir_path}{filename}")


class StorageQuotaExceededError(Exception):
    """Raised when a hosted write would exceed the user's storage quota."""

    def __init__(self, used_bytes: int, limit_bytes: int):
        self.used_bytes = used_bytes
        self.limit_bytes = limit_bytes
        used_mb = used_bytes / (1024 * 1024)
        limit_mb = limit_bytes / (1024 * 1024)
        super().__init__(
            f"storage quota exceeded (using {used_mb:.0f} MiB of {limit_mb:.0f} MiB)"
        )


class VaultFS(ABC):
    """Abstract virtual filesystem for the knowledge vault."""

    user_id: str

    @abstractmethod
    async def resolve_kb(self, slug: str) -> dict | None: ...

    @abstractmethod
    async def list_knowledge_bases(self) -> list[dict]: ...

    @abstractmethod
    async def create_knowledge_base(self, name: str, description: str | None = None, kind: str = "wiki") -> dict: ...

    @abstractmethod
    async def update_knowledge_base(self, kb_id: str, name: str | None = None, description: str | None = None, kind: str | None = None) -> dict | None: ...

    @abstractmethod
    async def get_document(self, kb_id: str, filename: str, dir_path: str) -> dict | None: ...

    @abstractmethod
    async def find_document_by_name(self, kb_id: str, name: str) -> dict | None: ...

    @abstractmethod
    async def get_document_metadata(self, kb_id: str, filename: str, dir_path: str) -> dict | None: ...

    @abstractmethod
    async def find_document_metadata_by_name(self, kb_id: str, name: str) -> dict | None: ...

    @abstractmethod
    async def create_document(self, kb_id: str, filename: str, title: str, dir_path: str, file_type: str, content: str, tags: list[str], date: str | None = None, metadata: dict | None = None) -> dict: ...

    @abstractmethod
    async def update_document(self, doc_id: str, content: str, tags: list[str] | None = None, title: str | None = None, date: str | None = None, metadata: dict | None = None) -> dict | None: ...

    @abstractmethod
    async def add_highlight_reply(self, doc_id: str, highlight_id: str, reply: dict) -> dict | None: ...

    @abstractmethod
    async def archive_documents(self, doc_ids: list[str]) -> int: ...

    @abstractmethod
    async def list_documents(self, kb_id: str) -> list[dict]: ...

    @abstractmethod
    async def list_documents_with_content(
        self,
        kb_id: str,
        path_glob: str | None = None,
        content_limit: int | None = None,
        wiki_content_only: bool = False,
    ) -> list[dict]: ...

    @abstractmethod
    async def get_pages(self, doc_id: str, page_nums: list[int]) -> list[dict]: ...

    @abstractmethod
    async def get_all_pages(self, doc_id: str) -> list[dict]: ...

    @abstractmethod
    async def get_pages_for_batch(self, doc_id: str, max_chars: int) -> list[dict]: ...

    @abstractmethod
    async def get_page_index(self, doc_id: str) -> list[dict]: ...

    @abstractmethod
    async def search_chunks(self, kb_id: str, query: str, limit: int, path_filter: str | None = None) -> list[dict]: ...

    @abstractmethod
    async def load_source_bytes(self, doc: dict) -> bytes | None: ...

    @abstractmethod
    async def load_image_bytes(self, doc_id: str, image_id: str) -> bytes | None: ...

    @abstractmethod
    async def load_asset_bytes(self, asset_doc_id: str) -> bytes | None: ...

    @abstractmethod
    def write_to_disk(self, dir_path: str, filename: str, content: str) -> bool: ...

    @abstractmethod
    def delete_from_disk(self, docs: list[dict]) -> None: ...

    @abstractmethod
    async def delete_references(self, source_doc_id: str) -> None: ...

    @abstractmethod
    async def upsert_reference(self, source_id: str, target_id: str, kb_id: str, ref_type: str, page: int | None) -> None: ...

    @abstractmethod
    async def replace_references(
        self,
        source_id: str,
        kb_id: str,
        edges: list[tuple[str, str, int | None]],
    ) -> None: ...

    @abstractmethod
    async def propagate_staleness(self, doc_id: str) -> None: ...

    @abstractmethod
    async def get_backlinks(self, doc_id: str) -> list[dict]: ...

    @abstractmethod
    async def get_forward_references(self, doc_id: str) -> list[dict]: ...

    @abstractmethod
    async def get_reference_edges(self, kb_id: str) -> list[dict]: ...

    @abstractmethod
    async def find_uncited_sources(self, kb_id: str) -> list[dict]: ...

    @abstractmethod
    async def find_stale_pages(self, kb_id: str) -> list[dict]: ...
