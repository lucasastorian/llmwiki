"""Reference parsing and graph building.

Parses wiki page content for footnote citations ([^N]: filename.pdf, p.3)
and internal links ([text](path.md)), stores edges in document_references.
"""

import re
import logging

logger = logging.getLogger(__name__)

_CITATION_RE = re.compile(r"\[\^\d+\]:\s*(.+)$", re.MULTILINE)
_WIKI_LINK_RE = re.compile(r"(?<!!)\[(?:[^\]]*)\]\(([^)]+)\)")


def parse_citation_filename(raw: str) -> tuple[str, int | None]:
    """Extract filename and optional page from a citation like 'paper.pdf, p.3'."""
    raw = raw.strip().lstrip("*").rstrip("*")
    link_match = re.match(r"\[([^\]]+)\]\([^)]*\)", raw)
    if link_match:
        raw = link_match.group(1)
    parts = re.match(r"^(.+?)(?:,\s*p\.?\s*(\d+))?(?:\s*[-–—].*)?$", raw)
    if not parts:
        return raw, None
    filename = parts.group(1).strip()
    page = int(parts.group(2)) if parts.group(2) else None
    return filename, page


def parse_wiki_links(content: str, current_dir: str) -> list[str]:
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


def build_lookup_maps(
    all_docs: list[dict],
) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    """Build filename, base-name, and wiki-path lookup dicts from a doc list."""
    filename_to_doc: dict[str, dict] = {}
    base_to_doc: dict[str, dict] = {}
    wiki_path_to_doc: dict[str, dict] = {}

    for doc in all_docs:
        fn_lower = doc["filename"].lower()
        if fn_lower not in filename_to_doc:
            filename_to_doc[fn_lower] = doc
        if doc.get("title"):
            title_lower = doc["title"].lower()
            if title_lower not in filename_to_doc:
                filename_to_doc[title_lower] = doc
        base = re.sub(r"\.(pdf|docx?|pptx?|xlsx?|csv|html?|md|txt)$", "", fn_lower)
        if base not in base_to_doc:
            base_to_doc[base] = doc
        if doc["path"].startswith("/wiki/"):
            relative = (doc["path"] + doc["filename"]).replace("/wiki/", "", 1)
            wiki_path_to_doc[relative.lower()] = doc

    return filename_to_doc, base_to_doc, wiki_path_to_doc


def extract_references(
    content: str,
    doc_id: str,
    wiki_dir: str,
    filename_to_doc: dict[str, dict],
    base_to_doc: dict[str, dict],
    wiki_path_to_doc: dict[str, dict],
) -> list[dict]:
    """Parse content and return a list of reference edges.

    Each edge is: {"target_id": str, "type": "cites"|"links_to", "page": int|None}
    """
    edges: list[dict] = []
    seen: set[tuple[str, str]] = set()

    # Footnote citations: [^N]: filename.pdf, p.3
    for match in _CITATION_RE.finditer(content):
        filename, page = parse_citation_filename(match.group(1))
        fn_lower = filename.lower()
        target = filename_to_doc.get(fn_lower)
        if not target:
            base = re.sub(r"\.(pdf|docx?|pptx?|xlsx?|csv|html?|md|txt)$", "", fn_lower)
            target = base_to_doc.get(base)
        if target and target["id"] != doc_id:
            key = (target["id"], "cites")
            if key not in seen:
                seen.add(key)
                edges.append({"target_id": target["id"], "type": "cites", "page": page})

    # Wiki cross-references: [text](path.md)
    for link_path in parse_wiki_links(content, wiki_dir):
        target = wiki_path_to_doc.get(link_path.lower())
        if not target:
            target = wiki_path_to_doc.get(link_path.lower() + ".md")
        if not target:
            basename = link_path.split("/")[-1].lower()
            target = wiki_path_to_doc.get(basename)
        if target and target["id"] != doc_id:
            key = (target["id"], "links_to")
            if key not in seen:
                seen.add(key)
                edges.append({"target_id": target["id"], "type": "links_to", "page": None})

    return edges
