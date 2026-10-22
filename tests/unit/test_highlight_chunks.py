import pytest
from services.chunk_text_index import ChunkTextIndex
from services.highlight_chunks import (
    all_affected_chunks,
    build_annotations_text,
    build_chunk_content,
    chunks_for_highlight,
    iter_chunks_with_annotations,
)
from services.types import ChunkRecord

from tests.support.scaling import assert_linear_scaling


def _chunk(id_: str, idx: int, source: str, *, page: int | None = None, start: int = 0) -> ChunkRecord:
    return ChunkRecord(id=id_, chunk_index=idx, source_content=source, page=page, start_char=start)


def _assign_highlights_at_scale(chunk_count: int) -> dict[str, list[dict]]:
    """One highlight per hundred chunks, so chunks x highlights work grows 16x when the input grows 4x."""
    from services.highlight_chunks import assign_highlights_to_chunks

    chunks = [
        _chunk(f"c{i}", i, f"Paragraph {i} covers topic{i} with **bold{i}** words and a [ref{i}](https://x.com/{i}).", start=i * 100)
        for i in range(chunk_count)
    ]
    highlights = [_text(f"h{k}", 0, 1, f"covers topic{k * 97} with bold{k * 97} words") for k in range(chunk_count // 100)]
    return assign_highlights_to_chunks(ChunkTextIndex(chunks), highlights)


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
        hit = chunks_for_highlight(h, ChunkTextIndex(chunks))
        assert [c.id for c in hit] == ["c2"]

    def test_page_offsets_map_to_overlapping_chunks(self):
        chunks = [
            _chunk("c1", 0, "a" * 50, page=3, start=0),
            _chunk("c2", 1, "b" * 50, page=3, start=50),
            _chunk("c3", 2, "c" * 50, page=4, start=0),
        ]
        h = _pdf("h1", page=3, text="selection", start=40, end=60)
        hit = chunks_for_highlight(h, ChunkTextIndex(chunks))
        assert {c.id for c in hit} == {"c1", "c2"}

    def test_page_with_no_substring_match_uses_one_bounded_fallback_chunk(self):
        chunks = [
            _chunk("c1", 0, "Some unrelated content.", page=3),
            _chunk("c2", 1, "More unrelated content.", page=3),
        ]
        h = _pdf("h1", page=3, text="phrase nowhere in the chunks")
        hit = chunks_for_highlight(h, ChunkTextIndex(chunks))
        # One page-level note lands on one chunk, not every chunk on the page.
        assert [c.id for c in hit] == ["c1"]

    def test_page_with_no_chunks_returns_empty(self):
        chunks = [_chunk("c1", 0, "Page 1 text", page=1)]
        h = _pdf("h1", page=99, text="anything")
        assert chunks_for_highlight(h, ChunkTextIndex(chunks)) == []


class TestTextMapping:

    def test_text_anchor_inside_one_chunk_picks_it(self):
        # Chunk A: chars 0..50; Chunk B: chars 50..100; Chunk C: chars 100..150
        chunks = [
            _chunk("a", 0, "x" * 50, start=0),
            _chunk("b", 1, "y" * 50, start=50),
            _chunk("c", 2, "z" * 50, start=100),
        ]
        h = _text("h1", start=60, end=70, text="yyyyyyyyyy")
        hit = chunks_for_highlight(h, ChunkTextIndex(chunks))
        assert [c.id for c in hit] == ["b"]

    def test_text_anchor_spanning_two_chunks_returns_both(self):
        chunks = [
            _chunk("a", 0, "Intro words then the quote begins here", start=0),
            _chunk("b", 1, "and the quote ends here. Unrelated tail.", start=40),
        ]
        h = _text("h1", start=17, end=63, text="the quote begins here and the quote ends here.")
        hit = chunks_for_highlight(h, ChunkTextIndex(chunks))
        assert {c.id for c in hit} == {"a", "b"}

    def test_unquoted_text_is_not_assigned_by_offsets_alone(self):
        chunks = [
            _chunk("a", 0, "x" * 50, start=0),
            _chunk("b", 1, "y" * 50, start=50),
        ]
        h = _text("h1", start=30, end=70, text="something")
        assert chunks_for_highlight(h, ChunkTextIndex(chunks)) == []

    def test_text_anchor_no_overlap_falls_back_to_text_match(self):
        chunks = [
            _chunk("a", 0, "The quick brown fox jumps over the lazy dog.", start=0),
            _chunk("b", 1, "Unrelated chunk content here.", start=100),
        ]
        # textStart/textEnd both outside any chunk range, but text matches.
        h = _text("h1", start=9999, end=10000, text="brown fox")
        hit = chunks_for_highlight(h, ChunkTextIndex(chunks))
        assert [c.id for c in hit] == ["a"]

    def test_stale_offsets_overlapping_wrong_chunk_defer_to_quoting_chunk(self):
        # Offsets anchored against an older parser plaintext land in chunk "a"; the quote lives in "b".
        chunks = [
            _chunk("a", 0, "x" * 50, start=0),
            _chunk("b", 1, "The target phrase sits here.", start=50),
        ]
        h = _text("h1", start=10, end=23, text="target phrase")
        assert [c.id for c in chunks_for_highlight(h, ChunkTextIndex(chunks))] == ["b"]

    def test_emoji_before_highlight_shifts_utf16_offsets_past_quoting_chunk(self):
        # 40 emoji are 40 code points in chunk start_char but 80 UTF-16 units in the stored offsets.
        lead = "\U0001F600" * 40 + " intro"
        chunks = [
            _chunk("a", 0, lead, start=0),
            _chunk("b", 1, "needle text here", start=len(lead) + 2),
            _chunk("c", 2, "z" * 80, start=len(lead) + 20),
        ]
        utf16_start = len(lead.encode("utf-16-le")) // 2 + 2
        h = _text("h1", start=utf16_start, end=utf16_start + 11, text="needle text")
        assert [c.id for c in chunks_for_highlight(h, ChunkTextIndex(chunks))] == ["b"]

    def test_quote_matches_markdown_formatted_chunk_despite_emoji_shifted_offsets(self):
        # Parser output for 100 emoji then <b>target</b> phrase: the quote is plaintext, the chunk is Markdown.
        lead = "\U0001F600" * 100
        chunks = [
            _chunk("a", 0, lead, start=0),
            _chunk("b", 1, "**target** phrase, then \\*escaped\\* [link](https://x.com/p) `code`", start=102),
            _chunk("c", 2, "Unrelated chunk " * 10, start=170),
        ]
        h = _text("h1", start=200, end=213, text="target phrase")
        assert [c.id for c in chunks_for_highlight(h, ChunkTextIndex(chunks))] == ["b"]
        h2 = _text("h2", start=215, end=240, text="then *escaped* link code")
        assert [c.id for c in chunks_for_highlight(h2, ChunkTextIndex(chunks))] == ["b"]

    def test_repeated_quote_prefers_chunk_matching_context(self):
        chunks = [
            _chunk("a", 0, "Alpha says the model works.", start=0),
            _chunk("b", 1, "Beta says the model works.", start=30),
        ]
        h = _text("h1", start=0, end=15, text="the model works")
        h["textAnchor"]["prefix"] = "Beta says "
        assert [c.id for c in chunks_for_highlight(h, ChunkTextIndex(chunks))] == ["b"]

    def test_emoji_inside_highlight_matches_quoting_chunk(self):
        chunks = [
            _chunk("a", 0, "Plain words only.", start=0),
            _chunk("b", 1, "Party time \U0001F389 tonight.", start=17),
        ]
        h = _text("h1", start=29, end=40, text="time \U0001F389 tonight")
        assert [c.id for c in chunks_for_highlight(h, ChunkTextIndex(chunks))] == ["b"]


class TestAffectedUnion:

    def test_old_union_new_catches_deletions(self):
        chunks = [
            _chunk("c1", 0, "alpha beta gamma", page=1),
            _chunk("c2", 1, "delta epsilon",    page=2),
        ]
        old = [_pdf("h-removed", page=1, text="alpha beta")]
        new: list[dict] = []
        affected = all_affected_chunks(ChunkTextIndex(chunks), old, new)
        # c1 was touched only by `old`; the old ∪ new union keeps it from going stale.
        assert "c1" in affected

    def test_old_union_new_catches_moves(self):
        chunks = [
            _chunk("c1", 0, "alpha beta gamma", page=1),
            _chunk("c2", 1, "delta epsilon",    page=2),
        ]
        old = [_pdf("h-x", page=1, text="alpha")]
        new = [_pdf("h-x", page=2, text="epsilon")]  # same id, different page
        affected = all_affected_chunks(ChunkTextIndex(chunks), old, new)
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
        out = list(iter_chunks_with_annotations(ChunkTextIndex(chunks), affected, new))
        assert len(out) == 1
        chunk, anno, has_hl, content = out[0]
        assert chunk.id == "c1"
        assert has_hl is True
        assert anno is not None
        assert "note A" in anno
        assert content.startswith("alpha")

    def test_deletion_path_emits_none_annotations(self):
        chunks = [_chunk("c1", 0, "alpha", page=1)]
        # c1 was annotated before, so it must revert to source with has_highlight=False.
        out = list(iter_chunks_with_annotations(ChunkTextIndex(chunks), {"c1"}, new_highlights=[]))
        chunk, anno, has_hl, content = out[0]
        assert anno is None
        assert has_hl is False
        assert content == "alpha"


class TestHostileChunkText:

    def test_quote_matching_is_linear_on_unclosed_markdown_syntax(self):
        import time

        hostile = [
            "![a" * 3300, "](x" * 3300, "](<x" * 2500, "---" + " " * 10_000 + "x", " " * 10_000 + "x",
            "x" + "`" * 1000 + "a", "noodle " + "`" * 3000 + "a",
        ]
        chunks = [_chunk(f"c{i}", i, text, start=0) for i, text in enumerate(hostile)]
        started = time.perf_counter()
        assert chunks_for_highlight(_text("h1", 0, 6, "needle"), ChunkTextIndex(chunks)) == []
        assert time.perf_counter() - started < 1.0


class TestRenderedTextMatching:

    @pytest.mark.parametrize(("source", "quote"), [
        ("An _important_ insight here.", "An important insight"),
        ("Fish &amp; chips are great.", "Fish & chips"),
        ("```\na*b\n```", "a*b"),
        ("See [the docs][ref] now.\n\n[ref]: https://x.com/a", "See the docs now"),
        ("Read [this](https://x.com/a_(b)) today.", "Read this today"),
        ("| A | B |\n|---|---|\n| 1 | 2 |", "1\n2"),
        ("A&nbsp;b and `&amp;` literal", "A b and &amp; literal"),
    ])
    def test_quote_matches_rendered_markdown(self, source: str, quote: str):
        chunks = [_chunk("other", 0, "Unrelated words entirely.", start=0), _chunk("note", 1, source, start=30)]
        assert [c.id for c in chunks_for_highlight(_text("h1", 0, 1, quote), ChunkTextIndex(chunks))] == ["note"]

    def test_quote_spanning_a_chunk_boundary_lands_on_both_chunks(self):
        chunks = [
            _chunk("a", 0, "zero one two three four", start=0),
            _chunk("b", 1, "five six seven", start=25),
        ]
        hit = chunks_for_highlight(_text("h1", 0, 1, "one two three four five six"), ChunkTextIndex(chunks))
        assert [c.id for c in hit] == ["a", "b"]

    def test_quote_whose_halves_occur_apart_is_not_assigned(self):
        chunks = [
            _chunk("a", 0, "red apples are here", start=0),
            _chunk("b", 1, "and blue skies", start=21),
        ]
        assert chunks_for_highlight(_text("h1", 0, 1, "red apples blue skies"), ChunkTextIndex(chunks)) == []

    def test_chunker_overlap_is_counted_once(self):
        from services.chunker import chunk_text

        paragraphs = [f"Paragraph number {i} discusses subject{i} in some detail." for i in range(12)]
        records = [
            _chunk(f"c{c.index}", c.index, c.content, start=c.start_char)
            for c in chunk_text("\n\n".join(paragraphs), chunk_size=40, overlap=20)
        ]
        index = ChunkTextIndex(records)
        assert len(records) > 3

        inside = chunks_for_highlight(_text("h1", 0, 1, "subject5 in some detail"), index)
        assert len(inside) == 1 and "subject5" in inside[0].source_content

        spanning = chunks_for_highlight(_text("h2", 0, 1, paragraphs[5] + " " + paragraphs[6]), index)
        joined = " ".join(c.source_content for c in spanning)
        assert paragraphs[5] in joined and paragraphs[6] in joined
        assert [c.chunk_index for c in spanning] == list(range(spanning[0].chunk_index, spanning[-1].chunk_index + 1))

    def test_many_chunks_and_highlights_render_each_chunk_at_most_once(self):
        assert sorted(_assign_highlights_at_scale(5000)) == sorted(f"c{k * 97}" for k in range(50))
        assert_linear_scaling(_assign_highlights_at_scale, 1250)
