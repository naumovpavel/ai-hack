from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Request, Response

from interview_api.api.routes.workflow import (
    ERROR_RESPONSES,
    WorkflowAPIRoute,
    _service,
    _session_token,
    _set_session_cookie,
)
from interview_api.workflow.errors import (
    WorkflowForbiddenError,
    WorkflowNotFoundError,
    WorkflowUnauthorizedError,
)
from interview_api.workflow.schemas import SessionResponse
from interview_api.workflow.telegram_auth import TELEGRAM_LOGIN_COOKIE, TELEGRAM_LOGIN_TTL
from interview_api.workflow.telegram_schemas import (
    SwitchRoleRequest,
    TelegramStartRequest,
    TelegramStartResponse,
    TelegramStatusResponse,
)

router = APIRouter(prefix="/api/v1", tags=["auth"], route_class=WorkflowAPIRoute)


def _check_browser_origin(request: Request) -> None:
    """Allow configured frontend origins; reject cross-site cookie mutations."""
    origin = request.headers.get("origin")
    if not origin:
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise WorkflowForbiddenError("The request origin is not allowed.")
        return
    settings = getattr(request.app.state, "settings", None)
    allowed = set(getattr(settings, "cors_origin_list", []) or [])
    base = urlsplit(str(request.base_url))
    allowed.add(f"{base.scheme}://{base.netloc}")
    if origin.rstrip("/") not in allowed:
        raise WorkflowForbiddenError("The request origin is not allowed.")


@router.post(
    "/auth/telegram/start", response_model=TelegramStartResponse, responses=ERROR_RESPONSES
)
async def start_telegram_login(
    payload: TelegramStartRequest, request: Request, response: Response
) -> TelegramStartResponse:
    _check_browser_origin(request)
    service = _service(request)
    cookie, result = await service.start_telegram_login(payload.role, payload.invite_token)
    response.set_cookie(
        TELEGRAM_LOGIN_COOKIE,
        cookie,
        max_age=int(TELEGRAM_LOGIN_TTL.total_seconds()),
        httponly=True,
        secure=service.cookie_secure,
        samesite="lax",
        path="/api/v1/auth/telegram",
    )
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get(
    "/auth/telegram/status", response_model=TelegramStatusResponse, responses=ERROR_RESPONSES
)
async def telegram_login_status(request: Request, response: Response) -> TelegramStatusResponse:
    _check_browser_origin(request)
    service = _service(request)
    token, result = await service.poll_telegram_login(
        request.cookies.get(TELEGRAM_LOGIN_COOKIE), _session_token(request)
    )
    if token:
        _set_session_cookie(response, token, service)
    if result.status != "pending":
        response.delete_cookie(TELEGRAM_LOGIN_COOKIE, path="/api/v1/auth/telegram")
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/auth/role", response_model=SessionResponse, responses=ERROR_RESPONSES)
async def switch_telegram_role(
    payload: SwitchRoleRequest, request: Request, response: Response
) -> SessionResponse:
    _check_browser_origin(request)
    service = _service(request)
    token, result = await service.switch_telegram_role(_session_token(request), payload.role)
    _set_session_cookie(response, token, service)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.delete("/auth/session", status_code=204, responses=ERROR_RESPONSES)
async def logout_telegram_session(request: Request, response: Response) -> None:
    _check_browser_origin(request)
    service = _service(request)
    await service.logout_telegram_session(_session_token(request))
    response.delete_cookie(service.cookie_name, path="/")
    response.delete_cookie(TELEGRAM_LOGIN_COOKIE, path="/api/v1/auth/telegram")
    response.headers["Cache-Control"] = "no-store"


@router.post("/telegram/webhook", status_code=200, responses=ERROR_RESPONSES)
async def telegram_webhook(payload: dict[str, Any], request: Request) -> dict[str, bool]:
    service = _service(request)
    secret = getattr(service, "telegram_webhook_secret", None)
    if not secret:
        raise WorkflowNotFoundError("Telegram webhook is disabled.")
    supplied = request.headers.get("x-telegram-bot-api-secret-token", "")
    if not secrets.compare_digest(supplied.encode("utf-8"), str(secret).encode("utf-8")):
        raise WorkflowUnauthorizedError("Invalid Telegram webhook signature.")
    await service.handle_telegram_update(payload)
    return {"ok": True}
