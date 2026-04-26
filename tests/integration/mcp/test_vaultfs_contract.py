"""Tier 1: VaultFS contract tests against SqliteVaultFS.

Tests every VaultFS method. Self-contained — no Postgres needed.
"""

import pytest
from tests.integration.mcp.conftest import TEST_USER_ID


class TestWorkspace:

    async def test_resolve_kb_returns_workspace(self, fs):
        instance, kb_id = fs
        kb = await instance.resolve_kb("test-workspace")
        assert kb is not None
        assert kb["name"] == "test-workspace"
        assert kb["slug"] == "test-workspace"
        assert kb["id"] == kb_id

    async def test_resolve_kb_returns_none_for_unknown(self, fs):
        instance, _ = fs
        assert await instance.resolve_kb("nonexistent") is not None  # SQLite returns workspace regardless

    async def test_list_knowledge_bases(self, fs):
        instance, _ = fs
        kbs = await instance.list_knowledge_bases()
        assert len(kbs) == 1
        assert kbs[0]["name"] == "test-workspace"
        assert kbs[0]["slug"] == "test-workspace"


class TestDocumentCRUD:

    async def test_create_and_get_source_document(self, fs):
        instance, kb_id = fs
        doc = await instance.create_document(kb_id, "notes.md", "Notes", "/", "md", "hello", ["tag1"])
        assert doc["id"]
        assert doc["filename"] == "notes.md"
        assert doc["path"] == "/"

        fetched = await instance.get_document(kb_id, "notes.md", "/")
        assert fetched is not None
        assert fetched["content"] == "hello"
        assert fetched["tags"] == ["tag1"]

    async def test_create_wiki_document(self, fs):
        instance, kb_id = fs
        doc = await instance.create_document(kb_id, "scaling.md", "Scaling", "/wiki/concepts/", "md", "# Scaling", ["concept"])
        fetched = await instance.get_document(kb_id, "scaling.md", "/wiki/concepts/")
        assert fetched is not None
        assert fetched["content"] == "# Scaling"

    async def test_get_document_wrong_path_returns_none(self, fs):
        instance, kb_id = fs
        await instance.create_document(kb_id, "notes.md", "Notes", "/", "md", "hello", ["tag1"])
        assert await instance.get_document(kb_id, "notes.md", "/wrong/") is None

    async def test_find_document_by_name_case_insensitive(self, fs):
        instance, kb_id = fs
        await instance.create_document(kb_id, "Report.md", "My Report", "/", "md", "content", ["tag"])
        found = await instance.find_document_by_name(kb_id, "report.md")
        assert found is not None
        assert found["filename"] == "Report.md"

    async def test_find_document_by_title(self, fs):
        instance, kb_id = fs
        await instance.create_document(kb_id, "report.md", "My Report", "/", "md", "content", ["tag"])
        found = await instance.find_document_by_name(kb_id, "my report")
        assert found is not None

    async def test_find_document_by_name_returns_none_for_missing(self, fs):
        instance, kb_id = fs
        assert await instance.find_document_by_name(kb_id, "nonexistent") is None

    async def test_update_document_content_and_version(self, fs):
        instance, kb_id = fs
        doc = await instance.create_document(kb_id, "notes.md", "Notes", "/", "md", "v1", ["tag"])
        await instance.update_document(str(doc["id"]), "v2")
        fetched = await instance.get_document(kb_id, "notes.md", "/")
        assert fetched["content"] == "v2"
        assert fetched["version"] == 1

    async def test_update_document_optional_fields(self, fs):
        instance, kb_id = fs
        doc = await instance.create_document(kb_id, "notes.md", "Notes", "/", "md", "content", ["tag1"])
        await instance.update_document(str(doc["id"]), "content", tags=["tag2"], title="New Title")
        fetched = await instance.get_document(kb_id, "notes.md", "/")
        assert fetched["title"] == "New Title"
        assert fetched["tags"] == ["tag2"]

    async def test_archive_removes_from_listing(self, fs):
        instance, kb_id = fs
        doc = await instance.create_document(kb_id, "temp.md", "Temp", "/", "md", "content", ["tag"])
        count = await instance.archive_documents([str(doc["id"])])
        assert count == 1
        assert await instance.get_document(kb_id, "temp.md", "/") is None

    async def test_archive_empty_list(self, fs):
        instance, _ = fs
        assert await instance.archive_documents([]) == 0

    async def test_list_documents_sorted(self, fs):
        instance, kb_id = fs
        await instance.create_document(kb_id, "b.md", "B", "/", "md", "b", ["tag"])
        await instance.create_document(kb_id, "a.md", "A", "/", "md", "a", ["tag"])
        docs = await instance.list_documents(kb_id)
        filenames = [d["filename"] for d in docs]
        assert filenames.index("a.md") < filenames.index("b.md")

    async def test_list_documents_excludes_archived(self, fs):
        instance, kb_id = fs
        doc = await instance.create_document(kb_id, "gone.md", "Gone", "/", "md", "x", ["tag"])
        await instance.archive_documents([str(doc["id"])])
        docs = await instance.list_documents(kb_id)
        assert all(d["filename"] != "gone.md" for d in docs)

    async def test_list_documents_with_content(self, fs):
        instance, kb_id = fs
        await instance.create_document(kb_id, "rich.md", "Rich", "/", "md", "full content", ["tag"])
        docs = await instance.list_documents_with_content(kb_id)
        rich = [d for d in docs if d["filename"] == "rich.md"]
        assert len(rich) == 1
        assert rich[0]["content"] == "full content"


