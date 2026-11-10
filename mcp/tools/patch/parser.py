import re

from .types import FileUpdate, Hunk, PatchError

BEGIN_PATCH = "*** Begin Patch"
END_PATCH = "*** End Patch"
UPDATE_FILE = "*** Update File: "
MOVE_TO = "*** Move to: "
END_OF_FILE = "*** End of File"
UNSUPPORTED_SECTIONS = {
    "*** Add File: ": "create new pages with the `create` tool",
    "*** Delete File: ": "delete pages with the `delete` tool",
}
_UNIFIED_RANGE_RE = re.compile(r"^-\d+(?:,\d+)? \+\d+(?:,\d+)? @@\s*")


class PatchParser:
    """Parse the `*** Update File:` subset of Codex's apply_patch format."""

    def parse(self, text: str) -> list[FileUpdate]:
        lines = text.replace("\r\n", "\n").strip("\n").split("\n")
        if lines[0].strip() != BEGIN_PATCH:
            raise PatchError(f"a patch must start with '{BEGIN_PATCH}'")

        updates: list[FileUpdate] = []
        index = 1
        while index < len(lines):
            line = lines[index].strip()
            if line == END_PATCH:
                return self._finish(updates, lines, index)
            if line.startswith(UPDATE_FILE):
                path = line.removeprefix(UPDATE_FILE).strip()
                hunks, index = self._parse_hunks(path, lines, index + 1)
                updates.append(FileUpdate(path, hunks))
                continue
            self._reject_unsupported(line)
            if line:
                raise PatchError(f"unexpected patch line: {line}")
            index += 1
        raise PatchError(f"missing '{END_PATCH}'")

    def _finish(self, updates: list[FileUpdate], lines: list[str], end_index: int) -> list[FileUpdate]:
        if end_index + 1 != len(lines):
            raise PatchError(f"unexpected content after '{END_PATCH}'")
        if not updates:
            raise PatchError(f"the patch has no '{UPDATE_FILE.strip()}' sections")
        return updates

    def _reject_unsupported(self, line: str) -> None:
        for prefix, advice in UNSUPPORTED_SECTIONS.items():
            if line.startswith(prefix):
                raise PatchError(f"'{prefix.strip()}' isn't supported here; {advice}")

    def _parse_hunks(self, path: str, lines: list[str], index: int) -> tuple[list[Hunk], int]:
        if index < len(lines) and lines[index].strip().startswith(MOVE_TO):
            raise PatchError(f"{path}: '{MOVE_TO.strip()}' isn't supported; pages can't be renamed yet")

        hunks: list[Hunk] = []
        current = Hunk()
        while index < len(lines):
            line = lines[index]
            if line.rstrip() == END_OF_FILE:
                current.is_end_of_file = True
                self._close(hunks, current)
                current = Hunk()
                index += 1
                continue
            if line.startswith("*** "):
                break
            index += 1
            if line.startswith("@@"):
                self._close(hunks, current)
                current = Hunk(anchor=self._parse_anchor(line[2:]))
                continue
            if line.startswith("\\ No newline"):
                continue
            self._push_line(path, current, line)
        self._close(hunks, current)
        if not hunks:
            raise PatchError(f"{path}: no hunks")
        return hunks, index

    def _parse_anchor(self, text: str) -> str | None:
        """The text after `@@`, minus any unified-diff range header such as `-3,4 +3,5 @@`."""
        anchor = _UNIFIED_RANGE_RE.sub("", text.strip()).strip()
        if not anchor or anchor.endswith("@@"):
            return None
        return anchor

    def _push_line(self, path: str, hunk: Hunk, line: str) -> None:
        if not line:
            hunk.push_context("")
            return
        marker, content = line[0], line[1:]
        if marker == " ":
            hunk.push_context(content)
        elif marker == "-":
            hunk.old_lines.append(content)
        elif marker == "+":
            hunk.new_lines.append(content)
        else:
            raise PatchError(
                f"{path}: hunk lines must start with ' ' (context), '-' or '+'; got '{line[:80]}'"
            )

    def _close(self, hunks: list[Hunk], hunk: Hunk) -> None:
        if hunk.has_lines():
            hunks.append(hunk)
