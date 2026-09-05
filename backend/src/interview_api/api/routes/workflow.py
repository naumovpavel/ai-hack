from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from interview_api.workflow.errors import (
    WorkflowError,
    WorkflowNotFoundError,
    WorkflowServiceUnavailableError,
)
from interview_api.workflow.hiring_schemas import (
    CandidateCreateRequest,
    CandidateDraftResponse,
    CompanyCandidateSummary,
    ContextDocumentResponse,
    InterviewCreateRequest,
    InterviewDraftResponse,
    InterviewPlanDetailResponse,
    InterviewPlanResponse,
    InterviewTemplateFields,
    InterviewTemplateResponse,
    PrepareInterviewRequest,
    VacancyCreateRequest,
    VacancyDetailResponse,
    VacancyDraftResponse,
    VacancyFields,
    VacancyResponse,
    VacancyTemplateResponse,
)
from interview_api.workflow.schemas import (
    AnalysisResponse,
    AnswerResponse,
    ApprovalResponse,
    CandidateDetailResponse,
    CandidateOutcomeResponse,
    CompleteInterviewResponse,
    DecisionRequest,
    DecisionResponse,
    DevSessionRequest,
    InterviewBriefingResponse,
    InterviewStateResponse,
    MediaListResponse,
    PositionDetailResponse,
    PositionResponse,
    QuestionResponse,
    ResolveInviteRequest,
    ReviewHeartbeatRequest,
    ReviewHeartbeatResponse,
    SessionResponse,
    StartInterviewRequest,
    UpdateQuestionRequest,
    UserResponse,
    WorkflowErrorResponse,
)
from interview_api.workflow.service import WorkflowService

SESSION_COOKIE = "signal_session"
ERROR_RESPONSES = {
    400: {"model": WorkflowErrorResponse},
    401: {"model": WorkflowErrorResponse},
    403: {"model": WorkflowErrorResponse},
    404: {"model": WorkflowErrorResponse},
    409: {"model": WorkflowErrorResponse},
    422: {"model": WorkflowErrorResponse},
    502: {"model": WorkflowErrorResponse},
    503: {"model": WorkflowErrorResponse},
}


