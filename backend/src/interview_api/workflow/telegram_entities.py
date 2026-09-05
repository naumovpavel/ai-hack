from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from interview_api.workflow.entities import WorkflowBase, utc_now


class TelegramAccountRow(WorkflowBase):
    __tablename__ = "workflow_telegram_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_users.id", ondelete="CASCADE"), unique=True, index=True
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    username: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    started: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    first_name: Mapped[str] = mapped_column(String(200), default="")
    last_name: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class TelegramLoginChallengeRow(WorkflowBase):
    __tablename__ = "workflow_telegram_login_challenges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    start_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    poll_token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(16))
    invite_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_users.id", ondelete="CASCADE"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
