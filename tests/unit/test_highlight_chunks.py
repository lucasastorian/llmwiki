"""Unit tests for highlight → chunk mapping + materialization helpers."""

import pytest

from services.highlight_chunks import (
    ChunkRecord,
    build_annotations_text,
    build_chunk_content,
    chunks_for_highlight,
    all_affected_chunks,
    iter_chunks_with_annotations,
)


def _chunk(id_: str, idx: int, source: str, *, page: int | None = None, start: int = 0) -> ChunkRecord:
    return ChunkRecord(id=id_, chunk_index=idx, source_content=source, page=page, start_char=start)


def _pdf(
    id_: str, page: int, text: str, *, comment: str | None = None,
    start: int | None = None, end: int | None = None,
) -> dict:
    return {
        "id": id_,
        "type": "pdf",
        "color": "yellow",
        "createdAt": "2026-05-31T00:00:00Z",
        "pdfAnchor": {
            "page": page, "textStart": start, "textEnd": end,
            "textContent": text, "rects": [],
        },
        "comment": comment,
    }


def _text(id_: str, start: int, end: int, text: str, *, comment: str | None = None) -> dict:
    return {
        "id": id_,
        "type": "text",
        "color": "yellow",
        "createdAt": "2026-05-31T00:00:00Z",
        "textAnchor": {
            "textStart": start, "textEnd": end,
            "textContent": text, "prefix": None, "suffix": None,
        },
        "comment": comment,
    }


class TestPdfMapping:

    def test_single_page_with_substring_match_picks_one_chunk(self):
        chunks = [
            _chunk("c1", 0, "First page text about machine learning.", page=1),
            _chunk("c2", 1, "Second page text about CAR-T therapy.",   page=2),
            _chunk("c3", 2, "Third page text about general topics.",   page=3),
        ]
        h = _pdf("h1", page=2, text="CAR-T therapy")
        hit = chunks_for_highlight(h, chunks)
        assert [c.id for c in hit] == ["c2"]

    def test_page_offsets_map_to_overlapping_chunks(self):
        chunks = [
            _chunk("c1", 0, "a" * 50, page=3, start=0),
            _chunk("c2", 1, "b" * 50, page=3, start=50),
            _chunk("c3", 2, "c" * 50, page=4, start=0),
        ]
        h = _pdf("h1", page=3, text="selection", start=40, end=60)
        hit = chunks_for_highlight(h, chunks)
        assert {c.id for c in hit} == {"c1", "c2"}

    def test_page_with_no_substring_match_uses_one_bounded_fallback_chunk(self):
        chunks = [
            _chunk("c1", 0, "Some unrelated content.", page=3),
            _chunk("c2", 1, "More unrelated content.", page=3),
        ]
        h = _pdf("h1", page=3, text="phrase nowhere in the chunks")
        hit = chunks_for_highlight(h, chunks)
        # Preserve page-level discoverability without duplicating one note
        # into every search chunk on the page.
        assert [c.id for c in hit] == ["c1"]

    def test_page_with_no_chunks_returns_empty(self):
        chunks = [_chunk("c1", 0, "Page 1 text", page=1)]
        h = _pdf("h1", page=99, text="anything")
        assert chunks_for_highlight(h, chunks) == []


class TestTextMapping:

    def test_text_anchor_inside_one_chunk_picks_it(self):
        # Chunk A: chars 0..50; Chunk B: chars 50..100; Chunk C: chars 100..150
        chunks = [
            _chunk("a", 0, "x" * 50, start=0),
            _chunk("b", 1, "y" * 50, start=50),
            _chunk("c", 2, "z" * 50, start=100),
        ]
        h = _text("h1", start=60, end=70, text="yyyyyyyyyy")
        hit = chunks_for_highlight(h, chunks)
        assert [c.id for c in hit] == ["b"]

    def test_text_anchor_spanning_two_chunks_returns_both(self):
        chunks = [
            _chunk("a", 0, "x" * 50, start=0),
            _chunk("b", 1, "y" * 50, start=50),
        ]
        # Spans halfway through chunk A into chunk B with equal overlap.
        h = _text("h1", start=30, end=70, text="something")
        hit = chunks_for_highlight(h, chunks)
        assert {c.id for c in hit} == {"a", "b"}

    def test_text_anchor_no_overlap_falls_back_to_text_match(self):
        chunks = [
            _chunk("a", 0, "The quick brown fox jumps over the lazy dog.", start=0),
            _chunk("b", 1, "Unrelated chunk content here.", start=100),
        ]
        # textStart/textEnd both outside any chunk range, but text matches.
        h = _text("h1", start=9999, end=10000, text="brown fox")
        hit = chunks_for_highlight(h, chunks)
        assert [c.id for c in hit] == ["a"]


