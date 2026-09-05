from __future__ import annotations

import io
import json
import wave

import pytest

from interview_api.workflow.errors import WorkflowProviderError
from interview_api.workflow.openrouter import OpenRouterWorkflowAI
from interview_api.workflow.speech import playable_speech, speech_request

GEMINI = "google/gemini-3.1-flash-tts-preview"


def test_gemini_requests_pcm_and_keeps_question_verbatim_in_transcript() -> None:
    question = "Как вы обеспечивали идемпотентность при работе с Kafka?"
    payload = speech_request(model=GEMINI, voice="Sulafat", text=question, language="ru")
    assert payload["response_format"] == "pcm"
    assert payload["voice"] == "Sulafat"
    assert str(payload["input"]).endswith("TRANSCRIPT:\n" + question)
    assert "Speak in Russian" in str(payload["input"])


def test_other_speech_models_keep_mp3_and_unmodified_text() -> None:
    payload = speech_request(model="other/tts", voice="speaker", text="Вопрос?", language="ru")
    assert payload["response_format"] == "mp3"
    assert payload["input"] == "Вопрос?"


@pytest.mark.parametrize(
    ("content_type", "model", "rate", "channels"),
    [
        ("audio/pcm", GEMINI, 24000, 1),
        ("audio/pcm;rate=22050;channels=2", "other/tts", 22050, 2),
    ],
)
def test_raw_pcm_is_wrapped_in_playable_wav_without_altering_samples(
    content_type: str, model: str, rate: int, channels: int
) -> None:
    samples = b"\x00\x00\x10\x01" * 100
    result, mime_type = playable_speech(samples, content_type, model=model)
    assert mime_type == "audio/wav"
    with wave.open(io.BytesIO(result), "rb") as audio:
        assert audio.getframerate() == rate
        assert audio.getnchannels() == channels
        assert audio.getsampwidth() == 2
        assert audio.readframes(audio.getnframes()) == samples


@pytest.mark.parametrize(
    ("data", "content_type", "model"),
    [
        (b"", "audio/mpeg", GEMINI),
        (b"{}", "application/json", GEMINI),
        (b"\x00", "audio/pcm", GEMINI),
        (b"\x00\x00", "audio/pcm;rate=invalid", GEMINI),
        (b"\x00\x00", "audio/pcm;rate=1000000", GEMINI),
        (b"\x00\x00", "audio/pcm", "unknown/tts"),
    ],
)
def test_invalid_speech_is_rejected_before_caching(
    data: bytes, content_type: str, model: str
) -> None:
    with pytest.raises(WorkflowProviderError):
        playable_speech(data, content_type, model=model)


@pytest.mark.asyncio
async def test_gateway_sends_pcm_request_and_returns_browser_playable_wav() -> None:
    class Response:
        status = 200
        data = b"\x00\x00\x10\x01" * 100
        headers = {"Content-Type": "audio/pcm;rate=24000;channels=1"}

    class Pool:
        def request(self, method: str, url: str, *, body: bytes, headers: dict) -> Response:
            assert method == "POST"
            assert url.endswith("/audio/speech")
            assert json.loads(body)["response_format"] == "pcm"
            assert headers["Accept"] == "audio/*"
            return Response()

    gateway = OpenRouterWorkflowAI(
        api_key="test-key",
        chat_model="chat",
        stt_model="stt",
        tts_model=GEMINI,
        tts_voice="Sulafat",
        pool=Pool(),  # type: ignore[arg-type]
    )
    data, content_type = await gateway.synthesize("Расскажите о проекте.", language="ru")
    assert data[:4] == b"RIFF"
    assert data[8:12] == b"WAVE"
    assert content_type == "audio/wav"
