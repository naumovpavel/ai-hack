from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from interview_api.workflow.entities import CandidateRow, InterviewRow
from interview_api.workflow.errors import WorkflowConflictError, WorkflowNotFoundError
from interview_api.workflow.practice_entities import PracticeSessionRow


class PracticeRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, practice_id: str) -> PracticeSessionRow:
        async with self._sessions() as session:
            row = await session.get(PracticeSessionRow, practice_id)
            if row is None:
                raise WorkflowNotFoundError("Mock interview was not found.")
            return row

    async def for_interview(self, interview_id: str) -> PracticeSessionRow | None:
        async with self._sessions() as session:
            return await session.scalar(
                select(PracticeSessionRow).where(PracticeSessionRow.interview_id == interview_id)
            )

    async def create(self, row: PracticeSessionRow) -> PracticeSessionRow:
        try:
            async with self._sessions.begin() as session:
                candidate = await session.get(CandidateRow, row.candidate_id, with_for_update=True)
                if candidate is None:
                    raise WorkflowNotFoundError("Candidate was deleted.")
                interview = await session.get(InterviewRow, row.interview_id, with_for_update=True)
                if interview is None:
                    raise WorkflowNotFoundError("Interview was deleted.")
                existing = await session.scalar(
                    select(PracticeSessionRow).where(
                        PracticeSessionRow.interview_id == row.interview_id
                    )
                )
                if existing is not None:
                    return existing
                if interview.status != "ready":
                    raise WorkflowConflictError("Start practice before the real interview.")
                session.add(row)
            return row
        except IntegrityError:
            existing = await self.for_interview(row.interview_id)
            if existing is not None:
                return existing
            raise WorkflowNotFoundError("Interview was deleted.") from None

    async def mutate(
        self, practice_id: str, change: Callable[[PracticeSessionRow], None]
    ) -> PracticeSessionRow:
        try:
            async with self._sessions.begin() as session:
                candidate_id = await session.scalar(
                    select(PracticeSessionRow.candidate_id).where(
                        PracticeSessionRow.id == practice_id
                    )
                )
                if candidate_id is None:
                    raise WorkflowNotFoundError("Mock interview was deleted.")
                candidate = await session.get(CandidateRow, candidate_id, with_for_update=True)
                if candidate is None:
                    raise WorkflowNotFoundError("Candidate was deleted.")
                row = await session.get(PracticeSessionRow, practice_id, with_for_update=True)
                if row is None:
                    raise WorkflowNotFoundError("Mock interview was deleted.")
                change(row)
            return row
        except StaleDataError as exc:
            raise WorkflowConflictError("Mock interview changed; reload and try again.") from exc

    async def recover_interrupted(self) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(PracticeSessionRow)
                .where(PracticeSessionRow.status == "analyzing")
                .values(status="error", revision=PracticeSessionRow.revision + 1)
            )
