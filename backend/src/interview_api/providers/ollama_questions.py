import json
from pathlib import Path

from httpx import HTTPError, TimeoutException
from ollama import AsyncClient, ResponseError
from pydantic import ValidationError

from interview_api.domain.errors import (
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from interview_api.domain.models import (
    LoadedContext,
    QuestionDraft,
    QuestionGenerationInput,
    QuestionType,
)

OLLAMA_QUESTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["core", "personalized"]},
                    "text": {"type": "string"},
                    "competency": {"type": "string"},
                    "source_file_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["type", "text", "competency", "source_file_ids"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}
_GENERATION_BATCH_SIZE = 3
_EXTRA_BATCH_ATTEMPTS = 6


class OllamaQuestionGenerationProvider:
    def __init__(
        self,
        client: AsyncClient,
        *,
        model: str,
        prompt_path: Path,
        context_length: int,
    ) -> None:
        self._client = client
        self._model = model
        self._instructions = self._load_prompt(prompt_path)
        self._context_length = context_length

    async def generate(self, input: QuestionGenerationInput) -> list[QuestionDraft]:
        seen_texts: set[str] = set()
        core_questions = await self._generate_group(
            contexts=input.core_contexts,
            target_count=input.core_question_count,
            question_type=QuestionType.CORE,
            language=input.language,
            seen_texts=seen_texts,
        )
        personalized_questions = await self._generate_group(
            contexts=input.personalized_contexts,
            target_count=input.question_count - input.core_question_count,
            question_type=QuestionType.PERSONALIZED,
            language=input.language,
            seen_texts=seen_texts,
        )
        return [*core_questions, *personalized_questions]

    async def _generate_group(
        self,
        *,
        contexts: list[LoadedContext],
        target_count: int,
        question_type: QuestionType,
        language: str,
        seen_texts: set[str],
    ) -> list[QuestionDraft]:
        if target_count == 0:
            return []

        questions: list[QuestionDraft] = []
        max_attempts = (
            (target_count + _GENERATION_BATCH_SIZE - 1) // _GENERATION_BATCH_SIZE
            + _EXTRA_BATCH_ATTEMPTS
        )
        feedback: str | None = None

        for _attempt in range(max_attempts):
            remaining = target_count - len(questions)
            if remaining == 0:
                return questions

            batch_size = min(remaining, _GENERATION_BATCH_SIZE)
            request_input = QuestionGenerationInput(
                core_contexts=contexts if question_type is QuestionType.CORE else [],
                personalized_contexts=contexts,
                question_count=batch_size,
                core_question_count=(
                    batch_size if question_type is QuestionType.CORE else 0
                ),
                language=language,
            )
            try:
                candidates = await self._request_candidates(
                    request_input,
                    feedback=feedback,
                    existing_question_texts=list(seen_texts),
                    attempt=_attempt,
                )
            except (ValueError, TypeError):
                feedback = "The response was not valid JSON matching the schema."
                continue

            added = self._collect_group_candidates(
                candidates=candidates,
                contexts=contexts,
                question_type=question_type,
                target_count=target_count,
                questions=questions,
                seen_texts=seen_texts,
            )
            feedback = (
                f"The previous response added {added} usable questions. "
                f"Return {min(target_count - len(questions), _GENERATION_BATCH_SIZE)} "
                f"new {question_type.value} questions."
            )

        if len(questions) == target_count:
            return questions
        raise ProviderResponseError(
            details={
                "reason": (
                    f"Expected {target_count} {question_type.value} questions, got "
                    f"{len(questions)} after {max_attempts} batched attempts."
                )
            }
        )

    async def _request_candidates(
        self,
        input: QuestionGenerationInput,
        *,
        feedback: str | None,
        existing_question_texts: list[str],
        attempt: int,
    ) -> list[QuestionDraft]:
        try:
            response = await self._client.chat(
                model=self._model,
                messages=[
                    {"role": "system", "content": self._instructions},
                    {
                        "role": "user",
                        "content": self._build_input(
                            input,
                            feedback,
                            existing_question_texts,
                            attempt,
                        ),
                    },
                ],
                format=OLLAMA_QUESTIONS_SCHEMA,
                options={
                    "temperature": min(attempt * 0.2, 0.8),
                    "num_ctx": self._context_length,
                },
                think=False,
            )
        except TimeoutException as exc:
            raise ProviderTimeoutError() from exc
        except (HTTPError, ResponseError) as exc:
            raise ProviderUnavailableError() from exc

        return self._parse_candidates(response.message.content)

    @staticmethod
    def _load_prompt(prompt_path: Path) -> str:
        try:
            prompt = prompt_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise RuntimeError(f"Cannot load question prompt: {prompt_path}") from exc
        if not prompt:
            raise RuntimeError(f"Question prompt is empty: {prompt_path}")
        return prompt

    @staticmethod
    def _build_input(
        input: QuestionGenerationInput,
        feedback: str | None,
        existing_question_texts: list[str],
        attempt: int,
    ) -> str:
        payload = {
            "language": input.language,
            "question_count": input.question_count,
            "core_question_count": input.core_question_count,
            "personalized_question_count": (
                input.question_count - input.core_question_count
            ),
            "core_contexts": [context.model_dump() for context in input.core_contexts],
            "personalized_contexts": [
                context.model_dump() for context in input.personalized_contexts
            ],
            "generation_attempt": attempt + 1,
        }
        if feedback is not None:
            payload["previous_response_error"] = feedback
            payload["retry_instruction"] = "Return only the newly requested questions."
        if existing_question_texts:
            payload["existing_question_texts"] = existing_question_texts
            payload["deduplication_instruction"] = (
                "Do not repeat or closely paraphrase any existing question."
            )
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _parse_candidates(content: str) -> list[QuestionDraft]:
        payload = json.loads(content)
        if not isinstance(payload, dict) or not isinstance(payload.get("questions"), list):
            raise ValueError("Missing questions array")

        candidates: list[QuestionDraft] = []
        for item in payload["questions"]:
            try:
                candidates.append(QuestionDraft.model_validate(item))
            except ValidationError:
                continue
        return candidates

    @staticmethod
    def _collect_group_candidates(
        *,
        candidates: list[QuestionDraft],
        contexts: list[LoadedContext],
        question_type: QuestionType,
        target_count: int,
        questions: list[QuestionDraft],
        seen_texts: set[str],
    ) -> int:
        allowed_sources = {context.file_id for context in contexts}
        preferred_source = next(
            (
                context.file_id
                for context in contexts
                if question_type is QuestionType.PERSONALIZED and context.type == "cv"
            ),
            contexts[0].file_id,
        )
        added = 0

        for candidate in candidates:
            if len(questions) >= target_count:
                break
            normalized_text = " ".join(candidate.text.casefold().split())
            if normalized_text in seen_texts:
                continue

            valid_sources = [
                source
                for source in dict.fromkeys(candidate.source_file_ids)
                if source in allowed_sources
            ]
            normalized = candidate.model_copy(
                update={
                    "type": question_type,
                    "source_file_ids": valid_sources or [preferred_source],
                }
            )
            questions.append(normalized)
            seen_texts.add(normalized_text)
            added += 1
        return added
