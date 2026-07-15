"""Comments tool — list highlight comment threads across the vault."""

from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP, Context

from vaultfs import VaultFS
from vaultfs.highlights import parse_highlights_value
from .helpers import clean_annotation_text, glob_match, highlight_quote_and_page

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)


def _parse_timestamp(value) -> datetime:
    if not isinstance(value, str) or not value:
        return _EPOCH
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return _EPOCH
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class CommentsHandler:
    """Lists highlight comment threads across documents, newest first."""

    def __init__(self, fs: VaultFS, kb: dict):
        self.fs = fs
        self.kb = kb
        self.kb_id = str(kb["id"])
        self.slug = kb["slug"]

    async def list_comments(self, path: str, limit: int) -> str:
        limit = max(1, min(limit or DEFAULT_LIMIT, MAX_LIMIT))
        pattern = "/" + path.lstrip("/") if not path.startswith("/") else path

        docs = await self.fs.list_documents_with_content(
            self.kb_id,
            path_glob=pattern,
            content_limit=0,
        )
        docs = [d for d in docs if glob_match(d["path"] + d["filename"], pattern)]

        threads: list[dict] = []
        for doc in docs:
            threads.extend(self._doc_threads(doc))
        if not threads:
            return f"No comments found matching `{pattern}` in {self.slug}."

        threads.sort(key=lambda t: t["last_activity"], reverse=True)
        shown = threads[:limit]

        header = f"**{len(threads)} comment thread(s)** matching `{pattern}`, newest first"
        if len(threads) > len(shown):
            header += f" (showing {len(shown)} — raise `limit` for more)"
        return "\n".join([header, "", *[self._format_thread(t) for t in shown]])

    def _doc_threads(self, doc: dict) -> list[dict]:
        threads: list[dict] = []
        for h in parse_highlights_value(doc.get("highlights")):
            if not isinstance(h, dict) or not h.get("id"):
                continue
            comment = clean_annotation_text(h.get("comment") or "")
            replies = [r for r in (h.get("replies") or []) if isinstance(r, dict)]
            if not comment and not replies:
                continue
            quote, page = highlight_quote_and_page(h)
            timestamps = [_parse_timestamp(h.get("createdAt"))]
            timestamps += [_parse_timestamp(r.get("createdAt")) for r in replies]
            threads.append({
                "doc_path": doc["path"] + doc["filename"],
                "highlight_id": h["id"],
                "quote": quote,
                "page": page,
                "comment": comment,
                "replies": replies,
                "last_activity": max(timestamps),
                "needs_reply": not replies or replies[-1].get("author") != "agent",
            })
        return threads

    def _format_thread(self, t: dict) -> str:
        date = t["last_activity"].strftime("%Y-%m-%d") if t["last_activity"] > _EPOCH else "undated"
        status = "needs reply" if t["needs_reply"] else "replied"
        page = f" (p.{t['page']})" if t["page"] else ""
        lines = [
            f"- **{date}** `{t['doc_path']}`{page} — “{t['quote']}” "
            f"`[highlight_id: {t['highlight_id']}]` — _{status}_"
        ]
        if t["comment"]:
            lines.append(f"    - *user note:* {t['comment']}")
        for r in t["replies"]:
            text = clean_annotation_text(r.get("text") or "")
            if not text:
                continue
            author = "you (agent)" if r.get("author") == "agent" else "user"
            lines.append(f"    - *{author} replied:* {text}")
        return "\n".join(lines)


def register(mcp: FastMCP, get_user_id, fs_factory) -> None:

    @mcp.tool(
        name="list_comments",
        description=(
            "List highlight comment threads across the knowledge vault, newest first.\n\n"
            "Use this to sweep for recent comments without reading every page:\n"
            "- `path=\"**\"` — all comments in the knowledge base (default)\n"
            "- `path=\"/wiki/**\"` — comments on wiki pages only\n"
            "- `path=\"/wiki/concepts/**\"` — one section\n\n"
            "Each thread shows the quoted passage, the user's note, any replies, and a "
            "status: _needs reply_ (no reply yet, or the user replied after you) vs "
            "_replied_. Address a note first (rework the passage), then respond with "
            "`reply_to_comment` using the listed highlight_id."
        ),
    )
    async def list_comments(
        ctx: Context,
        knowledge_base: str,
        path: str = "**",
        limit: int = DEFAULT_LIMIT,
    ) -> str:
        user_id = get_user_id(ctx)
        fs = fs_factory(user_id)
        kb = await fs.resolve_kb(knowledge_base)
        if not kb:
            return f"Knowledge base '{knowledge_base}' not found."

        handler = CommentsHandler(fs, kb)
        return await handler.list_comments(path, limit)
