from collections.abc import Callable

from fastapi.testclient import TestClient

from interview_api.domain.errors import ProviderTimeoutError, ProviderUnavailableError
from interview_api.domain.models import AudioInput, ProviderTranscript


class FailingTranscriptionProvider:
    async def transcribe(self, audio: AudioInput) -> ProviderTranscript:
        raise ProviderUnavailableError()


class TimeoutTranscriptionProvider:
    async def transcribe(self, audio: AudioInput) -> ProviderTranscript:
        raise ProviderTimeoutError()


class RecordingTranscriptionProvider:
    def __init__(self) -> None:
        self.audio: AudioInput | None = None

    async def transcribe(self, audio: AudioInput) -> ProviderTranscript:
        self.audio = audio
        return ProviderTranscript(text="ok", provider="recording")


def test_transcription_success(app_factory: Callable[..., TestClient]) -> None:
    client = app_factory()

    response = client.post(
        "/api/v1/transcriptions",
        files={"audio": ("answer.webm", b"audio-content", "audio/webm")},
        data={"language": "ru", "interview_id": "interview-1", "question_id": "question-1"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "text": "Тестовая расшифровка",
        "is_final": True,
        "question_id": "question-1",
        "meta": {"provider": "fake"},
    }


def test_transcription_rejects_empty_audio(app_factory: Callable[..., TestClient]) -> None:
    provider = RecordingTranscriptionProvider()
    client = app_factory(transcription_provider=provider)

    response = client.post(
        "/api/v1/transcriptions",
        files={"audio": ("empty.webm", b"", "audio/webm")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_audio"
    assert provider.audio is None


def test_transcription_rejects_oversized_audio(
    app_factory: Callable[..., TestClient],
) -> None:
    provider = RecordingTranscriptionProvider()
    client = app_factory(transcription_provider=provider)

    response = client.post(
        "/api/v1/transcriptions",
        files={"audio": ("large.wav", b"x" * 1025, "audio/wav")},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert provider.audio is None


def test_transcription_maps_provider_error(app_factory: Callable[..., TestClient]) -> None:
    client = app_factory(transcription_provider=FailingTranscriptionProvider())

    response = client.post(
        "/api/v1/transcriptions",
        files={"audio": ("answer.webm", b"audio-content", "audio/webm")},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "provider_unavailable"


def test_transcription_maps_provider_timeout(app_factory: Callable[..., TestClient]) -> None:
    client = app_factory(transcription_provider=TimeoutTranscriptionProvider())

    response = client.post(
        "/api/v1/transcriptions",
        files={"audio": ("answer.webm", b"audio-content", "audio/webm")},
    )

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "provider_timeout"


def test_transcription_passes_normalized_audio_metadata(
    app_factory: Callable[..., TestClient],
) -> None:
    provider = RecordingTranscriptionProvider()
    client = app_factory(transcription_provider=provider)

    response = client.post(
        "/api/v1/transcriptions",
        files={"audio": ("answer.webm", b"abc", "audio/webm")},
        data={"language": "ru", "interview_id": "interview-1"},
    )

    assert response.status_code == 200
    assert response.json()["question_id"] is None
    assert provider.audio is not None
    assert provider.audio.size_bytes == 3
    assert provider.audio.filename == "answer.webm"
    assert provider.audio.content_type == "audio/webm"
    assert provider.audio.language == "ru"
