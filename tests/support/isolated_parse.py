"""Run the production parse in a resource-limited child so a hang, OOM or stack crash fails one test, not the runner."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from tests.support.types import IsolatedRun, ParseOutcome

REPO_ROOT = Path(__file__).resolve().parents[2]
WALL_CLOCK_SECONDS = 30
CPU_SECONDS = 20
ADDRESS_SPACE_BYTES = 2 * 1024**3
PARSES_PER_RUN = 2


def run_isolated(html: str, url: str) -> IsolatedRun:
    """Parse `html` twice in a fresh interpreter under CPU, memory and wall-clock limits."""
    request = json.dumps({"html": html, "url": url})
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "tests.support.isolated_parse"],
            input=request,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=REPO_ROOT,
            env=_child_env(),
            timeout=WALL_CLOCK_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return IsolatedRun(outcomes=[], failure=f"timed out after {WALL_CLOCK_SECONDS}s wall clock")
    if completed.returncode != 0:
        return IsolatedRun(
            outcomes=[],
            failure=f"child exited with {completed.returncode}; stderr tail: {completed.stderr[-2000:]}",
        )
    payload = json.loads(completed.stdout)
    return IsolatedRun(outcomes=[ParseOutcome(**outcome) for outcome in payload])


def _child_env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": os.pathsep.join([str(REPO_ROOT / "api"), str(REPO_ROOT)])}


def _apply_limits() -> None:
    """Best effort: some platforms (macOS RLIMIT_AS, Windows) refuse or lack these limits."""
    try:
        import resource
    except ImportError:
        return
    for limit, value in (
        (resource.RLIMIT_CPU, CPU_SECONDS),
        (resource.RLIMIT_AS, ADDRESS_SPACE_BYTES),
        (resource.RLIMIT_CORE, 0),
    ):
        try:
            resource.setrlimit(limit, (value, value))
        except (ValueError, OSError):
            continue


def _parse_once(html: str, url: str) -> ParseOutcome:
    from html_parser import ParseLimitExceededError, Parser

    try:
        result = Parser(html, url=url, content_only=True).parse()
    except Exception as exc:
        return ParseOutcome(
            error_type=type(exc).__name__,
            error_message=str(exc)[:500],
            is_limit_error=isinstance(exc, ParseLimitExceededError),
        )
    return ParseOutcome(markdown=result.content, plaintext=result.plaintext)


def _main() -> None:
    _apply_limits()
    request = json.loads(sys.stdin.read())
    outcomes = [_parse_once(request["html"], request["url"]) for _ in range(PARSES_PER_RUN)]
    sys.stdout.write(json.dumps([asdict(outcome) for outcome in outcomes]))


if __name__ == "__main__":
    _main()
