import json
from typing import Any

import pytest

from interview_api.domain.models import AnnotationLabel, ClaimJudgement
from interview_api.providers.openrouter_interview import (
    OpenRouterClient,
    OpenRouterInterviewPipelineProvider,
    StructuredResult,
)


class FakeStructuredClient:
    def complete_json(
        self,
        *,
        messages: list[dict[str, str]],
        schema_name: str,
        schema: dict[str, Any],
        purpose: str,
    ) -> StructuredResult:
        del schema_name, schema
        user_message = messages[-1]["content"]
        values = {
            "extraction": {
                "claims": [
                    {"text": "MVCC overwrites rows in place.", "start": 0, "end": 30},
                    {
                        "text": "Read Committed can observe phantom reads.",
                        "start": 55,
                        "end": 99,
                    },
                    {
                        "text": "An index guarantees serializability.",
                        "start": 100,
                        "end": 135,
                    },
                ]
            },
            "completeness": {
                "missing_aspects": [
                    {
                        "text": "which isolation levels",
                        "start": 25,
                        "end": 47,
                        "confidence": 0.91,
                        "rationale": "The answer does not identify the requested levels.",
                    },
                    {
                        "text": "PostgreSQL concurrency",
                        "start": 0,
                        "end": 22,
                        "confidence": 0.99,
                        "rationale": "This is only broad context.",
                    },
                ]
            },
        }
        if purpose != "judgement":
            return StructuredResult(values[purpose], "openai/gpt-5.6-luna", "test")
        judgements = {
            "MVCC overwrites": ("incorrect", 0.98),
            "Read Committed": ("correct", 0.96),
            "An index": ("incorrect", 0.69),
        }
        verdict, confidence = next(
            value for prefix, value in judgements.items() if prefix in user_message
        )
        return StructuredResult(
            {
                "verdict": verdict,
                "confidence": confidence,
                "rationale": "Technical judgement.",
            },
            "openai/gpt-5.6-luna",
            "test",
        )


class FakeHttpResponse:
    def __init__(self, status: int, data: bytes = b"") -> None:
        self.status = status
        self.data = data


class RetryingPool:
    def __init__(self, responses: list[FakeHttpResponse]) -> None:
        self.responses = iter(responses)
        self.calls = 0
        self.request_kwargs: list[dict[str, Any]] = []

    def request(self, *args: Any, **kwargs: Any) -> FakeHttpResponse:
        del args
        self.calls += 1
        self.request_kwargs.append(kwargs)
        return next(self.responses)


@pytest.mark.asyncio
async def test_pipeline_returns_only_incorrect_and_low_confidence_spans() -> None:
    question = (
        "Explain PostgreSQL concurrency and which isolation levels can produce phantom reads."
    )
    answer = (
        "MVCC overwrites rows in place. I processed 20 million rows. "
        "Read Committed can observe phantom reads. "
        "An index guarantees serializability."
    )
    provider = OpenRouterInterviewPipelineProvider(FakeStructuredClient())  # type: ignore[arg-type]

    result = await provider.evaluate(question, answer)

    assert [span.label for span in result.spans] == [
        AnnotationLabel.INCORRECT,
        AnnotationLabel.REVIEW,
    ]
    assert [span.text for span in result.spans] == [
        "MVCC overwrites rows in place.",
        "An index guarantees serializability.",
    ]
    assert "20 million" not in " ".join(span.text for span in result.spans)
    assert all(answer[span.start : span.end] == span.text for span in result.spans)
    assert [aspect.text for aspect in result.missing_aspects] == ["which isolation levels"]
    assert result.meta.claims_evaluated == 3


def test_confidence_thresholds_are_inclusive() -> None:
    provider = OpenRouterInterviewPipelineProvider(FakeStructuredClient())  # type: ignore[arg-type]

    assert provider._annotation_label(
        ClaimJudgement(verdict="correct", confidence=0.69, rationale="uncertain")
    ) is AnnotationLabel.REVIEW
    assert provider._annotation_label(
        ClaimJudgement(verdict="correct", confidence=0.70, rationale="certain")
    ) is None
    assert not provider._is_confident_explicit_aspect(
        {"text": "which indexes", "confidence": 0.84}
    )
    assert provider._is_confident_explicit_aspect(
        {"text": "which indexes", "confidence": 0.85}
    )


def test_repeated_quotes_follow_model_offset_hints() -> None:
    items = [
        {"text": "retry", "start": 10, "end": 15},
        {"text": "retry", "start": 0, "end": 5},
    ]

    aligned = OpenRouterInterviewPipelineProvider._align_quotes("retry and retry", items)

    assert [item["start"] for item in aligned] == [0, 10]


def test_client_requires_proxy() -> None:
    with pytest.raises(ValueError, match="proxy URL"):
        OpenRouterClient(api_key="secret", proxy_url="")


def test_structured_response_parser() -> None:
    raw = {
        "model": "openai/gpt-5.6-luna",
        "provider": "test-provider",
        "choices": [{"message": {"content": json.dumps({"claims": []})}}],
    }

    result = OpenRouterClient._parse_response(json.dumps(raw).encode())

    assert result.value == {"claims": []}
    assert result.model == "openai/gpt-5.6-luna"
    assert result.provider == "test-provider"


def test_client_retries_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = {
        "model": "openai/gpt-5.6-luna",
        "provider": "test-provider",
        "choices": [{"message": {"content": json.dumps({"claims": []})}}],
    }
    pool = RetryingPool(
        [FakeHttpResponse(429), FakeHttpResponse(200, json.dumps(raw).encode())]
    )
    client = OpenRouterClient(
        api_key="secret",
        proxy_url="https://proxy.example:443",
        fallback_model=None,
        max_retries=1,
    )
    client._pool = pool  # type: ignore[assignment]
    monkeypatch.setattr("interview_api.providers.openrouter_interview.time.sleep", lambda _: None)

    result = client.complete_json(
        messages=[{"role": "user", "content": "test"}],
        schema_name="test",
        schema={"type": "object"},
        purpose="extraction",
    )

    assert pool.calls == 2
    assert result.value == {"claims": []}


def test_client_uses_question_generation_model_override() -> None:
    raw = {
        "model": "openai/gpt-5.6-luna",
        "provider": "test-provider",
        "choices": [{"message": {"content": json.dumps({"questions": []})}}],
    }
    pool = RetryingPool([FakeHttpResponse(200, json.dumps(raw).encode())])
    client = OpenRouterClient(
        api_key="secret",
        proxy_url="https://proxy.example:443",
        model="answer-model",
        fallback_model=None,
    )
    client._pool = pool  # type: ignore[assignment]

    client.complete_json(
        messages=[{"role": "user", "content": "test"}],
        schema_name="questions",
        schema={"type": "object"},
        purpose="question_generation",
        model="openai/gpt-5.6-luna",
    )

    payload = json.loads(pool.request_kwargs[0]["body"])
    assert payload["model"] == "openai/gpt-5.6-luna"
    assert payload["max_tokens"] == 4000
    assert payload["provider"]["zdr"] is True
