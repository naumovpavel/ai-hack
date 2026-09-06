from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, func, inspect, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from interview_api.workflow.ai import AnalysisDraft, QuestionProposal
from interview_api.workflow.deletion_repository import DeletionRepositoryMixin
from interview_api.workflow.entities import (
    AnalysisItemRow,
    AnalysisRow,
    AnswerRow,
    AuthSessionRow,
    CandidateRow,
    DecisionRow,
    HiringResourceRow,
    HumanReviewRow,
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
    ReviewGateError,
    WorkflowConflictError,
    WorkflowNotFoundError,
    WorkflowValidationError,
)
from interview_api.workflow.telegram_entities import TelegramAccountRow
from interview_api.workflow.telegram_repository import TelegramRepositoryMixin


def new_id() -> str:
    return str(uuid4())


class SqlAlchemyWorkflowRepository(TelegramRepositoryMixin, DeletionRepositoryMixin):
    """Async repository shared by PostgreSQL production and SQLite API tests."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    @staticmethod
    async def _lock_candidate(session: AsyncSession, candidate_id: str) -> CandidateRow:
        candidate = await session.get(CandidateRow, candidate_id, with_for_update=True)
        if candidate is None:
            raise WorkflowNotFoundError(details={"candidateId": candidate_id})
        return candidate

    @classmethod
    async def _lock_interview_candidate(cls, session: AsyncSession, interview_id: str) -> None:
        candidate_id = await session.scalar(
            select(InterviewRow.candidate_id).where(InterviewRow.id == interview_id)
        )
        if candidate_id is None:
            raise WorkflowNotFoundError(details={"interviewId": interview_id})
        await cls._lock_candidate(session, candidate_id)

    @classmethod
    def from_engine(cls, engine: AsyncEngine) -> SqlAlchemyWorkflowRepository:
        return cls(async_sessionmaker(engine, expire_on_commit=False))

    async def initialize(self, engine: AsyncEngine) -> None:
        async with engine.begin() as connection:
            await connection.run_sync(WorkflowBase.metadata.create_all)
            # Additive migration keeps existing local SQLite and PostgreSQL data intact.
            for table, column, declaration in (
                ("workflow_positions", "role", "VARCHAR(240) NOT NULL DEFAULT ''"),
                ("workflow_candidates", "interview_plan_id", "VARCHAR(36) NULL"),
                ("workflow_candidates", "user_id", "VARCHAR(36) NULL"),
                ("workflow_candidates", "telegram_username", "VARCHAR(32) NULL"),
                ("workflow_auth_sessions", "active_role", "VARCHAR(16) NULL"),
                ("workflow_auth_sessions", "candidate_id", "VARCHAR(36) NULL"),
            ):
                columns = await connection.run_sync(
                    lambda conn, table=table: {
                        item["name"] for item in inspect(conn).get_columns(table)
                    }
                )
                if column not in columns:
                    await connection.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
                    )

            # create_all skips indexes on an existing table; add indexes for
            # migrated Telegram contact/ownership columns after adding them.
            for index in CandidateRow.__table__.indexes:
                if index.name in {
                    "ix_workflow_candidates_user_id", "ix_workflow_candidates_telegram_username"
                }:
                    await connection.run_sync(
                        lambda conn, index=index: index.create(conn, checkfirst=True)
                    )

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

    async def recover_interrupted_analyses(self) -> int:
        async with self._sessions.begin() as session:
            candidate_ids = list(
                await session.scalars(
                    select(InterviewRow.candidate_id).where(InterviewRow.status == "analyzing")
                )
            )
            if not candidate_ids:
                return 0
            await session.execute(
                update(InterviewRow)
                .where(InterviewRow.status == "analyzing")
                .values(status="error")
            )
            await session.execute(
                update(CandidateRow)
                .where(CandidateRow.id.in_(candidate_ids))
                .values(processing_status="error")
            )
            return len(candidate_ids)

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
            result = (await session.execute(
                select(UserRow, AuthSessionRow)
                .join(AuthSessionRow, AuthSessionRow.user_id == UserRow.id)
                .where(AuthSessionRow.token_hash == token_hash, AuthSessionRow.expires_at > now)
            )).first()
            if result is None:
                return None
            user, auth = result
            account = await session.scalar(
                select(TelegramAccountRow).where(TelegramAccountRow.user_id == user.id)
            )
            session.expunge(user)
            if auth.active_role:
                user.role = auth.active_role
                user.candidate_id = auth.candidate_id
            user.telegram_username = account.username if account else None
            user.telegram_connected = bool(account)
            return user

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
        role: str = "",
    ) -> PositionRow:
        row = PositionRow(
            id=new_id(),
            created_by=created_by,
            title=title,
            role=role,
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
        interview_plan_id: str | None = None,
        telegram_username: str | None = None,
    ) -> CandidateRow:
        candidate = CandidateRow(
            telegram_username=telegram_username,
            id=new_id(),
            position_id=position_id,
            interview_plan_id=interview_plan_id,
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
            await self._lock_candidate(session, candidate_id)
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
            await self._lock_candidate(session, candidate_id)
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
            await self._lock_candidate(session, candidate_id)
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
            await self._lock_candidate(session, candidate_id)
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
            await self._lock_interview_candidate(session, interview_id)
            row = await session.get(InterviewRow, interview_id, with_for_update=True)
            if row is None:
                raise WorkflowNotFoundError(details={"interviewId": interview_id})
            if row.status == "ready":
                row.status = "in_progress"
                row.consent_at = started_at
                row.started_at = started_at
                row.deadline_at = deadline_at
                candidate = await session.get(CandidateRow, row.candidate_id)
                if candidate is not None:
                    candidate.processing_status = "in_progress"
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
            await self._lock_candidate(session, candidate_id)
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
        candidate_id: str,
        audio_object_key: str,
        audio_filename: str,
        audio_content_type: str,
        audio_size_bytes: int,
        video_object_key: str,
        video_filename: str,
        video_content_type: str,
        video_size_bytes: int,
        alignment_object_key: str | None = None,
        alignment_filename: str | None = None,
        alignment_size_bytes: int | None = None,
    ) -> AnswerRow:
        async with self._sessions.begin() as session:
            await self._lock_candidate(session, candidate_id)
            interview = await session.get(InterviewRow, interview_id, with_for_update=True)
            if interview is None:
                raise WorkflowNotFoundError(details={"interviewId": interview_id})
            existing = await session.scalar(
                select(AnswerRow).where(
                    AnswerRow.interview_id == interview_id,
                    AnswerRow.question_id == question_id,
                )
            )
            row = existing
            if row is None:
                row = AnswerRow(
                    id=new_id(),
                    interview_id=interview_id,
                    question_id=question_id,
                    transcript=transcript,
                    duration_seconds=duration_seconds,
                )
                session.add(row)
            media_specs = [
                (
                    "audio",
                    audio_object_key,
                    audio_filename,
                    audio_content_type,
                    audio_size_bytes,
                ),
                (
                    "video",
                    video_object_key,
                    video_filename,
                    video_content_type,
                    video_size_bytes,
                ),
            ]
            if alignment_object_key and alignment_filename and alignment_size_bytes is not None:
                media_specs.append(
                    (
                        "alignment",
                        alignment_object_key,
                        alignment_filename,
                        "application/json",
                        alignment_size_bytes,
                    )
                )
            for kind, object_key, filename, content_type, size_bytes in media_specs:
                media_exists = await session.scalar(
                    select(MediaAssetRow.id).where(
                        MediaAssetRow.answer_id == row.id,
                        MediaAssetRow.kind == kind,
                    )
                )
                if media_exists is None:
                    session.add(
                        MediaAssetRow(
                            id=new_id(),
                            candidate_id=candidate_id,
                            interview_id=interview_id,
                            answer_id=row.id,
                            question_id=question_id,
                            kind=kind,
                            object_key=object_key,
                            filename=filename,
                            content_type=content_type,
                            size_bytes=size_bytes,
                        )
                    )
            candidate = await session.get(CandidateRow, candidate_id)
            if candidate is not None:
                candidate.processing_status = "in_progress"
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

    async def list_answered_question_ids(self, interview_id: str) -> list[str]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(AnswerRow.question_id).where(AnswerRow.interview_id == interview_id)
            )
            return list(rows)

    async def find_answer_media(self, *, answer_id: str, kind: str) -> MediaAssetRow | None:
        async with self._sessions() as session:
            return await session.scalar(
                select(MediaAssetRow).where(
                    MediaAssetRow.answer_id == answer_id,
                    MediaAssetRow.kind == kind,
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

    async def list_answers_by_question_ids(self, question_ids: list[str]) -> list[AnswerRow]:
        if not question_ids:
            return []
        async with self._sessions() as session:
            rows = await session.scalars(
                select(AnswerRow).where(AnswerRow.question_id.in_(question_ids))
            )
            return list(rows)

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
        async with self._sessions.begin() as session:
            await self._lock_candidate(session, candidate_id)
            if answer_id is not None:
                await session.get(AnswerRow, answer_id, with_for_update=True)
                existing = await session.scalar(
                    select(MediaAssetRow).where(
                        MediaAssetRow.answer_id == answer_id,
                        MediaAssetRow.kind == kind,
                    )
                )
                if existing is not None:
                    return existing
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

    async def find_interview_media(self, *, interview_id: str, kind: str) -> MediaAssetRow | None:
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
            await self._lock_interview_candidate(session, interview_id)
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
                    "in_progress": "in_progress",
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
            await self._lock_candidate(session, candidate_id)
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
            # These mappers have no ORM relationship to order their inserts.
            # Persist the parent before its items while keeping one transaction.
            await session.flush()
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

    async def list_analysis_items(self, analysis_id: str) -> list[AnalysisItemRow]:
        async with self._sessions() as session:
            return list(
                await session.scalars(
                    select(AnalysisItemRow)
                    .where(AnalysisItemRow.analysis_id == analysis_id)
                    .order_by(AnalysisItemRow.order_index)
                )
            )

    async def get_human_review(self, analysis_id: str, user_id: str) -> HumanReviewRow | None:
        async with self._sessions() as session:
            return await session.scalar(
                select(HumanReviewRow).where(
                    HumanReviewRow.analysis_id == analysis_id, HumanReviewRow.user_id == user_id
                )
            )

    async def save_human_review(
        self,
        *,
        candidate_id: str,
        analysis_id: str,
        user_id: str,
        question_id: str | None = None,
        rating: str | None = None,
        initial_status: str | None = None,
        feedback: str = "",
        internal_reason: str = "",
        required_question_ids: set[str] | None = None,
        now: datetime,
    ) -> HumanReviewRow:
        async with self._sessions.begin() as session:
            # Serialize edits/reveal/finalization for this candidate on PostgreSQL.
            candidate = await session.get(CandidateRow, candidate_id, with_for_update=True)
            if candidate is None:
                raise WorkflowNotFoundError()
            if candidate.hiring_decision != "pending":
                raise WorkflowConflictError("Решение уже подтверждено.")
            row = await session.scalar(
                select(HumanReviewRow)
                .where(HumanReviewRow.analysis_id == analysis_id, HumanReviewRow.user_id == user_id)
                .with_for_update()
            )
            if row is None:
                row = HumanReviewRow(
                    id=new_id(), analysis_id=analysis_id, user_id=user_id, question_ratings={}
                )
                session.add(row)
            if row.revealed_at is not None:
                # A network retry must not erase or replace the independent judgment.
                if (
                    question_id is None
                    and row.initial_status == initial_status
                    and row.initial_feedback == feedback
                    and row.initial_internal_reason == internal_reason
                ):
                    return row
                raise WorkflowConflictError("Первоначальная оценка уже сохранена перед показом ИИ.")
            if question_id is not None and rating is not None:
                row.question_ratings = {**row.question_ratings, question_id: rating}
            if initial_status is not None:
                if not required_question_ids or not required_question_ids.issubset(
                    row.question_ratings
                ):
                    raise ReviewGateError()
                row.initial_status = initial_status
                row.initial_feedback = feedback
                row.initial_internal_reason = internal_reason
                row.revealed_at = now
        return row

    async def save_decision(
        self,
        *,
        candidate_id: str,
        decided_by: str,
        status: str,
        internal_reason: str,
        candidate_feedback: str,
        analysis_id: str,
        change_reason: str,
    ) -> DecisionRow:
        async with self._sessions.begin() as session:
            candidate = await session.get(CandidateRow, candidate_id, with_for_update=True)
            if candidate is None:
                raise WorkflowNotFoundError(details={"candidateId": candidate_id})
            review = await session.scalar(
                select(HumanReviewRow)
                .where(
                    HumanReviewRow.analysis_id == analysis_id, HumanReviewRow.user_id == decided_by
                )
                .with_for_update()
            )
            if review is None or review.revealed_at is None:
                raise ReviewGateError()
            existing = await session.scalar(
                select(DecisionRow).where(DecisionRow.candidate_id == candidate_id)
            )
            if existing is not None:
                if (
                    existing.status == status
                    and existing.internal_reason == internal_reason
                    and existing.candidate_feedback == candidate_feedback
                    and review.change_reason == change_reason
                ):
                    return existing
                raise WorkflowConflictError("Решение уже подтверждено.")
            review.change_reason = change_reason
            row = DecisionRow(
                id=new_id(),
                candidate_id=candidate_id,
                decided_by=decided_by,
                status=status,
                internal_reason=internal_reason,
                candidate_feedback=candidate_feedback,
            )
            session.add(row)
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

    async def list_hiring_resources(self, owner: str, kind: str) -> list[HiringResourceRow]:
        async with self._sessions() as session:
            return list(
                await session.scalars(
                    select(HiringResourceRow)
                    .where(HiringResourceRow.created_by == owner, HiringResourceRow.kind == kind)
                    .order_by(HiringResourceRow.created_at)
                )
            )

    async def get_hiring_resource(
        self, resource_id: str, owner: str, kind: str
    ) -> HiringResourceRow:
        async with self._sessions() as session:
            row = await session.get(HiringResourceRow, resource_id)
            if row is None or row.created_by != owner or row.kind != kind:
                raise WorkflowNotFoundError("Resource was not found.")
            return row

    async def save_hiring_resources(self, resources: list[HiringResourceRow]) -> None:
        async with self._sessions.begin() as session:
            for row in resources:
                if row.kind == "interview_plan":
                    position = await session.get(
                        PositionRow, row.payload["vacancyId"], with_for_update=True
                    )
                    if position is None or position.created_by != row.created_by:
                        raise WorkflowNotFoundError("Vacancy was not found.")
                await session.merge(row)

    async def update_vacancy(self, position_id: str, changes: dict) -> PositionRow:
        async with self._sessions.begin() as session:
            row = await session.get(PositionRow, position_id)
            if row is None:
                raise WorkflowNotFoundError("Vacancy was not found.")
            for field, value in changes.items():
                setattr(row, field, value)
        return row

    async def list_company_candidates(self, owner: str) -> list[tuple[CandidateRow, PositionRow]]:
        async with self._sessions() as session:
            rows = await session.execute(
                select(CandidateRow, PositionRow)
                .join(PositionRow, CandidateRow.position_id == PositionRow.id)
                .where(PositionRow.created_by == owner)
                .order_by(CandidateRow.created_at.desc())
            )
            return list(rows.all())

    async def save_prepared_candidate(
        self,
        *,
        draft_id: str,
        owner: str,
        candidate_fields: dict,
        proposals: Sequence[QuestionProposal],
    ) -> CandidateRow:
        async with self._sessions.begin() as session:
            position = await session.get(
                PositionRow, candidate_fields["position_id"], with_for_update=True
            )
            plan = await session.get(HiringResourceRow, candidate_fields["interview_plan_id"])
            if (position is None or position.created_by != owner or plan is None
                    or plan.kind != "interview_plan" or plan.created_by != owner):
                raise WorkflowNotFoundError("Interview was not found.")
            draft = await session.scalar(
                select(HiringResourceRow)
                .where(
                    HiringResourceRow.id == draft_id,
                    HiringResourceRow.created_by == owner,
                    HiringResourceRow.kind == "candidate_draft",
                )
                .with_for_update()
            )
            if draft is None:
                raise WorkflowNotFoundError("Candidate draft was not found.")
            existing_id = draft.payload.get("candidateId")
            if existing_id:
                return await session.get(CandidateRow, existing_id)
            candidate = CandidateRow(id=new_id(), **candidate_fields)
            session.add(candidate)
            await session.flush()
            session.add(
                UserRow(
                    id=new_id(),
                    role="candidate",
                    name=candidate.name,
                    email=candidate.email,
                    candidate_id=candidate.id,
                )
            )
            session.add_all(
                [
                    QuestionRow(
                        id=new_id(),
                        candidate_id=candidate.id,
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
            )
            draft.payload = {**draft.payload, "candidateId": candidate.id}
        return candidate

    async def attach_legacy_interview_plan(self, plan: HiringResourceRow, position_id: str) -> None:
        async with self._sessions.begin() as session:
            if await session.get(HiringResourceRow, plan.id) is None:
                session.add(plan)
            await session.execute(
                update(CandidateRow)
                .where(
                    CandidateRow.position_id == position_id,
                    CandidateRow.interview_plan_id.is_(None),
                )
                .values(interview_plan_id=plan.id)
            )
