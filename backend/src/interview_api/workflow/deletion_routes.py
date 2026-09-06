import logging

from fastapi import APIRouter, Request, Response

from interview_api.api.routes.workflow import (
    ERROR_RESPONSES,
    WorkflowAPIRoute,
    _service,
    _session_token,
)
from interview_api.workflow.deletion_repository import DeletionKind

router = APIRouter(prefix="/api/v1", tags=["workflow"], route_class=WorkflowAPIRoute)
logger = logging.getLogger(__name__)


async def _delete(request: Request, kind: DeletionKind, resource_id: str) -> Response:
    service = _service(request)
    actor = await service.require_actor(_session_token(request), role="hr")
    deleted = await service.repository.delete_hiring_aggregate(
        owner=actor.id, kind=kind, resource_id=resource_id
    )
    try:
        await service.storage.delete_owned_objects(keys=deleted.keys, prefixes=deleted.prefixes)
    except Exception:
        # Deletion/revocation must remain successful if object storage is unavailable.
        logger.exception("Hiring record deleted; private object cleanup needs retry")
    return Response(status_code=204)


@router.delete("/vacancies/{vacancy_id}", status_code=204, responses=ERROR_RESPONSES)
async def delete_vacancy(request: Request, vacancy_id: str) -> Response:
    return await _delete(request, "vacancy", vacancy_id)


@router.delete("/interview-plans/{plan_id}", status_code=204, responses=ERROR_RESPONSES)
async def delete_interview_plan(request: Request, plan_id: str) -> Response:
    return await _delete(request, "interview_plan", plan_id)


@router.delete("/candidates/{candidate_id}", status_code=204, responses=ERROR_RESPONSES)
async def delete_candidate(request: Request, candidate_id: str) -> Response:
    return await _delete(request, "candidate", candidate_id)
