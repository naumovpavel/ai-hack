from collections.abc import Sequence

from interview_api.domain.errors import ProviderResponseError
from interview_api.domain.models import (
    AnswerAnnotation,
    EvaluateAnswerResponse,
    MissingAspect,
)
from interview_api.providers.interfaces import AnswerEvaluationProvider


class AnswerEvaluationService:
    def __init__(self, provider: AnswerEvaluationProvider) -> None:
        self._provider = provider

    async def evaluate(self, question: str, answer: str) -> EvaluateAnswerResponse:
        result = await self._provider.evaluate(question, answer)
        self._validate_spans(answer, result.spans)
        self._validate_spans(question, result.missing_aspects)
        return result

    @staticmethod
    def _validate_spans(
        source: str,
        spans: Sequence[AnswerAnnotation | MissingAspect],
    ) -> None:
        previous_end = -1
        for span in sorted(spans, key=lambda item: (item.start, item.end)):
            valid = (
                span.start >= previous_end
                and span.end <= len(source)
                and source[span.start : span.end] == span.text
            )
            if not valid:
                raise ProviderResponseError(
                    details={"reason": "Provider returned invalid or overlapping spans."}
                )
            previous_end = span.end
