"""Shared helpers for the documents.highlights JSON list."""

import json


def parse_highlights_value(value) -> list[dict]:
    """Normalize a raw highlights column value (str | list | None) to a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def find_highlight(highlights: list, highlight_id: str) -> dict | None:
    """Return the highlight entry with the given id, if any."""
    for h in highlights:
        if isinstance(h, dict) and h.get("id") == highlight_id:
            return h
    return None


def append_reply(highlight: dict, reply: dict) -> None:
    """Append a reply to the highlight's thread, creating it if absent."""
    replies = highlight.get("replies")
    if not isinstance(replies, list):
        replies = []
    replies.append(reply)
    highlight["replies"] = replies
