"""Managed Bot API polling and durable notification delivery for the FastAPI lifespan."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from interview_api.config import Settings
from interview_api.workflow.entities import WorkflowBase
from interview_api.workflow.telegram_client import TelegramBotClient
from interview_api.workflow.telegram_notifications import TelegramNotificationService

logger = logging.getLogger(__name__)


class TelegramPollStateRow(WorkflowBase):
    __tablename__ = "workflow_telegram_poll_state"

    bot: Mapped[str] = mapped_column(String(100), primary_key=True)
    offset: Mapped[int] = mapped_column(BigInteger, default=0)


class TelegramRuntime:
    def __init__(self, service, settings: Settings) -> None:
        self.service = service
        self.settings = settings
        self.tasks: list[asyncio.Task] = []
        self.client = TelegramBotClient(settings.telegram_bot_token.get_secret_value())
        service.telegram_client = self.client
        service.telegram_bot_username = settings.telegram_bot_username.lstrip("@")
        service.telegram_webhook_secret = (
            settings.telegram_webhook_secret.get_secret_value()
            if settings.telegram_update_mode == "webhook" and settings.telegram_webhook_secret
            else None
        )
        service.telegram_notifier = TelegramNotificationService(
            session_factory=service.repository._sessions, client=self.client
        )

    async def start(self) -> None:
        if self.settings.telegram_update_mode == "disabled":
            return
        self.tasks.append(asyncio.create_task(self._updates(), name="telegram-updates"))
        self.tasks.append(asyncio.create_task(self._notifications(), name="telegram-notifications"))

    async def stop(self) -> None:
        for task in self.tasks:
            task.cancel()
        for task in self.tasks:
            with suppress(asyncio.CancelledError):
                await task

    async def _updates(self) -> None:
        while True:
            try:
                identity = await self.client.get_me()
                self.service.telegram_bot_username = identity["username"]
                break
            except Exception:
                logger.warning("Telegram is unavailable; retrying bot initialization.")
                await asyncio.sleep(10)
        if self.settings.telegram_update_mode != "polling":
            return
        bot = str(identity["id"])
        while True:
            try:
                async with self.service.repository._sessions.begin() as session:
                    state = await session.get(TelegramPollStateRow, bot)
                    if state is None:
                        state = TelegramPollStateRow(bot=bot, offset=0)
                        session.add(state)
                    offset = state.offset
                break
            except Exception:
                logger.warning("Unable to read Telegram update cursor; retrying.")
                await asyncio.sleep(5)
        while True:
            try:
                updates = await self.client.get_updates(offset=offset, timeout=25)
                for update in updates:
                    await self.service.handle_telegram_update(update)
                    next_offset = update["update_id"] + 1
                    async with self.service.repository._sessions.begin() as session:
                        state = await session.get(TelegramPollStateRow, bot)
                        state.offset = next_offset
                    offset = next_offset
            except Exception:
                # Never print exceptions containing Bot API URLs (which include the token).
                logger.warning("Telegram polling failed; retrying with the saved update cursor.")
                await asyncio.sleep(5)

    async def _notifications(self) -> None:
        while True:
            try:
                await self.service.telegram_notifier.dispatch_pending()
            except Exception:
                logger.warning("Telegram notification delivery failed; retrying.")
            await asyncio.sleep(2)
