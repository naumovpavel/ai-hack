import asyncio
from io import BytesIO
from types import SimpleNamespace

import pytest

from interview_api.domain.errors import ProviderTimeoutError
from interview_api.domain.models import AudioInput
from interview_api.providers.faster_whisper_transcription import (
    FasterWhisperTranscriptionProvider,
)


class FakeWhisperModel:
    def __init__(self) -> None:
        self.received_audio = None
        self.options = None

    def transcribe(self, audio: object, **options: object) -> tuple[object, object]:
        self.received_audio = audio
        self.options = options
        segments = iter(
            [SimpleNamespace(text=" Первая фраза "), SimpleNamespace(text="вторая.")]
        )
        return segments, object()


class SlowWhisperModel:
    def transcribe(self, audio: object, **options: object) -> tuple[object, object]:
        import time

        time.sleep(0.05)
        return iter([]), object()


@pytest.mark.asyncio
async def test_provider_normalizes_faster_whisper_output() -> None:
    model = FakeWhisperModel()
    stream = BytesIO(b"fake-audio")
    stream.seek(4)
    provider = FasterWhisperTranscriptionProvider(model, timeout_seconds=1, beam_size=3)

    result = await provider.transcribe(
        AudioInput(stream=stream, size_bytes=10, language="ru")
    )

    assert result.model_dump() == {
        "text": "Первая фраза вторая.",
        "is_final": True,
        "provider": "faster-whisper",
    }
    assert model.received_audio is stream
    assert model.options == {"language": "ru", "beam_size": 3, "vad_filter": True}


@pytest.mark.asyncio
async def test_provider_maps_timeout() -> None:
    provider = FasterWhisperTranscriptionProvider(
        SlowWhisperModel(), timeout_seconds=0.001
    )

    with pytest.raises(ProviderTimeoutError):
        await provider.transcribe(AudioInput(stream=BytesIO(b"audio"), size_bytes=5))

    await asyncio.sleep(0.06)
