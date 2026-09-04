from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from interview_api.workflow.entities import (
    AnalysisItemRow,
    AnalysisRow,
    AnswerRow,
    CandidateRow,
    InterviewRow,
    MediaAssetRow,
    PositionRow,
    QuestionRow,
    ReviewProgressRow,
    UserRow,
    WorkflowBase,
)

DATABASE_URL = "sqlite+aiosqlite:////private/tmp/signal-interview-demo.sqlite3"
MEDIA_ROOT = Path("/private/tmp/signal-interview-media")


def evidence(transcript: str, quote: str, label: str, rationale: str) -> dict[str, object]:
    start = transcript.index(quote)
    return {
        "quote": quote,
        "start": start,
        "end": start + len(quote),
        "label": label,
        "rationale": rationale,
    }


async def seed() -> None:
    engine = create_async_engine(DATABASE_URL)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(WorkflowBase.metadata.create_all)

    now = datetime.now(UTC)
    async with sessions.begin() as session:
        if await session.get(CandidateRow, "demo-candidate-analysis") is not None:
            print("Demo analysis already exists: demo-candidate-analysis")
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
            id="demo-position-analysis",
            created_by="hr-demo",
            title="Senior Python Developer · демо",
            level="Senior",
            location="Москва · гибрид",
            requirements=[
                "Python и асинхронное программирование",
                "PostgreSQL и диагностика запросов",
                "Надёжные очереди сообщений",
                "CI/CD и контейнеризация",
            ],
            question_count=3,
            duration_minutes=25,
            max_follow_up_questions=1,
            vacancy_object_key="demo/vacancy.txt",
            vacancy_filename="demo-vacancy.txt",
            vacancy_content_type="text/plain",
            vacancy_text=(
                "Разработка высоконагруженных Python-сервисов, PostgreSQL, очереди "
                "сообщений, Docker и CI/CD. Важны практические примеры и личный вклад."
            ),
            seed_questions=[],
            status="active",
            created_at=now,
            updated_at=now,
        )
        candidate = CandidateRow(
            id="demo-candidate-analysis",
            position_id=position.id,
            name="Алексей Морозов",
            email="alexey.demo@example.test",
            role="Senior Python Developer",
            resume_object_key="demo/resume.txt",
            resume_filename="alexey-morozov.txt",
            resume_content_type="text/plain",
            resume_text=(
                "7 лет Python, FastAPI, asyncio, PostgreSQL, RabbitMQ, Docker, "
                "Kubernetes и GitLab CI."
            ),
            processing_status="ready",
            hiring_decision="pending",
            created_at=now,
            updated_at=now,
        )
        candidate_user = UserRow(
            id="demo-candidate-user",
            role="candidate",
            name=candidate.name,
            email=candidate.email,
            candidate_id=candidate.id,
            created_at=now,
        )
        interview = InterviewRow(
            id="demo-interview-analysis",
            candidate_id=candidate.id,
            status="completed",
            consent_at=now,
            started_at=now,
            deadline_at=now,
            completed_at=now,
            created_at=now,
        )

        questions = [
            QuestionRow(
                id="demo-question-async",
                candidate_id=candidate.id,
                order_index=0,
                kind="generated",
                text="Когда асинхронный Python оправдан и чем опасен блокирующий вызов?",
                topic="Async Python",
                competency="Асинхронное программирование",
                source_refs=["vacancy", "resume"],
                status="approved",
                created_at=now,
                updated_at=now,
            ),
            QuestionRow(
                id="demo-question-postgres",
                candidate_id=candidate.id,
                order_index=1,
                kind="generated",
                text="Как вы находите причину медленного запроса PostgreSQL?",
                topic="PostgreSQL",
                competency="Диагностика базы данных",
                source_refs=["requirements", "resume"],
                status="approved",
                created_at=now,
                updated_at=now,
            ),
            QuestionRow(
                id="demo-question-cicd",
                candidate_id=candidate.id,
                order_index=2,
                kind="generated",
                text="Как устроены сборка, деплой и откат вашего сервиса?",
                topic="CI/CD",
                competency="Доставка изменений",
                source_refs=["requirements", "resume"],
                status="approved",
                created_at=now,
                updated_at=now,
            ),
        ]
        transcripts = [
            (
                "demo-answer-async",
                questions[0].id,
                "Асинхронный код выбираю для большого числа I/O операций. "
                "Блокирующий вызов останавливает event loop и задерживает остальные корутины.",
            ),
            (
                "demo-answer-postgres",
                questions[1].id,
                "Сначала запускаю EXPLAIN ANALYZE, сравниваю ожидаемое и фактическое "
                "число строк, затем проверяю статистику, индексы и чтение с диска.",
            ),
            (
                "demo-answer-cicd",
                questions[2].id,
                "В GitLab CI запускались линтеры и тесты, образ отправлялся в registry. "
                "Настройкой Kubernetes в основном занимался DevOps, я контролировал rollout.",
            ),
        ]
        answers = [
            AnswerRow(
                id=answer_id,
                interview_id=interview.id,
                question_id=question_id,
                transcript=transcript,
                duration_seconds=95,
                created_at=now,
            )
            for answer_id, question_id, transcript in transcripts
        ]

        analysis = AnalysisRow(
            id="demo-analysis",
            candidate_id=candidate.id,
            version="demo-seed-v1",
            score=7.8,
            confidence=0.82,
            recommendation="fit",
            summary=(
                "Кандидат уверенно подтверждает Python, asyncio и диагностику PostgreSQL. "
                "На следующем этапе стоит подробнее проверить личный вклад в CI/CD и Kubernetes."
            ),
            strengths=[
                "Корректно объясняет влияние блокирующих вызовов на event loop.",
                "Использует EXPLAIN ANALYZE и проверяет качество статистики PostgreSQL.",
            ],
            growth_areas=["Личный вклад в деплой и rollback раскрыт частично."],
            unknowns=["Продакшн-опыт с Kafka не проверялся."],
            skills=["Python", "asyncio", "PostgreSQL", "Docker", "GitLab CI"],
            next_questions=[
                "Как именно тегировался Docker-образ и выполнялся rollback?",
                "За какое решение в Kubernetes вы отвечали лично?",
            ],
            model_meta={"provider": "demo-seed", "model": "curated-example"},
            created_at=now,
        )
        items = [
            AnalysisItemRow(
                id="demo-item-async",
                analysis_id=analysis.id,
                order_index=0,
                kind="criterion",
                title="Async Python — подтверждено",
                body=(
                    "Ответ правильно связывает асинхронность с I/O-нагрузкой и объясняет, "
                    "почему синхронная блокировка задерживает все корутины в event loop."
                ),
                question_id=questions[0].id,
                evidence=[
                    evidence(
                        transcripts[0][2],
                        (
                            "Блокирующий вызов останавливает event loop и задерживает "
                            "остальные корутины."
                        ),
                        "confirmed",
                        "Технически корректное объяснение влияния блокировки.",
                    )
                ],
                required_review=True,
            ),
            AnalysisItemRow(
                id="demo-item-postgres",
                analysis_id=analysis.id,
                order_index=1,
                kind="criterion",
                title="PostgreSQL — сильная диагностика",
                body=(
                    "Кандидат называет последовательный подход: план выполнения, расхождение "
                    "оценок строк, статистика, индексы и дисковый I/O."
                ),
                question_id=questions[1].id,
                evidence=[
                    evidence(
                        transcripts[1][2],
                        "Сначала запускаю EXPLAIN ANALYZE",
                        "confirmed",
                        "Назван базовый инструмент анализа фактического плана.",
                    )
                ],
                required_review=True,
            ),
            AnalysisItemRow(
                id="demo-item-cicd",
                analysis_id=analysis.id,
                order_index=2,
                kind="risk",
                title="CI/CD — требуется уточнение",
                body=(
                    "CI-проверки описаны, но личная ответственность за сборку образа, "
                    "деплой и безопасный rollback подтверждена не полностью."
                ),
                question_id=questions[2].id,
                evidence=[
                    evidence(
                        transcripts[2][2],
                        "Настройкой Kubernetes в основном занимался DevOps",
                        "check",
                        ("Нужно отделить наблюдение за rollout от личного владения процессом."),
                    )
                ],
                required_review=True,
            ),
        ]
        review_progress = [
            ReviewProgressRow(
                id=f"demo-review-{index + 1}",
                analysis_item_id=item.id,
                user_id="hr-demo",
                accumulated_seconds=10.0,
                active=False,
                completed_at=now,
            )
            for index, item in enumerate(items)
        ]

        transcript_key = "demo/interview-transcript.txt"
        transcript_text = "\n\n".join(
            f"{index + 1}. {questions[index].text}\nОтвет: {entry[2]}"
            for index, entry in enumerate(transcripts)
        )
        transcript_path = MEDIA_ROOT / transcript_key
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(transcript_text, encoding="utf-8")
        media = MediaAssetRow(
            id="demo-media-transcript",
            candidate_id=candidate.id,
            interview_id=interview.id,
            answer_id=None,
            question_id=None,
            kind="transcript",
            object_key=transcript_key,
            filename="demo-interview-transcript.txt",
            content_type="text/plain; charset=utf-8",
            size_bytes=len(transcript_text.encode("utf-8")),
            created_at=now,
        )

        session.add_all(
            [
                position,
                candidate,
                candidate_user,
                interview,
                *questions,
                *answers,
                analysis,
                *items,
                *review_progress,
                media,
            ]
        )

    await engine.dispose()
    print("Seeded demo analysis for Алексей Морозов")


if __name__ == "__main__":
    asyncio.run(seed())
