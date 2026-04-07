"""Unit tests for the text chunker."""

from services.chunker import chunk_text, chunk_pages, _estimate_tokens, CHUNK_SIZE


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

    def test_very_short_text_below_minimum_is_dropped(self):
        assert chunk_text("hi") == []

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
