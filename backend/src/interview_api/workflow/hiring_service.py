from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

from pypdf import PdfReader

from interview_api.workflow.ai import QuestionProposal
from interview_api.workflow.entities import CandidateRow, HiringResourceRow, PositionRow, UserRow
from interview_api.workflow.errors import WorkflowValidationError
from interview_api.workflow.hiring_ai import HiringAI
from interview_api.workflow.hiring_schemas import (
    CandidateCreateRequest,
    CandidateDraftResponse,
    CompanyCandidateSummary,
    ContextDocumentResponse,
    InterviewCreateRequest,
    InterviewDraftResponse,
    InterviewPlanDetailResponse,
    InterviewPlanResponse,
    InterviewTemplateFields,
    InterviewTemplateResponse,
    VacancyCreateRequest,
    VacancyDetailResponse,
    VacancyDraftResponse,
    VacancyFields,
    VacancyResponse,
    VacancyTemplateResponse,
)
from interview_api.workflow.hiring_templates import generic_templates, template_id
from interview_api.workflow.schemas import ApprovalResponse


class HiringWorkflowMixin:
    """Company-level hiring setup layered over the existing candidate interview engine."""

    def _hiring_ai(self) -> HiringAI:
        return HiringAI(self.ai)

    def _company_lock(self, owner: str) -> asyncio.Lock:
        if not hasattr(self, "_company_locks"):
            self._company_locks: dict[str, asyncio.Lock] = {}
        return self._company_locks.setdefault(owner, asyncio.Lock())

    def _resource(
        self, actor: UserRow, kind: str, payload: dict, *, resource_id: str | None = None
    ) -> HiringResourceRow:
        return HiringResourceRow(
            id=resource_id or self._new_id(),
            created_by=actor.id,
            kind=kind,
            payload=payload,
            created_at=datetime.now(UTC),
        )

    async def _ensure_templates(self, actor: UserRow) -> None:
        self._require_hr(actor)
        existing = await self.repository.list_hiring_resources(actor.id, "vacancy_template")
        if existing:
            return
        await self.repository.save_hiring_resources(
            [
                self._resource(actor, kind, payload, resource_id=resource_id)
                for resource_id, kind, payload in generic_templates(actor.id)
            ]
        )

    async def _migrate_legacy_hiring(self) -> None:
        # Older positions stored one interview directly on the vacancy. Retain their
        # settings and candidate links in a visible plan without regenerating anything.
        for position, _ in await self.repository.list_positions():
            if position.question_count <= 0:
                continue
            actor = await self.repository.get_user(position.created_by)
            await self._ensure_templates(actor)
            existing = await self.repository.list_hiring_resources(actor.id, "interview_plan")
            plan_id = template_id(actor.id, f"legacy:{position.id}")
            if any(plan.id == plan_id for plan in existing):
                continue
            questions = list(position.seed_questions)
            requirements = position.requirements or ["Опыт по вакансии"]
            while len(questions) < position.question_count:
                topic = requirements[len(questions) % len(requirements)]
                questions.append(f"Расскажите о практическом опыте по теме «{topic}».")
            plan = self._resource(
                actor,
                "interview_plan",
                {
                    "vacancyId": position.id,
                    "templateId": template_id(actor.id, "hr-technical"),
                    "name": "Интервью по вакансии",
                    "description": "Сохранённое интервью с настройками и кандидатами вакансии.",
                    "evaluates": requirements,
                    "questions": [
                        {
                            "text": value,
                            "topic": requirements[index % len(requirements)][:240],
                            "competency": requirements[index % len(requirements)][:240],
                        }
                        for index, value in enumerate(questions)
                    ],
                    "durationMinutes": position.duration_minutes,
                    "maxFollowUpQuestions": position.max_follow_up_questions,
                    "maxPersonalizedQuestions": 0,
                },
                resource_id=plan_id,
            )
            await self.repository.attach_legacy_interview_plan(plan, position.id)

    async def _company_context(self, owner: str) -> str:
        docs = await self.repository.list_hiring_resources(owner, "company_context")
        return "\n\n".join(f"## {row.payload['filename']}\n{row.payload['text']}" for row in docs)

    async def list_company_context(self, *, actor: UserRow) -> list[ContextDocumentResponse]:
        self._require_hr(actor)
        return [
            ContextDocumentResponse(
                id=row.id,
                created_at=row.created_at,
                filename=row.payload["filename"],
                text=row.payload["text"],
            )
            for row in await self.repository.list_hiring_resources(actor.id, "company_context")
        ]

    async def upload_company_context(
        self, *, actor: UserRow, data: bytes, filename: str, content_type: str
    ) -> ContextDocumentResponse:
        self._require_hr(actor)
        text = await self._extract_document(
            data, filename=filename, content_type=content_type, context_type="company_context"
        )
        if filename.lower().endswith(".pdf"):
            # Layout extraction preserves grade columns and explicit source pages.
            def pages_text() -> str:
                reader = PdfReader(BytesIO(data))
                return "\n\n".join(
                    f"[Страница {index + 1}]\n{page.extract_text(extraction_mode='layout') or ''}"
                    for index, page in enumerate(reader.pages)
                )

            text = await asyncio.to_thread(pages_text)
        normalized = await self._hiring_ai().normalize_context(
            text, pdf=data if filename.lower().endswith(".pdf") else None, filename=filename
        )
        if len(normalized) > self.max_document_characters:
            raise WorkflowValidationError("Normalized company context is too large.")
        # Serializes concurrent context additions and commits document + all template changes
        # together only after every model call succeeds. Failed adaptation preserves prior state.
        async with self._company_lock(actor.id):
            await self._ensure_templates(actor)
            previous = await self._company_context(actor.id)
            combined = f"{previous}\n\n## {filename}\n{normalized}".strip()
            if len(combined) > 180_000:
                raise WorkflowValidationError("Company context exceeds 180000 characters.")
            resources = [
                *await self.repository.list_hiring_resources(actor.id, "vacancy_template"),
                *await self.repository.list_hiring_resources(actor.id, "interview_template"),
            ]
            adapted = await self._hiring_ai().adapt_templates(
                [{"id": row.id, **row.payload} for row in resources], combined
            )
            by_id = {item["id"]: item for item in adapted}
            for row in resources:
                row.payload = {key: value for key, value in by_id[row.id].items() if key != "id"}
            object_key = self._document_key("company", actor.id, self._new_id(), filename)
            await self.storage.put_bytes(
                object_key, data, content_type=content_type, metadata={"kind": "company_context"}
            )
            document = self._resource(
                actor,
                "company_context",
                {
                    "filename": self._safe_filename(filename),
                    "text": normalized,
                    "objectKey": object_key,
                    "contentType": content_type,
                },
            )
            await self.repository.save_hiring_resources([document, *resources])
        return ContextDocumentResponse(
            id=document.id,
            filename=document.payload["filename"],
            text=normalized,
            created_at=document.created_at,
        )

    async def list_vacancy_templates(
        self, *, actor: UserRow, role: str | None = None, level: str | None = None
    ) -> list[VacancyTemplateResponse]:
        await self._ensure_templates(actor)
        return [
            VacancyTemplateResponse(id=row.id, **row.payload)
            for row in await self.repository.list_hiring_resources(actor.id, "vacancy_template")
            if (not role or row.payload["role"] == role)
            and (not level or row.payload["level"] == level)
        ]

    async def update_vacancy_template(
        self, *, actor: UserRow, template_id: str, payload: VacancyFields
    ) -> VacancyTemplateResponse:
        self._require_hr(actor)
        async with self._company_lock(actor.id):
            row = await self.repository.get_hiring_resource(
                template_id, actor.id, "vacancy_template"
            )
            row.payload = {
                **payload.model_dump(by_alias=True),
                "adapted": row.payload.get("adapted", False),
            }
            await self.repository.save_hiring_resources([row])
        return VacancyTemplateResponse(id=row.id, **row.payload)

    async def list_interview_templates(self, *, actor: UserRow) -> list[InterviewTemplateResponse]:
        await self._ensure_templates(actor)
        return [
            InterviewTemplateResponse(id=row.id, **row.payload)
            for row in await self.repository.list_hiring_resources(actor.id, "interview_template")
        ]

    async def update_interview_template(
        self, *, actor: UserRow, template_id: str, payload: InterviewTemplateFields
    ) -> InterviewTemplateResponse:
        self._require_hr(actor)
        async with self._company_lock(actor.id):
            row = await self.repository.get_hiring_resource(
                template_id, actor.id, "interview_template"
            )
            row.payload = {
                **payload.model_dump(by_alias=True),
                "adapted": row.payload.get("adapted", False),
            }
            await self.repository.save_hiring_resources([row])
        return InterviewTemplateResponse(id=row.id, **row.payload)

    async def prepare_vacancy(
        self, *, actor: UserRow, data: bytes, filename: str, content_type: str
    ) -> VacancyDraftResponse:
        self._require_hr(actor)
        text = await self._extract_document(
            data, filename=filename, content_type=content_type, context_type="vacancy"
        )
        fields = await self._hiring_ai().parse_vacancy(
            text,
            await self._company_context(actor.id),
            pdf=data if filename.lower().endswith(".pdf") else None,
            filename=filename,
        )
        key = self._document_key("vacancy-drafts", self._new_id(), "vacancy", filename)
        await self.storage.put_bytes(
            key, data, content_type=content_type, metadata={"kind": "vacancy"}
        )
        draft = self._resource(
            actor,
            "vacancy_draft",
            {
                "objectKey": key,
                "filename": self._safe_filename(filename),
                "contentType": content_type,
                "sourceText": text,
            },
        )
        await self.repository.save_hiring_resources([draft])
        return VacancyDraftResponse(draft_id=draft.id, **fields.model_dump())

    def _vacancy_response(
        self, row: PositionRow, candidate_count: int = 0, interview_count: int = 0
    ) -> VacancyResponse:
        # Legacy positions remain visible after upgrade even if optional old fields were empty.
        return VacancyResponse(
            id=row.id,
            title=row.title,
            role=row.role or row.title,
            level=row.level or "Не указан",
            description=row.vacancy_text
            if len(row.vacancy_text) >= 10
            else f"Описание вакансии: {row.vacancy_text}",
            requirements=row.requirements or ["Требования не указаны"],
            status=row.status,
            created_at=row.created_at,
            candidate_count=candidate_count,
            interview_count=interview_count,
        )

    async def list_vacancies(self, *, actor: UserRow) -> list[VacancyResponse]:
        self._require_hr(actor)
        plans = await self.repository.list_hiring_resources(actor.id, "interview_plan")
        return [
            self._vacancy_response(
                row, count, sum(plan.payload["vacancyId"] == row.id for plan in plans)
            )
            for row, count in await self.repository.list_positions()
            if row.created_by == actor.id
        ]

    async def get_vacancy(self, *, actor: UserRow, vacancy_id: str) -> VacancyDetailResponse:
        row = await self.repository.get_position(vacancy_id)
        self._require_position_owner(actor, row)
        candidates = await self.repository.list_candidates(row.id)
        plans = [
            plan
            for plan in await self.repository.list_hiring_resources(actor.id, "interview_plan")
            if plan.payload["vacancyId"] == row.id
        ]
        return VacancyDetailResponse(
            **self._vacancy_response(row, len(candidates), len(plans)).model_dump(),
            interviews=[
                self._plan_response(plan, sum(c.interview_plan_id == plan.id for c in candidates))
                for plan in plans
            ],
        )

    async def create_vacancy(
        self, *, actor: UserRow, payload: VacancyCreateRequest
    ) -> VacancyDetailResponse:
        self._require_hr(actor)
        source: dict[str, Any] = {}
        if payload.draft_id:
            draft = await self.repository.get_hiring_resource(
                payload.draft_id, actor.id, "vacancy_draft"
            )
            source = draft.payload
        if payload.template_id:
            await self.repository.get_hiring_resource(
                payload.template_id, actor.id, "vacancy_template"
            )
        row = await self.repository.create_position(
            created_by=actor.id,
            title=payload.title,
            role=payload.role,
            level=payload.level,
            location="",
            requirements=payload.requirements,
            question_count=0,
            duration_minutes=30,
            max_follow_up_questions=2,
            vacancy_object_key=source.get("objectKey", ""),
            vacancy_filename=source.get("filename", ""),
            vacancy_content_type=source.get("contentType", "text/plain"),
            vacancy_text=payload.description,
            seed_questions=[],
        )
        return await self.get_vacancy(actor=actor, vacancy_id=row.id)

    async def update_vacancy(
        self, *, actor: UserRow, vacancy_id: str, payload: VacancyFields
    ) -> VacancyDetailResponse:
        row = await self.repository.get_position(vacancy_id)
        self._require_position_owner(actor, row)
        fields = payload.model_dump()
        fields["vacancy_text"] = fields.pop("description")
        await self.repository.update_vacancy(row.id, fields)
        return await self.get_vacancy(actor=actor, vacancy_id=row.id)

    async def prepare_interview(
        self, *, actor: UserRow, vacancy_id: str, template_id: str
    ) -> InterviewDraftResponse:
        vacancy = await self.get_vacancy(actor=actor, vacancy_id=vacancy_id)
        template = await self.repository.get_hiring_resource(
            template_id, actor.id, "interview_template"
        )
        fields = {k: template.payload[k] for k in ("name", "description", "evaluates")}
        questions = await self._hiring_ai().shared_questions(
            vacancy.model_dump(mode="json", by_alias=True, exclude={"interviews"}),
            await self._company_context(actor.id),
            fields,
        )
        return InterviewDraftResponse(template_id=template.id, **fields, questions=questions)

    async def create_interview_plan(
        self, *, actor: UserRow, vacancy_id: str, payload: InterviewCreateRequest
    ) -> InterviewPlanResponse:
        await self.get_vacancy(actor=actor, vacancy_id=vacancy_id)
        template = await self.repository.get_hiring_resource(
            payload.template_id, actor.id, "interview_template"
        )
        fields = {k: template.payload[k] for k in ("name", "description", "evaluates")}
        plan = self._resource(
            actor,
            "interview_plan",
            {
                **payload.model_dump(by_alias=True),
                **fields,
                "vacancyId": vacancy_id,
            },
        )
        await self.repository.save_hiring_resources([plan])
        return self._plan_response(plan)

    @staticmethod
    def _plan_response(row: HiringResourceRow, count: int = 0) -> InterviewPlanResponse:
        return InterviewPlanResponse(
            id=row.id, **row.payload, created_at=row.created_at, candidate_count=count
        )

    async def get_interview_plan(
        self, *, actor: UserRow, plan_id: str
    ) -> InterviewPlanDetailResponse:
        self._require_hr(actor)
        plan = await self.repository.get_hiring_resource(plan_id, actor.id, "interview_plan")
        vacancy = await self.repository.get_position(plan.payload["vacancyId"])
        self._require_position_owner(actor, vacancy)
        candidates = [
            self._company_candidate(candidate, vacancy, plan)
            for candidate in await self.repository.list_candidates(vacancy.id)
            if candidate.interview_plan_id == plan.id
        ]
        return InterviewPlanDetailResponse(
            **self._plan_response(plan, len(candidates)).model_dump(),
            vacancy=self._vacancy_response(vacancy),
            candidates=candidates,
        )

    def _company_candidate(
        self, row: CandidateRow, vacancy: PositionRow, plan: HiringResourceRow | None
    ) -> CompanyCandidateSummary:
        return CompanyCandidateSummary(
            **self._candidate_summary(row).model_dump(),
            vacancy_id=vacancy.id,
            vacancy_title=vacancy.title,
            interview_plan_id=row.interview_plan_id,
            interview_name=plan.payload["name"] if plan else "Интервью",
        )

    async def list_all_candidates(
        self, *, actor: UserRow, search: str | None = None
    ) -> list[CompanyCandidateSummary]:
        self._require_hr(actor)
        plans = {
            p.id: p for p in await self.repository.list_hiring_resources(actor.id, "interview_plan")
        }
        return [
            self._company_candidate(candidate, vacancy, plans.get(candidate.interview_plan_id))
            for candidate, vacancy in await self.repository.list_company_candidates(actor.id)
            if not search or search.strip().casefold() in candidate.name.casefold()
        ]

    async def prepare_plan_candidate(
        self, *, actor: UserRow, plan_id: str, data: bytes, filename: str, content_type: str
    ) -> CandidateDraftResponse:
        plan = await self.get_interview_plan(actor=actor, plan_id=plan_id)
        text = await self._extract_document(
            data, filename=filename, content_type=content_type, context_type="resume"
        )
        profile, questions = await self._hiring_ai().candidate_draft(
            text,
            plan.vacancy.model_dump(mode="json", by_alias=True),
            await self._company_context(actor.id),
            plan.model_dump(mode="json", by_alias=True, exclude={"vacancy", "candidates"}),
        )
        key = self._document_key("candidate-drafts", self._new_id(), "resume", filename)
        await self.storage.put_bytes(
            key, data, content_type=content_type, metadata={"kind": "resume"}
        )
        draft = self._resource(
            actor,
            "candidate_draft",
            {
                "planId": plan_id,
                "objectKey": key,
                "filename": self._safe_filename(filename),
                "contentType": content_type,
                "sourceText": text,
            },
        )
        await self.repository.save_hiring_resources([draft])
        return CandidateDraftResponse(draft_id=draft.id, **profile, questions=questions)

    async def create_plan_candidate(
        self, *, actor: UserRow, plan_id: str, payload: CandidateCreateRequest
    ) -> ApprovalResponse:
        plan = await self.get_interview_plan(actor=actor, plan_id=plan_id)
        draft = await self.repository.get_hiring_resource(
            payload.draft_id, actor.id, "candidate_draft"
        )
        if draft.payload["planId"] != plan_id:
            raise WorkflowValidationError("Resume draft belongs to a different interview.")
        if len(payload.questions) > plan.max_personalized_questions:
            raise WorkflowValidationError(
                "Personalized question count exceeds the interview limit."
            )
        if not payload.name.strip():
            raise WorkflowValidationError("Candidate name is required.")
        proposals = [
            QuestionProposal(
                text=q.text,
                topic=q.topic,
                competency=q.competency,
                kind="provided",
                source_refs=["interviewPool"],
            )
            for q in plan.questions
        ]
        proposals += [
            QuestionProposal(
                text=q.text,
                topic=q.topic,
                competency=q.competency,
                source_refs=["resume", "vacancy"],
            )
            for q in payload.questions
        ]
        candidate = await self.repository.save_prepared_candidate(
            draft_id=draft.id,
            owner=actor.id,
            candidate_fields={
                "position_id": plan.vacancy_id,
                "interview_plan_id": plan.id,
                "name": payload.name.strip(),
                "email": payload.email,
                "role": payload.role,
                "resume_object_key": draft.payload["objectKey"],
                "resume_filename": draft.payload["filename"],
                "resume_content_type": draft.payload["contentType"],
                "resume_text": draft.payload["sourceText"],
            },
            proposals=proposals,
        )
        return await self.approve_questions(actor=actor, candidate_id=candidate.id)

    async def _candidate_position(self, candidate: CandidateRow) -> PositionRow:
        position = await self.repository.get_position(candidate.position_id)
        if not candidate.interview_plan_id:
            return position
        plan = await self.repository.get_hiring_resource(
            candidate.interview_plan_id, position.created_by, "interview_plan"
        )
        # Detached ORM objects: these runtime overrides never change the stored vacancy.
        position.duration_minutes = plan.payload["durationMinutes"]
        position.max_follow_up_questions = plan.payload["maxFollowUpQuestions"]
        position.question_count = len(
            [q for q in await self.repository.list_questions(candidate.id) if q.kind != "follow_up"]
        )
        position.vacancy_text = json.dumps(
            {
                "vacancy": position.vacancy_text,
                "companyContext": await self._company_context(position.created_by),
                "interview": {k: plan.payload[k] for k in ("name", "description", "evaluates")},
            },
            ensure_ascii=False,
        )
        return position
