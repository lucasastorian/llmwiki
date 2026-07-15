"""Tier 2: list_comments tool flow (CommentsHandler → SqliteVaultFS)."""

import json

import pytest


def _make_kb(kb_id: str) -> dict:
    return {"id": kb_id, "name": "test-workspace", "slug": "test-workspace"}


def _highlight(
    highlight_id: str, comment: str | None, created_at: str,
    replies: list | None = None,
) -> dict:
    return {
        "id": highlight_id,
        "type": "text",
        "textAnchor": {"textStart": 0, "textEnd": 5, "textContent": "quote"},
        "comment": comment,
        "replies": replies or [],
        "createdAt": created_at,
    }


async def _create_doc(instance, kb_id: str, filename: str, dir_path: str, highlights: list[dict]) -> dict:
    doc = await instance.create_document(
        kb_id, filename, filename, dir_path, "md", "quote and more text", ["notes"],
    )
    from vaultfs.sqlite import SqliteVaultFS
    db = SqliteVaultFS._db_or_raise()
    await db.execute(
        "UPDATE documents SET highlights = ? WHERE id = ?",
        (json.dumps(highlights), str(doc["id"])),
    )
    await db.commit()
    return doc


class TestListComments:

    async def test_lists_newest_first_across_documents(self, fs):
        instance, kb_id = fs
        from tools.comments import CommentsHandler

        await _create_doc(instance, kb_id, "old.md", "/wiki/", [
            _highlight("h-old", "old note", "2026-01-01T00:00:00Z"),
        ])
        await _create_doc(instance, kb_id, "new.md", "/wiki/", [
            _highlight("h-new", "new note", "2026-07-01T00:00:00Z"),
        ])

        result = await CommentsHandler(instance, _make_kb(kb_id)).list_comments("**", 50)
        assert "2 comment thread(s)" in result
        assert result.index("h-new") < result.index("h-old")

    async def test_reply_activity_bumps_thread_to_top(self, fs):
        instance, kb_id = fs
        from tools.comments import CommentsHandler

        reply = {"id": "r1", "author": "user", "text": "still confused", "createdAt": "2026-07-08T00:00:00Z"}
        await _create_doc(instance, kb_id, "a.md", "/wiki/", [
            _highlight("h-a", "early note with late reply", "2026-01-01T00:00:00Z", replies=[reply]),
        ])
        await _create_doc(instance, kb_id, "b.md", "/wiki/", [
            _highlight("h-b", "mid note", "2026-06-01T00:00:00Z"),
        ])

        result = await CommentsHandler(instance, _make_kb(kb_id)).list_comments("**", 50)
        assert result.index("h-a") < result.index("h-b")

    async def test_glob_narrows_to_subtree(self, fs):
        instance, kb_id = fs
        from tools.comments import CommentsHandler

        await _create_doc(instance, kb_id, "page.md", "/wiki/", [
            _highlight("h-wiki", "wiki note", "2026-07-01T00:00:00Z"),
        ])
        await _create_doc(instance, kb_id, "source.md", "/", [
            _highlight("h-src", "source note", "2026-07-02T00:00:00Z"),
        ])

        result = await CommentsHandler(instance, _make_kb(kb_id)).list_comments("/wiki/**", 50)
        assert "h-wiki" in result
        assert "h-src" not in result

    async def test_reports_reply_status(self, fs):
        instance, kb_id = fs
        from tools.comments import CommentsHandler

        agent_reply = {"id": "r1", "author": "agent", "text": "reworked it", "createdAt": "2026-07-02T00:00:00Z"}
        user_after = {"id": "r2", "author": "user", "text": "still unclear", "createdAt": "2026-07-03T00:00:00Z"}
        await _create_doc(instance, kb_id, "answered.md", "/wiki/", [
            _highlight("h-done", "note", "2026-07-01T00:00:00Z", replies=[agent_reply]),
        ])
        await _create_doc(instance, kb_id, "reopened.md", "/wiki/", [
            _highlight("h-reopen", "note", "2026-07-01T00:00:00Z", replies=[dict(agent_reply), user_after]),
        ])

        result = await CommentsHandler(instance, _make_kb(kb_id)).list_comments("**", 50)
        done_line = next(l for l in result.split("\n") if "h-done" in l)
        reopen_line = next(l for l in result.split("\n") if "h-reopen" in l)
        assert "_replied_" in done_line
        assert "_needs reply_" in reopen_line

    async def test_bare_highlights_excluded(self, fs):
        instance, kb_id = fs
        from tools.comments import CommentsHandler

        await _create_doc(instance, kb_id, "bare.md", "/wiki/", [
            _highlight("h-bare", None, "2026-07-01T00:00:00Z"),
        ])

        result = await CommentsHandler(instance, _make_kb(kb_id)).list_comments("**", 50)
        assert "No comments found" in result

    async def test_limit_caps_output(self, fs):
        instance, kb_id = fs
        from tools.comments import CommentsHandler

        highlights = [
            _highlight(f"h-{i}", f"note {i}", f"2026-07-0{i}T00:00:00Z") for i in range(1, 4)
        ]
        await _create_doc(instance, kb_id, "many.md", "/wiki/", highlights)

        result = await CommentsHandler(instance, _make_kb(kb_id)).list_comments("**", 2)
        assert "3 comment thread(s)" in result
        assert "showing 2" in result
        assert "h-3" in result and "h-2" in result and "h-1" not in result
