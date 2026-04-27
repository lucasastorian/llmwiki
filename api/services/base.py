"""Service layer ABCs. One implementation per mode (hosted/local)."""

from __future__ import annotations

from abc import ABC, abstractmethod


class UserService(ABC):

    @abstractmethod
    async def get_profile(self) -> dict: ...

    @abstractmethod
    async def complete_onboarding(self) -> None: ...

    @abstractmethod
    async def get_usage(self) -> dict: ...


class KBService(ABC):

    @abstractmethod
    async def list(self) -> list[dict]: ...

    @abstractmethod
    async def get(self, kb_id: str) -> dict | None: ...

    @abstractmethod
    async def create(self, name: str, description: str | None) -> dict: ...

    @abstractmethod
    async def update(self, kb_id: str, name: str | None, description: str | None) -> dict | None: ...

    @abstractmethod
    async def delete(self, kb_id: str) -> bool: ...


class DocumentService(ABC):

    @abstractmethod
    async def list(self, kb_id: str, path: str | None = None) -> list[dict]: ...

    @abstractmethod
    async def get(self, doc_id: str) -> dict | None: ...

    @abstractmethod
    async def get_content(self, doc_id: str) -> dict | None: ...

    @abstractmethod
    async def get_url(self, doc_id: str) -> dict | None: ...

    @abstractmethod
    async def create_note(self, kb_id: str, filename: str, path: str, content: str) -> dict: ...

    @abstractmethod
    async def create_web_clip(self, kb_id: str, url: str, title: str, html: str) -> dict: ...

    @abstractmethod
    async def update_content(self, doc_id: str, content: str) -> dict | None: ...

    @abstractmethod
    async def update_metadata(self, doc_id: str, fields: dict) -> dict | None: ...

    @abstractmethod
    async def delete(self, doc_id: str) -> bool: ...

    @abstractmethod
    async def bulk_delete(self, doc_ids: list[str]) -> int: ...


class ServiceFactory(ABC):

    @abstractmethod
    def user_service(self, user_id: str) -> UserService: ...

    @abstractmethod
    def kb_service(self, user_id: str) -> KBService: ...

    @abstractmethod
    def document_service(self, user_id: str) -> DocumentService: ...
