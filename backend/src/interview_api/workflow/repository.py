from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from interview_api.workflow.ai import AnalysisDraft, QuestionProposal
from interview_api.workflow.entities import (
    AnalysisItemRow,
    AnalysisRow,
    AnswerRow,
    AuthSessionRow,
    CandidateRow,
    DecisionRow,
    InterviewRow,
    InviteRow,
    MediaAssetRow,
    PositionRow,
    QuestionRow,
    ReviewProgressRow,
    UserRow,
    WorkflowBase,
)
from interview_api.workflow.errors import (
    WorkflowConflictError,
    WorkflowNotFoundError,
    WorkflowValidationError,
)


def new_id() -> str:
    return str(uuid4())


class SqlAlchemyWorkflowRepository:
    """Async repository shared by PostgreSQL production and SQLite API tests."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    @classmethod
    def from_engine(cls, engine: AsyncEngine) -> SqlAlchemyWorkflowRepository:
        return cls(async_sessionmaker(engine, expire_on_commit=False))

    async def initialize(self, engine: AsyncEngine) -> None:
        async with engine.begin() as connection:
            await connection.run_sync(WorkflowBase.metadata.create_all)

    async def ensure_demo_users(self) -> None:
        async with self._sessions.begin() as session:
            if await session.get(UserRow, "hr-demo") is None:
                session.add(
                    UserRow(
                        id="hr-demo",
                        role="hr",
                        name="Юлия Белова",
                        email="hr@example.test",
                    )
                )

    async def list_users(self) -> list[UserRow]:
        async with self._sessions() as session:
            result = await session.scalars(select(UserRow).order_by(UserRow.created_at, UserRow.id))
            return list(result)

    async def get_user(self, user_id: str) -> UserRow:
        async with self._sessions() as session:
            row = await session.get(UserRow, user_id)
            if row is None:
                raise WorkflowNotFoundError("Demo user was not found.", details={"userId": user_id})
            return row

    async def create_auth_session(
        self,
        *,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> AuthSessionRow:
        row = AuthSessionRow(
            id=new_id(), token_hash=token_hash, user_id=user_id, expires_at=expires_at
        )
        async with self._sessions.begin() as session:
            session.add(row)
        return row

    async def resolve_auth_session(self, token_hash: str, now: datetime) -> UserRow | None:
        async with self._sessions() as session:
            return await session.scalar(
                select(UserRow)
                .join(AuthSessionRow, AuthSessionRow.user_id == UserRow.id)
                .where(AuthSessionRow.token_hash == token_hash, AuthSessionRow.expires_at > now)
            )

    async def create_position(
        self,
        *,
        created_by: str,
        title: str,
        level: str,
        location: str,
        requirements: list[str],
        question_count: int,
        duration_minutes: int,
        max_follow_up_questions: int,
        vacancy_object_key: str,
        vacancy_filename: str,
        vacancy_content_type: str,
        vacancy_text: str,
        seed_questions: list[str],
    ) -> PositionRow:
        row = PositionRow(
            id=new_id(),
            created_by=created_by,
            title=title,
            level=level,
            location=location,
            requirements=requirements,
            question_count=question_count,
            duration_minutes=duration_minutes,
            max_follow_up_questions=max_follow_up_questions,
            vacancy_object_key=vacancy_object_key,
            vacancy_filename=vacancy_filename,
            vacancy_content_type=vacancy_content_type,
            vacancy_text=vacancy_text,
            seed_questions=seed_questions,
            status="active",
        )
        async with self._sessions.begin() as session:
            session.add(row)
        return row

    async def list_positions(self) -> list[tuple[PositionRow, int]]:
        async with self._sessions() as session:
            statement = (
                select(PositionRow, func.count(CandidateRow.id))
                .outerjoin(CandidateRow, CandidateRow.position_id == PositionRow.id)
                .group_by(PositionRow.id)
                .order_by(PositionRow.created_at.desc())
            )
            return [(row, int(count)) for row, count in (await session.execute(statement)).all()]

    async def get_position(self, position_id: str) -> PositionRow:
        async with self._sessions() as session:
            row = await session.get(PositionRow, position_id)
            if row is None:
                raise WorkflowNotFoundError(
                    "Position was not found.", details={"positionId": position_id}
                )
            return row

    async def list_candidates(self, position_id: str) -> list[CandidateRow]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(CandidateRow)
                .where(CandidateRow.position_id == position_id)
                .order_by(CandidateRow.created_at)
            )
            return list(rows)

    async def create_candidate(
        self,
        *,
        position_id: str,
        name: str,
        email: str | None,
        role: str,
        resume_object_key: str,
        resume_filename: str,
        resume_content_type: str,
        resume_text: str,
    ) -> CandidateRow:
        candidate = CandidateRow(
            id=new_id(),
            position_id=position_id,
            name=name,
            email=email,
            role=role,
            resume_object_key=resume_object_key,
            resume_filename=resume_filename,
            resume_content_type=resume_content_type,
            resume_text=resume_text,
        )
        candidate_user = UserRow(
            id=new_id(),
            role="candidate",
            name=name,
            email=email,
            candidate_id=candidate.id,
        )
        async with self._sessions.begin() as session:
            session.add_all([candidate, candidate_user])
        return candidate

    async def get_candidate(self, candidate_id: str) -> CandidateRow:
        async with self._sessions() as session:
            row = await session.get(CandidateRow, candidate_id)
            if row is None:
                raise WorkflowNotFoundError(
                    "Candidate was not found.", details={"candidateId": candidate_id}
                )
            return row

    async def get_candidate_user(self, candidate_id: str) -> UserRow:
        async with self._sessions() as session:
            row = await session.scalar(
                select(UserRow).where(
                    UserRow.role == "candidate", UserRow.candidate_id == candidate_id
                )
            )
            if row is None:
                raise WorkflowNotFoundError(
                    "Candidate user was not found.", details={"candidateId": candidate_id}
                )
            return row

    async def replace_questions(
        self, candidate_id: str, proposals: Sequence[QuestionProposal]
    ) -> list[QuestionRow]:
        rows = [
            QuestionRow(
                id=new_id(),
                candidate_id=candidate_id,
                order_index=index,
                kind=proposal.kind,
                text=proposal.text,
                topic=proposal.topic,
                competency=proposal.competency,
                source_refs=proposal.source_refs,
                status="draft",
            )
            for index, proposal in enumerate(proposals)
        ]
        async with self._sessions.begin() as session:
            await session.execute(
                delete(QuestionRow).where(QuestionRow.candidate_id == candidate_id)
            )
            session.add_all(rows)
        return rows

    async def list_questions(self, candidate_id: str) -> list[QuestionRow]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(QuestionRow)
                .where(QuestionRow.candidate_id == candidate_id)
                .order_by(QuestionRow.order_index)
            )
            return list(rows)

    async def get_question(self, question_id: str) -> QuestionRow:
        async with self._sessions() as session:
            row = await session.get(QuestionRow, question_id)
            if row is None:
                raise WorkflowNotFoundError(
                    "Question was not found.", details={"questionId": question_id}
                )
            return row

    async def update_question(
        self,
        *,
        candidate_id: str,
        question_id: str,
        text: str | None,
        topic: str | None,
        competency: str | None,
        order_index: int | None,
    ) -> QuestionRow:
        async with self._sessions.begin() as session:
            rows = list(
                await session.scalars(
                    select(QuestionRow)
                    .where(QuestionRow.candidate_id == candidate_id)
                    .order_by(QuestionRow.order_index)
                    .with_for_update()
                )
            )
            row = next((item for item in rows if item.id == question_id), None)
            if row is None:
                raise WorkflowNotFoundError(
                    "Question was not found.", details={"questionId": question_id}
                )
            if row.status != "draft":
                raise WorkflowConflictError("Approved questions can no longer be edited.")
            if text is not None:
                row.text = text
            if topic is not None:
                row.topic = topic
            if competency is not None:
                row.competency = competency
            if order_index is not None:
                target = min(order_index, len(rows) - 1)
                rows.remove(row)
                rows.insert(target, row)
                for index, item in enumerate(rows):
                    item.order_index = 10_000 + index
                await session.flush()
                for index, item in enumerate(rows):
                    item.order_index = index
            row.updated_at = datetime.now(UTC)
        return row

    async def approve_questions(self, candidate_id: str) -> list[QuestionRow]:
        async with self._sessions.begin() as session:
            rows = list(
                await session.scalars(
                    select(QuestionRow)
                    .where(QuestionRow.candidate_id == candidate_id)
                    .order_by(QuestionRow.order_index)
                    .with_for_update()
                )
            )
            if not rows:
                raise WorkflowValidationError("At least one question is required.")
            for row in rows:
                row.status = "approved"
            candidate = await session.get(CandidateRow, candidate_id)
            if candidate is None:
                raise WorkflowNotFoundError(details={"candidateId": candidate_id})
            candidate.processing_status = "invited"
        return rows

    async def upsert_invite_and_interview(
        self,
        *,
        candidate_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> tuple[InviteRow, InterviewRow]:
        async with self._sessions.begin() as session:
            invite = await session.scalar(
                select(InviteRow).where(InviteRow.candidate_id == candidate_id).with_for_update()
            )
            if invite is None:
                invite = InviteRow(
                    id=new_id(),
                    candidate_id=candidate_id,
                    token_hash=token_hash,
                    expires_at=expires_at,
                )
                session.add(invite)
            else:
                invite.token_hash = token_hash
                invite.expires_at = expires_at
                invite.revoked_at = None
            interview = await session.scalar(
                select(InterviewRow)
                .where(InterviewRow.candidate_id == candidate_id)
                .with_for_update()
            )
            if interview is None:
                interview = InterviewRow(id=new_id(), candidate_id=candidate_id, status="ready")
                session.add(interview)
            candidate = await session.get(CandidateRow, candidate_id)
            if candidate is None:
                raise WorkflowNotFoundError(details={"candidateId": candidate_id})
            candidate.processing_status = "invited"
        return invite, interview

    async def resolve_invite(
        self, token_hash: str, now: datetime
    ) -> tuple[InviteRow, CandidateRow]:
        async with self._sessions() as session:
            result = await session.execute(
                select(InviteRow, CandidateRow)
                .join(CandidateRow, CandidateRow.id == InviteRow.candidate_id)
                .where(
                    InviteRow.token_hash == token_hash,
                    InviteRow.expires_at > now,
                    InviteRow.revoked_at.is_(None),
                )
            )
            pair = result.one_or_none()
            if pair is None:
                raise WorkflowNotFoundError("Interview invitation is invalid or expired.")
            return pair[0], pair[1]

    async def get_interview(self, interview_id: str) -> InterviewRow:
        async with self._sessions() as session:
            row = await session.get(InterviewRow, interview_id)
            if row is None:
                raise WorkflowNotFoundError(
                    "Interview was not found.", details={"interviewId": interview_id}
                )
            return row

    async def get_interview_for_candidate(self, candidate_id: str) -> InterviewRow:
        async with self._sessions() as session:
            row = await session.scalar(
                select(InterviewRow).where(InterviewRow.candidate_id == candidate_id)
            )
            if row is None:
                raise WorkflowNotFoundError(
                    "Interview was not found.", details={"candidateId": candidate_id}
                )
            return row

    async def start_interview(
        self,
        interview_id: str,
        *,
        started_at: datetime,
        deadline_at: datetime,
    ) -> InterviewRow:
        async with self._sessions.begin() as session:
            row = await session.get(InterviewRow, interview_id, with_for_update=True)
            if row is None:
                raise WorkflowNotFoundError(details={"interviewId": interview_id})
            if row.status == "ready":
                row.status = "in_progress"
                row.consent_at = started_at
                row.started_at = started_at
                row.deadline_at = deadline_at
            elif row.status != "in_progress":
                raise WorkflowConflictError("Interview cannot be started in its current state.")
        return row

    async def next_unanswered_question(self, interview_id: str) -> QuestionRow | None:
        async with self._sessions() as session:
            interview = await session.get(InterviewRow, interview_id)
            if interview is None:
                raise WorkflowNotFoundError(details={"interviewId": interview_id})
            answered = select(AnswerRow.question_id).where(AnswerRow.interview_id == interview_id)
            return await session.scalar(
                select(QuestionRow)
                .where(
                    QuestionRow.candidate_id == interview.candidate_id,
                    QuestionRow.status == "approved",
                    QuestionRow.id.not_in(answered),
                )
                .order_by(QuestionRow.order_index)
                .limit(1)
            )

    async def remaining_base_questions(self, interview_id: str) -> int:
        async with self._sessions() as session:
            interview = await session.get(InterviewRow, interview_id)
            if interview is None:
                raise WorkflowNotFoundError(details={"interviewId": interview_id})
            answered = select(AnswerRow.question_id).where(AnswerRow.interview_id == interview_id)
            count = await session.scalar(
                select(func.count(QuestionRow.id)).where(
                    QuestionRow.candidate_id == interview.candidate_id,
                    QuestionRow.status == "approved",
                    QuestionRow.kind != "follow_up",
                    QuestionRow.id.not_in(answered),
                )
            )
            return int(count or 0)

    async def count_follow_ups(self, candidate_id: str) -> int:
        async with self._sessions() as session:
            count = await session.scalar(
                select(func.count(QuestionRow.id)).where(
                    QuestionRow.candidate_id == candidate_id,
                    QuestionRow.kind == "follow_up",
                )
            )
            return int(count or 0)

    async def add_follow_up(
        self,
        *,
        candidate_id: str,
        parent_question_id: str,
        text: str,
        topic: str,
        competency: str,
        reason: str,
    ) -> QuestionRow:
        async with self._sessions.begin() as session:
            rows = list(
                await session.scalars(
                    select(QuestionRow)
                    .where(QuestionRow.candidate_id == candidate_id)
                    .order_by(QuestionRow.order_index)
                    .with_for_update()
                )
            )
            parent_index = next(
                (index for index, row in enumerate(rows) if row.id == parent_question_id), None
            )
            if parent_index is None:
                raise WorkflowNotFoundError(details={"questionId": parent_question_id})
            row = QuestionRow(
                id=new_id(),
                candidate_id=candidate_id,
                parent_question_id=parent_question_id,
                order_index=20_000 + len(rows),
                kind="follow_up",
                text=text,
                topic=topic,
                competency=competency,
                source_refs=[parent_question_id],
                follow_up_reason=reason,
                status="approved",
            )
            session.add(row)
            await session.flush()
            rows.insert(parent_index + 1, row)
            for index, item in enumerate(rows):
                item.order_index = 10_000 + index
            await session.flush()
            for index, item in enumerate(rows):
                item.order_index = index
        return row

    async def add_answer(
        self,
        *,
        interview_id: str,
        question_id: str,
        transcript: str,
        duration_seconds: int | None,
    ) -> AnswerRow:
        row = AnswerRow(
            id=new_id(),
            interview_id=interview_id,
            question_id=question_id,
            transcript=transcript,
            duration_seconds=duration_seconds,
        )
        async with self._sessions.begin() as session:
            session.add(row)
            candidate = await session.scalar(
                select(CandidateRow)
                .join(InterviewRow, InterviewRow.candidate_id == CandidateRow.id)
                .where(InterviewRow.id == interview_id)
            )
            if candidate is not None:
                candidate.processing_status = "recorded"
        return row

    async def get_answer_for_question(
        self, *, interview_id: str, question_id: str
    ) -> AnswerRow | None:
        async with self._sessions() as session:
            return await session.scalar(
                select(AnswerRow).where(
                    AnswerRow.interview_id == interview_id,
                    AnswerRow.question_id == question_id,
                )
            )

    async def list_answers_with_questions(
        self, interview_id: str
    ) -> list[tuple[AnswerRow, QuestionRow]]:
        async with self._sessions() as session:
            result = await session.execute(
                select(AnswerRow, QuestionRow)
                .join(QuestionRow, QuestionRow.id == AnswerRow.question_id)
                .where(AnswerRow.interview_id == interview_id)
                .order_by(QuestionRow.order_index)
            )
            return [(answer, question) for answer, question in result.all()]

    async def add_media_asset(
        self,
        *,
        candidate_id: str,
        interview_id: str,
        answer_id: str | None,
        question_id: str | None,
        kind: str,
        object_key: str,
        filename: str,
        content_type: str,
        size_bytes: int,
    ) -> MediaAssetRow:
        row = MediaAssetRow(
            id=new_id(),
            candidate_id=candidate_id,
            interview_id=interview_id,
            answer_id=answer_id,
            question_id=question_id,
            kind=kind,
            object_key=object_key,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
        )
        async with self._sessions.begin() as session:
            session.add(row)
        return row

    async def list_media_assets(self, candidate_id: str) -> list[MediaAssetRow]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(MediaAssetRow)
                .where(MediaAssetRow.candidate_id == candidate_id)
                .order_by(MediaAssetRow.created_at)
            )
            return list(rows)

    async def find_question_speech(
        self, interview_id: str, question_id: str
    ) -> MediaAssetRow | None:
        async with self._sessions() as session:
            return await session.scalar(
                select(MediaAssetRow).where(
                    MediaAssetRow.interview_id == interview_id,
                    MediaAssetRow.question_id == question_id,
                    MediaAssetRow.kind == "question_audio",
                )
            )

    async def find_interview_media(
        self, *, interview_id: str, kind: str
    ) -> MediaAssetRow | None:
        async with self._sessions() as session:
            return await session.scalar(
                select(MediaAssetRow).where(
                    MediaAssetRow.interview_id == interview_id,
                    MediaAssetRow.kind == kind,
                )
            )

    async def set_interview_status(
        self,
        interview_id: str,
        status: str,
        *,
        completed_at: datetime | None = None,
    ) -> InterviewRow:
        async with self._sessions.begin() as session:
            row = await session.get(InterviewRow, interview_id, with_for_update=True)
            if row is None:
                raise WorkflowNotFoundError(details={"interviewId": interview_id})
            row.status = status
            if completed_at is not None:
                row.completed_at = completed_at
            candidate = await session.get(CandidateRow, row.candidate_id)
            if candidate is not None:
                candidate.processing_status = {
                    "analyzing": "analyzing",
                    "completed": "ready",
                    "error": "error",
                    "in_progress": "recorded",
                }.get(status, candidate.processing_status)
        return row

    async def replace_analysis(
        self,
        *,
        candidate_id: str,
        draft: AnalysisDraft,
    ) -> tuple[AnalysisRow, list[AnalysisItemRow]]:
        analysis = AnalysisRow(
            id=new_id(),
            candidate_id=candidate_id,
            version=draft.version,
            score=draft.score,
            confidence=draft.confidence,
            recommendation=draft.recommendation,
            summary=draft.summary,
            strengths=draft.strengths,
            growth_areas=draft.growth_areas,
            unknowns=draft.unknowns,
            skills=draft.skills,
            next_questions=draft.next_questions,
            model_meta=draft.model_meta,
        )
        items = [
            AnalysisItemRow(
                id=new_id(),
                analysis_id=analysis.id,
                order_index=index,
                kind=item.kind,
                title=item.title,
                body=item.body,
                question_id=item.question_id,
                evidence=item.evidence,
                required_review=True,
            )
            for index, item in enumerate(draft.items)
        ]
        async with self._sessions.begin() as session:
            old_ids = select(AnalysisItemRow.id).where(
                AnalysisItemRow.analysis_id.in_(
                    select(AnalysisRow.id).where(AnalysisRow.candidate_id == candidate_id)
                )
            )
            await session.execute(
                delete(ReviewProgressRow).where(ReviewProgressRow.analysis_item_id.in_(old_ids))
            )
            await session.execute(
                delete(AnalysisItemRow).where(
                    AnalysisItemRow.analysis_id.in_(
                        select(AnalysisRow.id).where(AnalysisRow.candidate_id == candidate_id)
                    )
                )
            )
            await session.execute(
                delete(AnalysisRow).where(AnalysisRow.candidate_id == candidate_id)
            )
            session.add(analysis)
            session.add_all(items)
        return analysis, items

    async def get_analysis(self, candidate_id: str) -> AnalysisRow:
        async with self._sessions() as session:
            row = await session.scalar(
                select(AnalysisRow).where(AnalysisRow.candidate_id == candidate_id)
            )
            if row is None:
                raise WorkflowNotFoundError(
                    "Interview analysis is not ready.", details={"candidateId": candidate_id}
                )
            return row

    async def list_analysis_items_with_progress(
        self, analysis_id: str, user_id: str
    ) -> list[tuple[AnalysisItemRow, ReviewProgressRow | None]]:
        async with self._sessions() as session:
            result = await session.execute(
                select(AnalysisItemRow, ReviewProgressRow)
                .outerjoin(
                    ReviewProgressRow,
                    (ReviewProgressRow.analysis_item_id == AnalysisItemRow.id)
                    & (ReviewProgressRow.user_id == user_id),
                )
                .where(AnalysisItemRow.analysis_id == analysis_id)
                .order_by(AnalysisItemRow.order_index)
            )
            return [(item, progress) for item, progress in result.all()]

    async def record_review_event(
        self,
        *,
        candidate_id: str,
        user_id: str,
        item_id: str,
        event: str,
        visible: bool,
        focused: bool,
        now: datetime,
        required_seconds: float,
        heartbeat_grace_seconds: float,
    ) -> ReviewProgressRow:
        async with self._sessions.begin() as session:
            item = await session.scalar(
                select(AnalysisItemRow)
                .join(AnalysisRow, AnalysisRow.id == AnalysisItemRow.analysis_id)
                .where(AnalysisItemRow.id == item_id, AnalysisRow.candidate_id == candidate_id)
            )
            if item is None:
                raise WorkflowNotFoundError(
                    "Analysis item was not found.", details={"itemId": item_id}
                )
            progress = await session.scalar(
                select(ReviewProgressRow)
                .where(
                    ReviewProgressRow.analysis_item_id == item_id,
                    ReviewProgressRow.user_id == user_id,
                )
                .with_for_update()
            )
            if progress is None:
                progress = ReviewProgressRow(id=new_id(), analysis_item_id=item_id, user_id=user_id)
                session.add(progress)
                await session.flush()

            if event == "open":
                progress.active = bool(visible and focused)
                progress.last_heartbeat_at = now if progress.active else None
            else:
                if (
                    progress.active
                    and progress.last_heartbeat_at is not None
                    and visible
                    and focused
                ):
                    previous = progress.last_heartbeat_at
                    if previous.tzinfo is None:
                        previous = previous.replace(tzinfo=UTC)
                    elapsed = max(0.0, (now - previous).total_seconds())
                    progress.accumulated_seconds += min(elapsed, heartbeat_grace_seconds)
                progress.active = event == "heartbeat" and bool(visible and focused)
                progress.last_heartbeat_at = now if progress.active else None

            if progress.accumulated_seconds >= required_seconds and progress.completed_at is None:
                progress.completed_at = now
        return progress

    async def all_required_items_reviewed(
        self, *, candidate_id: str, user_id: str, required_seconds: float
    ) -> bool:
        async with self._sessions() as session:
            incomplete = await session.scalar(
                select(func.count(AnalysisItemRow.id))
                .join(AnalysisRow, AnalysisRow.id == AnalysisItemRow.analysis_id)
                .outerjoin(
                    ReviewProgressRow,
                    (ReviewProgressRow.analysis_item_id == AnalysisItemRow.id)
                    & (ReviewProgressRow.user_id == user_id),
                )
                .where(
                    AnalysisRow.candidate_id == candidate_id,
                    AnalysisItemRow.required_review.is_(True),
                    (
                        (ReviewProgressRow.id.is_(None))
                        | (ReviewProgressRow.accumulated_seconds < required_seconds)
                    ),
                )
            )
            return int(incomplete or 0) == 0

    async def save_decision(
        self,
        *,
        candidate_id: str,
        decided_by: str,
        status: str,
        internal_reason: str,
        candidate_feedback: str,
        paste_events: int,
        typed_characters: int,
    ) -> DecisionRow:
        async with self._sessions.begin() as session:
            existing = await session.scalar(
                select(DecisionRow).where(DecisionRow.candidate_id == candidate_id)
            )
            if existing is not None:
                raise WorkflowConflictError("A hiring decision has already been recorded.")
            row = DecisionRow(
                id=new_id(),
                candidate_id=candidate_id,
                decided_by=decided_by,
                status=status,
                internal_reason=internal_reason,
                candidate_feedback=candidate_feedback,
                internal_reason_paste_events=paste_events,
                internal_reason_typed_characters=typed_characters,
            )
            session.add(row)
            candidate = await session.get(CandidateRow, candidate_id, with_for_update=True)
            if candidate is None:
                raise WorkflowNotFoundError(details={"candidateId": candidate_id})
            candidate.hiring_decision = status
            # The analysis remains available after the human decision. The
            # separate hiring_decision field carries the terminal outcome.
            candidate.processing_status = "ready"
        return row

    async def get_decision(self, candidate_id: str) -> DecisionRow | None:
        async with self._sessions() as session:
            return await session.scalar(
                select(DecisionRow).where(DecisionRow.candidate_id == candidate_id)
            )
