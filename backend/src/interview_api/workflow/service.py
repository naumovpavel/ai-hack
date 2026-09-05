from __future__ import annotations

import hashlib
import json
import secrets
from asyncio import CancelledError
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

from interview_api.domain.models import DocumentInput
from interview_api.providers.document_text import PdfDocxTextExtractor
from interview_api.providers.interfaces import DocumentTextExtractor
from interview_api.workflow.ai import (
    AnalysisDraft,
    AnalysisItemDraft,
    WorkflowAIGateway,
    WorkflowTranscript,
)
from interview_api.workflow.entities import (
    AnalysisItemRow,
    AnalysisRow,
    AnswerRow,
    CandidateRow,
    DecisionRow,
    InterviewRow,
    PositionRow,
    QuestionRow,
    UserRow,
)
from interview_api.workflow.errors import (
    ReviewGateError,
    WorkflowConflictError,
    WorkflowForbiddenError,
    WorkflowNotFoundError,
    WorkflowProviderError,
    WorkflowUnauthorizedError,
    WorkflowValidationError,
)
from interview_api.workflow.hiring_service import HiringWorkflowMixin
from interview_api.workflow.repository import SqlAlchemyWorkflowRepository
from interview_api.workflow.schemas import (
    AnalysisEvidenceResponse,
    AnalysisItemResponse,
    AnalysisResponse,
    AnswerResponse,
    ApprovalResponse,
    CandidateDetailResponse,
    CandidateOutcomeResponse,
    CandidateSummary,
    CompleteInterviewResponse,
    DecisionRequest,
    DecisionResponse,
    InitialDecisionRequest,
    InitialDecisionResponse,
    InterviewBriefingResponse,
    InterviewStateResponse,
    MediaAssetResponse,
    MediaListResponse,
    PositionDetailResponse,
    PositionResponse,
    PublicQuestion,
    QuestionResponse,
    QuestionReviewRequest,
    QuestionReviewResponse,
    SessionResponse,
    UserResponse,
)
from interview_api.workflow.storage import ObjectStorage


