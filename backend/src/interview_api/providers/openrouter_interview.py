from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import unquote, urlsplit, urlunsplit

import certifi
import urllib3
from pydantic import ValidationError

from interview_api.domain.errors import (
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from interview_api.domain.models import (
    AnnotationLabel,
    AnswerAnnotation,
    ClaimJudgement,
    EvaluateAnswerResponse,
    EvaluationMeta,
    ExtractedClaim,
    MissingAspect,
)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
PROMPT_VERSION = "interview-technical-errors-v6"
DEFAULT_MODEL = "openai/gpt-5.6-luna"
DEFAULT_FALLBACK_MODEL = "deepseek/deepseek-v4-flash-0731"
CLAIM_CONFIDENCE_THRESHOLD = 0.70
COMPLETENESS_CONFIDENCE_THRESHOLD = 0.85
EXPLICIT_ASPECT_PREFIXES = (
    "how ",
    "which ",
    "what ",
    "when ",
    "why ",
    "name ",
    "\u043a\u0430\u043a ",
    "\u043a\u0430\u043a\u0438\u0435 ",
    "\u043a\u0430\u043a\u043e\u0439 ",
    "\u043d\u0430\u0437\u043e\u0432\u0438\u0442\u0435 ",
    "\u0447\u0442\u043e ",
    "\u043a\u043e\u0433\u0434\u0430 ",
    "\u043f\u043e\u0447\u0435\u043c\u0443 ",
)

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Exact contiguous quote from the answer",
                    },
                    "start": {"type": "integer", "minimum": 0},
                    "end": {"type": "integer", "minimum": 0},
                },
                "required": ["text", "start", "end"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["claims"],
    "additionalProperties": False,
}

JUDGEMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["correct", "incorrect"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string"},
    },
    "required": ["verdict", "confidence", "rationale"],
    "additionalProperties": False,
}

COMPLETENESS_SCHEMA = {
    "type": "object",
    "properties": {
        "missing_aspects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Exact contiguous quote from the question",
                    },
                    "start": {"type": "integer", "minimum": 0},
                    "end": {"type": "integer", "minimum": 0},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "rationale": {"type": "string"},
                },
                "required": ["text", "start", "end", "confidence", "rationale"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["missing_aspects"],
    "additionalProperties": False,
}

EXTRACTION_PROMPT = """You evaluate only the technical correctness of an interview answer.
Extract atomic claims about technology behavior, system properties, technical causality, and
technical recommendations.

Every `text` must be an exact contiguous quote from the answer and stand on its own. Keep the
subject, negation, condition, cause, and qualification needed to understand it without adjacent
sentences. Split a sentence only when both resulting quotes are independently understandable and
verifiable. Claims must not overlap. Offsets use Python Unicode [start, end).

Do not extract the mere fact of personal experience, employer names, scale, achieved metrics, or
subjective assessments. If a personal statement contains a technical assertion, extract only the
technical part. Do not judge truth at this stage and do not include speech filler.
"""

JUDGEMENT_PROMPT = """Judge exactly one claim from a technical interview answer. Evaluate only
whether its technical content is true, using stable generally accepted knowledge and constraints
in the question. Do not assess answer completeness, style, usefulness, subjectivity, employer,
personal experience, or whether claimed personal metrics are truthful.

Return `incorrect` only for a technical error, false causal link, invalid guarantee, or dangerous
recommendation. A partial but true claim is `correct`; missing detail or omitted best practices do
not make it incorrect. Do not expand the claim with words such as always, completely, or only when
they are absent. If multiple technical interpretations are plausible, use the most natural one and
lower confidence. Confidence is certainty in this technical verdict only.
"""

COMPLETENESS_PROMPT = """Conservatively identify concrete, independently requested technical
parts of the question that the answer does not address at all. Maximize precision: if the answer
touches a part with any substantive claim—even an incorrect or brief one—do not return it.

Do not return the general goal or scenario of the question. Return only an explicit requested part,
such as 'which libraries', 'name the volumes', or 'how was the Docker image built'. Each `text`
must be a minimal exact contiguous quote from the question. When uncertain, return no aspect.
Confidence means certainty that the aspect is entirely absent from the answer.
"""


@dataclass(slots=True)
class StructuredResult:
    value: dict[str, Any]
    model: str
    provider: str


class StructuredClient(Protocol):
    def complete_json(
        self,
        *,
        messages: list[dict[str, str]],
        schema_name: str,
        schema: dict[str, Any],
        purpose: str,
    ) -> StructuredResult: ...


