"""Anonymous, paired before/after research, separate from hiring decisions."""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Request, Response
from pydantic import Field, StringConstraints, model_validator
from sqlalchemy import JSON, DateTime, String, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from interview_api.api.routes.workflow import WorkflowAPIRoute, _service, _session_token
from interview_api.workflow.entities import WorkflowBase, utc_now
from interview_api.workflow.errors import (
    WorkflowConflictError,
    WorkflowForbiddenError,
    WorkflowNotFoundError,
)
from interview_api.workflow.research_catalog import REASON_OPTIONS
from interview_api.workflow.schemas import ApiModel

VERSION = "signal-v2"
DEMO_VERSION = "signal-demo-v2"
RESULTS_OWNER = "wift657"
YesNo = Literal["yes", "no"]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Factors = Annotated[
    list[Annotated[str, StringConstraints(min_length=1, max_length=60)]], Field(max_length=8)
]


def validate_branch(group: str, answer: str, factors: list[str], reason: str) -> None:
    allowed = {option["id"] for option in REASON_OPTIONS[group][answer]}
    if not factors and not reason:
        raise ValueError("Выберите хотя бы одну причину или напишите свой ответ.")
    if len(factors) != len(set(factors)) or any(factor not in allowed for factor in factors):
        raise ValueError("Выбранные причины не соответствуют ответу «Да / Нет».")


class Opinion(ApiModel):
    trust: YesNo
    trust_factors: Factors
    trust_reason: Reason
    readiness: YesNo
    readiness_factors: Factors
    readiness_reason: Reason

    @model_validator(mode="after")
    def validate_opinion(self) -> Opinion:
        validate_branch("trust", self.trust, self.trust_factors, self.trust_reason)
        validate_branch("readiness", self.readiness, self.readiness_factors, self.readiness_reason)
        return self


class Baseline(Opinion):
    had_interview: YesNo
    had_ai_interview: YesNo
    experience_liked: YesNo | None
    experience_factors: Factors
    experience_reason: Reason

    @model_validator(mode="after")
    def validate_experience(self) -> Baseline:
        if self.had_interview == "no" and self.had_ai_interview != "no":
            raise ValueError("Проверьте ответы об опыте собеседований.")
        if self.had_ai_interview == "yes":
            if self.experience_liked is None:
                raise ValueError("Укажите, понравился ли опыт интервью с ИИ.")
            validate_branch(
                "experience", self.experience_liked, self.experience_factors, self.experience_reason
            )
        elif self.experience_liked is not None or self.experience_factors or self.experience_reason:
            raise ValueError("Вопрос об опыте относится только к прошедшим интервью с ИИ.")
        return self


class Followup(Opinion):
    solution_liked: YesNo
    solution_factors: Factors
    solution_reason: Reason

    @model_validator(mode="after")
    def validate_solution(self) -> Followup:
        validate_branch(
            "solution", self.solution_liked, self.solution_factors, self.solution_reason
        )
        return self


class Demo(ApiModel):
    demo_version: Literal["signal-demo-v2"]


class ResearchRow(WorkflowBase):
    __tablename__ = "workflow_research_responses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    survey_version: Mapped[str] = mapped_column(String(32), default=VERSION)
    demo_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    baseline: Mapped[dict[str, Any]] = mapped_column(JSON)
    followup: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    baseline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    demo_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


router = APIRouter(prefix="/api/v1/research", tags=["research"], route_class=WorkflowAPIRoute)
Token = Annotated[UUID, Header(alias="X-Survey-Token")]


def token_hash(token: UUID) -> str:
    return hashlib.sha256(str(token).encode()).hexdigest()


def serialize(row: ResearchRow) -> dict[str, Any]:
    return {
        "status": "complete" if row.completed_at else "demo" if row.demo_viewed_at else "baseline",
        "baseline": row.baseline,
        "followup": row.followup,
    }


async def get_row(request: Request, token: UUID) -> ResearchRow:
    async with _service(request).repository._sessions() as session:
        row = await session.scalar(
            select(ResearchRow).where(
                ResearchRow.token_hash == token_hash(token), ResearchRow.survey_version == VERSION
            )
        )
        if row is None:
            raise WorkflowNotFoundError("Сохранённый опрос не найден.")
        return row


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.get("/session")
async def get_session(request: Request, response: Response, token: Token) -> dict[str, Any]:
    no_store(response)
    return serialize(await get_row(request, token))


