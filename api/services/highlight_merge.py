"""Shared highlight-list merge helpers for the hosted and local services."""

from html_parser.models import MappedHighlight


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
        # Reply-unaware writers (extension re-clips) send an empty list; don't let it wipe the thread.
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


def merge_text_anchors(payloads: list[dict], mapped: list[MappedHighlight]) -> list[dict]:
    """Add located `textAnchor`s to the payloads; unlocated highlights persist for viewer text-search fallback."""
    merged: list[dict] = []
    for i, h in enumerate(payloads):
        if not isinstance(h, dict):
            continue
        entry = dict(h)
        anchor = mapped[i].text_anchor if i < len(mapped) else None
        if anchor is not None:
            entry["textAnchor"] = {
                "textStart": anchor.text_start,
                "textEnd": anchor.text_end,
                "textContent": anchor.text_content,
                "prefix": anchor.prefix,
                "suffix": anchor.suffix,
            }
        merged.append(entry)
    return merged
