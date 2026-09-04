from collections.abc import Sequence
from typing import Protocol

from interview_api.domain.models import (
    AudioInput,
    ContextReference,
    DocumentInput,
    EvaluateAnswerResponse,
    LoadedContext,
    ProviderTranscript,
    QuestionDraft,
    QuestionGenerationInput,
)


class ContextLoader(Protocol):
    async def load(self, reference: ContextReference) -> LoadedContext: ...


class QuestionGenerationProvider(Protocol):
    async def generate(self, input: QuestionGenerationInput) -> Sequence[QuestionDraft]: ...


class DocumentTextExtractor(Protocol):
    async def extract(self, document: DocumentInput) -> str: ...


class TranscriptionProvider(Protocol):
    async def transcribe(self, audio: AudioInput) -> ProviderTranscript: ...


class AnswerEvaluationProvider(Protocol):
    async def evaluate(self, question: str, answer: str) -> EvaluateAnswerResponse: ...
