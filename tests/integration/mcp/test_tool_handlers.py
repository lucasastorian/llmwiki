"""Tool → handler → SqliteVaultFS end-to-end on a temp workspace."""

import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from mcp.server.elicitation import AcceptedElicitation
from mcp.types import ClientCapabilities


def _make_kb(kb_id: str) -> dict:
    return {"id": kb_id, "name": "test-workspace", "slug": "test-workspace"}


class _ElicitingSession:
    def check_client_capability(self, capability: ClientCapabilities) -> bool:
        return capability.elicitation is not None


class _AcceptDeleteContext:
    def __init__(self) -> None:
        self.request_context = SimpleNamespace(session=_ElicitingSession())

    async def elicit(
        self, message: str, schema: type[BaseModel]
    ) -> AcceptedElicitation[BaseModel]:
        return AcceptedElicitation(data=schema(confirm=True))


class TestWriteReadFlow:

    async def test_edit_tool_schema_uses_anthropic_string_names(self):
        from tools.write import register

        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp, lambda _ctx: "user", lambda _user_id: None)

        tools = await mcp.list_tools()
        tool = next(tool for tool in tools if tool.name == "edit")
        properties = tool.inputSchema["properties"]
        required = tool.inputSchema["required"]

        assert "old_string" in properties
        assert "new_string" in properties
        assert "old_string" in required
        assert "new_string" in required
        assert "old_text" not in properties
        assert "new_text" not in properties

    async def test_create_then_read_round_trip(self, fs):
        instance, kb_id = fs
        from tools.read import ReadHandler
        from tools.write import WriteHandler

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

    async def test_create_wiki_page_adds_frontmatter_from_args(self, fs):
        instance, kb_id = fs
        from tools.lint import LintHandler
        from tools.write import WriteHandler, _parse_frontmatter

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        linter = LintHandler(instance, kb)

        await writer.create(
            "/wiki/",
            "Auto Metadata",
            "A short synthesized page.",
            ["alpha", "beta"],
            "2026-06-15",
            False,
        )

        doc = await instance.get_document(kb_id, "auto-metadata.md", "/wiki/")
        meta = _parse_frontmatter(doc["content"])
        assert meta["title"] == "Auto Metadata"
        assert meta["description"] == "A short synthesized page."
        assert str(meta["date"]) == "2026-06-15"
        assert meta["tags"] == ["alpha", "beta"]

        result = await linter.run(path="/wiki/auto-metadata.md", include_graph=False)
        assert "Lint passed" in result

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

    async def test_create_uses_frontmatter_tags_as_index_source(self, fs):
        instance, kb_id = fs
        from tools.search import SearchHandler
        from tools.write import WriteHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        searcher = SearchHandler(instance, kb)

        await writer.create(
            "/wiki/",
            "Tagged From Frontmatter",
            "---\ntags: [frontmatter-tag]\n---\n\nBody",
            [],
            "",
            False,
        )

        result = await searcher.list_documents("*", ["frontmatter-tag"])
        assert "tagged-from-frontmatter.md" in result

    async def test_create_rejects_duplicate_without_overwrite(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler

        writer = WriteHandler(instance, _make_kb(kb_id))
        await writer.create("/", "Dup", "v1", ["tag"], "", False)
        result = await writer.create("/", "Dup", "v2", ["tag"], "", False)
        assert "already exists" in result

    async def test_create_with_overwrite_replaces_content(self, fs):
        instance, kb_id = fs
        from tools.read import ReadHandler
        from tools.write import WriteHandler

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
        from tools.read import ReadHandler
        from tools.write import WriteHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        reader = ReadHandler(instance, kb)

        await writer.create("/", "Editable", "Hello world, this is a test.", ["tag"], "", False)
        result = await writer.edit("editable.md", "Hello world", "Goodbye world")
        assert "Replaced 1 occurrence" in result

        content = await reader.read("editable.md", "", None, False)
        assert "Goodbye world" in content
        assert "Hello world" not in content

    async def test_edit_and_append_refuse_binary_sources(self, workspace, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler

        (workspace / "paper.pdf").write_bytes(b"%PDF-1.7 original bytes")
        await instance.create_document(kb_id, "paper.pdf", "Paper", "/", "pdf", "Extracted text.", ["source"])
        writer = WriteHandler(instance, _make_kb(kb_id))

        assert "read-only" in await writer.edit("/paper.pdf", "Extracted", "Changed")
        assert "read-only" in await writer.append("/paper.pdf", "more")
        assert (workspace / "paper.pdf").read_bytes() == b"%PDF-1.7 original bytes"

    async def test_edit_keeps_app_metadata_and_tracks_frontmatter_description(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler
        from vaultfs.sqlite import SqliteVaultFS

        writer = WriteHandler(instance, _make_kb(kb_id))
        page = "---\ndescription: First take\n---\n# Lesson\n\nBody text."
        await writer.create("/wiki/", "Lesson", page, ["course"], "", False)
        db = SqliteVaultFS._db_or_raise()
        await db.execute(
            "UPDATE documents SET metadata = json_set(metadata, '$.course', json('{\"status\":\"complete\"}'), "
            "'$.source_url', 'https://example.com') WHERE filename = 'lesson.md'",
        )
        await db.commit()

        await writer.edit("/wiki/lesson.md", "description: First take\n", "")

        cursor = await db.execute("SELECT metadata FROM documents WHERE filename = 'lesson.md'")
        metadata = json.loads((await cursor.fetchone())[0])
        assert metadata["course"] == {"status": "complete"}
        assert metadata["source_url"] == "https://example.com"
        assert "description" not in metadata

    async def test_create_refuses_unindexed_files_and_hidden_folders(self, workspace, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler

        writer = WriteHandler(instance, _make_kb(kb_id))
        (workspace / "notes").mkdir()
        (workspace / "notes" / "plan.md").write_text("my own file")

        clobber = await writer.create("/notes/", "Plan", "agent text", ["x"], "", False)
        hidden = await writer.create("/.claude/", "settings.json", '{"hooks": {}}', ["x"], "", False)

        assert "already exists on disk" in clobber
        assert (workspace / "notes" / "plan.md").read_text() == "my own file"
        assert "not writable" in hidden
        assert not (workspace / ".claude").exists()

    async def test_create_uses_the_filename_given_in_path(self, workspace, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler

        writer = WriteHandler(instance, _make_kb(kb_id))
        result = await writer.create("wiki/concepts/attention.md", "Attention Mechanisms", "# Attention", ["ml"], "", False)

        assert "`/wiki/concepts/attention.md`" in result
        assert (workspace / "wiki" / "concepts" / "attention.md").exists()
        doc = await instance.get_document(kb_id, "attention.md", "/wiki/concepts/")
        assert doc["title"] == "Attention Mechanisms"

    async def test_create_keeps_an_explicit_filename_verbatim(self, workspace, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler

        writer = WriteHandler(instance, _make_kb(kb_id))
        await writer.create("/notes/README.txt", "Readme", "plain text", ["x"], "", False)

        assert (workspace / "notes" / "README.txt").read_text().endswith("plain text")
        doc = await instance.get_document(kb_id, "README.txt", "/notes/")
        assert doc["file_type"] == "txt"

    async def test_edit_clears_the_pages_stale_flag(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler
        from vaultfs.sqlite import SqliteVaultFS

        writer = WriteHandler(instance, _make_kb(kb_id))
        await writer.create("/wiki/", "Topic", "# Topic\n\nOld claim.", ["x"], "", False)
        db = SqliteVaultFS._db_or_raise()
        await db.execute("UPDATE documents SET stale_since = datetime('now') WHERE filename = 'topic.md'")
        await db.commit()

        await writer.edit("/wiki/topic.md", "Old claim.", "New claim.")

        cursor = await db.execute("SELECT stale_since FROM documents WHERE filename = 'topic.md'")
        assert (await cursor.fetchone())[0] is None

    async def test_named_footnote_citations_become_graph_edges(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler

        source = await instance.create_document(kb_id, "paper.pdf", "Paper", "/", "pdf", "", ["source"])
        writer = WriteHandler(instance, _make_kb(kb_id))
        await writer.create("/wiki/", "Findings", "# Findings\n\nClaim.[^smith2020]\n\n[^smith2020]: paper.pdf, p.3", ["x"], "", False)

        backlinks = await instance.get_backlinks(str(source["id"]))
        assert [b["reference_type"] for b in backlinks] == ["cites"]

    async def test_edit_rejects_no_match(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler

        writer = WriteHandler(instance, _make_kb(kb_id))
        await writer.create("/", "Doc", "actual content", ["tag"], "", False)
        result = await writer.edit("doc.md", "nonexistent text", "replacement")
        assert "no match" in result.lower()

    async def test_edit_rejects_multiple_matches(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler

        writer = WriteHandler(instance, _make_kb(kb_id))
        await writer.create("/", "Repeat", "foo bar foo bar", ["tag"], "", False)
        result = await writer.edit("repeat.md", "foo", "baz")
        assert "2 matches" in result

    async def test_edit_keeps_index_synced_to_frontmatter_tags(self, fs):
        instance, kb_id = fs
        from tools.search import SearchHandler
        from tools.write import WriteHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        searcher = SearchHandler(instance, kb)

        await writer.create(
            "/wiki/",
            "Metadata Tags",
            "---\ntags: [frontmatter-tag]\n---\n\nold body",
            ["arg-tag"],
            "",
            False,
        )
        await writer.edit("wiki/metadata-tags.md", "old body", "new body")

        assert "metadata-tags.md" in await searcher.list_documents("*", ["frontmatter-tag"])
        assert "metadata-tags.md" not in await searcher.list_documents("*", ["arg-tag"])

    async def test_append_adds_content(self, fs):
        instance, kb_id = fs
        from tools.read import ReadHandler
        from tools.write import WriteHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        reader = ReadHandler(instance, kb)

        await writer.create("/", "Log", "Entry 1", ["log"], "", False)
        result = await writer.append("log.md", "Entry 2")
        assert "Appended" in result

        content = await reader.read("log.md", "", None, False)
        assert "Entry 1" in content
        assert "Entry 2" in content

    async def test_append_inserts_before_trailing_footnotes(self, fs):
        instance, kb_id = fs
        from tools.read import ReadHandler
        from tools.write import WriteHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        reader = ReadHandler(instance, kb)

        await writer.create(
            "/wiki/",
            "Footnoted",
            "Body text.[^1]\n\n[^1]: source.pdf, p.3",
            ["wiki"],
            "",
            False,
        )
        result = await writer.append("wiki/footnoted.md", "## New Section\n\nMore body.")
        assert "Appended" in result

        content = await reader.read("wiki/footnoted.md", "", None, False)
        assert content.index("## New Section") < content.index("[^1]: source.pdf")

    async def test_append_renumbers_colliding_footnotes(self, fs):
        instance, kb_id = fs
        from tools.read import ReadHandler
        from tools.write import WriteHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        reader = ReadHandler(instance, kb)

        await writer.create(
            "/wiki/",
            "Footnote Collision",
            "Existing claim.[^1]\n\n[^1]: first.pdf, p.1",
            ["wiki"],
            "",
            False,
        )
        await writer.append(
            "wiki/footnote-collision.md",
            "New claim.[^1]\n\n[^1]: second.pdf, p.2",
        )

        content = await reader.read("wiki/footnote-collision.md", "", None, False)
        assert "Existing claim.[^1]" in content
        assert "New claim.[^2]" in content
        assert "[^1]: first.pdf, p.1" in content
        assert "[^2]: second.pdf, p.2" in content

    async def test_append_keeps_index_synced_to_frontmatter_tags(self, fs):
        instance, kb_id = fs
        from tools.search import SearchHandler
        from tools.write import WriteHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        searcher = SearchHandler(instance, kb)

        await writer.create(
            "/wiki/",
            "Append Metadata",
            "---\ntags: [frontmatter-tag]\n---\n\nBody",
            ["arg-tag"],
            "",
            False,
        )
        await writer.append("wiki/append-metadata.md", "More body")

        assert "append-metadata.md" in await searcher.list_documents("*", ["frontmatter-tag"])
        assert "append-metadata.md" not in await searcher.list_documents("*", ["arg-tag"])

    async def test_append_missing_document(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler

        writer = WriteHandler(instance, _make_kb(kb_id))
        result = await writer.append("nonexistent.md", "content")
        assert "not found" in result.lower()


class TestLintTool:

    async def test_lint_passes_clean_wiki_page(self, fs):
        instance, kb_id = fs
        from tools.lint import LintHandler
        from tools.write import WriteHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        linter = LintHandler(instance, kb)

        await instance.create_document(kb_id, "source.pdf", "Source", "/", "pdf", "", ["source"])
        await writer.create(
            "/wiki/",
            "Good Page",
            (
                "---\n"
                "title: Good Page\n"
                "description: A properly cited page.\n"
                "date: 2026-05-31\n"
                "tags: [alpha, beta]\n"
                "---\n\n"
                "A sourced claim.[^1]\n\n"
                "[^1]: source.pdf, p.1"
            ),
            [],
            "",
            False,
        )

        result = await linter.run(path="/wiki/good-page.md")
        assert "Lint passed" in result

    async def test_lint_reports_missing_frontmatter(self, fs):
        instance, kb_id = fs
        from tools.lint import LintHandler

        kb = _make_kb(kb_id)
        linter = LintHandler(instance, kb)

        await instance.create_document(kb_id, "bad.md", "Bad", "/wiki/", "md", "No frontmatter", ["tag"])

        result = await linter.run(path="/wiki/bad.md", include_graph=False)
        assert "missing-frontmatter" in result

    async def test_lint_reports_metadata_mismatch(self, fs):
        instance, kb_id = fs
        from tools.lint import LintHandler

        kb = _make_kb(kb_id)
        linter = LintHandler(instance, kb)

        await instance.create_document(
            kb_id,
            "mismatch.md",
            "Mismatch",
            "/wiki/",
            "md",
            (
                "---\n"
                "title: Mismatch\n"
                "description: Metadata mismatch.\n"
                "date: 2026-05-31\n"
                "tags: [frontmatter, canonical]\n"
                "---\n\n"
                "Body"
            ),
            ["indexed-only"],
            date="2026-01-01",
        )

        result = await linter.run(path="/wiki/mismatch.md", include_graph=False)
        assert "tag-index-mismatch" in result
        assert "date-index-mismatch" in result

    async def test_lint_reports_footnote_hygiene(self, fs):
        instance, kb_id = fs
        from tools.lint import LintHandler

        kb = _make_kb(kb_id)
        linter = LintHandler(instance, kb)

        await instance.create_document(
            kb_id,
            "footnotes.md",
            "Footnotes",
            "/wiki/",
            "md",
            (
                "---\n"
                "title: Footnotes\n"
                "description: Broken footnotes.\n"
                "date: 2026-05-31\n"
                "tags: [alpha, beta]\n"
                "---\n\n"
                "Claim one.[^1]\n"
                "Claim two.[^1]\n"
                "Missing definition.[^2]\n\n"
                "[^1]: source.pdf, p.1\n"
                "[^1]: other.pdf, p.2\n\n"
                "## More body"
            ),
            ["alpha", "beta"],
        )

        result = await linter.run(path="/wiki/footnotes.md", include_graph=False)
        assert "duplicate-footnote" in result
        assert "footnote-without-definition" in result
        assert "footnotes-not-at-tail" in result

    async def test_lint_reports_dangling_link_and_unresolved_citation(self, fs):
        instance, kb_id = fs
        from tools.lint import LintHandler

        kb = _make_kb(kb_id)
        linter = LintHandler(instance, kb)

        await instance.create_document(
            kb_id,
            "broken-links.md",
            "Broken Links",
            "/wiki/",
            "md",
            (
                "---\n"
                "title: Broken Links\n"
                "description: Broken references.\n"
                "date: 2026-05-31\n"
                "tags: [alpha, beta]\n"
                "---\n\n"
                "See [Missing](missing.md). Claim.[^1]\n\n"
                "[^1]: missing.pdf, p.1"
            ),
            ["alpha", "beta"],
        )

        result = await linter.run(path="/wiki/broken-links.md", include_graph=False)
        assert "dangling-link" in result
        assert "unresolved-citation" in result

    async def test_lint_reports_citation_graph_mismatch(self, fs):
        instance, kb_id = fs
        from tools.lint import LintHandler

        kb = _make_kb(kb_id)
        linter = LintHandler(instance, kb)

        await instance.create_document(kb_id, "source.pdf", "Source", "/", "pdf", "", ["source"])
        await instance.create_document(
            kb_id,
            "unsynced.md",
            "Unsynced",
            "/wiki/",
            "md",
            (
                "---\n"
                "title: Unsynced\n"
                "description: Citation graph was not synced.\n"
                "date: 2026-05-31\n"
                "tags: [alpha, beta]\n"
                "---\n\n"
                "Claim.[^1]\n\n"
                "[^1]: source.pdf, p.1"
            ),
            ["alpha", "beta"],
            date="2026-05-31",
        )

        result = await linter.run(path="/wiki/unsynced.md")
        assert "citation-graph-mismatch" in result

    async def test_lint_glob_path_narrows_to_subtree(self, fs):
        instance, kb_id = fs
        from tools.lint import LintHandler

        kb = _make_kb(kb_id)
        linter = LintHandler(instance, kb)

        await instance.create_document(kb_id, "top.md", "Top", "/wiki/", "md", "no frontmatter", ["tag"])
        await instance.create_document(kb_id, "nested.md", "Nested", "/wiki/concepts/", "md", "no frontmatter", ["tag"])

        result = await linter.run(path="/wiki/concepts/*.md", include_graph=False)
        assert "/wiki/concepts/nested.md" in result
        assert "/wiki/top.md" not in result

    async def test_lint_scope_sources_skips_wiki_pages(self, fs):
        instance, kb_id = fs
        from tools.lint import LintHandler

        kb = _make_kb(kb_id)
        linter = LintHandler(instance, kb)

        await instance.create_document(kb_id, "source.pdf", "Source", "/", "pdf", "", ["source"])
        await instance.create_document(kb_id, "broken.md", "Broken", "/wiki/", "md", "no frontmatter", ["tag"])

        result = await linter.run(scope="sources", include_graph=False)
        assert "missing-frontmatter" not in result
        assert "Lint passed" in result

    async def test_lint_include_graph_false_skips_graph_checks(self, fs):
        instance, kb_id = fs
        from tools.lint import LintHandler

        kb = _make_kb(kb_id)
        linter = LintHandler(instance, kb)

        # Graph-only issues (uncited source, stale page) must not appear with include_graph=False.
        await instance.create_document(kb_id, "uncited.pdf", "Uncited", "/", "pdf", "", ["source"])
        await instance.create_document(
            kb_id,
            "lonely.md",
            "Lonely",
            "/wiki/",
            "md",
            (
                "---\n"
                "title: Lonely\n"
                "description: A page with no backlinks.\n"
                "date: 2026-05-31\n"
                "tags: [alpha, beta]\n"
                "---\n\n"
                "Body"
            ),
            ["alpha", "beta"],
            date="2026-05-31",
        )

        result = await linter.run(include_graph=False)
        assert "uncited-source" not in result
        assert "orphan-page" not in result

    async def test_lint_reports_orphan_page(self, fs):
        instance, kb_id = fs
        from tools.lint import LintHandler

        kb = _make_kb(kb_id)
        linter = LintHandler(instance, kb)

        # Two non-root wiki pages, neither linked to. The one we lint is an orphan.
        await instance.create_document(kb_id, "other.md", "Other", "/wiki/", "md", "Other body", ["alpha", "beta"])
        await instance.create_document(
            kb_id,
            "orphan.md",
            "Orphan",
            "/wiki/",
            "md",
            (
                "---\n"
                "title: Orphan\n"
                "description: No incoming links.\n"
                "date: 2026-05-31\n"
                "tags: [alpha, beta]\n"
                "---\n\n"
                "Body"
            ),
            ["alpha", "beta"],
            date="2026-05-31",
        )

        result = await linter.run(path="/wiki/orphan.md")
        assert "orphan-page" in result

    async def test_lint_exempts_log_ledger_from_frontmatter(self, fs):
        instance, kb_id = fs
        from tools.lint import LintHandler

        kb = _make_kb(kb_id)
        linter = LintHandler(instance, kb)

        # The append-only ledger carries no frontmatter by design.
        await instance.create_document(
            kb_id, "log.md", "Log", "/wiki/", "md",
            "## [2026-05-31] ingest | Source\n\nRecorded an ingest.", ["log"],
        )

        result = await linter.run(path="/wiki/log.md", include_graph=False)
        assert "missing-frontmatter" not in result
        assert "Lint passed" in result


class TestReadModes:

    async def test_read_falls_back_to_title(self, fs):
        instance, kb_id = fs
        from tools.read import ReadHandler
        from tools.write import WriteHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        reader = ReadHandler(instance, kb)

        await writer.create("/wiki/", "Deep Topic", "content here", ["tag"], "", False)
        result = await reader.read("Deep Topic", "", None, False)
        assert "content here" in result

    async def test_read_sections_filters_headings(self, fs):
        instance, kb_id = fs
        from tools.read import ReadHandler
        from tools.write import WriteHandler

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
        from tools.read import ReadHandler
        from tools.write import WriteHandler

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

    async def test_read_pages_returns_extracted_page_images(self, workspace, fs, insert_page):
        instance, kb_id = fs
        from tools.read import ReadHandler
        from vaultfs.sqlite import SqliteVaultFS

        png = b"\x89PNG\r\n\x1a\nfake-image-bytes"
        doc = await instance.create_document(kb_id, "paper.pdf", "Paper", "/", "pdf", "", ["source"])
        asset = await instance.create_document(
            kb_id, "page-001-image-01.png", "Figure", "/paper.assets/", "png", "", ["asset"],
        )
        (workspace / "paper.assets").mkdir()
        (workspace / "paper.assets" / "page-001-image-01.png").write_bytes(png)
        await insert_page(
            str(doc["id"]), 1, "Figure 1 shows the result.",
            {"images": [{"id": str(asset["id"]), "filename": "page-001-image-01.png"}]},
        )
        db = SqliteVaultFS._db_or_raise()
        await db.execute("UPDATE documents SET page_count = 1 WHERE id = ?", (str(doc["id"]),))
        await db.commit()

        result = await ReadHandler(instance, _make_kb(kb_id)).read("paper.pdf", "1", None, True)

        images = [block for block in result if getattr(block, "type", None) == "image"]
        assert len(images) == 1
        assert images[0].mimeType == "image/png"

    async def test_read_pages_materializes_only_selected_page_annotations(self, fs, insert_page):
        instance, kb_id = fs
        from tools.read import ReadHandler

        doc = await instance.create_document(kb_id, "annotated.pdf", "Annotated", "/", "pdf", "", [])
        doc_id = str(doc["id"])
        await insert_page(doc_id, 1, "First page")
        await insert_page(doc_id, 2, "Second page")

        highlights = [
            {"id": "h1", "type": "pdf", "pdfAnchor": {"page": 1, "textContent": "first quote"}, "comment": "keep"},
            {"id": "h2", "type": "pdf", "pdfAnchor": {"page": 2, "textContent": "second quote"}, "comment": "omit"},
        ]
        from vaultfs.sqlite import SqliteVaultFS
        db = SqliteVaultFS._db_or_raise()
        await db.execute(
            "UPDATE documents SET page_count = 2, highlights = ? WHERE id = ?",
            (json.dumps(highlights), doc_id),
        )
        await db.commit()

        result = await ReadHandler(instance, _make_kb(kb_id)).read(
            "annotated.pdf", "1", None, False,
        )
        assert "first quote" in result
        assert "keep" in result
        assert "second quote" not in result
        assert "omit" not in result

    async def test_read_backlinks_shown(self, fs):
        instance, kb_id = fs
        from tools.read import ReadHandler

        kb = _make_kb(kb_id)
        reader = ReadHandler(instance, kb)

        target = await instance.create_document(kb_id, "target.md", "Target", "/wiki/", "md", "target content", ["tag"])
        source = await instance.create_document(kb_id, "source.md", "Source", "/wiki/", "md", "links to target", ["tag"])
        await instance.replace_references(str(source["id"]), kb_id, [(str(target["id"]), "links_to", None)])

        result = await reader.read("wiki/target.md", "", None, False)
        assert "Referenced by" in result


class TestSearchDeleteLifecycle:

    async def test_search_list_groups_sources_and_wiki(self, fs):
        instance, kb_id = fs
        from tools.search import SearchHandler
        from tools.write import WriteHandler

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
        from tools.search import SearchHandler
        from tools.write import WriteHandler

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
        from tools.search import SearchHandler
        from tools.write import WriteHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        searcher = SearchHandler(instance, kb)

        await writer.create("/", "Searchable", "quantum computing research", ["science"], "", False)
        doc = await instance.get_document(kb_id, "searchable.md", "/")
        await insert_chunk(str(doc["id"]), kb_id, "quantum computing is transformative research")

        result = await searcher.search_chunks("quantum", "*", None, 10)
        assert "quantum" in result.lower()

    async def test_search_chunks_respects_file_glob(self, fs, insert_chunk):
        instance, kb_id = fs
        from tools.search import SearchHandler

        searcher = SearchHandler(instance, _make_kb(kb_id))

        await instance.create_document(kb_id, "paper.pdf", "Paper", "/", "pdf", "", ["science"])
        await instance.create_document(kb_id, "notes.md", "Notes", "/", "md", "", ["science"])
        pdf = await instance.get_document(kb_id, "paper.pdf", "/")
        md = await instance.get_document(kb_id, "notes.md", "/")
        await insert_chunk(str(pdf["id"]), kb_id, "quantum entanglement in the paper")
        await insert_chunk(str(md["id"]), kb_id, "quantum notes here")

        result = await searcher.search_chunks("quantum", "*.pdf", None, 10)
        assert "paper.pdf" in result
        assert "notes.md" not in result

    async def test_search_references_uncited(self, fs):
        instance, kb_id = fs
        from tools.search import SearchHandler

        await instance.create_document(kb_id, "uncited.pdf", "Uncited", "/", "pdf", "", ["tag"])
        searcher = SearchHandler(instance, _make_kb(kb_id))
        result = await searcher.query_references("*", "uncited")
        assert "uncited.pdf" in result

    async def test_delete_exact_path(self, fs):
        instance, kb_id = fs
        from tools.delete import DeleteHandler
        from tools.write import WriteHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        deleter = DeleteHandler(instance, kb)

        await writer.create("/", "Doomed", "content", ["tag"], "", False)
        result = await deleter.delete(_AcceptDeleteContext(), "doomed.md")
        assert "Deleted" in result

        assert await instance.get_document(kb_id, "doomed.md", "/") is None

    async def test_delete_glob_skips_protected(self, fs):
        instance, kb_id = fs
        from tools.delete import DeleteHandler

        await instance.create_document(kb_id, "overview.md", "Overview", "/wiki/", "md", "overview", ["tag"])
        await instance.create_document(kb_id, "log.md", "Log", "/wiki/", "md", "log", ["tag"])
        await instance.create_document(kb_id, "extra.md", "Extra", "/wiki/", "md", "extra", ["tag"])

        deleter = DeleteHandler(instance, _make_kb(kb_id))
        result = await deleter.delete(_AcceptDeleteContext(), "/wiki/*")
        assert "Skipped (protected)" in result
        assert "overview.md" in result or "log.md" in result

        assert await instance.get_document(kb_id, "overview.md", "/wiki/") is not None
        assert await instance.get_document(kb_id, "log.md", "/wiki/") is not None
        assert await instance.get_document(kb_id, "extra.md", "/wiki/") is None

    @pytest.mark.parametrize("pattern", ["*", "**", "**/*", "/*", "/**"])
    async def test_delete_accepts_global_wildcard_after_approval(self, fs, pattern):
        instance, kb_id = fs
        from tools.delete import DeleteHandler

        await instance.create_document(kb_id, "root.md", "Root", "/", "md", "root", ["tag"])
        await instance.create_document(kb_id, "nested.md", "Nested", "/wiki/", "md", "nested", ["tag"])
        deleter = DeleteHandler(instance, _make_kb(kb_id))
        result = await deleter.delete(_AcceptDeleteContext(), pattern)

        assert "Deleted 2 document(s)" in result
        assert await instance.get_document(kb_id, "root.md", "/") is None
        assert await instance.get_document(kb_id, "nested.md", "/wiki/") is None

    async def test_full_lifecycle(self, fs, insert_chunk):
        instance, kb_id = fs
        from tools.delete import DeleteHandler
        from tools.read import ReadHandler
        from tools.search import SearchHandler
        from tools.write import WriteHandler

        kb = _make_kb(kb_id)
        writer = WriteHandler(instance, kb)
        reader = ReadHandler(instance, kb)
        searcher = SearchHandler(instance, kb)
        deleter = DeleteHandler(instance, kb)

        create_result = await writer.create("/", "Lifecycle", "initial content", ["test"], "", False)
        assert "Created" in create_result

        read_result = await reader.read("lifecycle.md", "", None, False)
        assert "initial content" in read_result

        edit_result = await writer.edit("lifecycle.md", "initial content", "updated content")
        assert "Replaced 1" in edit_result

        read_result = await reader.read("lifecycle.md", "", None, False)
        assert "updated content" in read_result

        doc = await instance.get_document(kb_id, "lifecycle.md", "/")
        await insert_chunk(str(doc["id"]), kb_id, "updated content for lifecycle test")

        search_result = await searcher.search_chunks("lifecycle", "*", None, 10)
        assert "lifecycle" in search_result.lower()

        list_result = await searcher.list_documents("*", None)
        assert "lifecycle" in list_result.lower()

        delete_result = await deleter.delete(_AcceptDeleteContext(), "lifecycle.md")
        assert "Deleted" in delete_result

        assert await instance.get_document(kb_id, "lifecycle.md", "/") is None
