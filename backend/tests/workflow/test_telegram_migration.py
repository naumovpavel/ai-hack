from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from interview_api.workflow.repository import SqlAlchemyWorkflowRepository


@pytest.mark.asyncio
async def test_telegram_columns_migrate_existing_database_without_losing_users(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.sqlite'}")
    repository = SqlAlchemyWorkflowRepository.from_engine(engine)
    try:
        await repository.initialize(engine)
        await repository.ensure_demo_users()
        await repository.create_auth_session(
            user_id="hr-demo", token_hash="legacy", expires_at=datetime(2030, 1, 1, tzinfo=UTC)
        )
        async with engine.begin() as connection:
            for column in ("user_id", "telegram_username"):
                await connection.execute(text(f"DROP INDEX ix_workflow_candidates_{column}"))
                await connection.execute(
                    text(f"ALTER TABLE workflow_candidates DROP COLUMN {column}")
                )
            for column in ("active_role", "candidate_id"):
                await connection.execute(
                    text(f"ALTER TABLE workflow_auth_sessions DROP COLUMN {column}")
                )
        await repository.initialize(engine)
        await repository.initialize(engine)
        actor = await repository.resolve_auth_session("legacy", datetime.now(UTC))
        assert actor.id == "hr-demo"
        assert actor.role == "hr"
        async with engine.connect() as connection:
            columns = await connection.run_sync(
                lambda conn: {c["name"] for c in inspect(conn).get_columns("workflow_candidates")}
            )
            indexes = await connection.run_sync(
                lambda conn: {i["name"] for i in inspect(conn).get_indexes("workflow_candidates")}
            )
        assert {"user_id", "telegram_username"} <= columns
        assert "ix_workflow_candidates_telegram_username" in indexes
    finally:
        await engine.dispose()
