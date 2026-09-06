from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        from_attributes=True,
    )


class UserRole(StrEnum):
    HR = "hr"
    CANDIDATE = "candidate"


class UserResponse(ApiModel):
    telegram_username: str | None = None
    telegram_connected: bool = False
    roles: list[UserRole] = Field(default_factory=list)
    id: str
    role: UserRole
    name: str
    email: str | None = None
    candidate_id: str | None = None


class DevSessionRequest(ApiModel):
    user_id: str = Field(min_length=1, max_length=100)


class SessionResponse(ApiModel):
    user: UserResponse
    expires_at: datetime


class CandidateSummary(ApiModel):
    telegram_username: str | None = None
    id: str
    position_id: str
    name: str
    email: str | None = None
    role: str
    processing_status: str
    hiring_decision: str
    created_at: datetime


class PositionResponse(ApiModel):
    id: str
    title: str
    level: str
    location: str
    description: str
    requirements: list[str]
    question_count: int
    duration_minutes: int
    max_follow_up_questions: int
    status: str
    created_at: datetime
    candidate_count: int = 0


class PositionDetailResponse(PositionResponse):
    vacancy_filename: str
    seed_questions: list[str]
    candidates: list[CandidateSummary]


class QuestionKind(StrEnum):
    PROVIDED = "provided"
    GENERATED = "generated"
    FOLLOW_UP = "follow_up"


class QuestionResponse(ApiModel):
    id: str
    candidate_id: str
    parent_question_id: str | None = None
    order_index: int
    kind: QuestionKind
    text: str
    topic: str
    competency: str
    source_refs: list[str]
    follow_up_reason: str | None = None
    status: str


class CandidateDetailResponse(CandidateSummary):
    resume_filename: str
    questions: list[QuestionResponse]


class UpdateQuestionRequest(ApiModel):
    text: str | None = Field(default=None, min_length=3, max_length=4_000)
    topic: str | None = Field(default=None, min_length=2, max_length=240)
    competency: str | None = Field(default=None, min_length=2, max_length=240)
    order_index: int | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def require_change(self) -> UpdateQuestionRequest:
        if not self.model_fields_set:
            raise ValueError("At least one question field must be supplied")
        return self


class ApprovalResponse(ApiModel):
    candidate_id: str
    interview_id: str
    invite_token: str
    invite_url: str
    expires_at: datetime


class ResolveInviteRequest(ApiModel):
    token: str = Field(min_length=16, max_length=512)


class PublicQuestion(ApiModel):
    id: str
    text: str
    topic: str
    kind: QuestionKind
    order_index: int
    follow_up_reason: str | None = None


class InterviewBriefingResponse(ApiModel):
    interview_id: str
    candidate_id: str
    candidate_name: str
    position_id: str
    position_title: str
    topics: list[str]
    question_count: int
    duration_minutes: int
    status: str
    current_question: PublicQuestion | None = None
    records_audio: bool = True
    records_video: bool = True
    allows_follow_ups: bool = True
    evaluation_notice: str = (
        "AI structures answer evidence against the position requirements. It does not "
        "evaluate appearance, accent, voice, emotions, or protected characteristics."
    )
    human_review_notice: str = (
        "The hiring team evaluates each answer and records its own decision and feedback "
        "before seeing the AI recommendation. Only the confirmed human decision is published."
    )


class PracticeQuestionResponse(ApiModel):
    id: str
    text: str
    topic: str
    kind: Literal["practice"] = "practice"
    order_index: int
    answer_seconds: int = Field(ge=30, le=180)


class PracticeSetResponse(ApiModel):
    mode: Literal["practice"] = "practice"
    questions: list[PracticeQuestionResponse]
    practice_id: str
    interview_id: str
    status: str
    current_question: PracticeQuestionResponse | None = None
    answered_question_ids: list[str] = Field(default_factory=list)
    remaining_seconds: int = 0
    started_at: datetime | None = None
    deadline_at: datetime | None = None
    local_only: bool = False
    notice: str = (
        "Это тренировочные примеры. Настоящие вопросы будут другими, а ответы "
        "сохраняются для личного разбора, не передаются рекрутеру и не влияют на отбор."
    )


