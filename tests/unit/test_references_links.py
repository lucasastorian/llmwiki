"""Wiki-link resolution in references.extract_references (the links_to path)."""

import importlib.util
from pathlib import Path


def _references_module():
    spec = importlib.util.spec_from_file_location(
        "api_references_links_test",
        Path(__file__).resolve().parents[2] / "api" / "services" / "references.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _doc(doc_id: str, path: str, filename: str) -> dict:
    return {"id": doc_id, "path": path, "filename": filename, "title": filename}


def _wiki_path_map(docs: list[dict]) -> dict[str, dict]:
    """Mirror build_lookup_maps' wiki_path_to_doc: key is path+filename minus /wiki/, lowered."""
    out: dict[str, dict] = {}
    for doc in docs:
        if doc["path"].startswith("/wiki/"):
            relative = (doc["path"] + doc["filename"]).replace("/wiki/", "", 1)
            out[relative.lower()] = doc
    return out


_ABS = _doc("abs-1", "/wiki/", "abs.md")
_SIBLING = _doc("sib-1", "/wiki/notes/", "sibling.md")
_PARENT = _doc("par-1", "/wiki/", "parent.md")
_BARE = _doc("bare-1", "/wiki/notes/", "name.md")


def test_links_resolve_against_wiki_path_map():
    extract_references = _references_module().extract_references
    docs = [_ABS, _SIBLING, _PARENT, _BARE]
    wiki_map = _wiki_path_map(docs)

    source_id = "writer-1"  # current page lives in /wiki/notes/
    wiki_dir = "notes/"

    cases = [
        ("absolute /wiki/ link", "[a](/wiki/abs.md)", "abs-1"),
        ("./sibling relative", "[s](./sibling.md)", "sib-1"),
        ("../parent stack collapse", "[p](../parent.md)", "par-1"),
        ("bare name in current dir", "[n](name.md)", "bare-1"),
    ]

    for label, content, expected_target in cases:
        edges = extract_references(content, source_id, wiki_dir, {}, {}, wiki_map)
        assert edges == [
            {"target_id": expected_target, "type": "links_to", "page": None}
        ], label


def test_duplicate_link_targets_dedup_to_one_edge():
    extract_references = _references_module().extract_references
    wiki_map = _wiki_path_map([_ABS])

    content = "See [first](/wiki/abs.md) and again [second](/wiki/abs.md)."
    edges = extract_references(content, "writer-1", "notes/", {}, {}, wiki_map)

    assert edges == [{"target_id": "abs-1", "type": "links_to", "page": None}]


def test_self_reference_is_excluded():
    extract_references = _references_module().extract_references
    wiki_map = _wiki_path_map([_ABS])

    edges = extract_references("[me](/wiki/abs.md)", "abs-1", "", {}, {}, wiki_map)

    assert edges == []


def test_non_wiki_and_image_links_are_skipped():
    extract_references = _references_module().extract_references
    # These targets would resolve as wiki links, so the skip must come from the href shape.
    img = _doc("img-1", "/wiki/", "diagram.png")
    wiki_map = _wiki_path_map([_ABS, img])

    skipped = [
        "[http](https://example.com/abs.md)",
        "[hash](#abs.md)",
        "[mail](mailto:abs.md)",
        "[data](data:text/plain,abs.md)",
        "[png](/wiki/diagram.png)",
        "[jpg](/wiki/abs.jpg)",
        "[svg](/wiki/abs.svg)",
    ]

    for content in skipped:
        edges = extract_references(content, "writer-1", "notes/", {}, {}, wiki_map)
        assert edges == [], content
