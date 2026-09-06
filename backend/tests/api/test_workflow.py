from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from interview_api.config import Settings
from interview_api.main import create_app
from interview_api.workflow.ai import (
    AnalysisDraft,
    DeterministicWorkflowAI,
    FollowUpProposal,
    PracticeQuestionProposal,
    TranscriptWord,
    WorkflowTranscript,
)
from interview_api.workflow.errors import WorkflowProviderError
from interview_api.workflow.openrouter import OpenRouterWorkflowAI
from interview_api.workflow.repository import SqlAlchemyWorkflowRepository
from interview_api.workflow.service import WorkflowService
from interview_api.workflow.storage import MemoryObjectStorage, StoredObject


@dataclass
class MutableClock:
    value: datetime

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


class FollowUpWorkflowAI(DeterministicWorkflowAI):
    def __init__(self) -> None:
        self.follow_up_calls = 0

    async def propose_follow_up(
        self,
        *,
        question: str,
        topic: str,
        answer: str,
        remaining_seconds: int,
        remaining_base_questions: int,
    ) -> FollowUpProposal:
        del question, answer, remaining_seconds, remaining_base_questions
        self.follow_up_calls += 1
        return FollowUpProposal(
            should_ask=self.follow_up_calls == 1,
            question="Как именно вы проверяли надёжность этого решения?",
            topic=topic,
            competency=topic,
            reason="Нужен проверяемый пример",
        )


class FailOnceAnalysisAI(FollowUpWorkflowAI):
    def __init__(self) -> None:
        super().__init__()
        self.analysis_attempts = 0

    async def analyze(
        self,
        *,
        vacancy_text: str,
        requirements: list[str],
        questions_and_answers: list[dict[str, object]],
    ) -> AnalysisDraft:
        self.analysis_attempts += 1
        if self.analysis_attempts == 1:
            raise WorkflowProviderError("Temporary analysis failure")
        return await super().analyze(
            vacancy_text=vacancy_text,
            requirements=requirements,
            questions_and_answers=questions_and_answers,
        )


class PracticeIsolationAI(FollowUpWorkflowAI):
    def __init__(self) -> None:
        super().__init__()
        self.practice_calls: list[dict[str, object]] = []

    async def generate_practice_questions(
        self,
        *,
        role_family: str,
        level_band: str,
        question_count: int,
        language: str,
        broad_topics: list[str] | None = None,
    ) -> list[PracticeQuestionProposal]:
        self.practice_calls.append(
            {
                "broad_topics": broad_topics,
                "role_family": role_family,
                "level_band": level_band,
                "question_count": question_count,
                "language": language,
            }
        )
        if len(self.practice_calls) == 1:
            return [
                PracticeQuestionProposal(
                    text="Расскажите о сложном Python-сервисе.",
                    topic="Небезопасное совпадение",
                ),
                PracticeQuestionProposal(text="Безопасный вопрос один.", topic="Практика"),
                PracticeQuestionProposal(text="Безопасный вопрос два.", topic="Практика"),
            ]
        return [
            PracticeQuestionProposal(
                text="Как бы вы начали разбирать вымышленную задачу с неполными данными?",
                topic="Разбор ситуации",
            ),
            PracticeQuestionProposal(
                text="Как в учебном кейсе сравнить два разумных подхода?",
                topic="Принятие решений",
            ),
            PracticeQuestionProposal(
                text="Что вы измените, если первый эксперимент не подтвердит гипотезу?",
                topic="Рефлексия",
            ),
        ]


class FailOnceVideoStorage(MemoryObjectStorage):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    async def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        metadata: Mapping[str, str] | None = None,
    ) -> StoredObject:
        if not self.failed and "/video." in key:
            self.failed = True
            raise WorkflowProviderError("Temporary video storage failure")
        return await super().put_bytes(
            key,
            data,
            content_type=content_type,
            metadata=metadata,
        )


@pytest.fixture
def workflow_client() -> Iterator[tuple[TestClient, WorkflowService, MutableClock]]:
    engine: AsyncEngine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    repository = SqlAlchemyWorkflowRepository.from_engine(engine)
    clock = MutableClock(datetime(2026, 9, 4, 12, 0, tzinfo=UTC))
    service = WorkflowService(
        repository=repository,
        storage=MemoryObjectStorage(),
        ai=FollowUpWorkflowAI(),
        clock=clock,
        invite_base_url="http://localhost:3000",
    )

    app = create_app(
        settings=Settings(app_env="test", demo_auth_enabled=True, _env_file=None),
        workflow_service=service,
        workflow_engine=engine,
    )
    with TestClient(app) as client:
        yield client, service, clock
    asyncio.run(engine.dispose())


