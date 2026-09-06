from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import delete, select, update

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
)
from interview_api.workflow.errors import WorkflowNotFoundError
from interview_api.workflow.hiring_templates import template_id
from interview_api.workflow.integrity_entities import (
    IntegrityChunkRow,
    IntegrityEventRow,
    IntegrityFindingRow,
    IntegrityJobRow,
    IntegrityMediaRow,
    IntegrityReviewRow,
    IntegritySessionRow,
)
from interview_api.workflow.practice_entities import PracticeSessionRow
from interview_api.workflow.telegram_notification_entities import TelegramNotificationRow

DeletionKind = Literal["candidate", "interview_plan", "vacancy"]


@dataclass(frozen=True)
class DeletedObjects:
    keys: tuple[str, ...]
    prefixes: tuple[str, ...]


class DeletionRepositoryMixin:
    async def delete_hiring_aggregate(
        self, *, owner: str, kind: DeletionKind, resource_id: str
    ) -> DeletedObjects:
        """Remove one owned hiring aggregate in FK-safe order, preserving identities.

        The vacancy lock also serializes plan/candidate creation with deletion.
        Explicit cleanup works in legacy SQLite databases with FK checks disabled.
        Return owned object keys for cleanup only after the transaction commits.
        """
        async with self._sessions.begin() as session:
            if kind == "candidate":
                target = await session.get(CandidateRow, resource_id)
                vacancy_id = target.position_id if target else None
            elif kind == "interview_plan":
                target = await session.get(HiringResourceRow, resource_id)
                vacancy_id = (
                    target.payload.get("vacancyId")
                    if target and target.kind == kind and target.created_by == owner
                    else None
                )
            else:
                vacancy_id = resource_id
            vacancy = (
                await session.get(PositionRow, vacancy_id, with_for_update=True)
                if vacancy_id
                else None
            )
            if vacancy is None or vacancy.created_by != owner:
                raise WorkflowNotFoundError("Resource was not found.")

            resources = list(
                await session.scalars(
                    select(HiringResourceRow).where(HiringResourceRow.created_by == owner)
                )
            )
            plan_ids = {
                row.id
                for row in resources
                if row.kind == "interview_plan"
                and row.payload.get("vacancyId") == vacancy.id
                and (kind == "vacancy" or (kind == "interview_plan" and row.id == resource_id))
            }
            if kind == "interview_plan" and resource_id not in plan_ids:
                raise WorkflowNotFoundError("Resource was not found.")

            query = select(CandidateRow).where(CandidateRow.position_id == vacancy.id)
            if kind == "candidate":
                query = query.where(CandidateRow.id == resource_id)
            elif kind == "interview_plan":
                query = query.where(CandidateRow.interview_plan_id == resource_id)
            candidates = list(await session.scalars(query.with_for_update()))
            candidate_ids = [row.id for row in candidates]
            if kind == "candidate" and not candidate_ids:
                raise WorkflowNotFoundError("Resource was not found.")
            interview_ids = list(
                await session.scalars(
                    select(InterviewRow.id).where(InterviewRow.candidate_id.in_(candidate_ids))
                )
            )
            analysis_ids = list(
                await session.scalars(
                    select(AnalysisRow.id).where(AnalysisRow.candidate_id.in_(candidate_ids))
                )
            )
            item_ids = select(AnalysisItemRow.id).where(
                AnalysisItemRow.analysis_id.in_(analysis_ids)
            )
            # Answers restrict deletion of their question, so delete them first.
            finding_ids = select(IntegrityFindingRow.id).where(
                IntegrityFindingRow.interview_id.in_(interview_ids)
            )
            await session.execute(delete(IntegrityReviewRow).where(
                IntegrityReviewRow.finding_id.in_(finding_ids)
            ))
            for table in (IntegrityFindingRow, IntegrityEventRow, IntegrityMediaRow,
                          IntegrityChunkRow, IntegrityJobRow, IntegritySessionRow):
                await session.execute(delete(table).where(table.interview_id.in_(interview_ids)))
            for table, predicate in (
                (ReviewProgressRow, ReviewProgressRow.analysis_item_id.in_(item_ids)),
                (HumanReviewRow, HumanReviewRow.analysis_id.in_(analysis_ids)),
                (AnalysisItemRow, AnalysisItemRow.analysis_id.in_(analysis_ids)),
                (AnalysisRow, AnalysisRow.candidate_id.in_(candidate_ids)),
                (DecisionRow, DecisionRow.candidate_id.in_(candidate_ids)),
                (TelegramNotificationRow, TelegramNotificationRow.candidate_id.in_(candidate_ids)),
                (MediaAssetRow, MediaAssetRow.candidate_id.in_(candidate_ids)),
                (AnswerRow, AnswerRow.interview_id.in_(interview_ids)),
                (InviteRow, InviteRow.candidate_id.in_(candidate_ids)),
            ):
                await session.execute(delete(table).where(predicate))
            # Practice records use the real candidate/interview as their ownership boundary.
            await session.execute(
                delete(PracticeSessionRow).where(PracticeSessionRow.candidate_id.in_(candidate_ids))
            )
            await session.execute(
                delete(InterviewRow).where(InterviewRow.candidate_id.in_(candidate_ids))
            )
            await session.execute(
                delete(QuestionRow).where(QuestionRow.candidate_id.in_(candidate_ids))
            )
            # Keep accounts and login sessions; detach only the deleted application.
            await session.execute(
                update(AuthSessionRow)
                .where(AuthSessionRow.candidate_id.in_(candidate_ids))
                .values(candidate_id=None)
            )
            await session.execute(
                update(UserRow)
                .where(UserRow.candidate_id.in_(candidate_ids))
                .values(candidate_id=None)
            )
            await session.execute(delete(CandidateRow).where(CandidateRow.id.in_(candidate_ids)))

            resource_ids = plan_ids | {
                row.id
                for row in resources
                if row.kind == "candidate_draft"
                and (
                    row.payload.get("candidateId") in candidate_ids
                    or row.payload.get("planId") in plan_ids
                )
            }
            object_keys = {row.resume_object_key for row in candidates if row.resume_object_key}
            object_keys.update(
                row.payload["objectKey"]
                for row in resources
                if row.id in resource_ids
                and row.kind == "candidate_draft"
                and row.payload.get("objectKey")
            )
            await session.execute(
                delete(HiringResourceRow).where(HiringResourceRow.id.in_(resource_ids))
            )
            if kind == "vacancy":
                await session.delete(vacancy)
            elif kind == "interview_plan" and resource_id == template_id(
                owner, f"legacy:{vacancy.id}"
            ):
                # A legacy vacancy's embedded pool is the migration source. Clear
                # it too, otherwise startup would recreate the deleted plan.
                vacancy.question_count = 0
                vacancy.seed_questions = []
        return DeletedObjects(
            keys=tuple(object_keys),
            prefixes=tuple(f"candidates/{candidate_id}/" for candidate_id in candidate_ids),
        )
