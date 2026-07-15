"""QuizGrader: Workers AI response parsing and failure handling at the httpx boundary."""

import json

import httpx
import pytest
from config import settings
from fastapi import HTTPException
from services.quiz_grader import (
    GRADER_MODEL,
    MAX_COMPLETION_TOKENS,
    MAX_FEEDBACK_CHARS,
    QuizGrader,
)
from services.types import QuizGradeResponse


def _cf_body(result_response: object) -> dict:
    return {"success": True, "result": {"response": result_response}}


async def _grade(body: dict, status_code: int = 200) -> QuizGradeResponse:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await QuizGrader(client).grade("Q?", "Correct if X.", "X because Y.")


class TestQuizGrader:

    async def test_parses_object_response(self):
        result = await _grade(_cf_body({"verdict": "correct", "feedback": "Nailed the base rate."}))
        assert result.verdict == "correct"
        assert result.feedback == "Nailed the base rate."

    async def test_parses_json_string_response(self):
        result = await _grade(_cf_body('{"verdict": "partial", "feedback": "Missing the prior."}'))
        assert result.verdict == "partial"
        assert result.feedback == "Missing the prior."

    async def test_feedback_is_trimmed_and_capped(self):
        result = await _grade(_cf_body({"verdict": "incorrect", "feedback": "  x" * MAX_FEEDBACK_CHARS}))
        assert len(result.feedback) == MAX_FEEDBACK_CHARS

    async def test_unknown_verdict_is_502(self):
        with pytest.raises(HTTPException) as exc:
            await _grade(_cf_body({"verdict": "meh", "feedback": "?"}))
        assert exc.value.status_code == 502

    async def test_empty_feedback_is_502(self):
        with pytest.raises(HTTPException) as exc:
            await _grade(_cf_body({"verdict": "correct", "feedback": "   "}))
        assert exc.value.status_code == 502

    async def test_malformed_json_string_is_502(self):
        with pytest.raises(HTTPException) as exc:
            await _grade(_cf_body("not json at all"))
        assert exc.value.status_code == 502

    async def test_http_error_is_502(self):
        with pytest.raises(HTTPException) as exc:
            await _grade({"success": False, "errors": [{"message": "boom"}]}, status_code=500)
        assert exc.value.status_code == 502

    async def test_upstream_rate_limit_is_preserved(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, headers={"Retry-After": "17"}, json={"errors": []})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(HTTPException) as exc:
                await QuizGrader(client).grade("Q?", "Correct if X.", "X.")

        assert exc.value.status_code == 429
        assert exc.value.headers == {"Retry-After": "17"}

    async def test_parses_vllm_choices_inside_success_envelope(self):
        # Real /ai/run shape for @cf/google/gemma-4-*: success envelope whose
        # result is an OpenAI chat.completion, not {"response": ...}.
        body = {
            "success": True,
            "errors": [],
            "messages": [],
            "result": {
                "object": "chat.completion",
                "choices": [
                    {"message": {"role": "assistant", "content": '{"verdict": "correct", "feedback": "Good."}'}}
                ],
            },
        }
        result = await _grade(body)
        assert result.verdict == "correct"
        assert result.feedback == "Good."

    async def test_unsuccessful_cf_envelope_is_502(self):
        with pytest.raises(HTTPException) as exc:
            await _grade({"success": False, "errors": [{"message": "model overloaded"}]})
        assert exc.value.status_code == 502

    async def test_request_targets_grader_model_with_bounded_non_thinking_schema(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = request.read().decode()
            return httpx.Response(200, json=_cf_body({"verdict": "correct", "feedback": "ok"}))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await QuizGrader(client).grade(
                "Q?",
                "Correct if X.",
                "X.",
                user_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            )

        assert GRADER_MODEL in seen["url"]
        body = json.loads(seen["body"])
        assert body["response_format"]["type"] == "json_schema"
        assert body["max_completion_tokens"] == MAX_COMPLETION_TOKENS == 500
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        assert len(body["user"]) == 24
        assert "Correct if X." in body["messages"][1]["content"]
        assert "<|think|>" not in body["messages"][0]["content"]

    async def test_gateway_uses_openai_shape_and_opaque_metadata(self, monkeypatch):
        seen: dict = {}
        monkeypatch.setattr(settings, "CLOUDFLARE_AI_GATEWAY_ID", "llm-wiki")

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["headers"] = request.headers
            seen["body"] = json.loads(request.read().decode())
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": '{"verdict":"correct","feedback":"Good."}'}}
                    ]
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await QuizGrader(client).grade(
                "Q?",
                "Correct if X.",
                "X.",
                user_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            )

        assert result.verdict == "correct"
        assert seen["url"].endswith("/ai/v1/chat/completions")
        assert seen["headers"]["cf-aig-gateway-id"] == "llm-wiki"
        metadata = json.loads(seen["headers"]["cf-aig-metadata"])
        assert len(metadata["quiz_user"]) == 24
        assert seen["body"]["model"] == GRADER_MODEL
