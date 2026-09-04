from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, BinaryIO, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

ContextType = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_-]*$",
    ),
]
FileId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    ),
]
LanguageCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=2,
        max_length=35,
        pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$",
    ),
]
CorrelationId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContextReference(StrictModel):
    type: ContextType
    file_id: FileId

    @field_validator("file_id")
    @classmethod
    def reject_path_segments(cls, value: str) -> str:
        if ".." in value:
            raise ValueError("file_id must not contain '..'")
        return value


class GenerateQuestionsRequest(StrictModel):
    context: list[ContextReference] = Field(min_length=1, max_length=20)
    question_count: int = Field(ge=1, le=20)
    core_question_count: int = Field(ge=0, le=20)
    language: LanguageCode

    @model_validator(mode="after")
    def validate_counts_and_context(self) -> "GenerateQuestionsRequest":
        if self.core_question_count > self.question_count:
            raise ValueError("core_question_count must not exceed question_count")

        file_ids = [item.file_id for item in self.context]
        if len(file_ids) != len(set(file_ids)):
            raise ValueError("context file_id values must be unique")
        return self


class GenerateQuestionsParameters(StrictModel):
    question_count: int = Field(ge=1, le=20)
    core_question_count: int = Field(ge=0, le=20)
    language: LanguageCode

    @model_validator(mode="after")
    def validate_counts(self) -> "GenerateQuestionsParameters":
        if self.core_question_count > self.question_count:
            raise ValueError("core_question_count must not exceed question_count")
        return self


class QuestionType(StrEnum):
    CORE = "core"
    PERSONALIZED = "personalized"


class QuestionDraft(StrictModel):
    type: QuestionType
    text: str = Field(min_length=1, max_length=2_000)
    competency: str = Field(min_length=1, max_length=200)
    source_file_ids: list[FileId] = Field(min_length=1, max_length=20)

    @field_validator("source_file_ids")
    @classmethod
    def require_unique_sources(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("source_file_ids must be unique")
        return value


class InterviewQuestion(QuestionDraft):
    id: UUID


class GenerateQuestionsResponse(StrictModel):
    questions: list[InterviewQuestion] = Field(min_length=1, max_length=20)


class LoadedContext(StrictModel):
    type: ContextType
    file_id: FileId
    text: str = Field(min_length=1)


class QuestionGenerationInput(StrictModel):
    core_contexts: list[LoadedContext]
    personalized_contexts: list[LoadedContext]
    question_count: int = Field(ge=1, le=20)
    core_question_count: int = Field(ge=0, le=20)
    language: LanguageCode


class StructuredQuestionsOutput(StrictModel):
    questions: list[QuestionDraft] = Field(min_length=1, max_length=20)


@dataclass(slots=True)
class DocumentInput:
    """Request-scoped, seekable document input owned by the caller."""

    stream: BinaryIO
    size_bytes: int
    context_type: str
    file_id: str
    filename: str | None = None
    content_type: str | None = None


@dataclass(slots=True)
class AudioInput:
    """Transport-independent, seekable audio input owned by the caller."""

    stream: BinaryIO
    size_bytes: int
    filename: str | None = None
    content_type: str | None = None
    language: str | None = None


@dataclass(slots=True)
class TranscriptionCommand:
    audio: AudioInput
    interview_id: str | None = None
    question_id: str | None = None


class ProviderTranscript(StrictModel):
    text: str
    is_final: bool = True
    provider: str = Field(min_length=1, max_length=64)


class ProviderMeta(StrictModel):
    provider: str = Field(min_length=1, max_length=64)


class TranscriptionResult(StrictModel):
    text: str
    is_final: bool
    question_id: str | None
    meta: ProviderMeta


class AnnotationLabel(StrEnum):
    INCORRECT = "неправильный"
    REVIEW = "рекомендуется проверка"


class EvaluateAnswerRequest(StrictModel):
    question: str = Field(min_length=1, max_length=4_000)
    answer: str = Field(min_length=1, max_length=50_000)


class ExtractedClaim(StrictModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str = Field(min_length=1)


class ClaimJudgement(StrictModel):
    verdict: Literal["correct", "incorrect"]
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1)


class AnswerAnnotation(ExtractedClaim):
    label: AnnotationLabel
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1)


class MissingAspect(ExtractedClaim):
    confidence: float = Field(ge=0, le=1)
    rationale: str = Field(min_length=1)


class EvaluationMeta(StrictModel):
    models: list[str] = Field(min_length=1)
    providers: list[str] = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    claims_evaluated: int = Field(ge=0)


class EvaluateAnswerResponse(StrictModel):
    spans: list[AnswerAnnotation]
    missing_aspects: list[MissingAspect]
    meta: EvaluationMeta


class ErrorDetail(StrictModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(StrictModel):
    error: ErrorDetail
