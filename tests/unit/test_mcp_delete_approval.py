"""Focused tests for the MCP delete elicitation gate."""

import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "mcp"))

from tools.delete import DeleteConfirmation, DeleteHandler, register  # noqa: E402, I001


KB = {"id": "kb-1", "slug": "test-vault"}


def _doc(doc_id: str, path: str, filename: str) -> dict:
    return {"id": doc_id, "path": path, "filename": filename}


class FakeVaultFS:
    def __init__(self, docs: list[dict]):
        self.docs = list(docs)
        self.deleted_from_disk: list[dict] = []
        self.archived_ids: list[str] = []

    async def list_documents(self, kb_id: str) -> list[dict]:
        assert kb_id == KB["id"]
        return [doc for doc in self.docs if str(doc["id"]) not in self.archived_ids]

    async def get_document(self, kb_id: str, filename: str, path: str) -> dict | None:
        assert kb_id == KB["id"]
        return next(
            (
                doc
                for doc in self.docs
                if doc["filename"] == filename
                and doc["path"] == path
                and str(doc["id"]) not in self.archived_ids
            ),
            None,
        )

    def delete_from_disk(self, docs: list[dict]) -> None:
        self.deleted_from_disk.extend(docs)

    async def archive_documents(self, doc_ids: list[str]) -> int:
        self.archived_ids.extend(doc_ids)
        return len(doc_ids)


class FakeSession:
    def __init__(self, supports_elicitation: bool):
        self.supports_elicitation = supports_elicitation

    def check_client_capability(self, capability) -> bool:
        assert capability.elicitation is not None
        return self.supports_elicitation


class FakeContext:
    def __init__(self, action: str, confirm: bool = False, supports_elicitation: bool = True):
        self.action = action
        self.confirm = confirm
        self.elicit_calls: list[tuple[str, type]] = []
        self.request_context = SimpleNamespace(
            session=FakeSession(supports_elicitation)
        )

    async def elicit(self, message: str, schema: type):
        self.elicit_calls.append((message, schema))
        if self.action == "accept":
            return SimpleNamespace(
                action="accept",
                data=SimpleNamespace(confirm=self.confirm),
            )
        return SimpleNamespace(action=self.action)


def _mixed_docs() -> list[dict]:
    return [
        _doc("1", "/", "alpha.md"),
        _doc("2", "/wiki/", "notes.md"),
        _doc("3", "/wiki/", "overview.md"),
        _doc("4", "/wiki/", "log.md"),
    ]


async def test_accept_with_explicit_true_deletes_exact_preview_and_skips_protected():
    fs = FakeVaultFS(_mixed_docs())
    ctx = FakeContext("accept", confirm=True)

    result = await DeleteHandler(fs, KB).delete(ctx, "/wiki/*")

    assert fs.archived_ids == ["2"]
    assert [doc["id"] for doc in fs.deleted_from_disk] == ["2"]
    assert "Deleted 1 document(s)" in result
    assert "Skipped (protected)" in result

    message, schema = ctx.elicit_calls[0]
    assert schema is DeleteConfirmation
    assert "matched 3 document(s)" in message
    assert "Exact documents to delete (1)" in message
    assert '"/wiki/notes.md"' in message
    assert "Protected structural pages that will be skipped (2)" in message
    assert schema.model_json_schema()["required"] == ["confirm"]


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("decline", "Deletion declined"),
        ("cancel", "Deletion cancelled"),
    ],
)
async def test_declined_or_cancelled_approval_never_deletes(action: str, expected: str):
    fs = FakeVaultFS([_doc("1", "/", "alpha.md")])
    ctx = FakeContext(action)

    result = await DeleteHandler(fs, KB).delete(ctx, "alpha.md")

    assert expected in result
    assert "No documents were deleted" in result
    assert fs.archived_ids == []
    assert fs.deleted_from_disk == []


async def test_accept_with_false_boolean_never_deletes():
    fs = FakeVaultFS([_doc("1", "/", "alpha.md")])
    ctx = FakeContext("accept", confirm=False)

    result = await DeleteHandler(fs, KB).delete(ctx, "alpha.md")

    assert "not explicitly confirmed" in result
    assert fs.archived_ids == []


async def test_database_noop_never_removes_local_file():
    class NoopVaultFS(FakeVaultFS):
        async def archive_documents(self, doc_ids: list[str]) -> int:
            return 0

    fs = NoopVaultFS([_doc("1", "/", "alpha.md")])
    ctx = FakeContext("accept", confirm=True)

    result = await DeleteHandler(fs, KB).delete(ctx, "alpha.md")

    assert "No documents were deleted" in result
    assert fs.deleted_from_disk == []


async def test_client_without_elicitation_gets_preview_but_nothing_is_deleted():
    fs = FakeVaultFS([_doc("1", "/", "alpha.md")])
    ctx = FakeContext("accept", confirm=True, supports_elicitation=False)

    result = await DeleteHandler(fs, KB).delete(ctx, "alpha.md")

    assert "Exact documents to delete (1)" in result
    assert '"/alpha.md"' in result
    assert "could not provide interactive approval" in result
    assert "No documents were deleted" in result
    assert ctx.elicit_calls == []
    assert fs.archived_ids == []


@pytest.mark.parametrize("pattern", ["*", "**", "**/*", "/*", "/**"])
async def test_whole_vault_globs_are_allowed_after_approval(pattern: str):
    fs = FakeVaultFS(_mixed_docs())
    ctx = FakeContext("accept", confirm=True)

    result = await DeleteHandler(fs, KB).delete(ctx, pattern)

    assert "Deleted 4 document(s)" in result
    assert fs.archived_ids == ["1", "4", "2", "3"]
    assert "Skipped (protected)" not in result


def test_delete_tool_is_annotated_as_destructive_and_not_read_only():
    captured = {}

    class FakeMCP:
        def tool(self, **kwargs):
            captured.update(kwargs)

            def decorator(fn):
                return fn

            return decorator

    register(FakeMCP(), lambda ctx: "user-1", lambda user_id: None)

    assert captured["annotations"].destructiveHint is True
    assert captured["annotations"].readOnlyHint is False