class PracticeAnswerResponse(ApiModel):
    answer_id: str
    transcript: str
    next_question: PracticeQuestionResponse | None
    follow_up_added: bool = False
    remaining_seconds: int


class StartInterviewRequest(ApiModel):
    consent_to_recording: bool

    @field_validator("consent_to_recording")
    @classmethod
    def require_consent(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Recording consent is required")
        return value


class InterviewStateResponse(ApiModel):
    interview_id: str
    status: str
    started_at: datetime | None
    deadline_at: datetime | None
    remaining_seconds: int
    current_question: PublicQuestion | None
    answered_question_ids: list[str] = Field(default_factory=list)


class AnswerResponse(ApiModel):
    answer_id: str
    transcript: str
    next_question: PublicQuestion | None
    follow_up_added: bool
    remaining_seconds: int


class AnalysisEvidenceResponse(ApiModel):
    quote: str
    label: Literal["confirmed", "incorrect", "check"]
    rationale: str = ""
    start: int
    end: int
    clip_start_seconds: float | None = None
    clip_end_seconds: float | None = None


class AnalysisItemResponse(ApiModel):
    id: str
    order_index: int
    kind: str
    title: str
    body: str
    question_id: str | None = None
    answer_text: str | None = None
    evidence: list[AnalysisEvidenceResponse]


QuestionRating = Literal["positive", "negative", "uncertain"]


class QuestionReviewRequest(ApiModel):
    rating: QuestionRating


class QuestionReviewResponse(ApiModel):
    question_id: str
    text: str
    topic: str
    kind: str
    answer_text: str | None
    rating: QuestionRating | None = None


class InitialDecisionResponse(ApiModel):
    status: Literal["next_stage", "rejected"]
    candidate_feedback: str
    internal_reason: str
    recorded_at: datetime


class AnalysisResponse(ApiModel):
    id: str
    candidate_id: str
    version: str
    score: float | None
    confidence: float | None
    recommendation: Literal["fit", "manual_review", "not_fit"] | None
    summary: str | None
    strengths: list[str]
    growth_areas: list[str]
    unknowns: list[str]
    skills: list[str]
    next_questions: list[str]
    items: list[AnalysisItemResponse]
    review_complete: bool
    recommendation_locked: bool
    questions: list[QuestionReviewResponse]
    initial_decision: InitialDecisionResponse | None = None
    final_decision: DecisionResponse | None = None
    change_reason: str = ""
    created_at: datetime


class CompleteInterviewResponse(ApiModel):
    interview_id: str
    status: str


class MediaAssetResponse(ApiModel):
    id: str
    kind: str
    filename: str
    content_type: str
    size_bytes: int
    download_url: str
    playback_url: str | None = None
    question_id: str | None = None


class MediaListResponse(ApiModel):
    candidate_id: str
    assets: list[MediaAssetResponse]


class DecisionStatus(StrEnum):
    NEXT_STAGE = "next_stage"
    REJECTED = "rejected"


class InitialDecisionRequest(ApiModel):
    status: DecisionStatus
    internal_reason: str = Field(default="", max_length=10_000)
    candidate_feedback: str = Field(min_length=1, max_length=10_000)

    @field_validator("candidate_feedback")
    @classmethod
    def meaningful_feedback(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Добавьте фидбэк кандидату.")
        return value.strip()


class DecisionRequest(InitialDecisionRequest):
    change_reason: str = Field(default="", max_length=10_000)


class DecisionResponse(ApiModel):
    id: str
    candidate_id: str
    status: DecisionStatus
    internal_reason: str
    candidate_feedback: str
    decided_at: datetime


class CandidateOutcomeResponse(ApiModel):
    candidate_id: str
    status: Literal["pending", "next_stage", "rejected"]
    candidate_feedback: str | None = None
    decided_at: datetime | None = None


class ErrorBody(ApiModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class WorkflowErrorResponse(ApiModel):
    error: ErrorBody
