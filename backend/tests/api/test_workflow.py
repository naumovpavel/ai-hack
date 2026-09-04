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
from interview_api.workflow.ai import AnalysisDraft, DeterministicWorkflowAI, FollowUpProposal
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
        settings=Settings(app_env="test", _env_file=None),
        workflow_service=service,
        workflow_engine=engine,
    )
    with TestClient(app) as client:
        yield client, service, clock
    asyncio.run(engine.dispose())


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


def test_briefing_reports_when_follow_ups_are_disabled(
    workflow_client: tuple[TestClient, WorkflowService, MutableClock],
) -> None:
    client, _service, _clock = workflow_client
    _position_id, candidate_id, _questions = _create_hr_position_and_candidate(
        client, max_follow_up_questions=0
    )
    approval = client.post(f"/api/v1/candidates/{candidate_id}/questions/approve").json()

    briefing = client.post("/api/v1/invites/resolve", json={"token": approval["inviteToken"]})

    assert briefing.status_code == 200
    assert briefing.json()["allowsFollowUps"] is False


def test_answer_finishing_at_deadline_is_saved_and_ends_interview(
    workflow_client: tuple[TestClient, WorkflowService, MutableClock],
) -> None:
    client, _service, clock = workflow_client
    _position_id, candidate_id, _questions = _create_hr_position_and_candidate(client)
    approval = client.post(f"/api/v1/candidates/{candidate_id}/questions/approve").json()
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
        client.get(f"/api/v1/candidates/{candidate_id}").json()["processingStatus"]
        == "in_progress"
    )
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
            interrupted_state = client.get(
                f"/api/v1/interviews/{interview_id}/state"
            ).json()
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
    assert analysis_payload["recommendation"] is None
    assert analysis_payload["recommendationLocked"] is True
    for item in analysis_payload["items"]:
        for evidence in item["evidence"]:
            assert evidence["quote"].startswith("Подтверждённый ответ")
            assert evidence["start"] >= 0

    media = client.get(f"/api/v1/candidates/{candidate_id}/media")
    assert media.status_code == 200
    kinds = [item["kind"] for item in media.json()["assets"]]
    assert kinds.count("audio") == 3
    assert kinds.count("video") == 3
    assert "transcript" in kinds

    blocked = client.post(
        f"/api/v1/candidates/{candidate_id}/decision",
        json={"status": "next_stage"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "analysis_review_incomplete"

    for item in analysis_payload["items"]:
        item_id = item["id"]
        opened = client.post(
            f"/api/v1/candidates/{candidate_id}/analysis/review",
            json={"itemId": item_id, "event": "open", "visible": True, "focused": True},
        )
        assert opened.status_code == 200
        progress = opened
        for _attempt in range(10):
            clock.advance(service.heartbeat_grace_seconds)
            progress = client.post(
                f"/api/v1/candidates/{candidate_id}/analysis/review",
                json={
                    "itemId": item_id,
                    "event": "heartbeat",
                    "visible": True,
                    "focused": True,
                },
            )
            if progress.json()["reviewComplete"]:
                break
        assert progress.json()["reviewComplete"]

    unlocked = client.get(f"/api/v1/candidates/{candidate_id}/analysis").json()
    assert unlocked["recommendation"] == "manual_review"
    assert unlocked["recommendationLocked"] is False

    reason = "Не подтверждена необходимая глубина Python"
    feedback = "Спасибо за интервью. Нам не хватило глубины в практических примерах Python."
    pasted = client.post(
        f"/api/v1/candidates/{candidate_id}/decision",
        json={
            "status": "rejected",
            "internalReason": reason,
            "candidateFeedback": feedback,
            "internalReasonPasteEvents": 1,
            "internalReasonTypedCharacters": len(reason),
        },
    )
    assert pasted.status_code == 422

    decision = client.post(
        f"/api/v1/candidates/{candidate_id}/decision",
        json={
            "status": "rejected",
            "internalReason": reason,
            "candidateFeedback": feedback,
            "internalReasonPasteEvents": 0,
            "internalReasonTypedCharacters": len(reason),
        },
    )
    assert decision.status_code == 200, decision.text
    assert client.get(f"/api/v1/candidates/{candidate_id}").json()["processingStatus"] == "ready"

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
            FakeAudioResponse(json.dumps({"text": "Привет"}).encode()),
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

    assert transcript == "Привет"
    stt_url, stt_body, stt_headers = pool.requests[0]
    assert stt_url.endswith("/audio/transcriptions")
    assert stt_headers["Content-Type"] == "application/json"
    stt_payload = json.loads(stt_body)
    assert stt_payload["input_audio"] == {
        "data": base64.b64encode(b"webm-bytes").decode("ascii"),
        "format": "webm",
    }
    tts_url, tts_body, _tts_headers = pool.requests[1]
    assert tts_url.endswith("/audio/speech")
    tts_payload = json.loads(tts_body)
    assert tts_payload["response_format"] == "mp3"
    assert audio == b"mp3-bytes"
    assert content_type == "audio/mpeg"
