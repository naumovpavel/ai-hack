from collections.abc import Mapping
from typing import Final

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from interview_api.domain.errors import (
    ApplicationError,
    ContextNotFoundError,
    DocumentTooLargeError,
    ExtractedTextTooLargeError,
    InsufficientContextError,
    InvalidAudioError,
    InvalidContextError,
    InvalidDocumentError,
    MissingContextDocumentsError,
    PayloadTooLargeError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    ServiceNotConfiguredError,
    UnsupportedDocumentTypeError,
)
from interview_api.domain.models import ErrorDetail, ErrorResponse

ERROR_STATUS_CODES: Final[Mapping[type[ApplicationError], int]] = {
    ContextNotFoundError: 404,
    InvalidContextError: 422,
    InsufficientContextError: 422,
    MissingContextDocumentsError: 422,
    InvalidDocumentError: 422,
    UnsupportedDocumentTypeError: 415,
    DocumentTooLargeError: 413,
    ExtractedTextTooLargeError: 413,
    InvalidAudioError: 422,
    PayloadTooLargeError: 413,
    ProviderResponseError: 502,
    ProviderTimeoutError: 504,
    ProviderUnavailableError: 503,
    ServiceNotConfiguredError: 503,
}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApplicationError)
    async def handle_application_error(
        _request: Request,
        exc: ApplicationError,
    ) -> JSONResponse:
        status_code = ERROR_STATUS_CODES.get(type(exc), 500)
        payload = ErrorResponse(
            error=ErrorDetail(code=exc.code, message=exc.message, details=exc.details)
        )
        return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        payload = ErrorResponse(
            error=ErrorDetail(
                code="validation_error",
                message="The request is invalid.",
                details={"errors": jsonable_encoder(exc.errors())},
            )
        )
        return JSONResponse(status_code=422, content=payload.model_dump(mode="json"))
