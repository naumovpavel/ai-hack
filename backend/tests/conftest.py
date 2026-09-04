import shutil
from collections.abc import Callable, Sequence
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from interview_api.config import Settings
from interview_api.domain.models import (
    AudioInput,
    ProviderTranscript,
    QuestionDraft,
    QuestionGenerationInput,
    QuestionType,
)
from interview_api.main import create_app
from interview_api.providers.interfaces import QuestionGenerationProvider, TranscriptionProvider
from interview_api.services.question_generation import QuestionGenerationService
from interview_api.services.transcription import TranscriptionService


@pytest.fixture
def local_tmp_path() -> Path:
    workspace = Path.cwd().resolve()
    path = (workspace / f".pytest-case-{uuid4().hex}").resolve()
    path.mkdir()
    try:
        yield path
    finally:
        if path.parent == workspace:
            shutil.rmtree(path, ignore_errors=True)


class FakeQuestionProvider:
    async def generate(self, input: QuestionGenerationInput) -> Sequence[QuestionDraft]:
        core_source = input.core_contexts[0].file_id if input.core_contexts else None
        personalized_source = input.personalized_contexts[0].file_id
        drafts = [
            QuestionDraft(
                type=QuestionType.CORE,
                text=f"Core question {index + 1}",
                competency="Python",
                source_file_ids=[core_source],
            )
            for index in range(input.core_question_count)
            if core_source is not None
        ]
        drafts.extend(
            QuestionDraft(
                type=QuestionType.PERSONALIZED,
                text=f"Personalized question {index + 1}",
                competency="Experience",
                source_file_ids=[personalized_source],
            )
            for index in range(input.question_count - input.core_question_count)
        )
        return drafts


class FakeTranscriptionProvider:
    def __init__(self) -> None:
        self.received_audio: AudioInput | None = None

    async def transcribe(self, audio: AudioInput) -> ProviderTranscript:
        self.received_audio = audio
        assert audio.stream.read() == b"audio-content"
        return ProviderTranscript(text="Тестовая расшифровка", provider="fake")


@pytest.fixture
def app_factory() -> Callable[..., TestClient]:
    def factory(
        *,
        question_provider: QuestionGenerationProvider | None = None,
        transcription_provider: TranscriptionProvider | None = None,
    ) -> TestClient:
        settings = Settings(
            app_env="test",
            max_audio_bytes=1024,
            max_document_bytes=1024,
            max_document_characters=1000,
            _env_file=None,
        )
        question_service = QuestionGenerationService(
            provider=question_provider or FakeQuestionProvider(),
        )
        transcription_service = TranscriptionService(
            provider=transcription_provider or FakeTranscriptionProvider(),
            max_audio_bytes=settings.max_audio_bytes,
        )
        app = create_app(
            settings=settings,
            question_generation_service=question_service,
            transcription_service=transcription_service,
        )
        return TestClient(app)

    return factory
