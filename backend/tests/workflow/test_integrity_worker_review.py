from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from test_integrity_worker import worker_setup as _worker_setup

from interview_api.workflow.integrity_ai import IntegrityAIResult
from interview_api.workflow.integrity_entities import (
    IntegrityEventRow,
    IntegrityJobRow,
    IntegritySessionRow,
)

worker_setup = _worker_setup


@pytest.mark.asyncio
async def test_session_status_reflects_actual_job_progress(worker_setup):
    worker, repository, ai = worker_setup
    ai.analyze = AsyncMock(return_value=IntegrityAIResult([], 0.001, {}))
    job = await worker.claim()
    async with repository._sessions() as db:
        assert (await db.get(IntegritySessionRow, "session")).status == "analyzing"
    await worker.process(job)
    async with repository._sessions() as db:
        assert (await db.get(IntegritySessionRow, "session")).status == "completed"
    async with repository._sessions.begin() as db:
        db.add(
            IntegrityJobRow(
                id="second",
                session_id="session",
                interview_id="interview",
                start_ms=115_000,
                end_ms=235_000,
                status="failed",
                attempts=3,
            )
        )
        await worker.update_session_status(db, "session")
    async with repository._sessions() as db:
        assert (await db.get(IntegritySessionRow, "session")).status == "partial"


@pytest.mark.asyncio
async def test_browser_evidence_persisted_even_when_vlm_unavailable(worker_setup):
    worker, repository, ai = worker_setup
    async with repository._sessions.begin() as db:
        db.add(
            IntegrityEventRow(
                id="event",
                session_id="session",
                interview_id="interview",
                client_event_id="event",
                type="focus_lost",
                offset_ms=20_000,
                duration_ms=1000,
                payload={},
            )
        )
    worker.prepare = AsyncMock(
        return_value=[SimpleNamespace(id="video", start_ms=0, end_ms=120_000)]
    )
    await worker.process(await worker.claim())
    ai.analyze.assert_awaited_once()
    payload = worker.service.add_finding.await_args.kwargs["payload"]
    assert payload["source"] == "browser"
    assert payload["evidenceRefs"] == [{"mediaId": "video", "startMs": 20_000, "endMs": 21_000}]
    assert "не подтверждает нарушение" in payload["limitations"][0]
    async with repository._sessions() as db:
        assert await db.scalar(select(IntegrityJobRow.status)) == "pending"


@pytest.mark.asyncio
async def test_interval_transcript_uses_anchors_outside_window_and_real_words(worker_setup):
    worker, _, _ = worker_setup
    worker.workflow.repository.list_answers_with_questions = AsyncMock(
        return_value=[
            (SimpleNamespace(transcript="Earlier"), SimpleNamespace(id="past", text="Past")),
            (SimpleNamespace(transcript="Current"), SimpleNamespace(id="current", text="Current")),
            (SimpleNamespace(transcript="Later"), SimpleNamespace(id="future", text="Future")),
        ]
    )
    worker.workflow._load_answer_alignments = AsyncMock(
        return_value={
            "current": {
                "words": [
                    {"text": "old", "start_seconds": 5, "end_seconds": 6},
                    {"text": "current", "start_seconds": 26, "end_seconds": 27},
                    {"text": "later", "start_seconds": 35, "end_seconds": 36},
                ]
            }
        }
    )
    anchors = []
    for question_id, start, end in [
        ("past", 10_000, 50_000),
        ("current", 90_000, 130_000),
        ("future", 140_000, 160_000),
    ]:
        anchors.extend(
            [
                SimpleNamespace(question_id=question_id, type="answer_started", offset_ms=start),
                SimpleNamespace(question_id=question_id, type="answer_ended", offset_ms=end),
            ]
        )
    result = await worker.interval_transcript(
        SimpleNamespace(interview_id="interview", start_ms=115_000, end_ms=120_000), anchors
    )
    assert [entry["questionId"] for entry in result] == ["current"]
    assert result[0]["words"] == [{"text": "current", "startMs": 116_000, "endMs": 117_000}]
    assert result[0]["startMs"] == 90_000
