from fastapi import Request

from interview_api.domain.errors import ServiceNotConfiguredError
from interview_api.services.document_extraction import DocumentExtractionService
from interview_api.services.question_generation import QuestionGenerationService
from interview_api.services.transcription import TranscriptionService


def get_question_generation_service(request: Request) -> QuestionGenerationService:
    service = getattr(request.app.state, "question_generation_service", None)
    if service is None:
        raise ServiceNotConfiguredError("question_generation")
    return service


def get_transcription_service(request: Request) -> TranscriptionService:
    service = getattr(request.app.state, "transcription_service", None)
    if service is None:
        raise ServiceNotConfiguredError("transcription")
    return service


def get_document_extraction_service(request: Request) -> DocumentExtractionService:
    service = getattr(request.app.state, "document_extraction_service", None)
    if service is None:
        raise ServiceNotConfiguredError("document_extraction")
    return service
