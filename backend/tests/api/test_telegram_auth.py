from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from interview_api.workflow.entities import AuthSessionRow, CandidateRow, PositionRow, UserRow
from interview_api.workflow.errors import (
    WorkflowForbiddenError,
    WorkflowNotFoundError,
    WorkflowUnauthorizedError,
)
from interview_api.workflow.repository import SqlAlchemyWorkflowRepository
from interview_api.workflow.schemas import UserResponse
from interview_api.workflow.telegram_auth import TelegramAuthMixin
from interview_api.workflow.telegram_entities import TelegramAccountRow
from interview_api.workflow.telegram_routes import router


class AuthService(TelegramAuthMixin):
    def __init__(self, repository):
        self.repository = repository
        self.now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
        self.session_ttl = timedelta(days=30)
        self.telegram_bot_username = "interview_test_bot"
        self.telegram_client = None
        self.telegram_webhook_secret = None
        self.cookie_name = "signal_session"
        self.cookie_secure = False

    def _now(self):
        return self.now

    @staticmethod
    def _hash_token(raw):
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _user_response(actor):
        return UserResponse.model_validate(actor)

    async def require_actor(self, raw_token):
        if not raw_token:
            raise WorkflowUnauthorizedError()
        actor = await self.repository.resolve_auth_session(self._hash_token(raw_token), self.now)
        if actor is None:
            raise WorkflowUnauthorizedError()
        return actor


@pytest_asyncio.fixture
async def auth(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'telegram.sqlite'}",
        pool_size=1,
        max_overflow=0,
        pool_timeout=2,
    )
    repository = SqlAlchemyWorkflowRepository.from_engine(engine)
    await repository.initialize(engine)
    service = AuthService(repository)
    yield service
    await engine.dispose()


def telegram_update(payload=None, *, telegram_id=1001, username="candidate_one"):
    return {
        "update_id": 1,
        "message": {
            "text": "/start" + (f" {payload}" if payload else ""),
            "chat": {"id": telegram_id, "type": "private"},
            "from": {"id": telegram_id, "first_name": "Candidate", "username": username},
        },
    }


async def login(auth, *, role="hr", telegram_id=1001, username="candidate_one", invite=None):
    poll, response = await auth.start_telegram_login(role, invite)
    payload = parse_qs(urlsplit(response.bot_url).query)["start"][0]
    await auth.handle_telegram_update(
        telegram_update(payload, telegram_id=telegram_id, username=username)
    )
    token, result = await auth.poll_telegram_login(poll)
    assert result.status == "authenticated"
    return token, result.user


@pytest.mark.asyncio
async def test_login_needs_separate_browser_secret_and_consumes_only_once(auth):
    poll, response = await auth.start_telegram_login("hr")
    payload = parse_qs(urlsplit(response.bot_url).query)["start"][0]
    assert len(payload) <= 64
    assert payload != poll
    assert (await auth.poll_telegram_login(poll))[1].status == "pending"
    await auth.handle_telegram_update(telegram_update(payload))
    assert (await auth.poll_telegram_login(payload))[1].status == "expired"
    token, result = await auth.poll_telegram_login(poll)
    assert result.status == "authenticated"
    assert result.user.role == "hr"
    assert (await auth.poll_telegram_login(poll))[1].status == "expired"
    resumed_token, resumed = await auth.poll_telegram_login(poll, token)
    assert resumed_token is None
    assert resumed.status == "authenticated"
    async with auth.repository._sessions() as session:
        assert await session.scalar(select(func.count()).select_from(AuthSessionRow)) == 1


@pytest.mark.asyncio
async def test_expired_challenge_cannot_authorize(auth):
    poll, response = await auth.start_telegram_login("hr")
    payload = parse_qs(urlsplit(response.bot_url).query)["start"][0]
    auth.now += timedelta(minutes=6)
    await auth.handle_telegram_update(telegram_update(payload))
    assert (await auth.poll_telegram_login(poll))[1].status == "expired"
    async with auth.repository._sessions() as session:
        assert await session.scalar(select(func.count()).select_from(AuthSessionRow)) == 0


