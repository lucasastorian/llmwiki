"""Graph service — queries and rebuilds the document reference graph.

All SQL lives here. Routes should never execute queries directly.
"""

import json
import logging
import uuid

from services.references import build_lookup_maps, extract_references

logger = logging.getLogger(__name__)


def _parse_json(raw, default=None):
    """Safely parse a JSON string or return the value if already parsed."""
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def _build_node(r: dict) -> dict:
    meta = _parse_json(r.get("metadata"), {})
    tags = _parse_json(r.get("tags"), [])
    return {
        "id": str(r["id"]),
        "title": r["title"] or r["filename"].removesuffix(".md").replace("-", " ").replace("_", " "),
        "description": meta.get("description") if isinstance(meta, dict) else None,
        "path": r["path"],
        "file_type": r["file_type"],
        "source_kind": r.get("source_kind", "source"),
        "tags": tags if isinstance(tags, list) else [],
    }


def _build_edge(r: dict) -> dict:
    return {
        "source": str(r["source_document_id"]),
        "target": str(r["target_document_id"]),
        "type": r["reference_type"],
        "page": r["page"],
    }


# ── Hosted (asyncpg) ──

async def get_graph_hosted(conn, kb_id, user_id: str) -> dict:
    """Return {nodes, edges} for the knowledge graph viewer."""
    doc_rows = await conn.fetch(
        "SELECT id, filename, title, path, file_type, metadata, tags, "
        "CASE WHEN path LIKE '/wiki/%' THEN 'wiki' ELSE 'source' END AS source_kind "
        "FROM documents "
        "WHERE knowledge_base_id = $1 AND user_id = $2 AND NOT archived "
        "AND status != 'failed'",
        kb_id, user_id,
    )

    doc_ids = {r["id"] for r in doc_rows}

    ref_rows = await conn.fetch(
        "SELECT source_document_id, target_document_id, reference_type, page "
        "FROM document_references WHERE knowledge_base_id = $1",
        kb_id,
    )

    return {
        "nodes": [_build_node(dict(r)) for r in doc_rows],
        "edges": [_build_edge(dict(r)) for r in ref_rows
                  if r["source_document_id"] in doc_ids and r["target_document_id"] in doc_ids],
    }


async def rebuild_hosted(conn, kb_id, user_id: str) -> dict:
    """Parse wiki pages and rebuild reference edges atomically.

    Runs through RLS (authenticated role) — the database enforces that
    the user can only read/write their own documents and references.
    Uses a savepoint for atomicity within the ScopedDB transaction.
    """
    all_docs = [dict(r) for r in await conn.fetch(
        "SELECT id, filename, title, path, file_type "
        "FROM documents "
        "WHERE knowledge_base_id = $1 AND user_id = $2 AND NOT archived",
        kb_id, user_id,
    )]

    filename_to_doc, base_to_doc, wiki_path_to_doc = build_lookup_maps(all_docs)

    wiki_pages = [dict(r) for r in await conn.fetch(
        "SELECT id, filename, path, content "
        "FROM documents "
        "WHERE knowledge_base_id = $1 AND user_id = $2 "
        "AND path LIKE '/wiki/%%' AND NOT archived AND file_type = 'md' "
        "AND content IS NOT NULL AND content != ''",
        kb_id, user_id,
    )]

    # Atomic: transaction wraps the delete + all inserts
    async with conn.transaction():
        await conn.execute(
            "DELETE FROM document_references "
            "WHERE knowledge_base_id = $1 "
            "AND knowledge_base_id IN (SELECT id FROM knowledge_bases WHERE user_id = $2)",
            kb_id, user_id,
        )

        total_cites = 0
        total_links = 0

        for page in wiki_pages:
            content = page["content"] or ""
            if not content:
                continue

            wiki_dir = page["path"].replace("/wiki/", "", 1) if page["path"].startswith("/wiki/") else ""
            edges = extract_references(
                content, page["id"], wiki_dir,
                filename_to_doc, base_to_doc, wiki_path_to_doc,
            )

            for edge in edges:
                if edge["type"] == "cites":
                    await conn.execute(
                        "INSERT INTO document_references "
                        "(source_document_id, target_document_id, knowledge_base_id, reference_type, page) "
                        "VALUES ($1, $2, $3, 'cites', $4) "
                        "ON CONFLICT (source_document_id, target_document_id, reference_type) "
                        "DO UPDATE SET page = EXCLUDED.page, created_at = now()",
                        page["id"], edge["target_id"], kb_id, edge["page"],
                    )
                    total_cites += 1
                else:
                    await conn.execute(
                        "INSERT INTO document_references "
                        "(source_document_id, target_document_id, knowledge_base_id, reference_type) "
                        "VALUES ($1, $2, $3, 'links_to') "
                        "ON CONFLICT (source_document_id, target_document_id, reference_type) DO NOTHING",
                        page["id"], edge["target_id"], kb_id,
                    )
                    total_links += 1

    logger.info("Rebuilt references for KB %s: %d citations, %d links", str(kb_id)[:8], total_cites, total_links)
    return {"citations": total_cites, "links": total_links}


