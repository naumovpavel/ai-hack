import pytest

from interview_api.domain.errors import ProviderResponseError
from interview_api.domain.models import (
    AnnotationLabel,
    AnswerAnnotation,
    EvaluateAnswerResponse,
    EvaluationMeta,
)
from interview_api.services.answer_evaluation import AnswerEvaluationService


class InvalidSpanProvider:
    async def evaluate(self, question: str, answer: str) -> EvaluateAnswerResponse:
        return EvaluateAnswerResponse(
            spans=[
                AnswerAnnotation(
                    start=0,
                    end=5,
                    text="wrong",
                    label=AnnotationLabel.INCORRECT,
                    confidence=0.99,
                    rationale="Invalid quote.",
                )
            ],
            missing_aspects=[],
            meta=EvaluationMeta(
                models=["fake"],
                providers=["fake"],
                prompt_version="test",
                claims_evaluated=1,
            ),
        )


@pytest.mark.asyncio
async def test_service_rejects_non_verbatim_span() -> None:
    service = AnswerEvaluationService(InvalidSpanProvider())

    with pytest.raises(ProviderResponseError):
        await service.evaluate("Question", "right")
