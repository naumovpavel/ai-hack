import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from av.error import FFmpegError

from interview_api.domain.errors import (
    InvalidAudioError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from interview_api.domain.models import AudioInput, ProviderTranscript


class FasterWhisperTranscriptionProvider:
    """Async adapter around one reusable, synchronous faster-whisper model."""

    def __init__(
        self,
        model: Any,
        *,
        timeout_seconds: float,
        beam_size: int = 5,
    ) -> None:
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._beam_size = beam_size
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="faster-whisper",
        )

    async def transcribe(self, audio: AudioInput) -> ProviderTranscript:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(self._executor, self._transcribe_sync, audio)
        except TimeoutError as exc:
            raise ProviderTimeoutError() from exc
        except (FFmpegError, TypeError, ValueError) as exc:
            raise InvalidAudioError() from exc
        except (OSError, RuntimeError) as exc:
            raise ProviderUnavailableError() from exc

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _transcribe_sync(self, audio: AudioInput) -> ProviderTranscript:
        audio.stream.seek(0)
        segments, _info = self._model.transcribe(
            audio.stream,
            language=audio.language,
            beam_size=self._beam_size,
            vad_filter=True,
        )
        text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        return ProviderTranscript(text=text, is_final=True, provider="faster-whisper")
