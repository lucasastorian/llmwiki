"""Production web-clip parse of every frozen real page equals its reviewed golden, byte for byte."""
from __future__ import annotations

import pytest

from tests.support.real_pages import load_goldens, load_pages, sha256_text
from tests.support.regenerate_real_page_goldens import render_golden
from tests.support.types import RealPage

PAGES = load_pages()
GOLDENS = load_goldens()
DIVERGENCE_CONTEXT = 120
REGENERATE_HINT = "if intended, run: PYTHONPATH=api python -m tests.support.regenerate_real_page_goldens"


def test_every_page_has_exactly_one_golden() -> None:
    assert sorted(GOLDENS) == sorted(page["id"] for page in PAGES)


@pytest.mark.parametrize("page", PAGES, ids=[page["id"] for page in PAGES])
def test_parser_output_matches_golden(page: RealPage) -> None:
    golden = GOLDENS[page["id"]]
    actual = render_golden(page)
    assert golden["markdown_sha256"] == sha256_text(golden["markdown"])
    for field in ("markdown", "plaintext"):
        assert actual[field] == golden[field], _first_divergence(field, golden[field], actual[field])


def _first_divergence(field: str, expected: str, actual: str) -> str:
    index = next(
        (i for i, (left, right) in enumerate(zip(expected, actual, strict=False)) if left != right),
        min(len(expected), len(actual)),
    )
    start = max(0, index - DIVERGENCE_CONTEXT)
    end = index + DIVERGENCE_CONTEXT
    return (
        f"{field} diverges at char {index} (golden {len(expected)} chars, actual {len(actual)}):\n"
        f"golden: {expected[start:end]!r}\nactual: {actual[start:end]!r}\n{REGENERATE_HINT}"
    )
