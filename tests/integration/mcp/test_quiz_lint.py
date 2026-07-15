"""Quiz-block validation: schema checks, write-time rejection, lint reporting."""


def _make_kb(kb_id: str) -> dict:
    return {"id": kb_id, "name": "test-workspace", "slug": "test-workspace"}


def _quiz_fence(body: str) -> str:
    return f"```quiz\n{body}\n```"


VALID_QUIZ = _quiz_fence(
    "title: Checkpoint\n"
    "questions:\n"
    "  - prompt: What is $P(A)$?\n"
    '    options: ["$1/4$", "$3/8$"]\n'
    "    answer: 1\n"
    "    hints:\n"
    "      - think\n"
    "    explanation: because"
)

FRONTMATTER = (
    "---\n"
    "title: Lesson\n"
    "description: A lesson with a checkpoint.\n"
    "date: 2026-07-10\n"
    "tags: [alpha, beta]\n"
    "---\n\n"
)


class TestQuizValidator:

    def test_valid_block_passes(self):
        from tools.quiz_lint import lint_quiz_blocks

        assert lint_quiz_blocks(f"Intro.\n\n{VALID_QUIZ}\n\nOutro.") == []

    def test_page_without_fences_passes(self):
        from tools.quiz_lint import lint_quiz_blocks

        assert lint_quiz_blocks("# Plain page\n\n```python\nx = 1\n```") == []

    def test_invalid_yaml_reported(self):
        from tools.quiz_lint import lint_quiz_blocks

        errors = lint_quiz_blocks(_quiz_fence(": : :"))
        assert len(errors) == 1
        assert "invalid YAML" in errors[0]

    def test_non_mapping_body_reported(self):
        from tools.quiz_lint import lint_quiz_blocks

        errors = lint_quiz_blocks(_quiz_fence("- just\n- a list"))
        assert errors == ["quiz block 1: body must be a YAML mapping with a `questions` list"]

    def test_missing_questions_reported(self):
        from tools.quiz_lint import lint_quiz_blocks

        errors = lint_quiz_blocks(_quiz_fence("title: Empty"))
        assert any("`questions` must be a non-empty list" in e for e in errors)

    def test_unknown_keys_reported(self):
        from tools.quiz_lint import lint_quiz_blocks

        errors = lint_quiz_blocks(
            _quiz_fence(
                "titl: Typo\n"
                "questions:\n"
                "  - prompt: Q?\n"
                "    options: [a, b]\n"
                "    answer: 0\n"
                "    explnation: typo"
            )
        )
        assert any("unknown key(s) ['titl']" in e for e in errors)
        assert any("unknown key(s) ['explnation']" in e for e in errors)

    def test_answer_out_of_range_reported(self):
        from tools.quiz_lint import lint_quiz_blocks

        errors = lint_quiz_blocks(
            _quiz_fence("questions:\n  - prompt: Q?\n    options: [a, b]\n    answer: 2")
        )
        assert errors == ["quiz block 1, question 1: `answer` 2 is out of range for 2 options (0-based)"]

    def test_boolean_answer_rejected(self):
        from tools.quiz_lint import lint_quiz_blocks

        errors = lint_quiz_blocks(
            _quiz_fence("questions:\n  - prompt: Q?\n    options: [a, b]\n    answer: true")
        )
        assert any("0-based index" in e for e in errors)

    def test_option_count_bounds(self):
        from tools.quiz_lint import lint_quiz_blocks

        too_few = _quiz_fence("questions:\n  - prompt: Q?\n    options: [only]\n    answer: 0")
        assert any("2-6 choices" in e for e in lint_quiz_blocks(too_few))

        seven = ", ".join(f"o{i}" for i in range(7))
        too_many = _quiz_fence(f"questions:\n  - prompt: Q?\n    options: [{seven}]\n    answer: 0")
        assert any("2-6 choices" in e for e in lint_quiz_blocks(too_many))

    def test_hints_cap(self):
        from tools.quiz_lint import MAX_HINTS, lint_quiz_blocks

        hints = "\n".join(f"      - hint {i}" for i in range(MAX_HINTS + 1))
        block = _quiz_fence(
            f"questions:\n  - prompt: Q?\n    options: [a, b]\n    answer: 0\n    hints:\n{hints}"
        )
        assert any(f"at most {MAX_HINTS} hints" in e for e in lint_quiz_blocks(block))

    def test_valid_text_question_passes(self):
        from tools.quiz_lint import lint_quiz_blocks

        block = _quiz_fence(
            "questions:\n"
            "  - type: text\n"
            "    prompt: Explain the base-rate fallacy.\n"
            "    rubric: Correct if the answer invokes the prior.\n"
            "    hints:\n"
            "      - think priors\n"
            "    explanation: Bayes."
        )
        assert lint_quiz_blocks(block) == []

    def test_text_question_requires_rubric(self):
        from tools.quiz_lint import lint_quiz_blocks

        block = _quiz_fence("questions:\n  - type: text\n    prompt: Explain X.")
        errors = lint_quiz_blocks(block)
        assert errors == ["quiz block 1, question 1: `rubric` must be non-empty text describing how to grade the answer"]

    def test_text_question_rejects_choice_keys(self):
        from tools.quiz_lint import lint_quiz_blocks

        block = _quiz_fence(
            "questions:\n"
            "  - type: text\n"
            "    prompt: Explain X.\n"
            "    rubric: Correct if X.\n"
            "    options: [a, b]\n"
            "    answer: 0"
        )
        errors = lint_quiz_blocks(block)
        assert any("unknown key(s) ['answer', 'options'] for a text question" in e for e in errors)

    def test_choice_question_rejects_rubric(self):
        from tools.quiz_lint import lint_quiz_blocks

        block = _quiz_fence(
            "questions:\n"
            "  - prompt: Q?\n"
            "    options: [a, b]\n"
            "    answer: 0\n"
            "    rubric: not allowed here"
        )
        errors = lint_quiz_blocks(block)
        assert any("unknown key(s) ['rubric'] for a choice question" in e for e in errors)

    def test_unknown_type_rejected(self):
        from tools.quiz_lint import lint_quiz_blocks

        block = _quiz_fence("questions:\n  - type: essay\n    prompt: Q?")
        errors = lint_quiz_blocks(block)
        assert errors == ['quiz block 1, question 1: `type` must be "choice" or "text"']

    def test_second_block_labeled(self):
        from tools.quiz_lint import lint_quiz_blocks

        bad = _quiz_fence("questions:\n  - prompt: Q?\n    options: [a, b]\n    answer: 9")
        errors = lint_quiz_blocks(f"{VALID_QUIZ}\n\ntext\n\n{bad}")
        assert len(errors) == 1
        assert errors[0].startswith("quiz block 2")

    def test_commonmark_fence_variants_are_validated(self):
        from tools.quiz_lint import lint_quiz_blocks

        invalid = "questions: []"
        variants = [
            f"   ```quiz\n{invalid}\n   ```",
            f"````quiz\n{invalid}\n````",
            f"~~~quiz\n{invalid}\n~~~",
            f"```quiz\r\n{invalid}\r\n```",
        ]
        for block in variants:
            assert any("non-empty list" in error for error in lint_quiz_blocks(block))

    def test_quiz_text_inside_an_outer_fence_is_ignored(self):
        from tools.quiz_lint import lint_quiz_blocks

        content = "````markdown\n```quiz\nquestions: []\n```\n````"
        assert lint_quiz_blocks(content) == []


