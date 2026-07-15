"""Parse citations and cross-references from wiki page content, store as edges."""

import re
import logging

from vaultfs import VaultFS

logger = logging.getLogger(__name__)

_CITATION_RE = re.compile(r"\[\^\d+\]:\s*(.+)$", re.MULTILINE)
_WIKI_LINK_RE = re.compile(r"(?<!!)\[(?:[^\]]*)\]\(([^)]+)\)")


def _parse_citation_filename(raw: str) -> tuple[str, int | None]:
    """Extract filename and optional page from a citation like 'paper.pdf, p.3'."""
    raw = raw.strip().lstrip("*").rstrip("*")
    link_match = re.match(r"\[([^\]]+)\]\([^)]*\)(.*)$", raw)
    if link_match:
        raw = f"{link_match.group(1)}{link_match.group(2)}"
    raw = re.split(r"\s+[-–—]\s+", raw, maxsplit=1)[0].strip()
    page_match = re.search(r",\s*p\.?\s*(\d+)\b", raw)
    if page_match:
        filename = raw[:page_match.start()].strip()
        page = int(page_match.group(1))
    else:
        filename = raw
        page = None
    return filename, page


def _parse_wiki_links(content: str, current_dir: str) -> list[str]:
    """Extract internal wiki link paths, resolved relative to current_dir."""
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


async def update_references(fs: VaultFS, kb_id: str, document_id: str, content: str, doc_path: str) -> None:
    """Parse content for citations and links, rebuild reference edges for this document."""
    wiki_relative_dir = doc_path.replace("/wiki/", "", 1) if doc_path.startswith("/wiki/") else ""

    all_docs = await fs.list_documents(kb_id)

    filename_to_doc: dict[str, dict] = {}
    basename_to_doc: dict[str, dict] = {}
    wiki_path_to_doc: dict[str, dict] = {}
    for doc in all_docs:
        fn_lower = doc["filename"].lower()
        if fn_lower not in filename_to_doc:
            filename_to_doc[fn_lower] = doc
        if doc.get("title"):
            title_lower = doc["title"].lower()
            if title_lower not in filename_to_doc:
                filename_to_doc[title_lower] = doc

        base = re.sub(
            r"\.(pdf|docx?|pptx?|xlsx?|csv|html?|md|txt)$",
            "",
            fn_lower,
        )
        basename_to_doc.setdefault(base, doc)

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
            target = basename_to_doc.get(base)
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

    deduped: list[tuple[str, str, int | None]] = []
    seen: set[tuple[str, str]] = set()
    for target_id, ref_type, page in edges:
        key = (target_id, ref_type)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((target_id, ref_type, page))

    await fs.replace_references(document_id, kb_id, deduped)

    logger.info(
        "Updated references for doc=%s: %d citations, %d links",
        document_id[:8],
        sum(1 for _, t, _ in edges if t == "cites"),
        sum(1 for _, t, _ in edges if t == "links_to"),
    )


async def get_backlinks_summary(fs: VaultFS, doc_id: str) -> str:
    """Return backlinks for display when reading a page."""
    rows = await fs.get_backlinks(doc_id)
    if not rows:
        return ""
    lines = [f"\n---\n**Referenced by ({len(rows)}):**"]
    for r in rows:
        title = r["title"] or r["filename"]
        lines.append(f"  - {title} ({r['reference_type']})")
    return "\n".join(lines)