@router.post("/baseline")
async def save_baseline(
    payload: Baseline, request: Request, response: Response, token: Token
) -> dict[str, Any]:
    no_store(response)
    data = payload.model_dump(by_alias=True)
    # A unique token hash makes even concurrent/lost-response retries idempotent.
    async with _service(request).repository._sessions.begin() as session:
        try:
            async with session.begin_nested():
                session.add(
                    ResearchRow(id=str(uuid4()), token_hash=token_hash(token), baseline=data)
                )
                await session.flush()
        except IntegrityError:
            existing = await session.scalar(
                select(ResearchRow).where(
                    ResearchRow.token_hash == token_hash(token),
                )
            )
            if existing is None:
                raise
            if existing.survey_version != VERSION or existing.baseline != data:
                raise WorkflowConflictError(
                    "Первый опрос уже сохранён и не может быть изменён. "
                    "Обновите страницу, чтобы продолжить."
                ) from None
    return serialize(await get_row(request, token))


@router.post("/demo")
async def save_demo(
    payload: Demo, request: Request, response: Response, token: Token
) -> dict[str, Any]:
    no_store(response)
    await get_row(request, token)
    async with _service(request).repository._sessions.begin() as session:
        await session.execute(
            update(ResearchRow)
            .where(
                ResearchRow.token_hash == token_hash(token),
                ResearchRow.demo_viewed_at.is_(None),
            )
            .values(demo_viewed_at=utc_now(), demo_version=payload.demo_version)
        )
    return serialize(await get_row(request, token))


@router.post("/complete")
async def complete(
    payload: Followup, request: Request, response: Response, token: Token
) -> dict[str, Any]:
    no_store(response)
    row = await get_row(request, token)
    if not row.demo_viewed_at:
        raise WorkflowConflictError("Сначала посмотрите примеры работы сервиса.")
    data = payload.model_dump(by_alias=True)
    async with _service(request).repository._sessions.begin() as session:
        # Conditional UPDATE protects immutable answers on SQLite and PostgreSQL.
        await session.execute(
            update(ResearchRow)
            .where(
                ResearchRow.token_hash == token_hash(token),
                ResearchRow.completed_at.is_(None),
                ResearchRow.demo_viewed_at.is_not(None),
            )
            .values(followup=data, completed_at=utc_now())
        )
    saved = await get_row(request, token)
    if saved.followup != data:
        raise WorkflowConflictError(
            "Второй опрос уже сохранён и не может быть изменён. Обновите страницу."
        )
    return serialize(saved)


def metric(rows: list[ResearchRow], field: str) -> dict[str, Any]:
    pairs = [
        (row.baseline[field], row.followup[field])
        for row in rows
        if row.completed_at and row.followup
    ]
    count = len(pairs)
    before_yes = sum(before == "yes" for before, _ in pairs)
    after_yes = sum(after == "yes" for _, after in pairs)
    return {
        "pairs": count,
        "beforeYes": before_yes,
        "afterYes": after_yes,
        "beforePercent": before_yes / count * 100 if count else None,
        "afterPercent": after_yes / count * 100 if count else None,
        "deltaPp": (after_yes - before_yes) / count * 100 if count else None,
        "noToYes": pairs.count(("no", "yes")),
        "yesToNo": pairs.count(("yes", "no")),
        "yesToYes": pairs.count(("yes", "yes")),
        "noToNo": pairs.count(("no", "no")),
    }


def reason_breakdown(rows: list[ResearchRow]) -> list[dict[str, Any]]:
    completed = [row for row in rows if row.completed_at and row.followup]
    result = []
    for question in ("trust", "readiness"):
        for answer in ("yes", "no"):
            before = [row.baseline for row in completed if row.baseline[question] == answer]
            after = [row.followup for row in completed if row.followup[question] == answer]
            result.append(
                {
                    "question": question,
                    "answer": answer,
                    "beforeRespondents": len(before),
                    "afterRespondents": len(after),
                    "options": [
                        {
                            **option,
                            "before": sum(
                                option["id"] in item[f"{question}Factors"] for item in before
                            ),
                            "after": sum(
                                option["id"] in item[f"{question}Factors"] for item in after
                            ),
                        }
                        for option in REASON_OPTIONS[question][answer]
                    ],
                }
            )
    return result


