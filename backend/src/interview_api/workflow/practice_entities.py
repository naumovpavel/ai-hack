from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from interview_api.workflow.entities import WorkflowBase, utc_now


class PracticeSessionRow(WorkflowBase):
    """Candidate-private rehearsal, deliberately separate from all hiring records."""

    __tablename__ = "workflow_practice_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    interview_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_interviews.id", ondelete="CASCADE"), unique=True, index=True
    )
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_candidates.id", ondelete="CASCADE"), index=True
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="ready")
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    questions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    answers: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    analysis: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    review: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    __mapper_args__ = {"version_id_col": revision}
