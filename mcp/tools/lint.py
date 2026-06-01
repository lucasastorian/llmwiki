"""Lint tool — deterministic hygiene checks for wiki pages and sources."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from mcp.server.fastmcp import Context, FastMCP

from vaultfs import VaultFS
from .helpers import glob_match
from .references import _parse_citation_filename, _parse_wiki_links
from .write import (
    _extract_frontmatter_tags,
    _extract_metadata,
    _is_footnote_suffix_line,
    _parse_frontmatter,
)

_FOOTNOTE_DEF_RE = re.compile(r"^\[\^([^\]]+)\]:\s*(.+)$", re.MULTILINE)
_FOOTNOTE_USE_RE = re.compile(r"\[\^([^\]]+)\](?!:)")
_SOURCE_EXT_RE = re.compile(r"\.(pdf|docx?|pptx?|xlsx?|csv|html?|md|txt)$", re.IGNORECASE)
_ROOT_PAGES = frozenset({"/wiki/overview.md", "/wiki/index.md", "/wiki/readme.md", "/wiki/log.md"})
# Append-only chronological ledgers — frontmatter/footnote conventions don't apply.
_LEDGER_PAGES = frozenset({"/wiki/log.md"})
_MATCH_ALL_PATHS = frozenset({"*", "**", "**/*"})
_MAX_ISSUES_PER_GROUP = 40

Scope = Literal["all", "wiki", "sources"]


@dataclass(frozen=True)
class LintIssue:
    severity: Literal["error", "warn"]
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class LintContext:
    """Lookups and counts computed once per run and shared across checks."""

    source_lookup: dict[str, dict]
    wiki_lookup: dict[str, dict]
    wiki_page_count: int


class LintHandler:
    """Runs deterministic checks across a knowledge base."""

    def __init__(self, fs: VaultFS, kb: dict):
        self.fs = fs
        self.kb = kb
        self.kb_id = str(kb["id"])
        self.slug = kb["slug"]

    async def run(
        self,
        path: str = "*",
        scope: Scope = "all",
        include_graph: bool = True,
    ) -> str:
        all_docs = await self.fs.list_documents_with_content(self.kb_id)
        docs = self._filter_docs(all_docs, path, scope)
        if not docs:
            return f"No documents matched `{path}` in {self.slug}."

        ctx = LintContext(
            source_lookup=self._source_lookup(all_docs),
            wiki_lookup=self._wiki_lookup(all_docs),
            wiki_page_count=sum(1 for doc in all_docs if self._is_wiki_page(doc)),
        )

        issues: list[LintIssue] = []
        for doc in docs:
            if self._is_wiki_page(doc):
                issues.extend(await self._lint_wiki_page(doc, ctx, include_graph))

        if include_graph:
            issues.extend(await self._lint_kb_wide(path, scope))

        return self._format_report(issues, docs)

    # ----- selection -------------------------------------------------------

    def _filter_docs(self, docs: list[dict], path: str, scope: Scope) -> list[dict]:
        if scope == "wiki":
            docs = [d for d in docs if self._is_wiki_page(d)]
        elif scope == "sources":
            docs = [d for d in docs if not self._is_wiki_page(d)]
        return [d for d in docs if self._path_matches(self._doc_path(d), path)]

    def _path_matches(self, doc_path: str, path: str) -> bool:
        if path in _MATCH_ALL_PATHS:
            return True
        glob_pat = path if path.startswith("/") else "/" + path
        return glob_match(doc_path, glob_pat)

    # ----- per-page checks -------------------------------------------------

    async def _lint_wiki_page(self, doc: dict, ctx: LintContext, include_graph: bool) -> list[LintIssue]:
        path = self._doc_path(doc)
        content = doc.get("content") or ""
        meta = _parse_frontmatter(content)

        issues: list[LintIssue] = []
        if not self._is_ledger_page(doc):
            issues.extend(self._lint_frontmatter(doc, meta))
            issues.extend(self._lint_footnotes(path, content))
        issues.extend(self._lint_citations(doc, content, ctx.source_lookup))
        issues.extend(self._lint_wiki_links(doc, content, ctx.wiki_lookup))

        if include_graph:
            issues.extend(await self._lint_reference_graph(doc, content, ctx.source_lookup))
            issues.extend(await self._lint_orphan(doc, ctx.wiki_page_count))

        return issues

    def _lint_frontmatter(self, doc: dict, meta: dict) -> list[LintIssue]:
        path = self._doc_path(doc)
        if not meta:
            return [LintIssue("error", "missing-frontmatter", path, "wiki page has no YAML frontmatter")]

        issues: list[LintIssue] = []
        title = meta.get("title")
        description = meta.get("description")
        fm_date_raw, _ = _extract_metadata(meta)
        fm_date = self._normalize_date(fm_date_raw)
        fm_tags = _extract_frontmatter_tags(meta)

        if not isinstance(title, str) or not title.strip():
            issues.append(LintIssue("error", "missing-title", path, "frontmatter is missing `title`"))
        if not isinstance(description, str) or not description.strip():
            issues.append(LintIssue("warn", "missing-description", path, "frontmatter is missing `description`"))
        if not fm_date:
            issues.append(LintIssue("warn", "missing-date", path, "frontmatter is missing `date`"))
        if fm_tags is None:
            issues.append(LintIssue("error", "missing-tags", path, "frontmatter is missing `tags`"))
        elif len(fm_tags) < 2:
            issues.append(LintIssue("warn", "too-few-tags", path, "frontmatter should include at least two tags"))

        indexed_tags = [str(t) for t in (doc.get("tags") or [])]
        if fm_tags is not None and self._normalize_tags(fm_tags) != self._normalize_tags(indexed_tags):
            issues.append(LintIssue(
                "warn",
                "tag-index-mismatch",
                path,
                f"frontmatter tags {fm_tags} do not match indexed tags {indexed_tags}",
            ))

        indexed_date = self._normalize_date(doc.get("date"))
        if fm_date and indexed_date and fm_date != indexed_date:
            issues.append(LintIssue(
                "warn",
                "date-index-mismatch",
                path,
                f"frontmatter date `{fm_date}` does not match indexed date `{indexed_date}`",
            ))
        elif fm_date and not indexed_date:
            issues.append(LintIssue("warn", "date-not-indexed", path, "frontmatter date is not indexed"))

        return issues

    def _lint_footnotes(self, path: str, content: str) -> list[LintIssue]:
        issues: list[LintIssue] = []
        def_ids = [footnote_id for footnote_id, _ in _FOOTNOTE_DEF_RE.findall(content)]
        used_ids = _FOOTNOTE_USE_RE.findall(content)

        for footnote_id in sorted({fid for fid in def_ids if def_ids.count(fid) > 1}, key=self._footnote_sort_key):
            issues.append(LintIssue("error", "duplicate-footnote", path, f"footnote `^{footnote_id}` is defined more than once"))

        for footnote_id in sorted(set(used_ids) - set(def_ids), key=self._footnote_sort_key):
            issues.append(LintIssue("error", "footnote-without-definition", path, f"footnote `^{footnote_id}` is used but not defined"))

        for footnote_id in sorted(set(def_ids) - set(used_ids), key=self._footnote_sort_key):
            issues.append(LintIssue("warn", "unused-footnote-definition", path, f"footnote `^{footnote_id}` is defined but not used"))

        if self._has_mid_document_footnotes(content):
            issues.append(LintIssue(
                "warn",
                "footnotes-not-at-tail",
                path,
                "footnote definitions should be grouped at the end of the page",
            ))

        return issues

    def _lint_citations(self, doc: dict, content: str, source_lookup: dict[str, dict]) -> list[LintIssue]:
        path = self._doc_path(doc)
        issues: list[LintIssue] = []
        for footnote_id, raw in _FOOTNOTE_DEF_RE.findall(content):
            filename, _page = _parse_citation_filename(raw)
            if not self._resolve_source(filename, source_lookup):
                issues.append(LintIssue(
                    "error",
                    "unresolved-citation",
                    path,
                    f"footnote `^{footnote_id}` cites `{filename}`, but no matching source exists",
                ))
        return issues

    def _lint_wiki_links(self, doc: dict, content: str, wiki_lookup: dict[str, dict]) -> list[LintIssue]:
        path = self._doc_path(doc)
        current_dir = doc["path"].replace("/wiki/", "", 1) if doc["path"].startswith("/wiki/") else ""
        issues: list[LintIssue] = []
        for link_path in _parse_wiki_links(content, current_dir):
            if not self._resolve_wiki_link(link_path, wiki_lookup):
                issues.append(LintIssue(
                    "error",
                    "dangling-link",
                    path,
                    f"wiki link `{link_path}` does not resolve to a page",
                ))
        return issues

    async def _lint_reference_graph(self, doc: dict, content: str, source_lookup: dict[str, dict]) -> list[LintIssue]:
        path = self._doc_path(doc)
        expected_source_ids: set[str] = set()
        for _footnote_id, raw in _FOOTNOTE_DEF_RE.findall(content):
            filename, _page = _parse_citation_filename(raw)
            target = self._resolve_source(filename, source_lookup)
            if target and str(target["id"]) != str(doc["id"]):
                expected_source_ids.add(str(target["id"]))

        if not expected_source_ids:
            return []

        forward = await self.fs.get_forward_references(str(doc["id"]))
        actual_source_ids = {
            str(ref["id"])
            for ref in forward
            if ref.get("reference_type") == "cites" and ref.get("id")
        }
        missing = expected_source_ids - actual_source_ids
        if not missing:
            return []

        missing_names = sorted(self._doc_path(d) for d in source_lookup.values() if str(d["id"]) in missing)
        return [LintIssue(
            "error",
            "citation-graph-mismatch",
            path,
            f"citation footnotes were not materialized into graph edges: {', '.join(missing_names)}",
        )]

    async def _lint_orphan(self, doc: dict, wiki_page_count: int) -> list[LintIssue]:
        if self._is_root_page(doc) or wiki_page_count <= 1:
            return []
        if await self.fs.get_backlinks(str(doc["id"])):
            return []
        return [LintIssue("warn", "orphan-page", self._doc_path(doc), "wiki page has no incoming links or citations")]

    # ----- knowledge-base-wide checks --------------------------------------

    async def _lint_kb_wide(self, path: str, scope: Scope) -> list[LintIssue]:
        """Graph-wide checks. Each issue is kept only when its path matches the
        run's `path` filter, so narrowing the run narrows these too (rather than
        silently dropping the check)."""
        issues: list[LintIssue] = []
        if scope in ("all", "sources"):
            issues.extend(i for i in await self._lint_uncited_sources() if self._path_matches(i.path, path))
        if scope in ("all", "wiki"):
            issues.extend(i for i in await self._lint_stale_pages() if self._path_matches(i.path, path))
        return issues

    async def _lint_uncited_sources(self) -> list[LintIssue]:
        rows = await self.fs.find_uncited_sources(self.kb_id)
        return [
            LintIssue("warn", "uncited-source", f"{row['path']}{row['filename']}", "source is not cited by any wiki page")
            for row in rows
        ]

    async def _lint_stale_pages(self) -> list[LintIssue]:
        rows = await self.fs.find_stale_pages(self.kb_id)
        return [
            LintIssue("warn", "stale-page", f"{row['path']}{row['filename']}", f"page is stale since {row.get('stale_since') or '?'}")
            for row in rows
        ]

    # ----- report ----------------------------------------------------------

    def _format_report(self, issues: list[LintIssue], docs: list[dict]) -> str:
        if not issues:
            return f"**Lint passed** for {self.kb['name']} ({len(docs)} document(s) checked)."

        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warn"]
        lines = [
            f"**Lint found {len(issues)} issue(s)** in {self.kb['name']} "
            f"({len(errors)} error, {len(warnings)} warning; {len(docs)} document(s) checked).",
        ]

        if errors:
            lines.append("\n**Errors**")
            lines.extend(self._format_issue_lines(errors))
        if warnings:
            lines.append("\n**Warnings**")
            lines.extend(self._format_issue_lines(warnings))

        return "\n".join(lines)

    def _format_issue_lines(self, issues: list[LintIssue]) -> list[str]:
        lines = [
            f"- [{issue.code}] `{issue.path}` — {issue.message}"
            for issue in issues[:_MAX_ISSUES_PER_GROUP]
        ]
        if len(issues) > _MAX_ISSUES_PER_GROUP:
            lines.append(f"- ... {len(issues) - _MAX_ISSUES_PER_GROUP} more")
        return lines

    # ----- lookups & helpers ----------------------------------------------

    def _source_lookup(self, docs: list[dict]) -> dict[str, dict]:
        lookup: dict[str, dict] = {}
        for doc in docs:
            if self._is_wiki_page(doc):
                continue
            for key in self._doc_keys(doc):
                lookup.setdefault(key, doc)
        return lookup

    def _wiki_lookup(self, docs: list[dict]) -> dict[str, dict]:
        lookup: dict[str, dict] = {}
        for doc in docs:
            if not self._is_wiki_page(doc):
                continue
            relative = self._doc_path(doc).replace("/wiki/", "", 1)
            lookup[relative.lower()] = doc
            lookup.setdefault(doc["filename"].lower(), doc)
        return lookup

    def _resolve_source(self, filename: str, source_lookup: dict[str, dict]) -> dict | None:
        key = filename.strip().lower()
        if key in source_lookup:
            return source_lookup[key]
        return source_lookup.get(_SOURCE_EXT_RE.sub("", key))

    def _resolve_wiki_link(self, link_path: str, wiki_lookup: dict[str, dict]) -> dict | None:
        key = link_path.split("#", 1)[0].lower()
        return (
            wiki_lookup.get(key)
            or wiki_lookup.get(f"{key}.md")
            or wiki_lookup.get(key.split("/")[-1])
        )

    def _doc_keys(self, doc: dict) -> list[str]:
        filename = doc["filename"].lower()
        title = str(doc.get("title") or "").lower()
        keys = [filename, _SOURCE_EXT_RE.sub("", filename)]
        if title:
            keys.extend([title, _SOURCE_EXT_RE.sub("", title)])
        return [k for k in keys if k]

    def _has_mid_document_footnotes(self, content: str) -> bool:
        """True when a footnote definition is followed by non-footnote prose.

        Uses the same tail-compatibility rule as the write tool's append logic
        (`_is_footnote_suffix_line`), so "grouped at the end" means the same
        thing in both places.
        """
        lines = content.rstrip().splitlines()
        for idx, line in enumerate(lines):
            if _FOOTNOTE_DEF_RE.match(line):
                return not all(_is_footnote_suffix_line(suffix) for suffix in lines[idx + 1:])
        return False

    def _normalize_tags(self, tags: list[str]) -> list[str]:
        return sorted({str(tag).strip().lower() for tag in tags if str(tag).strip()})

    def _normalize_date(self, value) -> str | None:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat().split("T", 1)[0]
        return str(value).split("T", 1)[0]

    def _doc_path(self, doc: dict) -> str:
        return f"{doc['path']}{doc['filename']}"

    def _is_wiki_page(self, doc: dict) -> bool:
        return doc.get("path", "").startswith("/wiki/")

    def _is_root_page(self, doc: dict) -> bool:
        return self._doc_path(doc) in _ROOT_PAGES

    def _is_ledger_page(self, doc: dict) -> bool:
        return self._doc_path(doc) in _LEDGER_PAGES

    def _footnote_sort_key(self, value: str) -> tuple[int, str]:
        return (0, f"{int(value):08d}") if value.isdigit() else (1, value)


def register(mcp: FastMCP, get_user_id, fs_factory) -> None:
    @mcp.tool(
        name="lint",
        description=(
            "Run deterministic hygiene checks across a knowledge base.\n\n"
            "Checks wiki frontmatter, tag/date index consistency, footnote hygiene, "
            "citation resolution, citation graph edges, dangling wiki links, orphan pages, "
            "uncited sources, and stale pages.\n\n"
            "Use `path` to scope the run, e.g. `*`, `/wiki/**`, or `/wiki/concepts/*.md`."
        ),
    )
    async def lint(
        ctx: Context,
        knowledge_base: str,
        path: str = "*",
        scope: Scope = "all",
        include_graph: bool = True,
    ) -> str:
        user_id = get_user_id(ctx)
        fs = fs_factory(user_id)

        kb = await fs.resolve_kb(knowledge_base)
        if not kb:
            return f"Knowledge base '{knowledge_base}' not found."

        handler = LintHandler(fs, kb)
        return await handler.run(path=path, scope=scope, include_graph=include_graph)
