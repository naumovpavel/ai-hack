from __future__ import annotations

import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from interview_api.workflow.entities import CandidateRow, UserRow
from interview_api.workflow.errors import (
    WorkflowServiceUnavailableError,
    WorkflowUnauthorizedError,
    WorkflowValidationError,
)
from interview_api.workflow.schemas import SessionResponse
from interview_api.workflow.telegram_schemas import TelegramStartResponse, TelegramStatusResponse

logger = logging.getLogger(__name__)
TELEGRAM_LOGIN_TTL = timedelta(minutes=5)
TELEGRAM_LOGIN_COOKIE = "signal_telegram_login"
_USERNAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{4,31}\Z")
_START = re.compile(r"/start(?:@([A-Za-z0-9_]+))?(?:\s+([A-Za-z0-9_-]{1,64}))?\s*\Z")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class TelegramAuthMixin:
    """Telegram identity and browser-bound login for ``WorkflowService``.

    The host provides repository, _now, _hash_token, _user_response,
    require_actor and session_ttl. Runtime configuration optionally supplies
    telegram_client, telegram_bot_username and telegram_webhook_secret.
    Only an authenticated Bot API update source may call handle_telegram_update.
    """

    async def start_telegram_login(
        self, role: str, invite_token: str | None = None
    ) -> tuple[str, TelegramStartResponse]:
        if role not in {"hr", "candidate"}:
            raise WorkflowValidationError("Choose the HR or candidate role.")
        username = str(getattr(self, "telegram_bot_username", "") or "").lstrip("@")
        if not _USERNAME.fullmatch(username):
            raise WorkflowServiceUnavailableError("Telegram sign-in is not configured.")
        raw_start, raw_poll = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        expires_at = self._now() + TELEGRAM_LOGIN_TTL
        await self.repository.create_telegram_challenge(
            start_token_hash=self._hash_token(raw_start),
            poll_token_hash=self._hash_token(raw_poll),
            role="candidate" if invite_token else role,
            invite_token_hash=self._hash_token(invite_token) if invite_token else None,
            expires_at=expires_at,
        )
        return raw_poll, TelegramStartResponse(
            bot_url=f"https://t.me/{username}?start={raw_start}", expires_at=expires_at
        )

    async def poll_telegram_login(
        self,
        raw_poll_cookie: str | None,
        raw_session_token: str | None = None,
    ) -> tuple[str | None, TelegramStatusResponse]:
        challenge = (
            await self.repository.get_telegram_challenge(self._hash_token(raw_poll_cookie))
            if raw_poll_cookie
            else None
        )
        if not raw_poll_cookie or (challenge is not None and challenge.consumed_at):
            if raw_session_token:
                try:
                    actor = await self.require_actor(raw_session_token)
                except WorkflowUnauthorizedError:
                    pass
                else:
                    account = await self.repository.get_telegram_account(actor.id)
                    if account and (challenge is None or challenge.approved_user_id == actor.id):
                        return None, TelegramStatusResponse(
                            status="authenticated", user=self._user_response(actor)
                        )
            return None, TelegramStatusResponse(status="expired")
        if challenge is None or _aware(challenge.expires_at) <= self._now():
            return None, TelegramStatusResponse(status="expired")
        if challenge.approved_user_id is None:
            return None, TelegramStatusResponse(status="pending")
        raw_session = secrets.token_urlsafe(32)
        actor = await self.repository.consume_telegram_challenge(
            poll_token_hash=self._hash_token(raw_poll_cookie),
            session_token_hash=self._hash_token(raw_session),
            session_expires_at=self._now() + self.session_ttl,
            now=self._now(),
        )
        if actor is None:
            # A concurrent request may have consumed it. Never mint another
            # session from the same browser challenge.
            return None, TelegramStatusResponse(status="expired")
        return raw_session, TelegramStatusResponse(
            status="authenticated", user=self._user_response(actor)
        )

    async def session_for_telegram_actor(
        self,
        actor: UserRow,
        role: str,
        candidate_id: str | None = None,
        previous_token: str | None = None,
    ) -> tuple[str, SessionResponse]:
        if role not in {"hr", "candidate"}:
            raise WorkflowValidationError("Choose the HR or candidate role.")
        raw_session = secrets.token_urlsafe(32)
        expires_at = self._now() + self.session_ttl
        user = await self.repository.create_telegram_session(
            user_id=actor.id,
            role=role,
            candidate_id=candidate_id,
            token_hash=self._hash_token(raw_session),
            expires_at=expires_at,
            previous_token_hash=self._hash_token(previous_token) if previous_token else None,
        )
        return raw_session, SessionResponse(user=self._user_response(user), expires_at=expires_at)

    async def switch_telegram_role(
        self, raw_session_token: str | None, role: str
    ) -> tuple[str, SessionResponse]:
        actor = await self.require_actor(raw_session_token)
        return await self.session_for_telegram_actor(
            actor,
            role=role,
            candidate_id=actor.candidate_id,
            previous_token=raw_session_token,
        )

    async def logout_telegram_session(self, raw_session_token: str | None) -> None:
        if raw_session_token:
            await self.repository.revoke_auth_session(self._hash_token(raw_session_token))

    async def claim_telegram_invite(self, actor: UserRow, raw_invite: str) -> CandidateRow:
        return await self.repository.claim_telegram_candidate(
            user_id=actor.id, invite_token_hash=self._hash_token(raw_invite), now=self._now()
        )

    async def handle_telegram_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return
        sender, chat, text = message.get("from"), message.get("chat"), message.get("text")
        if not isinstance(sender, dict) or not isinstance(chat, dict) or not isinstance(text, str):
            return
        telegram_id, chat_id = sender.get("id"), chat.get("id")
        if (
            chat.get("type") != "private"
            or not isinstance(telegram_id, int)
            or isinstance(telegram_id, bool)
            or telegram_id <= 0
            or chat_id != telegram_id
            or sender.get("is_bot")
        ):
            return
        start = _START.fullmatch(text.strip())
        if start is None:
            return
        addressed_bot, raw_start = start.groups()
        bot_username = str(getattr(self, "telegram_bot_username", "") or "").lstrip("@")
        if addressed_bot and addressed_bot.lower() != bot_username.lower():
            return
        username = sender.get("username")
        if not isinstance(username, str) or not _USERNAME.fullmatch(username):
            username = None
        account = await self.repository.register_telegram_account(
            telegram_id=telegram_id,
            chat_id=chat_id,
            username=username.lower() if username else None,
            first_name=str(sender.get("first_name") or "")[:200],
            last_name=str(sender.get("last_name") or "")[:200],
            now=self._now(),
        )
        reply = "Telegram подключён. Здесь будут появляться уведомления об интервью."
        if raw_start:
            approved = await self.repository.approve_telegram_challenge(
                start_token_hash=self._hash_token(raw_start),
                user_id=account.user_id,
                now=self._now(),
            )
            reply = (
                "Вход подтверждён. Вернитесь на сайт: авторизация завершится автоматически."
                if approved
                else "Ссылка истекла или уже использована. Нажмите «Войти» на сайте ещё раз."
            )
        client = getattr(self, "telegram_client", None)
        if client is not None:
            try:
                await client.call("sendMessage", {"chat_id": chat_id, "text": reply})
            except Exception:
                # A confirmation outage must not roll back identity/challenge
                # persistence. Never log provider URLs or credentials.
                logger.warning("Could not deliver the Telegram login confirmation.")
