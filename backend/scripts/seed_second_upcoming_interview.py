from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from interview_api.workflow.entities import (
    CandidateRow,
    InterviewRow,
    InviteRow,
    PositionRow,
    QuestionRow,
    UserRow,
)

DATABASE_URL = "sqlite+aiosqlite:////private/tmp/signal-interview-demo.sqlite3"
INVITE_TOKEN = "demo-dmitry-upcoming-interview-2026"


async def seed() -> None:
    engine = create_async_engine(DATABASE_URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)

    async with sessions.begin() as session:
        position = await session.get(PositionRow, "demo-position-upcoming")
        if position is None:
            raise RuntimeError("Run seed_upcoming_interview.py first")
        if await session.get(CandidateRow, "demo-candidate-upcoming-2") is not None:
            print(f"Second demo already exists: http://localhost:3000/?invite={INVITE_TOKEN}")
            await engine.dispose()
            return

        candidate = CandidateRow(
            id="demo-candidate-upcoming-2",
            position_id=position.id,
            name="Дмитрий Орлов",
            email="dmitry.demo@example.test",
            role="Backend Developer",
            resume_object_key="demo/upcoming-resume-dmitry.txt",
            resume_filename="dmitry-orlov.txt",
            resume_content_type="text/plain",
            resume_text=(
                "3 года Python и Django, REST API, PostgreSQL, Redis, Celery, "
                "Docker и базовый опыт RabbitMQ."
            ),
            processing_status="invited",
            hiring_decision="pending",
            created_at=now,
            updated_at=now,
        )
        candidate_user = UserRow(
            id="demo-upcoming-user-2",
            role="candidate",
            name=candidate.name,
            email=candidate.email,
            candidate_id=candidate.id,
            created_at=now,
        )
        question_specs = [
            (
                "Опыт и личный вклад",
                "Расскажите о последнем backend-сервисе и решениях, за которые отвечали лично.",
                "Самостоятельность",
            ),
            (
                "Проектирование API",
                "Как вы обеспечиваете совместимость при изменении REST API?",
                "API design",
            ),
            (
                "PostgreSQL",
                "Приведите пример оптимизации медленного запроса PostgreSQL.",
                "Работа с базой данных",
            ),
            (
                "Очереди сообщений",
                "Как организовать retry и dead-letter очередь без бесконечных повторов?",
                "Отказоустойчивость",
            ),
        ]
        questions = [
            QuestionRow(
                id=f"demo-upcoming-2-q{index + 1}",
                candidate_id=candidate.id,
                order_index=index,
                kind="generated",
                text=text,
                topic=topic,
                competency=competency,
                source_refs=["vacancy", "resume", "requirements"],
                status="approved",
                created_at=now,
                updated_at=now,
            )
            for index, (topic, text, competency) in enumerate(question_specs)
        ]
        interview = InterviewRow(
            id="demo-interview-upcoming-2",
            candidate_id=candidate.id,
            status="ready",
            created_at=now,
        )
        invite = InviteRow(
            id="demo-invite-upcoming-2",
            candidate_id=candidate.id,
            token_hash=hashlib.sha256(INVITE_TOKEN.encode("utf-8")).hexdigest(),
            expires_at=now + timedelta(days=30),
            created_at=now,
        )
        session.add_all([candidate, candidate_user, *questions, interview, invite])

    await engine.dispose()
    print(f"Seeded second interview: http://localhost:3000/?invite={INVITE_TOKEN}")


if __name__ == "__main__":
    asyncio.run(seed())
