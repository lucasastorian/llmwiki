"""Python side of the shared fixtures that pin the hand-ported TypeScript modules in web/src/lib to the server."""

import importlib.util
import json
import typing
from pathlib import Path
from types import ModuleType

import pytest
from domain.quiz_lint import lint_quiz_blocks
from html_parser import Parser
from pydantic import BaseModel
from services.types import Highlight, HighlightAnchor, HighlightReply, PdfAnchor, PdfRect, TextAnchor

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "parity"
MCP_QUIZ_LINT = REPO_ROOT / "mcp" / "tools" / "quiz_lint.py"

MODELS: dict[str, type[BaseModel]] = {
    "Highlight": Highlight,
    "HighlightAnchor": HighlightAnchor,
    "TextAnchor": TextAnchor,
    "PdfAnchor": PdfAnchor,
    "PdfRect": PdfRect,
    "HighlightReply": HighlightReply,
}


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _load_mcp_quiz_lint() -> ModuleType:
    """Load by path: the local mcp/ dir shadows the pip `mcp` package and `tools` is not on the API path."""
    spec = importlib.util.spec_from_file_location("mcp_quiz_lint", MCP_QUIZ_LINT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cases(fixture: dict, key: str) -> list:
    return [pytest.param(case, id=case["name"]) for case in fixture[key]]


CANONICAL = _load_fixture("canonical_plaintext.json")
LOCATOR = _load_fixture("highlight_locator.json")
QUIZ = _load_fixture("quiz_parse.json")
TYPES = _load_fixture("highlight_types.json")
MCP_LINT = _load_mcp_quiz_lint()


@pytest.mark.parametrize("case", _cases(CANONICAL, "cases"))
def test_parser_markdown_and_plaintext(case: dict) -> None:
    result = Parser(case["html"]).parse()
    assert result.content == case["markdown"]
    assert result.plaintext == case["plaintext"]


@pytest.mark.parametrize("case", _cases(LOCATOR, "normalizeAnchorText"))
def test_normalize_anchor_text(case: dict) -> None:
    assert Parser._normalize_anchor_text(case["input"]) == case["expected"]


@pytest.mark.parametrize("case", _cases(LOCATOR, "locateTextAnchor"))
def test_locate_highlight(case: dict) -> None:
    payload = {"textContent": case["textContent"], "prefix": case.get("prefix"), "suffix": case.get("suffix")}
    anchor = Parser._locate_highlight(case["plaintext"], payload)
    located = None if anchor is None else {
        "textStart": anchor.text_start,
        "textEnd": anchor.text_end,
        "textContent": anchor.text_content,
    }
    assert located == case["expected"]


@pytest.mark.parametrize("case", _cases(QUIZ, "cases"))
def test_quiz_lint_verdict(case: dict) -> None:
    content = f"```quiz\n{case['yaml']}\n```\n"
    api_errors = lint_quiz_blocks(content)
    assert api_errors == MCP_LINT.lint_quiz_blocks(content)
    assert (not api_errors) == case["pythonValid"]


@pytest.mark.parametrize("name", list(TYPES["models"]))
def test_highlight_model_fields(name: str) -> None:
    assert list(MODELS[name].model_fields) == TYPES["models"][name]["fields"]


def test_highlight_literals() -> None:
    assert list(typing.get_args(Highlight.model_fields["type"].annotation)) == TYPES["literals"]["Highlight.type"]
    author = HighlightReply.model_fields["author"].annotation
    assert list(typing.get_args(author)) == TYPES["literals"]["HighlightReply.author"]
