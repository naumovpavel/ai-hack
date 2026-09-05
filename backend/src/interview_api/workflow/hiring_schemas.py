from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from interview_api.workflow.schemas import ApiModel, CandidateSummary


class VacancyFields(ApiModel):
    title: str = Field(min_length=3, max_length=240)
    role: str = Field(min_length=2, max_length=240)
    level: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=10, max_length=60_000)
    requirements: list[str] = Field(min_length=1, max_length=80)

    @field_validator("title", "role", "level", "description")
    @classmethod
    def trim_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Text cannot be empty")
        return value.strip()

    @field_validator("requirements")
    @classmethod
    def clean_requirements(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned or any(len(item) > 4000 for item in cleaned):
            raise ValueError("Requirements must contain nonempty items up to 4000 characters")
        return cleaned


class VacancyCreateRequest(VacancyFields):
    draft_id: str | None = None
    template_id: str | None = None


class VacancyDraftResponse(VacancyFields):
    draft_id: str


class VacancyTemplateResponse(VacancyFields):
    id: str
    adapted: bool = False


class InterviewTemplateFields(ApiModel):
    name: str = Field(min_length=3, max_length=240)
    description: str = Field(min_length=10, max_length=20_000)
    evaluates: list[str] = Field(min_length=1, max_length=40)

    @field_validator("evaluates")
    @classmethod
    def clean_evaluates(cls, value: list[str]) -> list[str]:
        value = [item.strip() for item in value if item.strip()]
        if not value or any(len(item) > 4000 for item in value):
            raise ValueError("Evaluation criteria cannot be empty or exceed 4000 characters")
        return value


class InterviewTemplateResponse(InterviewTemplateFields):
    id: str
    adapted: bool = False


class ContextDocumentResponse(ApiModel):
    id: str
    filename: str
    text: str
    status: str = "ready"
    created_at: datetime


class EditableQuestion(ApiModel):
    text: str = Field(min_length=3, max_length=4000)
    topic: str = Field(default="Опыт и компетенции", min_length=1, max_length=240)
    competency: str = Field(default="Практические навыки", min_length=1, max_length=240)

    @field_validator("text", "topic", "competency")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Question fields cannot be blank")
        return value.strip()


class PrepareInterviewRequest(ApiModel):
    template_id: str


class InterviewSettings(ApiModel):
    max_follow_up_questions: int = Field(default=2, ge=0, le=10)
    max_personalized_questions: int = Field(default=3, ge=0, le=10)
    duration_minutes: int = Field(default=30, ge=5, le=120)


class InterviewCreateRequest(InterviewSettings):
    template_id: str
    questions: list[EditableQuestion] = Field(min_length=1, max_length=20)


class InterviewDraftResponse(InterviewCreateRequest, InterviewTemplateFields):
    pass


class InterviewPlanResponse(InterviewDraftResponse):
    id: str
    vacancy_id: str
    candidate_count: int = 0
    created_at: datetime


class VacancyResponse(VacancyFields):
    id: str
    status: str
    created_at: datetime
    candidate_count: int = 0
    interview_count: int = 0


class VacancyDetailResponse(VacancyResponse):
    interviews: list[InterviewPlanResponse] = Field(default_factory=list)


class CompanyCandidateSummary(CandidateSummary):
    vacancy_id: str
    vacancy_title: str
    interview_plan_id: str | None = None
    interview_name: str = ""


class InterviewPlanDetailResponse(InterviewPlanResponse):
    vacancy: VacancyResponse
    candidates: list[CompanyCandidateSummary]


class CandidateDraftResponse(ApiModel):
    telegram_username: str | None = None
    draft_id: str
    name: str
    email: str | None = None
    role: str = ""
    questions: list[EditableQuestion]


class CandidateCreateRequest(ApiModel):
    telegram_username: str | None = Field(default=None, max_length=100)
    draft_id: str
    name: str = Field(min_length=2, max_length=240)
    email: str | None = Field(default=None, max_length=320)
    role: str = Field(default="", max_length=240)
    questions: list[EditableQuestion] = Field(default_factory=list, max_length=10)