class WorkflowAPIRoute(APIRoute):
    """Keep workflow errors in the backend's canonical error envelope."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except WorkflowError as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={
                        "error": {
                            "code": exc.code,
                            "message": exc.message,
                            "details": exc.details,
                        }
                    },
                )

        return handler


router = APIRouter(prefix="/api/v1", tags=["workflow"], route_class=WorkflowAPIRoute)


def _service(request: Request) -> WorkflowService:
    service = getattr(request.app.state, "workflow_service", None)
    if service is None:
        raise WorkflowServiceUnavailableError()
    return service


def _require_demo_mode(request: Request) -> None:
    settings = getattr(request.app.state, "settings", None)
    if (getattr(settings, "app_env", "production") == "production"
        or not getattr(settings, "demo_auth_enabled", False)
        or getattr(settings, "telegram_bot_token", None)):
        raise WorkflowNotFoundError("Demo session endpoints are disabled.")


def _session_token(request: Request) -> str | None:
    service = _service(request)
    return request.cookies.get(service.cookie_name)


async def _read_upload(upload: UploadFile, maximum: int) -> bytes:
    try:
        return await upload.read(maximum + 1)
    finally:
        await upload.close()


def _set_session_cookie(response: Response, token: str, service: WorkflowService) -> None:
    response.set_cookie(
        service.cookie_name,
        token,
        max_age=int(service.session_ttl.total_seconds()),
        httponly=True,
        secure=service.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.get("/dev/users", response_model=list[UserResponse], responses=ERROR_RESPONSES)
async def list_demo_users(request: Request) -> list[UserResponse]:
    _require_demo_mode(request)
    return await _service(request).list_demo_users()


@router.post("/dev/session", response_model=SessionResponse, responses=ERROR_RESPONSES)
async def switch_demo_session(
    payload: DevSessionRequest,
    request: Request,
    response: Response,
) -> SessionResponse:
    _require_demo_mode(request)
    service = _service(request)
    token, session = await service.create_demo_session(payload.user_id)
    _set_session_cookie(response, token, service)
    return session


@router.delete("/dev/session", status_code=204)
async def clear_demo_session(request: Request, response: Response) -> None:
    _require_demo_mode(request)
    response.delete_cookie(_service(request).cookie_name, path="/")


@router.get("/session", response_model=UserResponse, responses=ERROR_RESPONSES)
async def get_current_session(request: Request, response: Response) -> UserResponse:
    response.headers["Cache-Control"] = "no-store"
    token = _session_token(request)
    if token is None:
        # The UI treats 404 as a first visit and offers Telegram sign-in.
        # Invalid or expired tokens still produce 401.
        raise WorkflowNotFoundError("No active session was found.")
    return await _service(request).current_session(token)


@router.get("/positions", response_model=list[PositionResponse], responses=ERROR_RESPONSES)
async def list_positions(request: Request) -> list[PositionResponse]:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.list_positions(actor=actor)


@router.post("/positions", response_model=PositionDetailResponse, responses=ERROR_RESPONSES)
async def create_position(
    request: Request,
    title: Annotated[str, Form(min_length=3, max_length=240)],
    requirements: Annotated[str, Form(min_length=1, max_length=30_000)],
    question_count: Annotated[int, Form(alias="questionCount", ge=1, le=20)],
    duration_minutes: Annotated[int, Form(alias="durationMinutes", ge=5, le=120)],
    vacancy: Annotated[UploadFile, File()],
    max_follow_up_questions: Annotated[int, Form(alias="maxFollowUpQuestions", ge=0, le=10)] = 2,
    level: Annotated[str, Form(max_length=120)] = "",
    location: Annotated[str, Form(max_length=240)] = "",
    seed_questions: Annotated[str | None, Form(alias="seedQuestions", max_length=30_000)] = None,
) -> PositionDetailResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    vacancy_data = await _read_upload(vacancy, service.max_document_bytes)
    return await service.create_position(
        actor=actor,
        title=title,
        level=level,
        location=location,
        requirements=service.parse_lines(requirements),
        question_count=question_count,
        duration_minutes=duration_minutes,
        max_follow_up_questions=max_follow_up_questions,
        seed_questions=service.parse_lines(seed_questions),
        vacancy_data=vacancy_data,
        vacancy_filename=vacancy.filename or "vacancy.txt",
        vacancy_content_type=vacancy.content_type or "application/octet-stream",
    )


@router.get(
    "/positions/{position_id}",
    response_model=PositionDetailResponse,
    responses=ERROR_RESPONSES,
)
async def get_position(position_id: str, request: Request) -> PositionDetailResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.get_position_detail(actor=actor, position_id=position_id)


@router.post(
    "/positions/{position_id}/candidates",
    response_model=CandidateDetailResponse,
    responses=ERROR_RESPONSES,
)
async def add_candidate(
    position_id: str,
    request: Request,
    name: Annotated[str, Form(min_length=2, max_length=240)],
    resume: Annotated[UploadFile, File()],
    email: Annotated[str | None, Form(max_length=320)] = None,
    role: Annotated[str, Form(max_length=240)] = "",
) -> CandidateDetailResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    resume_data = await _read_upload(resume, service.max_document_bytes)
    return await service.add_candidate(
        actor=actor,
        position_id=position_id,
        name=name,
        email=email,
        role=role,
        resume_data=resume_data,
        resume_filename=resume.filename or "resume.txt",
        resume_content_type=resume.content_type or "application/octet-stream",
    )


@router.get(
    "/candidates/{candidate_id}",
    response_model=CandidateDetailResponse,
    responses=ERROR_RESPONSES,
)
async def get_candidate(candidate_id: str, request: Request) -> CandidateDetailResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.get_candidate_detail(actor=actor, candidate_id=candidate_id)


@router.get(
    "/candidates/{candidate_id}/questions",
    response_model=list[QuestionResponse],
    responses=ERROR_RESPONSES,
)
async def list_candidate_questions(candidate_id: str, request: Request) -> list[QuestionResponse]:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.list_questions(actor=actor, candidate_id=candidate_id)


@router.patch(
    "/candidates/{candidate_id}/questions/{question_id}",
    response_model=QuestionResponse,
    responses=ERROR_RESPONSES,
)
async def update_candidate_question(
    candidate_id: str,
    question_id: str,
    payload: UpdateQuestionRequest,
    request: Request,
) -> QuestionResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.update_question(
        actor=actor,
        candidate_id=candidate_id,
        question_id=question_id,
        text=payload.text,
        topic=payload.topic,
        competency=payload.competency,
        order_index=payload.order_index,
    )


@router.post(
    "/candidates/{candidate_id}/questions/approve",
    response_model=ApprovalResponse,
    responses=ERROR_RESPONSES,
)
async def approve_candidate_questions(candidate_id: str, request: Request) -> ApprovalResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.approve_questions(actor=actor, candidate_id=candidate_id)


@router.post(
    "/invites/resolve",
    response_model=InterviewBriefingResponse,
    responses=ERROR_RESPONSES,
)
async def resolve_invite(
    payload: ResolveInviteRequest, request: Request, response: Response
) -> InterviewBriefingResponse:
    from interview_api.workflow.telegram_routes import _check_browser_origin

    _check_browser_origin(request)
    service = _service(request)
    actor = await service.require_actor(_session_token(request))
    raw_session, _session, briefing = await service.resolve_invite(
        payload.token, actor=actor, raw_session_token=_session_token(request)
    )
    _set_session_cookie(response, raw_session, service)
    response.headers["Cache-Control"] = "no-store"
    return briefing


@router.get(
    "/candidate/interview",
    response_model=InterviewBriefingResponse,
    responses=ERROR_RESPONSES,
)
async def get_current_candidate_interview(request: Request) -> InterviewBriefingResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="candidate")
    return await service.get_current_candidate_interview(actor=actor)


@router.get(
    "/interviews/{interview_id}",
    response_model=InterviewBriefingResponse,
    responses=ERROR_RESPONSES,
)
async def get_interview(interview_id: str, request: Request) -> InterviewBriefingResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="candidate")
    return await service.get_interview_briefing(actor=actor, interview_id=interview_id)


@router.get(
    "/interviews/{interview_id}/state",
    response_model=InterviewStateResponse,
    responses=ERROR_RESPONSES,
)
async def get_interview_state(interview_id: str, request: Request) -> InterviewStateResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="candidate")
    return await service.get_interview_state(actor=actor, interview_id=interview_id)


@router.post(
    "/interviews/{interview_id}/start",
    response_model=InterviewStateResponse,
    responses=ERROR_RESPONSES,
)
async def start_interview(
    interview_id: str,
    payload: StartInterviewRequest,
    request: Request,
) -> InterviewStateResponse:
    del payload  # validation of consentToRecording=true is the required side effect
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="candidate")
    return await service.start_interview(actor=actor, interview_id=interview_id)


@router.post(
    "/interviews/{interview_id}/answers",
    response_model=AnswerResponse,
    responses=ERROR_RESPONSES,
)
async def submit_answer(
    interview_id: str,
    request: Request,
    question_id: Annotated[str, Form(alias="questionId", min_length=1)],
    audio: Annotated[UploadFile, File()],
    video: Annotated[UploadFile, File()],
    duration_seconds: Annotated[int | None, Form(alias="durationSeconds", ge=0, le=300)] = None,
    language: Annotated[str, Form(min_length=2, max_length=35)] = "ru",
) -> AnswerResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="candidate")
    audio_filename = audio.filename or "answer.webm"
    audio_content_type = audio.content_type or "audio/webm"
    audio_data = await _read_upload(audio, service.max_audio_bytes)
    video_filename = video.filename or "answer-video.webm"
    video_content_type = video.content_type or "video/webm"
    video_data = await _read_upload(video, service.max_video_bytes)
    return await service.submit_answer(
        actor=actor,
        interview_id=interview_id,
        question_id=question_id,
        audio_data=audio_data,
        audio_filename=audio_filename,
        audio_content_type=audio_content_type,
        video_data=video_data,
        video_filename=video_filename,
        video_content_type=video_content_type,
        duration_seconds=duration_seconds,
        language=language,
    )


@router.get(
    "/interviews/{interview_id}/questions/{question_id}/speech",
    responses={
        200: {"content": {"audio/mpeg": {}, "audio/wav": {}}},
        **ERROR_RESPONSES,
    },
)
async def get_question_speech(interview_id: str, question_id: str, request: Request) -> Response:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="candidate")
    audio, content_type = await service.question_speech(
        actor=actor, interview_id=interview_id, question_id=question_id
    )
    return Response(
        content=audio,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.post(
    "/interviews/{interview_id}/complete",
    response_model=CompleteInterviewResponse,
    responses=ERROR_RESPONSES,
)
async def complete_interview(interview_id: str, request: Request) -> CompleteInterviewResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="candidate")
    return await service.complete_interview(actor=actor, interview_id=interview_id)


@router.get(
    "/candidates/{candidate_id}/analysis",
    response_model=AnalysisResponse,
    responses=ERROR_RESPONSES,
)
async def get_candidate_analysis(candidate_id: str, request: Request) -> AnalysisResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.get_analysis(actor=actor, candidate_id=candidate_id)


@router.get(
    "/candidates/{candidate_id}/media",
    response_model=MediaListResponse,
    responses=ERROR_RESPONSES,
)
async def get_candidate_media(candidate_id: str, request: Request) -> MediaListResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.list_media(actor=actor, candidate_id=candidate_id)


@router.post(
    "/candidates/{candidate_id}/analysis/review",
    response_model=ReviewHeartbeatResponse,
    responses=ERROR_RESPONSES,
)
async def review_analysis_item(
    candidate_id: str,
    payload: ReviewHeartbeatRequest,
    request: Request,
) -> ReviewHeartbeatResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.record_review(actor=actor, candidate_id=candidate_id, request=payload)


@router.post(
    "/candidates/{candidate_id}/decision",
    response_model=DecisionResponse,
    responses=ERROR_RESPONSES,
)
async def record_candidate_decision(
    candidate_id: str,
    payload: DecisionRequest,
    request: Request,
) -> DecisionResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.decide(actor=actor, candidate_id=candidate_id, request=payload)


@router.get(
    "/candidate/outcome",
    response_model=CandidateOutcomeResponse,
    responses=ERROR_RESPONSES,
)
async def get_candidate_outcome(request: Request) -> CandidateOutcomeResponse:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="candidate")
    return await service.candidate_outcome(actor=actor)


# Company hiring setup. Existing /positions and candidate-session endpoints are retained
# for links created before the vacancy → interview-plan hierarchy was introduced.


@router.get(
    "/company-context", response_model=list[ContextDocumentResponse], responses=ERROR_RESPONSES
)
async def list_company_context(request: Request):
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.list_company_context(actor=actor)


@router.post("/company-context", response_model=ContextDocumentResponse, responses=ERROR_RESPONSES)
async def upload_company_context(request: Request, document: Annotated[UploadFile, File()]):
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.upload_company_context(
        actor=actor,
        data=await _read_upload(document, service.max_document_bytes),
        filename=document.filename or "context.txt",
        content_type=document.content_type or "application/octet-stream",
    )


@router.get(
    "/vacancy-templates", response_model=list[VacancyTemplateResponse], responses=ERROR_RESPONSES
)
async def list_vacancy_templates(
    request: Request, role: str | None = None, level: str | None = None
):
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.list_vacancy_templates(actor=actor, role=role, level=level)


@router.patch(
    "/vacancy-templates/{template_id}",
    response_model=VacancyTemplateResponse,
    responses=ERROR_RESPONSES,
)
async def update_vacancy_template(template_id: str, payload: VacancyFields, request: Request):
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.update_vacancy_template(
        actor=actor, template_id=template_id, payload=payload
    )


@router.get(
    "/interview-templates",
    response_model=list[InterviewTemplateResponse],
    responses=ERROR_RESPONSES,
)
async def list_interview_templates(request: Request):
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.list_interview_templates(actor=actor)


@router.patch(
    "/interview-templates/{template_id}",
    response_model=InterviewTemplateResponse,
    responses=ERROR_RESPONSES,
)
async def update_interview_template(
    template_id: str, payload: InterviewTemplateFields, request: Request
):
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.update_interview_template(
        actor=actor, template_id=template_id, payload=payload
    )


@router.get("/vacancies", response_model=list[VacancyResponse], responses=ERROR_RESPONSES)
async def list_vacancies(request: Request):
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.list_vacancies(actor=actor)


@router.post("/vacancies/parse", response_model=VacancyDraftResponse, responses=ERROR_RESPONSES)
async def prepare_vacancy(request: Request, vacancy: Annotated[UploadFile, File()]):
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.prepare_vacancy(
        actor=actor,
        data=await _read_upload(vacancy, service.max_document_bytes),
        filename=vacancy.filename or "vacancy.txt",
        content_type=vacancy.content_type or "application/octet-stream",
    )


@router.post("/vacancies", response_model=VacancyDetailResponse, responses=ERROR_RESPONSES)
async def create_vacancy(payload: VacancyCreateRequest, request: Request):
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.create_vacancy(actor=actor, payload=payload)


@router.get(
    "/vacancies/{vacancy_id}", response_model=VacancyDetailResponse, responses=ERROR_RESPONSES
)
async def get_vacancy(vacancy_id: str, request: Request):
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.get_vacancy(actor=actor, vacancy_id=vacancy_id)


@router.patch(
    "/vacancies/{vacancy_id}", response_model=VacancyDetailResponse, responses=ERROR_RESPONSES
)
async def update_vacancy(vacancy_id: str, payload: VacancyFields, request: Request):
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.update_vacancy(actor=actor, vacancy_id=vacancy_id, payload=payload)


@router.post(
    "/vacancies/{vacancy_id}/interviews/prepare",
    response_model=InterviewDraftResponse,
    responses=ERROR_RESPONSES,
)
async def prepare_interview(vacancy_id: str, payload: PrepareInterviewRequest, request: Request):
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.prepare_interview(
        actor=actor, vacancy_id=vacancy_id, template_id=payload.template_id
    )


@router.post(
    "/vacancies/{vacancy_id}/interviews",
    response_model=InterviewPlanResponse,
    responses=ERROR_RESPONSES,
)
async def create_interview_plan(vacancy_id: str, payload: InterviewCreateRequest, request: Request):
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.create_interview_plan(actor=actor, vacancy_id=vacancy_id, payload=payload)


@router.get(
    "/interview-plans/{plan_id}",
    response_model=InterviewPlanDetailResponse,
    responses=ERROR_RESPONSES,
)
async def get_interview_plan(plan_id: str, request: Request):
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.get_interview_plan(actor=actor, plan_id=plan_id)


@router.post(
    "/interview-plans/{plan_id}/candidates/prepare",
    response_model=CandidateDraftResponse,
    responses=ERROR_RESPONSES,
)
async def prepare_plan_candidate(
    plan_id: str, request: Request, resume: Annotated[UploadFile, File()]
):
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.prepare_plan_candidate(
        actor=actor,
        plan_id=plan_id,
        data=await _read_upload(resume, service.max_document_bytes),
        filename=resume.filename or "resume.txt",
        content_type=resume.content_type or "application/octet-stream",
    )


@router.post(
    "/interview-plans/{plan_id}/candidates",
    response_model=ApprovalResponse,
    responses=ERROR_RESPONSES,
)
async def create_plan_candidate(plan_id: str, payload: CandidateCreateRequest, request: Request):
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.create_plan_candidate(actor=actor, plan_id=plan_id, payload=payload)


@router.get("/candidates", response_model=list[CompanyCandidateSummary], responses=ERROR_RESPONSES)
async def list_all_candidates(request: Request, search: str | None = None):
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    return await service.list_all_candidates(actor=actor, search=search)
