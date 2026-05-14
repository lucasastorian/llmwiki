"""Tier 2: End-to-end tool handler tests (tool → handler → VaultFS).

Tests the full flow through WriteHandler, ReadHandler, SearchHandler, DeleteHandler.
Uses SqliteVaultFS with a temp workspace — no Postgres needed.
"""

import pytest
from tests.integration.mcp.conftest import TEST_USER_ID


def _make_kb(kb_id: str) -> dict:
    return {"id": kb_id, "name": "test-workspace", "slug": "test-workspace"}


class TestWriteReadFlow:

    async def test_create_then_read_round_trip(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler
        from tools.read import ReadHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        reader = ReadHandler(instance, kb)

        result = await writer.create("/", "My Notes", "Hello world", ["notes"], "", False)
        assert "Created **My Notes**" in result
        assert "`/my-notes.md`" in result

        content = await reader.read("my-notes.md", "", None, False)
        assert "Hello world" in content

    async def test_create_wiki_page_with_citation_hint(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler

        writer = WriteHandler(instance, _make_kb(kb_id))
        result = await writer.create("/wiki/", "Concepts", "# Concepts", ["overview"], "", False)
        assert "cite sources" in result.lower() or "footnotes" in result.lower()

    async def test_create_rejects_missing_title(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler

        writer = WriteHandler(instance, _make_kb(kb_id))
        result = await writer.create("/", "", "content", ["tag"], "", False)
        assert "title is required" in result

    async def test_create_rejects_missing_tags(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler

        writer = WriteHandler(instance, _make_kb(kb_id))
        result = await writer.create("/", "Title", "content", [], "", False)
        assert "tag is required" in result

    async def test_create_rejects_duplicate_without_overwrite(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler

        writer = WriteHandler(instance, _make_kb(kb_id))
        await writer.create("/", "Dup", "v1", ["tag"], "", False)
        result = await writer.create("/", "Dup", "v2", ["tag"], "", False)
        assert "already exists" in result

    async def test_create_with_overwrite_replaces_content(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler
        from tools.read import ReadHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        reader = ReadHandler(instance, kb)

        await writer.create("/", "Replace Me", "old content", ["tag"], "", False)
        result = await writer.create("/", "Replace Me", "new content", ["tag"], "", True)
        assert "Created" in result

        content = await reader.read("replace-me.md", "", None, False)
        assert "new content" in content

    async def test_edit_replaces_text(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler
        from tools.read import ReadHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        reader = ReadHandler(instance, kb)

        await writer.create("/", "Editable", "Hello world, this is a test.", ["tag"], "", False)
        result = await writer.edit("editable.md", "Hello world", "Goodbye world", None)
        assert "Replaced 1 occurrence" in result

        content = await reader.read("editable.md", "", None, False)
        assert "Goodbye world" in content
        assert "Hello world" not in content

    async def test_edit_rejects_no_match(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler

        writer = WriteHandler(instance, _make_kb(kb_id))
        await writer.create("/", "Doc", "actual content", ["tag"], "", False)
        result = await writer.edit("doc.md", "nonexistent text", "replacement", None)
        assert "no match" in result.lower()

    async def test_edit_rejects_multiple_matches(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler

        writer = WriteHandler(instance, _make_kb(kb_id))
        await writer.create("/", "Repeat", "foo bar foo bar", ["tag"], "", False)
        result = await writer.edit("repeat.md", "foo", "baz", None)
        assert "2 matches" in result

    async def test_append_adds_content(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler
        from tools.read import ReadHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        reader = ReadHandler(instance, kb)

        await writer.create("/", "Log", "Entry 1", ["log"], "", False)
        result = await writer.append("log.md", "Entry 2", None)
        assert "Appended" in result

        content = await reader.read("log.md", "", None, False)
        assert "Entry 1" in content
        assert "Entry 2" in content

    async def test_append_missing_document(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler

        writer = WriteHandler(instance, _make_kb(kb_id))
        result = await writer.append("nonexistent.md", "content", None)
        assert "not found" in result.lower()


class TestReadModes:

    async def test_read_falls_back_to_title(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler
        from tools.read import ReadHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        reader = ReadHandler(instance, kb)

        await writer.create("/wiki/", "Deep Topic", "content here", ["tag"], "", False)
        result = await reader.read("Deep Topic", "", None, False)
        assert "content here" in result

    async def test_read_sections_filters_headings(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler
        from tools.read import ReadHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        reader = ReadHandler(instance, kb)

        content = "# Intro\nIntro text\n\n## Methods\nMethods text\n\n## Results\nResults text"
        await writer.create("/", "Paper", content, ["tag"], "", False)
        result = await reader.read("paper.md", "", ["Methods"], False)
        assert "Methods text" in result
        assert "Results text" not in result

    async def test_read_glob_batch(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler
        from tools.read import ReadHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        reader = ReadHandler(instance, kb)

        await writer.create("/wiki/", "A Page", "aaa", ["tag"], "", False)
        await writer.create("/wiki/", "B Page", "bbb", ["tag"], "", False)
        await writer.create("/", "Source", "src", ["tag"], "", False)

        result = await reader.read("/wiki/**", "", None, False)
        assert "aaa" in result or "a-page" in result
        assert "bbb" in result or "b-page" in result

    async def test_read_pages(self, fs, insert_page):
        instance, kb_id = fs
        from tools.read import ReadHandler

        doc = await instance.create_document(kb_id, "report.pdf", "Report", "/", "pdf", "", ["tag"])
        doc_id = str(doc["id"])
        await insert_page(doc_id, 1, "Page one content")
        await insert_page(doc_id, 2, "Page two content")

        from vaultfs.sqlite import SqliteVaultFS
        db = SqliteVaultFS._db_or_raise()
        await db.execute("UPDATE documents SET page_count = 2 WHERE id = ?", (doc_id,))
        await db.commit()

        reader = ReadHandler(instance, _make_kb(kb_id))
        result = await reader.read("report.pdf", "1-2", None, False)
        assert "Page one content" in result
        assert "Page two content" in result

    async def test_read_backlinks_shown(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler
        from tools.read import ReadHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        reader = ReadHandler(instance, kb)

        target = await instance.create_document(kb_id, "target.md", "Target", "/wiki/", "md", "target content", ["tag"])
        source = await instance.create_document(kb_id, "source.md", "Source", "/wiki/", "md", "links to target", ["tag"])
        await instance.upsert_reference(str(source["id"]), str(target["id"]), kb_id, "links_to", None)

        result = await reader.read("wiki/target.md", "", None, False)
        assert "Referenced by" in result


class TestSearchDeleteLifecycle:

    async def test_search_list_groups_sources_and_wiki(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler
        from tools.search import SearchHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        searcher = SearchHandler(instance, kb)

        await writer.create("/", "Source Doc", "src", ["data"], "", False)
        await writer.create("/wiki/", "Wiki Page", "wiki", ["overview"], "", False)

        result = await searcher.list_documents("*", None)
        assert "Sources" in result
        assert "Wiki" in result

    async def test_search_list_filters_by_tags(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler
        from tools.search import SearchHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        searcher = SearchHandler(instance, kb)

        await writer.create("/", "Tagged", "content", ["special"], "", False)
        await writer.create("/", "Other", "content", ["normal"], "", False)

        result = await searcher.list_documents("*", ["special"])
        assert "tagged" in result.lower()
        assert "other" not in result.lower()

    async def test_search_chunks_after_indexing(self, fs, insert_chunk):
        instance, kb_id = fs
        from tools.write import WriteHandler
        from tools.search import SearchHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        searcher = SearchHandler(instance, kb)

        await writer.create("/", "Searchable", "quantum computing research", ["science"], "", False)
        doc = await instance.get_document(kb_id, "searchable.md", "/")
        await insert_chunk(str(doc["id"]), kb_id, "quantum computing is transformative research")

        result = await searcher.search_chunks("quantum", "*", None, 10)
        assert "quantum" in result.lower()

    async def test_search_references_uncited(self, fs):
        instance, kb_id = fs
        from tools.search import SearchHandler

        await instance.create_document(kb_id, "uncited.pdf", "Uncited", "/", "pdf", "", ["tag"])
        searcher = SearchHandler(instance, _make_kb(kb_id))
        result = await searcher.query_references("*", "uncited")
        assert "uncited.pdf" in result

    async def test_delete_exact_path(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler
        from tools.delete import DeleteHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        deleter = DeleteHandler(instance, kb)

        await writer.create("/", "Doomed", "content", ["tag"], "", False)
        result = await deleter.delete("doomed.md")
        assert "Deleted" in result

        assert await instance.get_document(kb_id, "doomed.md", "/") is None

    async def test_delete_glob_skips_protected(self, fs):
        instance, kb_id = fs
        from tools.delete import DeleteHandler

        await instance.create_document(kb_id, "overview.md", "Overview", "/wiki/", "md", "overview", ["tag"])
        await instance.create_document(kb_id, "log.md", "Log", "/wiki/", "md", "log", ["tag"])
        await instance.create_document(kb_id, "extra.md", "Extra", "/wiki/", "md", "extra", ["tag"])

        deleter = DeleteHandler(instance, _make_kb(kb_id))
        result = await deleter.delete("/wiki/*")
        assert "Skipped (protected)" in result
        assert "overview.md" in result or "log.md" in result

        assert await instance.get_document(kb_id, "overview.md", "/wiki/") is not None
        assert await instance.get_document(kb_id, "log.md", "/wiki/") is not None
        assert await instance.get_document(kb_id, "extra.md", "/wiki/") is None

    async def test_delete_rejects_global_wildcard(self, fs):
        instance, kb_id = fs
        from tools.delete import DeleteHandler

        deleter = DeleteHandler(instance, _make_kb(kb_id))
        for pattern in ("*", "**", "**/*"):
            result = await deleter.delete(pattern)
            assert "refusing" in result.lower()

    async def test_full_lifecycle(self, fs, insert_chunk):
        instance, kb_id = fs
        from tools.write import WriteHandler
        from tools.read import ReadHandler
        from tools.search import SearchHandler
        from tools.delete import DeleteHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        reader = ReadHandler(instance, kb)
        searcher = SearchHandler(instance, kb)
        deleter = DeleteHandler(instance, kb)

        create_result = await writer.create("/", "Lifecycle", "initial content", ["test"], "", False)
        assert "Created" in create_result

        read_result = await reader.read("lifecycle.md", "", None, False)
        assert "initial content" in read_result

        edit_result = await writer.edit("lifecycle.md", "initial content", "updated content", None)
        assert "Replaced 1" in edit_result

        read_result = await reader.read("lifecycle.md", "", None, False)
        assert "updated content" in read_result

        doc = await instance.get_document(kb_id, "lifecycle.md", "/")
        await insert_chunk(str(doc["id"]), kb_id, "updated content for lifecycle test")

        search_result = await searcher.search_chunks("lifecycle", "*", None, 10)
        assert "lifecycle" in search_result.lower()

        list_result = await searcher.list_documents("*", None)
        assert "lifecycle" in list_result.lower()

        delete_result = await deleter.delete("lifecycle.md")
        assert "Deleted" in delete_result

        assert await instance.get_document(kb_id, "lifecycle.md", "/") is None
