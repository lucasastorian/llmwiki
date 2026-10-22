"""Size guards on every stage where crafted extractor output could amplify into huge objects or responses."""

import json
from pathlib import Path
from typing import Any


def bounded_utf8_size(value: Any, max_bytes: int, label: str) -> int:
    """Return UTF-8 size without allocating an unbounded encoded copy."""
    if not isinstance(value, str):
        raise RuntimeError(f"opendataloader {label} must be text")

    total = 0
    try:
        for offset in range(0, len(value), 4096):
            total += len(value[offset:offset + 4096].encode("utf-8"))
            if total > max_bytes:
                raise RuntimeError(f"opendataloader {label} exceeds safe size limit")
    except UnicodeEncodeError as exc:
        raise RuntimeError(f"opendataloader {label} contains invalid Unicode") from exc
    return total


def ensure_bounded_json(value: Any, max_bytes: int, label: str) -> None:
    """Measure compact JSON incrementally instead of materializing it."""
    total = 0
    encoder = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"))
    for piece in encoder.iterencode(value):
        total += bounded_utf8_size(piece, max_bytes - total, label)


def read_bounded_json(output_dir: str, engine: str, max_bytes: int) -> dict:
    """Load the extractor's JSON output without materializing an oversized file."""
    json_path = next(Path(output_dir).glob("*.json"), None)
    if json_path is None:
        raise RuntimeError(f"{engine} produced no output")

    if json_path.stat().st_size > max_bytes:
        raise RuntimeError(f"{engine} JSON exceeds safe size limit")
    with json_path.open("rb") as f:
        raw_json = f.read(max_bytes + 1)
    if len(raw_json) > max_bytes:
        raise RuntimeError(f"{engine} JSON exceeds safe size limit")
    data = json.loads(raw_json)
    if not isinstance(data, dict):
        raise RuntimeError(f"{engine} JSON root must be an object")
    return data