@pytest.mark.asyncio
async def test_duplicate_bot_starts_keep_identity_and_first_approval(auth):
    poll, response = await auth.start_telegram_login("candidate")
    payload = parse_qs(urlsplit(response.bot_url).query)["start"][0]
    await auth.handle_telegram_update(telegram_update(payload))
    await auth.handle_telegram_update(telegram_update(payload, telegram_id=1002))
    token, result = await auth.poll_telegram_login(poll)
    account = await auth.repository.get_telegram_account(result.user.id)
    assert account.telegram_id == 1001
    await auth.handle_telegram_update(telegram_update(username="renamed_user"))
    assert (await auth.repository.get_telegram_account(result.user.id)).username == "renamed_user"
    second_token, second_user = await login(auth, username="renamed_user")
    assert second_token != token
    assert second_user.id == result.user.id
    async with auth.repository._sessions() as session:
        assert await session.scalar(select(func.count()).select_from(TelegramAccountRow)) == 2


@pytest.mark.asyncio
async def test_simultaneous_poll_consumption_creates_one_session(auth):
    poll, response = await auth.start_telegram_login("hr")
    payload = parse_qs(urlsplit(response.bot_url).query)["start"][0]
    await auth.handle_telegram_update(telegram_update(payload))
    results = await asyncio.gather(auth.poll_telegram_login(poll), auth.poll_telegram_login(poll))
    assert sum(token is not None for token, _ in results) == 1
    async with auth.repository._sessions() as session:
        assert await session.scalar(select(func.count()).select_from(AuthSessionRow)) == 1


@pytest.mark.asyncio
async def test_same_account_switches_roles_and_logout_revokes_database_session(auth):
    original, user = await login(auth, role="hr")
    token, result = await auth.switch_telegram_role(original, "candidate")
    assert result.user.id == user.id
    assert result.user.role == "candidate"
    with pytest.raises(WorkflowUnauthorizedError):
        await auth.require_actor(original)
    token, result = await auth.switch_telegram_role(token, "hr")
    assert result.user.id == user.id
    assert result.user.role == "hr"
    async with auth.repository._sessions() as session:
        # Session preferences never rewrite the durable user record.
        assert (await session.get(UserRow, user.id)).role == "candidate"
    await auth.logout_telegram_session(token)
    with pytest.raises(WorkflowUnauthorizedError):
        await auth.require_actor(token)


@pytest.mark.asyncio
async def test_blocked_bot_notifications_do_not_remove_account_roles(auth):
    token, user = await login(auth)
    async with auth.repository._sessions.begin() as session:
        account = await session.scalar(
            select(TelegramAccountRow).where(TelegramAccountRow.user_id == user.id)
        )
        account.started = False
    _, result = await auth.switch_telegram_role(token, "candidate")
    assert result.user.telegram_connected is True
    assert set(result.user.roles) == {"hr", "candidate"}


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["group", "mismatched_sender", "bot_sender"])
async def test_bot_updates_must_come_from_matching_private_human_sender(auth, invalid):
    update = telegram_update()
    if invalid == "group":
        update["message"]["chat"]["type"] = "group"
    elif invalid == "mismatched_sender":
        update["message"]["chat"]["id"] = 9999
    else:
        update["message"]["from"]["is_bot"] = True
    await auth.handle_telegram_update(update)
    async with auth.repository._sessions() as session:
        assert await session.scalar(select(func.count()).select_from(TelegramAccountRow)) == 0


async def create_invite(auth, hr_id, username=None):
    async with auth.repository._sessions.begin() as session:
        session.add(
            PositionRow(
                id="position-one",
                created_by=hr_id,
                title="Developer",
                question_count=1,
                duration_minutes=10,
                vacancy_object_key="vacancy",
                vacancy_filename="vacancy.txt",
                vacancy_content_type="text/plain",
                vacancy_text="Developer",
            )
        )
        await session.flush()
        session.add(
            CandidateRow(
                id="candidate-one",
                position_id="position-one",
                name="Candidate",
                resume_object_key="resume",
                resume_filename="resume.txt",
                resume_content_type="text/plain",
                resume_text="A resume",
                telegram_username=username,
            )
        )
    raw_invite = "unguessable-test-invitation"
    await auth.repository.upsert_invite_and_interview(
        candidate_id="candidate-one",
        token_hash=auth._hash_token(raw_invite),
        expires_at=auth.now + timedelta(days=1),
    )
    return raw_invite


