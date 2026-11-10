"""Codex's line matcher: exact, then trailing-space, then surrounding-space, then punctuation-normalised."""

from collections.abc import Callable

from .types import Seek

_NORMALISE = str.maketrans(
    {
        **{chr(c): "-" for c in [*range(0x2010, 0x2016), 0x2212]},
        **{chr(c): "'" for c in range(0x2018, 0x201C)},
        **{chr(c): '"' for c in range(0x201C, 0x2020)},
        **{chr(c): " " for c in [0x00A0, *range(0x2002, 0x200B), 0x202F, 0x205F, 0x3000]},
    }
)


def _normalise(line: str) -> str:
    return line.strip().translate(_NORMALISE)


_PASSES: list[Callable[[str, str], bool]] = [
    lambda actual, expected: actual == expected,
    lambda actual, expected: actual.rstrip() == expected.rstrip(),
    lambda actual, expected: actual.strip() == expected.strip(),
    lambda actual, expected: _normalise(actual) == _normalise(expected),
]


def seek_sequence(lines: list[str], pattern: list[str], start: int, is_end_of_file: bool) -> Seek | None:
    """First index at or after `start` where `pattern` matches, trying each pass in turn."""
    window = _search_window(lines, pattern, start, is_end_of_file)
    for pass_index, equals in enumerate(_PASSES):
        for index in window:
            if _matches_at(lines, pattern, index, equals):
                return Seek(index, pass_index)
    return None


def other_matches(lines: list[str], pattern: list[str], cursor: int, is_end_of_file: bool, seek: Seek) -> list[int]:
    """Other indices in the same window where `pattern` matches under the pass that found `seek`."""
    equals = _PASSES[seek.pass_index]
    return [
        index
        for index in _search_window(lines, pattern, cursor, is_end_of_file)
        if index != seek.start and _matches_at(lines, pattern, index, equals)
    ]


def closest_line(lines: list[str], target: str) -> int | None:
    """The line most like `target`: most shared words, then longest shared prefix, earliest on ties."""
    target = _normalise(target)
    target_words = set(target.split())
    best_index, best_score = None, (0, 0)
    for index, line in enumerate(lines):
        line = _normalise(line)
        score = (len(set(line.split()) & target_words), _shared_prefix_length(line, target))
        if score > best_score:
            best_index, best_score = index, score
    return best_index


def _search_window(lines: list[str], pattern: list[str], start: int, is_end_of_file: bool) -> range:
    if len(pattern) > len(lines):
        return range(0)
    last = len(lines) - len(pattern)
    first = max(start, last) if is_end_of_file else start
    return range(first, last + 1)


def _matches_at(lines: list[str], pattern: list[str], index: int, equals: Callable[[str, str], bool]) -> bool:
    return all(equals(lines[index + offset], expected) for offset, expected in enumerate(pattern))


def _shared_prefix_length(a: str, b: str) -> int:
    length = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        length += 1
    return length
