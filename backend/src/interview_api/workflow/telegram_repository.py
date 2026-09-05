from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from interview_api.workflow.entities import AuthSessionRow, CandidateRow, InviteRow, UserRow
from interview_api.workflow.errors import (
    WorkflowForbiddenError,
    WorkflowNotFoundError,
    WorkflowUnauthorizedError,
)
from interview_api.workflow.telegram_entities import TelegramAccountRow, TelegramLoginChallengeRow


def _new_id() -> str:
    return str(uuid4())


def decorate_telegram_actor(
    user: UserRow,
    account: TelegramAccountRow,
    *,
    role: str,
    candidate_id: str | None,
) -> UserRow:
    """Apply session preferences only after the user has left its ORM session."""
    user.role = role
    user.candidate_id = candidate_id
    user.telegram_username = account.username
    user.telegram_connected = True
    user.roles = ["hr", "candidate"]
    return user


class TelegramRepositoryMixin:
    """Requires the repository's async SQLAlchemy session factory, ``_sessions``."""

    async def get_telegram_account(self, user_id: str) -> TelegramAccountRow | None:
        async with self._sessions() as session:
            return await session.scalar(
                select(TelegramAccountRow).where(TelegramAccountRow.user_id == user_id)
            )

    async def register_telegram_account(
        self,
        *,
        telegram_id: int,
        chat_id: int,
        username: str | None,
        first_name: str,
        last_name: str,
        now: datetime,
    ) -> TelegramAccountRow:
        # Unique telegram_id/user_id constraints are the final guard against
        # concurrent webhook workers creating duplicate application identities.
        for attempt in range(2):
            try:
                async with self._sessions.begin() as session:
                    account = await session.scalar(
                        select(TelegramAccountRow)
                        .where(TelegramAccountRow.telegram_id == telegram_id)
                        .with_for_update()
                    )
                    if account is None:
                        user = UserRow(
                            id=_new_id(),
                            role="candidate",
                            name=(f"{first_name} {last_name}".strip() or "Пользователь Telegram")[
                                :200
                            ],
                        )
                        session.add(user)
                        await session.flush()
                        account = TelegramAccountRow(
                            id=_new_id(), user_id=user.id, telegram_id=telegram_id
                        )
                        session.add(account)
                    # Telegram usernames can be renamed and recycled. A newly
                    # observed owner supersedes any stale cached username.
                    if username:
                        await session.execute(
                            update(TelegramAccountRow)
                            .where(
                                TelegramAccountRow.username == username,
                                TelegramAccountRow.telegram_id != telegram_id,
                            )
                            .values(username=None)
                        )
                    account.chat_id = chat_id
                    account.username = username
                    account.first_name = first_name
                    account.last_name = last_name
                    account.started = True
                    account.updated_at = now
                return account
            except IntegrityError:
                if attempt:
                    raise
        raise RuntimeError("Telegram account registration did not complete.")

    async def create_telegram_challenge(
        self,
        *,
        start_token_hash: str,
        poll_token_hash: str,
        role: str,
        invite_token_hash: str | None,
        expires_at: datetime,
    ) -> TelegramLoginChallengeRow:
        row = TelegramLoginChallengeRow(
            id=_new_id(),
            start_token_hash=start_token_hash,
            poll_token_hash=poll_token_hash,
            role=role,
            invite_token_hash=invite_token_hash,
            expires_at=expires_at,
        )
        async with self._sessions.begin() as session:
            session.add(row)
        return row

    async def get_telegram_challenge(
        self, poll_token_hash: str
    ) -> TelegramLoginChallengeRow | None:
        async with self._sessions() as session:
            return await session.scalar(
                select(TelegramLoginChallengeRow).where(
                    TelegramLoginChallengeRow.poll_token_hash == poll_token_hash
                )
            )

    async def approve_telegram_challenge(
        self, *, start_token_hash: str, user_id: str, now: datetime
    ) -> bool:
        async with self._sessions.begin() as session:
            result = await session.execute(
                update(TelegramLoginChallengeRow)
                .where(
                    TelegramLoginChallengeRow.start_token_hash == start_token_hash,
                    TelegramLoginChallengeRow.expires_at > now,
                    TelegramLoginChallengeRow.consumed_at.is_(None),
                    TelegramLoginChallengeRow.approved_user_id.is_(None),
                )
                .values(approved_user_id=user_id)
            )
            return bool(result.rowcount)

    @staticmethod
    async def _claim_telegram_invite_in_session(
        session: AsyncSession,
        *,
        account: TelegramAccountRow,
        invite_token_hash: str,
        now: datetime,
    ) -> CandidateRow:
        candidate = await session.scalar(
            select(CandidateRow)
            .join(InviteRow, InviteRow.candidate_id == CandidateRow.id)
            .where(
                InviteRow.token_hash == invite_token_hash,
                InviteRow.expires_at > now,
                InviteRow.revoked_at.is_(None),
            )
            .with_for_update()
        )
        if candidate is None:
            raise WorkflowNotFoundError("Interview invitation is invalid or expired.")
        if candidate.user_id is not None and candidate.user_id != account.user_id:
            raise WorkflowForbiddenError("This interview belongs to another Telegram account.")
        expected_username = (candidate.telegram_username or "").lstrip("@").lower()
        if (
            candidate.user_id is None
            and expected_username
            and expected_username != account.username
        ):
            raise WorkflowForbiddenError(
                "Sign in with the Telegram account specified in your resume.",
                details={"reason": "telegram_username_mismatch"},
            )
        # Conditional update also protects SQLite, which ignores FOR UPDATE.
        claimed = await session.execute(
            update(CandidateRow)
            .where(
                CandidateRow.id == candidate.id,
                (CandidateRow.user_id.is_(None)) | (CandidateRow.user_id == account.user_id),
            )
            .values(user_id=account.user_id)
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount != 1:
            raise WorkflowForbiddenError("This interview belongs to another Telegram account.")
        await session.refresh(candidate)
        return candidate

    async def claim_telegram_candidate(
        self, *, user_id: str, invite_token_hash: str, now: datetime
    ) -> CandidateRow:
        async with self._sessions.begin() as session:
            account = await session.scalar(
                select(TelegramAccountRow)
                .where(TelegramAccountRow.user_id == user_id)
                .with_for_update()
            )
            if account is None:
                raise WorkflowForbiddenError("Sign in through Telegram to open this interview.")
            return await self._claim_telegram_invite_in_session(
                session, account=account, invite_token_hash=invite_token_hash, now=now
            )

    @staticmethod
    async def _telegram_candidate_selection(
        session: AsyncSession, *, user_id: str, role: str, candidate_id: str | None
    ) -> str | None:
        if role != "candidate" and candidate_id is None:
            return None
        query = select(CandidateRow.id).where(CandidateRow.user_id == user_id)
        if candidate_id:
            query = query.where(CandidateRow.id == candidate_id)
        selected = await session.scalar(
            query.order_by(CandidateRow.created_at.desc(), CandidateRow.id).limit(1)
        )
        if candidate_id and selected is None:
            raise WorkflowForbiddenError("This interview belongs to another Telegram account.")
        return selected

    async def consume_telegram_challenge(
        self,
        *,
        poll_token_hash: str,
        session_token_hash: str,
        session_expires_at: datetime,
        now: datetime,
    ) -> UserRow | None:
        async with self._sessions.begin() as session:
            result = await session.execute(
                update(TelegramLoginChallengeRow)
                .where(
                    TelegramLoginChallengeRow.poll_token_hash == poll_token_hash,
                    TelegramLoginChallengeRow.approved_user_id.is_not(None),
                    TelegramLoginChallengeRow.consumed_at.is_(None),
                    TelegramLoginChallengeRow.expires_at > now,
                )
                .values(consumed_at=now)
                .returning(TelegramLoginChallengeRow)
            )
            challenge = result.scalar_one_or_none()
            if challenge is None:
                return None
            account = await session.scalar(
                select(TelegramAccountRow)
                .where(TelegramAccountRow.user_id == challenge.approved_user_id)
                .with_for_update()
            )
            if account is None:
                raise WorkflowUnauthorizedError("Telegram identity is no longer available.")
            user = await session.get(UserRow, account.user_id)
            if user is None:
                raise WorkflowUnauthorizedError()
            role = challenge.role
            # Authenticate independently from invitation authorization. The browser
            # resolves its invitation after login, so an expired or mismatched
            # invitation never traps the user outside their account.
            candidate_id = await self._telegram_candidate_selection(
                session, user_id=user.id, role=role, candidate_id=None
            )
            session.add(
                AuthSessionRow(
                    id=_new_id(),
                    user_id=user.id,
                    token_hash=session_token_hash,
                    expires_at=session_expires_at,
                    active_role=role,
                    candidate_id=candidate_id,
                )
            )
        return decorate_telegram_actor(user, account, role=role, candidate_id=candidate_id)

    async def create_telegram_session(
        self,
        *,
        user_id: str,
        role: str,
        candidate_id: str | None,
        token_hash: str,
        expires_at: datetime,
        previous_token_hash: str | None = None,
    ) -> UserRow:
        async with self._sessions.begin() as session:
            account = await session.scalar(
                select(TelegramAccountRow).where(TelegramAccountRow.user_id == user_id)
            )
            user = await session.get(UserRow, user_id)
            if account is None or user is None:
                raise WorkflowUnauthorizedError("Sign in through Telegram to switch roles.")
            selected = await self._telegram_candidate_selection(
                session, user_id=user_id, role=role, candidate_id=candidate_id
            )
            if previous_token_hash:
                await session.execute(
                    delete(AuthSessionRow).where(
                        AuthSessionRow.token_hash == previous_token_hash,
                        AuthSessionRow.user_id == user_id,
                    )
                )
            session.add(
                AuthSessionRow(
                    id=_new_id(),
                    user_id=user_id,
                    token_hash=token_hash,
                    expires_at=expires_at,
                    active_role=role,
                    candidate_id=selected,
                )
            )
        return decorate_telegram_actor(user, account, role=role, candidate_id=selected)

    async def revoke_auth_session(self, token_hash: str) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                delete(AuthSessionRow).where(AuthSessionRow.token_hash == token_hash)
            )
