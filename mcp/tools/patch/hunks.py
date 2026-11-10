"""Codex's hunk placement: each hunk searches after the previous one, then all splice in at once."""

from .matcher import closest_line, other_matches, seek_sequence
from .types import Hunk, PatchedText, PatchError, Replacement, Seek

MAX_SHOWN_LINE_CHARS = 200
MAX_LISTED_MATCHES = 5


def apply_hunks(path: str, content: str, hunks: list[Hunk]) -> PatchedText:
    """Apply `hunks` to `content` in order, each searching after where the previous one matched."""
    lines = _split_lines(content)
    cursor = 0
    replacements: list[Replacement] = []
    notes: list[str] = []
    for number, hunk in enumerate(hunks, start=1):
        try:
            replacement, cursor, other_starts = _place_hunk(lines, hunk, cursor)
        except PatchError as e:
            raise PatchError(f"{path}: hunk {number}: {e}") from None
        if other_starts:
            notes.append(_ambiguity_note(path, number, replacement.start, other_starts))
        replacements.append(replacement)
    return PatchedText(content=_splice(content, lines, replacements), notes=notes)


def _place_hunk(lines: list[str], hunk: Hunk, cursor: int) -> tuple[Replacement, int, list[int]]:
    """Return the hunk's replacement, the cursor for the next hunk, and other places it also matched."""
    if hunk.anchor is not None:
        cursor = _seek_anchor(lines, hunk.anchor, cursor)
    if not hunk.old_lines:
        return _insertion(lines, hunk, cursor), cursor, []

    found = _seek_old_block(lines, hunk, cursor)
    if found is None:
        raise PatchError(_expected_lines_error(lines, hunk.old_lines, cursor))
    old, new, seek = found
    replacement = Replacement(
        start=seek.start,
        old_len=len(old),
        new_lines=_replacement_lines(lines, hunk, old, new, seek),
    )
    others = other_matches(lines, old, cursor, hunk.is_end_of_file, seek)
    return replacement, seek.start + len(old), others


def _insertion(lines: list[str], hunk: Hunk, cursor: int) -> Replacement:
    """Insert right after the @@ anchor line, or at the end of the page without one."""
    start = cursor if hunk.anchor is not None and not hunk.is_end_of_file else len(lines)
    return Replacement(start=start, old_len=0, new_lines=list(hunk.new_lines))


def _replacement_lines(lines: list[str], hunk: Hunk, old: list[str], new: list[str], seek: Seek) -> list[str]:
    """The hunk's new lines, with each context line taken from the file as matched."""
    new_lines = list(new)
    for old_index, new_index in hunk.context_pairs:
        if old_index < len(old) and new_index < len(new_lines):
            new_lines[new_index] = lines[seek.start + old_index]
    return new_lines


def _seek_anchor(lines: list[str], anchor: str, cursor: int) -> int:
    seek = seek_sequence(lines, [anchor], cursor, False)
    if seek is None:
        raise PatchError(f"could not find @@ line '{_clip(anchor)}'{_closest_hint(lines, anchor)}")
    return seek.start + 1


def _seek_old_block(lines: list[str], hunk: Hunk, cursor: int) -> tuple[list[str], list[str], Seek] | None:
    """Seek the hunk's old lines, retrying without a trailing blank line as Codex does."""
    old, new = hunk.old_lines, hunk.new_lines
    seek = seek_sequence(lines, old, cursor, hunk.is_end_of_file)
    if seek is not None:
        return old, new, seek
    if old[-1] != "":
        return None
    old = old[:-1]
    new = new[:-1] if new and new[-1] == "" else new
    if not old:
        return None
    seek = seek_sequence(lines, old, cursor, hunk.is_end_of_file)
    return (old, new, seek) if seek is not None else None


def _expected_lines_error(lines: list[str], old: list[str], cursor: int) -> str:
    expected = "\n".join(_clip(line) for line in old)
    culprit = next((line for line in old if seek_sequence(lines, [line], cursor, False) is None), old[0])
    return (
        f"could not find these lines (read the page again and copy them exactly):\n{expected}"
        f"{_closest_hint(lines, culprit)}"
    )


def _closest_hint(lines: list[str], target: str) -> str:
    index = closest_line(lines, target)
    if index is None:
        return ""
    return f"\nclosest: line {index + 1}: {_clip(lines[index])}"


def _ambiguity_note(path: str, number: int, start: int, other_starts: list[int]) -> str:
    listed = [str(other + 1) for other in other_starts[:MAX_LISTED_MATCHES]]
    if len(other_starts) > MAX_LISTED_MATCHES:
        listed.append("…")
    return (
        f"{path}: hunk {number} matched at line {start + 1}; its lines also occur at line(s) "
        f"{', '.join(listed)} (add an @@ anchor to pick another)"
    )


def _split_lines(content: str) -> list[str]:
    if not content:
        return []
    return content.removesuffix("\n").split("\n")


def _splice(content: str, lines: list[str], replacements: list[Replacement]) -> str:
    """Splice replacements bottom-up and keep the page's final-newline state."""
    should_terminate = not content or content.endswith("\n") or _shortens_final_lines(lines, replacements)
    lines = list(lines)
    # reversed(), not reverse=True: insertions sharing a start must keep their patch order.
    for replacement in reversed(sorted(replacements, key=lambda r: r.start)):
        lines[replacement.start:replacement.start + replacement.old_len] = replacement.new_lines
    if not lines:
        return ""
    text = "\n".join(lines)
    return text + "\n" if should_terminate else text


def _shortens_final_lines(lines: list[str], replacements: list[Replacement]) -> bool:
    """Whether a replacement drops lines at the end, so an earlier newline-terminated line becomes last."""
    return any(
        r.start + r.old_len == len(lines) and len(r.new_lines) < r.old_len
        for r in replacements
    )


def _clip(line: str) -> str:
    return line if len(line) <= MAX_SHOWN_LINE_CHARS else line[:MAX_SHOWN_LINE_CHARS] + "…"
