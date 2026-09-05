"""Durable best-effort Telegram notifications, independent of business actions.

Enqueue after a workflow transaction commits; a periodic worker calls
``dispatch_pending``. Delivery is at least once after a worker crash, because
Telegram sendMessage does not provide an idempotency key.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from interview_api.workflow.entities import CandidateRow, PositionRow
from interview_api.workflow.telegram_client import TelegramAPIError, TelegramBotClient
from interview_api.workflow.telegram_contacts import normalize_telegram_username
from interview_api.workflow.telegram_entities import TelegramAccountRow
from interview_api.workflow.telegram_notification_entities import TelegramNotificationRow

logger = logging.getLogger(__name__)


class TelegramNotificationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        client: TelegramBotClient,
        *,
        clock: Callable[[], datetime] | None = None,
        max_attempts: int = 8,
    ) -> None:
        self._sessions = session_factory
        self.client = client
        self._clock = clock or (lambda: datetime.now(UTC))
        self.max_attempts = max(1, max_attempts)

    async def candidate_status(
        self,
        candidate_id: str,
        *,
        event_key: str,
        message: str,
        candidate_message: str | None = None,
        invite_url: str | None = None,
    ) -> int:
        """Queue separate HR/public messages; never pass internal notes to candidate_message.

        The event key identifies a committed transition, e.g. interview ID plus
        ``started`` or a decision ID. Replaying that event cannot enqueue a
        second message for the same recipient and role.
        """
        try:
            return await self._enqueue_candidate_status(
                candidate_id,
                event_key=event_key,
                message=message,
                candidate_message=candidate_message,
                invite_url=invite_url,
            )
        except Exception:
            # Database/transport exceptions may contain connection secrets, so
            # log no exception, traceback, SQL parameters or Telegram URL.
            logger.warning("Unable to enqueue Telegram status notification.")
            return 0

    async def _enqueue_candidate_status(
        self,
        candidate_id: str,
        *,
        event_key: str,
        message: str,
        candidate_message: str | None,
        invite_url: str | None,
    ) -> int:
        recipients: list[tuple[TelegramAccountRow, str, str]] = []
        async with self._sessions() as session:
            candidate = await session.get(CandidateRow, candidate_id)
            if candidate is None:
                return 0
            position = await session.get(PositionRow, candidate.position_id)
            if position is None:
                return 0
            recruiter = await session.scalar(
                select(TelegramAccountRow).where(TelegramAccountRow.user_id == position.created_by)
            )
            if self._can_send(recruiter):
                recipients.append(
                    (
                        recruiter,
                        "hr",
                        f"Кандидат: {candidate.name}\nВакансия: {position.title}\n{message}",
                    )
                )
            if candidate_message:
                account = await self._candidate_account(session, candidate)
                if self._can_send(account):
                    public_text = f"Вакансия: {position.title}\n{candidate_message}"
                    if invite_url:
                        public_text = f"{public_text[:3000]}\n\n{invite_url}"
                    recipients.append((account, "candidate", public_text))
            queued = 0
            for account, role, text in recipients:
                key = hashlib.sha256(
                    f"{candidate_id}\0{event_key}\0{account.id}\0{role}".encode()
                ).hexdigest()
                try:
                    async with session.begin_nested():
                        session.add(
                            TelegramNotificationRow(
                                id=str(uuid4()),
                                event_key=key,
                                candidate_id=candidate_id,
                                account_id=account.id,
                                chat_id=account.chat_id,
                                recipient_role=role,
                                text=text[:4000],
                                available_at=self._now(),
                            )
                        )
                        await session.flush()
                    queued += 1
                except IntegrityError:
                    # Unique event keys also protect against concurrent enqueues.
                    continue
            await session.commit()
            return queued

    async def _candidate_account(
        self, session: AsyncSession, candidate: CandidateRow
    ) -> TelegramAccountRow | None:
        if candidate.user_id:
            return await session.scalar(
                select(TelegramAccountRow).where(TelegramAccountRow.user_id == candidate.user_id)
            )
        username = normalize_telegram_username(candidate.telegram_username)
        if not username:
            return None
        matches = list(
            await session.scalars(
                select(TelegramAccountRow).where(TelegramAccountRow.username == username).limit(2)
            )
        )
        # Telegram handles may be renamed/recycled. Ambiguous contact hints must
        # not route candidate data to one arbitrarily selected account.
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _can_send(account: TelegramAccountRow | None) -> bool:
        return bool(account and account.started and account.chat_id and account.chat_id > 0)

    async def dispatch_pending(self, *, limit: int = 20) -> int:
        """Send due messages; isolate failures and return the number delivered."""
        try:
            async with self._sessions() as session:
                ids = list(
                    await session.scalars(
                        select(TelegramNotificationRow.id)
                        .where(*self._due_conditions(self._now()))
                        .order_by(TelegramNotificationRow.available_at, TelegramNotificationRow.id)
                        .limit(max(1, min(limit, 100)))
                    )
                )
        except Exception:
            logger.warning("Unable to read Telegram notification queue.")
            return 0
        delivered = 0
        for row_id in ids:
            try:
                delivered += await self._dispatch_one(row_id)
            except Exception:
                # A worker crash leaves a short lease. A subsequent worker may
                # retry after it expires without holding up a business request.
                logger.warning("Unable to process Telegram notification queue item.")
        return delivered

    @staticmethod
    def _due_conditions(now: datetime) -> tuple:
        return (
            TelegramNotificationRow.delivered_at.is_(None),
            TelegramNotificationRow.discarded_at.is_(None),
            TelegramNotificationRow.available_at <= now,
            or_(
                TelegramNotificationRow.lease_until.is_(None),
                TelegramNotificationRow.lease_until <= now,
            ),
        )

    async def _dispatch_one(self, row_id: str) -> int:
        now = self._now()
        claim_token = str(uuid4())
        async with self._sessions.begin() as session:
            result = await session.execute(
                update(TelegramNotificationRow)
                .where(TelegramNotificationRow.id == row_id, *self._due_conditions(now))
                .values(
                    claim_token=claim_token,
                    lease_until=now + timedelta(minutes=2),
                    attempts=TelegramNotificationRow.attempts + 1,
                )
            )
            if result.rowcount != 1:
                return 0
            row = await session.get(TelegramNotificationRow, row_id)
            account = await session.get(TelegramAccountRow, row.account_id)
            if not self._can_send(account) or account.chat_id != row.chat_id:
                row.discarded_at = now
                row.last_error = "recipient_unavailable"
                row.lease_until = None
                row.claim_token = None
                return 0
            chat_id, text = row.chat_id, row.text
        try:
            await self.client.send_message(chat_id, text)
        except TelegramAPIError as error:
            await self._record_failure(row_id, claim_token, error)
            return 0
        except Exception:
            await self._record_failure(row_id, claim_token, TelegramAPIError())
            return 0
        async with self._sessions.begin() as session:
            await session.execute(
                update(TelegramNotificationRow)
                .where(
                    TelegramNotificationRow.id == row_id,
                    TelegramNotificationRow.claim_token == claim_token,
                )
                .values(
                    delivered_at=self._now(), last_error=None, lease_until=None, claim_token=None
                )
            )
        return 1

    async def _record_failure(self, row_id: str, claim_token: str, error: TelegramAPIError) -> None:
        async with self._sessions.begin() as session:
            row = await session.scalar(
                select(TelegramNotificationRow).where(
                    TelegramNotificationRow.id == row_id,
                    TelegramNotificationRow.claim_token == claim_token,
                )
            )
            if row is None:
                return
            row.last_error = f"telegram_{error.error_code}"
            row.lease_until = None
            row.claim_token = None
            if error.blocked:
                await session.execute(
                    update(TelegramAccountRow)
                    .where(TelegramAccountRow.id == row.account_id)
                    .values(started=False)
                )
            if not error.retryable or row.attempts >= self.max_attempts:
                row.discarded_at = self._now()
            else:
                delay = max(min(3600, 5 * (2 ** min(row.attempts - 1, 10))), error.retry_after or 0)
                row.available_at = self._now() + timedelta(seconds=delay)

    def _now(self) -> datetime:
        value = self._clock()
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
