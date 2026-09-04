from collections.abc import Sequence
from uuid import uuid4

from interview_api.domain.errors import InsufficientContextError, ProviderResponseError
from interview_api.domain.models import (
    GenerateQuestionsParameters,
    GenerateQuestionsResponse,
    InterviewQuestion,
    LoadedContext,
    QuestionDraft,
    QuestionGenerationInput,
    QuestionType,
)
from interview_api.providers.interfaces import QuestionGenerationProvider

CORE_CONTEXT_TYPES = frozenset({"vacancy", "requirements"})


class QuestionGenerationService:
    def __init__(
        self,
        provider: QuestionGenerationProvider,
    ) -> None:
        self._provider = provider

    async def generate_from_contexts(
        self,
        loaded_contexts: Sequence[LoadedContext],
        parameters: GenerateQuestionsParameters,
    ) -> GenerateQuestionsResponse:
        core_contexts = [
            context for context in loaded_contexts if context.type in CORE_CONTEXT_TYPES
        ]
        if parameters.core_question_count and not core_contexts:
            raise InsufficientContextError()

        provider_input = QuestionGenerationInput(
            core_contexts=core_contexts,
            personalized_contexts=list(loaded_contexts),
            question_count=parameters.question_count,
            core_question_count=parameters.core_question_count,
            language=parameters.language,
        )
        drafts = list(await self._provider.generate(provider_input))
        self._validate_provider_result(drafts, provider_input)

        return GenerateQuestionsResponse(
            questions=[InterviewQuestion(id=uuid4(), **draft.model_dump()) for draft in drafts]
        )

    @staticmethod
    def _validate_provider_result(
        drafts: Sequence[QuestionDraft],
        provider_input: QuestionGenerationInput,
    ) -> None:
        if len(drafts) != provider_input.question_count:
            raise ProviderResponseError()

        actual_core_count = sum(draft.type is QuestionType.CORE for draft in drafts)
        if actual_core_count != provider_input.core_question_count:
            raise ProviderResponseError()

        all_source_ids = {context.file_id for context in provider_input.personalized_contexts}
        core_source_ids = {context.file_id for context in provider_input.core_contexts}

        for draft in drafts:
            source_ids = set(draft.source_file_ids)
            if not source_ids.issubset(all_source_ids):
                raise ProviderResponseError()
            if draft.type is QuestionType.CORE and not source_ids.issubset(core_source_ids):
                raise ProviderResponseError()
