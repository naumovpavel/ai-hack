from __future__ import annotations

import asyncio

from interview_api.domain.errors import ProviderResponseError
from interview_api.domain.models import AudioInput, ProviderTranscript
from interview_api.workflow.ai import WorkflowAIGateway
from interview_api.workflow.errors import WorkflowProviderError


class WorkflowTranscriptionProvider:
    """Expose workflow OpenRouter STT through the legacy transcription API."""

    def __init__(self, gateway: WorkflowAIGateway) -> None:
        self._gateway = gateway

    async def transcribe(self, audio: AudioInput) -> ProviderTranscript:
        def read_audio() -> bytes:
            audio.stream.seek(0)
            value = audio.stream.read()
            if not isinstance(value, bytes):
                raise TypeError("Audio stream must return bytes")
            return value

        data = await asyncio.to_thread(read_audio)
        try:
            text = await self._gateway.transcribe(
                data,
                content_type=audio.content_type or "audio/webm",
                language=audio.language or "ru",
            )
        except WorkflowProviderError as exc:
            raise ProviderResponseError(details=exc.details) from exc
        return ProviderTranscript(
            text=text,
            is_final=True,
            provider="openrouter-workflow",
        )