def _sign_in_telegram(
    client: TestClient, service: WorkflowService, *, telegram_id: int = 1001
) -> str:
    """Create a verified Telegram identity offline; bot protocol has separate tests."""

    async def sign_in() -> str:
        account = await service.repository.register_telegram_account(
            telegram_id=telegram_id,
            chat_id=telegram_id,
            username=f"candidate_{telegram_id}",
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
    return raw_token


def _create_hr_position_and_candidate(
    client: TestClient, *, max_follow_up_questions: int = 1
) -> tuple[str, str, list[dict[str, Any]]]:
    session = client.post("/api/v1/dev/session", json={"userId": "hr-demo"})
    assert session.status_code == 200
    assert session.json()["user"]["role"] == "hr"
    assert client.get("/api/v1/session").json()["role"] == "hr"

    position = client.post(
        "/api/v1/positions",
        data={
            "title": "Python Backend Developer",
            "requirements": '["Python", "PostgreSQL"]',
            "questionCount": "2",
            "durationMinutes": "20",
            "maxFollowUpQuestions": str(max_follow_up_questions),
            "seedQuestions": '["Расскажите о сложном Python-сервисе."]',
        },
        files={"vacancy": ("vacancy.txt", b"Backend vacancy", "text/plain")},
    )
    assert position.status_code == 200, position.text
    position_id = position.json()["id"]
    assert position.json()["questionCount"] == 2
    assert position.json()["maxFollowUpQuestions"] == max_follow_up_questions

    candidate = client.post(
        f"/api/v1/positions/{position_id}/candidates",
        data={"name": "Иван Петров", "email": "ivan@example.test", "role": "Developer"},
        files={
            "resume": (
                "resume.txt",
                b"Python developer with PostgreSQL experience",
                "text/plain",
            )
        },
    )
    assert candidate.status_code == 200, candidate.text
    payload = candidate.json()
    assert payload["processingStatus"] == "not_started"
    users = client.get("/api/v1/dev/users").json()
    candidate_user = next(user for user in users if user["candidateId"] == payload["id"])
    assert len(candidate_user["id"]) <= 36
    return position_id, payload["id"], payload["questions"]


def test_position_rejects_excessive_extracted_text(
    workflow_client: tuple[TestClient, WorkflowService, MutableClock],
) -> None:
    client, service, _clock = workflow_client
    service.max_document_characters = 10
    assert client.post("/api/v1/dev/session", json={"userId": "hr-demo"}).status_code == 200

    response = client.post(
        "/api/v1/positions",
        data={
            "title": "Backend Developer",
            "requirements": "Python",
            "questionCount": "1",
            "durationMinutes": "10",
        },
        files={"vacancy": ("vacancy.txt", b"eleven chars", "text/plain")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"] == {"maxCharacters": 10}


def test_create_app_exposes_workflow_with_credentialed_cors(
    workflow_client: tuple[TestClient, WorkflowService, MutableClock],
) -> None:
    client, _service, _clock = workflow_client

    response = client.options(
        "/api/v1/dev/users",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_workflow_reuses_openrouter_stt_for_legacy_transcription_endpoint(
    workflow_client: tuple[TestClient, WorkflowService, MutableClock],
) -> None:
    client, _service, _clock = workflow_client

    response = client.post(
        "/api/v1/transcriptions",
        files={"audio": ("answer.webm", b"TEXT:Legacy endpoint answer", "audio/webm")},
        data={"language": "ru"},
    )

    assert response.status_code == 200
    assert response.json()["text"] == "Legacy endpoint answer"
    assert response.json()["meta"]["provider"] == "openrouter-workflow"


def test_demo_session_endpoints_are_disabled_in_production(
    workflow_client: tuple[TestClient, WorkflowService, MutableClock],
) -> None:
    client, _service, _clock = workflow_client
    settings = client.app.state.settings
    previous_environment = settings.app_env
    settings.app_env = "production"
    try:
        assert client.get("/api/v1/dev/users").status_code == 404
        assert client.post("/api/v1/dev/session", json={"userId": "hr-demo"}).status_code == 404
    finally:
        settings.app_env = previous_environment


def test_invitation_requires_telegram_authentication_before_resolving(
    workflow_client: tuple[TestClient, WorkflowService, MutableClock],
) -> None:
    client, _service, _clock = workflow_client
    _position_id, candidate_id, _questions = _create_hr_position_and_candidate(client)
    approval = client.post(f"/api/v1/candidates/{candidate_id}/questions/approve").json()

    # Possessing an invitation must not turn a non-Telegram demo session into a candidate.
    non_telegram = client.post(
        "/api/v1/invites/resolve", json={"token": approval["inviteToken"]}
    )
    assert non_telegram.status_code == 403
    assert "set-cookie" not in non_telegram.headers
    assert client.get("/api/v1/session").json()["role"] == "hr"

    client.cookies.clear()
    for token in (approval["inviteToken"], "invalid-invitation-token"):
        anonymous = client.post("/api/v1/invites/resolve", json={"token": token})
        assert anonymous.status_code == 401
        assert "set-cookie" not in anonymous.headers
    assert client.get("/api/v1/candidate/interview").status_code == 401
    assert client.get(f"/api/v1/interviews/{approval['interviewId']}").status_code == 401


def test_invitation_cannot_rebind_candidate_to_another_telegram_account(
    workflow_client: tuple[TestClient, WorkflowService, MutableClock],
) -> None:
    client, service, _clock = workflow_client
    _position_id, candidate_id, _questions = _create_hr_position_and_candidate(client)
    approval = client.post(f"/api/v1/candidates/{candidate_id}/questions/approve").json()

    _sign_in_telegram(client, service, telegram_id=1001)
    accepted = client.post("/api/v1/invites/resolve", json={"token": approval["inviteToken"]})
    assert accepted.status_code == 200, accepted.text
    assert client.get("/api/v1/session").json()["candidateId"] == candidate_id

    _sign_in_telegram(client, service, telegram_id=1002)
    rejected = client.post("/api/v1/invites/resolve", json={"token": approval["inviteToken"]})
    assert rejected.status_code == 403
    assert "set-cookie" not in rejected.headers
    assert client.get("/api/v1/session").json()["candidateId"] is None
    assert client.get(f"/api/v1/interviews/{approval['interviewId']}").status_code == 403


def test_expired_invitation_is_rejected_after_telegram_authentication(
    workflow_client: tuple[TestClient, WorkflowService, MutableClock],
) -> None:
    client, service, clock = workflow_client
    _position_id, candidate_id, _questions = _create_hr_position_and_candidate(client)
    approval = client.post(f"/api/v1/candidates/{candidate_id}/questions/approve").json()
    clock.advance(service.invite_ttl.total_seconds() + 1)
    _sign_in_telegram(client, service)

    expired = client.post("/api/v1/invites/resolve", json={"token": approval["inviteToken"]})
    assert expired.status_code == 404
    assert "set-cookie" not in expired.headers
    assert client.get("/api/v1/session").json()["candidateId"] is None


def test_briefing_reports_when_follow_ups_are_disabled(
    workflow_client: tuple[TestClient, WorkflowService, MutableClock],
) -> None:
    client, service, _clock = workflow_client
    _position_id, candidate_id, _questions = _create_hr_position_and_candidate(
        client, max_follow_up_questions=0
    )
    approval = client.post(f"/api/v1/candidates/{candidate_id}/questions/approve").json()

    _sign_in_telegram(client, service)
    briefing = client.post("/api/v1/invites/resolve", json={"token": approval["inviteToken"]})

    assert briefing.status_code == 200
    assert briefing.json()["allowsFollowUps"] is False


def test_practice_questions_are_isolated_and_do_not_start_interview(
    workflow_client: tuple[TestClient, WorkflowService, MutableClock],
) -> None:
    client, service, _clock = workflow_client
    practice_ai = PracticeIsolationAI()
    service.ai = practice_ai
    _position_id, candidate_id, real_questions = _create_hr_position_and_candidate(client)
    approval = client.post(f"/api/v1/candidates/{candidate_id}/questions/approve").json()
    _sign_in_telegram(client, service)
    assert client.post(
        "/api/v1/invites/resolve", json={"token": approval["inviteToken"]}
    ).status_code == 200
    interview_id = approval["interviewId"]

    before = client.get(f"/api/v1/interviews/{interview_id}/state").json()
    response = client.post(f"/api/v1/interviews/{interview_id}/practice")
    after = client.get(f"/api/v1/interviews/{interview_id}/state").json()

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["mode"] == "practice"
    assert payload["localOnly"] is False
    assert len(payload["questions"]) == 3
    assert all(item["id"].startswith("practice-") for item in payload["questions"])
    assert {item["text"] for item in payload["questions"]}.isdisjoint(
        {item["text"] for item in real_questions}
    )
    assert len(practice_ai.practice_calls) == 2
    assert set(practice_ai.practice_calls[0]) == {
        "broad_topics",
        "role_family",
        "level_band",
        "question_count",
        "language",
    }
    assert before == after
    assert after["status"] == "ready"
    assert after["startedAt"] is None
    assert after["deadlineAt"] is None

    repeated = client.post(f"/api/v1/interviews/{interview_id}/practice")
    assert repeated.json() == payload
    assert len(practice_ai.practice_calls) == 2

    started = client.post(
        f"/api/v1/interviews/{interview_id}/start",
        json={"consentToRecording": True},
    )
    assert started.status_code == 200
    assert client.post(f"/api/v1/interviews/{interview_id}/practice").json() == payload


def test_practice_requires_the_invited_candidate(workflow_client):
    client, service, _ = workflow_client
    _, candidate_id, _ = _create_hr_position_and_candidate(client)
    approval = client.post(f"/api/v1/candidates/{candidate_id}/questions/approve").json()
    path = f"/api/v1/interviews/{approval['interviewId']}/practice"
    assert client.post(path).status_code == 403  # HR cannot rehearse as a candidate.
    client.cookies.clear()
    assert client.post(path).status_code == 401
    _, other_id, _ = _create_hr_position_and_candidate(client)
    other = client.post(f"/api/v1/candidates/{other_id}/questions/approve").json()
    _sign_in_telegram(client, service, telegram_id=2002)
    assert client.post(
        "/api/v1/invites/resolve", json={"token": other["inviteToken"]}
    ).status_code == 200
    assert client.post(path).status_code == 403


@pytest.mark.parametrize("failure", ["unavailable", "overlap"])
def test_practice_fallback_preserves_real_questions(workflow_client, monkeypatch, failure):
    client, service, _ = workflow_client
    _, candidate_id, real_questions = _create_hr_position_and_candidate(client)
    approval = client.post(f"/api/v1/candidates/{candidate_id}/questions/approve").json()
    _sign_in_telegram(client, service)
    client.post("/api/v1/invites/resolve", json={"token": approval["inviteToken"]})

    async def failed_generation(**kwargs):
        if failure == "unavailable":
            raise WorkflowProviderError("Unavailable")
        return [PracticeQuestionProposal(text=real_questions[0]["text"], topic="Overlap")] * 3

    monkeypatch.setattr(service.ai, "generate_practice_questions", failed_generation)
    path = f"/api/v1/interviews/{approval['interviewId']}"
    before = client.get(f"{path}/state").json()
    response = client.post(f"{path}/practice")
    assert response.status_code == 200, response.text
    assert len(response.json()["questions"]) == 3
    assert client.get(f"{path}/state").json() == before
    assert all(
        not service._questions_are_too_similar(practice["text"], real["text"])
        for practice in response.json()["questions"] for real in real_questions
    )


def test_practice_generation_finishing_after_real_start_is_rejected(workflow_client, monkeypatch):
    client, service, _ = workflow_client
    _, candidate_id, _ = _create_hr_position_and_candidate(client)
    approval = client.post(f"/api/v1/candidates/{candidate_id}/questions/approve").json()
    interview_id = approval["interviewId"]
    _sign_in_telegram(client, service)
    client.post("/api/v1/invites/resolve", json={"token": approval["inviteToken"]})
    generate = service.ai.generate_practice_questions

    async def start_while_generating(**kwargs):
        await service.repository.set_interview_status(interview_id, "in_progress")
        return await generate(**kwargs)

    monkeypatch.setattr(service.ai, "generate_practice_questions", start_while_generating)
    assert client.post(f"/api/v1/interviews/{interview_id}/practice").status_code == 409
    assert asyncio.run(service.practice_repository.for_interview(interview_id)) is None


@pytest.mark.parametrize("status", ["in_progress", "analyzing", "completed", "error"])
def test_existing_practice_remains_available_after_real_interview_starts(workflow_client, status):
    client, service, _ = workflow_client
    _, candidate_id, _ = _create_hr_position_and_candidate(client)
    approval = client.post(f"/api/v1/candidates/{candidate_id}/questions/approve").json()
    interview_id = approval["interviewId"]
    _sign_in_telegram(client, service)
    client.post("/api/v1/invites/resolve", json={"token": approval["inviteToken"]})
    path = f"/api/v1/interviews/{interview_id}/practice"
    initial = client.post(path).json()
    asyncio.run(service.repository.set_interview_status(interview_id, status))
    assert client.post(path).json() == initial


def test_answer_finishing_at_deadline_is_saved_and_ends_interview(
    workflow_client: tuple[TestClient, WorkflowService, MutableClock],
) -> None:
    client, service, clock = workflow_client
    _position_id, candidate_id, _questions = _create_hr_position_and_candidate(client)
    approval = client.post(f"/api/v1/candidates/{candidate_id}/questions/approve").json()
    _sign_in_telegram(client, service)
    assert (
        client.post("/api/v1/invites/resolve", json={"token": approval["inviteToken"]}).status_code
        == 200
    )
    interview_id = approval["interviewId"]
    started = client.post(
        f"/api/v1/interviews/{interview_id}/start",
        json={"consentToRecording": True},
    ).json()
    question_id = started["currentQuestion"]["id"]

    clock.advance(20 * 60 + 1)
    missing_video = client.post(
        f"/api/v1/interviews/{interview_id}/answers",
        data={"questionId": question_id},
        files={"audio": ("answer.webm", b"TEXT:Final answer", "audio/webm")},
    )
    assert missing_video.status_code == 422

    answer = client.post(
        f"/api/v1/interviews/{interview_id}/answers",
        data={"questionId": question_id},
        files={
            "audio": ("answer.webm", b"TEXT:Final answer", "audio/webm"),
            "video": ("answer-video.webm", b"video-bytes", "video/webm"),
        },
    )

    assert answer.status_code == 200, answer.text
    assert answer.json()["nextQuestion"] is None
    assert answer.json()["remainingSeconds"] == 0
    state = client.get(f"/api/v1/interviews/{interview_id}/state").json()
    assert state["answeredQuestionIds"] == [question_id]
    completed = client.post(f"/api/v1/interviews/{interview_id}/complete")
    assert completed.status_code == 200, completed.text
    assert client.get("/api/v1/candidate/interview").json()["currentQuestion"] is None


def test_full_hr_candidate_workflow_with_review_and_decision_gate(
    workflow_client: tuple[TestClient, WorkflowService, MutableClock],
) -> None:
    client, service, clock = workflow_client
    service.ai = FailOnceAnalysisAI()
    service.storage = FailOnceVideoStorage()

    assert client.get("/api/v1/session").status_code == 404
    _position_id, candidate_id, questions = _create_hr_position_and_candidate(client)
    assert len(questions) == 2
    assert questions[0]["kind"] == "provided"

    edited = client.patch(
        f"/api/v1/candidates/{candidate_id}/questions/{questions[0]['id']}",
        json={"text": "Опишите архитектуру сложного Python-сервиса."},
    )
    assert edited.status_code == 200

    approval = client.post(f"/api/v1/candidates/{candidate_id}/questions/approve")
    assert approval.status_code == 200, approval.text
    approval_payload = approval.json()
    assert approval_payload["inviteUrl"].startswith("http://localhost:3000/?invite=")
    interview_id = approval_payload["interviewId"]
    invite_token = approval_payload["inviteToken"]
    assert client.get(f"/api/v1/candidates/{candidate_id}").json()["processingStatus"] == "invited"

    _sign_in_telegram(client, service)
    briefing = client.post("/api/v1/invites/resolve", json={"token": invite_token})
    assert briefing.status_code == 200, briefing.text
    assert briefing.json()["questionCount"] == 2
    assert briefing.json()["humanReviewNotice"]
    assert client.get("/api/v1/candidate/interview").status_code == 200

    started = client.post(
        f"/api/v1/interviews/{interview_id}/start",
        json={"consentToRecording": True},
    )
    assert started.status_code == 200
    current = started.json()["currentQuestion"]
    assert current is not None

    assert client.post("/api/v1/dev/session", json={"userId": "hr-demo"}).status_code == 200
    assert (
        client.get(f"/api/v1/candidates/{candidate_id}").json()["processingStatus"] == "in_progress"
    )
    _sign_in_telegram(client, service)
    assert client.post("/api/v1/invites/resolve", json={"token": invite_token}).status_code == 200

    speech = client.get(f"/api/v1/interviews/{interview_id}/questions/{current['id']}/speech")
    assert speech.status_code == 200
    assert speech.content.startswith(b"RIFF")

    submitted_questions: list[str] = []
    follow_up_was_added = False
    while current is not None:
        submitted_questions.append(current["id"])
        answer = client.post(
            f"/api/v1/interviews/{interview_id}/answers",
            data={"questionId": current["id"], "durationSeconds": "12"},
            files={
                "audio": (
                    "answer.webm",
                    f"TEXT:Подтверждённый ответ {len(submitted_questions)} про Python".encode(),
                    "audio/webm",
                ),
                "video": ("answer-video.webm", b"video-bytes", "video/webm"),
            },
        )
        if len(submitted_questions) == 1:
            assert answer.status_code == 502
            interrupted_state = client.get(f"/api/v1/interviews/{interview_id}/state").json()
            assert interrupted_state["answeredQuestionIds"] == []
            assert interrupted_state["currentQuestion"]["id"] == current["id"]
            answer = client.post(
                f"/api/v1/interviews/{interview_id}/answers",
                data={"questionId": current["id"], "durationSeconds": "12"},
                files={
                    "audio": (
                        "answer.webm",
                        "TEXT:Подтверждённый ответ 1 про Python".encode(),
                        "audio/webm",
                    ),
                    "video": ("answer-video.webm", b"video-bytes", "video/webm"),
                },
            )
        assert answer.status_code == 200, answer.text
        assert answer.json()["transcript"].startswith("Подтверждённый ответ")
        follow_up_was_added = follow_up_was_added or answer.json()["followUpAdded"]
        current = answer.json()["nextQuestion"]
    assert follow_up_was_added
    assert len(submitted_questions) == 3

    failed_completion = client.post(f"/api/v1/interviews/{interview_id}/complete")
    assert failed_completion.status_code == 502

    completed = client.post(f"/api/v1/interviews/{interview_id}/complete")
    assert completed.status_code == 200, completed.text
    assert completed.json() == {"interviewId": interview_id, "status": "completed"}
    assert "analysis" not in completed.json()

    # Switch back to the HR demo identity; this also verifies cookie replacement.
    assert client.post("/api/v1/dev/session", json={"userId": "hr-demo"}).status_code == 200
    candidate = client.get(f"/api/v1/candidates/{candidate_id}")
    assert candidate.json()["processingStatus"] == "ready"

    late_reissue = client.post(f"/api/v1/candidates/{candidate_id}/questions/approve")
    assert late_reissue.status_code == 409
    assert client.get(f"/api/v1/candidates/{candidate_id}").json()["processingStatus"] == "ready"

    analysis = client.get(f"/api/v1/candidates/{candidate_id}/analysis")
    assert analysis.status_code == 200, analysis.text
    analysis_payload = analysis.json()
    assert analysis_payload["items"]
    assert all(item["questionId"] for item in analysis_payload["items"])
    assert all(item["body"] for item in analysis_payload["items"])
    assert all(item["evidence"] for item in analysis_payload["items"])
    assert analysis_payload["score"] is None
    assert analysis_payload["summary"] is None
    assert analysis_payload["strengths"] == []
    assert analysis_payload["growthAreas"] == []
    assert analysis_payload["unknowns"] == []
    assert len(analysis_payload["questions"]) == 3
    assert analysis_payload["recommendation"] is None
    assert analysis_payload["recommendationLocked"] is True
    assert all(
        q["answerText"].startswith("Подтверждённый ответ") for q in analysis_payload["questions"]
    )

    media = client.get(f"/api/v1/candidates/{candidate_id}/media")
    assert media.status_code == 200
    kinds = [item["kind"] for item in media.json()["assets"]]
    assert kinds.count("audio") == 3
    assert kinds.count("video") == 3
    assert "transcript" in kinds
    assert "alignment" not in kinds
    for asset in media.json()["assets"]:
        if asset["kind"] == "video":
            assert asset["playbackUrl"].endswith("disposition=inline")
        else:
            assert asset["playbackUrl"] is None

    feedback = "Спасибо за интервью. Нам не хватило глубины в практических примерах Python."
    initial = {"status": "rejected", "candidateFeedback": feedback}
    blocked = client.post(f"/api/v1/candidates/{candidate_id}/decision", json=initial)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "analysis_review_incomplete"
    assert (
        client.post(f"/api/v1/candidates/{candidate_id}/analysis/review", json=initial).status_code
        == 409
    )

    for question in analysis_payload["questions"]:
        rated = client.put(
            f"/api/v1/candidates/{candidate_id}/analysis/questions/{question['questionId']}/review",
            json={"rating": "uncertain"},
        )
        assert rated.status_code == 200, rated.text
        assert rated.json()["recommendationLocked"] is True
        assert rated.json()["recommendation"] is None
        assert rated.json()["items"] == analysis_payload["items"]
    # No time advancement is needed. Ratings survive reload, but do not unlock AI.
    rated = client.get(f"/api/v1/candidates/{candidate_id}/analysis").json()
    assert rated["reviewComplete"] is True
    assert all(q["rating"] == "uncertain" for q in rated["questions"])
    assert rated["initialDecision"] is None
    revealed = client.post(f"/api/v1/candidates/{candidate_id}/analysis/review", json=initial)
    assert revealed.status_code == 200, revealed.text
    unlocked = revealed.json()
    assert unlocked["recommendation"] == "manual_review"
    assert unlocked["recommendationLocked"] is False
    assert len(unlocked["items"]) > len(analysis_payload["items"])
    assert any(item["questionId"] is None for item in unlocked["items"])
    assert unlocked["initialDecision"]["candidateFeedback"] == feedback
    for item in unlocked["items"]:
        for evidence in item["evidence"]:
            assert evidence["quote"].startswith("Подтверждённый ответ")
            assert evidence["start"] >= 0
            assert evidence["clipStartSeconds"] is not None
            assert evidence["clipEndSeconds"] > evidence["clipStartSeconds"]

    _sign_in_telegram(client, service)
    assert client.post("/api/v1/invites/resolve", json={"token": invite_token}).status_code == 200
    assert client.get("/api/v1/candidate/outcome").json()["status"] == "pending"
    assert client.post("/api/v1/dev/session", json={"userId": "hr-demo"}).status_code == 200
    # A repeated request is safe; a changed initial judgment after reveal is not.
    repeated = client.post(f"/api/v1/candidates/{candidate_id}/analysis/review", json=initial)
    assert repeated.status_code == 200
    assert repeated.json()["initialDecision"] == unlocked["initialDecision"]
    assert (
        client.post(
            f"/api/v1/candidates/{candidate_id}/analysis/review",
            json={**initial, "status": "next_stage"},
        ).status_code
        == 409
    )
    assert (
        client.put(
            f"/api/v1/candidates/{candidate_id}/analysis/questions/{analysis_payload['questions'][0]['questionId']}/review",
            json={"rating": "positive"},
        ).status_code
        == 409
    )
    assert (
        client.get(f"/api/v1/candidates/{candidate_id}/analysis").json()["initialDecision"]
        == unlocked["initialDecision"]
    )

    decision = client.post(f"/api/v1/candidates/{candidate_id}/decision", json=initial)
    assert decision.status_code == 200, decision.text
    retry = client.post(f"/api/v1/candidates/{candidate_id}/decision", json=initial)
    assert retry.status_code == 200
    assert retry.json()["id"] == decision.json()["id"]
    assert client.get(f"/api/v1/candidates/{candidate_id}").json()["processingStatus"] == "ready"

    _sign_in_telegram(client, service)
    assert client.post("/api/v1/invites/resolve", json={"token": invite_token}).status_code == 200
    outcome = client.get("/api/v1/candidate/outcome")
    assert outcome.status_code == 200
    assert outcome.json()["status"] == "rejected"
    assert outcome.json()["candidateFeedback"] == feedback
    assert "internalReason" not in outcome.json()


class FakeAudioResponse:
    def __init__(self, data: bytes, content_type: str = "application/json") -> None:
        self.status = 200
        self.data = data
        self.headers = {"Content-Type": content_type}


class FakeAudioPool:
    def __init__(self, responses: list[FakeAudioResponse]) -> None:
        self.responses = iter(responses)
        self.requests: list[tuple[str, bytes, dict[str, str]]] = []

    def request(
        self, method: str, url: str, *, body: bytes, headers: dict[str, str]
    ) -> FakeAudioResponse:
        assert method == "POST"
        self.requests.append((url, body, headers))
        return next(self.responses)

    def clear(self) -> None:
        return None


@pytest.mark.asyncio
async def test_openrouter_audio_endpoints_use_current_wire_contract() -> None:
    pool = FakeAudioPool(
        [
            FakeAudioResponse(
                json.dumps(
                    {
                        "text": "Привет, мир!",
                        "words": [
                            {"word": "Привет", "start": 0.1, "end": 0.6},
                            {"word": "мир", "start": 0.7, "end": 1.0},
                        ],
                    }
                ).encode()
            ),
            FakeAudioResponse(b"mp3-bytes", "audio/mpeg"),
        ]
    )
    gateway = OpenRouterWorkflowAI(
        api_key="test-key",
        chat_model="chat-model",
        stt_model="openai/whisper-1",
        tts_model="openai/tts-model",
        pool=pool,  # type: ignore[arg-type]
    )

    transcript = await gateway.transcribe(b"webm-bytes", content_type="audio/webm", language="ru")
    audio, content_type = await gateway.synthesize("Вопрос", language="ru")

    assert transcript.text == "Привет, мир!"
    assert transcript.words == [
        TranscriptWord(text="Привет", start_seconds=0.1, end_seconds=0.6),
        TranscriptWord(text="мир", start_seconds=0.7, end_seconds=1.0),
    ]
    stt_url, stt_body, stt_headers = pool.requests[0]
    assert stt_url.endswith("/audio/transcriptions")
    assert stt_headers["Content-Type"] == "application/json"
    stt_payload = json.loads(stt_body)
    assert stt_payload["input_audio"] == {
        "data": base64.b64encode(b"webm-bytes").decode("ascii"),
        "format": "webm",
    }
    assert stt_payload["response_format"] == "verbose_json"
    assert stt_payload["timestamp_granularities"] == ["word"]
    tts_url, tts_body, _tts_headers = pool.requests[1]
    assert tts_url.endswith("/audio/speech")
    tts_payload = json.loads(tts_body)
    assert tts_payload["response_format"] == "mp3"
    assert audio == b"mp3-bytes"
    assert content_type == "audio/mpeg"


def test_word_alignment_handles_unicode_punctuation_and_builds_clip() -> None:
    transcript = WorkflowTranscript(
        text="Привет, сложный мир!",
        words=[
            TranscriptWord("Привет", 0.2, 0.8),
            TranscriptWord("сложный", 0.9, 1.5),
            TranscriptWord("мир", 1.6, 2.0),
        ],
    )

    alignment = WorkflowService._build_word_alignment(transcript, duration_seconds=2)

    assert alignment["words"] == [
        {"text": "Привет", "start": 0, "end": 6, "start_seconds": 0.2, "end_seconds": 0.8},
        {
            "text": "сложный",
            "start": 8,
            "end": 15,
            "start_seconds": 0.9,
            "end_seconds": 1.5,
        },
        {"text": "мир", "start": 16, "end": 19, "start_seconds": 1.6, "end_seconds": 2.0},
    ]
    assert WorkflowService._clip_for_range(alignment, 8, 20) == (0.4, 2.0)
    assert WorkflowService._clip_for_range(None, 8, 20) == (None, None)


def test_preexisting_demo_cookie_is_rejected_when_demo_auth_disabled(workflow_client):
    client, service, _clock = workflow_client
    assert client.post("/api/v1/dev/session", json={"userId": "hr-demo"}).status_code == 200
    service.allow_demo_auth = False
    assert client.get("/api/v1/session").status_code == 401
    assert client.get("/api/v1/positions").status_code == 401


class FixedRecommendationAI(FollowUpWorkflowAI):
    def __init__(self, recommendation: str) -> None:
        super().__init__()
        self.recommendation = recommendation

    async def analyze(self, **kwargs: Any) -> AnalysisDraft:
        from dataclasses import replace

        return replace(await super().analyze(**kwargs), recommendation=self.recommendation)


def _ready_review_candidate(client: TestClient, service: WorkflowService) -> tuple[str, str]:
    _, candidate_id, _ = _create_hr_position_and_candidate(client, max_follow_up_questions=0)
    approval = client.post(f"/api/v1/candidates/{candidate_id}/questions/approve").json()
    interview_id, token = approval["interviewId"], approval["inviteToken"]
    _sign_in_telegram(client, service)
    assert client.post("/api/v1/invites/resolve", json={"token": token}).status_code == 200
    state = client.post(
        f"/api/v1/interviews/{interview_id}/start", json={"consentToRecording": True}
    ).json()
    question = state["currentQuestion"]
    while question:
        answer = client.post(
            f"/api/v1/interviews/{interview_id}/answers",
            data={"questionId": question["id"]},
            files={
                "audio": ("answer.webm", b"TEXT:Python answer", "audio/webm"),
                "video": ("answer.webm", b"test-video", "video/webm"),
            },
        )
        assert answer.status_code == 200, answer.text
        question = answer.json()["nextQuestion"]
    assert client.post(f"/api/v1/interviews/{interview_id}/complete").status_code == 200
    assert client.post("/api/v1/dev/session", json={"userId": "hr-demo"}).status_code == 200
    return candidate_id, token


@pytest.mark.parametrize(
    ("recommendation", "initial_status", "final_status", "needs_reason"),
    [
        ("fit", "rejected", "next_stage", True),
        ("not_fit", "next_stage", "rejected", True),
        ("fit", "next_stage", "next_stage", False),
        ("not_fit", "rejected", "rejected", False),
        ("not_fit", "next_stage", "next_stage", False),
        ("fit", "rejected", "rejected", False),
        ("manual_review", "next_stage", "next_stage", False),
    ],
)
def test_human_decision_ai_reversal_requires_reason(
    workflow_client: tuple[TestClient, WorkflowService, MutableClock],
    recommendation: str,
    initial_status: str,
    final_status: str,
    needs_reason: bool,
) -> None:
    client, service, _clock = workflow_client
    service.ai = FixedRecommendationAI(recommendation)
    candidate_id, token = _ready_review_candidate(client, service)
    path = f"/api/v1/candidates/{candidate_id}"
    questions = client.get(f"{path}/analysis").json()["questions"]
    for question in questions:
        assert (
            client.put(
                f"{path}/analysis/questions/{question['questionId']}/review",
                json={"rating": "positive"},
            ).status_code
            == 200
        )
    # Whitespace is not feedback. Reject it for both outcomes.
    assert (
        client.post(
            f"{path}/analysis/review", json={"status": initial_status, "candidateFeedback": "   "}
        ).status_code
        == 422
    )
    initial = {"status": initial_status, "candidateFeedback": "Наш первоначальный фидбэк"}
    assert client.post(f"{path}/analysis/review", json=initial).status_code == 200
    final = {"status": final_status, "candidateFeedback": "Наш окончательный фидбэк"}
    result = client.post(f"{path}/decision", json=final)
    if needs_reason:
        assert result.status_code == 422
        assert result.json()["error"]["details"]["field"] == "changeReason"
        assert (
            client.post(f"{path}/decision", json={**final, "changeReason": "   "}).status_code
            == 422
        )
        final["changeReason"] = "ИИ указал на упущенный мной аргумент в ответе"
        result = client.post(f"{path}/decision", json=final)
    assert result.status_code == 200, result.text
    persisted = client.get(f"{path}/analysis").json()
    assert persisted["initialDecision"]["status"] == initial_status
    assert persisted["initialDecision"]["candidateFeedback"] == initial["candidateFeedback"]
    assert persisted["finalDecision"]["status"] == final_status
    assert persisted["changeReason"] == final.get("changeReason", "")
    # Candidate sees only the final human-approved outcome, never the internal reason.
    _sign_in_telegram(client, service)
    assert client.post("/api/v1/invites/resolve", json={"token": token}).status_code == 200
    outcome = client.get("/api/v1/candidate/outcome").json()
    assert outcome["status"] == final_status
    assert outcome["candidateFeedback"] == final["candidateFeedback"]
    assert "changeReason" not in outcome and "initialDecision" not in outcome
    assert client.get(f"{path}/analysis").status_code == 403


def test_question_ratings_cannot_use_another_candidates_question(
    workflow_client: tuple[TestClient, WorkflowService, MutableClock],
) -> None:
    client, service, _ = workflow_client
    candidate_id, token = _ready_review_candidate(client, service)
    _, _, other_questions = _create_hr_position_and_candidate(client)
    path = f"/api/v1/candidates/{candidate_id}/analysis"
    assert (
        client.put(
            f"{path}/questions/{other_questions[0]['id']}/review", json={"rating": "positive"}
        ).status_code
        == 404
    )
    questions = client.get(path).json()["questions"]
    question_path = f"{path}/questions/{questions[0]['questionId']}/review"
    assert client.put(question_path, json={"rating": "fake"}).status_code == 422
    assert client.put(question_path, json={"rating": "positive"}).status_code == 200
    assert client.put(question_path, json={"rating": "negative"}).status_code == 200
    assert client.get(path).json()["questions"][0]["rating"] == "negative"
    assert (
        client.post(
            f"{path}/review", json={"status": "next_stage", "candidateFeedback": "Хорошие ответы"}
        ).status_code
        == 409
    )
    _sign_in_telegram(client, service)
    assert client.post("/api/v1/invites/resolve", json={"token": token}).status_code == 200
    assert client.put(question_path, json={"rating": "positive"}).status_code == 403


@pytest.mark.asyncio
async def test_openrouter_practice_prompt_receives_only_coarse_profile() -> None:
    model_payload = {
        "model": "chat-model",
        "provider": "test",
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "questions": [
                                {
                                    "text": "Как вы начнёте разбирать учебную ситуацию?",
                                    "topic": "Разбор ситуации",
                                    "answerSeconds": 60,
                                }
                            ]
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ],
    }
    pool = FakeAudioPool([FakeAudioResponse(json.dumps(model_payload).encode())])
    gateway = OpenRouterWorkflowAI(
        api_key="test-key",
        chat_model="chat-model",
        stt_model="stt-model",
        tts_model="tts-model",
        pool=pool,  # type: ignore[arg-type]
    )

    questions = await gateway.generate_practice_questions(
        role_family="backend",
        level_band="middle",
        question_count=1,
        language="ru",
    )

    assert questions[0].text.startswith("Как вы")
    _url, body, _headers = pool.requests[0]
    request_payload = json.loads(body)
    user_payload = json.loads(request_payload["messages"][1]["content"])
    assert set(user_payload) == {
        "broadTopics", "roleFamily", "levelBand", "questionCount", "language"
    }
    serialized = json.dumps(user_payload, ensure_ascii=False).casefold()
    assert all(
        forbidden not in serialized
        for forbidden in ("vacancy", "resume", "requirements", "seedquestions")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("questions", [
    None, 5, {}, [], [None],
    [{"text": None, "topic": "Practice", "answerSeconds": 60}],
    [{"text": "Question", "topic": None, "answerSeconds": 60}],
    [{"text": "Question", "topic": "Practice", "answerSeconds": "oops"}],
    [{"text": "Question", "topic": "Practice", "answerSeconds": None}],
    [{"text": "Question", "topic": "Practice", "answerSeconds": True}],
])
async def test_invalid_practice_output_raises_provider_error(questions):
    response = {"choices": [{"message": {"content": json.dumps({"questions": questions})}}]}
    pool = FakeAudioPool([FakeAudioResponse(json.dumps(response).encode())])
    gateway = OpenRouterWorkflowAI(
        api_key="test-key", chat_model="chat-model", stt_model="stt", tts_model="tts", pool=pool,
    )
    with pytest.raises(WorkflowProviderError):
        await gateway.generate_practice_questions(
            role_family="general", level_band="middle", question_count=1, language="ru",
        )
