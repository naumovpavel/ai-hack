"""Provider-aware speech payloads and browser-playable audio containers."""

from __future__ import annotations

import io
import wave
from email.message import Message

from interview_api.workflow.errors import WorkflowProviderError


def speech_request(*, model: str, voice: str, text: str, language: str) -> dict[str, object]:
    """Gemini's speech endpoint returns native PCM, not MP3."""
    is_gemini = model.startswith("google/gemini-")
    spoken_text = text.strip()
    if not spoken_text:
        raise WorkflowProviderError("There is no question text to synthesize.")
    if is_gemini:
        # Google's TTS prompting guide requires a clear synthesis instruction
        # and transcript boundary so style notes are not read aloud.
        spoken_language = "Russian" if language.lower().startswith("ru") else language
        spoken_text = (
            "Synthesize speech. Read only the transcript below, exactly as written, "
            "without adding an introduction or answering the question. "
            f"Speak in {spoken_language} as a warm, calm professional interviewer, "
            "at a natural conversational pace, with clear technical terms and short pauses.\n"
            f"TRANSCRIPT:\n{spoken_text}"
        )
    return {
        "model": model,
        "voice": voice,
        "input": spoken_text,
        "response_format": "pcm" if is_gemini else "mp3",
        "provider": {"data_collection": "deny"},
    }


def playable_speech(
    data: bytes, content_type: str, *, model: str
) -> tuple[bytes, str]:
    """Wrap raw 16-bit PCM in WAV without lossy transcoding or external tools."""
    if not data:
        raise WorkflowProviderError("TTS returned empty audio.")
    headers = Message()
    headers["Content-Type"] = content_type
    mime_type = headers.get_content_type().lower()
    if mime_type == "audio/pcm":
        default_rate = "24000" if model.startswith("google/gemini-") else None
        try:
            sample_rate = int(headers.get_param("rate") or default_rate or "0")
            channels = int(headers.get_param("channels") or "1")
        except (TypeError, ValueError) as error:
            raise WorkflowProviderError("TTS returned invalid PCM format metadata.") from error
        if not 8_000 <= sample_rate <= 96_000 or channels not in (1, 2):
            raise WorkflowProviderError("TTS returned unsupported PCM format metadata.")
        if len(data) % (2 * channels):
            raise WorkflowProviderError("TTS returned an incomplete PCM audio frame.")
        result = io.BytesIO()
        with wave.open(result, "wb") as audio:
            audio.setnchannels(channels)
            audio.setsampwidth(2)
            audio.setframerate(sample_rate)
            audio.writeframes(data)
        return result.getvalue(), "audio/wav"
    if mime_type not in {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav"}:
        raise WorkflowProviderError("TTS returned an unsupported audio format.")
    return data, "audio/mpeg" if mime_type in {"audio/mpeg", "audio/mp3"} else "audio/wav"
