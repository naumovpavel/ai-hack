from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile

from interview_api.api.dependencies import get_transcription_service
from interview_api.api.upload_utils import measure_upload
from interview_api.domain.models import (
    AudioInput,
    CorrelationId,
    ErrorResponse,
    LanguageCode,
    TranscriptionCommand,
    TranscriptionResult,
)
from interview_api.services.transcription import TranscriptionService

router = APIRouter(prefix="/api/v1/transcriptions", tags=["transcriptions"])


@router.post(
    "",
    response_model=TranscriptionResult,
    responses={
        413: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)
async def create_transcription(
    audio: Annotated[UploadFile, File()],
    service: Annotated[TranscriptionService, Depends(get_transcription_service)],
    language: Annotated[LanguageCode | None, Form()] = None,
    interview_id: Annotated[CorrelationId | None, Form()] = None,
    question_id: Annotated[CorrelationId | None, Form()] = None,
) -> TranscriptionResult:
    try:
        size_bytes = await measure_upload(audio, max_bytes=service.max_audio_bytes)
        command = TranscriptionCommand(
            audio=AudioInput(
                stream=audio.file,
                size_bytes=size_bytes,
                filename=audio.filename,
                content_type=audio.content_type,
                language=language,
            ),
            interview_id=interview_id,
            question_id=question_id,
        )
        return await service.transcribe(command)
    finally:
        await audio.close()