# ── Local (aiosqlite) ──

async def get_graph_local(db, user_id: str) -> dict:
    """Return {nodes, edges} for the knowledge graph viewer (SQLite)."""
    doc_rows = await db.execute_fetchall(
        "SELECT id, filename, title, path, file_type, source_kind, metadata, tags "
        "FROM documents WHERE user_id = ? AND status != 'failed'",
        (user_id,),
    )

    doc_ids = {r["id"] for r in doc_rows}

    ref_rows = await db.execute_fetchall(
        "SELECT source_document_id, target_document_id, reference_type, page "
        "FROM document_references",
    )

    return {
        "nodes": [_build_node(dict(r)) for r in doc_rows],
        "edges": [_build_edge(dict(r)) for r in ref_rows
                  if r["source_document_id"] in doc_ids and r["target_document_id"] in doc_ids],
    }


async def rebuild_local(db, user_id: str) -> dict:
    """Parse wiki pages and rebuild reference edges atomically (SQLite)."""
    all_docs = [
        dict(r) for r in await db.execute_fetchall(
            "SELECT id, filename, title, path, file_type, source_kind "
            "FROM documents WHERE user_id = ?",
            (user_id,),
        )
    ]

    filename_to_doc, base_to_doc, wiki_path_to_doc = build_lookup_maps(all_docs)

    wiki_pages = await db.execute_fetchall(
        "SELECT id, filename, path, content FROM documents "
        "WHERE user_id = ? AND source_kind = 'wiki' AND file_type = 'md' AND content IS NOT NULL",
        (user_id,),
    )

    # Atomic: delete + inserts in a single transaction (commit only at the end)
    await db.execute("DELETE FROM document_references")

    total_cites = 0
    total_links = 0

    for page in wiki_pages:
        content = page["content"] or ""
        if not content:
            continue

        wiki_dir = page["path"].replace("/wiki/", "", 1) if page["path"].startswith("/wiki/") else ""
        edges = extract_references(
            content, page["id"], wiki_dir,
            filename_to_doc, base_to_doc, wiki_path_to_doc,
        )

        for edge in edges:
            if edge["type"] == "cites":
                await db.execute(
                    "INSERT INTO document_references (id, source_document_id, target_document_id, reference_type, page) "
                    "VALUES (?, ?, ?, 'cites', ?) "
                    "ON CONFLICT (source_document_id, target_document_id, reference_type) "
                    "DO UPDATE SET page = excluded.page",
                    (str(uuid.uuid4()), page["id"], edge["target_id"], edge["page"]),
                )
                total_cites += 1
            else:
                await db.execute(
                    "INSERT INTO document_references (id, source_document_id, target_document_id, reference_type) "
                    "VALUES (?, ?, ?, 'links_to') "
                    "ON CONFLICT (source_document_id, target_document_id, reference_type) DO NOTHING",
                    (str(uuid.uuid4()), page["id"], edge["target_id"]),
                )
                total_links += 1

    await db.commit()
    logger.info("Rebuilt references: %d citations, %d links", total_cites, total_links)
    return {"citations": total_cites, "links": total_links}
