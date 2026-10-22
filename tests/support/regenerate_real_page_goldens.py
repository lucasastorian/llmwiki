"""Rewrite tests/fixtures/real_pages/goldens.json.gz from the current parser and print what changed.

Run manually: PYTHONPATH=api python -m tests.support.regenerate_real_page_goldens
"""
from __future__ import annotations

import difflib

from html_parser import Parser

from tests.support.real_pages import GOLDENS_PATH, load_goldens, load_pages, save_goldens, sha256_text
from tests.support.types import PageGolden, RealPage

MAX_DIFF_LINES_PER_FIELD = 80


def main() -> None:
    previous = load_goldens() if GOLDENS_PATH.exists() else {}
    goldens = {page["id"]: render_golden(page) for page in load_pages()}
    for page_id, golden in goldens.items():
        _report_change(page_id, previous.get(page_id), golden)
    for page_id in previous.keys() - goldens.keys():
        print(f"removed {page_id}")
    save_goldens(goldens)
    print(f"wrote {len(goldens)} goldens to {GOLDENS_PATH}")


def render_golden(page: RealPage) -> PageGolden:
    """The production web-clip parse of one page."""
    result = Parser(page["html"], url=page["url"], content_only=True).parse()
    return PageGolden(
        markdown=result.content,
        plaintext=result.plaintext,
        markdown_sha256=sha256_text(result.content),
    )


def _report_change(page_id: str, before: PageGolden | None, after: PageGolden) -> None:
    if before is None:
        print(f"added {page_id}")
        return
    for field in ("markdown", "plaintext"):
        if before[field] != after[field]:
            print(f"changed {page_id} {field}")
            _print_diff(before[field], after[field])


def _print_diff(before: str, after: str) -> None:
    diff = list(difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=1))
    for line in diff[2:MAX_DIFF_LINES_PER_FIELD + 2]:
        print(f"    {line}")
    if len(diff) > MAX_DIFF_LINES_PER_FIELD + 2:
        print(f"    ... {len(diff) - MAX_DIFF_LINES_PER_FIELD - 2} more diff lines")


if __name__ == "__main__":
    main()
