import asyncio

from test_workflow import (
    _create_hr_position_and_candidate,
    _sign_in_telegram,
)
from test_workflow import (
    workflow_client as _workflow_client,
)

workflow_client = _workflow_client


def prepare(client, service, *, enabled=True):
    service.repository.integrity_enabled_for_new_interviews = enabled
    _, candidate_id, questions = _create_hr_position_and_candidate(
        client, max_follow_up_questions=0
    )
    approval = client.post(f"/api/v1/candidates/{candidate_id}/questions/approve").json()
    _sign_in_telegram(client, service)
    briefing = client.post("/api/v1/invites/resolve", json={"token": approval["inviteToken"]})
    assert briefing.status_code == 200
    return candidate_id, approval["interviewId"], questions, briefing.json()


def capture(client, interview_id):
    response = client.post(
        f"/api/v1/interviews/{interview_id}/integrity/start",
        json={
            "clientSessionId": "capture-client",
            "cameraActive": True,
            "microphoneActive": True,
            "screenActive": True,
            "displaySurface": "monitor",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_integrity_blocks_all_next_question_disclosure_until_capture_recovers(workflow_client):
    client, service, _ = workflow_client
    _, interview_id, questions, briefing = prepare(client, service)
    assert briefing["integrityEnabled"] is True
    assert briefing["currentQuestion"] is None
    assert briefing["integrityBlocked"] is True
    capture(client, interview_id)
    started = client.post(
        f"/api/v1/interviews/{interview_id}/start", json={"consentToRecording": True}
    ).json()
    current = started["currentQuestion"]
    assert current is not None
    lost = client.post(
        f"/api/v1/interviews/{interview_id}/integrity/heartbeat",
        json={
            "cameraActive": False,
            "microphoneActive": False,
            "screenActive": True,
            "displaySurface": "monitor",
            "offsetMs": 1000,
        },
    )
    assert lost.status_code == 200
    answer_data = {"questionId": current["id"], "durationSeconds": "12"}
    answer_files = {
        "audio": ("answer.webm", "TEXT:Я проверил решение тестами".encode(), "audio/webm"),
        "video": ("answer.webm", b"video-bytes", "video/webm"),
    }
    response = client.post(
        f"/api/v1/interviews/{interview_id}/answers", data=answer_data, files=answer_files
    )
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["answerId"]
    assert answer["nextQuestion"] is None
    assert answer["integrityBlocked"] is True
    repeat = client.post(
        f"/api/v1/interviews/{interview_id}/answers", data=answer_data, files=answer_files
    )
    assert repeat.status_code == 200, repeat.text
    assert repeat.json()["answerId"] == answer["answerId"]
    assert repeat.json()["nextQuestion"] is None
    state = client.get(f"/api/v1/interviews/{interview_id}/state").json()
    assert state["currentQuestion"] is None
    assert current["id"] in state["answeredQuestionIds"]
    assert client.get(f"/api/v1/interviews/{interview_id}").json()["currentQuestion"] is None
    future = next(q for q in questions if q["id"] != current["id"])
    speech = client.get(f"/api/v1/interviews/{interview_id}/questions/{future['id']}/speech")
    assert speech.status_code == 409
    restored = client.post(
        f"/api/v1/interviews/{interview_id}/integrity/heartbeat",
        json={
            "cameraActive": True,
            "microphoneActive": True,
            "screenActive": True,
            "displaySurface": "monitor",
            "offsetMs": 2000,
        },
    )
    assert restored.status_code == 200
    resumed = client.get(f"/api/v1/interviews/{interview_id}/state").json()
    assert resumed["currentQuestion"]["id"] == future["id"]
    assert resumed["integrityBlocked"] is False
    client.post(
        f"/api/v1/interviews/{interview_id}/integrity/heartbeat",
        json={
            "cameraActive": False,
            "microphoneActive": False,
            "screenActive": False,
            "displaySurface": "monitor",
            "offsetMs": 3000,
        },
    )
    final = client.post(
        f"/api/v1/interviews/{interview_id}/answers",
        data={"questionId": future["id"], "durationSeconds": "12"},
        files=answer_files,
    )
    assert final.status_code == 200, final.text
    assert final.json()["nextQuestion"] is None
    assert final.json()["integrityBlocked"] is False
    assert client.post(f"/api/v1/interviews/{interview_id}/complete").status_code == 200


def test_feature_flag_only_applies_to_new_interviews(workflow_client):
    client, service, _ = workflow_client
    _, interview_id, _, briefing = prepare(client, service, enabled=False)
    assert briefing["integrityEnabled"] is False
    service.repository.integrity_enabled_for_new_interviews = True
    stored = asyncio.run(service.repository.get_interview(interview_id))
    assert stored.integrity_enabled is False
    response = client.post(
        f"/api/v1/interviews/{interview_id}/integrity/start",
        json={
            "clientSessionId": "capture-client",
            "cameraActive": True,
            "microphoneActive": True,
            "screenActive": True,
            "displaySurface": "monitor",
        },
    )
    assert response.status_code == 404
    started = client.post(
        f"/api/v1/interviews/{interview_id}/start", json={"consentToRecording": True}
    ).json()
    assert started["currentQuestion"] is not None
    assert started["integrityBlocked"] is False


def test_integrity_candidate_api_requires_own_candidate_session(workflow_client):
    client, service, _ = workflow_client
    _, interview_id, _, _ = prepare(client, service)
    _sign_in_telegram(client, service, telegram_id=1002)
    response = client.post(
        f"/api/v1/interviews/{interview_id}/integrity/start",
        json={
            "clientSessionId": "other-capture",
            "cameraActive": True,
            "microphoneActive": True,
            "screenActive": True,
            "displaySurface": "monitor",
        },
    )
    assert response.status_code == 403


def test_capture_failure_does_not_gate_completion_after_deadline(workflow_client):
    client, service, clock = workflow_client
    _, interview_id, _, _ = prepare(client, service)
    capture(client, interview_id)
    started = client.post(
        f"/api/v1/interviews/{interview_id}/start", json={"consentToRecording": True}
    ).json()
    assert started["currentQuestion"]
    clock.advance(20 * 60 + 1)
    state = client.get(f"/api/v1/interviews/{interview_id}/state").json()
    assert state["remainingSeconds"] == 0
    assert state["currentQuestion"] is None
    assert state["integrityBlocked"] is False
