from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from test_workflow import (
    MutableClock,
    _create_hr_position_and_candidate,
    _sign_in_telegram,
)

from interview_api.config import Settings
from interview_api.main import create_app
from interview_api.workflow.ai import AnalysisItemDraft, DeterministicWorkflowAI
from interview_api.workflow.entities import (
    AnalysisRow,
    AnswerRow,
    DecisionRow,
    MediaAssetRow,
    QuestionRow,
)
from interview_api.workflow.errors import WorkflowProviderError
from interview_api.workflow.practice_repository import PracticeRepository
from interview_api.workflow.practice_topics import broad_topics
from interview_api.workflow.repository import SqlAlchemyWorkflowRepository
from interview_api.workflow.service import WorkflowService
from interview_api.workflow.storage import MemoryObjectStorage


@pytest.fixture
def practice_client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    clock = MutableClock(datetime(2026, 9, 6, tzinfo=UTC))
    service = WorkflowService(
        repository=SqlAlchemyWorkflowRepository.from_engine(engine),
        storage=MemoryObjectStorage(), ai=DeterministicWorkflowAI(), clock=clock,
    )
    app = create_app(
        settings=Settings(app_env="test", demo_auth_enabled=True, _env_file=None),
        workflow_service=service, workflow_engine=engine,
    )
    with TestClient(app) as client:
        yield client, service, clock
    asyncio.run(engine.dispose())


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def setup_practice(client, service):
    _, candidate_id, real_questions = _create_hr_position_and_candidate(client)
    # Deliberately precise internal subjects must never escape into the briefing/model prompt.
    async def set_topics():
        async with service.repository._sessions.begin() as session:
            first = await session.get(QuestionRow, real_questions[0]["id"])
            second = await session.get(QuestionRow, real_questions[1]["id"])
            first.topic = "Kafka: offset commit before/after PostgreSQL transaction"
            first.competency = "Exactly once, key=id заказа; secret_project_42"
            second.topic = "PostgreSQL: EXPLAIN ANALYZE executes UPDATE"
            second.competency = "Side effects and index selectivity"
    asyncio.run(set_topics())
    approval = ok(client.post(f"/api/v1/candidates/{candidate_id}/questions/approve"))
    _sign_in_telegram(client, service)
    briefing = ok(client.post("/api/v1/invites/resolve", json={"token": approval["inviteToken"]}))
    mock = ok(client.post(f"/api/v1/interviews/{approval['interviewId']}/practice"))
    return approval, briefing, mock


def upload_answer(client, mock, question, value="Kafka preserves order inside one partition."):
    return client.post(f"/api/v1/practice/{mock['practiceId']}/answers", data={
        "questionId": question["id"], "durationSeconds": 10,
    }, files={
        "audio": ("answer.webm", f"TEXT:{value}".encode(), "audio/webm"),
        "video": ("answer.webm", b"test-video", "video/webm"),
    })


def answer_all(client, mock):
    ok(client.post(f"/api/v1/practice/{mock['practiceId']}/start",
                   json={"consentToRecording": True}))
    return [ok(upload_answer(client, mock, q)) for q in mock["questions"]]


