"""Reply threads survive writers that don't send them (extension re-clips, stale clients)."""

from services.highlight_merge import merge_highlights_by_id, preserve_replies

REPLY = {"id": "r1", "author": "agent", "text": "clarified", "createdAt": "2026-07-09T00:00:00Z"}


def _h(highlight_id: str, replies: list | None = None, **extra) -> dict:
    entry = {"id": highlight_id, "comment": "note", **extra}
    if replies is not None:
        entry["replies"] = replies
    return entry


class TestPreserveReplies:

    def test_empty_incoming_replies_keep_existing_thread(self):
        incoming = [_h("h1", replies=[])]
        preserve_replies(incoming, [_h("h1", replies=[REPLY])])
        assert incoming[0]["replies"] == [REPLY]

    def test_missing_incoming_replies_keep_existing_thread(self):
        incoming = [_h("h1")]
        preserve_replies(incoming, [_h("h1", replies=[REPLY])])
        assert incoming[0]["replies"] == [REPLY]

    def test_incoming_thread_wins_when_present(self):
        newer = [dict(REPLY), {"id": "r2", "author": "user", "text": "thanks", "createdAt": "now"}]
        incoming = [_h("h1", replies=newer)]
        preserve_replies(incoming, [_h("h1", replies=[REPLY])])
        assert incoming[0]["replies"] == newer

    def test_new_highlight_untouched(self):
        incoming = [_h("h2", replies=[])]
        preserve_replies(incoming, [_h("h1", replies=[REPLY])])
        assert incoming[0]["replies"] == []


class TestMergeKeepsReplies:

    def test_reclip_merge_does_not_wipe_thread(self):
        existing = [_h("h1", replies=[REPLY])]
        incoming = [_h("h1", replies=[], comment="updated note")]
        merged = merge_highlights_by_id(existing, incoming)
        assert merged[0]["comment"] == "updated note"
        assert merged[0]["replies"] == [REPLY]
