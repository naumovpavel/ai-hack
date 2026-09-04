import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from interview_api.domain.errors import ProviderResponseError
from interview_api.domain.models import LoadedContext, QuestionGenerationInput
from interview_api.providers.ollama_questions import OllamaQuestionGenerationProvider

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


def test_ollama_provider_uses_structured_output_and_configured_model() -> None:
    chat = AsyncMock(
        return_value=SimpleNamespace(
            message=SimpleNamespace(
                content=json.dumps(
                    {
                        "questions": [
                            {
                                "type": "core",
                                "text": "How does asyncio scheduling work?",
                                "competency": "Python concurrency",
                                "source_file_ids": ["vacancy-1"],
                            },
                            {
                                "type": "personalized",
                                "text": "Your CV mentions Python. What did you build with it?",
                                "competency": "Python experience",
                                "source_file_ids": ["cv-1"],
                            },
                        ]
                    }
                )
            )
        )
    )
    client = SimpleNamespace(chat=chat)
    provider = OllamaQuestionGenerationProvider(
        client,
        model="configured-model",
        prompt_path=PROMPT_PATH,
        context_length=8192,
    )

    questions = asyncio.run(provider.generate(make_input()))

    assert len(questions) == 2
    call = chat.await_args_list[0].kwargs
    assert call["model"] == "configured-model"
    assert call["format"]["type"] == "object"
    assert "maxLength" not in json.dumps(call["format"])
    assert call["options"] == {"temperature": 0, "num_ctx": 8192}
    assert call["think"] is False
    request_payload = json.loads(call["messages"][1]["content"])
    assert request_payload["core_question_count"] == 1
    assert request_payload["personalized_question_count"] == 0
    assert request_payload["core_contexts"][0]["file_id"] == "vacancy-1"
    assert "required_output_json_schema" not in request_payload


def test_ollama_provider_rejects_unstructured_response() -> None:
    chat = AsyncMock(return_value=SimpleNamespace(message=SimpleNamespace(content="not-json")))
    client = SimpleNamespace(chat=chat)
    provider = OllamaQuestionGenerationProvider(
        client,
        model="configured-model",
        prompt_path=PROMPT_PATH,
        context_length=8192,
    )

    with pytest.raises(ProviderResponseError):
        asyncio.run(provider.generate(make_input()))

    assert chat.await_count == 7


def test_ollama_provider_retries_semantically_invalid_response() -> None:
    invalid = {
        "questions": [
            {
                "type": "core",
                "text": "Only one question",
                "competency": "Python",
                "source_file_ids": ["vacancy-1"],
            }
        ]
    }
    valid = {
        "questions": [
            {
                "type": "core",
                "text": "Explain asyncio.",
                "competency": "Python",
                "source_file_ids": ["vacancy-1"],
            },
            {
                "type": "personalized",
                "text": "Your CV mentions Python. What did you build?",
                "competency": "Experience",
                "source_file_ids": ["cv-1"],
            },
        ]
    }
    chat = AsyncMock(
        side_effect=[
            SimpleNamespace(message=SimpleNamespace(content=json.dumps(invalid))),
            SimpleNamespace(message=SimpleNamespace(content=json.dumps(valid))),
        ]
    )
    provider = OllamaQuestionGenerationProvider(
        SimpleNamespace(chat=chat),
        model="configured-model",
        prompt_path=PROMPT_PATH,
        context_length=8192,
    )

    questions = asyncio.run(provider.generate(make_input()))

    assert len(questions) == 2
    retry_payload = json.loads(chat.await_args_list[1].kwargs["messages"][1]["content"])
    assert retry_payload["question_count"] == 1
    assert retry_payload["core_question_count"] == 0
    assert retry_payload["existing_question_texts"] == ["only one question"]


def test_ollama_provider_fills_an_undercounted_batch() -> None:
    def response(*texts: str) -> SimpleNamespace:
        return SimpleNamespace(
            message=SimpleNamespace(
                content=json.dumps(
                    {
                        "questions": [
                            {
                                "type": "personalized",
                                "text": text,
                                "competency": "Experience",
                                "source_file_ids": ["cv-1"],
                            }
                            for text in texts
                        ]
                    }
                )
            )
        )

    chat = AsyncMock(
        side_effect=[
            response("Question 1", "Question 2"),
            response("Question 3", "Question 4"),
            response("Question 5"),
        ]
    )
    source_input = make_input()
    input = source_input.model_copy(
        update={"question_count": 5, "core_question_count": 0}
    )
    provider = OllamaQuestionGenerationProvider(
        SimpleNamespace(chat=chat),
        model="configured-model",
        prompt_path=PROMPT_PATH,
        context_length=8192,
    )

    questions = asyncio.run(provider.generate(input))

    assert len(questions) == 5
    requested_counts = [
        json.loads(call.kwargs["messages"][1]["content"])["question_count"]
        for call in chat.await_args_list
    ]
    assert requested_counts == [3, 3, 1]


def test_prompt_marks_cv_claims_as_unverified() -> None:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    assert "CV statements are unverified candidate claims" in prompt
    assert "never invent candidate experience" in prompt
