import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from interview_api.domain.errors import ProviderResponseError
from interview_api.domain.models import LoadedContext, QuestionGenerationInput
from interview_api.providers.openrouter_interview import StructuredResult
from interview_api.providers.openrouter_questions import OpenRouterQuestionGenerationProvider

PROMPT_PATH = Path("app/prompts/initial_questions_v1.txt")


def make_input() -> QuestionGenerationInput:
    vacancy = LoadedContext(
        type="vacancy",
        file_id="vacancy-1",
        text="Python backend engineer",
    )
    cv = LoadedContext(type="cv", file_id="cv-1", text="Claims five years of Python")
    return QuestionGenerationInput(
        core_contexts=[vacancy],
        personalized_contexts=[vacancy, cv],
        question_count=2,
        core_question_count=1,
        language="en",
    )


class FakeStructuredClient:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = iter(responses)
        self.calls: list[dict[str, Any]] = []

    def complete_json(self, **kwargs: Any) -> StructuredResult:
        self.calls.append(kwargs)
        return StructuredResult(next(self._responses), kwargs["model"], "test")


def question(text: str, question_type: str, source: str) -> dict[str, Any]:
    return {
        "type": question_type,
        "text": text,
        "competency": "Python",
        "source_file_ids": [source],
    }


def test_openrouter_provider_uses_structured_output_and_configured_model() -> None:
    client = FakeStructuredClient(
        [
            {
                "questions": [
                    question(
                        "How does asyncio scheduling work?",
                        "core",
                        "vacancy-1",
                    )
                ]
            },
            {
                "questions": [
                    question(
                        "Your CV mentions Python. What did you build with it?",
                        "personalized",
                        "cv-1",
                    )
                ]
            },
        ]
    )
    provider = OpenRouterQuestionGenerationProvider(
        client,
        model="openai/gpt-5.6-luna",
        prompt_path=PROMPT_PATH,
    )

    questions = asyncio.run(provider.generate(make_input()))

    assert len(questions) == 2
    call = client.calls[0]
    assert call["model"] == "openai/gpt-5.6-luna"
    assert call["purpose"] == "question_generation"
    assert call["schema"]["type"] == "object"
    request_payload = json.loads(call["messages"][1]["content"])
    assert request_payload["core_question_count"] == 1
    assert request_payload["personalized_question_count"] == 0
    assert request_payload["core_contexts"][0]["file_id"] == "vacancy-1"


def test_openrouter_provider_rejects_unstructured_response() -> None:
    client = FakeStructuredClient([{"unexpected": []}] * 7)
    provider = OpenRouterQuestionGenerationProvider(
        client,
        model="openai/gpt-5.6-luna",
        prompt_path=PROMPT_PATH,
    )

    with pytest.raises(ProviderResponseError):
        asyncio.run(provider.generate(make_input()))

    assert len(client.calls) == 7


def test_openrouter_provider_retries_semantically_invalid_response() -> None:
    client = FakeStructuredClient(
        [
            {"questions": [question("Explain asyncio.", "core", "vacancy-1")]},
            {"questions": []},
            {
                "questions": [
                    question(
                        "Your CV mentions Python. What did you build?",
                        "personalized",
                        "cv-1",
                    )
                ]
            },
        ]
    )
    provider = OpenRouterQuestionGenerationProvider(
        client,
        model="openai/gpt-5.6-luna",
        prompt_path=PROMPT_PATH,
    )

    questions = asyncio.run(provider.generate(make_input()))

    assert len(questions) == 2
    retry_payload = json.loads(client.calls[2]["messages"][1]["content"])
    assert retry_payload["question_count"] == 1
    assert retry_payload["core_question_count"] == 0
    assert retry_payload["existing_question_texts"] == ["explain asyncio."]


def test_openrouter_provider_fills_an_undercounted_batch() -> None:
    client = FakeStructuredClient(
        [
            {
                "questions": [
                    question("Question 1", "personalized", "cv-1"),
                    question("Question 2", "personalized", "cv-1"),
                ]
            },
            {
                "questions": [
                    question("Question 3", "personalized", "cv-1"),
                    question("Question 4", "personalized", "cv-1"),
                ]
            },
            {"questions": [question("Question 5", "personalized", "cv-1")]},
        ]
    )
    source_input = make_input()
    input = source_input.model_copy(update={"question_count": 5, "core_question_count": 0})
    provider = OpenRouterQuestionGenerationProvider(
        client,
        model="openai/gpt-5.6-luna",
        prompt_path=PROMPT_PATH,
    )

    questions = asyncio.run(provider.generate(input))

    assert len(questions) == 5
    requested_counts = [
        json.loads(call["messages"][1]["content"])["question_count"]
        for call in client.calls
    ]
    assert requested_counts == [3, 3, 1]


def test_prompt_marks_cv_claims_as_unverified() -> None:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    assert "CV statements are unverified candidate claims" in prompt
    assert "never invent candidate experience" in prompt
