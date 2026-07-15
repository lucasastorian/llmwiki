"""Reply tool — respond to a user's highlight or comment on a document."""

import uuid
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP, Context

from vaultfs import VaultFS
from vaultfs.highlights import find_highlight, parse_highlights_value
from .helpers import resolve_path

MAX_REPLY_CHARS = 4000
MAX_LISTED_HIGHLIGHTS = 20
# Must not exceed the API's Highlight.replies max_length, or web edits of the
# highlight would fail validation after the thread grows past it.
MAX_THREAD_REPLIES = 50


class ReplyHandler:
    """Appends agent replies to highlight comment threads."""

    def __init__(self, fs: VaultFS, kb: dict):
        self.fs = fs
        self.kb = kb
        self.kb_id = str(kb["id"])
        self.slug = kb["slug"]

    async def reply(self, path: str, highlight_id: str, text: str) -> str:
        text = text.strip()
        if not text:
            return "Error: reply text is empty."
        if len(text) > MAX_REPLY_CHARS:
            return f"Error: reply exceeds {MAX_REPLY_CHARS} characters."

        doc = await self._fetch_document(path)
        if not doc:
            return f"Document '{path}' not found in {self.slug}."

        highlights = parse_highlights_value(doc.get("highlights"))
        target = find_highlight(highlights, highlight_id)
        if target is None:
            return self._unknown_highlight_message(path, highlight_id, highlights)
        existing_replies = target.get("replies")
        if isinstance(existing_replies, list) and len(existing_replies) >= MAX_THREAD_REPLIES:
            return f"Error: this thread already has {MAX_THREAD_REPLIES} replies."

        reply = {
            "id": uuid.uuid4().hex,
            "author": "agent",
            "text": text,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        updated = await self.fs.add_highlight_reply(str(doc["id"]), highlight_id, reply)
        if updated is None:
            return f"Highlight '{highlight_id}' no longer exists on '{path}'."
        return self._confirmation(path, updated)

    async def _fetch_document(self, path: str) -> dict | None:
        dir_path, filename = resolve_path(path)
        doc = await self.fs.get_document(self.kb_id, filename, dir_path)
        if not doc:
            name = path.lstrip("/").split("/")[-1]
            doc = await self.fs.find_document_by_name(self.kb_id, name)
        return doc

    def _unknown_highlight_message(self, path: str, highlight_id: str, highlights: list) -> str:
        lines = [f"No highlight with id '{highlight_id}' on '{path}'."]
        listed = 0
        for h in highlights:
            if not isinstance(h, dict) or not h.get("id"):
                continue
            if listed >= MAX_LISTED_HIGHLIGHTS:
                lines.append(f"  … and {len(highlights) - listed} more")
                break
            quote = _anchor_text(h)[:80]
            note = (h.get("comment") or "").strip()[:80]
            suffix = f" — note: {note}" if note else ""
            lines.append(f"  - {h['id']}: “{quote}”{suffix}")
            listed += 1
        if listed == 0:
            lines.append("This document has no highlights.")
        return "\n".join(lines)

    def _confirmation(self, path: str, highlight: dict) -> str:
        quote = _anchor_text(highlight)[:120]
        replies = highlight.get("replies") or []
        return (
            f"Replied to highlight on '{path}' (thread now has {len(replies)} repl{'y' if len(replies) == 1 else 'ies'}).\n"
            f"Highlighted text: “{quote}”"
        )


def _anchor_text(highlight: dict) -> str:
    for key in ("textAnchor", "pdfAnchor", "anchor"):
        anchor = highlight.get(key)
        if isinstance(anchor, dict) and anchor.get("textContent"):
            return anchor["textContent"]
    return ""


def register(mcp: FastMCP, get_user_id, fs_factory) -> None:

    @mcp.tool(
        name="reply_to_comment",
        description=(
            "Reply to a user's highlight or comment on a document.\n\n"
            "The `read` tool's 'Highlights & Annotations' appendix lists each highlight "
            "with its id. After addressing a comment (e.g. reworking a confusing passage), "
            "use this to tell the user what you did — the reply appears threaded under "
            "their comment in the app.\n\n"
            "Keep replies short and concrete: what changed, where to look, or a direct "
            "answer to their question."
        ),
    )
    async def reply_to_comment(
        ctx: Context,
        knowledge_base: str,
        path: str,
        highlight_id: str,
        reply: str,
    ) -> str:
        user_id = get_user_id(ctx)
        fs = fs_factory(user_id)
        kb = await fs.resolve_kb(knowledge_base)
        if not kb:
            return f"Knowledge base '{knowledge_base}' not found."

        handler = ReplyHandler(fs, kb)
        return await handler.reply(path, highlight_id, reply)
