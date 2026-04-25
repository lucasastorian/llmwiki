"""Local reference graph — SQLite version of tools/references.py.

Parses citations and cross-references from wiki page content, stores as edges
in the document_references table, and propagates staleness.
"""

import re
import logging

from infra.db.sqlite import get_db, get_document, list_documents

logger = logging.getLogger(__name__)

_CITATION_RE = re.compile(r"\[\^\d+\]:\s*(.+)$", re.MULTILINE)
_WIKI_LINK_RE = re.compile(r"\[(?:[^\]]*)\]\(([^)]+)\)")


def _parse_citation_filename(raw: str) -> tuple[str, int | None]:
    raw = raw.strip().lstrip("*").rstrip("*")
    link_match = re.match(r"\[([^\]]+)\]\([^)]*\)", raw)
    if link_match:
        raw = link_match.group(1)
    parts = re.match(r"^(.+?)(?:,\s*p\.?\s*(\d+))?(?:\s*[-–].*)?$", raw)
    if not parts:
        return raw, None
    filename = parts.group(1).strip()
    page = int(parts.group(2)) if parts.group(2) else None
    return filename, page


def _parse_wiki_links(content: str, current_dir: str) -> list[str]:
    paths = []
    for match in _WIKI_LINK_RE.finditer(content):
        href = match.group(1)
        if href.startswith(("http", "#", "mailto:", "data:")):
            continue
        if re.search(r"\.(png|jpg|jpeg|gif|webp|svg)$", href, re.IGNORECASE):
            continue

        if href.startswith("/wiki/"):
            resolved = href.replace("/wiki/", "", 1)
        elif href.startswith("./"):
            resolved = (current_dir + href[2:]) if current_dir else href[2:]
        elif href.startswith("../"):
            parts = (current_dir.rstrip("/") + "/" + href).split("/")
            resolved_parts = []
            for p in parts:
                if p == "..":
                    if resolved_parts:
                        resolved_parts.pop()
                elif p and p != ".":
                    resolved_parts.append(p)
            resolved = "/".join(resolved_parts)
        elif "/" not in href:
            resolved = (current_dir + href) if current_dir else href
        else:
            resolved = href

        if resolved:
            paths.append(resolved)
    return paths


async def update_references(
    user_id: str, kb_slug: str, document_id: str, content: str, doc_path: str,
) -> None:
    db = await get_db()
    wiki_relative_dir = doc_path.replace("/wiki/", "", 1) if doc_path.startswith("/wiki/") else ""

    all_docs = await list_documents(user_id, kb_slug)

    filename_to_doc: dict[str, dict] = {}
    wiki_path_to_doc: dict[str, dict] = {}
    for doc in all_docs:
        fn_lower = doc["filename"].lower()
        if fn_lower not in filename_to_doc:
            filename_to_doc[fn_lower] = doc
        if doc.get("title"):
            title_lower = doc["title"].lower()
            if title_lower not in filename_to_doc:
                filename_to_doc[title_lower] = doc
        if doc["path"].startswith("/wiki/"):
            relative = (doc["path"] + doc["filename"]).replace("/wiki/", "", 1)
            wiki_path_to_doc[relative.lower()] = doc

    edges: list[tuple[str, str, int | None]] = []

    for match in _CITATION_RE.finditer(content):
        filename, page = _parse_citation_filename(match.group(1))
        fn_lower = filename.lower()
        target = filename_to_doc.get(fn_lower)
        if not target:
            base = re.sub(r"\.(pdf|docx?|pptx?|xlsx?|csv|html?|md|txt)$", "", fn_lower)
            for doc in all_docs:
                doc_base = re.sub(r"\.(pdf|docx?|pptx?|xlsx?|csv|html?|md|txt)$", "", doc["filename"].lower())
                if doc_base == base:
                    target = doc
                    break
        if target and str(target["id"]) != document_id:
            edges.append((str(target["id"]), "cites", page))

    link_paths = _parse_wiki_links(content, wiki_relative_dir)
    for link_path in link_paths:
        target = wiki_path_to_doc.get(link_path.lower())
        if not target:
            target = wiki_path_to_doc.get(link_path.lower() + ".md")
        if not target:
            basename = link_path.split("/")[-1].lower()
            target = wiki_path_to_doc.get(basename)
        if target and str(target["id"]) != document_id:
            edges.append((str(target["id"]), "links_to", None))

    await db.execute("DELETE FROM document_references WHERE source_document_id = ?", (document_id,))

    seen = set()
    for target_id, ref_type, page in edges:
        key = (target_id, ref_type)
        if key in seen:
            continue
        seen.add(key)
        try:
            await db.execute(
                "INSERT OR REPLACE INTO document_references "
                "(source_document_id, target_document_id, reference_type, page) "
                "VALUES (?, ?, ?, ?)",
                (document_id, target_id, ref_type, page),
            )
        except Exception as e:
            logger.warning("Failed to insert reference %s -> %s: %s", document_id[:8], target_id[:8], e)

    await db.commit()
    logger.info(
        "Updated references for doc=%s: %d citations, %d links",
        document_id[:8],
        sum(1 for _, t, _ in edges if t == "cites"),
        sum(1 for _, t, _ in edges if t == "links_to"),
    )


