from typing import NamedTuple


class BatchPages(NamedTuple):
    text: str
    chars: int
    pages_included: int
    is_truncated: bool
