from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from interview_api.config import Settings
from interview_api.main import create_app
from interview_api.workflow.ai import DeterministicWorkflowAI
from interview_api.workflow.entities import UserRow
from interview_api.workflow.errors import WorkflowProviderError
from interview_api.workflow.hiring_ai import HiringAI
from interview_api.workflow.openrouter import OpenRouterWorkflowAI
from interview_api.workflow.repository import SqlAlchemyWorkflowRepository
from interview_api.workflow.service import WorkflowService
from interview_api.workflow.storage import MemoryObjectStorage


@pytest.fixture
def hiring_client() -> Iterator[tuple[TestClient, WorkflowService]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
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
        client.post("/api/v1/dev/session", json={"userId": "hr-demo"})
        yield client, service
    asyncio.run(engine.dispose())


def assert_ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def sign_in_telegram(client: TestClient, service: WorkflowService) -> None:
    """Authenticate the candidate offline before accepting the invitation."""

    async def sign_in() -> str:
        account = await service.repository.register_telegram_account(
            telegram_id=1001,
            chat_id=1001,
            username="candidate_1001",
            first_name="Иван",
            last_name="Петров",
            now=service._now(),
        )
        actor = await service.repository.get_user(account.user_id)
        raw_token, _session = await service.session_for_telegram_actor(actor, role="candidate")
        return raw_token

    raw_token = asyncio.run(sign_in())
    client.cookies.clear()
    client.cookies.set(service.cookie_name, raw_token)
    assert client.get("/api/v1/session").status_code == 200


def make_plan(client: TestClient, personalized: int = 2, minutes: int = 17):
    template = assert_ok(client.get("/api/v1/vacancy-templates"))[0]
    vacancy = assert_ok(
        client.post(
            "/api/v1/vacancies",
            json={
                "templateId": template["id"],
                **{
                    key: template[key]
                    for key in ("title", "role", "level", "description", "requirements")
                },
            },
        )
    )
    interview_template = assert_ok(client.get("/api/v1/interview-templates"))[0]
    draft = assert_ok(
        client.post(
            f"/api/v1/vacancies/{vacancy['id']}/interviews/prepare",
            json={"templateId": interview_template["id"]},
        )
    )
    assert "HR" in draft["name"]
    assert len(draft["questions"]) == 8
    draft["questions"][0]["text"] = "Что привлекает вас в этой роли?"
    payload = {
        key: draft[key]
        for key in (
            "templateId",
            "questions",
            "durationMinutes",
            "maxFollowUpQuestions",
            "maxPersonalizedQuestions",
        )
    }
    payload.update(
        maxFollowUpQuestions=0, maxPersonalizedQuestions=personalized, durationMinutes=minutes
    )
    plan = assert_ok(client.post(f"/api/v1/vacancies/{vacancy['id']}/interviews", json=payload))
    return vacancy, plan


def candidate_draft(client: TestClient, plan: dict):
    return assert_ok(
        client.post(
            f"/api/v1/interview-plans/{plan['id']}/candidates/prepare",
            files={
                "resume": (
                    "resume.txt",
                    "Иван Петров\nivan@example.test\nPython, SQL".encode(),
                    "text/plain",
                )
            },
        )
    )


def test_complete_hierarchy_preserves_pool_settings_and_idempotent_candidate(hiring_client):
    client, service = hiring_client
    vacancy, plan = make_plan(client)
    assert "questions" not in vacancy
    assert vacancy["interviews"] == []
    draft = candidate_draft(client, plan)
    assert len(draft["questions"]) == 2
    draft["questions"][0]["text"] = "Как вы измерили результат проекта из резюме?"
    approval = assert_ok(
        client.post(f"/api/v1/interview-plans/{plan['id']}/candidates", json=draft)
    )
    # Repeating save after a network interruption must reuse the candidate, not duplicate it.
    repeat = assert_ok(client.post(f"/api/v1/interview-plans/{plan['id']}/candidates", json=draft))
    assert approval["candidateId"] == repeat["candidateId"]
    detail = assert_ok(client.get(f"/api/v1/interview-plans/{plan['id']}"))
    assert len(detail["candidates"]) == 1
    assert detail["candidateCount"] == 1
    saved = assert_ok(client.get(f"/api/v1/candidates/{approval['candidateId']}"))
    assert saved["processingStatus"] == "invited"
    assert len(saved["questions"]) == 10
    assert saved["questions"][0]["text"] == plan["questions"][0]["text"]
    assert saved["questions"][8]["text"] == draft["questions"][0]["text"]
    candidates = assert_ok(client.get("/api/v1/candidates", params={"search": "пЕтРоВ"}))
    assert candidates[0]["vacancyTitle"] == vacancy["title"]
    assert candidates[0]["interviewPlanId"] == plan["id"]
    assert assert_ok(client.get("/api/v1/candidates", params={"search": "none"})) == []
    listing = assert_ok(client.get("/api/v1/vacancies"))
    assert listing[0]["candidateCount"] == 1 and listing[0]["interviewCount"] == 1
    sign_in_telegram(client, service)
    briefing = assert_ok(
        client.post("/api/v1/invites/resolve", json={"token": repeat["inviteToken"]})
    )
    assert briefing["durationMinutes"] == 17
    assert briefing["allowsFollowUps"] is False
    assert briefing["questionCount"] == 10
    started = assert_ok(
        client.post(
            f"/api/v1/interviews/{repeat['interviewId']}/start", json={"consentToRecording": True}
        )
    )
    assert started["remainingSeconds"] == 17 * 60
    # Candidate identity cannot inspect company documents or other HR resources.
    assert client.get("/api/v1/company-context").status_code == 403
    assert client.get("/api/v1/candidates").status_code == 403


def test_plan_candidate_can_practice_then_complete_real_interview(hiring_client, monkeypatch):
    client, service = hiring_client
    vacancy, plan = make_plan(client, minutes=17)
    draft = candidate_draft(client, plan)
    approval = assert_ok(client.post(
        f"/api/v1/interview-plans/{plan['id']}/candidates", json=draft,
    ))
    candidate_id = approval["candidateId"]
    real_questions = assert_ok(client.get(f"/api/v1/candidates/{candidate_id}/questions"))
    calls = []
    generate = service.ai.generate_practice_questions

    async def record_profile(**kwargs):
        calls.append(kwargs)
        return await generate(**kwargs)

    monkeypatch.setattr(service.ai, "generate_practice_questions", record_profile)
    stored_before = dict(service.storage.objects)
    sign_in_telegram(client, service)
    assert_ok(client.post("/api/v1/invites/resolve", json={"token": approval["inviteToken"]}))
    path = f"/api/v1/interviews/{approval['interviewId']}"
    before = assert_ok(client.get(f"{path}/state"))
    examples = assert_ok(client.post(f"{path}/practice"))
    assert len(examples["questions"]) == 3
    assert calls == [{
        "role_family": service._practice_role_family(vacancy["role"]),
        "level_band": service._practice_level_band(vacancy["level"], vacancy["title"]),
        "question_count": 3,
        "language": "ru",
    }]
    assert all(
        not service._questions_are_too_similar(p["text"], q["text"])
        for p in examples["questions"] for q in real_questions
    )
    assert assert_ok(client.get(f"{path}/state")) == before
    assert service.storage.objects == stored_before
    # A practice ID cannot be used in the real answer or speech endpoints.
    practice_id = examples["questions"][0]["id"]
    state = assert_ok(client.post(f"{path}/start", json={"consentToRecording": True}))
    assert state["remainingSeconds"] == 17 * 60
    assert client.post(f"{path}/answers", data={"questionId": practice_id}, files={
        "audio": ("practice.webm", b"TEXT:local practice", "audio/webm"),
        "video": ("practice.webm", b"test-video", "video/webm"),
    }).status_code == 409
    assert client.get(f"{path}/questions/{practice_id}/speech").status_code == 404
    question = state["currentQuestion"]
    while question:
        answer = assert_ok(client.post(
            f"{path}/answers", data={"questionId": question["id"]}, files={
            "audio": ("answer.webm", b"TEXT:An independent answer", "audio/webm"),
            "video": ("answer.webm", b"test-video", "video/webm"),
        }))
        question = answer["nextQuestion"]
    assert_ok(client.post(f"{path}/complete"))
    assert_ok(client.post("/api/v1/dev/session", json={"userId": "hr-demo"}))
    assert assert_ok(client.get(f"/api/v1/candidates/{candidate_id}/questions")) == real_questions
    analysis = assert_ok(client.get(f"/api/v1/candidates/{candidate_id}/analysis"))
    assert analysis["recommendationLocked"] is True
    assert analysis["recommendation"] is None
    assert {q["questionId"] for q in analysis["questions"]} == {q["id"] for q in real_questions}


def test_templates_context_accumulation_and_no_questions_during_vacancy_upload(hiring_client):
    client, service = hiring_client
    templates = assert_ok(client.get("/api/v1/vacancy-templates"))
    assert len(templates) == 18
    assert len({t["role"] for t in templates}) == 6
    assert {t["level"] for t in templates} == {"Junior", "Middle", "Senior"}
    assert all(not t["adapted"] for t in templates)
    filtered = assert_ok(client.get("/api/v1/vacancy-templates", params={"level": "Senior"}))
    assert len(filtered) == 6
    first = assert_ok(
        client.post(
            "/api/v1/company-context",
            files={
                "document": (
                    "grades.txt",
                    b"Middle: independent work. Senior: architecture.",
                    "text/plain",
                )
            },
        )
    )
    second = assert_ok(
        client.post(
            "/api/v1/company-context",
            files={
                "document": (
                    "company.txt",
                    b"Company: data platform. Teamwork matters.",
                    "text/plain",
                )
            },
        )
    )
    assert first["id"] != second["id"]
    assert len(assert_ok(client.get("/api/v1/company-context"))) == 2
    assert all(t["adapted"] for t in assert_ok(client.get("/api/v1/vacancy-templates")))
    assert assert_ok(client.get("/api/v1/interview-templates"))[0]["adapted"]
    draft = assert_ok(
        client.post(
            "/api/v1/vacancies/parse",
            files={
                "vacancy": (
                    "vacancy.txt",
                    b"Python Backend Developer\nBuild APIs and SQL services.",
                    "text/plain",
                )
            },
        )
    )
    assert "questions" not in draft
    draft["title"] = "Edited backend vacancy"
    vacancy = assert_ok(client.post("/api/v1/vacancies", json=draft))
    assert vacancy["title"] == "Edited backend vacancy"
    assert vacancy["interviews"] == []
    row = asyncio.run(service.repository.get_position(vacancy["id"]))
    assert row.question_count == 0
    assert row.seed_questions == []


def test_context_adaptation_failure_is_atomic(hiring_client, monkeypatch):
    client, _ = hiring_client
    original = assert_ok(client.get("/api/v1/vacancy-templates"))

    async def fail(*args, **kwargs):
        raise WorkflowProviderError("Temporary adaptation error")

    monkeypatch.setattr(HiringAI, "adapt_templates", fail)
    response = client.post(
        "/api/v1/company-context",
        files={"document": ("context.txt", b"Company context with grading rules.", "text/plain")},
    )
    assert response.status_code == 502
    assert assert_ok(client.get("/api/v1/company-context")) == []
    assert assert_ok(client.get("/api/v1/vacancy-templates")) == original


def test_interview_template_is_immutable_on_create_and_drafts_are_scoped(hiring_client):
    client, service = hiring_client
    vacancy, plan = make_plan(client)
    draft = candidate_draft(client, plan)
    _, other_plan = make_plan(client, personalized=0)
    assert (
        client.post(
            f"/api/v1/interview-plans/{other_plan['id']}/candidates", json=draft
        ).status_code
        == 422
    )
    template = assert_ok(client.get("/api/v1/interview-templates"))[0]
    forged = {"templateId": template["id"], "name": "Forged name", "questions": plan["questions"]}
    assert (
        client.post(f"/api/v1/vacancies/{vacancy['id']}/interviews", json=forged).status_code == 422
    )
    update = {key: template[key] for key in ("name", "description", "evaluates")}
    update["name"] = "Company screening version two"
    assert_ok(client.patch(f"/api/v1/interview-templates/{template['id']}", json=update))
    # Existing plan stays a snapshot, unaffected by later global edits.
    assert assert_ok(client.get(f"/api/v1/interview-plans/{plan['id']}"))["name"] == plan["name"]

    async def add_other_hr():
        async with service.repository._sessions.begin() as session:
            session.add(UserRow(id="hr-other", role="hr", name="Other HR"))

    asyncio.run(add_other_hr())
    assert_ok(client.post("/api/v1/dev/session", json={"userId": "hr-other"}))
    assert client.get(f"/api/v1/interview-plans/{plan['id']}").status_code == 404
    assert (
        client.post(
            "/api/v1/vacancies",
            json={
                **{
                    key: vacancy[key]
                    for key in ("title", "role", "level", "description", "requirements")
                },
                "draftId": draft["draftId"],
            },
        ).status_code
        == 404
    )
    assert assert_ok(client.get("/api/v1/candidates")) == []


@pytest.mark.asyncio
async def test_additive_migration_preserves_existing_rows(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'old.sqlite'}")
    repo = SqlAlchemyWorkflowRepository.from_engine(engine)
    await repo.initialize(engine)
    await repo.ensure_demo_users()
    row = await repo.create_position(
        created_by="hr-demo",
        title="Legacy role",
        level="",
        location="",
        requirements=["SQL"],
        question_count=2,
        duration_minutes=20,
        max_follow_up_questions=1,
        vacancy_object_key="",
        vacancy_filename="old.txt",
        vacancy_content_type="text/plain",
        vacancy_text="Legacy vacancy",
        seed_questions=[],
    )
    async with engine.begin() as connection:
        await connection.execute(text("ALTER TABLE workflow_positions DROP COLUMN role"))
        await connection.execute(text("DROP INDEX ix_workflow_candidates_interview_plan_id"))
        await connection.execute(
            text("ALTER TABLE workflow_candidates DROP COLUMN interview_plan_id")
        )
    await repo.initialize(engine)
    await repo.initialize(engine)
    retained = await repo.get_position(row.id)
    assert retained.title == "Legacy role"
    assert retained.role == ""
    await engine.dispose()


class FakeResponse:
    status = 200

    def __init__(self, value: dict):
        self.data = json.dumps({"choices": [{"message": {"content": json.dumps(value)}}]}).encode()


class FakePool:
    def __init__(self):
        self.bodies = []

    def request(self, method, url, *, body, headers):
        self.bodies.append(json.loads(body))
        return FakeResponse({"text": "# Backend\n## Middle\nIndependent delivery and SQL."})

    def clear(self):
        pass


@pytest.mark.asyncio
async def test_pdf_sent_once_then_company_text_only():
    pool = FakePool()
    gateway = OpenRouterWorkflowAI(
        api_key="test", chat_model="test", stt_model="test", tts_model="test", pool=pool
    )
    ai = HiringAI(gateway)
    result = await ai._json(
        "vacancy_pdf",
        {"type": "object"},
        "Parse the vacancy",
        {"companyContext": "Stored text"},
        pdf=b"%PDF-test",
        filename="vacancy.pdf",
    )
    normalized = result["text"]
    body = pool.bodies[0]
    parts = body["messages"][1]["content"]
    assert parts[1]["file"]["file_data"].startswith("data:application/pdf;base64,")
    assert "redundant extracted text" not in parts[0]["text"]
    assert body["plugins"][0]["pdf"]["engine"] == "cloudflare-ai"
    await ai._json(
        "next", {"type": "object"}, "Read company criteria", {"companyContext": normalized}
    )
    second = pool.bodies[1]["messages"][1]["content"]
    assert isinstance(second, str) and normalized in json.loads(second)["companyContext"]
    assert "file_data" not in second


@pytest.mark.asyncio
async def test_context_normalization_keeps_whole_pages_and_every_chunk(monkeypatch):
    pool = FakePool()
    gateway = OpenRouterWorkflowAI(
        api_key="test", chat_model="test", stt_model="test", tts_model="test", pool=pool
    )
    ai = HiringAI(gateway)
    received = []

    async def record(name, schema, system, user, **kwargs):
        received.append(user["document"])
        return {"text": user["document"]}

    monkeypatch.setattr(ai, "_json", record)
    pages = [
        f"[Страница {i}]\nROLE-{i}\n" + ("Junior Middle Senior requirements\n" * 60)
        for i in range(1, 8)
    ]
    normalized = await ai.normalize_context("\n\n".join(pages), pdf=None, filename="grades.txt")
    assert len(received) > 1
    for page in pages:
        assert sum(page in chunk for chunk in received) == 1
        assert page.strip() in normalized


def test_legacy_hierarchy_backfill_keeps_candidates_and_settings(hiring_client):
    client, service = hiring_client
    position = assert_ok(
        client.post(
            "/api/v1/positions",
            data={
                "title": "Legacy backend",
                "requirements": "Python",
                "questionCount": "2",
                "durationMinutes": "23",
                "maxFollowUpQuestions": "1",
            },
            files={"vacancy": ("old.txt", b"Existing vacancy description", "text/plain")},
        )
    )
    candidate = assert_ok(
        client.post(
            f"/api/v1/positions/{position['id']}/candidates",
            data={
                "name": "Legacy Candidate",
                "role": "Backend",
            },
            files={"resume": ("cv.txt", b"Existing backend engineer", "text/plain")},
        )
    )
    asyncio.run(service._migrate_legacy_hiring())
    asyncio.run(service._migrate_legacy_hiring())
    detail = assert_ok(client.get(f"/api/v1/vacancies/{position['id']}"))
    assert detail["candidateCount"] == 1 and detail["interviewCount"] == 1
    plan = assert_ok(client.get(f"/api/v1/interview-plans/{detail['interviews'][0]['id']}"))
    assert plan["durationMinutes"] == 23
    assert plan["maxFollowUpQuestions"] == 1
    assert plan["candidates"][0]["id"] == candidate["id"]
    assert len(assert_ok(client.get(f"/api/v1/candidates/{candidate['id']}"))["questions"]) == 2


def test_resume_telegram_contact_is_parsed_and_saved(hiring_client):
    client, _service = hiring_client
    _vacancy, plan = make_plan(client)
    draft = assert_ok(client.post(
        f"/api/v1/interview-plans/{plan['id']}/candidates/prepare",
        files={"resume": ("resume.txt", "Иван Петров\nTelegram: @Candidate_Tg\nPython".encode(),
                          "text/plain")},
    ))
    assert draft["telegramUsername"] == "candidate_tg"
    draft["telegramUsername"] = "@Corrected_Tg"
    approval = assert_ok(client.post(
        f"/api/v1/interview-plans/{plan['id']}/candidates", json=draft,
    ))
    saved = assert_ok(client.get(f"/api/v1/candidates/{approval['candidateId']}"))
    assert saved["telegramUsername"] == "corrected_tg"
    listing = assert_ok(client.get("/api/v1/candidates"))
    assert listing[0]["telegramUsername"] == "corrected_tg"