@pytest.mark.asyncio
async def test_invite_claim_checks_username_and_durable_identity(auth):
    token, user = await login(auth, role="hr", username="candidate_one")
    invite = await create_invite(auth, user.id, username="candidate_one")
    other_token, _ = await login(auth, telegram_id=1002, username="candidate_two")
    with pytest.raises(WorkflowForbiddenError):
        await auth.claim_telegram_invite(await auth.require_actor(other_token), invite)
    candidate = await auth.claim_telegram_invite(await auth.require_actor(token), invite)
    assert candidate.user_id == user.id
    await auth.handle_telegram_update(telegram_update(username="renamed_user"))
    assert (
        await auth.claim_telegram_invite(await auth.require_actor(token), invite)
    ).id == candidate.id
    with pytest.raises(WorkflowForbiddenError):
        await auth.claim_telegram_invite(await auth.require_actor(other_token), invite)


@pytest.mark.asyncio
async def test_login_authenticates_before_invitation_selects_candidate(auth):
    _, user = await login(auth, role="hr")
    invite = await create_invite(auth, user.id)
    token, candidate_user = await login(auth, invite=invite)
    assert candidate_user.id == user.id
    assert candidate_user.role == "candidate"
    assert candidate_user.candidate_id is None
    actor = await auth.require_actor(token)
    candidate = await auth.claim_telegram_invite(actor, invite)
    token, session = await auth.session_for_telegram_actor(
        actor, role="candidate", candidate_id=candidate.id, previous_token=token
    )
    assert session.user.candidate_id == "candidate-one"
    assert (await auth.require_actor(token)).candidate_id == "candidate-one"


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_invite", ["wrong_username", "expired"])
async def test_invite_rejection_keeps_authenticated_session_and_does_not_bind(auth, invalid_invite):
    _, hr_user = await login(auth, role="hr")
    invite = await create_invite(auth, hr_user.id, username="candidate_one")
    if invalid_invite == "expired":
        auth.now += timedelta(days=2)
    token, user = await login(auth, telegram_id=1002, username="candidate_two", invite=invite)
    assert user.role == "candidate"
    actor = await auth.require_actor(token)
    expected = WorkflowNotFoundError if invalid_invite == "expired" else WorkflowForbiddenError
    with pytest.raises(expected):
        await auth.claim_telegram_invite(actor, invite)
    assert (await auth.require_actor(token)).id == user.id
    assert (await auth.repository.get_candidate("candidate-one")).user_id is None


@pytest.mark.asyncio
async def test_auth_routes_protect_webhook_and_cookie_origins(auth):
    app = FastAPI()
    app.state.workflow_service = auth
    app.state.settings = SimpleNamespace(cors_origin_list=["http://frontend.test"])
    app.include_router(router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://backend.test"
    ) as client:
        response = await client.post(
            "/api/v1/auth/telegram/start",
            json={"role": "hr"},
            headers={"Origin": "http://attacker.test"},
        )
        assert response.status_code == 403
        response = await client.post(
            "/api/v1/auth/telegram/start",
            json={"role": "hr"},
            headers={"Origin": "http://frontend.test"},
        )
        assert response.status_code == 200
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=lax" in response.headers["set-cookie"]
        assert response.headers["cache-control"] == "no-store"
        assert (await client.get("/api/v1/auth/telegram/status")).json()["status"] == "pending"
        response = await client.post("/api/v1/telegram/webhook", json=telegram_update())
        assert response.status_code == 404
        auth.telegram_webhook_secret = "test-webhook-secret"
        response = await client.post("/api/v1/telegram/webhook", json=telegram_update())
        assert response.status_code == 401
        response = await client.post(
            "/api/v1/telegram/webhook",
            json=telegram_update(),
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-webhook-secret"},
        )
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_switching_roles_preserves_selected_interview_with_multiple_candidates(auth):
    token, user = await login(auth)
    invite = await create_invite(auth, user.id)
    actor = await auth.require_actor(token)
    selected = await auth.claim_telegram_invite(actor, invite)
    token, _ = await auth.session_for_telegram_actor(
        actor, "candidate", candidate_id=selected.id, previous_token=token
    )
    async with auth.repository._sessions.begin() as session:
        session.add(
            CandidateRow(
                id="candidate-newer",
                position_id="position-one",
                user_id=user.id,
                name="Candidate",
                resume_object_key="newer",
                resume_filename="resume.txt",
                resume_content_type="text/plain",
                resume_text="Another application",
                created_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
    token, hr = await auth.switch_telegram_role(token, "hr")
    assert hr.user.id == user.id
    token, candidate = await auth.switch_telegram_role(token, "candidate")
    assert candidate.user.candidate_id == selected.id
    assert (await auth.require_actor(token)).candidate_id == selected.id
