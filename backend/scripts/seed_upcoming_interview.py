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
    WorkflowBase,
)

DATABASE_URL = "sqlite+aiosqlite:////private/tmp/signal-interview-demo.sqlite3"
INVITE_TOKEN = "demo-maria-upcoming-interview-2026"


async def seed() -> None:
    engine = create_async_engine(DATABASE_URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(WorkflowBase.metadata.create_all)

    now = datetime.now(UTC)
    async with sessions.begin() as session:
        if await session.get(CandidateRow, "demo-candidate-upcoming") is not None:
            print(f"Demo interview already exists: http://localhost:3000/?invite={INVITE_TOKEN}")
            await engine.dispose()
            return

        if await session.get(UserRow, "hr-demo") is None:
            session.add(
                UserRow(
                    id="hr-demo",
                    role="hr",
                    name="Юлия Белова",
                    email="hr@example.test",
                )
            )

        position = PositionRow(
            id="demo-position-upcoming",
            created_by="hr-demo",
            title="Middle Backend Developer · интервью",
            level="Middle",
            location="Удалённо",
            requirements=[
                "Python и FastAPI",
                "Проектирование REST API",
                "PostgreSQL",
                "Очереди сообщений и отказоустойчивость",
            ],
            question_count=4,
            duration_minutes=20,
            max_follow_up_questions=1,
            vacancy_object_key="demo/upcoming-vacancy.txt",
            vacancy_filename="backend-vacancy.txt",
            vacancy_content_type="text/plain",
            vacancy_text=(
                "Ищем Middle Backend Developer для разработки API на Python/FastAPI, "
                "работы с PostgreSQL и очередями сообщений."
            ),
            seed_questions=[
                "Расскажите о backend-сервисе, за который вы отвечали лично."
            ],
            status="active",
            created_at=now,
            updated_at=now,
        )
        candidate = CandidateRow(
            id="demo-candidate-upcoming",
            position_id=position.id,
            name="Мария Соколова",
            email="maria.demo@example.test",
            role="Python Backend Developer",
            resume_object_key="demo/upcoming-resume.txt",
            resume_filename="maria-sokolova.txt",
            resume_content_type="text/plain",
            resume_text=(
                "4 года Python. Разрабатывала API на FastAPI, работала с PostgreSQL "
                "и RabbitMQ, настраивала тесты и CI."
            ),
            processing_status="invited",
            hiring_decision="pending",
            created_at=now,
            updated_at=now,
        )
        candidate_user = UserRow(
            id="demo-upcoming-user",
            role="candidate",
            name=candidate.name,
            email=candidate.email,
            candidate_id=candidate.id,
            created_at=now,
        )
        questions = [
            QuestionRow(
                id="demo-upcoming-q1",
                candidate_id=candidate.id,
                order_index=0,
                kind="provided",
                text="Расскажите о backend-сервисе, за который вы отвечали лично.",
                topic="Опыт и личный вклад",
                competency="Самостоятельность",
                source_refs=["seedQuestions"],
                status="approved",
                created_at=now,
                updated_at=now,
            ),
            QuestionRow(
                id="demo-upcoming-q2",
                candidate_id=candidate.id,
                order_index=1,
                kind="generated",
                text="Как вы проектируете обработку ошибок и валидацию в FastAPI?",
                topic="Python и FastAPI",
                competency="Проектирование API",
                source_refs=["vacancy", "resume"],
                status="approved",
                created_at=now,
                updated_at=now,
            ),
            QuestionRow(
                id="demo-upcoming-q3",
                candidate_id=candidate.id,
                order_index=2,
                kind="generated",
                text="Как вы диагностируете медленный запрос PostgreSQL?",
                topic="PostgreSQL",
                competency="Работа с базой данных",
                source_refs=["requirements"],
                status="approved",
                created_at=now,
                updated_at=now,
            ),
            QuestionRow(
                id="demo-upcoming-q4",
                candidate_id=candidate.id,
                order_index=3,
                kind="generated",
                text="Как обеспечить повторную доставку сообщения без двойной обработки?",
                topic="Очереди сообщений",
                competency="Отказоустойчивость",
                source_refs=["requirements", "resume"],
                status="approved",
                created_at=now,
                updated_at=now,
            ),
        ]
        interview = InterviewRow(
            id="demo-interview-upcoming",
            candidate_id=candidate.id,
            status="ready",
            created_at=now,
        )
        invite = InviteRow(
            id="demo-invite-upcoming",
            candidate_id=candidate.id,
            token_hash=hashlib.sha256(INVITE_TOKEN.encode("utf-8")).hexdigest(),
            expires_at=now + timedelta(days=30),
            created_at=now,
        )
        session.add_all(
            [position, candidate, candidate_user, *questions, interview, invite]
        )

    await engine.dispose()
    print(f"Seeded upcoming interview: http://localhost:3000/?invite={INVITE_TOKEN}")


if __name__ == "__main__":
    asyncio.run(seed())
