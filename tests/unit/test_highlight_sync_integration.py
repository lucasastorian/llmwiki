"""Highlight CRUD to chunk annotations/content sync against a real SQLite chunks table."""
import uuid
from pathlib import Path

import aiosqlite
import pytest
from infra.db.sqlite import SQLiteDocumentRepository


@pytest.fixture
async def db_repo(tmp_path: Path):
    """A throwaway SQLite DB seeded with the shared schema."""
    db_path = tmp_path / "test.db"
    db = await aiosqlite.connect(str(db_path))
    schema_path = Path(__file__).resolve().parents[2] / "shared" / "sqlite_migrations" / "0001_baseline.sql"
    await db.executescript(schema_path.read_text(encoding="utf-8"))
    await db.commit()
    yield db, SQLiteDocumentRepository(db)
    await db.close()


async def _seed_doc(db: aiosqlite.Connection, doc_id: str) -> None:
    # Local-mode schema: single workspace, no knowledge_base_id column.
    await db.execute(
        "INSERT INTO documents (id, user_id, filename, title, path, relative_path, "
        "source_kind, file_type, status, content, tags, version, document_number, "
        "metadata, highlights) "
        "VALUES (?, ?, ?, ?, ?, ?, 'source', 'md', 'ready', NULL, '[]', 0, 1, '{}', '[]')",
        (doc_id, "local", f"test-{doc_id[:8]}.md", "Test Doc", "/", f"test-{doc_id[:8]}.md"),
    )


async def _seed_chunks(db: aiosqlite.Connection, doc_id: str, chunks: list[tuple]) -> list[str]:
    """Insert (content, page, start_char) chunks. Returns chunk ids in order."""
    ids = []
    for idx, (content, page, start_char) in enumerate(chunks):
        cid = str(uuid.uuid4())
        ids.append(cid)
        await db.execute(
            "INSERT INTO document_chunks (id, document_id, chunk_index, content, "
            "source_content, page, start_char, token_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, doc_id, idx, content, content, page, start_char, len(content) // 4),
        )
    await db.commit()
    return ids


async def _chunk_row(db: aiosqlite.Connection, chunk_id: str) -> dict:
    cursor = await db.execute(
        "SELECT source_content, annotations_text, has_highlight, content "
        "FROM document_chunks WHERE id = ?", (chunk_id,),
    )
    row = await cursor.fetchone()
    return {
        "source_content": row[0],
        "annotations_text": row[1],
        "has_highlight": row[2],
        "content": row[3],
    }


def _pdf_highlight(hid: str, page: int, text: str, comment: str | None = None) -> dict:
    return {
        "id": hid,
        "type": "pdf",
        "anchor": None,
        "textAnchor": None,
        "pdfAnchor": {
            "page": page,
            "textContent": text,
            "prefix": None,
            "suffix": None,
            "rects": [],
        },
        "comment": comment,
        "color": "yellow",
        "createdAt": "2026-05-31T12:00:00Z",
    }