def test_private_practice_full_review_persists_and_never_changes_real_interview(
    practice_client, monkeypatch,
):
    client, service, _clock = practice_client
    calls = []
    generate = service.ai.generate_practice_questions

    async def record_generation(**kwargs):
        calls.append(kwargs)
        return await generate(**kwargs)

    monkeypatch.setattr(service.ai, "generate_practice_questions", record_generation)
    approval, briefing, mock = setup_practice(client, service)
    practice_path = f"/api/v1/practice/{mock['practiceId']}"
    real_path = f"/api/v1/interviews/{approval['interviewId']}"
    candidate_id = approval["candidateId"]
    # Cross-domain questions retain both broad categories, without exact screening hints.
    assert {"Интеграции", "Базы данных"}.issubset(briefing["topics"])
    assert all(len(topic) < 40 for topic in briefing["topics"])
    assert {q["topic"] for q in mock["questions"]} == set(briefing["topics"])
    assert "secret_project_42" not in str(calls)
    assert "EXPLAIN" not in str(calls)
    before = ok(client.get(f"{real_path}/state"))
    assert client.get(f"{practice_path}/analysis").status_code == 404
    assert client.post(
        f"{practice_path}/start", json={"consentToRecording": False}
    ).status_code == 422
    answers = answer_all(client, mock)
    assert answers[-1]["nextQuestion"] is None
    # Network retries return the same transcript, even when the submitted text differs.
    repeated = ok(upload_answer(client, mock, mock["questions"][0], "different answer"))
    assert repeated["answerId"] == answers[0]["answerId"]
    assert repeated["transcript"] == answers[0]["transcript"]
    complete = ok(client.post(f"{practice_path}/complete"))
    assert complete["status"] == "completed"
    analysis = ok(client.get(f"{practice_path}/analysis"))
    assert analysis["recommendationLocked"]
    assert analysis["score"] is None
    assert analysis["items"]
    answered_ids = {q["questionId"] for q in analysis["questions"] if q["answerText"]}
    assert all(item["questionId"] in answered_ids for item in analysis["items"])
    assert analysis["summary"] is None
    assert analysis["recommendation"] is None
    assert analysis["growthAreas"] == []
    assert all(q["answerText"] for q in analysis["questions"])
    initial = {"status": "next_stage", "candidateFeedback": "Понимаю порядок событий.",
               "internalReason": "Нужно больше практики."}
    assert client.post(f"{practice_path}/decision", json=initial).status_code == 409
    assert client.post(f"{practice_path}/review", json=initial).status_code == 409
    for question in mock["questions"]:
        ok(client.put(f"{practice_path}/questions/{question['id']}/rating",
                      json={"rating": "positive"}))
    revealed = ok(client.post(f"{practice_path}/review", json=initial))
    assert not revealed["recommendationLocked"]
    assert revealed["summary"]
    assert revealed["items"]
    assert any(item["questionId"] is None for item in revealed["items"])
    assert ok(client.post(f"{practice_path}/review", json=initial)) == revealed
    assert client.put(f"{practice_path}/questions/{mock['questions'][0]['id']}/rating",
                      json={"rating": "negative"}).status_code == 409
    final = ok(client.post(f"{practice_path}/decision", json=initial))
    assert ok(client.post(f"{practice_path}/decision", json=initial)) == final
    assert client.post(f"{practice_path}/decision", json={
        **initial, "candidateFeedback": "changed"
    }).status_code == 409
    assert len(ok(client.get(f"{practice_path}/media"))["assets"]) == len(answers) * 2
    assert ok(client.get(f"{real_path}/state")) == before
    assert ok(client.get("/api/v1/candidate/outcome"))["status"] == "pending"

    # A new service/repository instance can recover everything from storage, no process cache.
    service.practice_repository = PracticeRepository(service.repository._sessions)
    assert ok(client.get(f"{practice_path}/analysis"))["finalDecision"] == final
    assert ok(client.post(f"{real_path}/practice"))["practiceId"] == mock["practiceId"]
    assert ok(client.post(f"{practice_path}/complete")) == complete

    async def assert_no_real_rows():
        async with service.repository._sessions() as session:
            assert await session.scalar(text("PRAGMA foreign_keys")) == 1
            for model in (AnswerRow, AnalysisRow, DecisionRow, MediaAssetRow):
                assert list(await session.scalars(select(model))) == []
        candidate = await service.repository.get_candidate(candidate_id)
        assert candidate.hiring_decision == "pending"
        assert candidate.processing_status == "invited"
    asyncio.run(assert_no_real_rows())

    # HR sees only real questions, no rehearsals, no media, no candidate's private feedback.
    ok(client.post("/api/v1/dev/session", json={"userId": "hr-demo"}))
    for suffix in ("", "/analysis", "/media"):
        assert client.get(f"{practice_path}{suffix}").status_code == 403
    assert client.get(f"/api/v1/candidates/{candidate_id}/analysis").status_code == 404
    assert ok(client.get(f"/api/v1/candidates/{candidate_id}/media"))["assets"] == []


