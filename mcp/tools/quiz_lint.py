"""Quiz-block validation — shared by the write tools and the lint tool."""

import yaml

MAX_QUESTIONS = 20
MIN_OPTIONS = 2
MAX_OPTIONS = 6
MAX_HINTS = 5

QUIZ_SCHEMA_HINT = (
    "Schema: optional `title`, required `questions:`. Multiple-choice question (default): "
    "`prompt`, `options` (2-6 strings), `answer` (0-based index of the correct option). "
    "Free-form question: `type: text`, `prompt`, `rubric` (grading criteria for the AI grader). "
    "Every question may add `hints` (list) and `explanation`."
)

_BLOCK_KEYS = {"title", "questions"}
_QUESTION_TYPES = ("choice", "text")
_COMMON_KEYS = {"type", "prompt", "hints", "explanation"}
_CHOICE_KEYS = _COMMON_KEYS | {"options", "answer"}
_TEXT_KEYS = _COMMON_KEYS | {"rubric"}


def _opening_fence(line: str) -> tuple[str, int, str] | None:
    """Return (marker, length, info) for a CommonMark fenced-code opener."""
    stripped = line.rstrip("\r\n")
    indent = len(stripped) - len(stripped.lstrip(" "))
    if indent > 3:
        return None
    candidate = stripped[indent:]
    if not candidate or candidate[0] not in "`~":
        return None
    marker = candidate[0]
    length = len(candidate) - len(candidate.lstrip(marker))
    if length < 3:
        return None
    info = candidate[length:].strip()
    # Backticks are forbidden in the info string for backtick fences.
    if marker == "`" and "`" in info:
        return None
    return marker, length, info


def _is_closing_fence(line: str, marker: str, opening_length: int) -> bool:
    stripped = line.rstrip("\r\n")
    indent = len(stripped) - len(stripped.lstrip(" "))
    if indent > 3:
        return False
    candidate = stripped[indent:]
    length = len(candidate) - len(candidate.lstrip(marker))
    return length >= opening_length and not candidate[length:].strip()


def _quiz_sources(content: str):
    """Yield quiz bodies while respecting all surrounding fenced code blocks."""
    lines = content.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        opening = _opening_fence(lines[index])
        if opening is None:
            index += 1
            continue

        marker, opening_length, info = opening
        body_start = index + 1
        index = body_start
        while index < len(lines) and not _is_closing_fence(lines[index], marker, opening_length):
            index += 1

        # CommonMark treats EOF as the end of an unclosed fenced block.
        body = "".join(lines[body_start:index])
        language = info.split(None, 1)[0] if info else ""
        if language == "quiz":
            yield body
        if index < len(lines):
            index += 1


def lint_quiz_blocks(content: str) -> list[str]:
    """Return one error message per problem across all quiz fenced blocks."""
    errors: list[str] = []
    for index, source in enumerate(_quiz_sources(content), start=1):
        errors.extend(_lint_block(index, source))
    return errors


def _lint_block(index: int, source: str) -> list[str]:
    label = f"quiz block {index}"
    try:
        data = yaml.safe_load(source)
    except yaml.YAMLError as e:
        return [f"{label}: invalid YAML — {e}"]
    if not isinstance(data, dict):
        return [f"{label}: body must be a YAML mapping with a `questions` list"]

    errors: list[str] = []
    unknown = set(data) - _BLOCK_KEYS
    if unknown:
        errors.append(f"{label}: unknown key(s) {sorted(unknown)} — allowed: title, questions")
    title = data.get("title")
    if title is not None and not isinstance(title, str):
        errors.append(f"{label}: `title` must be a string")

    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        errors.append(f"{label}: `questions` must be a non-empty list")
        return errors
    if len(questions) > MAX_QUESTIONS:
        errors.append(f"{label}: at most {MAX_QUESTIONS} questions per block")
    for q_index, question in enumerate(questions, start=1):
        errors.extend(_lint_question(f"{label}, question {q_index}", question))
    return errors


def _lint_question(label: str, question: object) -> list[str]:
    if not isinstance(question, dict):
        return [f"{label}: must be a mapping with a `prompt`"]

    question_type = question.get("type", "choice")
    if question_type not in _QUESTION_TYPES:
        return [f'{label}: `type` must be "choice" or "text"']

    errors = _lint_shared_fields(label, question, question_type)
    if question_type == "text":
        errors.extend(_lint_text_fields(label, question))
    else:
        errors.extend(_lint_choice_fields(label, question))
    return errors


def _lint_shared_fields(label: str, question: dict, question_type: str) -> list[str]:
    errors: list[str] = []
    allowed = _TEXT_KEYS if question_type == "text" else _CHOICE_KEYS
    unknown = set(question) - allowed
    if unknown:
        errors.append(
            f"{label}: unknown key(s) {sorted(unknown)} for a {question_type} question — allowed: {sorted(allowed)}"
        )

    prompt = question.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        errors.append(f"{label}: `prompt` must be non-empty text")

    hints = question.get("hints")
    if hints is not None:
        if not isinstance(hints, list) or not all(isinstance(h, str) and h.strip() for h in hints):
            errors.append(f"{label}: `hints` must be a list of non-empty strings")
        elif len(hints) > MAX_HINTS:
            errors.append(f"{label}: at most {MAX_HINTS} hints per question")

    explanation = question.get("explanation")
    if explanation is not None and (not isinstance(explanation, str) or not explanation.strip()):
        errors.append(f"{label}: `explanation` must be non-empty text")

    return errors


def _lint_choice_fields(label: str, question: dict) -> list[str]:
    errors: list[str] = []
    options = question.get("options")
    valid_options = isinstance(options, list) and all(isinstance(o, str) and o.strip() for o in options)
    if not valid_options:
        errors.append(f"{label}: `options` must be a list of non-empty strings")
    elif not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
        errors.append(f"{label}: `options` must list {MIN_OPTIONS}-{MAX_OPTIONS} choices, got {len(options)}")

    answer = question.get("answer")
    if not isinstance(answer, int) or isinstance(answer, bool):
        errors.append(f"{label}: `answer` must be the 0-based index of the correct option")
    elif valid_options and not 0 <= answer < len(options):
        errors.append(f"{label}: `answer` {answer} is out of range for {len(options)} options (0-based)")

    return errors


def _lint_text_fields(label: str, question: dict) -> list[str]:
    rubric = question.get("rubric")
    if not isinstance(rubric, str) or not rubric.strip():
        return [f"{label}: `rubric` must be non-empty text describing how to grade the answer"]
    return []
