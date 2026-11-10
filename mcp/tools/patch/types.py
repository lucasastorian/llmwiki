from dataclasses import dataclass, field


class PatchError(ValueError):
    """A patch that cannot be parsed or applied; nothing has been written."""


@dataclass
class Hunk:
    anchor: str | None = None
    old_lines: list[str] = field(default_factory=list)
    new_lines: list[str] = field(default_factory=list)
    # (old index, new index) of each context line, so a fuzzy match keeps the file's own text.
    context_pairs: list[tuple[int, int]] = field(default_factory=list)
    is_end_of_file: bool = False

    def has_lines(self) -> bool:
        return bool(self.old_lines or self.new_lines)

    def push_context(self, line: str) -> None:
        self.context_pairs.append((len(self.old_lines), len(self.new_lines)))
        self.old_lines.append(line)
        self.new_lines.append(line)


@dataclass(frozen=True)
class FileUpdate:
    path: str
    hunks: list[Hunk]


@dataclass(frozen=True)
class Seek:
    start: int
    pass_index: int


@dataclass(frozen=True)
class Replacement:
    start: int
    old_len: int
    new_lines: list[str]


@dataclass(frozen=True)
class PatchedText:
    content: str
    notes: list[str]
