"""Shared highlight-list merge helpers for the hosted and local services."""


def merge_highlights_by_id(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """Merge two highlight lists by id, incoming fields winning per entry."""
    merged: dict[str, dict] = {}
    order: list[str] = []
    for highlight in [*existing, *incoming]:
        if not isinstance(highlight, dict):
            continue
        highlight_id = highlight.get("id")
        if not highlight_id:
            continue
        if highlight_id not in merged:
            order.append(highlight_id)
        current = merged.get(highlight_id, {})
        entry = {**current, **highlight}
        # Writers that don't know about replies (extension re-clips) send an
        # empty list; never let that wipe an existing thread.
        if not highlight.get("replies") and current.get("replies"):
            entry["replies"] = current["replies"]
        merged[highlight_id] = entry
    return [merged[highlight_id] for highlight_id in order]


def preserve_replies(incoming: list[dict], existing: list[dict]) -> None:
    """Keep existing reply threads when a writer sends highlights without them."""
    by_id = {h.get("id"): h for h in existing if isinstance(h, dict)}
    for h in incoming:
        if not isinstance(h, dict):
            continue
        prev = by_id.get(h.get("id"))
        if prev and not h.get("replies") and prev.get("replies"):
            h["replies"] = prev["replies"]
