from __future__ import annotations

import asyncio
import csv
import io
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from test_workflow import workflow_client as _workflow_client

from interview_api.workflow.research import ResearchRow, token_hash

# Register the shared fixture under a local name without shadowing its import.
research_client = _workflow_client

BASELINE = {
    "hadInterview": "yes",
    "hadAiInterview": "no",
    "experienceLiked": None,
    "experienceFactors": [],
    "experienceReason": "",
    "trust": "no",
    "trustFactors": [],
    "trustReason": "Не понимаю критерии",
    "readiness": "no",
    "readinessFactors": [],
    "readinessReason": "Хочу знать условия",
}
FOLLOWUP = {
    "trust": "yes",
    "trustFactors": [],
    "trustReason": "Можно проверить выводы",
    "readiness": "yes",
    "readinessFactors": [],
    "readinessReason": "Понятен процесс",
    "solutionLiked": "yes",
    "solutionFactors": [],
    "solutionReason": "Понятна роль человека",
}
PREFIX = "/api/v1/research"


def headers():
    return {"X-Survey-Token": str(uuid4())}


def sign_in(client, service, username="wift657", role="candidate", telegram_id=1001):
    async def create():
        account = await service.repository.register_telegram_account(
            telegram_id=telegram_id,
            chat_id=telegram_id,
            username=username,
            first_name="Research",
            last_name="Owner",
            now=service._now(),
        )
        actor = await service.repository.get_user(account.user_id)
        token, _ = await service.session_for_telegram_actor(actor, role=role)
        return token

    client.cookies.clear()
    client.cookies.set(service.cookie_name, asyncio.run(create()))


def finish(client, token, baseline=None, followup=None):
    result = client.post(f"{PREFIX}/baseline", headers=token, json=baseline or BASELINE)
    assert result.status_code == 200, result.text
    result = client.post(f"{PREFIX}/demo", headers=token, json={"demoVersion": "signal-demo-v2"})
    assert result.status_code == 200, result.text
    result = client.post(f"{PREFIX}/complete", headers=token, json=followup or FOLLOWUP)
    assert result.status_code == 200, result.text
    return result.json()


def test_public_flow_recovery_and_immutable_answers(research_client):
    client, service, _ = research_client
    token = headers()
    assert not client.cookies
    assert client.get(f"{PREFIX}/session", headers=token).status_code == 404
    assert client.post(f"{PREFIX}/complete", headers=token, json=FOLLOWUP).status_code == 404
    first = client.post(f"{PREFIX}/baseline", headers=token, json=BASELINE)
    assert first.status_code == 200
    assert first.json()["status"] == "baseline"
    assert client.post(f"{PREFIX}/complete", headers=token, json=FOLLOWUP).status_code == 409
    assert client.get(f"{PREFIX}/session", headers=headers()).status_code == 404
    changed = {**BASELINE, "trust": "yes"}
    assert client.post(f"{PREFIX}/baseline", headers=token, json=changed).status_code == 409
    completed = finish(client, token)
    assert completed["status"] == "complete"
    assert finish(client, token) == completed
    assert client.get(f"{PREFIX}/session", headers=token).json() == completed
    assert (
        client.post(
            f"{PREFIX}/complete", headers=token, json={**FOLLOWUP, "trust": "no"}
        ).status_code
        == 409
    )
    assert not client.cookies  # Participating never creates/requires a Telegram session.
    sign_in(client, service)
    assert client.get(f"{PREFIX}/results").json()["started"] == 1


@pytest.mark.parametrize("suffix", ["results", "results.csv"])
def test_results_require_exact_verified_telegram_owner(research_client, suffix):
    client, service, _ = research_client
    url = f"{PREFIX}/{suffix}"
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"X-Telegram-Username": "wift657"}).status_code == 401
    client.post("/api/v1/dev/session", json={"userId": "hr-demo"})
    assert client.get(url).status_code == 403
    sign_in(client, service, username="someone_else", role="hr", telegram_id=2002)
    assert client.get(url).status_code == 403
    sign_in(client, service, username="wift657_extra", telegram_id=2003)
    assert client.get(url).status_code == 403
    for role in ("hr", "candidate"):
        sign_in(client, service, username="Wift657", role=role)
        response = client.get(url)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"


