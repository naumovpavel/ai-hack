from __future__ import annotations

from asyncio import CancelledError
from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, timedelta
from typing import Any
from uuid import uuid4

from interview_api.workflow.ai import PracticeQuestionProposal
from interview_api.workflow.entities import UserRow
from interview_api.workflow.errors import (
    ReviewGateError,
    WorkflowConflictError,
    WorkflowForbiddenError,
    WorkflowNotFoundError,
    WorkflowProviderError,
    WorkflowValidationError,
)
from interview_api.workflow.practice_entities import PracticeSessionRow
from interview_api.workflow.practice_topics import broad_topics, fallback_questions
from interview_api.workflow.schemas import (
    AnalysisItemResponse,
    AnalysisResponse,
    CompleteInterviewResponse,
    DecisionRequest,
    DecisionResponse,
    InitialDecisionRequest,
    InitialDecisionResponse,
    MediaAssetResponse,
    MediaListResponse,
    PracticeAnswerResponse,
    PracticeQuestionResponse,
    PracticeSetResponse,
    QuestionReviewRequest,
    QuestionReviewResponse,
)


class PracticeWorkflowMixin:
    async def _owned_practice(self, actor: UserRow, practice_id: str) -> PracticeSessionRow:
        if actor.role != "candidate" or not actor.candidate_id:
            raise WorkflowForbiddenError()
        row = await self.practice_repository.get(practice_id)
        if row.owner_user_id != actor.id or row.candidate_id != actor.candidate_id:
            raise WorkflowNotFoundError("Mock interview was not found.")
        # Revoked ownership and deleted/reassigned invitations must revoke access, too.
        await self._candidate_interview(actor, row.interview_id)
        return row

    async def create_practice_set(
        self, *, actor: UserRow, interview_id: str
    ) -> PracticeSetResponse:
        interview = await self._candidate_interview(actor, interview_id)
        existing = await self.practice_repository.for_interview(interview_id)
        if existing is not None:
            return await self.get_practice(actor=actor, practice_id=existing.id)
        if interview.status != "ready":
            raise WorkflowConflictError("Start practice before the real interview.")
        candidate = await self.repository.get_candidate(interview.candidate_id)
        position = await self._candidate_position(candidate)
        questions = [
            row for row in await self.repository.list_questions(candidate.id)
            if row.status == "approved"
        ]
        topics = broad_topics([f"{row.topic} {row.competency}" for row in questions])
        question_count = max(3, len(topics))
        context = {
            "role_family": self._practice_role_family(position.role or position.title),
            "level_band": self._practice_level_band(position.level, position.title),
            "broad_topics": topics,
        }
        safe: list[PracticeQuestionProposal] = []
        real_texts = [row.text for row in questions]
        for _attempt in range(2):
            try:
                generated = await self.ai.generate_practice_questions(
                    **context, question_count=question_count, language="ru"
                )
            except WorkflowProviderError:
                continue
            safe = self._safe_practice_questions(
                [item for item in generated if item.topic in topics], real_texts
            )
            if len(safe) >= question_count and set(topics).issubset(q.topic for q in safe):
                break
        # A provider failure must retain topic coverage, not silently replace it with
        # generic soft skills. Only local broad labels are inserted into fallback text.
        chosen: list[PracticeQuestionProposal] = []
        for topic in topics:
            alternatives = [q for q in safe if q.topic == topic] + [
                PracticeQuestionProposal(text=text, topic=topic)
                for text in fallback_questions(topic)
            ]
            for item in self._safe_practice_questions(alternatives, real_texts):
                if item.text not in {q.text for q in chosen}:
                    chosen.append(item)
                    break
            else:
                raise WorkflowProviderError("Could not create safely distinct practice questions.")
        for item in safe:
            if len(chosen) >= question_count:
                break
            if item.text not in {q.text for q in chosen}:
                chosen.append(item)
        for topic in topics * 3:
            if len(chosen) >= question_count:
                break
            for item in self._safe_practice_questions(
                [PracticeQuestionProposal(text=text, topic=topic)
                 for text in fallback_questions(topic)], real_texts
            ):
                if item.text not in {q.text for q in chosen}:
                    chosen.append(item)
                    break
        if len(chosen) < question_count:
            raise WorkflowProviderError("Could not create safely distinct practice questions.")
        row = await self.practice_repository.create(PracticeSessionRow(
            id=str(uuid4()), interview_id=interview.id, candidate_id=candidate.id,
            owner_user_id=actor.id, status="ready", context=context,
            questions=[
                PracticeQuestionResponse(
                    id=f"practice-{uuid4()}", text=item.text, topic=item.topic,
                    order_index=index, answer_seconds=max(30, min(180, item.answer_seconds)),
                ).model_dump(mode="json")
                for index, item in enumerate(chosen)
            ],
            answers=[], review={},
        ))
        return self._practice_response(row)

    def _practice_remaining(self, row: PracticeSessionRow) -> int:
        if row.deadline_at is None:
            return sum(q["answer_seconds"] + 30 for q in row.questions)
        deadline = row.deadline_at
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        return max(0, int((deadline - self._now()).total_seconds()))

    def _practice_response(self, row: PracticeSessionRow) -> PracticeSetResponse:
        answered = {answer["question_id"] for answer in row.answers}
        current = next((q for q in row.questions if q["id"] not in answered), None)
        return PracticeSetResponse(
            practice_id=row.id, interview_id=row.interview_id, status=row.status,
            questions=[PracticeQuestionResponse.model_validate(q) for q in row.questions],
            current_question=PracticeQuestionResponse.model_validate(current)
            if current and row.status == "in_progress" and self._practice_remaining(row) > 0
            else None,
            answered_question_ids=list(answered), remaining_seconds=self._practice_remaining(row),
            started_at=row.started_at, deadline_at=row.deadline_at,
        )

    async def get_practice(self, *, actor: UserRow, practice_id: str) -> PracticeSetResponse:
        return self._practice_response(await self._owned_practice(actor, practice_id))

    async def start_practice(self, *, actor: UserRow, practice_id: str) -> PracticeSetResponse:
        await self._owned_practice(actor, practice_id)

        def start(row: PracticeSessionRow) -> None:
            empty_expired = (
                row.status == "in_progress" and not row.answers
                and self._practice_remaining(row) == 0
            )
            if row.status == "in_progress" and not empty_expired:
                return
            if row.status != "ready" and not empty_expired:
                raise WorkflowConflictError("Mock interview cannot be restarted.")
            row.started_at = self._now()
            row.deadline_at = row.started_at + timedelta(
                seconds=sum(q["answer_seconds"] + 30 for q in row.questions)
            )
            row.status = "in_progress"

        return self._practice_response(await self.practice_repository.mutate(practice_id, start))

    async def submit_practice_answer(
        self, *, actor: UserRow, practice_id: str, question_id: str,
        audio_data: bytes, audio_filename: str, audio_content_type: str,
        video_data: bytes, video_filename: str, video_content_type: str,
        duration_seconds: int | None, language: str,
    ) -> PracticeAnswerResponse:
        row = await self._owned_practice(actor, practice_id)
        existing = next((a for a in row.answers if a["question_id"] == question_id), None)
        if existing is not None:
            return self._practice_answer_response(row, existing)
        self._check_practice_answer(row, question_id)
        self._validate_media(audio_data, maximum=self.max_audio_bytes, label="audio", required=True)
        self._validate_media(video_data, maximum=self.max_video_bytes, label="video", required=True)
        transcript = await self.ai.transcribe(
            audio_data, content_type=audio_content_type, language=language
        )
        if not transcript.text.strip():
            raise WorkflowProviderError("The speech model returned an empty transcript.")
        answer_id = str(uuid4())
        prefix = f"candidates/{row.candidate_id}/practice/{row.id}/{answer_id}/"
        try:
            media = []
            for kind, data, filename, content_type in (
                ("audio", audio_data, audio_filename, audio_content_type),
                ("video", video_data, video_filename, video_content_type),
            ):
                filename = self._safe_filename(filename)
                key = f"{prefix}{kind}/{filename}"
                await self.storage.put_bytes(key, data, content_type=content_type)
                media.append({
                    "id": str(uuid4()), "object_key": key, "kind": kind,
                    "filename": filename, "content_type": content_type, "size_bytes": len(data),
                    "question_id": question_id,
                })
            answer = {
                "id": answer_id, "question_id": question_id, "transcript": transcript.text.strip(),
                "duration_seconds": duration_seconds, "media": media,
                "alignment": self._build_word_alignment(
                    transcript, duration_seconds=duration_seconds
                ),
            }

            def save(current: PracticeSessionRow) -> None:
                if any(a["question_id"] == question_id for a in current.answers):
                    return  # Idempotent retry; the first complete recording wins.
                self._check_practice_answer(current, question_id)
                current.answers = [*current.answers, answer]

            row = await self.practice_repository.mutate(practice_id, save)
            saved = next(a for a in row.answers if a["question_id"] == question_id)
            if saved["id"] != answer_id:
                await self._discard_practice_upload(prefix)
            return self._practice_answer_response(row, saved)
        except (Exception, CancelledError):
            await self._discard_practice_upload(prefix)
            raise

    async def _discard_practice_upload(self, prefix: str) -> None:
        # A failed or duplicate upload must not retain private recordings indefinitely.
        with suppress(WorkflowProviderError, OSError):
            await self.storage.delete_owned_objects(keys=(), prefixes=(prefix,))

    def _check_practice_answer(self, row: PracticeSessionRow, question_id: str) -> None:
        if row.status != "in_progress":
            raise WorkflowConflictError("Mock interview is not in progress.")
        if row.deadline_at is not None:
            deadline = row.deadline_at
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=UTC)
            if (self._now() - deadline).total_seconds() > self.answer_submission_grace_seconds:
                raise WorkflowConflictError("Mock interview time has expired; complete it.")
        answered = {a["question_id"] for a in row.answers}
        current = next((q for q in row.questions if q["id"] not in answered), None)
        if current is None or current["id"] != question_id:
            raise WorkflowConflictError("Answers must be submitted in mock interview order.")

    def _practice_answer_response(
        self, row: PracticeSessionRow, answer: dict[str, Any]
    ) -> PracticeAnswerResponse:
        return PracticeAnswerResponse(
            answer_id=answer["id"], transcript=answer["transcript"],
            next_question=self._practice_response(row).current_question,
            remaining_seconds=self._practice_remaining(row),
        )

    async def practice_question_speech(
        self, *, actor: UserRow, practice_id: str, question_id: str
    ) -> tuple[bytes, str]:
        row = await self._owned_practice(actor, practice_id)
        current = self._practice_response(row).current_question
        if current is None or current.id != question_id:
            raise WorkflowConflictError("Only the current mock question can be spoken.")
        return await self.ai.synthesize(current.text, language="ru")

    async def complete_practice(
        self, *, actor: UserRow, practice_id: str
    ) -> CompleteInterviewResponse:
        row = await self._owned_practice(actor, practice_id)
        if row.status in {"completed", "analyzing"}:
            return CompleteInterviewResponse(interview_id=row.id, status=row.status)
        claimed = False

        def begin(current: PracticeSessionRow) -> None:
            nonlocal claimed
            if current.status in {"completed", "analyzing"}:
                return
            if current.status not in {"in_progress", "error"}:
                raise WorkflowConflictError("Mock interview has not started.")
            if not current.answers:
                raise WorkflowValidationError("At least one recorded answer is required.")
            if (len(current.answers) < len(current.questions)
                and self._practice_remaining(current) > 0):
                raise WorkflowConflictError("Answer every mock question before completing it.")
            current.status = "analyzing"
            claimed = True

        row = await self.practice_repository.mutate(practice_id, begin)
        if not claimed:
            return CompleteInterviewResponse(interview_id=row.id, status=row.status)
        answer_by_id = {a["question_id"]: a for a in row.answers}
        analysis_input = [
            {"questionId": q["id"], "question": q["text"], "topic": q["topic"],
             "kind": "practice", "answer": answer_by_id[q["id"]]["transcript"]}
            for q in row.questions if q["id"] in answer_by_id
        ]
        try:
            draft = await self.ai.analyze(
                vacancy_text=(f"Учебное интервью. Направление: {row.context['role_family']}. "
                              f"Уровень: {row.context['level_band']}. "
                              "Оценивай знания и ответы для личного развития кандидата."),
                requirements=row.context["broad_topics"], questions_and_answers=analysis_input,
            )
            # Model-generated foreign question IDs must never leak cross-interview evidence.
            for item in draft.items:
                if item.question_id and item.question_id not in answer_by_id:
                    item.question_id = None
                    item.evidence = []
            self._sanitize_analysis_evidence(
                draft, analysis_input, {a["question_id"]: a["alignment"] for a in row.answers}
            )
            analysis = {
                **asdict(draft), "id": str(uuid4()), "created_at": self._now().isoformat(),
                "items": [{**asdict(item), "id": str(uuid4()), "order_index": i}
                          for i, item in enumerate(draft.items)],
            }

            def finish(current: PracticeSessionRow) -> None:
                if current.status != "analyzing":
                    raise WorkflowConflictError("Mock analysis state changed.")
                current.analysis = analysis
                current.status = "completed"
                current.completed_at = self._now()

            row = await self.practice_repository.mutate(practice_id, finish)
        except (Exception, CancelledError):
            def fail(current: PracticeSessionRow) -> None:
                if current.status == "analyzing":
                    current.status = "error"
            # Deleting the parent must never resurrect the practice.
            with suppress(WorkflowNotFoundError):
                await self.practice_repository.mutate(practice_id, fail)
            raise
        return CompleteInterviewResponse(interview_id=row.id, status=row.status)

    async def get_practice_analysis(
        self, *, actor: UserRow, practice_id: str
    ) -> AnalysisResponse:
        return self._practice_analysis_response(await self._owned_practice(actor, practice_id))

    def _practice_analysis_response(self, row: PracticeSessionRow) -> AnalysisResponse:
        analysis = row.analysis
        if row.status != "completed" or analysis is None:
            raise WorkflowNotFoundError("Mock interview analysis is not ready.")
        review = row.review
        unlocked = bool(review.get("initial_decision"))
        answers = {a["question_id"]: a["transcript"] for a in row.answers}
        ratings = review.get("ratings", {})
        return AnalysisResponse(
            id=analysis["id"], candidate_id=row.candidate_id, version=analysis["version"],
            score=analysis["score"] if unlocked else None,
            confidence=analysis["confidence"] if unlocked else None,
            recommendation=analysis["recommendation"] if unlocked else None,
            summary=analysis["summary"] if unlocked else None,
            strengths=analysis["strengths"] if unlocked else [],
            growth_areas=analysis["growth_areas"] if unlocked else [],
            unknowns=analysis["unknowns"] if unlocked else [],
            skills=analysis["skills"] if unlocked else [],
            next_questions=analysis["next_questions"] if unlocked else [],
            # Match HR review: answer-specific evidence is visible before the initial
            # judgment; overall conclusions stay locked until that judgment is saved.
            items=[AnalysisItemResponse(
                id=item["id"], order_index=item["order_index"], kind=item["kind"],
                title=item["title"], body=item["body"], question_id=item["question_id"],
                answer_text=answers.get(item["question_id"]),
                evidence=self._analysis_evidence_responses(
                    item["evidence"], answers.get(item["question_id"])
                ),
            ) for item in analysis["items"]
                if unlocked or item["question_id"] in answers],
            review_complete=bool(row.questions) and all(q["id"] in ratings for q in row.questions),
            recommendation_locked=not unlocked,
            questions=[QuestionReviewResponse(
                question_id=q["id"], text=q["text"], topic=q["topic"], kind="practice",
                answer_text=answers.get(q["id"]), rating=ratings.get(q["id"]),
            ) for q in row.questions],
            initial_decision=InitialDecisionResponse.model_validate(review["initial_decision"])
            if unlocked else None,
            final_decision=DecisionResponse.model_validate(review["final_decision"])
            if review.get("final_decision") else None,
            change_reason=review.get("change_reason", ""), created_at=analysis["created_at"],
        )

    async def rate_practice_question(
        self, *, actor: UserRow, practice_id: str, question_id: str, request: QuestionReviewRequest
    ) -> AnalysisResponse:
        await self._owned_practice(actor, practice_id)

        def rate(row: PracticeSessionRow) -> None:
            self._practice_analysis_response(row)
            if question_id not in {q["id"] for q in row.questions}:
                raise WorkflowNotFoundError("Mock question was not found.")
            if row.review.get("initial_decision"):
                raise WorkflowConflictError("Initial self-assessment is already saved.")
            row.review = {**row.review, "ratings": {
                **row.review.get("ratings", {}), question_id: request.rating,
            }}

        return self._practice_analysis_response(await self.practice_repository.mutate(
            practice_id, rate
        ))

    async def record_practice_review(
        self, *, actor: UserRow, practice_id: str, request: InitialDecisionRequest
    ) -> AnalysisResponse:
        await self._owned_practice(actor, practice_id)
        fields = {"status": request.status.value,
                  "candidate_feedback": request.candidate_feedback.strip(),
                  "internal_reason": request.internal_reason.strip()}

        def reveal(row: PracticeSessionRow) -> None:
            response = self._practice_analysis_response(row)
            existing = row.review.get("initial_decision")
            if existing:
                if all(existing[key] == value for key, value in fields.items()):
                    return
                raise WorkflowConflictError("Initial self-assessment is already saved.")
            if not response.review_complete:
                raise ReviewGateError()
            row.review = {**row.review, "initial_decision": {
                **fields, "recorded_at": self._now().isoformat(),
            }}

        return self._practice_analysis_response(await self.practice_repository.mutate(
            practice_id, reveal
        ))

    async def decide_practice(
        self, *, actor: UserRow, practice_id: str, request: DecisionRequest
    ) -> DecisionResponse:
        await self._owned_practice(actor, practice_id)
        fields = {"status": request.status.value,
                  "candidate_feedback": request.candidate_feedback.strip(),
                  "internal_reason": request.internal_reason.strip()}

        def decide(row: PracticeSessionRow) -> None:
            self._practice_analysis_response(row)
            initial = row.review.get("initial_decision")
            if initial is None:
                raise ReviewGateError()
            existing = row.review.get("final_decision")
            if existing:
                if (all(existing[key] == value for key, value in fields.items())
                    and row.review.get("change_reason", "") == request.change_reason.strip()):
                    return
                raise WorkflowConflictError("Final reflection is already saved.")
            ai_status = {"fit": "next_stage", "not_fit": "rejected"}.get(
                row.analysis["recommendation"]
            )
            if (request.status.value != initial["status"] and request.status.value == ai_status
                and not request.change_reason.strip()):
                raise WorkflowValidationError(
                    "Объясните, почему рекомендация ИИ изменила вашу оценку.",
                    details={"field": "changeReason"},
                )
            row.review = {**row.review, "change_reason": request.change_reason.strip(),
                          "final_decision": {
                              **fields, "id": str(uuid4()), "candidate_id": row.candidate_id,
                              "decided_at": self._now().isoformat(),
                          }}

        row = await self.practice_repository.mutate(practice_id, decide)
        return DecisionResponse.model_validate(row.review["final_decision"])

    async def list_practice_media(
        self, *, actor: UserRow, practice_id: str
    ) -> MediaListResponse:
        row = await self._owned_practice(actor, practice_id)
        assets = []
        for answer in row.answers:
            for media in answer["media"]:
                assets.append(MediaAssetResponse(
                    **{key: value for key, value in media.items() if key != "object_key"},
                    download_url=await self.storage.presign_download(
                        media["object_key"], filename=media["filename"]
                    ),
                    playback_url=await self.storage.presign_download(
                        media["object_key"], filename=media["filename"], inline=True
                    ) if media["kind"] == "video" else None,
                ))
        return MediaListResponse(candidate_id=row.candidate_id, assets=assets)
