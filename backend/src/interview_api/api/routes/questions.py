from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from interview_api.api.dependencies import (
    get_document_extraction_service,
    get_question_generation_service,
)
from interview_api.api.upload_utils import measure_upload
from interview_api.domain.errors import MissingContextDocumentsError
from interview_api.domain.models import (
    DocumentInput,
    ErrorResponse,
    GenerateQuestionsParameters,
    GenerateQuestionsResponse,
    LanguageCode,
)
from interview_api.services.document_extraction import DocumentExtractionService
from interview_api.services.question_generation import QuestionGenerationService

router = APIRouter(prefix="/api/v1/questions", tags=["questions"])


@router.post(
    "/generate",
    response_model=GenerateQuestionsResponse,
    responses={
        404: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)
async def generate_questions(
    service: Annotated[QuestionGenerationService, Depends(get_question_generation_service)],
    extraction_service: Annotated[
        DocumentExtractionService,
        Depends(get_document_extraction_service),
    ],
    question_count: Annotated[int, Form()],
    core_question_count: Annotated[int, Form()],
    language: Annotated[LanguageCode, Form()],
    cv: Annotated[UploadFile | None, File()] = None,
    vacancy: Annotated[UploadFile | None, File()] = None,
    requirements: Annotated[UploadFile | None, File()] = None,
) -> GenerateQuestionsResponse:
    try:
        parameters = GenerateQuestionsParameters(
            question_count=question_count,
            core_question_count=core_question_count,
            language=language,
        )
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc

    typed_uploads = [
        (context_type, upload)
        for context_type, upload in (
            ("cv", cv),
            ("vacancy", vacancy),
            ("requirements", requirements),
        )
        if upload is not None
    ]
    if not typed_uploads:
        raise MissingContextDocumentsError()

    try:
        documents = [
            DocumentInput(
                stream=upload.file,
                size_bytes=await measure_upload(
                    upload,
                    max_bytes=extraction_service.max_document_bytes,
                ),
                context_type=context_type,
                file_id=context_type,
                filename=upload.filename,
                content_type=upload.content_type,
            )
            for context_type, upload in typed_uploads
        ]
        contexts = await extraction_service.extract_all(documents)
    finally:
        for _context_type, upload in typed_uploads:
            await upload.close()

    return await service.generate_from_contexts(contexts, parameters)