def test_paired_binary_metrics_exclude_dropouts_and_show_all_transitions(research_client):
    client, service, _ = research_client
    finish(client, headers())
    finish(
        client,
        headers(),
        {**BASELINE, "trust": "yes", "readiness": "yes"},
        {**FOLLOWUP, "trust": "no", "readiness": "yes"},
    )
    finish(
        client,
        headers(),
        {**BASELINE, "trust": "yes"},
        {**FOLLOWUP, "trust": "yes", "readiness": "no"},
    )
    finish(client, headers(), BASELINE, {**FOLLOWUP, "trust": "no"})
    client.post(f"{PREFIX}/baseline", headers=headers(), json={**BASELINE, "trust": "yes"})
    sign_in(client, service)
    data = client.get(f"{PREFIX}/results").json()
    assert (data["started"], data["demoViewed"], data["completed"]) == (5, 4, 4)
    assert data["trust"] == {
        "pairs": 4,
        "beforeYes": 2,
        "afterYes": 2,
        "beforePercent": 50,
        "afterPercent": 50,
        "deltaPp": 0,
        "noToYes": 1,
        "yesToNo": 1,
        "yesToYes": 1,
        "noToNo": 1,
    }
    assert data["readiness"] == {
        "pairs": 4,
        "beforeYes": 1,
        "afterYes": 3,
        "beforePercent": 25,
        "afterPercent": 75,
        "deltaPp": 50,
        "noToYes": 2,
        "yesToNo": 0,
        "yesToYes": 1,
        "noToNo": 1,
    }


def test_empty_results_and_csv_reasons_without_tokens(research_client):
    client, service, _ = research_client
    sign_in(client, service)
    metric = client.get(f"{PREFIX}/results").json()["trust"]
    assert metric["pairs"] == 0 and metric["beforePercent"] is None and metric["deltaPp"] is None
    token = headers()
    finish(
        client,
        token,
        {**BASELINE, "trustReason": '=HYPERLINK("x")'},
        {**FOLLOWUP, "solutionReason": "Первая строка\nВторая, с запятой"},
    )
    response = client.get(f"{PREFIX}/results.csv")
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert len(rows) == 1
    assert rows[0]["before_trustReason"].startswith("'=")
    assert rows[0]["after_solutionReason"] == "Первая строка\nВторая, с запятой"
    assert rows[0]["trust_transition"] == "no -> yes"
    assert token["X-Survey-Token"] not in response.text
    assert "token_hash" not in response.text


@pytest.mark.parametrize(
    "patch",
    [
        {"trust": 0},
        {"trust": 10},
        {"trust": True},
        {"trust": None},
        {"trust": "unsure"},
        {"trustReason": "   "},
        {"readinessReason": "x" * 2001},
        {"hadAiInterview": "yes"},
        {"hadInterview": "no", "hadAiInterview": "yes"},
        {"trust": "yes", "trustFactors": ["automatic_rejection"]},
        {"readiness": "no", "readinessFactors": ["convenient_time"]},
        {"experienceLiked": "yes", "experienceFactors": ["useful_feedback"]},
    ],
)
def test_reject_invalid_baseline(research_client, patch):
    client, _, _ = research_client
    assert (
        client.post(f"{PREFIX}/baseline", headers=headers(), json={**BASELINE, **patch}).status_code
        == 422
    )


def test_prior_experience_and_version_validation(research_client):
    client, _, _ = research_client
    token = headers()
    baseline = {
        **BASELINE,
        "hadAiInterview": "yes",
        "experienceLiked": "no",
        "experienceReason": "Не получил обратную связь",
    }
    assert client.post(f"{PREFIX}/baseline", json=baseline).status_code == 422
    assert client.post(f"{PREFIX}/baseline", headers=token, json=baseline).status_code == 200
    assert (
        client.post(f"{PREFIX}/demo", headers=token, json={"demoVersion": "future"}).status_code
        == 422
    )