class TestQuizWriteRejection:

    async def test_create_rejects_invalid_quiz(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler

        writer = WriteHandler(instance, _make_kb(kb_id))
        bad_page = FRONTMATTER + _quiz_fence("questions:\n  - prompt: Q?\n    options: [a, b]\n    answer: 7")
        result = await writer.create("/wiki/", "Bad Lesson", bad_page, ["a", "b"], "", False)

        assert "Error: invalid ```quiz block(s)" in result
        assert "out of range" in result
        assert await instance.get_document(kb_id, "bad-lesson.md", "/wiki/") is None

    async def test_create_accepts_valid_quiz(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler

        writer = WriteHandler(instance, _make_kb(kb_id))
        result = await writer.create("/wiki/", "Good Lesson", FRONTMATTER + VALID_QUIZ, ["a", "b"], "", False)

        assert "Created **Good Lesson**" in result

    async def test_edit_rejects_introducing_invalid_quiz(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler

        writer = WriteHandler(instance, _make_kb(kb_id))
        await writer.create("/wiki/", "Lesson", FRONTMATTER + VALID_QUIZ, ["a", "b"], "", False)

        result = await writer.edit("/wiki/lesson.md", "answer: 1", "answer: 9")
        assert "Error: invalid ```quiz block(s)" in result

        doc = await instance.get_document(kb_id, "lesson.md", "/wiki/")
        assert "answer: 1" in doc["content"]

    async def test_append_rejects_invalid_quiz(self, fs):
        instance, kb_id = fs
        from tools.write import WriteHandler

        writer = WriteHandler(instance, _make_kb(kb_id))
        await writer.create("/wiki/", "Lesson", FRONTMATTER + "Intro.", ["a", "b"], "", False)

        result = await writer.append("/wiki/lesson.md", _quiz_fence("questions: []"))
        assert "Error: invalid ```quiz block(s)" in result

        doc = await instance.get_document(kb_id, "lesson.md", "/wiki/")
        assert "```quiz" not in doc["content"]


class TestQuizLintTool:

    async def test_lint_reports_invalid_quiz(self, fs):
        instance, kb_id = fs
        from tools.lint import LintHandler

        # Seed directly through VaultFS — write tools now reject this content.
        bad_page = FRONTMATTER + _quiz_fence("questions:\n  - prompt: Q?\n    options: [a]\n    answer: 0")
        await instance.create_document(kb_id, "bad-quiz.md", "Bad Quiz", "/wiki/", "md", bad_page, ["a", "b"])

        linter = LintHandler(instance, _make_kb(kb_id))
        result = await linter.run(path="/wiki/bad-quiz.md", include_graph=False)
        assert "invalid-quiz" in result
        assert "2-6 choices" in result
