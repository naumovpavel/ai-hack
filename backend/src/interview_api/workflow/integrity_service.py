from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from sqlalchemy import or_, select

from interview_api.workflow.entities import InterviewRow, QuestionRow, UserRow
from interview_api.workflow.errors import (
    WorkflowConflictError,
    WorkflowNotFoundError,
    WorkflowValidationError,
)
from interview_api.workflow.integrity_entities import (
    IntegrityChunkRow,
    IntegrityEventRow,
    IntegrityFindingRow,
    IntegrityJobRow,
    IntegrityMediaRow,
    IntegrityReviewRow,
    IntegritySessionRow,
)
from interview_api.workflow.integrity_schemas import (
    AnalysisCoverage,
    FindingDraft,
    IntegrityEventsRequest,
    IntegrityFindingResponse,
    IntegrityFinishRequest,
    IntegrityHeartbeatRequest,
    IntegrityPlaybackResponse,
    IntegrityReviewRequest,
    IntegrityReviewResponse,
    IntegritySessionResponse,
    IntegrityStartRequest,
    IntegritySummaryResponse,
    PlaybackObservation,
    PlaybackSegment,
    PlaybackTranscript,
    RecordingCoverage,
    TimeRange,
    TranscriptWord,
)
from interview_api.workflow.repository import new_id

if TYPE_CHECKING:
    from interview_api.workflow.service import WorkflowService


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def merged_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if end <= start:
            continue
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return result


def covered_ms(ranges: list[tuple[int, int]]) -> int:
    return sum(end - start for start, end in merged_ranges(ranges))


