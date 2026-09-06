from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, Request, Response, UploadFile

from interview_api.api.routes.workflow import (
    ERROR_RESPONSES,
    WorkflowAPIRoute,
    _read_upload,
    _service,
    _session_token,
)
from interview_api.workflow.errors import WorkflowServiceUnavailableError
from interview_api.workflow.integrity_schemas import (
    IntegrityEventsRequest,
    IntegrityFinishRequest,
    IntegrityHeartbeatRequest,
    IntegrityPlaybackResponse,
    IntegrityReviewRequest,
    IntegrityReviewResponse,
    IntegritySessionResponse,
    IntegrityStartRequest,
    IntegritySummaryResponse,
)
from interview_api.workflow.integrity_service import IntegrityService

router = APIRouter(
    prefix="/api/v1", tags=["integrity"], route_class=WorkflowAPIRoute, responses=ERROR_RESPONSES
)


def _integrity(request: Request) -> IntegrityService:
    service = getattr(_service(request), "integrity", None)
    if service is None:
        raise WorkflowServiceUnavailableError("Integrity service is not configured.")
    return service


async def _actor(request: Request, role: str):
    return await _service(request).require_actor(_session_token(request), role=role)


@router.post("/interviews/{interview_id}/integrity/start", response_model=IntegritySessionResponse)
async def start(interview_id: str, payload: IntegrityStartRequest, request: Request):
    return await _integrity(request).start(
        actor=await _actor(request, "candidate"), interview_id=interview_id, payload=payload
    )


@router.post("/interviews/{interview_id}/integrity/events")
async def events(interview_id: str, payload: IntegrityEventsRequest, request: Request):
    return await _integrity(request).events(
        actor=await _actor(request, "candidate"), interview_id=interview_id, payload=payload
    )


@router.post(
    "/interviews/{interview_id}/integrity/heartbeat", response_model=IntegritySessionResponse
)
async def heartbeat(interview_id: str, payload: IntegrityHeartbeatRequest, request: Request):
    return await _integrity(request).heartbeat(
        actor=await _actor(request, "candidate"), interview_id=interview_id, payload=payload
    )


@router.post("/interviews/{interview_id}/integrity/chunks")
async def chunks(
    interview_id: str,
    request: Request,
    chunk: Annotated[UploadFile, File()],
    client_chunk_id: Annotated[str, Form(alias="clientChunkId", min_length=1, max_length=100)],
    stream_id: Annotated[str, Form(alias="streamId", min_length=1, max_length=100)],
    kind: Annotated[Literal["camera", "screen"], Form()],
    sequence: Annotated[int, Form(ge=0, le=100_000)],
    start_ms: Annotated[int, Form(alias="startMs", ge=0, le=86_400_000)],
    end_ms: Annotated[int, Form(alias="endMs", gt=0, le=86_400_000)],
    question_id: Annotated[str | None, Form(alias="questionId", max_length=36)] = None,
):
    actor = await _actor(request, "candidate")
    service = _integrity(request)
    return await service.upload_chunk(
        actor=actor,
        interview_id=interview_id,
        client_chunk_id=client_chunk_id,
        stream_id=stream_id,
        kind=kind,
        sequence=sequence,
        start_ms=start_ms,
        end_ms=end_ms,
        data=await _read_upload(chunk, service.max_chunk_bytes),
        content_type=chunk.content_type or "video/webm",
        question_id=question_id,
    )


@router.post("/interviews/{interview_id}/integrity/finish", response_model=IntegritySessionResponse)
async def finish(interview_id: str, payload: IntegrityFinishRequest, request: Request):
    return await _integrity(request).finish(
        actor=await _actor(request, "candidate"), interview_id=interview_id, payload=payload
    )


@router.get("/candidates/{candidate_id}/integrity", response_model=IntegritySummaryResponse)
async def summary(candidate_id: str, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return await _integrity(request).summary(
        actor=await _actor(request, "hr"), candidate_id=candidate_id
    )


@router.get(
    "/candidates/{candidate_id}/integrity/findings/{finding_id}/playback",
    response_model=IntegrityPlaybackResponse,
)
async def playback(candidate_id: str, finding_id: str, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return await _integrity(request).playback(
        actor=await _actor(request, "hr"), candidate_id=candidate_id, finding_id=finding_id
    )


@router.put(
    "/candidates/{candidate_id}/integrity/findings/{finding_id}/review",
    response_model=IntegrityReviewResponse,
)
async def review(
    candidate_id: str, finding_id: str, payload: IntegrityReviewRequest, request: Request
):
    return await _integrity(request).review(
        actor=await _actor(request, "hr"),
        candidate_id=candidate_id,
        finding_id=finding_id,
        payload=payload,
    )


@router.post("/candidates/{candidate_id}/integrity/retry")
async def retry(candidate_id: str, request: Request):
    return await _integrity(request).retry(
        actor=await _actor(request, "hr"), candidate_id=candidate_id
    )
