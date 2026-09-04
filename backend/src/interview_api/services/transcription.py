from interview_api.domain.errors import InvalidAudioError, PayloadTooLargeError
from interview_api.domain.models import (
    ProviderMeta,
    TranscriptionCommand,
    TranscriptionResult,
)
from interview_api.providers.interfaces import TranscriptionProvider


class TranscriptionService:
    def __init__(self, provider: TranscriptionProvider, *, max_audio_bytes: int) -> None:
        self._provider = provider
        self.max_audio_bytes = max_audio_bytes

    async def transcribe(self, command: TranscriptionCommand) -> TranscriptionResult:
        if command.audio.size_bytes == 0:
            raise InvalidAudioError()
        if command.audio.size_bytes > self.max_audio_bytes:
            raise PayloadTooLargeError()

        transcript = await self._provider.transcribe(command.audio)
        return TranscriptionResult(
            text=transcript.text,
            is_final=transcript.is_final,
            question_id=command.question_id,
            meta=ProviderMeta(provider=transcript.provider),
        )
