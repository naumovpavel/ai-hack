from collections.abc import Callable

from fastapi.testclient import TestClient

from interview_api.config import Settings
from interview_api.domain.models import (
    AnnotationLabel,
    AnswerAnnotation,
    EvaluateAnswerResponse,
    EvaluationMeta,
)
from interview_api.main import create_app


class IncorrectAnswerProvider:
    async def evaluate(self, question: str, answer: str) -> EvaluateAnswerResponse:
        return EvaluateAnswerResponse(
            spans=[
                AnswerAnnotation(
                    start=0,
                    end=len(answer),
                    text=answer,
                    label=AnnotationLabel.INCORRECT,
                    confidence=0.98,
                    rationale="The technical statement is false.",
                )
            ],
            missing_aspects=[],
            meta=EvaluationMeta(
                models=["openai/gpt-5.6-luna"],
                providers=["test"],
                prompt_version="test",
                claims_evaluated=1,
            ),
        )


def test_evaluate_answer_endpoint(app_factory: Callable[..., TestClient]) -> None:
    client = app_factory(answer_evaluation_provider=IncorrectAnswerProvider())

    response = client.post(
        "/api/v1/interviews/evaluate-answer",
        json={"question": "How does MVCC work?", "answer": "MVCC locks every row."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["spans"][0]["label"] == AnnotationLabel.INCORRECT
    assert payload["spans"][0]["text"] == "MVCC locks every row."
    assert payload["meta"]["models"] == ["openai/gpt-5.6-luna"]


def test_evaluate_answer_requires_configuration() -> None:
    app = create_app(
        settings=Settings(app_env="test", _env_file=None),
        answer_evaluation_service=None,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/interviews/evaluate-answer",
            json={"question": "How does MVCC work?", "answer": "With row versions."},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_not_configured"