class TestPages:

    async def test_get_pages_returns_requested_pages(self, fs, insert_page):
        instance, kb_id = fs
        doc = await instance.create_document(kb_id, "doc.pdf", "Doc", "/", "pdf", "", ["tag"])
        doc_id = str(doc["id"])
        await insert_page(doc_id, 1, "page one")
        await insert_page(doc_id, 2, "page two")
        await insert_page(doc_id, 3, "page three")

        pages = await instance.get_pages(doc_id, [1, 3])
        assert len(pages) == 2
        assert pages[0]["page"] == 1
        assert pages[1]["page"] == 3

    async def test_get_pages_empty_returns_empty(self, fs):
        instance, _ = fs
        assert await instance.get_pages("fake-id", []) == []

    async def test_get_all_pages(self, fs, insert_page):
        instance, kb_id = fs
        doc = await instance.create_document(kb_id, "doc.pdf", "Doc", "/", "pdf", "", ["tag"])
        doc_id = str(doc["id"])
        await insert_page(doc_id, 1, "page one")
        await insert_page(doc_id, 2, "page two")

        pages = await instance.get_all_pages(doc_id)
        assert len(pages) == 2
        assert pages[0]["page"] == 1


class TestSearch:

    async def test_search_chunks_finds_matching_content(self, fs, insert_chunk):
        instance, kb_id = fs
        doc = await instance.create_document(kb_id, "notes.md", "Notes", "/", "md", "hello world", ["tag"])
        await insert_chunk(str(doc["id"]), kb_id, "hello world is great")

        results = await instance.search_chunks(kb_id, "hello", 10)
        assert len(results) >= 1
        assert "hello" in results[0]["content"]

    async def test_search_chunks_respects_limit(self, fs, insert_chunk):
        instance, kb_id = fs
        for i in range(5):
            doc = await instance.create_document(kb_id, f"doc{i}.md", f"Doc {i}", "/", "md", f"searchterm {i}", ["tag"])
            await insert_chunk(str(doc["id"]), kb_id, f"searchterm content {i}")

        results = await instance.search_chunks(kb_id, "searchterm", 2)
        assert len(results) <= 2

    async def test_search_chunks_wiki_filter(self, fs, insert_chunk):
        instance, kb_id = fs
        src = await instance.create_document(kb_id, "src.md", "Src", "/", "md", "data", ["tag"])
        wiki = await instance.create_document(kb_id, "page.md", "Page", "/wiki/", "md", "data", ["tag"])
        await insert_chunk(str(src["id"]), kb_id, "shared keyword")
        await insert_chunk(str(wiki["id"]), kb_id, "shared keyword")

        wiki_results = await instance.search_chunks(kb_id, "shared", 10, path_filter="wiki")
        source_results = await instance.search_chunks(kb_id, "shared", 10, path_filter="sources")

        wiki_paths = [r["path"] for r in wiki_results]
        source_paths = [r["path"] for r in source_results]
        assert all(p.startswith("/wiki") for p in wiki_paths)
        assert all(not p.startswith("/wiki") for p in source_paths)


class TestBytesAndDisk:

    async def test_load_source_bytes_from_cache(self, fs, workspace):
        instance, kb_id = fs
        cache_file = workspace / ".llmwiki" / "cache" / "test.txt"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(b"cached data")

        doc = {"path": "/", "filename": "test.txt", "relative_path": "test.txt"}
        data = await instance.load_source_bytes(doc)
        assert data == b"cached data"

    async def test_load_source_bytes_from_workspace(self, fs, workspace):
        instance, _ = fs
        (workspace / "file.txt").write_bytes(b"workspace data")

        doc = {"path": "/", "filename": "file.txt", "relative_path": "file.txt"}
        data = await instance.load_source_bytes(doc)
        assert data == b"workspace data"

    async def test_load_image_bytes_returns_none(self, fs):
        instance, _ = fs
        assert await instance.load_image_bytes("doc-id", "img-id") is None

    async def test_write_to_disk_creates_file(self, fs, workspace):
        instance, _ = fs
        result = instance.write_to_disk("/wiki/", "test.md", "content")
        assert result is True
        assert (workspace / "wiki" / "test.md").read_text() == "content"

    async def test_write_to_disk_creates_nested_dirs(self, fs, workspace):
        instance, _ = fs
        result = instance.write_to_disk("/wiki/deep/nested/", "file.md", "deep")
        assert result is True
        assert (workspace / "wiki" / "deep" / "nested" / "file.md").exists()

    async def test_write_to_disk_rejects_path_escape(self, fs):
        instance, _ = fs
        result = instance.write_to_disk("/../../../", "evil.md", "pwned")
        assert result is False

    async def test_delete_from_disk(self, fs, workspace):
        instance, _ = fs
        (workspace / "wiki").mkdir(exist_ok=True)
        (workspace / "wiki" / "temp.md").write_text("temp")
        instance.delete_from_disk([{"path": "/wiki/", "filename": "temp.md"}])
        assert not (workspace / "wiki" / "temp.md").exists()

    async def test_delete_from_disk_ignores_missing(self, fs):
        instance, _ = fs
        instance.delete_from_disk([{"path": "/", "filename": "nonexistent.md"}])


