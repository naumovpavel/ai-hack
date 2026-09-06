from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from test_hiring import assert_ok, candidate_draft, make_plan, sign_in_telegram

from interview_api.config import Settings
from interview_api.main import create_app
from interview_api.workflow.ai import DeterministicWorkflowAI
from interview_api.workflow.entities import (
    AnalysisItemRow,
    AnalysisRow,
    AnswerRow,
    AuthSessionRow,
    CandidateRow,
    DecisionRow,
    HiringResourceRow,
    HumanReviewRow,
    InterviewRow,
    InviteRow,
    MediaAssetRow,
    PositionRow,
    QuestionRow,
    ReviewProgressRow,
    UserRow,
)
from interview_api.workflow.errors import WorkflowNotFoundError
from interview_api.workflow.hiring_templates import template_id
from interview_api.workflow.practice_entities import PracticeSessionRow
from interview_api.workflow.repository import SqlAlchemyWorkflowRepository
from interview_api.workflow.service import WorkflowService
from interview_api.workflow.storage import MemoryObjectStorage
from interview_api.workflow.telegram_notification_entities import TelegramNotificationRow


@pytest.fixture
def deletion_client() -> Iterator[tuple[TestClient, WorkflowService]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    service = WorkflowService(
        repository=SqlAlchemyWorkflowRepository.from_engine(engine),
        storage=MemoryObjectStorage(),
        ai=DeterministicWorkflowAI(),
        clock=lambda: datetime(2026, 9, 5, tzinfo=UTC),
    )
    app = create_app(
        settings=Settings(app_env="test", demo_auth_enabled=True, _env_file=None),
        workflow_service=service,
        workflow_engine=engine,
    )
    with TestClient(app) as client:
        assert_ok(client.post("/api/v1/dev/session", json={"userId": "hr-demo"}))
        yield client, service
    asyncio.run(engine.dispose())


def add_candidate(client, plan):
    draft = candidate_draft(client, plan)
    return draft, assert_ok(
        client.post(
            f"/api/v1/interview-plans/{plan['id']}/candidates",
            json=draft,
        )
    )


def other_plan(client, vacancy, plan):
    fields = (
        "templateId",
        "questions",
        "durationMinutes",
        "maxFollowUpQuestions",
        "maxPersonalizedQuestions",
    )
    return assert_ok(
        client.post(
            f"/api/v1/vacancies/{vacancy['id']}/interviews",
            json={key: plan[key] for key in fields},
        )
    )


@pytest.mark.parametrize("kind", ["candidate", "interview_plan", "vacancy"])
def test_delete_cascades_owned_data_with_foreign_keys_and_preserves_accounts(deletion_client, kind):
    client, service = deletion_client
    vacancy, plan = make_plan(client)
    draft, approval = add_candidate(client, plan)
    candidate_id, interview_id = approval["candidateId"], approval["interviewId"]
    second_plan = other_plan(client, vacancy, plan)
    _, sibling = add_candidate(client, second_plan)
    other_vacancy, unrelated_plan = make_plan(client)
    _, unrelated = add_candidate(client, unrelated_plan)

    sign_in_telegram(client, service)
    assert_ok(client.post("/api/v1/invites/resolve", json={"token": approval["inviteToken"]}))
    active = assert_ok(
        client.post(
            f"/api/v1/interviews/{interview_id}/start",
            json={"consentToRecording": True},
        )
    )
    candidate_cookie = client.cookies.get(service.cookie_name, domain="testserver.local")
    candidate_actor = assert_ok(client.get("/api/v1/session"))
    question_id = active["currentQuestion"]["id"]

    async def seed_related():
        async with service.repository._sessions.begin() as session:
            assert await session.scalar(text("PRAGMA foreign_keys")) == 1
            account = await service.repository.get_telegram_account(candidate_actor["id"])
            session.add(
                AnswerRow(
                    id="answer",
                    interview_id=interview_id,
                    question_id=question_id,
                    transcript="Test answer",
                )
            )
            session.add(
                AnalysisRow(
                    id="analysis",
                    candidate_id=candidate_id,
                    version="test",
                    score=5,
                    confidence=0.5,
                    recommendation="next_stage",
                    summary="Test",
                )
            )
            await session.flush()
            session.add(
                AnalysisItemRow(
                    id="item",
                    analysis_id="analysis",
                    order_index=0,
                    kind="answer",
                    title="Test",
                    body="Test",
                    question_id=question_id,
                )
            )
            session.add(HumanReviewRow(id="review", analysis_id="analysis", user_id="hr-demo"))
            session.add(
                DecisionRow(
                    id="decision",
                    candidate_id=candidate_id,
                    decided_by="hr-demo",
                    status="next_stage",
                )
            )
            session.add(
                MediaAssetRow(
                    id="media",
                    candidate_id=candidate_id,
                    interview_id=interview_id,
                    answer_id="answer",
                    question_id=question_id,
                    kind="audio",
                    object_key=f"candidates/{candidate_id}/audio.webm",
                    filename="audio.webm",
                    content_type="audio/webm",
                    size_bytes=4,
                )
            )
            session.add(
                PracticeSessionRow(
                    id="practice",
                    candidate_id=candidate_id,
                    interview_id=interview_id,
                    owner_user_id=candidate_actor["id"],
                )
            )
            session.add(
                TelegramNotificationRow(
                    id="notification",
                    event_key="test",
                    candidate_id=candidate_id,
                    account_id=account.id,
                    chat_id=1001,
                    recipient_role="candidate",
                    text="Test",
                )
            )
            await session.flush()
            session.add(
                ReviewProgressRow(id="progress", analysis_item_id="item", user_id="hr-demo")
            )
        for key in (
            f"candidates/{candidate_id}/audio.webm",
            f"candidates/{candidate_id}/practice/practice/video.webm",
        ):
            await service.storage.put_bytes(key, b"test", content_type="video/webm")
        await service.storage.put_bytes(
            "shared/company.pdf", b"company", content_type="application/pdf"
        )
        return (await service.repository.get_candidate(candidate_id)).resume_object_key

    resume_key = asyncio.run(seed_related())
    assert_ok(client.post("/api/v1/dev/session", json={"userId": "hr-demo"}))
    path = {
        "candidate": f"candidates/{candidate_id}",
        "interview_plan": f"interview-plans/{plan['id']}",
        "vacancy": f"vacancies/{vacancy['id']}",
    }[kind]
    response = client.delete(f"/api/v1/{path}")
    assert response.status_code == 204, response.text
    assert client.delete(f"/api/v1/{path}").status_code == 404
    assert client.get(f"/api/v1/candidates/{candidate_id}").status_code == 404
    assert client.get(f"/api/v1/candidates/{unrelated['candidateId']}").status_code == 200
    assert client.get(f"/api/v1/vacancies/{other_vacancy['id']}").status_code == 200
    assert client.get(f"/api/v1/candidates/{sibling['candidateId']}").status_code == (
        404 if kind == "vacancy" else 200
    )
    assert (
        client.post(f"/api/v1/interview-plans/{plan['id']}/candidates", json=draft).status_code
        == 404
    )
    assert resume_key not in service.storage.objects
    assert not any(key.startswith(f"candidates/{candidate_id}/") for key in service.storage.objects)
    assert "shared/company.pdf" in service.storage.objects

    async def assert_deleted():
        async with service.repository._sessions() as session:
            for table in (
                AnswerRow,
                AnalysisRow,
                AnalysisItemRow,
                HumanReviewRow,
                DecisionRow,
                MediaAssetRow,
                ReviewProgressRow,
                TelegramNotificationRow,
                PracticeSessionRow,
            ):
                assert list(await session.scalars(select(table))) == [], table.__name__
            assert await session.get(CandidateRow, candidate_id) is None
            assert await session.get(InterviewRow, interview_id) is None
            assert (
                await session.scalar(
                    select(InviteRow).where(InviteRow.candidate_id == candidate_id)
                )
                is None
            )
            assert (
                await session.scalar(
                    select(QuestionRow).where(QuestionRow.candidate_id == candidate_id)
                )
                is None
            )
            assert await session.get(UserRow, candidate_actor["id"]) is not None
            assert (
                await session.scalar(select(UserRow).where(UserRow.candidate_id == candidate_id))
                is None
            )
            assert (
                await session.scalar(
                    select(AuthSessionRow).where(AuthSessionRow.candidate_id == candidate_id)
                )
                is None
            )
            assert await session.get(HiringResourceRow, draft["draftId"]) is None
            saved_vacancy = await session.get(PositionRow, vacancy["id"])
            assert (saved_vacancy is None) == (kind == "vacancy")
            assert list(await session.execute(text("PRAGMA foreign_key_check"))) == []
        # An in-flight analysis result cannot recreate a deleted candidate's data.
        analysis = await service.ai.analyze(
            vacancy_text="Test", requirements=[], questions_and_answers=[]
        )
        with pytest.raises(WorkflowNotFoundError):
            await service.repository.replace_analysis(candidate_id=candidate_id, draft=analysis)

    asyncio.run(assert_deleted())
    client.cookies.clear()
    client.cookies.set(service.cookie_name, candidate_cookie)
    assert client.get("/api/v1/session").status_code == 200
    assert client.get(f"/api/v1/interviews/{interview_id}/state").status_code in (403, 404)
    assert (
        client.post("/api/v1/invites/resolve", json={"token": approval["inviteToken"]}).status_code
        == 404
    )


@pytest.mark.parametrize("actor", ["anonymous", "candidate", "other_hr"])
def test_deletion_requires_owner_and_hr_role(deletion_client, actor):
    client, service = deletion_client
    vacancy, plan = make_plan(client)
    _, approval = add_candidate(client, plan)
    if actor == "anonymous":
        client.cookies.clear()
        expected = 401
    elif actor == "candidate":
        sign_in_telegram(client, service)
        expected = 403
    else:

        async def create_other_hr():
            async with service.repository._sessions.begin() as session:
                session.add(UserRow(id="other-hr", role="hr", name="Other"))

        asyncio.run(create_other_hr())
        assert_ok(client.post("/api/v1/dev/session", json={"userId": "other-hr"}))
        expected = 404
    for path in (
        f"vacancies/{vacancy['id']}",
        f"interview-plans/{plan['id']}",
        f"candidates/{approval['candidateId']}",
    ):
        response = client.delete(f"/api/v1/{path}")
        assert response.status_code == expected, response.text
    assert_ok(client.post("/api/v1/dev/session", json={"userId": "hr-demo"}))
    assert client.get(f"/api/v1/candidates/{approval['candidateId']}").status_code == 200


def test_storage_failure_does_not_restore_deleted_invitation(deletion_client, monkeypatch):
    client, service = deletion_client
    _, plan = make_plan(client)
    _, approval = add_candidate(client, plan)

    async def unavailable(**_kwargs):
        raise OSError("Storage is unavailable")

    monkeypatch.setattr(service.storage, "delete_owned_objects", unavailable)
    assert client.delete(f"/api/v1/candidates/{approval['candidateId']}").status_code == 204
    assert client.get(f"/api/v1/candidates/{approval['candidateId']}").status_code == 404


def test_deleted_legacy_interview_stays_deleted_after_startup_migration(deletion_client):
    client, service = deletion_client
    vacancy, existing_plan = make_plan(client)

    async def migrate():
        await service.repository.update_vacancy(
            vacancy["id"],
            {
                "question_count": 1,
                "seed_questions": ["Legacy question"],
            },
        )
        await service._migrate_legacy_hiring()

    asyncio.run(migrate())
    legacy_id = template_id("hr-demo", f"legacy:{vacancy['id']}")
    assert client.delete(f"/api/v1/interview-plans/{legacy_id}").status_code == 204
    asyncio.run(service._migrate_legacy_hiring())
    detail = assert_ok(client.get(f"/api/v1/vacancies/{vacancy['id']}"))
    assert [row["id"] for row in detail["interviews"]] == [existing_plan["id"]]
