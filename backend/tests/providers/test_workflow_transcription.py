from io import BytesIO

import pytest

from interview_api.domain.errors import ProviderResponseError
from interview_api.domain.models import AudioInput
from interview_api.workflow.ai import DeterministicWorkflowAI
from interview_api.workflow.errors import WorkflowProviderError
from interview_api.workflow.transcription import WorkflowTranscriptionProvider


class FailingWorkflowAI(DeterministicWorkflowAI):
    async def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str,
        language: str,
    ) -> str:
        del audio, content_type, language
        raise WorkflowProviderError("OpenRouter failed", details={"status": 503})


@pytest.mark.asyncio
async def test_workflow_transcription_maps_gateway_errors() -> None:
    provider = WorkflowTranscriptionProvider(FailingWorkflowAI())
    audio = AudioInput(
        stream=BytesIO(b"audio"),
        size_bytes=5,
        filename="answer.webm",
        content_type="audio/webm",
        language="ru",
    )

    with pytest.raises(ProviderResponseError) as captured:
        await provider.transcribe(audio)

    assert captured.value.details == {"status": 503}
