from __future__ import annotations

import io
import wave
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(slots=True)
class QuestionProposal:
    text: str
    topic: str
    competency: str
    kind: str = "generated"
    source_refs: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FollowUpProposal:
    should_ask: bool
    question: str = ""
    topic: str = ""
    competency: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class TranscriptWord:
    text: str
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True, slots=True)
class WorkflowTranscript:
    text: str
    words: list[TranscriptWord] = field(default_factory=list)


@dataclass(slots=True)
class AnalysisItemDraft:
    kind: str
    title: str
    body: str
    question_id: str | None = None
    evidence: list[dict[str, object]] = field(default_factory=list)


@dataclass(slots=True)
class AnalysisDraft:
    score: float
    confidence: float
    recommendation: str
    summary: str
    strengths: list[str]
    growth_areas: list[str]
    unknowns: list[str]
    skills: list[str]
    next_questions: list[str]
    items: list[AnalysisItemDraft]
    model_meta: dict[str, object] = field(default_factory=dict)
    version: str = "workflow-analysis-v1"


class WorkflowAIGateway(Protocol):
    async def generate_questions(
        self,
        *,
        vacancy_text: str,
        requirements: list[str],
        resume_text: str,
        seed_questions: list[str],
        question_count: int,
        duration_minutes: int,
    ) -> list[QuestionProposal]: ...

    async def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str,
        language: str,
    ) -> WorkflowTranscript: ...

    async def propose_follow_up(
        self,
        *,
        question: str,
        topic: str,
        answer: str,
        remaining_seconds: int,
        remaining_base_questions: int,
    ) -> FollowUpProposal: ...

    async def analyze(
        self,
        *,
        vacancy_text: str,
        requirements: list[str],
        questions_and_answers: list[dict[str, object]],
    ) -> AnalysisDraft: ...

    async def synthesize(self, text: str, *, language: str) -> tuple[bytes, str]: ...


class DeterministicWorkflowAI:
    """Offline deterministic implementation intended for tests and local fallback."""

    async def generate_questions(
        self,
        *,
        vacancy_text: str,
        requirements: list[str],
        resume_text: str,
        seed_questions: list[str],
        question_count: int,
        duration_minutes: int,
    ) -> list[QuestionProposal]:
        del duration_minutes
        topics = requirements or ["Опыт по вакансии"]
        proposals = [
            QuestionProposal(
                text=text,
                topic=topics[index % len(topics)][:240],
                competency=topics[index % len(topics)][:240],
                kind="provided",
                source_refs=["position.seedQuestions"],
            )
            for index, text in enumerate(seed_questions[:question_count])
        ]
        while len(proposals) < question_count:
            index = len(proposals)
            topic = topics[index % len(topics)][:240]
            context = "резюме" if resume_text.strip() else "вакансию"
            proposals.append(
                QuestionProposal(
                    text=(
                        f"Расскажите о практическом примере по теме «{topic}» и уточните "
                        f"свой личный вклад; опирайтесь на {context}."
                    ),
                    topic=topic,
                    competency=topic,
                    source_refs=["resume", "vacancy"] if resume_text.strip() else ["vacancy"],
                )
            )
        return proposals

    async def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str,
        language: str,
    ) -> WorkflowTranscript:
        del content_type, language
        if audio.startswith(b"TEXT:"):
            text = audio[5:].decode("utf-8").strip()
        else:
            text = "Ответ кандидата сохранён; тестовая транскрипция недоступна."
        words = [
            TranscriptWord(text=word, start_seconds=index * 0.5, end_seconds=(index + 1) * 0.5)
            for index, word in enumerate(text.split())
        ]
        return WorkflowTranscript(text=text, words=words)

    async def propose_follow_up(
        self,
        *,
        question: str,
        topic: str,
        answer: str,
        remaining_seconds: int,
        remaining_base_questions: int,
    ) -> FollowUpProposal:
        del question, answer, remaining_base_questions
        if remaining_seconds < 90:
            return FollowUpProposal(should_ask=False)
        return FollowUpProposal(should_ask=False, topic=topic)

    async def analyze(
        self,
        *,
        vacancy_text: str,
        requirements: list[str],
        questions_and_answers: list[dict[str, object]],
    ) -> AnalysisDraft:
        del vacancy_text
        items: list[AnalysisItemDraft] = []
        for index, item in enumerate(questions_and_answers):
            transcript = str(item.get("answer", ""))
            question = str(item.get("question", ""))
            items.append(
                AnalysisItemDraft(
                    kind="answer",
                    title=f"Ответ {index + 1}: {str(item.get('topic', 'Тема'))}",
                    body=(
                        "Ответ получен и связан с вопросом. Требуется содержательная "
                        "проверка нанимающей командой."
                    ),
                    question_id=str(item.get("questionId", "")) or None,
                    evidence=[
                        {
                            "quote": transcript[:500],
                            "question": question[:500],
                            "label": "check",
                        }
                    ],
                )
            )
        if not items:
            items.append(
                AnalysisItemDraft(
                    kind="coverage",
                    title="Полнота интервью",
                    body="Нет ответов, достаточных для автоматической рекомендации.",
                )
            )
        named_requirements = [item for item in requirements if item.strip()]
        return AnalysisDraft(
            score=5.0,
            confidence=0.35,
            recommendation="manual_review",
            summary="Материалы структурированы; итог требует ручной проверки команды.",
            strengths=[],
            growth_areas=named_requirements[:3],
            unknowns=named_requirements[3:] or ["Недостаточно данных для уверенного вывода"],
            skills=named_requirements[:6],
            next_questions=[
                f"Уточните практический опыт: {item}" for item in named_requirements[:3]
            ],
            items=items,
            model_meta={"provider": "deterministic-test-fallback"},
        )

    async def synthesize(self, text: str, *, language: str) -> tuple[bytes, str]:
        del text, language
        stream = io.BytesIO()
        with wave.open(stream, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16_000)
            output.writeframes(b"\x00\x00" * 1_600)
        return stream.getvalue(), "audio/wav"
