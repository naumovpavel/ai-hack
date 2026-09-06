from dataclasses import replace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from interview_api.workflow.ai import AnalysisDraft, AnalysisItemDraft
from interview_api.workflow.repository import SqlAlchemyWorkflowRepository


@pytest.mark.asyncio
async def test_analysis_items_respect_foreign_keys_and_replacement_is_atomic():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    repository = SqlAlchemyWorkflowRepository.from_engine(engine)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("PRAGMA foreign_keys=ON"))
            assert await connection.scalar(text("PRAGMA foreign_keys")) == 1
        await repository.initialize(engine)
        await repository.ensure_demo_users()
        position = await repository.create_position(
            created_by="hr-demo",
            title="Test role",
            level="Middle",
            location="",
            requirements=["Python"],
            question_count=1,
            duration_minutes=10,
            max_follow_up_questions=0,
            vacancy_object_key="test/vacancy.txt",
            vacancy_filename="vacancy.txt",
            vacancy_content_type="text/plain",
            vacancy_text="Test vacancy",
            seed_questions=[],
        )
        candidate = await repository.create_candidate(
            position_id=position.id,
            name="Test candidate",
            email=None,
            role="Python",
            resume_object_key="test/resume.txt",
            resume_filename="resume.txt",
            resume_content_type="text/plain",
            resume_text="Test resume",
        )
        draft = AnalysisDraft(
            score=5,
            confidence=0.5,
            recommendation="manual_review",
            summary="First analysis",
            strengths=[],
            growth_areas=[],
            unknowns=[],
            skills=[],
            next_questions=[],
            items=[
                AnalysisItemDraft(kind="unknown", title="Evidence", body="More evidence needed")
            ],
        )
        first, first_items = await repository.replace_analysis(
            candidate_id=candidate.id, draft=draft
        )
        assert first_items[0].analysis_id == first.id
        second, second_items = await repository.replace_analysis(
            candidate_id=candidate.id, draft=replace(draft, summary="Updated analysis")
        )
        assert second.id != first.id
        assert [item.id for item in await repository.list_analysis_items(second.id)] == [
            second_items[0].id
        ]
        assert await repository.list_analysis_items(first.id) == []

        invalid = replace(
            draft,
            items=[
                AnalysisItemDraft(
                    kind="unknown",
                    title="Invalid",
                    body="Invalid question reference",
                    question_id="missing-question",
                ),
            ],
        )
        with pytest.raises(IntegrityError):
            await repository.replace_analysis(candidate_id=candidate.id, draft=invalid)
        retained = await repository.get_analysis(candidate.id)
        assert retained.id == second.id
        assert retained.summary == "Updated analysis"
        assert len(await repository.list_analysis_items(retained.id)) == 1
        async with engine.connect() as connection:
            assert (await connection.execute(text("PRAGMA foreign_key_check"))).all() == []
    finally:
        await engine.dispose()
