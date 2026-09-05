from __future__ import annotations

from typing import Any


class WorkflowError(Exception):
    status_code = 400
    code = "workflow_error"
    message = "The interview workflow request could not be completed."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or type(self).message
        self.details = details
        super().__init__(self.message)


class WorkflowNotFoundError(WorkflowError):
    status_code = 404
    code = "workflow_not_found"
    message = "The requested workflow resource was not found."


class WorkflowConflictError(WorkflowError):
    status_code = 409
    code = "workflow_conflict"
    message = "The operation is not valid in the current workflow state."


class WorkflowValidationError(WorkflowError):
    status_code = 422
    code = "workflow_validation_error"
    message = "The workflow request is invalid."


class WorkflowUnauthorizedError(WorkflowError):
    status_code = 401
    code = "workflow_unauthorized"
    message = "A valid demo session is required."


class WorkflowForbiddenError(WorkflowError):
    status_code = 403
    code = "workflow_forbidden"
    message = "The current user cannot perform this operation."


class ReviewGateError(WorkflowConflictError):
    code = "analysis_review_incomplete"
    message = "Оцените каждый ответ и сохраните своё решение с фидбэком перед рекомендацией ИИ."


class WorkflowProviderError(WorkflowError):
    status_code = 502
    code = "workflow_provider_error"
    message = "The model provider could not complete the workflow operation."


class WorkflowServiceUnavailableError(WorkflowError):
    status_code = 503
    code = "workflow_service_unavailable"
    message = "The workflow service is not configured."
