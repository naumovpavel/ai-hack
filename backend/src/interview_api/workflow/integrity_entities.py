"""Integrity records never modify answer scores or hiring decisions.

Media timestamps are milliseconds on a session clock; each recorder restart gets
a different stream_id. Original chunks and seekable streams share the same TTL.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from interview_api.workflow.entities import WorkflowBase, utc_now


class IntegritySessionRow(WorkflowBase):
    __tablename__ = "workflow_integrity_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    interview_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_interviews.id", ondelete="CASCADE"), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="recording", index=True)
    client_session_id: Mapped[str] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    camera_active: Mapped[bool] = mapped_column(Boolean, default=False)
    microphone_active: Mapped[bool] = mapped_column(Boolean, default=False)
    screen_active: Mapped[bool] = mapped_column(Boolean, default=False)
    display_surface: Mapped[str | None] = mapped_column(String(32), nullable=True)
    capture_state_offset_ms: Mapped[int] = mapped_column(Integer, default=0)
    issued_question_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    end_ms: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IntegrityEventRow(WorkflowBase):
    __tablename__ = "workflow_integrity_events"
    __table_args__ = (UniqueConstraint("session_id", "client_event_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_integrity_sessions.id", ondelete="CASCADE"), index=True
    )
    interview_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_interviews.id", ondelete="CASCADE"), index=True
    )
    client_event_id: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(64))
    offset_ms: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    question_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_questions.id", ondelete="SET NULL"), nullable=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class IntegrityChunkRow(WorkflowBase):
    __tablename__ = "workflow_integrity_chunks"
    __table_args__ = (
        UniqueConstraint("session_id", "client_chunk_id"),
        UniqueConstraint("session_id", "kind", "stream_id", "sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_integrity_sessions.id", ondelete="CASCADE"), index=True
    )
    interview_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_interviews.id", ondelete="CASCADE"), index=True
    )
    client_chunk_id: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(16))
    stream_id: Mapped[str] = mapped_column(String(100))
    sequence: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    object_key: Mapped[str] = mapped_column(String(900), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    question_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_questions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IntegrityMediaRow(WorkflowBase):
    __tablename__ = "workflow_integrity_media"
    __table_args__ = (UniqueConstraint("session_id", "kind", "stream_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_integrity_sessions.id", ondelete="CASCADE"), index=True
    )
    interview_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_interviews.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    stream_id: Mapped[str] = mapped_column(String(100))
    object_key: Mapped[str] = mapped_column(String(900), unique=True)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer)
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IntegrityJobRow(WorkflowBase):
    __tablename__ = "workflow_integrity_jobs"
    __table_args__ = (UniqueConstraint("interview_id", "start_ms", "end_ms"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_integrity_sessions.id", ondelete="CASCADE"), index=True
    )
    interview_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_interviews.id", ondelete="CASCADE"), index=True
    )
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    cost_usd_known: Mapped[bool] = mapped_column(Boolean, default=False)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IntegrityFindingRow(WorkflowBase):
    __tablename__ = "workflow_integrity_findings"
    __table_args__ = (UniqueConstraint("interview_id", "dedupe_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    interview_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_interviews.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_questions.id", ondelete="SET NULL"), nullable=True
    )
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_integrity_jobs.id", ondelete="SET NULL"), nullable=True
    )
    dedupe_key: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(24))
    observation: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    alternative_explanations: Mapped[list[str]] = mapped_column(JSON, default=list)
    limitations: Mapped[list[str]] = mapped_column(JSON, default=list)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    observability: Mapped[str] = mapped_column(String(32), default="partial")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class IntegrityReviewRow(WorkflowBase):
    __tablename__ = "workflow_integrity_reviews"
    __table_args__ = (UniqueConstraint("finding_id", "user_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    finding_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_integrity_findings.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_users.id", ondelete="RESTRICT"), index=True
    )
    decision: Mapped[str] = mapped_column(String(32))
    comment: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