class IntegrityService:
    """Capture lifecycle and HR-only evidence access, independent of answer scoring."""

    def __init__(self, workflow: WorkflowService) -> None:
        self.workflow = workflow
        self._sessions = workflow.repository._sessions
        self.storage = workflow.storage
        self.max_chunk_bytes = 32 * 1024 * 1024

    def _now(self) -> datetime:
        return self.workflow._now()

    def _healthy(self, row: IntegritySessionRow | None) -> bool:
        return bool(
            row
            and row.status == "recording"
            and row.deleted_at is None
            and row.camera_active
            and row.microphone_active
            and row.screen_active
            and row.display_surface == "monitor"
            and row.heartbeat_at
            and (self._now() - aware(row.heartbeat_at)).total_seconds() <= 30
        )

    def _elapsed(self, row: IntegritySessionRow) -> int:
        if row.finished_at is not None:
            return row.end_ms
        return max(row.end_ms, int((self._now() - aware(row.started_at)).total_seconds() * 1000))

    def _response(self, row: IntegritySessionRow) -> IntegritySessionResponse:
        return IntegritySessionResponse(
            id=row.id,
            interview_id=row.interview_id,
            status=row.status,
            next_question_blocked=not self._healthy(row),
            elapsed_ms=self._elapsed(row),
        )

    async def _candidate(self, actor: UserRow, interview_id: str) -> InterviewRow:
        interview = await self.workflow._candidate_interview(actor, interview_id)
        if not getattr(interview, "integrity_enabled", False):
            raise WorkflowNotFoundError("Контроль записи не включён для этого интервью.")
        return interview

    async def _owner(self, actor: UserRow, candidate_id: str) -> InterviewRow:
        await self.workflow._owned_candidate(actor, candidate_id)
        return await self.workflow.repository.get_interview_for_candidate(candidate_id)

    async def _locked_session(self, db, interview_id: str) -> IntegritySessionRow:
        row = await db.scalar(
            select(IntegritySessionRow)
            .where(IntegritySessionRow.interview_id == interview_id)
            .with_for_update()
        )
        if row is None:
            raise WorkflowConflictError("Сначала включите камеру, микрофон и весь экран.")
        if row.deleted_at or aware(row.expires_at) <= self._now():
            raise WorkflowConflictError("Срок хранения записи истёк.")
        return row

    async def start(
        self, *, actor: UserRow, interview_id: str, payload: IntegrityStartRequest
    ) -> IntegritySessionResponse:
        interview = await self._candidate(actor, interview_id)
        if interview.completed_at is not None:
            raise WorkflowConflictError("Интервью уже завершено.")
        async with self._sessions.begin() as db:
            # Lock the immutable parent before creating the unique session.
            await db.get(InterviewRow, interview_id, with_for_update=True)
            row = await db.scalar(
                select(IntegritySessionRow).where(IntegritySessionRow.interview_id == interview_id)
            )
            if row is None:
                row = IntegritySessionRow(
                    id=new_id(),
                    interview_id=interview_id,
                    client_session_id=payload.client_session_id,
                    started_at=self._now(),
                    status="recording",
                    end_ms=0,
                    expires_at=self._now() + timedelta(days=30),
                )
                db.add(row)
            elif row.finished_at or row.deleted_at:
                raise WorkflowConflictError("Запись этого интервью уже завершена.")
            row.client_session_id = payload.client_session_id
            row.status = "recording"
            for field in ("camera_active", "microphone_active", "screen_active", "display_surface"):
                setattr(row, field, getattr(payload, field))
            row.heartbeat_at = self._now()
            row.capture_state_offset_ms = self._elapsed(row)
        return self._response(row)

    async def heartbeat(
        self, *, actor: UserRow, interview_id: str, payload: IntegrityHeartbeatRequest
    ) -> IntegritySessionResponse:
        await self._candidate(actor, interview_id)
        async with self._sessions.begin() as db:
            row = await self._locked_session(db, interview_id)
            if row.finished_at:
                return self._response(row)
            self._validate_offset(row, payload.offset_ms)
            if payload.offset_ms >= row.capture_state_offset_ms:
                for field in (
                    "camera_active",
                    "microphone_active",
                    "screen_active",
                    "display_surface",
                ):
                    setattr(row, field, getattr(payload, field))
                row.heartbeat_at = self._now()
                row.capture_state_offset_ms = payload.offset_ms
            row.end_ms = max(row.end_ms, payload.offset_ms)
        return self._response(row)

    def _validate_offset(self, row: IntegritySessionRow, offset_ms: int) -> None:
        # A small allowance covers clock and request latency, not invented future evidence.
        ceiling = int((self._now() - aware(row.started_at)).total_seconds() * 1000)
        if offset_ms > ceiling + 30_000:
            raise WorkflowValidationError("Время записи выходит за длительность сессии.")

    async def events(
        self, *, actor: UserRow, interview_id: str, payload: IntegrityEventsRequest
    ) -> dict[str, Any]:
        interview = await self._candidate(actor, interview_id)
        accepted = []
        async with self._sessions.begin() as db:
            row = await self._locked_session(db, interview_id)
            for event in payload.events:
                self._validate_offset(row, event.offset_ms + event.duration_ms)
                if len(json.dumps(event.payload, ensure_ascii=False)) > 16_384:
                    raise WorkflowValidationError("Слишком большой payload события.")
                await self._validate_question(db, interview, event.question_id)
                existing = await db.scalar(
                    select(IntegrityEventRow).where(
                        IntegrityEventRow.session_id == row.id,
                        IntegrityEventRow.client_event_id == event.client_event_id,
                    )
                )
                if existing is not None:
                    accepted.append(event.client_event_id)
                    continue
                db.add(
                    IntegrityEventRow(
                        id=new_id(),
                        session_id=row.id,
                        interview_id=interview_id,
                        **event.model_dump(),
                    )
                )
                if (
                    event.type in {"capture_stopped", "recording_gap"}
                    and event.offset_ms > row.capture_state_offset_ms
                ):
                    kind = event.payload.get("kind")
                    if kind in {"camera", "microphone", "screen"}:
                        setattr(row, f"{kind}_active", False)
                    else:
                        row.camera_active = row.microphone_active = row.screen_active = False
                    row.capture_state_offset_ms = event.offset_ms
                accepted.append(event.client_event_id)
        return {"acceptedEventIds": accepted}

    @staticmethod
    async def _validate_question(db, interview: InterviewRow, question_id: str | None) -> None:
        if question_id is None:
            return
        question = await db.get(QuestionRow, question_id)
        if question is None or question.candidate_id != interview.candidate_id:
            raise WorkflowValidationError("Вопрос не принадлежит этому интервью.")

    async def upload_chunk(
        self,
        *,
        actor: UserRow,
        interview_id: str,
        client_chunk_id: str,
        stream_id: str,
        kind: str,
        sequence: int,
        start_ms: int,
        end_ms: int,
        data: bytes,
        content_type: str,
        question_id: str | None = None,
    ) -> dict[str, Any]:
        interview = await self._candidate(actor, interview_id)
        content_type = content_type.split(";", 1)[0].lower()
        if kind not in {"camera", "screen"} or content_type not in {
            "video/webm",
            "video/mp4",
            "video/x-matroska",
            "application/octet-stream",
        }:
            raise WorkflowValidationError("Неподдерживаемый тип медиапорции.")
        if not data or len(data) > self.max_chunk_bytes:
            raise WorkflowValidationError("Пустая или слишком большая медиапорция.")
        if start_ms < 0 or end_ms <= start_ms or end_ms - start_ms > 120_000 or sequence < 0:
            raise WorkflowValidationError("Недопустимый интервал медиапорции.")
        digest = hashlib.sha256(data).hexdigest()
        async with self._sessions.begin() as db:
            row = await self._locked_session(db, interview_id)
            self._validate_offset(row, end_ms)
            await self._validate_question(db, interview, question_id)
            existing = await db.scalar(
                select(IntegrityChunkRow).where(
                    IntegrityChunkRow.session_id == row.id,
                    or_(
                        IntegrityChunkRow.client_chunk_id == client_chunk_id,
                        (IntegrityChunkRow.kind == kind)
                        & (IntegrityChunkRow.stream_id == stream_id)
                        & (IntegrityChunkRow.sequence == sequence),
                    ),
                )
            )
            if existing:
                if (
                    existing.sha256,
                    existing.kind,
                    existing.stream_id,
                    existing.sequence,
                    existing.start_ms,
                    existing.end_ms,
                ) != (digest, kind, stream_id, sequence, start_ms, end_ms):
                    raise WorkflowConflictError("Повторная порция отличается от уже сохранённой.")
                return {"id": existing.id, "clientChunkId": client_chunk_id, "accepted": True}
            # Never mutate a prepared stream after successful analysis. Idempotent retries above
            # remain accepted; an unfinished upload must complete before the finish request.
            if row.finished_at:
                raise WorkflowConflictError(
                    "Сначала дождитесь загрузки порций, затем завершайте запись."
                )
            neighbors = list(
                await db.scalars(
                    select(IntegrityChunkRow).where(
                        IntegrityChunkRow.session_id == row.id,
                        IntegrityChunkRow.kind == kind,
                        IntegrityChunkRow.stream_id == stream_id,
                        IntegrityChunkRow.sequence.in_([sequence - 1, sequence + 1]),
                    )
                )
            )
            for neighbor in neighbors:
                if (neighbor.sequence < sequence and neighbor.end_ms > start_ms + 250) or (
                    neighbor.sequence > sequence and end_ms > neighbor.start_ms + 250
                ):
                    raise WorkflowValidationError("Порядок медиапорций не соответствует времени.")
            chunk_id = new_id()
            key = f"candidates/{interview.candidate_id}/integrity/{row.id}/chunks/{chunk_id}"
            await self.storage.put_bytes(key, data, content_type=content_type)
            chunk = IntegrityChunkRow(
                id=chunk_id,
                session_id=row.id,
                interview_id=interview_id,
                client_chunk_id=client_chunk_id,
                stream_id=stream_id,
                kind=kind,
                sequence=sequence,
                start_ms=start_ms,
                end_ms=end_ms,
                object_key=key,
                content_type=content_type,
                size_bytes=len(data),
                sha256=digest,
                question_id=question_id,
                expires_at=row.expires_at,
            )
            db.add(chunk)
            row.end_ms = max(row.end_ms, end_ms)
        return {"id": chunk.id, "clientChunkId": client_chunk_id, "accepted": True}

    async def finish(
        self, *, actor: UserRow, interview_id: str, payload: IntegrityFinishRequest
    ) -> IntegritySessionResponse:
        await self._candidate(actor, interview_id)
        return await self.finish_interview(interview_id, offset_ms=payload.offset_ms)

    async def finish_interview(
        self, interview_id: str, *, offset_ms: int | None = None
    ) -> IntegritySessionResponse:
        async with self._sessions.begin() as db:
            row = await self._locked_session(db, interview_id)
            if row.finished_at:
                return self._response(row)
            if offset_ms is not None:
                self._validate_offset(row, offset_ms)
            row.end_ms = max(row.end_ms, offset_ms or self._elapsed(row), 1)
            row.finished_at = self._now()
            row.status = "queued"
            # 120 s windows with 5 s overlap; the unique interval key makes finish retry-safe.
            start = 0
            while start < row.end_ms:
                end = min(start + 120_000, row.end_ms)
                db.add(
                    IntegrityJobRow(
                        id=new_id(),
                        session_id=row.id,
                        interview_id=interview_id,
                        start_ms=start,
                        end_ms=end,
                        status="pending",
                        attempts=0,
                        cost_usd=0,
                    )
                )
                if end == row.end_ms:
                    break
                start += 115_000
        return self._response(row)

    async def is_blocked(self, interview_id: str) -> bool:
        async with self._sessions() as db:
            interview = await db.get(InterviewRow, interview_id)
            if not interview or not getattr(interview, "integrity_enabled", False):
                return False
            row = await db.scalar(
                select(IntegritySessionRow).where(IntegritySessionRow.interview_id == interview_id)
            )
            return not self._healthy(row)

    async def issue_question(self, interview: InterviewRow, question_id: str) -> bool:
        if not getattr(interview, "integrity_enabled", False):
            return True
        async with self._sessions.begin() as db:
            row = await db.scalar(
                select(IntegritySessionRow)
                .where(IntegritySessionRow.interview_id == interview.id)
                .with_for_update()
            )
            if row is not None and row.issued_question_id == question_id:
                return True  # Current answer remains writable during a technical failure.
            if not self._healthy(row):
                return False
            row.issued_question_id = question_id
            db.add(
                IntegrityEventRow(
                    id=new_id(),
                    session_id=row.id,
                    interview_id=interview.id,
                    client_event_id=f"issued-{question_id}",
                    type="question_issued",
                    offset_ms=self._elapsed(row),
                    duration_ms=0,
                    question_id=question_id,
                    payload={},
                )
            )
        return True

    async def _exists(self, media: IntegrityMediaRow) -> bool:
        if media.deleted_at or aware(media.expires_at) <= self._now():
            return False
        try:
            exists = getattr(self.storage, "object_exists", None)
            return (
                await exists(media.object_key)
                if exists
                else bool(await self.storage.get_bytes(media.object_key))
            )
        except WorkflowNotFoundError:
            return False

    async def add_finding(
        self, *, interview_id: str, payload: dict[str, Any], job_id: str | None = None
    ) -> IntegrityFindingRow | None:
        """Strict evidence grounding boundary for untrusted multimodal model output."""
        try:
            draft = FindingDraft.model_validate(payload)
        except ValidationError:
            return None
        async with self._sessions.begin() as db:
            interview = await db.get(InterviewRow, interview_id)
            if interview is None:
                return None
            await db.get(InterviewRow, interview_id, with_for_update=True)
            if job_id:
                job = await db.get(IntegrityJobRow, job_id)
                if (
                    not job
                    or job.interview_id != interview_id
                    or draft.start_ms < job.start_ms
                    or draft.end_ms > job.end_ms
                ):
                    return None
            try:
                await self._validate_question(db, interview, draft.question_id)
            except WorkflowValidationError:
                return None
            coverage = []
            for reference in draft.evidence_refs:
                media = await db.get(IntegrityMediaRow, reference.media_id)
                if (
                    media is None
                    or media.interview_id != interview_id
                    or reference.start_ms < media.start_ms
                    or reference.end_ms > media.end_ms
                    or reference.start_ms < draft.start_ms
                    or reference.end_ms > draft.end_ms
                    or not await self._exists(media)
                ):
                    return None
                coverage.append((reference.start_ms, reference.end_ms))
            if not any(
                start <= draft.start_ms and end >= draft.end_ms
                for start, end in merged_ranges(coverage)
            ):
                return None
            # A model-provided question association is not trusted. Derive it only from
            # the actual captured question/answer anchors, leaving between-question
            # observations unassociated.
            anchors = list(
                await db.scalars(
                    select(IntegrityEventRow).where(
                        IntegrityEventRow.interview_id == interview_id,
                        IntegrityEventRow.question_id.is_not(None),
                    )
                )
            )
            draft.question_id = None
            for question_id in {e.question_id for e in anchors}:
                starts = [
                    e.offset_ms
                    for e in anchors
                    if e.question_id == question_id
                    and e.type in {"question_issued", "question_started", "answer_started"}
                ]
                ends = [
                    e.offset_ms
                    for e in anchors
                    if e.question_id == question_id and e.type == "answer_ended"
                ]
                if starts and ends and min(starts) <= draft.start_ms < draft.end_ms <= max(ends):
                    draft.question_id = question_id
                    break
            duplicate = await db.scalar(
                select(IntegrityFindingRow).where(
                    IntegrityFindingRow.interview_id == interview_id,
                    IntegrityFindingRow.source == draft.source,
                    IntegrityFindingRow.category == draft.category,
                    IntegrityFindingRow.start_ms < draft.end_ms,
                    IntegrityFindingRow.end_ms > draft.start_ms,
                )
            )
            if duplicate is not None:
                # Overlap from neighboring analysis windows is one episode. Keep all valid
                # media references so playback can span the boundary without a new clip.
                duplicate.start_ms = min(duplicate.start_ms, draft.start_ms)
                duplicate.end_ms = max(duplicate.end_ms, draft.end_ms)
                refs = duplicate.evidence_refs + [
                    r.model_dump(by_alias=True) for r in draft.evidence_refs
                ]
                duplicate.evidence_refs = list(
                    {json.dumps(ref, sort_keys=True): ref for ref in refs}.values()
                )
                return duplicate
            fields = draft.model_dump(exclude={"evidence_refs"})
            row = IntegrityFindingRow(
                id=new_id(),
                interview_id=interview_id,
                job_id=job_id,
                dedupe_key=hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest(),
                evidence_refs=[r.model_dump(by_alias=True) for r in draft.evidence_refs],
                **fields,
            )
            db.add(row)
        return row

    async def _finding_response(
        self,
        row: IntegrityFindingRow,
        media: dict[str, IntegrityMediaRow],
        review: IntegrityReviewRow | None,
    ) -> IntegrityFindingResponse:
        ranges = []
        for ref in row.evidence_refs:
            item = media.get(ref["mediaId"])
            if item and await self._exists(item):
                ranges.append((max(row.start_ms, item.start_ms), min(row.end_ms, item.end_ms)))
        available = any(
            start <= row.start_ms and end >= row.end_ms for start, end in merged_ranges(ranges)
        )
        fields = FindingDraft.model_validate(row).model_dump()
        return IntegrityFindingResponse(
            **fields,
            id=row.id,
            interview_id=row.interview_id,
            video_available=available,
            review=IntegrityReviewResponse.model_validate(review) if review else None,
        )

    async def summary(self, *, actor: UserRow, candidate_id: str) -> IntegritySummaryResponse:
        interview = await self._owner(actor, candidate_id)
        async with self._sessions() as db:
            row = await db.scalar(
                select(IntegritySessionRow).where(IntegritySessionRow.interview_id == interview.id)
            )
            if row is None:
                return IntegritySummaryResponse(
                    enabled=getattr(interview, "integrity_enabled", False)
                )
            chunks = list(
                await db.scalars(
                    select(IntegrityChunkRow).where(
                        IntegrityChunkRow.session_id == row.id,
                        IntegrityChunkRow.deleted_at.is_(None),
                    )
                )
            )
            media = {
                item.id: item
                for item in await db.scalars(
                    select(IntegrityMediaRow).where(IntegrityMediaRow.session_id == row.id)
                )
            }
            jobs = list(
                await db.scalars(
                    select(IntegrityJobRow).where(IntegrityJobRow.session_id == row.id)
                )
            )
            findings = list(
                await db.scalars(
                    select(IntegrityFindingRow)
                    .where(IntegrityFindingRow.interview_id == interview.id)
                    .order_by(IntegrityFindingRow.start_ms)
                )
            )
            reviews = {
                r.finding_id: r
                for r in await db.scalars(
                    select(IntegrityReviewRow).where(
                        IntegrityReviewRow.finding_id.in_([f.id for f in findings]),
                        IntegrityReviewRow.user_id == actor.id,
                    )
                )
            }
        camera = merged_ranges(
            [
                (c.start_ms, c.end_ms)
                for c in chunks
                if c.kind == "camera" and aware(c.expires_at) > self._now()
            ]
        )
        screen = merged_ranges(
            [
                (c.start_ms, c.end_ms)
                for c in chunks
                if c.kind == "screen" and aware(c.expires_at) > self._now()
            ]
        )
        joint = [(max(a, c), min(b, d)) for a, b in camera for c, d in screen]
        total = self._elapsed(row)
        return IntegritySummaryResponse(
            enabled=True,
            session=self._response(row),
            findings=[await self._finding_response(f, media, reviews.get(f.id)) for f in findings],
            recording_coverage=RecordingCoverage(
                camera_ms=covered_ms(camera),
                screen_ms=covered_ms(screen),
                joint_ms=covered_ms(joint),
                total_ms=total,
            ),
            analysis_coverage=AnalysisCoverage(
                analyzed_ms=covered_ms(
                    [
                        (max(j.start_ms, m.start_ms), min(j.end_ms, m.end_ms))
                        for j in jobs
                        if j.status == "succeeded"
                        for m in media.values()
                    ]
                ),
                total_ms=total,
            ),
            cost_usd=sum(j.cost_usd for j in jobs),
            cost_known=all(j.cost_usd_known for j in jobs if j.attempts > 0),
            pending_jobs=sum(j.status in {"pending", "running"} for j in jobs),
            failed_jobs=sum(j.status == "failed" for j in jobs),
        )

    async def _authorized_finding(
        self, actor: UserRow, candidate_id: str, finding_id: str
    ) -> tuple[InterviewRow, IntegrityFindingRow]:
        interview = await self._owner(actor, candidate_id)
        async with self._sessions() as db:
            finding = await db.get(IntegrityFindingRow, finding_id)
            if finding is None or finding.interview_id != interview.id:
                raise WorkflowNotFoundError("Эпизод не найден.")
        return interview, finding

    async def review(
        self, *, actor: UserRow, candidate_id: str, finding_id: str, payload: IntegrityReviewRequest
    ) -> IntegrityReviewResponse:
        await self._authorized_finding(actor, candidate_id, finding_id)
        async with self._sessions.begin() as db:
            await db.get(IntegrityFindingRow, finding_id, with_for_update=True)
            row = await db.scalar(
                select(IntegrityReviewRow).where(
                    IntegrityReviewRow.finding_id == finding_id,
                    IntegrityReviewRow.user_id == actor.id,
                )
            )
            if row is None:
                row = IntegrityReviewRow(id=new_id(), finding_id=finding_id, user_id=actor.id)
                db.add(row)
            row.decision, row.comment = payload.decision, payload.comment
            row.reviewed_at = self._now()
        return IntegrityReviewResponse.model_validate(row)

    async def retry(self, *, actor: UserRow, candidate_id: str) -> dict[str, int]:
        interview = await self._owner(actor, candidate_id)
        retried = 0
        async with self._sessions.begin() as db:
            row = await self._locked_session(db, interview.id)
            for job in await db.scalars(
                select(IntegrityJobRow)
                .where(
                    IntegrityJobRow.interview_id == interview.id,
                    IntegrityJobRow.status == "failed",
                    IntegrityJobRow.attempts < 3,
                )
                .with_for_update()
            ):
                job.status, job.locked_at, job.error = "pending", None, None
                retried += 1
            if retried:
                row.status = "queued"
        return {"retriedJobs": retried}

    async def playback(
        self, *, actor: UserRow, candidate_id: str, finding_id: str
    ) -> IntegrityPlaybackResponse:
        interview, finding = await self._authorized_finding(actor, candidate_id, finding_id)
        async with self._sessions() as db:
            all_media = list(
                await db.scalars(
                    select(IntegrityMediaRow)
                    .where(IntegrityMediaRow.interview_id == interview.id)
                    .order_by(IntegrityMediaRow.start_ms)
                )
            )
            events = list(
                await db.scalars(
                    select(IntegrityEventRow)
                    .where(IntegrityEventRow.interview_id == interview.id)
                    .order_by(IntegrityEventRow.offset_ms)
                )
            )
        media = [item for item in all_media if await self._exists(item)]
        if not media:
            raise WorkflowNotFoundError("Видео этого интервала отсутствует.")
        reference_ids = {ref["mediaId"] for ref in finding.evidence_refs}
        evidence_ranges = [(m.start_ms, m.end_ms) for m in media if m.id in reference_ids]
        if not any(
            start <= finding.start_ms and end >= finding.end_ms
            for start, end in merged_ranges(evidence_ranges)
        ):
            raise WorkflowNotFoundError("Видео этого интервала отсутствует.")
        context = TimeRange(
            start_ms=min(m.start_ms for m in media), end_ms=max(m.end_ms for m in media)
        )
        expires = self._now() + timedelta(minutes=10)
        streams: dict[str, list[PlaybackSegment]] = {"camera": [], "screen": []}
        for item in media:
            streams[item.kind].append(
                PlaybackSegment(
                    media_id=item.id,
                    stream_id=item.stream_id,
                    start_ms=item.start_ms,
                    end_ms=item.end_ms,
                    media_offset_ms=0,
                    url=await self.storage.presign_download(
                        item.object_key,
                        filename=f"{item.kind}.mp4",
                        inline=True,
                        expires_seconds=600,
                    ),
                )
            )
        answers = await self.workflow.repository.list_answers_with_questions(interview.id)
        alignments = await self.workflow._load_answer_alignments(answers)
        transcripts = []
        answer_range = None
        for answer, question in answers:
            question_events = [e for e in events if e.question_id == question.id]
            begins = [e.offset_ms for e in question_events if e.type == "answer_started"]
            ends = [e.offset_ms for e in question_events if e.type == "answer_ended"]
            issued = [
                e.offset_ms
                for e in question_events
                if e.type in {"question_started", "question_issued"}
            ]
            start, end = (min(begins) if begins else None), (max(ends) if ends else None)
            # No timing is synthesized when the actual answer-start anchor was not recorded.
            words = []
            if start is not None:
                for word in alignments.get(question.id, {}).get("words", []):
                    try:
                        word_start = start + round(float(word["start_seconds"]) * 1000)
                        word_end = start + round(float(word["end_seconds"]) * 1000)
                        if word_end > word_start and (end is None or word_end <= end + 250):
                            words.append(
                                TranscriptWord(
                                    text=str(word["text"]), start_ms=word_start, end_ms=word_end
                                )
                            )
                    except (KeyError, TypeError, ValueError, ValidationError):
                        continue
            transcripts.append(
                PlaybackTranscript(
                    question_id=question.id,
                    text=answer.transcript,
                    start_ms=start,
                    end_ms=end,
                    words=words,
                )
            )
            if question.id == finding.question_id and end is not None and (issued or begins):
                beginning = min(issued + begins)
                bounded_start, bounded_end = (
                    max(context.start_ms, beginning),
                    min(context.end_ms, end),
                )
                if bounded_end > bounded_start:
                    answer_range = TimeRange(start_ms=bounded_start, end_ms=bounded_end)
        return IntegrityPlaybackResponse(
            finding_id=finding.id,
            title=finding.category,
            episode=TimeRange(start_ms=finding.start_ms, end_ms=finding.end_ms),
            context=context,
            answer_range=answer_range,
            camera=streams["camera"],
            screen=streams["screen"],
            transcript=transcripts,
            observations=[
                PlaybackObservation(
                    source=finding.source,
                    text=finding.observation,
                    start_ms=finding.start_ms,
                    end_ms=finding.end_ms,
                )
            ],
            expires_at=expires,
        )
