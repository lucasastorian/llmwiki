"""Tier 2: reply_to_comment tool flow (ReplyHandler → SqliteVaultFS)."""

import json

import pytest


def _make_kb(kb_id: str) -> dict:
    return {"id": kb_id, "name": "test-workspace", "slug": "test-workspace"}


def _highlight(highlight_id: str, comment: str | None, replies: list | None = None) -> dict:
    entry = {
        "id": highlight_id,
        "type": "text",
        "textAnchor": {
            "textStart": 0,
            "textEnd": 11,
            "textContent": "Hello world",
        },
        "comment": comment,
        "color": "yellow",
        "createdAt": "2026-07-09T00:00:00Z",
    }
    if replies is not None:
        entry["replies"] = replies
    return entry


async def _create_doc_with_highlights(instance, kb_id: str, highlights: list[dict]) -> dict:
    doc = await instance.create_document(
        kb_id, "notes.md", "Notes", "/", "md", "Hello world, this is a page.", ["notes"],
    )
    from vaultfs.sqlite import SqliteVaultFS
    db = SqliteVaultFS._db_or_raise()
    await db.execute(
        "UPDATE documents SET highlights = ? WHERE id = ?",
        (json.dumps(highlights), str(doc["id"])),
    )
    await db.commit()
    return doc


class TestReplyTool:

    async def test_reply_persists_and_bumps_version(self, fs):
        instance, kb_id = fs
        from tools.reply import ReplyHandler

        await _create_doc_with_highlights(instance, kb_id, [_highlight("h1", "what does this mean?")])
        handler = ReplyHandler(instance, _make_kb(kb_id))

        result = await handler.reply("notes.md", "h1", "I expanded the intro with an example.")
        assert "Replied to highlight" in result
        assert "1 reply" in result

        doc = await instance.get_document(kb_id, "notes.md", "/")
        highlights = doc["highlights"]
        assert isinstance(highlights, list)
        replies = highlights[0]["replies"]
        assert len(replies) == 1
        assert replies[0]["author"] == "agent"
        assert replies[0]["text"] == "I expanded the intro with an example."
        assert replies[0]["id"]
        assert doc["version"] >= 1

    async def test_reply_appends_to_existing_thread(self, fs):
        instance, kb_id = fs
        from tools.reply import ReplyHandler

        existing = [{"id": "r1", "author": "agent", "text": "first", "createdAt": "2026-07-09T00:00:00Z"}]
        await _create_doc_with_highlights(instance, kb_id, [_highlight("h1", "why?", replies=existing)])
        handler = ReplyHandler(instance, _make_kb(kb_id))

        result = await handler.reply("notes.md", "h1", "second")
        assert "2 replies" in result

        doc = await instance.get_document(kb_id, "notes.md", "/")
        assert [r["text"] for r in doc["highlights"][0]["replies"]] == ["first", "second"]

    async def test_unknown_highlight_lists_available_ids(self, fs):
        instance, kb_id = fs
        from tools.reply import ReplyHandler

        await _create_doc_with_highlights(instance, kb_id, [_highlight("h1", "a note")])
        handler = ReplyHandler(instance, _make_kb(kb_id))

        result = await handler.reply("notes.md", "nope", "hi")
        assert "No highlight with id 'nope'" in result
        assert "h1" in result
        assert "a note" in result

    async def test_missing_document(self, fs):
        instance, kb_id = fs
        from tools.reply import ReplyHandler

        handler = ReplyHandler(instance, _make_kb(kb_id))
        result = await handler.reply("ghost.md", "h1", "hi")
        assert "not found" in result

    async def test_empty_reply_rejected(self, fs):
        instance, kb_id = fs
        from tools.reply import ReplyHandler

        await _create_doc_with_highlights(instance, kb_id, [_highlight("h1", "a note")])
        handler = ReplyHandler(instance, _make_kb(kb_id))

        result = await handler.reply("notes.md", "h1", "   ")
        assert "empty" in result

    async def test_read_appendix_shows_ids_and_replies(self, fs):
        instance, kb_id = fs
        from tools.read import ReadHandler
        from tools.reply import ReplyHandler

        await _create_doc_with_highlights(instance, kb_id, [_highlight("h1", "confusing bit")])
        reply_handler = ReplyHandler(instance, _make_kb(kb_id))
        await reply_handler.reply("notes.md", "h1", "Clarified with a diagram.")

        reader = ReadHandler(instance, _make_kb(kb_id))
        content = await reader.read("notes.md", "", None, False)
        assert "Highlights & Annotations" in content
        assert "[highlight_id: h1]" in content
        assert "*you (agent) replied:* Clarified with a diagram." in content
