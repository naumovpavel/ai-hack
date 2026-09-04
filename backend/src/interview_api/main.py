import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from faster_whisper import WhisperModel

from interview_api.api.exception_handlers import register_exception_handlers
from interview_api.api.routes.health import router as health_router
from interview_api.api.routes.interviews import router as interviews_router
from interview_api.api.routes.questions import router as questions_router
from interview_api.api.routes.transcriptions import router as transcriptions_router
from interview_api.config import Settings, get_settings
from interview_api.providers.document_text import PdfDocxTextExtractor
from interview_api.providers.faster_whisper_transcription import (
    FasterWhisperTranscriptionProvider,
)
from interview_api.providers.openrouter_interview import (
    OpenRouterClient,
    OpenRouterInterviewPipelineProvider,
)
from interview_api.providers.openrouter_questions import OpenRouterQuestionGenerationProvider
from interview_api.services.answer_evaluation import AnswerEvaluationService
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
    answer_evaluation_service: AnswerEvaluationService | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    managed_transcription_provider: FasterWhisperTranscriptionProvider | None = None
    managed_openrouter_client: OpenRouterClient | None = None

    if document_extraction_service is None:
        document_extraction_service = DocumentExtractionService(
            PdfDocxTextExtractor(),
            max_document_bytes=resolved_settings.max_document_bytes,
            max_document_characters=resolved_settings.max_document_characters,
        )

    api_key = (
        resolved_settings.openai_api_key.get_secret_value()
        if resolved_settings.openai_api_key
        else ""
    )
    proxy_url = (
        resolved_settings.openai_proxy_url.get_secret_value()
        if resolved_settings.openai_proxy_url
        else ""
    )
    if (
        question_generation_service is None or answer_evaluation_service is None
    ) and api_key and proxy_url:
        managed_openrouter_client = OpenRouterClient(
            api_key=api_key,
            proxy_url=proxy_url,
            model=resolved_settings.openrouter_model,
            fallback_model=resolved_settings.openrouter_fallback_model,
            timeout_seconds=resolved_settings.openrouter_timeout_seconds,
            max_retries=resolved_settings.openrouter_max_retries,
        )

    if question_generation_service is None and managed_openrouter_client is not None:
        question_generation_service = QuestionGenerationService(
            provider=OpenRouterQuestionGenerationProvider(
                managed_openrouter_client,
                model=resolved_settings.question_generation_model,
                prompt_path=resolved_settings.question_prompt_path,
            )
        )

    if answer_evaluation_service is None and managed_openrouter_client is not None:
        answer_evaluation_service = AnswerEvaluationService(
            OpenRouterInterviewPipelineProvider(
                managed_openrouter_client,
                judge_workers=resolved_settings.interview_judge_workers,
            )
        )
    if (
        question_generation_service is None or answer_evaluation_service is None
    ) and bool(api_key) != bool(proxy_url):
        logger.warning(
            "OpenRouter services are disabled: OPENAI_API_KEY and "
            "OPENAI_PROXY_URL must both be configured"
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
            if managed_transcription_provider is not None:
                managed_transcription_provider.close()
            if managed_openrouter_client is not None:
                managed_openrouter_client.close()

    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.question_generation_service = question_generation_service
    app.state.document_extraction_service = document_extraction_service
    app.state.transcription_service = transcription_service
    app.state.answer_evaluation_service = answer_evaluation_service

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(interviews_router)
    app.include_router(questions_router)
    app.include_router(transcriptions_router)
    return app


app = create_app()