class OpenRouterClient:
    """Synchronous structured-output client with a mandatory HTTPS proxy."""

    def __init__(
        self,
        *,
        api_key: str,
        proxy_url: str,
        model: str = DEFAULT_MODEL,
        fallback_model: str | None = DEFAULT_FALLBACK_MODEL,
        timeout_seconds: float = 90,
        max_retries: int = 1,
    ) -> None:
        if not api_key or not proxy_url:
            raise ValueError("OpenRouter API key and proxy URL are required")
        if not proxy_url.startswith(("http://", "https://")):
            raise ValueError("OpenRouter proxy must use HTTP or HTTPS")
        self.api_key = api_key
        self.proxy_url = proxy_url
        self.model = model
        self.fallback_model = fallback_model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._pool: urllib3.ProxyManager | None = None

    def close(self) -> None:
        if self._pool is not None:
            self._pool.clear()

    def complete_json(
        self,
        *,
        messages: list[dict[str, str]],
        schema_name: str,
        schema: dict[str, Any],
        purpose: str,
    ) -> StructuredResult:
        models = tuple(dict.fromkeys(filter(None, (self.model, self.fallback_model))))
        errors: list[Exception] = []
        for model in models:
            try:
                return self._complete_model(
                    model=model,
                    messages=messages,
                    schema_name=schema_name,
                    schema=schema,
                    purpose=purpose,
                )
            except (ProviderResponseError, ProviderTimeoutError, ProviderUnavailableError) as exc:
                errors.append(exc)
        raise errors[-1]

    def _complete_model(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        schema_name: str,
        schema: dict[str, Any],
        purpose: str,
    ) -> StructuredResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": {
                "extraction": 1800,
                "judgement": 700,
                "completeness": 700,
            }.get(purpose, 1200),
            "reasoning": {"enabled": False, "exclude": True},
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
            "provider": {"require_parameters": True, "data_collection": "deny"},
        }
        payload.update({"seed": 0} if model.startswith("openai/gpt-5") else {"temperature": 0})
        body = json.dumps(payload, ensure_ascii=False).encode()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://localhost/ai-interview",
            "X-Title": "AI Interview Backend",
        }
        response = self._request_with_retries(body, headers)
        if not 200 <= response.status < 300:
            error_type = {
                408: ProviderTimeoutError,
                504: ProviderTimeoutError,
            }.get(response.status, ProviderResponseError)
            raise error_type(details={"status": response.status})
        return self._parse_response(response.data)

    def _request_with_retries(
        self, body: bytes, headers: dict[str, str]
    ) -> urllib3.BaseHTTPResponse:
        retryable = {408, 409, 429, 500, 502, 503, 504}
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._get_pool().request(
                    "POST", OPENROUTER_URL, body=body, headers=headers
                )
            except urllib3.exceptions.TimeoutError as exc:
                last_error = ProviderTimeoutError()
                last_error.__cause__ = exc
            except urllib3.exceptions.HTTPError as exc:
                last_error = ProviderUnavailableError()
                last_error.__cause__ = exc
            else:
                if response.status not in retryable or attempt == self.max_retries:
                    return response
            if attempt < self.max_retries:
                time.sleep(2**attempt)
        raise last_error or ProviderUnavailableError()

    def _get_pool(self) -> urllib3.ProxyManager:
        if self._pool is not None:
            return self._pool
        parsed = urlsplit(self.proxy_url)
        proxy_headers = None
        proxy_url = self.proxy_url
        if parsed.username is not None:
            credentials = f"{unquote(parsed.username)}:{unquote(parsed.password or '')}"
            proxy_headers = urllib3.make_headers(proxy_basic_auth=credentials)
            host = parsed.hostname or ""
            host = f"[{host}]" if ":" in host and not host.startswith("[") else host
            host = f"{host}:{parsed.port}" if parsed.port is not None else host
            proxy_url = urlunsplit((parsed.scheme, host, parsed.path, parsed.query, ""))
        self._pool = urllib3.ProxyManager(
            proxy_url,
            proxy_headers=proxy_headers,
            cert_reqs="CERT_REQUIRED",
            ca_certs=certifi.where(),
            timeout=urllib3.Timeout(connect=20, read=self.timeout_seconds),
            retries=False,
        )
        return self._pool

    @staticmethod
    def _parse_response(data: bytes) -> StructuredResult:
        try:
            raw = json.loads(data.decode("utf-8"))
            message = raw["choices"][0]["message"]
            content = message.get("content")
            value = message.get("parsed") if content is None else content
            if isinstance(value, list):
                value = "".join(
                    item.get("text", "") for item in value if isinstance(item, dict)
                )
            value = json.loads(value) if isinstance(value, str) else value
            if not isinstance(value, dict):
                raise TypeError
            return StructuredResult(
                value=value,
                model=str(raw.get("model", "unknown")),
                provider=str(raw.get("provider", "unknown")),
            )
        except (IndexError, KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProviderResponseError() from exc


class OpenRouterInterviewPipelineProvider:
    def __init__(self, client: StructuredClient, *, judge_workers: int = 6) -> None:
        self._client = client
        self._judge_workers = judge_workers

    async def evaluate(self, question: str, answer: str) -> EvaluateAnswerResponse:
        return await asyncio.to_thread(self._evaluate_sync, question, answer)

    def _evaluate_sync(self, question: str, answer: str) -> EvaluateAnswerResponse:
        claims, extraction_result = self._extract_claims(question, answer)

        def judge(claim: ExtractedClaim) -> tuple[AnswerAnnotation | None, StructuredResult]:
            return self._judge_claim(question, claim)

        workers = max(1, min(self._judge_workers, len(claims) + 1))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            completeness_future = executor.submit(self._judge_completeness, question, answer)
            judgements = list(executor.map(judge, claims))
            missing_aspects, completeness_result = completeness_future.result()

        spans = [span for span, _result in judgements if span is not None]
        results = [
            extraction_result,
            completeness_result,
            *(result for _span, result in judgements),
        ]
        return EvaluateAnswerResponse(
            spans=spans,
            missing_aspects=missing_aspects,
            meta=EvaluationMeta(
                models=list(dict.fromkeys(result.model for result in results)),
                providers=list(dict.fromkeys(result.provider for result in results)),
                prompt_version=PROMPT_VERSION,
                claims_evaluated=len(claims),
            ),
        )

    def _extract_claims(
        self, question: str, answer: str
    ) -> tuple[list[ExtractedClaim], StructuredResult]:
        result = self._client.complete_json(
            messages=[
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user", "content": f"QUESTION:\n{question}\n\nANSWER:\n{answer}"},
            ],
            schema_name="claim_extraction",
            schema=EXTRACTION_SCHEMA,
            purpose="extraction",
        )
        claims = [
            ExtractedClaim.model_validate(item)
            for item in self._align_quotes(answer, result.value.get("claims", []))
        ]
        return claims, result

    def _judge_claim(
        self, question: str, claim: ExtractedClaim
    ) -> tuple[AnswerAnnotation | None, StructuredResult]:
        result = self._client.complete_json(
            messages=[
                {"role": "system", "content": JUDGEMENT_PROMPT},
                {"role": "user", "content": f"QUESTION:\n{question}\n\nCLAIM:\n{claim.text}"},
            ],
            schema_name="claim_judgement",
            schema=JUDGEMENT_SCHEMA,
            purpose="judgement",
        )
        try:
            judgement = ClaimJudgement.model_validate(result.value)
        except ValidationError as exc:
            raise ProviderResponseError() from exc
        label = self._annotation_label(judgement)
        annotation = (
            AnswerAnnotation(
                **claim.model_dump(),
                label=label,
                confidence=judgement.confidence,
                rationale=judgement.rationale,
            )
            if label is not None
            else None
        )
        return annotation, result

    def _judge_completeness(
        self, question: str, answer: str
    ) -> tuple[list[MissingAspect], StructuredResult]:
        result = self._client.complete_json(
            messages=[
                {"role": "system", "content": COMPLETENESS_PROMPT},
                {"role": "user", "content": f"QUESTION:\n{question}\n\nANSWER:\n{answer}"},
            ],
            schema_name="missing_aspects",
            schema=COMPLETENESS_SCHEMA,
            purpose="completeness",
        )
        aligned = self._align_quotes(question, result.value.get("missing_aspects", []))
        accepted = [item for item in aligned if self._is_confident_explicit_aspect(item)]
        try:
            return [MissingAspect.model_validate(item) for item in accepted], result
        except ValidationError as exc:
            raise ProviderResponseError() from exc

    @staticmethod
    def _annotation_label(judgement: ClaimJudgement) -> AnnotationLabel | None:
        if judgement.confidence < CLAIM_CONFIDENCE_THRESHOLD:
            return AnnotationLabel.REVIEW
        return {"correct": None, "incorrect": AnnotationLabel.INCORRECT}[judgement.verdict]

    @staticmethod
    def _is_confident_explicit_aspect(item: dict[str, Any]) -> bool:
        confidence = item.get("confidence")
        return (
            isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and confidence >= COMPLETENESS_CONFIDENCE_THRESHOLD
            and str(item.get("text", "")).casefold().startswith(EXPLICIT_ASPECT_PREFIXES)
        )

    @staticmethod
    def _align_quotes(source: str, raw_items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        aligned: list[dict[str, Any]] = []
        for raw in raw_items:
            text = str(raw.get("text", ""))
            hint = raw.get("start") if isinstance(raw.get("start"), int) else -1
            candidates: list[int] = []
            position = source.find(text)
            while text and position >= 0:
                candidates.append(position)
                position = source.find(text, position + 1)
            candidates.sort(key=lambda start: (abs(start - hint) if hint >= 0 else start, start))
            start = next(
                (
                    candidate
                    for candidate in candidates
                    if not OpenRouterInterviewPipelineProvider._overlaps(
                        candidate, candidate + len(text), aligned
                    )
                ),
                None,
            )
            if start is not None:
                aligned.append({**raw, "start": start, "end": start + len(text), "text": text})
        return sorted(aligned, key=lambda item: (item["start"], item["end"]))

    @staticmethod
    def _overlaps(start: int, end: int, spans: Sequence[dict[str, Any]]) -> bool:
        return any(start < int(span["end"]) and int(span["start"]) < end for span in spans)
