"""Text request models enforce their limit in encoded bytes, not characters."""

import pytest
from pydantic import ValidationError
from services import types


@pytest.mark.parametrize(
    ("model", "extra"),
    [
        (types.CreateNote, {"filename": "note.md"}),
        (types.UpdateContent, {}),
    ],
)
def test_multibyte_content_uses_utf8_size(monkeypatch, model, extra):
    monkeypatch.setattr(types, "MAX_TEXT_CONTENT_BYTES", 4)

    with pytest.raises(ValidationError, match="UTF-8 encoded"):
        model(content="ééé", **extra)


def test_content_at_limit_is_accepted(monkeypatch):
    monkeypatch.setattr(types, "MAX_TEXT_CONTENT_BYTES", 4)

    body = types.UpdateContent(content="éé")

    assert body.content == "éé"