def test_trust_choices_and_free_text_are_saved_and_exported(research_client):
    client, service, _ = research_client
    token = headers()
    before = {
        **BASELINE,
        "trustFactors": ["misunderstanding", "automatic_rejection"],
        "trustReason": "",
    }
    after = {**FOLLOWUP, "trustFactors": ["human_review"], "trustReason": "Есть уточнение"}
    result = finish(client, token, before, after)
    assert result["baseline"]["trustFactors"] == ["misunderstanding", "automatic_rejection"]
    assert result["baseline"]["trustReason"] == ""
    assert result["followup"]["trustFactors"] == ["human_review"]
    assert result["followup"]["trustReason"] == "Есть уточнение"
    sign_in(client, service)
    response = client.get(f"{PREFIX}/results.csv")
    row = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))[0]
    assert "неправильно поймёт" in row["before_trustFactors"]
    assert "автоматического отказа" in row["before_trustFactors"]
    assert row["after_trustReason"] == "Есть уточнение"


@pytest.mark.parametrize("factors", [[], ["unknown"], ["misunderstanding", "misunderstanding"]])
def test_invalid_or_empty_trust_choices_rejected(research_client, factors):
    client, _, _ = research_client
    response = client.post(
        f"{PREFIX}/baseline",
        headers=headers(),
        json={**BASELINE, "trustFactors": factors, "trustReason": ""},
    )
    assert response.status_code == 422


def test_reason_frequency_denominators_follow_the_branch(research_client):
    client, service, _ = research_client
    finish(
        client,
        headers(),
        {**BASELINE, "trustFactors": ["automatic_rejection"]},
        {**FOLLOWUP, "trustFactors": ["human_review"]},
    )
    finish(
        client,
        headers(),
        BASELINE,
        {**FOLLOWUP, "trust": "no", "trustFactors": ["automatic_rejection"]},
    )
    sign_in(client, service)
    groups = client.get(f"{PREFIX}/results").json()["reasons"]
    no_group = next(
        group for group in groups if group["question"] == "trust" and group["answer"] == "no"
    )
    assert (no_group["beforeRespondents"], no_group["afterRespondents"]) == (2, 1)
    reason = next(option for option in no_group["options"] if option["id"] == "automatic_rejection")
    assert (reason["before"], reason["after"]) == (1, 1)
    assert reason["hypothesis"] == "PH5"


def test_legacy_scores_preserved_but_excluded_from_binary_results(research_client):
    client, service, _ = research_client
    old_token = headers()

    async def insert_old():
        async with service.repository._sessions.begin() as session:
            session.add(
                ResearchRow(
                    id=str(uuid4()),
                    token_hash=token_hash(UUID(old_token["X-Survey-Token"])),
                    survey_version="signal-v1",
                    baseline={"trustScore": 2, "readinessScore": 5},
                    followup={"trustScore": 9, "readinessScore": 6},
                    completed_at=service._now(),
                )
            )

    asyncio.run(insert_old())
    finish(client, headers())
    assert client.get(f"{PREFIX}/session", headers=old_token).status_code == 404
    assert client.post(f"{PREFIX}/baseline", headers=old_token, json=BASELINE).status_code == 409
    sign_in(client, service)
    assert client.get(f"{PREFIX}/results").json()["completed"] == 1
    response = client.get(f"{PREFIX}/results.csv")
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert len(rows) == 2
    old = next(row for row in rows if row["survey_version"] == "signal-v1")
    assert old["before_trustScore"] == "2" and old["after_trustScore"] == "9"


def test_previous_demo_is_retained_without_mixing_current_results(research_client):
    client, service, _ = research_client
    old_token = headers()
    finish(client, old_token)

    async def mark_previous_demo():
        async with service.repository._sessions.begin() as session:
            row = await session.scalar(
                select(ResearchRow).where(
                    ResearchRow.token_hash == token_hash(UUID(old_token["X-Survey-Token"]))
                )
            )
            row.demo_version = "signal-v1"

    asyncio.run(mark_previous_demo())
    finish(client, headers())
    sign_in(client, service)
    result = client.get(f"{PREFIX}/results").json()
    assert result["completed"] == 1 and result["trust"]["pairs"] == 1
    rows = list(
        csv.DictReader(io.StringIO(client.get(f"{PREFIX}/results.csv").content.decode("utf-8-sig")))
    )
    assert {row["demo_version"] for row in rows} == {"signal-v1", "signal-demo-v2"}