class TestHighlightSyncRoundTrip:

    async def test_replace_highlight_populates_chunk_annotations(self, db_repo):
        db, repo = db_repo
        doc_id = "00000000-0000-0000-0000-000000000001"
        await _seed_doc(db, doc_id)
        chunk_ids = await _seed_chunks(db, doc_id, [
            ("Chimeric antigen receptor T-cell therapies show promise.", 1, 0),
            ("In vivo CAR-T approaches reduce manufacturing burden.",    2, 60),
        ])

        h = _pdf_highlight(
            "h-1", page=1,
            text="Chimeric antigen receptor T-cell",
            comment="Look into solid-tumor angle",
        )
        result = await repo.replace_highlights(doc_id, "local", [h])
        assert result is not None
        assert result["highlights"] == [h]

        c1 = await _chunk_row(db, chunk_ids[0])
        c2 = await _chunk_row(db, chunk_ids[1])

        assert c1["has_highlight"] == 1
        assert c1["annotations_text"] is not None
        assert "User highlighted" in c1["annotations_text"]
        assert "solid-tumor angle" in c1["annotations_text"]
        assert c1["content"].startswith(c1["source_content"])
        assert "[^user-1]:" in c1["content"]

        assert c2["has_highlight"] == 0
        assert c2["annotations_text"] is None
        assert c2["content"] == c2["source_content"]

    async def test_delete_clears_stale_annotations(self, db_repo):
        """Deletion must revisit chunks touched by the old highlight set, not just the new one."""
        db, repo = db_repo
        doc_id = "00000000-0000-0000-0000-000000000002"
        await _seed_doc(db, doc_id)
        chunk_ids = await _seed_chunks(db, doc_id, [
            ("CAR-T cells engineered ex vivo.", 1, 0),
        ])

        h = _pdf_highlight("h-1", page=1, text="CAR-T cells", comment="ref-1")
        await repo.replace_highlights(doc_id, "local", [h])
        before = await _chunk_row(db, chunk_ids[0])
        assert before["has_highlight"] == 1
        assert "ref-1" in (before["annotations_text"] or "")

        await repo.replace_highlights(doc_id, "local", [])
        after = await _chunk_row(db, chunk_ids[0])

        assert after["has_highlight"] == 0
        assert after["annotations_text"] is None
        assert after["content"] == after["source_content"]

    async def test_upsert_highlight_then_edit_comment(self, db_repo):
        db, repo = db_repo
        doc_id = "00000000-0000-0000-0000-000000000003"
        await _seed_doc(db, doc_id)
        chunk_ids = await _seed_chunks(db, doc_id, [
            ("Vein-to-vein time is a critical bottleneck.", 1, 0),
        ])

        h1 = _pdf_highlight("h-1", page=1, text="Vein-to-vein", comment="check refs")
        await repo.upsert_highlight(doc_id, "local", h1)
        row = await _chunk_row(db, chunk_ids[0])
        assert "check refs" in row["annotations_text"]

        h1_edited = _pdf_highlight("h-1", page=1, text="Vein-to-vein", comment="updated note")
        await repo.upsert_highlight(doc_id, "local", h1_edited)
        row = await _chunk_row(db, chunk_ids[0])
        assert "updated note" in row["annotations_text"]
        assert "check refs" not in row["annotations_text"]

    async def test_delete_endpoint_clears_only_targeted_highlight(self, db_repo):
        db, repo = db_repo
        doc_id = "00000000-0000-0000-0000-000000000004"
        await _seed_doc(db, doc_id)
        chunk_ids = await _seed_chunks(db, doc_id, [
            ("Multiple highlights can live in the same chunk.", 1, 0),
        ])

        h1 = _pdf_highlight("h-1", page=1, text="Multiple highlights", comment="first")
        h2 = _pdf_highlight("h-2", page=1, text="same chunk", comment="second")
        await repo.upsert_highlight(doc_id, "local", h1)
        await repo.upsert_highlight(doc_id, "local", h2)
        row = await _chunk_row(db, chunk_ids[0])
        assert "first" in row["annotations_text"]
        assert "second" in row["annotations_text"]

        await repo.delete_highlight(doc_id, "local", "h-1")
        row = await _chunk_row(db, chunk_ids[0])
        assert "first" not in (row["annotations_text"] or "")
        assert "second" in row["annotations_text"]
        assert row["has_highlight"] == 1

    async def test_chunks_fts_picks_up_annotation_text(self, db_repo):
        """chunks_fts indexes `content`, which carries the footnote body after sync."""
        db, repo = db_repo
        doc_id = "00000000-0000-0000-0000-000000000005"
        await _seed_doc(db, doc_id)
        await _seed_chunks(db, doc_id, [
            ("Body text the user did not write.", 1, 0),
        ])

        h = _pdf_highlight(
            "h-1", page=1, text="Body text",
            comment="indexable annotation phrase fooflarble",
        )
        await repo.replace_highlights(doc_id, "local", [h])

        cursor = await db.execute(
            "SELECT dc.content FROM document_chunks dc "
            "JOIN chunks_fts fts ON dc.rowid = fts.rowid "
            "WHERE chunks_fts MATCH ?",
            ("fooflarble",),
        )
        rows = await cursor.fetchall()
        assert len(rows) == 1
        assert "fooflarble" in rows[0][0]


class TestWikiNoteTextHighlights:

    async def test_text_highlight_on_formatted_markdown_annotates_its_chunk(self, db_repo):
        """Wiki highlights quote rendered text, which never contains the Markdown syntax of the chunk."""
        db, repo = db_repo
        doc_id = "00000000-0000-0000-0000-000000000010"
        await _seed_doc(db, doc_id)
        chunk_ids = await _seed_chunks(db, doc_id, [
            ("Intro paragraph about something else.", None, 0),
            ("An _important_ insight about **Fish &amp; chips**.", None, 40),
        ])
        highlight = {
            "id": "h-1",
            "type": "text",
            "anchor": None,
            "textAnchor": {
                "textStart": 0, "textEnd": 39,
                "textContent": "An important insight about Fish & chips",
                "prefix": "something else.\n", "suffix": ".",
            },
            "comment": "worth a page",
            "color": "yellow",
            "createdAt": "2026-06-01T00:00:00Z",
        }

        await repo.upsert_highlight(doc_id, "local", highlight)
        await repo.reapply_highlights(doc_id)

        intro, note = await _chunk_row(db, chunk_ids[0]), await _chunk_row(db, chunk_ids[1])
        assert note["has_highlight"] == 1
        assert "worth a page" in note["annotations_text"]
        assert intro["has_highlight"] == 0
