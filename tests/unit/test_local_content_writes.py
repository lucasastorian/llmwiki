"""Editing a document's text must never overwrite a binary source file on disk."""

import uuid
from pathlib import Path

import pytest

USER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


async def _seed(db, filename: str, file_type: str) -> str:
    await db.execute(
        "INSERT OR IGNORE INTO workspace (id, name, description, user_id) VALUES ('ws', 'ws', '', ?)",
        (USER_ID,),
    )
    doc_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO documents (id, user_id, filename, title, path, relative_path, source_kind, "
        "file_type, status, content, highlights, tags, version, document_number) "
        "VALUES (?, ?, ?, ?, '/', ?, 'source', ?, 'ready', 'old text', '[]', '[]', 0, 1)",
        (doc_id, USER_ID, filename, filename, filename, file_type),
    )
    await db.commit()
    return doc_id


@pytest.fixture
async def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from config import settings
    from infra.db.sqlite import create_pool
    from services.local import LocalDocumentService

    monkeypatch.setattr(settings, "WORKSPACE_PATH", str(tmp_path))
    db = await create_pool(str(tmp_path / "index.db"))
    yield LocalDocumentService(db, USER_ID), db
    await db.close()


async def test_pdf_text_edit_leaves_the_pdf_untouched(service, tmp_path: Path) -> None:
    svc, db = service
    (tmp_path / "paper.pdf").write_bytes(b"%PDF-1.7 original")
    doc_id = await _seed(db, "paper.pdf", "pdf")

    await svc.update_content(doc_id, "corrected extracted text")

    assert (tmp_path / "paper.pdf").read_bytes() == b"%PDF-1.7 original"
    assert (await svc.get_content(doc_id))["content"] == "corrected extracted text"


async def test_markdown_edit_still_writes_the_file(service, tmp_path: Path) -> None:
    svc, db = service
    (tmp_path / "note.md").write_text("old text")
    doc_id = await _seed(db, "note.md", "md")

    await svc.update_content(doc_id, "new text")

    assert (tmp_path / "note.md").read_text() == "new text"


async def test_metadata_patch_replaces_top_level_keys_like_hosted(service) -> None:
    svc, db = service
    doc_id = await _seed(db, "note.md", "md")
    await svc.doc_repo.update_metadata(doc_id, USER_ID, metadata={"properties": {"old": 1}, "course": {"s": 1}})

    row = await svc.doc_repo.update_metadata(doc_id, USER_ID, metadata={"properties": {"new": 2}})

    assert row["metadata"] == {"properties": {"new": 2}, "course": {"s": 1}}


async def test_create_note_never_overwrites_an_existing_file(service, tmp_path: Path) -> None:
    from fastapi import HTTPException

    svc, db = service
    await _seed(db, "seed.md", "md")
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "overview.md").write_text("the real overview")

    with pytest.raises(HTTPException) as exc:
        await svc.create_note("ws", "overview.md", "/wiki", "replacement")

    assert exc.value.status_code == 409
    assert (tmp_path / "wiki" / "overview.md").read_text() == "the real overview"


async def test_create_note_refuses_hidden_targets(service, tmp_path: Path) -> None:
    from fastapi import HTTPException

    svc, _ = service
    with pytest.raises(HTTPException) as exc:
        await svc.create_note("ws", "index.db", "/.llmwiki/", "garbage")

    assert exc.value.status_code == 400
    assert not (tmp_path / ".llmwiki" / "index.db").exists()


async def test_create_note_stores_a_canonical_path(service, tmp_path: Path) -> None:
    svc, db = service
    await _seed(db, "seed.md", "md")

    row = await svc.create_note("ws", "fresh.md", "notes", "body")

    assert row["path"] == "/notes/"
    assert (tmp_path / "notes" / "fresh.md").read_text() == "body"


async def test_rename_onto_an_existing_file_is_refused(service, tmp_path: Path) -> None:
    from fastapi import HTTPException

    svc, db = service
    (tmp_path / "a.md").write_text("A")
    (tmp_path / "b.md").write_text("B")
    doc_a = await _seed(db, "a.md", "md")

    with pytest.raises(HTTPException) as exc:
        await svc.update_metadata(doc_a, {"filename": "b.md"})

    assert exc.value.status_code == 409
    assert (tmp_path / "a.md").read_text() == "A"
    assert (tmp_path / "b.md").read_text() == "B"


async def test_rename_moves_the_file(service, tmp_path: Path) -> None:
    svc, db = service
    (tmp_path / "a.md").write_text("A")
    doc_a = await _seed(db, "a.md", "md")

    row = await svc.update_metadata(doc_a, {"filename": "c.md", "path": "archive"})

    assert row["path"] == "/archive/"
    assert row["relative_path"] == "archive/c.md"
    assert (tmp_path / "archive" / "c.md").read_text() == "A"
    assert not (tmp_path / "a.md").exists()