async def results_rows(request: Request, *, include_legacy: bool = False) -> list[ResearchRow]:
    service = _service(request)
    actor = await service.require_actor(_session_token(request))
    if (
        not getattr(actor, "telegram_connected", False)
        or (getattr(actor, "telegram_username", None) or "").lower() != RESULTS_OWNER
    ):
        raise WorkflowForbiddenError("Результаты доступны только организатору исследования.")
    async with service.repository._sessions() as session:
        query = select(ResearchRow).order_by(ResearchRow.baseline_at)
        if not include_legacy:
            query = query.where(
                ResearchRow.survey_version == VERSION,
                or_(ResearchRow.demo_version.is_(None), ResearchRow.demo_version == DEMO_VERSION),
            )
        return list(await session.scalars(query))


@router.get("/results")
async def results(request: Request, response: Response) -> dict[str, Any]:
    no_store(response)
    rows = await results_rows(request)
    return {
        "started": len(rows),
        "demoViewed": sum(row.demo_viewed_at is not None for row in rows),
        "completed": sum(row.completed_at is not None for row in rows),
        "trust": metric(rows, "trust"),
        "readiness": metric(rows, "readiness"),
        "reasons": reason_breakdown(rows),
    }


def csv_safe(value: Any) -> Any:
    # Free-text answers must not become spreadsheet formulas when exported.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return "" if value is None else value


def export_value(answers: dict[str, Any], key: str) -> Any:
    value = answers.get(key)
    if not key.endswith("Factors") or not isinstance(value, list):
        return value
    group = key.removesuffix("Factors")
    answer_key = f"{group}Liked" if group in {"experience", "solution"} else group
    labels = {
        option["id"]: option["label"]
        for option in REASON_OPTIONS.get(group, {}).get(answers.get(answer_key), [])
    }
    return "; ".join(labels.get(item, item) for item in value)


@router.get("/results.csv")
async def export_results(request: Request) -> Response:
    # Old 0–10 responses stay available in the export, but never enter v2 metrics.
    rows = await results_rows(request, include_legacy=True)
    output = io.StringIO()
    writer = csv.writer(output)
    baseline_fields = [
        "hadInterview",
        "hadAiInterview",
        "experienceLiked",
        "experienceFactors",
        "experienceReason",
        "trust",
        "trustFactors",
        "trustReason",
        "readiness",
        "readinessFactors",
        "readinessReason",
        "trustScore",
        "readinessScore",
        "experienceImpression",
    ]
    followup_fields = [
        "trust",
        "trustFactors",
        "trustReason",
        "readiness",
        "readinessFactors",
        "readinessReason",
        "solutionLiked",
        "solutionFactors",
        "solutionReason",
        "trustScore",
        "readinessScore",
        "solutionImpression",
    ]
    writer.writerow(
        [
            "response_id",
            "survey_version",
            "demo_version",
            "baseline_at",
            "demo_viewed_at",
            "completed_at",
            *[f"before_{key}" for key in baseline_fields],
            *[f"after_{key}" for key in followup_fields],
            "trust_transition",
            "readiness_transition",
        ]
    )
    for row in rows:
        after = row.followup or {}
        transitions = [
            f"{row.baseline[key]} -> {after[key]}" if key in row.baseline and key in after else ""
            for key in ("trust", "readiness")
        ]
        writer.writerow(
            [
                csv_safe(value)
                for value in [
                    row.id,
                    row.survey_version,
                    row.demo_version,
                    row.baseline_at.isoformat(),
                    row.demo_viewed_at.isoformat() if row.demo_viewed_at else "",
                    row.completed_at.isoformat() if row.completed_at else "",
                    *[export_value(row.baseline, key) for key in baseline_fields],
                    *[export_value(after, key) for key in followup_fields],
                    *transitions,
                ]
            ]
        )
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="signal-research.csv"',
            "Cache-Control": "no-store",
        },
    )
