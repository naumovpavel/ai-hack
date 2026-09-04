from typing import Annotated

from fastapi import APIRouter, Depends

from interview_api.api.dependencies import get_answer_evaluation_service
from interview_api.domain.models import (
    ErrorResponse,
    EvaluateAnswerRequest,
    EvaluateAnswerResponse,
)
from interview_api.services.answer_evaluation import AnswerEvaluationService

router = APIRouter(prefix="/api/v1/interviews", tags=["interviews"])


@router.post(
    "/evaluate-answer",
    response_model=EvaluateAnswerResponse,
    responses={
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)
async def evaluate_answer(
    request: EvaluateAnswerRequest,
    service: Annotated[AnswerEvaluationService, Depends(get_answer_evaluation_service)],
) -> EvaluateAnswerResponse:
    return await service.evaluate(request.question, request.answer)