async def propagate_staleness(document_id: str) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE documents SET stale_since = datetime('now') "
        "WHERE id IN ("
        "  SELECT source_document_id FROM document_references "
        "  WHERE target_document_id = ? AND reference_type = 'links_to'"
        ") AND stale_since IS NULL",
        (document_id,),
    )
    await db.commit()


async def get_impact_surface(user_id: str, document_id: str) -> str:
    db = await get_db()
    cursor = await db.execute(
        "SELECT d.path, d.filename, d.title, dr.reference_type "
        "FROM document_references dr "
        "JOIN documents d ON dr.source_document_id = d.id "
        "WHERE dr.target_document_id = ? AND d.status != 'failed' "
        "ORDER BY d.path, d.filename",
        (document_id,),
    )
    rows = await cursor.fetchall()
    cols = [c[0] for c in cursor.description]
    rows = [dict(zip(cols, r)) for r in rows]

    if not rows:
        return ""

    lines = [f"\n**{len(rows)} page(s) reference this document** — consider updating:"]
    for r in rows:
        path = f"{r['path']}{r['filename']}"
        title = r["title"] or r["filename"]
        ref = "cites" if r["reference_type"] == "cites" else "links to"
        lines.append(f"  - `{path}` ({title}) — {ref} this page")
    return "\n".join(lines)


async def get_backlinks_summary(user_id: str, document_id: str) -> str:
    db = await get_db()
    cursor = await db.execute(
        "SELECT d.path, d.filename, d.title, dr.reference_type "
        "FROM document_references dr "
        "JOIN documents d ON dr.source_document_id = d.id "
        "WHERE dr.target_document_id = ? AND d.status != 'failed' "
        "ORDER BY d.path, d.filename",
        (document_id,),
    )
    rows = await cursor.fetchall()
    cols = [c[0] for c in cursor.description]
    rows = [dict(zip(cols, r)) for r in rows]

    if not rows:
        return ""

    lines = [f"\n---\n**Referenced by ({len(rows)}):**"]
    for r in rows:
        title = r["title"] or r["filename"]
        lines.append(f"  - {title} ({r['reference_type']})")
    return "\n".join(lines)


