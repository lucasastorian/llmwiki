from difflib import unified_diff

DIFF_CONTEXT_LINES = 2


def render_diff(path: str, before: str, after: str) -> str:
    """Unified diff of one page, labelled with its path."""
    lines = unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=path,
        tofile=path,
        n=DIFF_CONTEXT_LINES,
        lineterm="",
    )
    return "\n".join(lines)
