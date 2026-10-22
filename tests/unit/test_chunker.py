from services.chunker import _estimate_tokens, chunk_pages, chunk_text


class TestChunkText:

    def test_empty_content_returns_nothing(self):
        assert chunk_text("") == []
        assert chunk_text("   ") == []
        assert chunk_text(None) == []

    def test_short_text_returns_one_chunk(self):
        text = "This is a paragraph with enough words to comfortably exceed the minimum token threshold. " * 3
        text = text.strip()
        chunks = chunk_text(text)
        assert len(chunks) == 1
        assert chunks[0].index == 0
        assert chunks[0].page is None

    def test_very_short_text_is_still_searchable(self):
        chunks = chunk_text("# Q3 Revenue\n\n- Up 20% YoY")
        assert [c.content for c in chunks] == ["# Q3 Revenue\n\n- Up 20% YoY"]

    def test_short_trailing_block_is_kept(self):
        text = ("Long paragraph text. " * 120) + "\n\nContact: alice@example.com"
        assert "alice@example.com" in chunk_text(text)[-1].content

    def test_short_leading_block_merges_into_next_chunk(self):
        text = "Intro.\n\n" + ("Word " * 3000)
        assert chunk_text(text)[0].content.startswith("Intro.")

    def test_breadcrumb_names_the_section_the_chunk_came_from(self):
        text = "# Alpha\n\n" + ("alpha text " * 400) + "\n\n# Beta\n\n" + ("beta text " * 50)
        chunks = chunk_text(text)
        assert chunks[0].header_breadcrumb == "Alpha"
        assert chunks[-1].header_breadcrumb == "Beta"

    def test_long_text_produces_multiple_chunks(self):
        para = "Word " * 300
        text = f"{para}\n\n{para}\n\n{para}"
        chunks = chunk_text(text)
        assert len(chunks) > 1

    def test_chunks_have_sequential_indices(self):
        text = ("Paragraph of text. " * 50 + "\n\n") * 10
        chunks = chunk_text(text)
        for i, chunk in enumerate(chunks):
            assert chunk.index == i

    def test_header_breadcrumb_tracking(self):
        text = "# Main Title\n\nIntro paragraph.\n\n## Section A\n\n" + ("Content. " * 50)
        chunks = chunk_text(text)
        assert len(chunks) >= 1
        assert "Main Title" in chunks[-1].header_breadcrumb
        assert "Section A" in chunks[-1].header_breadcrumb

    def test_page_parameter_propagates(self):
        text = "Enough content to make a chunk. " * 10
        chunks = chunk_text(text, page=5)
        assert all(c.page == 5 for c in chunks)

    def test_start_char_offset(self):
        text = "Enough content to make a chunk. " * 10
        chunks = chunk_text(text, start_char_offset=100)
        assert chunks[0].start_char >= 100

    def test_token_count_is_positive(self):
        text = "A reasonable paragraph with sufficient words. " * 10
        chunks = chunk_text(text)
        assert all(c.token_count > 0 for c in chunks)


class TestChunkPages:

    def test_multiple_pages(self):
        pages = [
            (1, "First page content. " * 20),
            (2, "Second page content. " * 20),
        ]
        chunks = chunk_pages(pages)
        assert len(chunks) >= 2
        page_nums = {c.page for c in chunks}
        assert 1 in page_nums
        assert 2 in page_nums

    def test_indices_are_global(self):
        pages = [
            (1, "Content A. " * 20),
            (2, "Content B. " * 20),
        ]
        chunks = chunk_pages(pages)
        indices = [c.index for c in chunks]
        assert indices == list(range(len(chunks)))


class TestEstimateTokens:

    def test_rough_estimate(self):
        assert _estimate_tokens("a" * 400) == 100
        assert _estimate_tokens("") == 1


class TestEnforceMaxCharsAssignsPerPieceStartChar:
    """Each piece split by _enforce_max_chars gets its own start_char for text-anchor mapping."""

    def test_oversized_chunk_splits_with_per_piece_offsets(self):
        from services.chunker import MAX_CHUNK_CHARS
        sentence = "All this happened, more or less. " * 6
        paragraph = (sentence * 200).strip()
        assert len(paragraph) > MAX_CHUNK_CHARS

        chunks = chunk_text(paragraph, page=7, start_char_offset=1000)
        oversized_originals = [c for c in chunks if len(c.content) > MAX_CHUNK_CHARS]
        assert oversized_originals == []

        starts = [c.start_char for c in chunks]
        assert starts[0] == 1000
        assert len(set(starts)) == len(starts), (
            "Split pieces share start_char; downstream text-anchor mapping will "
            "misassign highlights. See _enforce_max_chars fix."
        )
        for a, b in zip(starts, starts[1:]):
            assert b > a

    def test_under_limit_chunks_unchanged(self):
        # Long enough to clear the chunker's minimum-token threshold.
        text = "This is a properly sized paragraph with enough words to actually be chunked. " * 4
        chunks = chunk_text(text.strip(), page=1, start_char_offset=500)
        assert len(chunks) >= 1
        for c in chunks:
            assert c.start_char is not None
