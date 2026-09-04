from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


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
        "The hiring team must open every analysis item and spend at least 10 seconds "
        "reviewing each item before it can record a decision."
    )


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


class AnswerResponse(ApiModel):
    answer_id: str
    transcript: str
    next_question: PublicQuestion | None
    follow_up_added: bool
    remaining_seconds: int


class AnalysisItemResponse(ApiModel):
    id: str
    order_index: int
    kind: str
    title: str
    body: str
    question_id: str | None = None
    evidence: list[dict[str, Any]]
    required_review: bool
    reviewed_seconds: float = 0
    review_complete: bool = False


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
    question_id: str | None = None


class MediaListResponse(ApiModel):
    candidate_id: str
    assets: list[MediaAssetResponse]


class ReviewEvent(StrEnum):
    OPEN = "open"
    HEARTBEAT = "heartbeat"
    CLOSE = "close"


class ReviewHeartbeatRequest(ApiModel):
    item_id: str
    event: ReviewEvent
    visible: bool = True
    focused: bool = True


class ReviewHeartbeatResponse(ApiModel):
    item_id: str
    reviewed_seconds: float
    review_complete: bool
    all_items_complete: bool


class DecisionStatus(StrEnum):
    NEXT_STAGE = "next_stage"
    REJECTED = "rejected"


class DecisionRequest(ApiModel):
    status: DecisionStatus
    internal_reason: str = Field(default="", max_length=10_000)
    candidate_feedback: str = Field(default="", max_length=10_000)
    internal_reason_paste_events: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("pasteEvents", "internalReasonPasteEvents"),
        serialization_alias="pasteEvents",
    )
    internal_reason_typed_characters: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("typedCharacters", "internalReasonTypedCharacters"),
        serialization_alias="typedCharacters",
    )


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
