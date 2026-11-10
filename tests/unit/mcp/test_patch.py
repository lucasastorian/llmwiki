"""The patch parser and hunk placement port Codex's apply_patch semantics to wiki pages."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "mcp"))


def _apply(content: str, body: str) -> tuple[str, list[str]]:
    from tools.patch import PatchParser, apply_hunks

    [update] = PatchParser().parse(f"*** Begin Patch\n*** Update File: /wiki/page.md\n{body}\n*** End Patch")
    patched = apply_hunks(update.path, content, update.hunks)
    return patched.content, patched.notes


def test_parses_several_pages_in_one_patch():
    from tools.patch import PatchParser

    updates = PatchParser().parse(
        "*** Begin Patch\n"
        "*** Update File: /wiki/a.md\n@@\n-old a\n+new a\n"
        "*** Update File: wiki/b.md\n@@ ## Heading\n context\n+added\n"
        "*** End Patch\n"
    )

    assert [u.path for u in updates] == ["/wiki/a.md", "wiki/b.md"]
    assert updates[1].hunks[0].anchor == "## Heading"
    assert updates[1].hunks[0].old_lines == ["context"]
    assert updates[1].hunks[0].new_lines == ["context", "added"]


@pytest.mark.parametrize(
    ("section", "advice"),
    [
        ("*** Add File: /wiki/new.md\n+text", "`create`"),
        ("*** Delete File: /wiki/old.md", "`delete`"),
        ("*** Update File: /wiki/a.md\n*** Move to: /wiki/b.md\n@@\n-x\n+y", "renamed"),
    ],
)
def test_rejects_sections_other_tools_own(section: str, advice: str):
    from tools.patch import PatchError, PatchParser

    with pytest.raises(PatchError, match=advice):
        PatchParser().parse(f"*** Begin Patch\n{section}\n*** End Patch")


def test_rejects_a_patch_without_begin_or_end_markers():
    from tools.patch import PatchError, PatchParser

    with pytest.raises(PatchError, match="Begin Patch"):
        PatchParser().parse("*** Update File: /wiki/a.md\n-x\n+y")
    with pytest.raises(PatchError, match="End Patch"):
        PatchParser().parse("*** Begin Patch\n*** Update File: /wiki/a.md\n-x\n+y")


def test_unified_diff_range_headers_are_not_treated_as_anchors():
    from tools.patch import PatchParser

    [update] = PatchParser().parse(
        "*** Begin Patch\n*** Update File: /wiki/a.md\n@@ -3,2 +3,2 @@ ## Results\n-x\n+y\n"
        "@@ -9 +9 @@\n-p\n+q\n*** End Patch"
    )

    assert [h.anchor for h in update.hunks] == ["## Results", None]


def test_replaces_lines_and_keeps_the_final_newline():
    content, notes = _apply("# Title\n\nOld claim.\nKeep me.\n", "@@\n-Old claim.\n+New claim.")

    assert content == "# Title\n\nNew claim.\nKeep me.\n"
    assert notes == []


def test_matches_curly_quotes_and_dashes_and_keeps_the_pages_own_context_text():
    page = "Revenue rose ‘sharply’ — per the 10‑K.\nOld line.\n"

    content, _ = _apply(page, "@@\n Revenue rose 'sharply' - per the 10-K.\n-Old line.\n+New line.")

    assert content == "Revenue rose ‘sharply’ — per the 10‑K.\nNew line.\n"


def test_anchor_picks_which_repeated_line_to_change():
    page = "## Before\n- [ ] Task\n## After\n- [ ] Task\n"

    content, notes = _apply(page, "@@ ## After\n-- [ ] Task\n+- [x] Task")

    assert content == "## Before\n- [ ] Task\n## After\n- [x] Task\n"
    assert notes == []


def test_ambiguous_hunk_changes_the_first_match_and_names_the_others():
    content, notes = _apply("- [ ] Task\nmiddle\n- [ ] Task\n", "@@\n-- [ ] Task\n+- [x] Task")

    assert content == "- [x] Task\nmiddle\n- [ ] Task\n"
    assert "also occur at line(s) 3" in notes[0]


def test_plus_only_hunk_inserts_after_its_anchor():
    content, _ = _apply("## Notes\n- one\n## Next\n", "@@ ## Notes\n+- zero")

    assert content == "## Notes\n- zero\n- one\n## Next\n"


def test_plus_only_hunk_without_anchor_appends_at_the_end():
    content, _ = _apply("first\nlast", "@@\n+appended")

    assert content == "first\nlast\nappended"


def test_end_of_file_marker_pins_the_hunk_to_the_last_lines():
    content, _ = _apply("x\nmid\nx\n", "@@\n-x\n+y\n*** End of File")

    assert content == "x\nmid\ny\n"


def test_hunks_apply_in_order_each_after_the_previous():
    content, _ = _apply("a\nb\na\nb\n", "@@\n-a\n+A\n@@\n-a\n+A2")

    assert content == "A\nb\nA2\nb\n"


def test_missing_lines_report_the_closest_line():
    from tools.patch import PatchError

    with pytest.raises(PatchError) as error:
        _apply("# Title\nThe model scales linearly with depth.\n", "@@\n-The model scales quadratically with depth.\n+x")

    assert "hunk 1" in str(error.value)
    assert "closest: line 2: The model scales linearly with depth." in str(error.value)


def test_context_line_missing_its_leading_space_is_rejected():
    from tools.patch import PatchError, PatchParser

    with pytest.raises(PatchError, match="must start with"):
        PatchParser().parse("*** Begin Patch\n*** Update File: /wiki/a.md\n@@\nno marker\n*** End Patch")


def test_render_diff_shows_removed_and_added_lines():
    from tools.patch import render_diff

    diff = render_diff("/wiki/a.md", "one\ntwo\n", "one\n2\n")

    assert "--- /wiki/a.md" in diff
    assert "-two" in diff
    assert "+2" in diff
