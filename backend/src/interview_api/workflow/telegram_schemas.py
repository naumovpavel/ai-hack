from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from interview_api.workflow.schemas import ApiModel, UserResponse


class TelegramStartRequest(ApiModel):
    role: Literal["hr", "candidate"] = "hr"
    invite_token: str | None = Field(default=None, min_length=1, max_length=512)


class TelegramStartResponse(ApiModel):
    bot_url: str
    expires_at: datetime


class TelegramStatusResponse(ApiModel):
    status: Literal["pending", "expired", "authenticated"]
    user: UserResponse | None = None


class SwitchRoleRequest(ApiModel):
    role: Literal["hr", "candidate"]