async def query_references(user_id: str, kb_slug: str, path: str, query: str) -> str:
    db = await get_db()

    if query == "uncited":
        cursor = await db.execute(
            "SELECT d.filename, d.title, d.path, d.file_type "
            "FROM documents d "
            "WHERE d.source_kind != 'wiki' AND d.status != 'failed' "
            "  AND d.id NOT IN (SELECT target_document_id FROM document_references WHERE reference_type = 'cites') "
            "ORDER BY d.filename",
        )
        rows = await cursor.fetchall()
        cols = [c[0] for c in cursor.description]
        rows = [dict(zip(cols, r)) for r in rows]
        if not rows:
            return "All sources are cited in at least one wiki page."
        lines = [f"**{len(rows)} uncited source(s)** — not referenced by any wiki page:\n"]
        for r in rows:
            lines.append(f"  {r['path']}{r['filename']} ({r['file_type']})")
        return "\n".join(lines)

    if query == "stale":
        cursor = await db.execute(
            "SELECT d.filename, d.title, d.path, d.stale_since "
            "FROM documents d "
            "WHERE d.status != 'failed' AND d.stale_since IS NOT NULL "
            "ORDER BY d.stale_since DESC",
        )
        rows = await cursor.fetchall()
        cols = [c[0] for c in cursor.description]
        rows = [dict(zip(cols, r)) for r in rows]
        if not rows:
            return "No stale pages found."
        lines = [f"**{len(rows)} potentially stale page(s):**\n"]
        for r in rows:
            title = r["title"] or r["filename"]
            lines.append(f"  {r['path']}{r['filename']} ({title}) — stale since {r['stale_since'] or '?'}")
        return "\n".join(lines)

    if not path or path in ("*", "**"):
        return "references mode requires a `path` to a specific document, or `query=\"uncited\"` / `query=\"stale\"`."

    from .helpers import resolve_path
    dir_path, filename = resolve_path(path)
    doc = await get_document(user_id, kb_slug, filename, dir_path)
    if not doc:
        return f"Document '{path}' not found."

    doc_id = str(doc["id"])

    cursor = await db.execute(
        "SELECT d.filename, d.title, d.path, dr.reference_type, dr.page "
        "FROM document_references dr JOIN documents d ON dr.target_document_id = d.id "
        "WHERE dr.source_document_id = ? AND d.status != 'failed' "
        "ORDER BY dr.reference_type, d.path, d.filename",
        (doc_id,),
    )
    forward = [dict(zip([c[0] for c in cursor.description], r)) for r in await cursor.fetchall()]

    cursor = await db.execute(
        "SELECT d.filename, d.title, d.path, dr.reference_type, dr.page "
        "FROM document_references dr JOIN documents d ON dr.source_document_id = d.id "
        "WHERE dr.target_document_id = ? AND d.status != 'failed' "
        "ORDER BY dr.reference_type, d.path, d.filename",
        (doc_id,),
    )
    backlinks = [dict(zip([c[0] for c in cursor.description], r)) for r in await cursor.fetchall()]

    title = doc.get("title") or doc["filename"]
    lines = [f"**References for {title}** (`{dir_path}{filename}`):\n"]

    if forward:
        cites = [r for r in forward if r["reference_type"] == "cites"]
        links = [r for r in forward if r["reference_type"] == "links_to"]
        if cites:
            lines.append(f"**Cites ({len(cites)} sources):**")
            for r in cites:
                page_str = f", p.{r['page']}" if r.get("page") else ""
                lines.append(f"  {r['path']}{r['filename']}{page_str}")
        if links:
            lines.append(f"\n**Links to ({len(links)} pages):**")
            for r in links:
                lines.append(f"  {r['path']}{r['filename']} ({r.get('title') or r['filename']})")
    else:
        lines.append("No outgoing references.")

    lines.append("")
    if backlinks:
        lines.append(f"**Referenced by ({len(backlinks)} pages):**")
        for r in backlinks:
            ref = "cites" if r["reference_type"] == "cites" else "links to"
            lines.append(f"  {r['path']}{r['filename']} ({r.get('title') or r['filename']}) — {ref}")
    else:
        lines.append("No incoming references (backlinks).")

    return "\n".join(lines)
