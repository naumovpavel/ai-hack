import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from interview_api.workflow.entities import CandidateRow, PositionRow, UserRow, WorkflowBase
from interview_api.workflow.telegram_client import TelegramAPIError
from interview_api.workflow.telegram_entities import TelegramAccountRow
from interview_api.workflow.telegram_notification_entities import TelegramNotificationRow
from interview_api.workflow.telegram_notifications import TelegramNotificationService


class FakeClient:
    def __init__(self):
        self.sent = []
        self.failure = None

    async def send_message(self, chat_id, text):
        if self.failure:
            raise self.failure
        self.sent.append((chat_id, text))
        return {"message_id": len(self.sent)}


@pytest_asyncio.fixture
async def notifications(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'notifications.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(WorkflowBase.metadata.create_all)
    async with sessions.begin() as session:
        session.add_all(
            [
                UserRow(id="hr", name="HR", role="hr"),
                UserRow(id="user", name="Candidate", role="candidate"),
                TelegramAccountRow(
                    id="hr-tg",
                    user_id="hr",
                    telegram_id=11,
                    chat_id=11,
                    username="recruiter",
                    started=True,
                    first_name="HR",
                    last_name="",
                ),
                TelegramAccountRow(
                    id="user-tg",
                    user_id="user",
                    telegram_id=22,
                    chat_id=22,
                    username="candidate",
                    started=True,
                    first_name="User",
                    last_name="",
                ),
                PositionRow(
                    id="position",
                    created_by="hr",
                    title="Developer",
                    question_count=2,
                    duration_minutes=20,
                    vacancy_object_key="vacancy",
                    vacancy_filename="v.txt",
                    vacancy_content_type="text/plain",
                    vacancy_text="vacancy",
                ),
                CandidateRow(
                    id="candidate",
                    position_id="position",
                    name="Alice",
                    user_id=None,
                    telegram_username="candidate",
                    resume_object_key="resume",
                    resume_filename="r.txt",
                    resume_content_type="text/plain",
                    resume_text="",
                ),
            ]
        )
    client = FakeClient()
    current = [datetime(2026, 9, 5, tzinfo=UTC)]
    service = TelegramNotificationService(sessions, client, clock=lambda: current[0])
    yield service, sessions, client, current
    await engine.dispose()


@pytest.mark.asyncio
async def test_deduplicates_queues_and_delivers_to_both_roles(notifications):
    service, sessions, client, _ = notifications
    args = {
        "event_key": "invite-1",
        "message": "Приглашение создано",
        "candidate_message": "Вы приглашены",
        "invite_url": "https://app.test/invite/token",
    }
    assert await service.candidate_status("candidate", **args) == 2
    assert await service.candidate_status("candidate", **args) == 0
    assert client.sent == []
    assert await service.dispatch_pending() == 2
    assert await service.dispatch_pending() == 0
    assert {chat_id for chat_id, text in client.sent} == {11, 22}
    public = next(text for chat_id, text in client.sent if chat_id == 22)
    assert "https://app.test/invite/token" in public
    assert "Приглашение создано" not in public


@pytest.mark.asyncio
async def test_never_sends_to_username_without_start(notifications):
    service, sessions, client, _ = notifications
    async with sessions.begin() as session:
        row = await session.get(TelegramAccountRow, "user-tg")
        row.started = False
    assert (
        await service.candidate_status(
            "candidate", event_key="e1", message="HR update", candidate_message="Candidate update"
        )
        == 1
    )
    assert await service.dispatch_pending() == 1
    assert [chat_id for chat_id, text in client.sent] == [11]


@pytest.mark.asyncio
async def test_linked_user_wins_over_old_resume_handle(notifications):
    service, sessions, client, _ = notifications
    async with sessions.begin() as session:
        candidate = await session.get(CandidateRow, "candidate")
        candidate.user_id = "user"
        candidate.telegram_username = "recruiter"
    await service.candidate_status(
        "candidate", event_key="e1", message="HR update", candidate_message="Candidate update"
    )
    assert await service.dispatch_pending() == 2
    assert "Candidate update" in next(text for chat_id, text in client.sent if chat_id == 22)


@pytest.mark.asyncio
async def test_recipient_is_rechecked_after_enqueue(notifications):
    service, sessions, client, _ = notifications
    await service.candidate_status("candidate", event_key="e1", message="HR update")
    async with sessions.begin() as session:
        row = await session.get(TelegramAccountRow, "hr-tg")
        row.started = False
    assert await service.dispatch_pending() == 0
    assert client.sent == []


@pytest.mark.asyncio
async def test_rate_limit_retries_after_requested_delay(notifications):
    service, sessions, client, current = notifications
    await service.candidate_status("candidate", event_key="e1", message="HR update")
    client.failure = TelegramAPIError(429, retry_after=45)
    assert await service.dispatch_pending() == 0
    current[0] += timedelta(seconds=44)
    assert await service.dispatch_pending() == 0
    client.failure = None
    current[0] += timedelta(seconds=1)
    assert await service.dispatch_pending() == 1
    assert len(client.sent) == 1


@pytest.mark.asyncio
async def test_blocked_bot_disables_recipient(notifications):
    service, sessions, client, _ = notifications
    await service.candidate_status("candidate", event_key="e1", message="HR update")
    client.failure = TelegramAPIError(403)
    assert await service.dispatch_pending() == 0
    async with sessions() as session:
        account = await session.get(TelegramAccountRow, "hr-tg")
        row = await session.scalar(select(TelegramNotificationRow))
        assert account.started is False
        assert row.discarded_at is not None
        assert row.last_error == "telegram_403"
    assert await service.candidate_status("candidate", event_key="e2", message="HR update") == 0


@pytest.mark.asyncio
async def test_database_failure_isolated_from_business_action(notifications, monkeypatch):
    service, _, _, _ = notifications

    async def fail(*args, **kwargs):
        raise RuntimeError("sensitive database connection details")

    monkeypatch.setattr(service, "_enqueue_candidate_status", fail)
    assert await service.candidate_status("candidate", event_key="e1", message="HR update") == 0


@pytest.mark.asyncio
async def test_ambiguous_resume_handle_is_not_routed(notifications):
    service, sessions, client, _ = notifications
    async with sessions.begin() as session:
        account = await session.get(TelegramAccountRow, "hr-tg")
        account.username = "candidate"
    assert (
        await service.candidate_status(
            "candidate", event_key="e1", message="HR update", candidate_message="Candidate update"
        )
        == 1
    )
    assert await service.dispatch_pending() == 1
    assert [chat_id for chat_id, text in client.sent] == [11]


@pytest.mark.asyncio
async def test_overlapping_workers_claim_each_message_once(notifications):
    service, sessions, client, _ = notifications
    await service.candidate_status("candidate", event_key="e1", message="HR update")
    second = TelegramNotificationService(sessions, client, clock=service._clock)
    assert sum(await asyncio.gather(service.dispatch_pending(), second.dispatch_pending())) == 1
    assert len(client.sent) == 1


@pytest.mark.asyncio
async def test_expired_worker_lease_is_recovered(notifications):
    service, sessions, client, current = notifications
    await service.candidate_status("candidate", event_key="e1", message="HR update")
    async with sessions.begin() as session:
        row = await session.scalar(select(TelegramNotificationRow))
        row.lease_until = current[0] + timedelta(seconds=60)
        row.claim_token = "old-worker"
    assert await service.dispatch_pending() == 0
    current[0] += timedelta(seconds=61)
    assert await service.dispatch_pending() == 1
    assert len(client.sent) == 1


@pytest.mark.asyncio
async def test_retries_are_bounded(notifications):
    service, sessions, client, current = notifications
    service.max_attempts = 2
    client.failure = TelegramAPIError(500)
    await service.candidate_status("candidate", event_key="e1", message="HR update")
    assert await service.dispatch_pending() == 0
    current[0] += timedelta(seconds=6)
    assert await service.dispatch_pending() == 0
    client.failure = None
    current[0] += timedelta(hours=3)
    assert await service.dispatch_pending() == 0
    async with sessions() as session:
        row = await session.scalar(select(TelegramNotificationRow))
        assert row.attempts == 2
        assert row.discarded_at is not None
