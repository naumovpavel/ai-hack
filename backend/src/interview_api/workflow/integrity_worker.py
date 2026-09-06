"""Single PostgreSQL advisory-lock worker; queue state survives application restarts."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select, text, update

from interview_api.workflow.entities import InterviewRow
from interview_api.workflow.integrity_ai import IntegrityAI, IntegrityAIResult
from interview_api.workflow.integrity_entities import (
    IntegrityChunkRow,
    IntegrityEventRow,
    IntegrityJobRow,
    IntegrityMediaRow,
    IntegritySessionRow,
)
from interview_api.workflow.integrity_media import IntegrityMedia

logger = logging.getLogger(__name__)
WORKER_LOCK = 873251694


class IntegrityWorker:
    def __init__(self, service, *, media: IntegrityMedia, ai: IntegrityAI) -> None:
        self.service = service
        self.workflow = service.workflow
        self.sessions = self.workflow.repository._sessions
        self.media = media
        self.ai = ai
        self.task: asyncio.Task | None = None

    async def start(self) -> None:
        self.task = asyncio.create_task(self.run(), name="integrity-worker")

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        self.ai.close()

    async def run(self) -> None:
        while True:
            try:
                # Keep the same DB connection for the lifetime of the advisory lock.
                # Multiple API processes therefore still run only ONE analysis at a time.
                async with self.sessions() as lock_session:
                    postgres = lock_session.bind.dialect.name == "postgresql"
                    acquired = not postgres or await lock_session.scalar(
                        text("SELECT pg_try_advisory_lock(:key)"), {"key": WORKER_LOCK}
                    )
                    if not acquired:
                        await asyncio.sleep(10)
                        continue
                    try:
                        await self.recover()
                        while True:
                            if postgres:
                                # Detect a lost lock connection before claiming further work.
                                await lock_session.execute(text("SELECT 1"))
                            await self.expire_media()
                            await self.mark_interrupted_capture()
                            job = await self.claim()
                            if job:
                                await self.process(job)
                            else:
                                await asyncio.sleep(5)
                    finally:
                        if postgres:
                            await lock_session.execute(
                                text("SELECT pg_advisory_unlock(:key)"), {"key": WORKER_LOCK}
                            )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Integrity worker failed; answer analysis is unaffected")
                await asyncio.sleep(10)

    async def recover(self) -> None:
        async with self.sessions.begin() as db:
            session_ids = set()
            for job in await db.scalars(
                select(IntegrityJobRow).where(IntegrityJobRow.status == "running")
            ):
                session_ids.add(job.session_id)
                job.status = "pending" if job.attempts < 3 or job.result_payload else "failed"
                job.error = "Worker restarted; interrupted interval can be retried."
                job.locked_at = None
            for session_id in session_ids:
                await self.update_session_status(db, session_id)

    @staticmethod
    async def update_session_status(db, session_id: str) -> None:
        session = await db.get(IntegritySessionRow, session_id)
        if session is None or session.deleted_at:
            return
        statuses = list(
            await db.scalars(
                select(IntegrityJobRow.status).where(
                    IntegrityJobRow.session_id == session_id,
                )
            )
        )
        if not statuses:
            return
        if "running" in statuses:
            session.status = "analyzing"
        elif "pending" in statuses:
            session.status = "queued"
        elif all(status == "succeeded" for status in statuses):
            session.status = "completed"
        elif "succeeded" in statuses:
            session.status = "partial"
        else:
            session.status = "failed"

    async def claim(self) -> IntegrityJobRow | None:
        async with self.sessions.begin() as db:
            job = await db.scalar(
                select(IntegrityJobRow)
                .join(IntegritySessionRow, IntegritySessionRow.id == IntegrityJobRow.session_id)
                .where(
                    IntegrityJobRow.status == "pending",
                    (IntegrityJobRow.attempts < 3) | IntegrityJobRow.result_payload.is_not(None),
                    IntegritySessionRow.deleted_at.is_(None),
                    IntegritySessionRow.expires_at > datetime.now(UTC),
                )
                .order_by(IntegrityJobRow.created_at, IntegrityJobRow.start_ms)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job:
                job.status = "running"
                if not job.result_payload:
                    job.attempts += 1
                job.locked_at = datetime.now(UTC)
                await self.update_session_status(db, job.session_id)
            return job

    async def interval_transcript(self, job, anchors) -> list[dict]:
        answers = await self.workflow.repository.list_answers_with_questions(job.interview_id)
        load = getattr(self.workflow, "_load_answer_alignments", None)
        alignments = await load(answers) if load else {}
        transcript = []
        for answer, question in answers:
            starts = [
                e.offset_ms
                for e in anchors
                if e.question_id == question.id and e.type == "answer_started"
            ]
            ends = [
                e.offset_ms
                for e in anchors
                if e.question_id == question.id and e.type == "answer_ended"
            ]
            start, end = min(starts) if starts else None, max(ends) if ends else None
            if (start is not None and start >= job.end_ms) or (
                end is not None and end <= job.start_ms
            ):
                continue
            words = []
            if start is not None:
                for word in alignments.get(question.id, {}).get("words", []):
                    try:
                        word_start = start + round(float(word["start_seconds"]) * 1000)
                        word_end = start + round(float(word["end_seconds"]) * 1000)
                        if (
                            word_end <= word_start
                            or word_start >= job.end_ms
                            or word_end <= job.start_ms
                            or (end is not None and word_end > end + 250)
                        ):
                            continue
                        words.append(
                            {"text": str(word["text"]), "startMs": word_start, "endMs": word_end}
                        )
                    except (KeyError, TypeError, ValueError, OverflowError):
                        continue
            transcript.append(
                {
                    "questionId": question.id,
                    "question": question.text,
                    "text": answer.transcript,
                    "startMs": start,
                    "endMs": end,
                    "words": words,
                    "textScope": "whole answer context; only supplied words have synchronization",
                    "alignment": "recorded_word_times" if words else "unaligned",
                }
            )
        return transcript

    async def prepare(self, job: IntegrityJobRow) -> list[IntegrityMediaRow]:
        async with self.sessions() as db:
            session = await db.get(IntegritySessionRow, job.session_id)
            interview = await db.get(InterviewRow, job.interview_id)
            if not session or not interview or session.deleted_at:
                raise ValueError("Integrity session is no longer available")
            chunks = list(
                await db.scalars(
                    select(IntegrityChunkRow).where(
                        IntegrityChunkRow.session_id == session.id,
                        IntegrityChunkRow.deleted_at.is_(None),
                    )
                )
            )
            existing = list(
                await db.scalars(
                    select(IntegrityMediaRow).where(
                        IntegrityMediaRow.session_id == session.id,
                        IntegrityMediaRow.deleted_at.is_(None),
                    )
                )
            )
        known = {(item.kind, item.stream_id) for item in existing}
        streams: dict[tuple[str, str], list] = defaultdict(list)
        for chunk in chunks:
            streams[chunk.kind, chunk.stream_id].append(chunk)
        errors = []
        for (kind, stream_id), stream_chunks in streams.items():
            if (kind, stream_id) in known:
                continue
            identifier = str(uuid5(NAMESPACE_URL, f"integrity:{session.id}:{kind}:{stream_id}"))
            key = (
                f"candidates/{interview.candidate_id}/interviews/{interview.id}/"
                f"integrity/streams/{identifier}.mp4"
            )
            try:
                prepared = await self.media.prepare_stream(stream_chunks, object_key=key)
            except Exception:
                errors.append(f"{kind}: stream preparation unavailable")
                continue
            row = IntegrityMediaRow(
                id=identifier,
                session_id=session.id,
                interview_id=interview.id,
                kind=kind,
                stream_id=stream_id,
                object_key=key,
                start_ms=prepared.start_ms,
                end_ms=prepared.end_ms,
                duration_ms=prepared.duration_ms,
                size_bytes=prepared.size_bytes,
                expires_at=session.expires_at,
            )
            async with self.sessions.begin() as db:
                # Re-check ownership after expensive conversion to avoid orphan rows.
                if not await db.get(IntegritySessionRow, session.id):
                    await self.workflow.storage.delete_owned_objects(keys=(key,), prefixes=())
                    raise ValueError("Integrity session deleted during preparation")
                db.add(row)
            existing.append(row)
        if not existing and errors:
            raise RuntimeError("Continuous media could not be prepared; check FFmpeg and chunks")
        return existing

    async def process(self, job: IntegrityJobRow) -> None:
        try:
            media = await self.prepare(job)
            async with self.sessions() as db:
                rows = list(
                    await db.scalars(
                        select(IntegrityEventRow)
                        .where(
                            IntegrityEventRow.session_id == job.session_id,
                            IntegrityEventRow.offset_ms <= job.end_ms,
                            IntegrityEventRow.offset_ms + IntegrityEventRow.duration_ms
                            >= job.start_ms,
                        )
                        .order_by(IntegrityEventRow.offset_ms)
                    )
                )
                anchors = list(
                    await db.scalars(
                        select(IntegrityEventRow).where(
                            IntegrityEventRow.session_id == job.session_id,
                            IntegrityEventRow.type.in_(["answer_started", "answer_ended"]),
                        )
                    )
                )
            transcript = await self.interval_transcript(job, anchors)
            events = [
                {
                    "id": row.id,
                    "type": row.type,
                    "startMs": row.offset_ms,
                    "endMs": row.offset_ms + row.duration_ms,
                    "questionId": row.question_id,
                    "payload": row.payload,
                }
                for row in rows
            ]
            # Grounded browser/local observations remain reviewable even if the
            # optional VLM provider fails. They never confirm a violation themselves.
            await self.save_event_observations(job, rows, media)
            if job.result_payload:
                result = IntegrityAIResult(job.result_payload["findings"], None, {})
            else:
                parts = await self.media.interval_parts(media, job.start_ms, job.end_ms)
                result = await self.ai.analyze(
                    parts=parts,
                    transcript=transcript,
                    events=events,
                    start_ms=job.start_ms,
                    end_ms=job.end_ms,
                )
                # Checkpoint before deriving findings: a crash on validation/persistence
                # can resume without paying for a successful model interval again.
                async with self.sessions.begin() as db:
                    current = await db.get(IntegrityJobRow, job.id)
                    if current:
                        current.cost_usd += result.cost_usd or 0
                        current.cost_usd_known = result.cost_usd is not None
                        current.result_payload = {"findings": result.findings}
            for draft in result.findings:
                if not isinstance(draft, dict):
                    continue
                await self.service.add_finding(
                    interview_id=job.interview_id, job_id=job.id, payload={**draft, "source": "vlm"}
                )
            async with self.sessions.begin() as db:
                current = await db.get(IntegrityJobRow, job.id)
                if current:
                    current.status = "succeeded"
                    current.error = None
                    current.completed_at = datetime.now(UTC)
                    current.locked_at = None
                    await self.update_session_status(db, current.session_id)
        except asyncio.CancelledError:
            # Leave running state for crash recovery. No successful interval is repeated.
            raise
        except Exception as exc:
            logger.warning("Integrity interval failed: %s", type(exc).__name__)
            async with self.sessions.begin() as db:
                current = await db.get(IntegrityJobRow, job.id)
                if current:
                    current.status = "pending" if current.attempts < 3 else "failed"
                    current.error = (
                        "Не удалось обработать интервал. Проверьте запись, FFmpeg и OpenRouter. "
                        "Это технический сбой, он не влияет на оценку ответов."
                    )
                    current.locked_at = None
                    await self.update_session_status(db, current.session_id)

    async def save_event_observations(self, job, events, media) -> None:
        descriptions = {
            "visibility_change": ("browser", "Вкладка интервью была скрыта"),
            "focus_lost": ("browser", "Окно интервью потеряло фокус"),
            "face_absent": ("local_heuristic", "Локальная эвристика длительно не видела лицо"),
            "head_deviation": ("local_heuristic", "Положение головы вышло за диапазон калибровки"),
            "gaze_deviation": ("local_heuristic", "Положение глаз вышло за диапазон калибровки"),
        }
        for event in events:
            if event.type not in descriptions:
                continue
            if (
                event.type == "visibility_change"
                and event.payload.get("visibilityState") != "hidden"
            ):
                continue
            source, observation = descriptions[event.type]
            start, end = event.offset_ms, event.offset_ms + max(1000, event.duration_ms)
            refs = [
                {
                    "mediaId": item.id,
                    "startMs": max(start, item.start_ms),
                    "endMs": min(end, item.end_ms),
                }
                for item in media
                if item.start_ms < end and item.end_ms > start
            ]
            if not refs:
                continue
            await self.service.add_finding(
                interview_id=job.interview_id,
                job_id=None,
                payload={
                    "source": source,
                    "category": event.type,
                    "observation": observation,
                    "reason": "Слабый сигнал для сопоставления с записью; требуется просмотр.",
                    "alternativeExplanations": [
                        "Обычное действие или отвлечение",
                        "Системное уведомление, движение или погрешность локального отслеживания",
                    ],
                    "limitations": ["Сам по себе сигнал не подтверждает нарушение"],
                    "observability": "partial",
                    "startMs": start,
                    "endMs": end,
                    "evidenceRefs": refs,
                },
            )

    async def mark_interrupted_capture(self) -> None:
        now = datetime.now(UTC)
        async with self.sessions.begin() as db:
            rows = await db.execute(
                select(IntegritySessionRow, InterviewRow)
                .join(
                    InterviewRow,
                    InterviewRow.id == IntegritySessionRow.interview_id,
                )
                .where(
                    IntegritySessionRow.finished_at.is_(None),
                    IntegritySessionRow.deleted_at.is_(None),
                )
            )
            for session, interview in rows:
                heartbeat = session.heartbeat_at or session.started_at
                if heartbeat.replace(tzinfo=UTC) > now - timedelta(minutes=5):
                    continue
                deadline = interview.deadline_at
                ended = interview.status in {"completed", "error", "analyzing", "processing"}
                if not ended and (not deadline or deadline.replace(tzinfo=UTC) > now):
                    continue
                # Do not seal an incomplete upload just because the browser went
                # offline. IndexedDB may still contain acknowledged-later chunks;
                # only the ordered client finish marker makes streams immutable.
                session.status = "awaiting_upload"

    async def expire_media(self) -> None:
        now = datetime.now(UTC)
        async with self.sessions() as db:
            expired = list(
                await db.scalars(
                    select(IntegritySessionRow).where(
                        IntegritySessionRow.expires_at <= now,
                        IntegritySessionRow.deleted_at.is_(None),
                    )
                )
            )
        for item in expired:
            async with self.sessions() as db:
                chunks = list(
                    await db.scalars(
                        select(IntegrityChunkRow).where(IntegrityChunkRow.session_id == item.id)
                    )
                )
                media = list(
                    await db.scalars(
                        select(IntegrityMediaRow).where(IntegrityMediaRow.session_id == item.id)
                    )
                )
            await self.workflow.storage.delete_owned_objects(
                keys=tuple(row.object_key for row in [*chunks, *media]),
                prefixes=(),
            )
            async with self.sessions.begin() as db:
                for table in (IntegritySessionRow, IntegrityChunkRow, IntegrityMediaRow):
                    predicate = (
                        table.id == item.id
                        if table is IntegritySessionRow
                        else table.session_id == item.id
                    )
                    await db.execute(update(table).where(predicate).values(deleted_at=now))
                await db.execute(
                    update(IntegrityJobRow)
                    .where(
                        IntegrityJobRow.session_id == item.id,
                        IntegrityJobRow.status.in_(["pending", "running"]),
                    )
                    .values(status="failed", error="Срок хранения записи истёк")
                )