class WorkflowService(HiringWorkflowMixin):
    def __init__(
        self,
        *,
        repository: SqlAlchemyWorkflowRepository,
        storage: ObjectStorage,
        ai: WorkflowAIGateway,
        invite_base_url: str = "http://localhost:3000",
        document_extractor: DocumentTextExtractor | None = None,
        clock: Callable[[], datetime] | None = None,
        max_document_bytes: int = 10 * 1024 * 1024,
        max_document_characters: int = 100_000,
        max_audio_bytes: int = 25 * 1024 * 1024,
        max_video_bytes: int = 250 * 1024 * 1024,
        answer_submission_grace_seconds: int = 60,
        cookie_secure: bool = False,
        cookie_name: str = "signal_session",
        session_ttl_hours: int = 24 * 30,
        invite_ttl_days: int = 14,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.ai = ai
        self.invite_base_url = invite_base_url.rstrip("/")
        self._extractor = document_extractor or PdfDocxTextExtractor()
        self._clock = clock or (lambda: datetime.now(UTC))
        self.max_document_bytes = max_document_bytes
        self.max_document_characters = max_document_characters
        self.max_audio_bytes = max_audio_bytes
        self.max_video_bytes = max_video_bytes
        self.answer_submission_grace_seconds = answer_submission_grace_seconds
        self.cookie_secure = cookie_secure
        self.cookie_name = cookie_name
        self.session_ttl = timedelta(hours=session_ttl_hours)
        self.invite_ttl = timedelta(days=invite_ttl_days)

    async def initialize(self) -> None:
        await self.storage.ensure_bucket()
        await self.repository.recover_interrupted_analyses()
        await self.repository.ensure_demo_users()
        await self._migrate_legacy_hiring()

    async def list_demo_users(self) -> list[UserResponse]:
        await self.repository.ensure_demo_users()
        return [self._user_response(row) for row in await self.repository.list_users()]

    async def create_demo_session(self, user_id: str) -> tuple[str, SessionResponse]:
        user = await self.repository.get_user(user_id)
        raw_token = secrets.token_urlsafe(32)
        expires_at = self._now() + self.session_ttl
        await self.repository.create_auth_session(
            user_id=user.id,
            token_hash=self._hash_token(raw_token),
            expires_at=expires_at,
        )
        return raw_token, SessionResponse(user=self._user_response(user), expires_at=expires_at)

    async def current_session(self, raw_token: str | None) -> UserResponse:
        return self._user_response(await self.require_actor(raw_token))

    async def require_actor(self, raw_token: str | None, *, role: str | None = None) -> UserRow:
        if not raw_token:
            raise WorkflowUnauthorizedError()
        user = await self.repository.resolve_auth_session(self._hash_token(raw_token), self._now())
        if user is None:
            raise WorkflowUnauthorizedError()
        if role is not None and user.role != role:
            raise WorkflowForbiddenError(details={"requiredRole": role})
        return user

    async def create_position(
        self,
        *,
        actor: UserRow,
        title: str,
        level: str,
        location: str,
        requirements: list[str],
        question_count: int,
        duration_minutes: int,
        max_follow_up_questions: int,
        seed_questions: list[str],
        vacancy_data: bytes,
        vacancy_filename: str,
        vacancy_content_type: str,
    ) -> PositionDetailResponse:
        self._require_hr(actor)
        title = title.strip()
        requirements = self._clean_lines(requirements)
        seed_questions = self._clean_lines(seed_questions)
        if len(title) < 3:
            raise WorkflowValidationError("Position title must contain at least 3 characters.")
        if not requirements:
            raise WorkflowValidationError("At least one candidate requirement is required.")
        if not 1 <= question_count <= 20:
            raise WorkflowValidationError("questionCount must be between 1 and 20.")
        if not 5 <= duration_minutes <= 120:
            raise WorkflowValidationError("durationMinutes must be between 5 and 120.")
        if not 0 <= max_follow_up_questions <= 10:
            raise WorkflowValidationError("maxFollowUpQuestions must be between 0 and 10.")
        if len(seed_questions) > question_count:
            raise WorkflowValidationError(
                "The optional seed question list cannot exceed questionCount."
            )
        vacancy_text = await self._extract_document(
            vacancy_data,
            filename=vacancy_filename,
            content_type=vacancy_content_type,
            context_type="vacancy",
        )
        position_id = self._new_id()
        object_key = self._document_key("positions", position_id, "vacancy", vacancy_filename)
        await self.storage.put_bytes(
            object_key,
            vacancy_data,
            content_type=vacancy_content_type,
            metadata={"kind": "vacancy"},
        )
        # The repository generates its own public id; keep the storage namespace
        # opaque and independent from database identifiers.
        row = await self.repository.create_position(
            created_by=actor.id,
            title=title,
            level=level.strip(),
            location=location.strip(),
            requirements=requirements,
            question_count=question_count,
            duration_minutes=duration_minutes,
            max_follow_up_questions=max_follow_up_questions,
            vacancy_object_key=object_key,
            vacancy_filename=self._safe_filename(vacancy_filename),
            vacancy_content_type=vacancy_content_type,
            vacancy_text=vacancy_text,
            seed_questions=seed_questions,
        )
        return self._position_detail(row, [])

    async def list_positions(self, *, actor: UserRow) -> list[PositionResponse]:
        self._require_hr(actor)
        return [
            self._position_response(position, count)
            for position, count in await self.repository.list_positions()
            if position.created_by == actor.id
        ]

    async def get_position_detail(
        self, *, actor: UserRow, position_id: str
    ) -> PositionDetailResponse:
        position = await self.repository.get_position(position_id)
        self._require_position_owner(actor, position)
        candidates = await self.repository.list_candidates(position.id)
        return self._position_detail(position, candidates)

    async def add_candidate(
        self,
        *,
        actor: UserRow,
        position_id: str,
        name: str,
        email: str | None,
        role: str,
        resume_data: bytes,
        resume_filename: str,
        resume_content_type: str,
    ) -> CandidateDetailResponse:
        position = await self.repository.get_position(position_id)
        self._require_position_owner(actor, position)
        if len(name.strip()) < 2:
            raise WorkflowValidationError("Candidate name is required.")
        resume_text = await self._extract_document(
            resume_data,
            filename=resume_filename,
            content_type=resume_content_type,
            context_type="resume",
        )
        proposals = await self.ai.generate_questions(
            vacancy_text=position.vacancy_text,
            requirements=list(position.requirements),
            resume_text=resume_text,
            seed_questions=list(position.seed_questions),
            question_count=position.question_count,
            duration_minutes=position.duration_minutes,
        )
        if len(proposals) != position.question_count:
            raise WorkflowProviderError(
                "The model did not produce the configured question count.",
                details={"expected": position.question_count, "actual": len(proposals)},
            )
        candidate_namespace = self._new_id()
        object_key = self._document_key(
            "candidates", candidate_namespace, "resume", resume_filename
        )
        await self.storage.put_bytes(
            object_key,
            resume_data,
            content_type=resume_content_type,
            metadata={"kind": "resume", "positionId": position.id},
        )
        candidate = await self.repository.create_candidate(
            position_id=position.id,
            name=name.strip(),
            email=email.strip() if email and email.strip() else None,
            role=role.strip(),
            resume_object_key=object_key,
            resume_filename=self._safe_filename(resume_filename),
            resume_content_type=resume_content_type,
            resume_text=resume_text,
        )
        questions = await self.repository.replace_questions(candidate.id, proposals)
        return self._candidate_detail(candidate, questions)

    async def get_candidate_detail(
        self, *, actor: UserRow, candidate_id: str
    ) -> CandidateDetailResponse:
        candidate, _position = await self._owned_candidate(actor, candidate_id)
        return self._candidate_detail(candidate, await self.repository.list_questions(candidate.id))

    async def update_question(
        self,
        *,
        actor: UserRow,
        candidate_id: str,
        question_id: str,
        text: str | None,
        topic: str | None,
        competency: str | None,
        order_index: int | None,
    ) -> QuestionResponse:
        await self._owned_candidate(actor, candidate_id)
        row = await self.repository.update_question(
            candidate_id=candidate_id,
            question_id=question_id,
            text=text.strip() if text is not None else None,
            topic=topic.strip() if topic is not None else None,
            competency=competency.strip() if competency is not None else None,
            order_index=order_index,
        )
        return self._question_response(row)

    async def list_questions(self, *, actor: UserRow, candidate_id: str) -> list[QuestionResponse]:
        await self._owned_candidate(actor, candidate_id)
        return [
            self._question_response(row)
            for row in await self.repository.list_questions(candidate_id)
        ]

    async def approve_questions(self, *, actor: UserRow, candidate_id: str) -> ApprovalResponse:
        candidate, position = await self._owned_candidate(actor, candidate_id)
        if candidate.hiring_decision != "pending":
            raise WorkflowConflictError(
                "A decided candidate cannot receive a new interview invitation."
            )
        try:
            existing_interview = await self.repository.get_interview_for_candidate(candidate.id)
        except WorkflowNotFoundError:
            existing_interview = None
        if existing_interview is not None and existing_interview.status != "ready":
            raise WorkflowConflictError(
                "An invitation can be reissued only before the interview starts.",
                details={"interviewStatus": existing_interview.status},
            )
        questions = await self.repository.list_questions(candidate.id)
        if len(questions) != position.question_count:
            raise WorkflowValidationError(
                "Question set must contain the configured number of questions."
            )
        if any(not row.text.strip() or not row.topic.strip() for row in questions):
            raise WorkflowValidationError("Every question needs text and a topic.")
        await self.repository.approve_questions(candidate.id)
        raw_invite = secrets.token_urlsafe(32)
        expires_at = self._now() + self.invite_ttl
        _invite, interview = await self.repository.upsert_invite_and_interview(
            candidate_id=candidate.id,
            token_hash=self._hash_token(raw_invite),
            expires_at=expires_at,
        )
        return ApprovalResponse(
            candidate_id=candidate.id,
            interview_id=interview.id,
            invite_token=raw_invite,
            invite_url=self._invite_url(raw_invite),
            expires_at=expires_at,
        )

    async def resolve_invite(
        self, raw_invite: str
    ) -> tuple[str, SessionResponse, InterviewBriefingResponse]:
        _invite, candidate = await self.repository.resolve_invite(
            self._hash_token(raw_invite), self._now()
        )
        user = await self.repository.get_candidate_user(candidate.id)
        raw_session, session = await self.create_demo_session(user.id)
        interview = await self.repository.get_interview_for_candidate(candidate.id)
        briefing = await self._briefing(candidate, interview)
        return raw_session, session, briefing

    async def get_interview_briefing(
        self, *, actor: UserRow, interview_id: str
    ) -> InterviewBriefingResponse:
        interview = await self._candidate_interview(actor, interview_id)
        candidate = await self.repository.get_candidate(interview.candidate_id)
        return await self._briefing(candidate, interview)

    async def get_current_candidate_interview(self, *, actor: UserRow) -> InterviewBriefingResponse:
        if actor.role != "candidate" or not actor.candidate_id:
            raise WorkflowForbiddenError(details={"requiredRole": "candidate"})
        candidate = await self.repository.get_candidate(actor.candidate_id)
        interview = await self.repository.get_interview_for_candidate(candidate.id)
        return await self._briefing(candidate, interview)

    async def start_interview(self, *, actor: UserRow, interview_id: str) -> InterviewStateResponse:
        interview = await self._candidate_interview(actor, interview_id)
        candidate = await self.repository.get_candidate(interview.candidate_id)
        position = await self._candidate_position(candidate)
        now = self._now()
        interview = await self.repository.start_interview(
            interview.id,
            started_at=now,
            deadline_at=now + timedelta(minutes=position.duration_minutes),
        )
        return await self._interview_state(interview)

    async def get_interview_state(
        self, *, actor: UserRow, interview_id: str
    ) -> InterviewStateResponse:
        return await self._interview_state(await self._candidate_interview(actor, interview_id))

    async def submit_answer(
        self,
        *,
        actor: UserRow,
        interview_id: str,
        question_id: str,
        audio_data: bytes,
        audio_filename: str,
        audio_content_type: str,
        video_data: bytes,
        video_filename: str,
        video_content_type: str,
        duration_seconds: int | None,
        language: str,
    ) -> AnswerResponse:
        interview = await self._candidate_interview(actor, interview_id)
        if interview.status != "in_progress":
            raise WorkflowConflictError("Interview is not in progress.")
        self._validate_media(audio_data, maximum=self.max_audio_bytes, label="audio", required=True)
        self._validate_media(video_data, maximum=self.max_video_bytes, label="video", required=True)
        existing_answer = await self.repository.get_answer_for_question(
            interview_id=interview.id, question_id=question_id
        )
        if existing_answer is not None:
            await self._ensure_answer_media(
                interview=interview,
                answer=existing_answer,
                question_id=question_id,
                audio_data=audio_data,
                audio_filename=audio_filename,
                audio_content_type=audio_content_type,
                video_data=video_data,
                video_filename=video_filename,
                video_content_type=video_content_type,
            )
            remaining_seconds = self._remaining_seconds(interview, self._now())
            next_question = (
                await self.repository.next_unanswered_question(interview.id)
                if remaining_seconds > 0
                else None
            )
            return AnswerResponse(
                answer_id=existing_answer.id,
                transcript=existing_answer.transcript,
                next_question=self._public_question(next_question),
                follow_up_added=False,
                remaining_seconds=remaining_seconds,
            )
        now = self._now()
        remaining_seconds = self._remaining_seconds(interview, now)
        if (
            remaining_seconds <= 0
            and self._seconds_past_deadline(interview, now) > self.answer_submission_grace_seconds
        ):
            raise WorkflowConflictError("Interview time has expired; complete the interview.")
        # A request that arrived just after the timer reached zero may still
        # persist the answer that the browser was already recording.
        current = await self.repository.next_unanswered_question(interview.id)
        if current is None:
            raise WorkflowConflictError("All interview questions have already been answered.")
        if current.id != question_id:
            raise WorkflowConflictError(
                "Answers must be submitted in interview order.",
                details={"expectedQuestionId": current.id},
            )
        transcription = await self.ai.transcribe(
            audio_data, content_type=audio_content_type, language=language
        )
        transcript = transcription.text.strip()
        if not transcript.strip():
            raise WorkflowProviderError("The speech model returned an empty transcript.")
        audio_key = self._answer_media_key(
            interview=interview,
            question_id=current.id,
            kind="audio",
            filename=audio_filename,
        )
        video_key = self._answer_media_key(
            interview=interview,
            question_id=current.id,
            kind="video",
            filename=video_filename,
        )
        await self.storage.put_bytes(
            audio_key,
            audio_data,
            content_type=audio_content_type,
            metadata={"interviewId": interview.id, "questionId": current.id},
        )
        await self.storage.put_bytes(
            video_key,
            video_data,
            content_type=video_content_type,
            metadata={"interviewId": interview.id, "questionId": current.id},
        )
        alignment_key: str | None = None
        alignment_bytes: bytes | None = None
        alignment = self._build_word_alignment(
            WorkflowTranscript(text=transcript, words=transcription.words),
            duration_seconds=duration_seconds,
        )
        if alignment["words"]:
            candidate_key = self._answer_media_key(
                interview=interview,
                question_id=current.id,
                kind="alignment",
                filename="alignment.json",
            )
            candidate_bytes = json.dumps(alignment, ensure_ascii=False).encode("utf-8")
            try:
                await self.storage.put_bytes(
                    candidate_key,
                    candidate_bytes,
                    content_type="application/json",
                    metadata={"interviewId": interview.id, "questionId": current.id},
                )
            except (OSError, WorkflowProviderError):
                pass
            else:
                alignment_key = candidate_key
                alignment_bytes = candidate_bytes
        answer = await self.repository.add_answer(
            interview_id=interview.id,
            question_id=current.id,
            transcript=transcript,
            duration_seconds=duration_seconds,
            candidate_id=interview.candidate_id,
            audio_object_key=audio_key,
            audio_filename=self._safe_filename(audio_filename),
            audio_content_type=audio_content_type,
            audio_size_bytes=len(audio_data),
            video_object_key=video_key,
            video_filename=self._safe_filename(video_filename),
            video_content_type=video_content_type,
            video_size_bytes=len(video_data),
            alignment_object_key=alignment_key,
            alignment_filename="alignment.json" if alignment_key else None,
            alignment_size_bytes=len(alignment_bytes) if alignment_bytes is not None else None,
        )
        transcript = answer.transcript

        candidate = await self.repository.get_candidate(interview.candidate_id)
        position = await self._candidate_position(candidate)
        remaining_base = await self.repository.remaining_base_questions(interview.id)
        remaining_seconds = self._remaining_seconds(interview, self._now())
        follow_up_added = False
        follow_up_count = await self.repository.count_follow_ups(candidate.id)
        if follow_up_count < position.max_follow_up_questions and remaining_seconds >= max(
            90, remaining_base * 90
        ):
            try:
                proposal = await self.ai.propose_follow_up(
                    question=current.text,
                    topic=current.topic,
                    answer=transcript,
                    remaining_seconds=remaining_seconds,
                    remaining_base_questions=remaining_base,
                )
                if proposal.should_ask:
                    await self.repository.add_follow_up(
                        candidate_id=candidate.id,
                        parent_question_id=current.id,
                        text=proposal.question,
                        topic=proposal.topic or current.topic,
                        competency=proposal.competency or current.competency,
                        reason=proposal.reason,
                    )
                    follow_up_added = True
            except WorkflowProviderError:
                # A follow-up is optional; a provider failure must not lose the
                # already persisted candidate answer.
                follow_up_added = False
        remaining_seconds = self._remaining_seconds(interview, self._now())
        next_question = (
            await self.repository.next_unanswered_question(interview.id)
            if remaining_seconds > 0
            else None
        )
        return AnswerResponse(
            answer_id=answer.id,
            transcript=answer.transcript,
            next_question=self._public_question(next_question),
            follow_up_added=follow_up_added,
            remaining_seconds=remaining_seconds,
        )

    async def question_speech(
        self, *, actor: UserRow, interview_id: str, question_id: str
    ) -> tuple[bytes, str]:
        interview = await self._candidate_interview(actor, interview_id)
        question = await self.repository.get_question(question_id)
        if question.candidate_id != interview.candidate_id or question.status != "approved":
            raise WorkflowNotFoundError("Interview question was not found.")
        if interview.status != "in_progress":
            raise WorkflowConflictError("Interview must be started before requesting speech.")
        current = await self._active_current_question(interview)
        if current is None or current.id != question.id:
            raise WorkflowConflictError("Only the current interview question can be spoken.")
        cached = await self.repository.find_question_speech(interview.id, question.id)
        if cached is not None:
            return await self.storage.get_bytes(cached.object_key), cached.content_type
        audio, content_type = await self.ai.synthesize(question.text, language="ru")
        if not audio:
            raise WorkflowProviderError("The speech model returned empty audio.")
        extension = ".mp3" if "mpeg" in content_type else ".wav"
        filename = f"question-{question.order_index + 1}{extension}"
        key = self._media_key(
            candidate_id=interview.candidate_id,
            interview_id=interview.id,
            question_id=question.id,
            kind="question-audio",
            filename=filename,
        )
        await self.storage.put_bytes(key, audio, content_type=content_type)
        await self.repository.add_media_asset(
            candidate_id=interview.candidate_id,
            interview_id=interview.id,
            answer_id=None,
            question_id=question.id,
            kind="question_audio",
            object_key=key,
            filename=filename,
            content_type=content_type,
            size_bytes=len(audio),
        )
        return audio, content_type

    async def complete_interview(
        self, *, actor: UserRow, interview_id: str
    ) -> CompleteInterviewResponse:
        interview = await self._candidate_interview(actor, interview_id)
        if interview.status == "completed":
            return CompleteInterviewResponse(
                interview_id=interview.id,
                status=interview.status,
            )
        if interview.status not in {"in_progress", "error"}:
            raise WorkflowConflictError("Interview cannot be completed in its current state.")
        answers = await self.repository.list_answers_with_questions(interview.id)
        if not answers:
            raise WorkflowValidationError("At least one recorded answer is required.")
        remaining = await self.repository.next_unanswered_question(interview.id)
        if remaining is not None and self._remaining_seconds(interview, self._now()) > 0:
            raise WorkflowConflictError(
                "Answer every interview question before completing the interview.",
                details={"nextQuestionId": remaining.id},
            )
        candidate = await self.repository.get_candidate(interview.candidate_id)
        position = await self._candidate_position(candidate)
        await self.repository.set_interview_status(interview.id, "analyzing")
        analysis_input = [
            {
                "questionId": question.id,
                "question": question.text,
                "topic": question.topic,
                "kind": question.kind,
                "answer": answer.transcript,
            }
            for answer, question in answers
        ]
        try:
            draft = await self.ai.analyze(
                vacancy_text=position.vacancy_text,
                requirements=list(position.requirements),
                questions_and_answers=analysis_input,
            )
            alignments = await self._load_answer_alignments(answers)
            self._sanitize_analysis_evidence(draft, analysis_input, alignments)
            transcript = self._render_transcript(candidate, position, answers)
            transcript_key = f"candidates/{candidate.id}/interviews/{interview.id}/transcript.txt"
            existing_transcript = await self.repository.find_interview_media(
                interview_id=interview.id, kind="transcript"
            )
            if existing_transcript is None:
                transcript_bytes = transcript.encode("utf-8")
                await self.storage.put_bytes(
                    transcript_key,
                    transcript_bytes,
                    content_type="text/plain; charset=utf-8",
                )
                await self.repository.add_media_asset(
                    candidate_id=candidate.id,
                    interview_id=interview.id,
                    answer_id=None,
                    question_id=None,
                    kind="transcript",
                    object_key=transcript_key,
                    filename="interview-transcript.txt",
                    content_type="text/plain; charset=utf-8",
                    size_bytes=len(transcript_bytes),
                )
            await self.repository.replace_analysis(candidate_id=candidate.id, draft=draft)
            interview = await self.repository.set_interview_status(
                interview.id, "completed", completed_at=self._now()
            )
        except CancelledError:
            await self.repository.set_interview_status(interview.id, "error")
            raise
        except Exception:
            await self.repository.set_interview_status(interview.id, "error")
            raise
        return CompleteInterviewResponse(
            interview_id=interview.id,
            status=interview.status,
        )

    async def get_analysis(self, *, actor: UserRow, candidate_id: str) -> AnalysisResponse:
        await self._owned_candidate(actor, candidate_id)
        return await self._analysis_response(
            await self.repository.get_analysis(candidate_id), actor.id
        )

    async def list_media(self, *, actor: UserRow, candidate_id: str) -> MediaListResponse:
        await self._owned_candidate(actor, candidate_id)
        assets: list[MediaAssetResponse] = []
        for row in await self.repository.list_media_assets(candidate_id):
            if row.kind in {"question_audio", "alignment"}:
                continue
            assets.append(
                MediaAssetResponse(
                    id=row.id,
                    kind=row.kind,
                    filename=row.filename,
                    content_type=row.content_type,
                    size_bytes=row.size_bytes,
                    download_url=await self.storage.presign_download(
                        row.object_key, filename=row.filename
                    ),
                    playback_url=(
                        await self.storage.presign_download(
                            row.object_key, filename=row.filename, inline=True
                        )
                        if row.kind == "video"
                        else None
                    ),
                    question_id=row.question_id,
                )
            )
        return MediaListResponse(candidate_id=candidate_id, assets=assets)

    async def rate_question(
        self,
        *,
        actor: UserRow,
        candidate_id: str,
        question_id: str,
        request: QuestionReviewRequest,
    ) -> AnalysisResponse:
        await self._owned_candidate(actor, candidate_id)
        analysis = await self.repository.get_analysis(candidate_id)
        question = await self.repository.get_question(question_id)
        if question.candidate_id != candidate_id:
            raise WorkflowNotFoundError("Вопрос не относится к этому интервью.")
        await self.repository.save_human_review(
            candidate_id=candidate_id,
            analysis_id=analysis.id,
            user_id=actor.id,
            question_id=question_id,
            rating=request.rating,
            now=self._now(),
        )
        return await self._analysis_response(analysis, actor.id)

    async def record_review(
        self,
        *,
        actor: UserRow,
        candidate_id: str,
        request: InitialDecisionRequest,
    ) -> AnalysisResponse:
        await self._owned_candidate(actor, candidate_id)
        analysis = await self.repository.get_analysis(candidate_id)
        questions = await self.repository.list_questions(candidate_id)
        await self.repository.save_human_review(
            candidate_id=candidate_id,
            analysis_id=analysis.id,
            user_id=actor.id,
            initial_status=request.status.value,
            feedback=request.candidate_feedback.strip(),
            internal_reason=request.internal_reason.strip(),
            required_question_ids={question.id for question in questions},
            now=self._now(),
        )
        return await self._analysis_response(analysis, actor.id)

    async def decide(
        self,
        *,
        actor: UserRow,
        candidate_id: str,
        request: DecisionRequest,
    ) -> DecisionResponse:
        await self._owned_candidate(actor, candidate_id)
        analysis = await self.repository.get_analysis(candidate_id)
        review = await self.repository.get_human_review(analysis.id, actor.id)
        if review is None or review.revealed_at is None:
            raise ReviewGateError()
        ai_status = {"fit": "next_stage", "not_fit": "rejected"}.get(analysis.recommendation)
        if (
            request.status.value != review.initial_status
            and request.status.value == ai_status
            and not request.change_reason.strip()
        ):
            raise WorkflowValidationError(
                "Объясните, почему рекомендация ИИ изменила ваше решение.",
                details={"field": "changeReason"},
            )
        row = await self.repository.save_decision(
            candidate_id=candidate_id,
            decided_by=actor.id,
            status=request.status.value,
            internal_reason=request.internal_reason.strip(),
            candidate_feedback=request.candidate_feedback.strip(),
            analysis_id=analysis.id,
            change_reason=request.change_reason.strip(),
        )
        return self._decision_response(row)

    async def candidate_outcome(self, *, actor: UserRow) -> CandidateOutcomeResponse:
        if actor.role != "candidate" or not actor.candidate_id:
            raise WorkflowForbiddenError(details={"requiredRole": "candidate"})
        candidate = await self.repository.get_candidate(actor.candidate_id)
        decision = await self.repository.get_decision(candidate.id)
        if decision is None:
            return CandidateOutcomeResponse(candidate_id=candidate.id, status="pending")
        # Deliberately omit the internal reason from every candidate-facing model.
        return CandidateOutcomeResponse(
            candidate_id=candidate.id,
            status=decision.status,  # type: ignore[arg-type]
            candidate_feedback=decision.candidate_feedback or None,
            decided_at=decision.decided_at,
        )

    async def _owned_candidate(
        self, actor: UserRow, candidate_id: str
    ) -> tuple[CandidateRow, PositionRow]:
        candidate = await self.repository.get_candidate(candidate_id)
        position = await self._candidate_position(candidate)
        self._require_position_owner(actor, position)
        return candidate, position

    async def _candidate_interview(self, actor: UserRow, interview_id: str) -> InterviewRow:
        if actor.role != "candidate" or not actor.candidate_id:
            raise WorkflowForbiddenError(details={"requiredRole": "candidate"})
        interview = await self.repository.get_interview(interview_id)
        if interview.candidate_id != actor.candidate_id:
            raise WorkflowForbiddenError()
        return interview

    async def _briefing(
        self, candidate: CandidateRow, interview: InterviewRow
    ) -> InterviewBriefingResponse:
        position = await self._candidate_position(candidate)
        questions = [
            row
            for row in await self.repository.list_questions(candidate.id)
            if row.status == "approved"
        ]
        current = await self._active_current_question(interview)
        topics = list(dict.fromkeys(row.topic for row in questions if row.topic.strip()))
        return InterviewBriefingResponse(
            interview_id=interview.id,
            candidate_id=candidate.id,
            candidate_name=candidate.name,
            position_id=position.id,
            position_title=position.title,
            topics=topics,
            question_count=len([row for row in questions if row.kind != "follow_up"]),
            duration_minutes=position.duration_minutes,
            status=interview.status,
            current_question=self._public_question(current),
            allows_follow_ups=position.max_follow_up_questions > 0,
        )

    async def _interview_state(self, interview: InterviewRow) -> InterviewStateResponse:
        current = await self._active_current_question(interview)
        return InterviewStateResponse(
            interview_id=interview.id,
            status=interview.status,
            started_at=interview.started_at,
            deadline_at=interview.deadline_at,
            remaining_seconds=self._remaining_seconds(interview, self._now()),
            current_question=self._public_question(current),
            answered_question_ids=await self.repository.list_answered_question_ids(interview.id),
        )

    async def _active_current_question(self, interview: InterviewRow) -> QuestionRow | None:
        if interview.status != "in_progress":
            return None
        if self._remaining_seconds(interview, self._now()) <= 0:
            return None
        return await self.repository.next_unanswered_question(interview.id)

    async def _analysis_response(self, analysis: AnalysisRow, user_id: str) -> AnalysisResponse:
        review = await self.repository.get_human_review(analysis.id, user_id)
        decision = await self.repository.get_decision(analysis.candidate_id)
        questions = await self.repository.list_questions(analysis.candidate_id)
        answers = await self.repository.list_answers_by_question_ids([q.id for q in questions])
        answer_texts = {answer.question_id: answer.transcript for answer in answers}
        ratings = review.question_ratings if review else {}
        review_complete = bool(questions) and all(q.id in ratings for q in questions)
        unlocked = bool(review and review.revealed_at) or decision is not None
        # Question-specific reasoning helps reviewers check each answer. Overall
        # conclusions stay hidden until their own decision and feedback are saved.
        analysis_items = await self.repository.list_analysis_items(analysis.id)
        items = [
            self._analysis_item_response(item, answer_text=answer_texts.get(item.question_id or ""))
            for item in analysis_items
            if unlocked or item.question_id in answer_texts
        ]
        return AnalysisResponse(
            id=analysis.id,
            candidate_id=analysis.candidate_id,
            version=analysis.version,
            score=analysis.score if unlocked else None,
            confidence=analysis.confidence if unlocked else None,
            recommendation=analysis.recommendation if unlocked else None,
            summary=analysis.summary if unlocked else None,
            strengths=list(analysis.strengths) if unlocked else [],
            growth_areas=list(analysis.growth_areas) if unlocked else [],
            unknowns=list(analysis.unknowns) if unlocked else [],
            skills=list(analysis.skills) if unlocked else [],
            next_questions=list(analysis.next_questions) if unlocked else [],
            items=items,
            review_complete=review_complete,
            recommendation_locked=not unlocked,
            questions=[
                QuestionReviewResponse(
                    question_id=q.id,
                    text=q.text,
                    topic=q.topic,
                    kind=q.kind,
                    answer_text=answer_texts.get(q.id),
                    rating=ratings.get(q.id),
                )
                for q in questions
            ],
            initial_decision=InitialDecisionResponse(
                status=review.initial_status,
                candidate_feedback=review.initial_feedback,
                internal_reason=review.initial_internal_reason,
                recorded_at=review.revealed_at,
            )
            if review and review.revealed_at
            else None,
            final_decision=self._decision_response(decision) if decision else None,
            change_reason=review.change_reason if review else "",
            created_at=analysis.created_at,
        )

    def _analysis_item_response(
        self,
        item: AnalysisItemRow,
        *,
        answer_text: str | None,
    ) -> AnalysisItemResponse:
        return AnalysisItemResponse(
            id=item.id,
            order_index=item.order_index,
            kind=item.kind,
            title=item.title,
            body=item.body,
            question_id=item.question_id,
            answer_text=answer_text,
            evidence=self._analysis_evidence_responses(item.evidence, answer_text),
        )

    async def _extract_document(
        self,
        data: bytes,
        *,
        filename: str,
        content_type: str,
        context_type: str,
    ) -> str:
        if not data:
            raise WorkflowValidationError("Uploaded document is empty.")
        if len(data) > self.max_document_bytes:
            raise WorkflowValidationError(
                "Uploaded document is too large.",
                details={"maxBytes": self.max_document_bytes},
            )
        document = DocumentInput(
            stream=BytesIO(data),
            size_bytes=len(data),
            context_type=context_type,
            file_id=context_type,
            filename=filename,
            content_type=content_type,
        )
        text = await self._extractor.extract(document)
        if len(text) > self.max_document_characters:
            raise WorkflowValidationError(
                "Extracted document text is too large.",
                details={"maxCharacters": self.max_document_characters},
            )
        return text

    def _remaining_seconds(self, interview: InterviewRow, now: datetime) -> int:
        if interview.deadline_at is None:
            return 0
        deadline = interview.deadline_at
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        return max(0, int((deadline - now).total_seconds()))

    @staticmethod
    def _seconds_past_deadline(interview: InterviewRow, now: datetime) -> float:
        if interview.deadline_at is None:
            return float("inf")
        deadline = interview.deadline_at
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        return max(0.0, (now - deadline).total_seconds())

    @staticmethod
    def _validate_media(
        data: bytes,
        *,
        maximum: int,
        label: str,
        required: bool,
    ) -> None:
        if required and not data:
            raise WorkflowValidationError(f"Uploaded {label} is empty.")
        if len(data) > maximum:
            raise WorkflowValidationError(
                f"Uploaded {label} is too large.", details={"maxBytes": maximum}
            )

    async def _ensure_answer_media(
        self,
        *,
        interview: InterviewRow,
        answer: AnswerRow,
        question_id: str,
        audio_data: bytes,
        audio_filename: str,
        audio_content_type: str,
        video_data: bytes,
        video_filename: str,
        video_content_type: str,
    ) -> None:
        media = (
            ("audio", audio_data, audio_filename, audio_content_type),
            ("video", video_data, video_filename, video_content_type),
        )
        for kind, data, filename, content_type in media:
            if await self.repository.find_answer_media(answer_id=answer.id, kind=kind) is not None:
                continue
            object_key = self._answer_media_key(
                interview=interview,
                question_id=question_id,
                kind=kind,
                filename=filename,
            )
            await self.storage.put_bytes(
                object_key,
                data,
                content_type=content_type,
                metadata={"interviewId": interview.id, "questionId": question_id},
            )
            await self.repository.add_media_asset(
                candidate_id=interview.candidate_id,
                interview_id=interview.id,
                answer_id=answer.id,
                question_id=question_id,
                kind=kind,
                object_key=object_key,
                filename=self._safe_filename(filename),
                content_type=content_type,
                size_bytes=len(data),
            )

    def _answer_media_key(
        self,
        *,
        interview: InterviewRow,
        question_id: str,
        kind: str,
        filename: str,
    ) -> str:
        extension = Path(self._safe_filename(filename)).suffix.lower()[:12]
        return (
            f"candidates/{interview.candidate_id}/interviews/{interview.id}/"
            f"questions/{question_id}/{kind}{extension}"
        )

    @staticmethod
    def parse_lines(value: str | None) -> list[str]:
        if value is None or not value.strip():
            return []
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise WorkflowValidationError("Expected a JSON string array.") from exc
            if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
                raise WorkflowValidationError("Expected a JSON string array.")
            return [item.strip() for item in parsed if item.strip()]
        return [line.strip() for line in stripped.splitlines() if line.strip()]

    @staticmethod
    def _clean_lines(values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @staticmethod
    def _safe_filename(filename: str) -> str:
        name = Path(filename or "upload.bin").name
        return (
            "".join(character for character in name if character.isalnum() or character in ".-_ ")[
                :500
            ]
            or "upload.bin"
        )

    def _document_key(self, group: str, owner_id: str, kind: str, filename: str) -> str:
        extension = Path(self._safe_filename(filename)).suffix.lower()[:12]
        return f"{group}/{owner_id}/documents/{kind}-{self._new_id()}{extension}"

    def _media_key(
        self,
        *,
        candidate_id: str,
        interview_id: str,
        question_id: str,
        kind: str,
        filename: str,
    ) -> str:
        extension = Path(self._safe_filename(filename)).suffix.lower()[:12]
        return (
            f"candidates/{candidate_id}/interviews/{interview_id}/questions/"
            f"{question_id}/{kind}-{self._new_id()}{extension}"
        )

    def _invite_url(self, token: str) -> str:
        encoded = quote(token, safe="")
        if "{token}" in self.invite_base_url:
            return self.invite_base_url.format(token=encoded)
        if self.invite_base_url.endswith("?invite="):
            return self.invite_base_url + encoded
        return f"{self.invite_base_url.rstrip('/')}/?invite={encoded}"

    @staticmethod
    def _build_word_alignment(
        transcript: WorkflowTranscript, *, duration_seconds: int | None
    ) -> dict[str, object]:
        text = transcript.text
        cursor = 0
        aligned: list[dict[str, object]] = []
        for word in transcript.words:
            needle = word.text.strip()
            if not needle:
                continue
            start = text.find(needle, cursor)
            end = start + len(needle) if start >= 0 else -1
            if start < 0:
                normalized = "".join(
                    character.casefold() for character in needle if character.isalnum()
                )
                scan = cursor
                while normalized and scan < len(text):
                    while scan < len(text) and text[scan].isspace():
                        scan += 1
                    candidate_start = scan
                    while scan < len(text) and not text[scan].isspace():
                        scan += 1
                    candidate = text[candidate_start:scan]
                    candidate_normalized = "".join(
                        character.casefold() for character in candidate if character.isalnum()
                    )
                    if candidate_normalized == normalized:
                        start, end = candidate_start, scan
                        break
            if start < 0 or end <= start:
                continue
            aligned.append(
                {
                    "text": text[start:end],
                    "start": start,
                    "end": end,
                    "start_seconds": word.start_seconds,
                    "end_seconds": word.end_seconds,
                }
            )
            cursor = end
        return {
            "version": 1,
            "text": text,
            "duration_seconds": duration_seconds,
            "words": aligned,
        }

    async def _load_answer_alignments(
        self, answers: list[tuple[AnswerRow, QuestionRow]]
    ) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for answer_value, question_value in answers:
            asset = await self.repository.find_answer_media(
                answer_id=answer_value.id, kind="alignment"
            )
            if asset is None:
                continue
            try:
                data = await self.storage.get_bytes(asset.object_key)
                payload = json.loads(data.decode("utf-8"))
            except (
                UnicodeError,
                json.JSONDecodeError,
                WorkflowNotFoundError,
                WorkflowProviderError,
            ):
                continue
            if (
                isinstance(payload, dict)
                and payload.get("text") == answer_value.transcript
                and isinstance(payload.get("words"), list)
            ):
                result[question_value.id] = payload
        return result

    @staticmethod
    def _clip_for_range(
        alignment: dict[str, object] | None, start: int, end: int
    ) -> tuple[float | None, float | None]:
        if not alignment:
            return None, None
        words = alignment.get("words")
        if not isinstance(words, list):
            return None, None
        overlapping: list[dict[str, object]] = []
        for value in words:
            if not isinstance(value, dict):
                continue
            word_start = value.get("start")
            word_end = value.get("end")
            if (
                isinstance(word_start, int)
                and isinstance(word_end, int)
                and word_start < end
                and start < word_end
            ):
                overlapping.append(value)
        if not overlapping:
            return None, None
        try:
            clip_start = max(0.0, float(overlapping[0]["start_seconds"]) - 0.5)
            clip_end = float(overlapping[-1]["end_seconds"]) + 0.5
            duration = alignment.get("duration_seconds")
            if isinstance(duration, (int, float)) and duration >= 0:
                clip_end = min(clip_end, float(duration))
        except (KeyError, TypeError, ValueError):
            return None, None
        if clip_end <= clip_start:
            return None, None
        return round(clip_start, 3), round(clip_end, 3)

    @staticmethod
    def _analysis_evidence_responses(
        evidence_values: list[dict[str, object]], answer_text: str | None
    ) -> list[AnalysisEvidenceResponse]:
        result: list[AnalysisEvidenceResponse] = []
        for evidence in evidence_values:
            quote_text = evidence.get("quote")
            label = evidence.get("label")
            start = evidence.get("start")
            end = evidence.get("end")
            if (
                not isinstance(quote_text, str)
                or label not in {"confirmed", "incorrect", "check"}
                or not isinstance(start, int)
                or not isinstance(end, int)
                or start < 0
                or end <= start
                or (answer_text is not None and end > len(answer_text))
            ):
                continue
            raw_clip_start = evidence.get("clip_start_seconds")
            raw_clip_end = evidence.get("clip_end_seconds")
            clip_start = float(raw_clip_start) if isinstance(raw_clip_start, (int, float)) else None
            clip_end = float(raw_clip_end) if isinstance(raw_clip_end, (int, float)) else None
            if clip_start is None or clip_end is None or clip_end <= clip_start:
                clip_start = clip_end = None
            result.append(
                AnalysisEvidenceResponse(
                    quote=quote_text,
                    label=label,
                    rationale=str(evidence.get("rationale", "")),
                    start=start,
                    end=end,
                    clip_start_seconds=clip_start,
                    clip_end_seconds=clip_end,
                )
            )
        return result

    @staticmethod
    def _sanitize_analysis_evidence(
        draft: AnalysisDraft,
        questions_and_answers: list[dict[str, object]],
        alignments: dict[str, dict[str, object]] | None = None,
    ) -> None:
        """Drop hallucinated evidence and attach exact transcript offsets."""

        alignments = alignments or {}
        transcripts = {
            str(item.get("questionId", "")): str(item.get("answer", ""))
            for item in questions_and_answers
        }
        combined = "\n".join(transcripts.values())
        for item in draft.items:
            source = transcripts.get(item.question_id or "", combined)
            accepted: list[dict[str, object]] = []
            occupied: list[tuple[int, int]] = []
            for evidence in item.evidence:
                quote_text = evidence.get("quote")
                if not isinstance(quote_text, str) or not quote_text:
                    continue
                start = source.find(quote_text)
                if start < 0:
                    continue
                end = start + len(quote_text)
                if any(
                    start < previous_end and previous_start < end
                    for previous_start, previous_end in occupied
                ):
                    continue
                occupied.append((start, end))
                clip_start, clip_end = WorkflowService._clip_for_range(
                    alignments.get(item.question_id or ""), start, end
                )
                accepted.append(
                    {
                        **evidence,
                        "quote": quote_text,
                        "start": start,
                        "end": end,
                        "clip_start_seconds": clip_start,
                        "clip_end_seconds": clip_end,
                    }
                )
            item.evidence = accepted

        # Shortcut lists are also conclusions. Mirror each one into the review
        # stream so the decision gate covers every point shown after unlock.
        existing = {(item.kind, item.body.strip().casefold()) for item in draft.items}
        summaries = (
            ("strength", "Сильная сторона", draft.strengths),
            ("growth_area", "Зона развития", draft.growth_areas),
            ("unknown", "Не подтверждено", draft.unknowns),
        )
        for kind, title, values in summaries:
            for value in values:
                key = (kind, value.strip().casefold())
                if value.strip() and key not in existing:
                    draft.items.append(
                        AnalysisItemDraft(kind=kind, title=title, body=value.strip())
                    )
                    existing.add(key)

    @staticmethod
    def _render_transcript(
        candidate: CandidateRow,
        position: PositionRow,
        answers: list[tuple[object, object]],
    ) -> str:
        lines = [
            f"Кандидат: {candidate.name}",
            f"Позиция: {position.title}",
            "",
        ]
        for index, pair in enumerate(answers, start=1):
            answer, question = pair
            lines.extend(
                [
                    f"{index}. {question.text}",
                    f"Тема: {question.topic}",
                    f"Ответ: {answer.transcript}",
                    "",
                ]
            )
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _hash_token(raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _new_id() -> str:
        return secrets.token_hex(16)

    def _now(self) -> datetime:
        value = self._clock()
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    @staticmethod
    def _require_hr(actor: UserRow) -> None:
        if actor.role != "hr":
            raise WorkflowForbiddenError(details={"requiredRole": "hr"})

    def _require_position_owner(self, actor: UserRow, position: PositionRow) -> None:
        self._require_hr(actor)
        if position.created_by != actor.id:
            raise WorkflowForbiddenError()

    @staticmethod
    def _user_response(row: UserRow) -> UserResponse:
        return UserResponse(
            id=row.id,
            role=row.role,  # type: ignore[arg-type]
            name=row.name,
            email=row.email,
            candidate_id=row.candidate_id,
        )

    @staticmethod
    def _position_response(row: PositionRow, candidate_count: int) -> PositionResponse:
        return PositionResponse(
            id=row.id,
            title=row.title,
            level=row.level,
            location=row.location,
            description=row.vacancy_text,
            requirements=list(row.requirements),
            question_count=row.question_count,
            duration_minutes=row.duration_minutes,
            max_follow_up_questions=row.max_follow_up_questions,
            status=row.status,
            created_at=row.created_at,
            candidate_count=candidate_count,
        )

    def _position_detail(
        self, row: PositionRow, candidates: list[CandidateRow]
    ) -> PositionDetailResponse:
        return PositionDetailResponse(
            **self._position_response(row, len(candidates)).model_dump(),
            vacancy_filename=row.vacancy_filename,
            seed_questions=list(row.seed_questions),
            candidates=[self._candidate_summary(item) for item in candidates],
        )

    @staticmethod
    def _candidate_summary(row: CandidateRow) -> CandidateSummary:
        return CandidateSummary(
            id=row.id,
            position_id=row.position_id,
            name=row.name,
            email=row.email,
            role=row.role,
            processing_status=row.processing_status,
            hiring_decision=row.hiring_decision,
            created_at=row.created_at,
        )

    def _candidate_detail(
        self, row: CandidateRow, questions: list[QuestionRow]
    ) -> CandidateDetailResponse:
        return CandidateDetailResponse(
            **self._candidate_summary(row).model_dump(),
            resume_filename=row.resume_filename,
            questions=[self._question_response(item) for item in questions],
        )

    @staticmethod
    def _question_response(row: QuestionRow) -> QuestionResponse:
        return QuestionResponse(
            id=row.id,
            candidate_id=row.candidate_id,
            parent_question_id=row.parent_question_id,
            order_index=row.order_index,
            kind=row.kind,  # type: ignore[arg-type]
            text=row.text,
            topic=row.topic,
            competency=row.competency,
            source_refs=list(row.source_refs),
            follow_up_reason=row.follow_up_reason,
            status=row.status,
        )

    @staticmethod
    def _public_question(row: QuestionRow | None) -> PublicQuestion | None:
        if row is None:
            return None
        return PublicQuestion(
            id=row.id,
            text=row.text,
            topic=row.topic,
            kind=row.kind,  # type: ignore[arg-type]
            order_index=row.order_index,
            follow_up_reason=row.follow_up_reason,
        )

    @staticmethod
    def _decision_response(row: DecisionRow) -> DecisionResponse:
        return DecisionResponse(
            id=row.id,
            candidate_id=row.candidate_id,
            status=row.status,  # type: ignore[arg-type]
            internal_reason=row.internal_reason,
            candidate_feedback=row.candidate_feedback,
            decided_at=row.decided_at,
        )