async def test_content_edit_keeps_highlight_comments_searchable(service, tmp_path: Path) -> None:
    import json

    svc, db = service
    body = "The mitochondria is the powerhouse of the cell. " * 10
    (tmp_path / "bio.md").write_text(body)
    doc_id = await _seed(db, "bio.md", "md")
    highlights = [{"id": "h1", "type": "text", "comment": "ask about ATP",
                   "textAnchor": {"textContent": "powerhouse of the cell"}}]
    await db.execute("UPDATE documents SET highlights = ? WHERE id = ?", (json.dumps(highlights), doc_id))
    await db.commit()

    await svc.update_content(doc_id, body + "\n\nMore.")

    cursor = await db.execute(
        "SELECT annotations_text FROM document_chunks WHERE document_id = ? AND has_highlight = 1", (doc_id,),
    )
    assert any("ask about ATP" in (row[0] or "") for row in await cursor.fetchall())


async def test_concurrent_renames_to_one_name_never_clobber(service, tmp_path: Path) -> None:
    import asyncio

    from fastapi import HTTPException

    svc, db = service
    (tmp_path / "a.md").write_text("A")
    (tmp_path / "b.md").write_text("B")
    doc_a = await _seed(db, "a.md", "md")
    await db.execute(
        "INSERT INTO documents (id, user_id, filename, title, path, relative_path, source_kind, "
        "file_type, status, content, highlights, tags, version, document_number) "
        "VALUES ('doc-b', ?, 'b.md', 'b', '/', 'b.md', 'source', 'md', 'ready', 'B', '[]', '[]', 0, 2)",
        (USER_ID,),
    )
    await db.commit()

    results = await asyncio.gather(
        svc.update_metadata(doc_a, {"filename": "c.md"}),
        svc.update_metadata("doc-b", {"filename": "c.md"}),
        return_exceptions=True,
    )

    conflicts = [r for r in results if isinstance(r, HTTPException) and r.status_code == 409]
    assert len(conflicts) == 1
    survivors = sorted(p.read_text() for p in tmp_path.glob("*.md"))
    assert survivors == ["A", "B"]


async def test_rename_works_without_hard_link_support(service, tmp_path: Path, monkeypatch) -> None:
    import services.local as local_module

    def no_links(src, dst):
        raise PermissionError("hard links not supported")

    monkeypatch.setattr(local_module.os, "link", no_links)
    svc, db = service
    (tmp_path / "a.md").write_text("A")
    doc_a = await _seed(db, "a.md", "md")

    await svc.update_metadata(doc_a, {"filename": "c.md"})

    assert (tmp_path / "c.md").read_text() == "A"
    assert not (tmp_path / "a.md").exists()


async def test_failed_source_removal_leaves_no_second_path(service, tmp_path: Path, monkeypatch) -> None:
    from pathlib import Path as RealPath

    svc, db = service
    (tmp_path / "a.md").write_text("A")
    doc_a = await _seed(db, "a.md", "md")
    real_unlink = RealPath.unlink

    def refuse_source(self, missing_ok=False):
        if self.name == "a.md":
            raise PermissionError("source directory is read-only")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(RealPath, "unlink", refuse_source)

    with pytest.raises(PermissionError):
        await svc.update_metadata(doc_a, {"filename": "c.md"})

    assert (tmp_path / "a.md").read_text() == "A"
    assert not (tmp_path / "c.md").exists()


async def test_failed_copy_metadata_leaves_no_second_path(service, tmp_path: Path, monkeypatch) -> None:
    import services.local as local_module

    def no_links(src, dst):
        raise PermissionError("hard links not supported")

    def refuse_copystat(src, dst):
        raise PermissionError("cannot set times on this mount")

    monkeypatch.setattr(local_module.os, "link", no_links)
    monkeypatch.setattr(local_module.shutil, "copystat", refuse_copystat)
    svc, db = service
    (tmp_path / "a.md").write_text("A")
    doc_a = await _seed(db, "a.md", "md")

    with pytest.raises(PermissionError):
        await svc.update_metadata(doc_a, {"filename": "c.md"})

    assert (tmp_path / "a.md").read_text() == "A"
    assert not (tmp_path / "c.md").exists()


@pytest.mark.parametrize('extension', ['docx', 'doc', 'pptx', 'ppt'])
@pytest.mark.parametrize('namespace', ['local', USER_ID])
async def test_office_preview_serves_converted_pdf(service, tmp_path, extension, namespace):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import files

    svc, db = service
    doc_id = await _seed(db, f'source.{extension}', extension)
    (tmp_path / f'source.{extension}').write_bytes(b'PK original office file')
    key = f'{namespace}/{doc_id}/converted.pdf'
    converted = tmp_path / '.llmwiki' / 'cache' / key
    converted.parent.mkdir(parents=True)
    converted.write_bytes(b'%PDF-1.7 converted preview')

    result = await svc.get_url(doc_id)
    assert result['url'].endswith(f'/v1/files/{key}')
    files.set_workspace_root(str(tmp_path))
    app = FastAPI()
    app.include_router(files.router)
    with TestClient(app) as client:
        response = client.get(f'/v1/files/{key}')
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/pdf'
    assert response.content == converted.read_bytes()


async def test_office_preview_without_conversion_does_not_return_docx(service):
    from fastapi import HTTPException

    svc, db = service
    doc_id = await _seed(db, 'source.docx', 'docx')
    with pytest.raises(HTTPException) as exc:
        await svc.get_url(doc_id)
    assert exc.value.status_code == 409


async def test_pdf_preview_still_returns_original(service):
    svc, db = service
    doc_id = await _seed(db, 'source.pdf', 'pdf')
    assert (await svc.get_url(doc_id))['url'].endswith('/v1/files/source.pdf')
