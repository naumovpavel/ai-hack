from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, Request, Response, UploadFile

from interview_api.api.routes.workflow import (
    ERROR_RESPONSES,
    WorkflowAPIRoute,
    _read_upload,
    _service,
    _session_token,
)
from interview_api.workflow.schemas import (
    AnalysisResponse,
    CompleteInterviewResponse,
    DecisionRequest,
    DecisionResponse,
    InitialDecisionRequest,
    MediaListResponse,
    PracticeAnswerResponse,
    PracticeSetResponse,
    QuestionReviewRequest,
    StartInterviewRequest,
)

router = APIRouter(
    prefix="/api/v1/practice", tags=["practice"], route_class=WorkflowAPIRoute,
    responses=ERROR_RESPONSES,
)


@router.get("/{practice_id}", response_model=PracticeSetResponse)
async def get_practice(practice_id: str, request: Request) -> PracticeSetResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="candidate")
    return await service.get_practice(actor=actor, practice_id=practice_id)


@router.post("/{practice_id}/start", response_model=PracticeSetResponse)
async def start_practice(
    practice_id: str, payload: StartInterviewRequest, request: Request
) -> PracticeSetResponse:
    del payload  # Consent is enforced by the validated request model.
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="candidate")
    return await service.start_practice(actor=actor, practice_id=practice_id)


@router.post("/{practice_id}/answers", response_model=PracticeAnswerResponse)
async def submit_practice_answer(
    practice_id: str,
    request: Request,
    question_id: Annotated[str, Form(alias="questionId", min_length=1)],
    audio: Annotated[UploadFile, File()],
    video: Annotated[UploadFile, File()],
    duration_seconds: Annotated[int | None, Form(alias="durationSeconds", ge=0, le=300)] = None,
    language: Annotated[str, Form(min_length=2, max_length=35)] = "ru",
) -> PracticeAnswerResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="candidate")
    audio_data = await _read_upload(audio, service.max_audio_bytes)
    video_data = await _read_upload(video, service.max_video_bytes)
    return await service.submit_practice_answer(
        actor=actor, practice_id=practice_id, question_id=question_id,
        audio_data=audio_data, audio_filename=audio.filename or "answer.webm",
        audio_content_type=audio.content_type or "audio/webm",
        video_data=video_data, video_filename=video.filename or "answer-video.webm",
        video_content_type=video.content_type or "video/webm",
        duration_seconds=duration_seconds, language=language,
    )


@router.post("/{practice_id}/complete", response_model=CompleteInterviewResponse)
async def complete_practice(practice_id: str, request: Request) -> CompleteInterviewResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="candidate")
    return await service.complete_practice(actor=actor, practice_id=practice_id)


@router.get("/{practice_id}/analysis", response_model=AnalysisResponse)
async def get_practice_analysis(practice_id: str, request: Request) -> AnalysisResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="candidate")
    return await service.get_practice_analysis(actor=actor, practice_id=practice_id)


@router.put("/{practice_id}/questions/{question_id}/rating", response_model=AnalysisResponse)
async def rate_practice_question(
    practice_id: str, question_id: str, payload: QuestionReviewRequest, request: Request
) -> AnalysisResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="candidate")
    return await service.rate_practice_question(
        actor=actor, practice_id=practice_id, question_id=question_id, request=payload
    )


@router.post("/{practice_id}/review", response_model=AnalysisResponse)
async def record_practice_review(
    practice_id: str, payload: InitialDecisionRequest, request: Request
) -> AnalysisResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="candidate")
    return await service.record_practice_review(
        actor=actor, practice_id=practice_id, request=payload
    )


@router.post("/{practice_id}/decision", response_model=DecisionResponse)
async def decide_practice(
    practice_id: str, payload: DecisionRequest, request: Request
) -> DecisionResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="candidate")
    return await service.decide_practice(actor=actor, practice_id=practice_id, request=payload)


@router.get("/{practice_id}/media", response_model=MediaListResponse)
async def list_practice_media(practice_id: str, request: Request) -> MediaListResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="candidate")
    return await service.list_practice_media(actor=actor, practice_id=practice_id)


@router.get("/{practice_id}/questions/{question_id}/speech")
async def practice_question_speech(
    practice_id: str, question_id: str, request: Request
) -> Response:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="candidate")
    audio, content_type = await service.practice_question_speech(
        actor=actor, practice_id=practice_id, question_id=question_id
    )
    return Response(content=audio, media_type=content_type, headers={"Cache-Control": "no-store"})