class TestAffectedUnion:

    def test_old_union_new_catches_deletions(self):
        chunks = [
            _chunk("c1", 0, "alpha beta gamma", page=1),
            _chunk("c2", 1, "delta epsilon",    page=2),
        ]
        old = [_pdf("h-removed", page=1, text="alpha beta")]
        new: list[dict] = []
        affected = all_affected_chunks(chunks, old, new)
        # c1 was touched by `old`; without the union the chunk would never
        # get revisited and its annotations_text would stay stale.
        assert "c1" in affected

    def test_old_union_new_catches_moves(self):
        chunks = [
            _chunk("c1", 0, "alpha beta gamma", page=1),
            _chunk("c2", 1, "delta epsilon",    page=2),
        ]
        old = [_pdf("h-x", page=1, text="alpha")]
        new = [_pdf("h-x", page=2, text="epsilon")]  # same id, different page
        affected = all_affected_chunks(chunks, old, new)
        assert affected == {"c1", "c2"}


class TestBuildAnnotationsText:

    def test_empty_returns_none(self):
        assert build_annotations_text([]) is None

    def test_single_highlight_no_comment(self):
        out = build_annotations_text([_pdf("h1", page=1, text="hello world")])
        assert out == '[^user-1]: User highlighted "hello world"'

    def test_single_highlight_with_comment(self):
        h = _pdf("h1", page=1, text="hello world", comment="follow up")
        out = build_annotations_text([h])
        assert out == '[^user-1]: User highlighted "hello world" — user note: follow up'

    def test_multiple_highlights_sequential_ids_ordered_by_created_at(self):
        h1 = _pdf("z", page=1, text="zebra")
        h1["createdAt"] = "2026-05-31T12:00:00Z"
        h2 = _pdf("a", page=1, text="apple")
        h2["createdAt"] = "2026-05-31T09:00:00Z"
        h3 = _pdf("m", page=1, text="mango", comment="bright")
        h3["createdAt"] = "2026-05-31T10:30:00Z"
        out = build_annotations_text([h1, h2, h3])
        # Sorted by createdAt ascending: a, m, z. Sequential IDs per chunk.
        assert out == (
            '[^user-1]: User highlighted "apple"\n'
            '[^user-2]: User highlighted "mango" — user note: bright\n'
            '[^user-3]: User highlighted "zebra"'
        )

    def test_quoted_text_with_double_quotes_is_escaped(self):
        h = _pdf("h1", page=1, text='He said "hello"')
        out = build_annotations_text([h])
        assert '\\"hello\\"' in out

    def test_highlight_without_textcontent_is_dropped(self):
        h = {"id": "h1", "type": "pdf", "createdAt": "2026", "comment": "x", "pdfAnchor": {"page": 1}}
        out = build_annotations_text([h])
        assert out is None


class TestBuildChunkContent:

    def test_no_annotations_returns_source_unchanged(self):
        assert build_chunk_content("hello world", None) == "hello world"
        assert build_chunk_content("hello world", "") == "hello world"

    def test_with_annotations_joins_with_blank_line(self):
        content = build_chunk_content("source line", '[^user-1]: User highlighted "x"')
        assert content == 'source line\n\n[^user-1]: User highlighted "x"'


class TestIterChunksWithAnnotations:

    def test_emits_correct_tuples_for_affected_chunks_only(self):
        chunks = [
            _chunk("c1", 0, "alpha", page=1),
            _chunk("c2", 1, "beta",  page=2),
        ]
        new = [_pdf("h1", page=1, text="alpha", comment="note A")]
        affected = {"c1"}  # c2 deliberately not affected
        out = list(iter_chunks_with_annotations(chunks, affected, new))
        assert len(out) == 1
        chunk, anno, has_hl, content = out[0]
        assert chunk.id == "c1"
        assert has_hl is True
        assert anno is not None
        assert "note A" in anno
        assert content.startswith("alpha")

    def test_deletion_path_emits_none_annotations(self):
        chunks = [_chunk("c1", 0, "alpha", page=1)]
        # All highlights gone; chunk c1 was previously annotated and must
        # be cleared so has_highlight=False and content reverts to source.
        out = list(iter_chunks_with_annotations(chunks, {"c1"}, new_highlights=[]))
        chunk, anno, has_hl, content = out[0]
        assert anno is None
        assert has_hl is False
        assert content == "alpha"
