import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from faster_whisper import WhisperModel
from ollama import AsyncClient

from interview_api.api.exception_handlers import register_exception_handlers
from interview_api.api.routes.health import router as health_router
from interview_api.api.routes.questions import router as questions_router
from interview_api.api.routes.transcriptions import router as transcriptions_router
from interview_api.config import Settings, get_settings
from interview_api.providers.document_text import PdfDocxTextExtractor
from interview_api.providers.faster_whisper_transcription import (
    FasterWhisperTranscriptionProvider,
)
from interview_api.providers.ollama_questions import OllamaQuestionGenerationProvider
from interview_api.services.document_extraction import DocumentExtractionService
from interview_api.services.question_generation import QuestionGenerationService
from interview_api.services.transcription import TranscriptionService

logger = logging.getLogger(__name__)


def create_app(
    *,
    settings: Settings | None = None,
    question_generation_service: QuestionGenerationService | None = None,
    transcription_service: TranscriptionService | None = None,
    document_extraction_service: DocumentExtractionService | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    managed_ollama_client: AsyncClient | None = None
    managed_transcription_provider: FasterWhisperTranscriptionProvider | None = None

    if question_generation_service is None:
        managed_ollama_client = AsyncClient(
            host=resolved_settings.ollama_host,
            timeout=resolved_settings.ollama_timeout_seconds,
        )
        question_generation_service = QuestionGenerationService(
            provider=OllamaQuestionGenerationProvider(
                managed_ollama_client,
                model=resolved_settings.ollama_question_model,
                prompt_path=resolved_settings.question_prompt_path,
                context_length=resolved_settings.ollama_context_length,
            ),
        )

    if document_extraction_service is None:
        document_extraction_service = DocumentExtractionService(
            PdfDocxTextExtractor(),
            max_document_bytes=resolved_settings.max_document_bytes,
            max_document_characters=resolved_settings.max_document_characters,
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        nonlocal managed_transcription_provider
        try:
            if _app.state.transcription_service is None and resolved_settings.app_env != "test":
                try:
                    whisper_model = await asyncio.to_thread(
                        WhisperModel,
                        resolved_settings.whisper_model_size,
                        device=resolved_settings.whisper_device,
                        compute_type=resolved_settings.whisper_compute_type,
                    )
                    managed_transcription_provider = FasterWhisperTranscriptionProvider(
                        whisper_model,
                        timeout_seconds=resolved_settings.whisper_timeout_seconds,
                        beam_size=resolved_settings.whisper_beam_size,
                    )
                    _app.state.transcription_service = TranscriptionService(
                        provider=managed_transcription_provider,
                        max_audio_bytes=resolved_settings.max_audio_bytes,
                    )
                except Exception:
                    logger.exception("Failed to initialize the transcription provider")
            yield
        finally:
            if managed_ollama_client is not None:
                await managed_ollama_client.close()
            if managed_transcription_provider is not None:
                managed_transcription_provider.close()

    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.question_generation_service = question_generation_service
    app.state.document_extraction_service = document_extraction_service
    app.state.transcription_service = transcription_service

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(questions_router)
    app.include_router(transcriptions_router)
    return app


app = create_app()
