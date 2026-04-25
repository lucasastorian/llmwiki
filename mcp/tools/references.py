"""Parse citations and cross-references from wiki page content, store as edges."""

import re
import logging

from db import scoped_query, service_execute

logger = logging.getLogger(__name__)

# [^1]: filename.pdf, p.3
_CITATION_RE = re.compile(r"\[\^\d+\]:\s*(.+)$", re.MULTILINE)

# [link text](path.md) — internal wiki links (not http, not anchors)
_WIKI_LINK_RE = re.compile(r"\[(?:[^\]]*)\]\(([^)]+)\)")


def _parse_citation_filename(raw: str) -> tuple[str, int | None]:
    """Extract filename and optional page from a citation like 'paper.pdf, p.3'."""
    raw = raw.strip().lstrip("*").rstrip("*")
    # Strip markdown link syntax: [text](url) → text
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
    """Extract internal wiki link paths, resolved relative to current_dir."""
    paths = []
    for match in _WIKI_LINK_RE.finditer(content):
        href = match.group(1)
        # Skip external, anchor, and mailto links
        if href.startswith(("http", "#", "mailto:", "data:")):
            continue
        # Skip image extensions
        if re.search(r"\.(png|jpg|jpeg|gif|webp|svg)$", href, re.IGNORECASE):
            continue

        # Resolve relative path
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
            # Bare filename — resolve relative to current dir
            resolved = (current_dir + href) if current_dir else href
        else:
            resolved = href

        if resolved:
            paths.append(resolved)
    return paths


async def update_references(
    user_id: str, kb_id: str, document_id: str, content: str, doc_path: str,
) -> None:
    """Parse content for citations and links, rebuild reference edges for this document."""
    # Determine current directory for relative link resolution
    # doc_path is like "/wiki/concepts/" and filename is separate
    wiki_relative_dir = doc_path.replace("/wiki/", "", 1) if doc_path.startswith("/wiki/") else ""

    # Fetch all docs in this KB for resolving filenames/paths
    all_docs = await scoped_query(
        user_id,
        "SELECT id::text, filename, title, path, file_type FROM documents "
        "WHERE knowledge_base_id = $1 AND NOT archived AND user_id = $2",
        kb_id, user_id,
    )

    # Build lookup maps
    filename_to_doc: dict[str, dict] = {}
    wiki_path_to_doc: dict[str, dict] = {}
    for doc in all_docs:
        fn_lower = doc["filename"].lower()
        if fn_lower not in filename_to_doc:
            filename_to_doc[fn_lower] = doc
        if doc["title"]:
            title_lower = doc["title"].lower()
            if title_lower not in filename_to_doc:
                filename_to_doc[title_lower] = doc

        if doc["path"].startswith("/wiki/"):
            relative = (doc["path"] + doc["filename"]).replace("/wiki/", "", 1)
            wiki_path_to_doc[relative.lower()] = doc

    edges: list[tuple[str, str, int | None]] = []  # (target_id, ref_type, page)

    # Parse footnote citations: [^N]: filename.pdf, p.3
    for match in _CITATION_RE.finditer(content):
        filename, page = _parse_citation_filename(match.group(1))
        fn_lower = filename.lower()
        target = filename_to_doc.get(fn_lower)
        if not target:
            # Try without extension
            base = re.sub(r"\.(pdf|docx?|pptx?|xlsx?|csv|html?|md|txt)$", "", fn_lower)
            for doc in all_docs:
                doc_base = re.sub(r"\.(pdf|docx?|pptx?|xlsx?|csv|html?|md|txt)$", "", doc["filename"].lower())
                if doc_base == base:
                    target = doc
                    break
        if target and target["id"] != document_id:
            edges.append((target["id"], "cites", page))

    # Parse wiki cross-references: [text](path.md)
    link_paths = _parse_wiki_links(content, wiki_relative_dir)
    for link_path in link_paths:
        target = wiki_path_to_doc.get(link_path.lower())
        if not target:
            # Try adding .md
            target = wiki_path_to_doc.get(link_path.lower() + ".md")
        if not target:
            # Try just the filename part
            basename = link_path.split("/")[-1].lower()
            target = wiki_path_to_doc.get(basename)
        if target and target["id"] != document_id:
            edges.append((target["id"], "links_to", None))

    # Rebuild: delete old edges, insert new
    await service_execute(
        "DELETE FROM document_references WHERE source_document_id = $1",
        document_id,
    )

    # Deduplicate
    seen = set()
    for target_id, ref_type, page in edges:
        key = (target_id, ref_type)
        if key in seen:
            continue
        seen.add(key)
        try:
            await service_execute(
                "INSERT INTO document_references "
                "(source_document_id, target_document_id, knowledge_base_id, reference_type, page) "
                "VALUES ($1, $2, $3, $4, $5) "
                "ON CONFLICT (source_document_id, target_document_id, reference_type) DO UPDATE "
                "SET page = EXCLUDED.page, created_at = now()",
                document_id, target_id, kb_id, ref_type, page,
            )
        except Exception as e:
            logger.warning("Failed to insert reference %s -> %s: %s", document_id[:8], target_id[:8], e)

    logger.info(
        "Updated references for doc=%s: %d citations, %d links",
        document_id[:8],
        sum(1 for _, t, _ in edges if t == "cites"),
        sum(1 for _, t, _ in edges if t == "links_to"),
    )


async def propagate_staleness(user_id: str, document_id: str) -> None:
    """Flag all documents that link_to this document as potentially stale."""
    await service_execute(
        "UPDATE documents SET stale_since = now() "
        "WHERE id IN ("
        "  SELECT source_document_id FROM document_references "
        "  WHERE target_document_id = $1 AND reference_type = 'links_to'"
        ") AND stale_since IS NULL AND user_id = $2",
        document_id, user_id,
    )


async def get_impact_surface(user_id: str, document_id: str) -> str:
    """Return a summary of pages that reference this document (backlinks)."""
    rows = await scoped_query(
        user_id,
        "SELECT d.path, d.filename, d.title, dr.reference_type "
        "FROM document_references dr "
        "JOIN documents d ON dr.source_document_id = d.id "
        "WHERE dr.target_document_id = $1 AND NOT d.archived AND d.user_id = $2 "
        "ORDER BY d.path, d.filename",
        document_id, user_id,
    )
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
    """Return backlinks for display when reading a page."""
    rows = await scoped_query(
        user_id,
        "SELECT d.path, d.filename, d.title, dr.reference_type "
        "FROM document_references dr "
        "JOIN documents d ON dr.source_document_id = d.id "
        "WHERE dr.target_document_id = $1 AND NOT d.archived AND d.user_id = $2 "
        "ORDER BY d.path, d.filename",
        document_id, user_id,
    )
    if not rows:
        return ""

    lines = [f"\n---\n**Referenced by ({len(rows)}):**"]
    for r in rows:
        title = r["title"] or r["filename"]
        lines.append(f"  - {title} ({r['reference_type']})")
    return "\n".join(lines)
