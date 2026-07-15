"""Validation tests for the polymorphic highlight locator contract."""

import pytest
from pydantic import ValidationError

from services.types import Highlight


def _base(**overrides):
    value = {
        "id": "h1",
        "type": "text",
        "textAnchor": {"textStart": 0, "textEnd": 4, "textContent": "text"},
        "comment": None,
        "color": "yellow",
        "createdAt": "2026-07-11T00:00:00Z",
    }
    value.update(overrides)
    return value


def test_text_highlight_requires_a_text_locator():
    with pytest.raises(ValidationError, match="require anchor or textAnchor"):
        Highlight(**_base(textAnchor=None))


def test_pdf_highlight_requires_pdf_anchor_exclusively():
    with pytest.raises(ValidationError, match="cannot include text anchors"):
        Highlight(**_base(
            type="pdf",
            pdfAnchor={
                "page": 1,
                "textContent": "text",
                "rects": [{"x": 0, "y": 0, "width": 10, "height": 10}],
            },
        ))


def test_pdf_offsets_must_be_a_valid_pair():
    with pytest.raises(ValidationError, match="provided together"):
        Highlight(**_base(
            type="pdf",
            textAnchor=None,
            pdfAnchor={
                "page": 1,
                "textStart": 2,
                "textContent": "text",
                "rects": [{"x": 0, "y": 0, "width": 10, "height": 10}],
            },
        ))


def test_legacy_pdf_anchor_without_offsets_remains_valid():
    highlight = Highlight(**_base(
        type="pdf",
        textAnchor=None,
        pdfAnchor={
            "page": 1,
            "textContent": "text",
            "rects": [{"x": 0, "y": 0, "width": 10, "height": 10}],
        },
    ))
    assert highlight.pdfAnchor is not None
    assert highlight.pdfAnchor.textStart is None
