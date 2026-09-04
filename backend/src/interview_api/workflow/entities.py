from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(UTC)


class WorkflowBase(DeclarativeBase):
    """Declarative base exported for Alembic metadata discovery."""


class UserRow(WorkflowBase):
    __tablename__ = "workflow_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    # Deliberately not a database FK: positions reference HR users while candidate
    # users point back to candidates, and an FK here would create a schema cycle.
    candidate_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class AuthSessionRow(WorkflowBase):
    __tablename__ = "workflow_auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class PositionRow(WorkflowBase):
    __tablename__ = "workflow_positions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_by: Mapped[str] = mapped_column(
        ForeignKey("workflow_users.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(240))
    level: Mapped[str] = mapped_column(String(120), default="")
    location: Mapped[str] = mapped_column(String(240), default="")
    requirements: Mapped[list[str]] = mapped_column(JSON, default=list)
    question_count: Mapped[int] = mapped_column(Integer)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    max_follow_up_questions: Mapped[int] = mapped_column(Integer, default=2)
    vacancy_object_key: Mapped[str] = mapped_column(String(900))
    vacancy_filename: Mapped[str] = mapped_column(String(500))
    vacancy_content_type: Mapped[str] = mapped_column(String(200))
    vacancy_text: Mapped[str] = mapped_column(Text)
    seed_questions: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class CandidateRow(WorkflowBase):
    __tablename__ = "workflow_candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    position_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_positions.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(240))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    role: Mapped[str] = mapped_column(String(240), default="")
    resume_object_key: Mapped[str] = mapped_column(String(900))
    resume_filename: Mapped[str] = mapped_column(String(500))
    resume_content_type: Mapped[str] = mapped_column(String(200))
    resume_text: Mapped[str] = mapped_column(Text)
    processing_status: Mapped[str] = mapped_column(String(32), default="not_started", index=True)
    hiring_decision: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class QuestionRow(WorkflowBase):
    __tablename__ = "workflow_questions"
    __table_args__ = (
        UniqueConstraint("candidate_id", "order_index", name="uq_workflow_question_order"),
        Index("ix_workflow_questions_candidate_status", "candidate_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_candidates.id", ondelete="CASCADE"), index=True
    )
    parent_question_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_questions.id", ondelete="SET NULL"), nullable=True
    )
    order_index: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(24))
    text: Mapped[str] = mapped_column(Text)
    topic: Mapped[str] = mapped_column(String(240))
    competency: Mapped[str] = mapped_column(String(240), default="")
    source_refs: Mapped[list[str]] = mapped_column(JSON, default=list)
    follow_up_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class InviteRow(WorkflowBase):
    __tablename__ = "workflow_invites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_candidates.id", ondelete="CASCADE"), unique=True, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class InterviewRow(WorkflowBase):
    __tablename__ = "workflow_interviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_candidates.id", ondelete="CASCADE"), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="ready", index=True)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class AnswerRow(WorkflowBase):
    __tablename__ = "workflow_answers"
    __table_args__ = (
        UniqueConstraint("interview_id", "question_id", name="uq_workflow_answer_question"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    interview_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_interviews.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_questions.id", ondelete="RESTRICT"), index=True
    )
    transcript: Mapped[str] = mapped_column(Text)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class MediaAssetRow(WorkflowBase):
    __tablename__ = "workflow_media_assets"
    __table_args__ = (
        UniqueConstraint("answer_id", "kind", name="uq_workflow_media_answer_kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_candidates.id", ondelete="CASCADE"), index=True
    )
    interview_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_interviews.id", ondelete="CASCADE"), index=True
    )
    answer_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_answers.id", ondelete="CASCADE"), nullable=True, index=True
    )
    question_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_questions.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32), index=True)
    object_key: Mapped[str] = mapped_column(String(900), unique=True)
    filename: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(200))
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class AnalysisRow(WorkflowBase):
    __tablename__ = "workflow_analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_candidates.id", ondelete="CASCADE"), unique=True, index=True
    )
    version: Mapped[str] = mapped_column(String(80))
    score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    recommendation: Mapped[str] = mapped_column(String(32), index=True)
    summary: Mapped[str] = mapped_column(Text)
    strengths: Mapped[list[str]] = mapped_column(JSON, default=list)
    growth_areas: Mapped[list[str]] = mapped_column(JSON, default=list)
    unknowns: Mapped[list[str]] = mapped_column(JSON, default=list)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    next_questions: Mapped[list[str]] = mapped_column(JSON, default=list)
    model_meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class AnalysisItemRow(WorkflowBase):
    __tablename__ = "workflow_analysis_items"
    __table_args__ = (
        UniqueConstraint("analysis_id", "order_index", name="uq_workflow_analysis_item_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_analyses.id", ondelete="CASCADE"), index=True
    )
    order_index: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    question_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_questions.id", ondelete="SET NULL"), nullable=True
    )
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    required_review: Mapped[bool] = mapped_column(Boolean, default=True)


class ReviewProgressRow(WorkflowBase):
    __tablename__ = "workflow_review_progress"
    __table_args__ = (
        UniqueConstraint("analysis_item_id", "user_id", name="uq_workflow_review_user_item"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analysis_item_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_analysis_items.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_users.id", ondelete="CASCADE"), index=True
    )
    accumulated_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DecisionRow(WorkflowBase):
    __tablename__ = "workflow_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_candidates.id", ondelete="CASCADE"), unique=True, index=True
    )
    decided_by: Mapped[str] = mapped_column(
        ForeignKey("workflow_users.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(24), index=True)
    internal_reason: Mapped[str] = mapped_column(Text, default="")
    candidate_feedback: Mapped[str] = mapped_column(Text, default="")
    internal_reason_paste_events: Mapped[int] = mapped_column(Integer, default=0)
    internal_reason_typed_characters: Mapped[int] = mapped_column(Integer, default=0)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
