from dataclasses import dataclass
from typing import NamedTuple


class BatchPages(NamedTuple):
    text: str
    chars: int
    pages_included: int
    is_truncated: bool


@dataclass(frozen=True)
class PlannedPage:
    path: str
    dir_path: str
    filename: str
    doc: dict
    before: str
    after: str
