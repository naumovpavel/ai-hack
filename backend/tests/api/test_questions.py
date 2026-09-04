from collections.abc import Callable
from unittest.mock import AsyncMock, Mock

from fastapi.testclient import TestClient

from interview_api.config import Settings
from interview_api.domain.models import QuestionDraft, QuestionGenerationInput, QuestionType
from interview_api.main import create_app

QUESTION_FORM = {
    "question_count": "3",
    "core_question_count": "2",
    "language": "ru",
}
QUESTION_FILES = {
    "cv": ("resume.txt", "Кандидат указывает опыт с Python".encode(), "text/plain"),
    "vacancy": ("vacancy.txt", b"Python backend developer", "text/plain"),
    "requirements": ("requirements.txt", b"FastAPI and asyncio", "text/plain"),
}


class TooFewQuestionsProvider:
    async def generate(self, input: QuestionGenerationInput) -> list[QuestionDraft]:
        return [
            QuestionDraft(
                type=QuestionType.CORE,
                text="Only one question",
                competency="Python",
                source_file_ids=["vacancy"],
            )
        ]


def test_generate_questions_from_uploaded_files_success(
    app_factory: Callable[..., TestClient],
) -> None:
    client = app_factory()
    response = client.post(
        "/api/v1/questions/generate", files=QUESTION_FILES, data=QUESTION_FORM
    )

    assert response.status_code == 200
    questions = response.json()["questions"]
    assert len(questions) == 3
    assert [question["type"] for question in questions] == [
        "core",
        "core",
        "personalized",
    ]
    assert all(question["id"] for question in questions)
    assert questions[0]["source_file_ids"] == ["vacancy"]
    assert questions[-1]["source_file_ids"] == ["cv"]


def test_generate_questions_rejects_wrong_provider_count(
    app_factory: Callable[..., TestClient],
) -> None:
    client = app_factory(question_provider=TooFewQuestionsProvider())
    response = client.post(
        "/api/v1/questions/generate", files=QUESTION_FILES, data=QUESTION_FORM
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_provider_response"


def test_generate_questions_rejects_invalid_count(
    app_factory: Callable[..., TestClient],
) -> None:
    client = app_factory()
    response = client.post(
        "/api/v1/questions/generate",
        files=QUESTION_FILES,
        data={**QUESTION_FORM, "question_count": "0", "core_question_count": "0"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_generate_questions_requires_a_document(
    app_factory: Callable[..., TestClient],
) -> None:
    client = app_factory()
    response = client.post("/api/v1/questions/generate", data=QUESTION_FORM)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "missing_context_documents"


def test_generate_questions_rejects_unsupported_document(
    app_factory: Callable[..., TestClient],
) -> None:
    client = app_factory()
    response = client.post(
        "/api/v1/questions/generate",
        files={"vacancy": ("vacancy.rtf", b"content", "application/rtf")},
        data={**QUESTION_FORM, "question_count": "1", "core_question_count": "1"},
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_document_type"


def test_generate_questions_rejects_oversized_document(
    app_factory: Callable[..., TestClient],
) -> None:
    client = app_factory()
    response = client.post(
        "/api/v1/questions/generate",
        files={"vacancy": ("vacancy.txt", b"x" * 1025, "text/plain")},
        data={**QUESTION_FORM, "question_count": "1", "core_question_count": "1"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "document_too_large"


def test_configured_app_wires_ollama_provider_without_network(monkeypatch) -> None:
    fake_client = Mock()
    fake_client.close = AsyncMock()

    class MockOllamaProvider:
        async def generate(self, input: QuestionGenerationInput) -> list[QuestionDraft]:
            return [
                QuestionDraft(
                    type=QuestionType.CORE,
                    text="Explain async Python.",
                    competency="Python",
                    source_file_ids=["vacancy"],
                )
            ]

    client_factory = Mock(return_value=fake_client)
    provider_factory = Mock(return_value=MockOllamaProvider())
    monkeypatch.setattr("interview_api.main.AsyncClient", client_factory)
    monkeypatch.setattr(
        "interview_api.main.OllamaQuestionGenerationProvider", provider_factory
    )
    settings = Settings(
        app_env="test",
        ollama_host="http://ollama.test:11434",
        ollama_question_model="configured-model",
        _env_file=None,
    )

    with TestClient(create_app(settings=settings)) as client:
        response = client.post(
            "/api/v1/questions/generate",
            files={"vacancy": ("vacancy.txt", b"Python backend role", "text/plain")},
            data={"question_count": "1", "core_question_count": "1", "language": "en"},
        )

    assert response.status_code == 200
    assert response.json()["questions"][0]["source_file_ids"] == ["vacancy"]
    assert provider_factory.call_args.kwargs["model"] == "configured-model"
    assert client_factory.call_args.kwargs["host"] == "http://ollama.test:11434"
    fake_client.close.assert_awaited_once()
