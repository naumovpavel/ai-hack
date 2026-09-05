import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import boto3
from botocore.config import Config as BotoConfig
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from faster_whisper import WhisperModel
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from interview_api.api.exception_handlers import register_exception_handlers
from interview_api.api.routes.health import router as health_router
from interview_api.api.routes.interviews import router as interviews_router
from interview_api.api.routes.questions import router as questions_router
from interview_api.api.routes.transcriptions import router as transcriptions_router
from interview_api.api.routes.workflow import router as workflow_router
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
from interview_api.workflow.openrouter import OpenRouterWorkflowAI
from interview_api.workflow.repository import SqlAlchemyWorkflowRepository
from interview_api.workflow.service import WorkflowService
from interview_api.workflow.storage import S3ObjectStorage
from interview_api.workflow.telegram_routes import router as telegram_router
from interview_api.workflow.telegram_runtime import TelegramRuntime
from interview_api.workflow.transcription import WorkflowTranscriptionProvider

logger = logging.getLogger(__name__)


def create_app(
    *,
    settings: Settings | None = None,
    question_generation_service: QuestionGenerationService | None = None,
    transcription_service: TranscriptionService | None = None,
    document_extraction_service: DocumentExtractionService | None = None,
    answer_evaluation_service: AnswerEvaluationService | None = None,
    workflow_service: WorkflowService | None = None,
    workflow_engine: AsyncEngine | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    managed_transcription_provider: FasterWhisperTranscriptionProvider | None = None
    managed_openrouter_client: OpenRouterClient | None = None
    managed_workflow_ai: OpenRouterWorkflowAI | None = None
    managed_workflow_engine: AsyncEngine | None = None
    managed_s3_clients: list[object] = []

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
        (question_generation_service is None or answer_evaluation_service is None)
        and api_key
        and proxy_url
    ):
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
    if (question_generation_service is None or answer_evaluation_service is None) and bool(
        api_key
    ) != bool(proxy_url):
        logger.warning(
            "OpenRouter services are disabled: OPENAI_API_KEY and "
            "OPENAI_PROXY_URL must both be configured"
        )

    if workflow_service is None and resolved_settings.app_env != "test":
        workflow_key = (
            resolved_settings.openrouter_api_key.get_secret_value()
            if resolved_settings.openrouter_api_key
            else ""
        )
        s3_access_key = (
            resolved_settings.s3_access_key.get_secret_value()
            if resolved_settings.s3_access_key
            else ""
        )
        s3_secret_key = (
            resolved_settings.s3_secret_key.get_secret_value()
            if resolved_settings.s3_secret_key
            else ""
        )
        if workflow_key and s3_access_key and s3_secret_key:
            managed_workflow_engine = create_async_engine(
                resolved_settings.database_url,
                echo=resolved_settings.database_echo,
                pool_pre_ping=True,
            )
            workflow_engine = managed_workflow_engine
            repository = SqlAlchemyWorkflowRepository.from_engine(managed_workflow_engine)
            boto_config = BotoConfig(
                signature_version="s3v4",
                s3={
                    "addressing_style": (
                        "path" if resolved_settings.s3_force_path_style else "auto"
                    )
                },
            )
            common_s3_options = {
                "service_name": "s3",
                "aws_access_key_id": s3_access_key,
                "aws_secret_access_key": s3_secret_key,
                "region_name": resolved_settings.s3_region,
                "config": boto_config,
            }
            internal_s3 = boto3.client(
                endpoint_url=resolved_settings.s3_endpoint_url,
                **common_s3_options,
            )
            public_s3 = boto3.client(
                endpoint_url=resolved_settings.s3_public_base_url,
                **common_s3_options,
            )
            managed_s3_clients.extend([internal_s3, public_s3])
            managed_workflow_ai = OpenRouterWorkflowAI(
                api_key=workflow_key,
                base_url=resolved_settings.openrouter_base_url,
                chat_model=resolved_settings.openrouter_chat_model,
                stt_model=resolved_settings.openrouter_stt_model,
                tts_model=resolved_settings.openrouter_tts_model,
                tts_voice=resolved_settings.openrouter_tts_voice,
                timeout_seconds=resolved_settings.openrouter_timeout_seconds,
                max_retries=resolved_settings.openrouter_max_retries,
                http_referer=resolved_settings.openrouter_http_referer,
                app_title=resolved_settings.openrouter_app_title,
            )
            workflow_service = WorkflowService(
                repository=repository,
                storage=S3ObjectStorage(
                    internal_s3,
                    bucket=resolved_settings.s3_bucket,
                    presign_client=public_s3,
                ),
                ai=managed_workflow_ai,
                invite_base_url=resolved_settings.workflow_invite_base_url,
                max_document_bytes=resolved_settings.max_document_bytes,
                max_document_characters=resolved_settings.max_document_characters,
                max_audio_bytes=resolved_settings.max_audio_bytes,
                cookie_secure=resolved_settings.workflow_cookie_secure,
                cookie_name=resolved_settings.session_cookie_name,
                session_ttl_hours=resolved_settings.session_ttl_hours,
                invite_ttl_days=resolved_settings.invite_ttl_days,
            )
        else:
            logger.warning(
                "Persistent workflow is disabled: configure OPENROUTER_API_KEY and S3 credentials"
            )

    if transcription_service is None and workflow_service is not None:
        transcription_service = TranscriptionService(
            provider=WorkflowTranscriptionProvider(workflow_service.ai),
            max_audio_bytes=resolved_settings.max_audio_bytes,
        )

    if workflow_service is not None:
        workflow_service.allow_demo_auth = (
            resolved_settings.demo_auth_enabled
            and resolved_settings.app_env != "production"
            and not resolved_settings.telegram_bot_token
        )

    telegram_runtime = (
        TelegramRuntime(workflow_service, resolved_settings)
        if workflow_service is not None and resolved_settings.telegram_bot_token
        else None
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        nonlocal managed_transcription_provider
        try:
            if workflow_service is not None:
                if workflow_engine is not None:
                    await workflow_service.repository.initialize(workflow_engine)
                await workflow_service.initialize()
                if telegram_runtime is not None:
                    await telegram_runtime.start()
            if (
                _app.state.transcription_service is None
                and workflow_service is None
                and resolved_settings.app_env != "test"
            ):
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
            if telegram_runtime is not None:
                await telegram_runtime.stop()
            if managed_transcription_provider is not None:
                managed_transcription_provider.close()
            if managed_openrouter_client is not None:
                managed_openrouter_client.close()
            if managed_workflow_ai is not None:
                managed_workflow_ai.close()
            for client in managed_s3_clients:
                close = getattr(client, "close", None)
                if close is not None:
                    close()
            if managed_workflow_engine is not None:
                await managed_workflow_engine.dispose()

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
    app.state.workflow_service = workflow_service

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(interviews_router)
    app.include_router(questions_router)
    app.include_router(transcriptions_router)
    app.include_router(workflow_router)
    app.include_router(telegram_router)
    return app


app = create_app()