def test_practice_wrong_candidate_order_timeout_recovery_and_retry(practice_client, monkeypatch):
    client, service, clock = practice_client
    approval, _briefing, mock = setup_practice(client, service)
    path = f"/api/v1/practice/{mock['practiceId']}"
    assert upload_answer(client, mock, mock["questions"][0]).status_code == 409
    ok(client.post(f"{path}/start", json={"consentToRecording": True}))
    assert upload_answer(client, mock, mock["questions"][1]).status_code == 409
    assert client.post(f"{path}/complete").status_code == 422
    ok(upload_answer(client, mock, mock["questions"][0]))
    assert client.post(f"{path}/complete").status_code == 409
    analyze = service.ai.analyze
    attempts = 0

    async def fail_once(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise WorkflowProviderError("temporary provider failure")
        draft = await analyze(**kwargs)
        draft.items.append(AnalysisItemDraft(
            kind="answer", title="Hallucination", body="Bad evidence",
            question_id=mock["questions"][0]["id"],
            evidence=[{"quote": "I never said this", "label": "confirmed"}],
        ))
        return draft

    monkeypatch.setattr(service.ai, "analyze", fail_once)
    clock.advance(mock["remainingSeconds"] + 1)
    assert client.post(f"{path}/complete").status_code == 502
    assert ok(client.get(path))["status"] == "error"
    assert ok(client.post(f"{path}/complete"))["status"] == "completed"
    assert attempts == 2
    # Unanswered questions stay visible for honest self-assessment.
    analysis = ok(client.get(f"{path}/analysis"))
    assert sum(q["answerText"] is None for q in analysis["questions"]) == len(mock["questions"]) - 1
    assert analysis["items"]
    assert all(item["questionId"] == mock["questions"][0]["id"] for item in analysis["items"])
    async def check_sanitized():
        row = await service.practice_repository.get(mock["practiceId"])
        item = next(i for i in row.analysis["items"] if i["title"] == "Hallucination")
        assert item["evidence"] == []
    asyncio.run(check_sanitized())
    _, other_id, _ = _create_hr_position_and_candidate(client)
    other_approval = ok(client.post(f"/api/v1/candidates/{other_id}/questions/approve"))
    _sign_in_telegram(client, service, telegram_id=2002)
    ok(client.post("/api/v1/invites/resolve", json={"token": other_approval["inviteToken"]}))
    for suffix in ("", "/analysis", "/media"):
        assert client.get(f"{path}{suffix}").status_code == 404
    for suffix in ("/complete", "/start"):
        assert client.post(f"{path}{suffix}", json={"consentToRecording": True}).status_code == 404
    assert client.post(f"/api/v1/interviews/{approval['interviewId']}/practice").status_code == 403


def test_practice_recovers_analysis_interrupted_by_restart(practice_client):
    client, service, _clock = practice_client
    _approval, _briefing, mock = setup_practice(client, service)
    answer_all(client, mock)

    async def interrupt_then_recover():
        def mark(row):
            row.status = "analyzing"
        await service.practice_repository.mutate(mock["practiceId"], mark)
        await service.practice_repository.recover_interrupted()
    asyncio.run(interrupt_then_recover())
    path = f"/api/v1/practice/{mock['practiceId']}"
    assert ok(client.get(path))["status"] == "error"
    assert ok(client.post(f"{path}/complete"))["status"] == "completed"


def test_practice_upload_failure_removes_partial_media_and_can_retry(practice_client, monkeypatch):
    client, service, _clock = practice_client
    _approval, _briefing, mock = setup_practice(client, service)
    path = f"/api/v1/practice/{mock['practiceId']}"
    ok(client.post(f"{path}/start", json={"consentToRecording": True}))
    original_put = service.storage.put_bytes
    failed = False

    async def fail_video_once(key, data, **kwargs):
        nonlocal failed
        if "/video/" in key and not failed:
            failed = True
            raise WorkflowProviderError("storage unavailable")
        return await original_put(key, data, **kwargs)

    monkeypatch.setattr(service.storage, "put_bytes", fail_video_once)
    assert upload_answer(client, mock, mock["questions"][0]).status_code == 502
    assert not any("/practice/" in key for key in service.storage.objects)
    assert ok(client.get(path))["answeredQuestionIds"] == []
    ok(upload_answer(client, mock, mock["questions"][0]))
    assert len(ok(client.get(f"{path}/media"))["assets"]) == 2


def test_deleted_candidate_cannot_be_resurrected_by_mock_analysis(practice_client, monkeypatch):
    client, service, _clock = practice_client
    approval, _briefing, mock = setup_practice(client, service)
    answer_all(client, mock)
    analyze = service.ai.analyze

    async def delete_during_analysis(**kwargs):
        draft = await analyze(**kwargs)
        deleted = await service.repository.delete_hiring_aggregate(
            owner="hr-demo", kind="candidate", resource_id=approval["candidateId"]
        )
        await service.storage.delete_owned_objects(keys=deleted.keys, prefixes=deleted.prefixes)
        return draft

    monkeypatch.setattr(service.ai, "analyze", delete_during_analysis)
    assert client.post(f"/api/v1/practice/{mock['practiceId']}/complete").status_code == 404
    assert not any("/practice/" in key for key in service.storage.objects)
    assert asyncio.run(service.practice_repository.for_interview(approval["interviewId"])) is None


def test_mock_speech_access_and_final_reason_gate(practice_client, monkeypatch):
    client, service, _clock = practice_client
    _approval, _briefing, mock = setup_practice(client, service)
    path = f"/api/v1/practice/{mock['practiceId']}"
    first_speech = f"{path}/questions/{mock['questions'][0]['id']}/speech"
    assert client.get(first_speech).status_code == 409
    ok(client.post(f"{path}/start", json={"consentToRecording": True}))
    assert client.get(first_speech).status_code == 200
    assert client.get(f"{path}/questions/{mock['questions'][1]['id']}/speech").status_code == 409
    for question in mock["questions"]:
        ok(upload_answer(client, mock, question))
    assert client.get(first_speech).status_code == 409
    analyze = service.ai.analyze

    async def recommend_fit(**kwargs):
        draft = await analyze(**kwargs)
        draft.recommendation = "fit"
        return draft

    monkeypatch.setattr(service.ai, "analyze", recommend_fit)
    ok(client.post(f"{path}/complete"))
    for question in mock["questions"]:
        ok(client.put(f"{path}/questions/{question['id']}/rating", json={"rating": "uncertain"}))
    initial = {"status": "rejected", "candidateFeedback": "Нужно укрепить знания."}
    ok(client.post(f"{path}/review", json=initial))
    changed = {**initial, "status": "next_stage"}
    assert client.post(f"{path}/decision", json=changed).status_code == 422
    ok(client.post(f"{path}/decision", json={
        **changed, "changeReason": "Ответ содержал верные примеры, которых я не заметил."
    }))


def test_expired_empty_mock_can_resume_same_questions(practice_client):
    client, service, clock = practice_client
    _approval, _briefing, mock = setup_practice(client, service)
    path = f"/api/v1/practice/{mock['practiceId']}"
    ok(client.post(f"{path}/start", json={"consentToRecording": True}))
    clock.advance(mock["remainingSeconds"] + 1)
    expired = ok(client.get(path))
    assert expired["currentQuestion"] is None
    assert expired["remainingSeconds"] == 0
    resumed = ok(client.post(f"{path}/start", json={"consentToRecording": True}))
    assert resumed["practiceId"] == mock["practiceId"]
    assert resumed["questions"] == mock["questions"]
    assert resumed["currentQuestion"]["id"] == mock["questions"][0]["id"]
    assert resumed["remainingSeconds"] > 0
    ok(upload_answer(client, mock, mock["questions"][0]))


@pytest.mark.parametrize(("source", "expected"), [
    ("Capital allocation", ["Профессиональная практика"]),
    ("Portfolios and bios", ["Профессиональная практика"]),
    ("JavaScript", ["Веб-разработка"]),
    ("Java", ["Программирование"]),
    ("iOS / Android", ["Мобильная разработка"]),
    ("API contracts", ["Интеграции"]),
    ("RabbitMQ and Kafka", ["Интеграции"]),
    ("PostgreSQL / SQLAlchemy", ["Базы данных"]),
    ("Architecture & Design", ["Архитектура"]),
    ("System   design", ["Архитектура"]),
    ("Database design", ["Базы данных"]),
    ("Architecture and UI design", ["Архитектура", "Дизайн"]),
    ("Интеграция очередей и проектирование системы", ["Интеграции", "Архитектура"]),
])
def test_broad_topics_respect_technology_boundaries_and_design_context(source, expected):
    assert broad_topics([source]) == expected