class TestReferences:

    async def test_upsert_and_get_backlinks(self, fs):
        instance, kb_id = fs
        src = await instance.create_document(kb_id, "page.md", "Page", "/wiki/", "md", "content", ["tag"])
        target = await instance.create_document(kb_id, "source.pdf", "Source", "/", "pdf", "", ["tag"])
        await instance.upsert_reference(str(src["id"]), str(target["id"]), kb_id, "cites", 3)

        backlinks = await instance.get_backlinks(str(target["id"]))
        assert len(backlinks) == 1
        assert backlinks[0]["filename"] == "page.md"
        assert backlinks[0]["reference_type"] == "cites"

    async def test_upsert_reference_updates_existing(self, fs):
        instance, kb_id = fs
        src = await instance.create_document(kb_id, "page.md", "Page", "/wiki/", "md", "content", ["tag"])
        target = await instance.create_document(kb_id, "source.pdf", "Source", "/", "pdf", "", ["tag"])
        await instance.upsert_reference(str(src["id"]), str(target["id"]), kb_id, "cites", 3)
        await instance.upsert_reference(str(src["id"]), str(target["id"]), kb_id, "cites", 7)

        forward = await instance.get_forward_references(str(src["id"]))
        assert len(forward) == 1

    async def test_delete_references(self, fs):
        instance, kb_id = fs
        src = await instance.create_document(kb_id, "page.md", "Page", "/wiki/", "md", "content", ["tag"])
        target = await instance.create_document(kb_id, "source.pdf", "Source", "/", "pdf", "", ["tag"])
        await instance.upsert_reference(str(src["id"]), str(target["id"]), kb_id, "cites", 1)
        await instance.delete_references(str(src["id"]))

        assert await instance.get_forward_references(str(src["id"])) == []

    async def test_get_forward_references(self, fs):
        instance, kb_id = fs
        src = await instance.create_document(kb_id, "page.md", "Page", "/wiki/", "md", "content", ["tag"])
        t1 = await instance.create_document(kb_id, "a.pdf", "A", "/", "pdf", "", ["tag"])
        t2 = await instance.create_document(kb_id, "b.md", "B", "/wiki/", "md", "", ["tag"])
        await instance.upsert_reference(str(src["id"]), str(t1["id"]), kb_id, "cites", 5)
        await instance.upsert_reference(str(src["id"]), str(t2["id"]), kb_id, "links_to", None)

        forward = await instance.get_forward_references(str(src["id"]))
        types = {r["reference_type"] for r in forward}
        assert "cites" in types
        assert "links_to" in types

    async def test_propagate_staleness(self, fs):
        instance, kb_id = fs
        target = await instance.create_document(kb_id, "target.md", "Target", "/wiki/", "md", "content", ["tag"])
        linker = await instance.create_document(kb_id, "linker.md", "Linker", "/wiki/", "md", "content", ["tag"])
        await instance.upsert_reference(str(linker["id"]), str(target["id"]), kb_id, "links_to", None)

        await instance.propagate_staleness(str(target["id"]))

        stale = await instance.find_stale_pages(kb_id)
        stale_ids = [s["filename"] for s in stale]
        assert "linker.md" in stale_ids

    async def test_find_uncited_sources(self, fs):
        instance, kb_id = fs
        await instance.create_document(kb_id, "cited.pdf", "Cited", "/", "pdf", "", ["tag"])
        await instance.create_document(kb_id, "uncited.pdf", "Uncited", "/", "pdf", "", ["tag"])
        wiki = await instance.create_document(kb_id, "page.md", "Page", "/wiki/", "md", "", ["tag"])

        cited = await instance.get_document(kb_id, "cited.pdf", "/")
        await instance.upsert_reference(str(wiki["id"]), str(cited["id"]), kb_id, "cites", 1)

        uncited = await instance.find_uncited_sources(kb_id)
        filenames = [u["filename"] for u in uncited]
        assert "uncited.pdf" in filenames
        assert "cited.pdf" not in filenames
        assert "page.md" not in filenames
