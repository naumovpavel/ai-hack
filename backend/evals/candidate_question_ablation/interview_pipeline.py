"""Claim extraction and context-based judging for interview answers.

The module intentionally has a small dependency surface and can be used both as
a Python API and as a command line application.  Network requests never bypass
the proxy configured in OPENAI_PROXY_URL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import unquote, urlsplit, urlunsplit


LABELS = ("правильный", "неправильный", "рекомендуется проверка")
DEFAULT_MODEL = "deepseek/deepseek-v4-flash-0731"
DEFAULT_FALLBACK_MODEL = "openai/gpt-5.6-luna"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
PROMPT_VERSION = "interview-claims-v1"


class PipelineError(RuntimeError):
    """A recoverable, user-facing pipeline error."""


def load_env(path: str | Path = ".env") -> dict[str, str]:
    """Read a small dotenv file without importing or mutating os.environ."""
    result: dict[str, str] = {}
    env_path = Path(path)
    if not env_path.exists():
        return result
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        result[key] = value
    return result


def _json_schema(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "strict": True, "schema": schema},
    }


@dataclass
class LLMResult:
    value: dict[str, Any]
    raw: dict[str, Any]
    cached: bool


class OpenRouterClient:
    """Minimal OpenRouter client that requires a configured proxy."""

    def __init__(
        self,
        *,
        api_key: str,
        proxy_url: str,
        model: str = DEFAULT_MODEL,
        fallback_model: str | None = DEFAULT_FALLBACK_MODEL,
        cache_dir: str | Path = "artifacts/cache",
        refresh: bool = False,
        timeout_seconds: float = 90.0,
        max_retries: int = 1,
    ) -> None:
        if not api_key:
            raise PipelineError("OPENAI_API_KEY is missing")
        if not proxy_url:
            raise PipelineError(
                "OPENAI_PROXY_URL is required; direct OpenRouter access is forbidden"
            )
        if not proxy_url.startswith(("http://", "https://")):
            raise PipelineError("OPENAI_PROXY_URL must be an http(s) proxy URL")
        self.api_key = api_key
        self.proxy_url = proxy_url
        self.model = model
        self.fallback_model = fallback_model
        self.cache_dir = Path(cache_dir)
        self.refresh = refresh
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._pool: Any = None

    @classmethod
    def from_env(
        cls,
        env_path: str | Path = ".env",
        *,
        model: str | None = None,
        refresh: bool = False,
        cache_dir: str | Path = "artifacts/cache",
    ) -> "OpenRouterClient":
        values = {**load_env(env_path), **os.environ}
        return cls(
            api_key=values.get("OPENAI_API_KEY", ""),
            proxy_url=values.get("OPENAI_PROXY_URL", ""),
            model=model or values.get("OPENROUTER_MODEL", DEFAULT_MODEL),
            fallback_model=values.get("OPENROUTER_FALLBACK_MODEL", DEFAULT_FALLBACK_MODEL),
            refresh=refresh,
            cache_dir=cache_dir,
        )

    def _get_pool(self) -> Any:
        if self._pool is None:
            try:
                import certifi
                import urllib3
            except ImportError as exc:
                raise PipelineError(
                    "Missing dependencies. Run: python -m pip install -r requirements.txt"
                ) from exc
            parsed = urlsplit(self.proxy_url)
            proxy_headers = None
            proxy_url = self.proxy_url
            if parsed.username is not None:
                username = unquote(parsed.username)
                password = unquote(parsed.password or "")
                proxy_headers = urllib3.make_headers(
                    proxy_basic_auth=f"{username}:{password}"
                )
                host = parsed.hostname or ""
                if ":" in host and not host.startswith("["):
                    host = f"[{host}]"
                if parsed.port is not None:
                    host = f"{host}:{parsed.port}"
                proxy_url = urlunsplit((parsed.scheme, host, parsed.path, parsed.query, ""))
            self._pool = urllib3.ProxyManager(
                proxy_url,
                proxy_headers=proxy_headers,
                cert_reqs="CERT_REQUIRED",
                ca_certs=certifi.where(),
                timeout=urllib3.Timeout(connect=20.0, read=self.timeout_seconds),
                retries=False,
            )
        return self._pool

    def complete_json(
        self,
        *,
        messages: list[dict[str, str]],
        schema_name: str,
        schema: dict[str, Any],
        purpose: str,
    ) -> LLMResult:
        errors: list[str] = []
        models = [self.model]
        if self.fallback_model and self.fallback_model not in models:
            models.append(self.fallback_model)
        for model in models:
            try:
                return self._complete_json_for_model(
                    model=model,
                    messages=messages,
                    schema_name=schema_name,
                    schema=schema,
                    purpose=purpose,
                )
            except PipelineError as exc:
                errors.append(f"{model}: {exc}")
        raise PipelineError("; fallback failed; ".join(errors))

    def _complete_json_for_model(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        schema_name: str,
        schema: dict[str, Any],
        purpose: str,
    ) -> LLMResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": {
                "answer generation": 2600,
                "claim extraction": 1800,
                "claim judgement": 700,
                "coverage judgement": 700,
                "question variation generation": 160,
                "smoke test": 100,
            }.get(purpose, 1200),
            "reasoning": {"enabled": False, "exclude": True},
            "response_format": _json_schema(schema_name, schema),
            "provider": {
                "require_parameters": True,
                "data_collection": "deny",
            },
        }
        # Current GPT-5 endpoints expose a deterministic seed but not temperature;
        # require_parameters=true would otherwise filter every provider out.
        if model.startswith("openai/gpt-5"):
            payload["seed"] = 0
        else:
            payload["temperature"] = 0
        cache_key = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        cache_path = self.cache_dir / f"{cache_key}.json"
        if cache_path.exists() and not self.refresh:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
            return LLMResult(self._extract_value(raw), raw, True)

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://localhost/interview-claim-eval",
            "X-Title": "Interview claim evaluation",
        }
        retryable = {408, 409, 429, 500, 502, 503, 504}
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._get_pool().request(
                    "POST",
                    OPENROUTER_URL,
                    body=body,
                    headers=headers,
                )
                raw_text = response.data.decode("utf-8", errors="replace")
                if response.status in retryable and attempt < self.max_retries:
                    time.sleep(min(2**attempt + random.random(), 8.0))
                    continue
                if response.status < 200 or response.status >= 300:
                    snippet = raw_text[:500].replace(self.api_key, "[REDACTED]")
                    raise PipelineError(
                        f"OpenRouter {purpose} failed with HTTP {response.status}: {snippet}"
                    )
                raw = json.loads(raw_text)
                try:
                    value = self._extract_value(raw)
                except PipelineError:
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
                    cache_path.with_suffix(".error.json").write_text(
                        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    raise
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(
                    json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                return LLMResult(value, raw, False)
            except PipelineError:
                raise
            except Exception as exc:  # transport and malformed response
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(min(2**attempt + random.random(), 8.0))
                    continue
        raise PipelineError(
            f"OpenRouter {purpose} failed through configured proxy: {last_error}. "
            "Direct fallback was not attempted."
        ) from last_error

    @staticmethod
    def _extract_value(raw: dict[str, Any]) -> dict[str, Any]:
        try:
            message = raw["choices"][0]["message"]
            content = message.get("content")
            if content is None and isinstance(message.get("parsed"), dict):
                return message["parsed"]
            if isinstance(content, dict):
                return content
            if isinstance(content, list):
                content = "".join(
                    item.get("text", "") for item in content if isinstance(item, dict)
                )
            value = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise PipelineError("OpenRouter returned malformed structured output") from exc
        if not isinstance(value, dict):
            raise PipelineError("Structured output must be a JSON object")
        return value


def _raw_metadata(result: LLMResult) -> dict[str, Any]:
    raw = result.raw
    return {
        "id": raw.get("id"),
        "model": raw.get("model"),
        "provider": raw.get("provider"),
        "usage": raw.get("usage"),
        "cached": result.cached,
        "response": raw,
    }


def _occupied(candidate: tuple[int, int], spans: Sequence[dict[str, Any]]) -> bool:
    start, end = candidate
    return any(start < int(s["end"]) and int(s["start"]) < end for s in spans)


def align_claims(answer: str, raw_claims: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate quotes and deterministically align them to non-overlapping spans."""
    aligned: list[dict[str, Any]] = []
    for raw in raw_claims:
        text = str(raw.get("text", ""))
        if not text or not text.strip():
            continue
        hint = raw.get("start", -1)
        try:
            hint = int(hint)
        except (TypeError, ValueError):
            hint = -1
        candidates: list[int] = []
        pos = answer.find(text)
        while pos != -1:
            candidates.append(pos)
            pos = answer.find(text, pos + 1)
        if not candidates:
            continue
        candidates.sort(key=lambda value: (abs(value - hint) if hint >= 0 else value, value))
        chosen: int | None = None
        for start in candidates:
            if not _occupied((start, start + len(text)), aligned):
                chosen = start
                break
        if chosen is None:
            continue
        aligned.append({"start": chosen, "end": chosen + len(text), "text": text})
    return sorted(aligned, key=lambda span: (span["start"], span["end"]))


def extract_claims(
    question: str, answer: str, client: OpenRouterClient
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    schema = {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "Exact verbatim substring from the answer",
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
    messages = [
        {
            "role": "system",
            "content": (
                "Выдели все атомарные содержательные утверждения в ответе кандидата. "
                "Каждый text обязан быть точной непрерывной цитатой из ответа. "
                "Не включай речевой шум и вводные слова. Не оценивай истинность. "
                "Спаны не должны пересекаться. Индексы — Python Unicode [start,end)."
            ),
        },
        {"role": "user", "content": f"ВОПРОС:\n{question}\n\nОТВЕТ:\n{answer}"},
    ]
    result = client.complete_json(
        messages=messages,
        schema_name="claim_extraction",
        schema=schema,
        purpose="claim extraction",
    )
    claims = align_claims(answer, result.value.get("claims", []))
    return claims, _raw_metadata(result)


def judge_claim(
    question: str,
    rubric: Sequence[dict[str, Any]],
    claim: dict[str, Any],
    client: OpenRouterClient,
) -> tuple[dict[str, Any], dict[str, Any]]:
    rubric_ids = [str(item["id"]) for item in rubric]
    schema = {
        "type": "object",
        "properties": {
            "label": {"type": "string", "enum": list(LABELS)},
            "rationale": {"type": "string"},
            "rubric_ids": {
                "type": "array",
                "items": {"type": "string", "enum": rubric_ids},
            },
        },
        "required": ["label", "rationale", "rubric_ids"],
        "additionalProperties": False,
    }
    context = json.dumps(list(rubric), ensure_ascii=False, indent=2)
    messages = [
        {
            "role": "system",
            "content": (
                "Ты context-based judge одного клейма интервью. Оценивай только данный "
                "клейм, не используя другие части ответа. 'правильный' — верно, релевантно "
                "и достаточно конкретно по rubric; 'неправильный' — противоречит rubric, "
                "технически ошибочно, вводит в заблуждение, нерелевантно или заменяет "
                "требуемую конкретику пустой формулировкой; 'рекомендуется проверка' — "
                "контекста недостаточно, в частности для личного опыта или метрик. "
                "Не считай отсутствие других пунктов ошибкой этого клейма."
            ),
        },
        {
            "role": "user",
            "content": f"ВОПРОС:\n{question}\n\nRUBRIC/CONTEXT:\n{context}\n\nКЛЕЙМ:\n{claim['text']}",
        },
    ]
    result = client.complete_json(
        messages=messages,
        schema_name="claim_judgement",
        schema=schema,
        purpose="claim judgement",
    )
    value = result.value
    label = value.get("label")
    if label not in LABELS:
        raise PipelineError(f"Judge returned unsupported label: {label!r}")
    valid_ids = [item for item in value.get("rubric_ids", []) if item in rubric_ids]
    judged = {
        **claim,
        "label": label,
        "rationale": str(value.get("rationale", "")),
        "rubric_ids": valid_ids,
    }
    return judged, _raw_metadata(result)


def _find_missing_requirements(
    question: str,
    answer: str,
    rubric: Sequence[dict[str, Any]],
    client: OpenRouterClient,
) -> tuple[list[str], dict[str, Any]]:
    rubric_ids = [str(item["id"]) for item in rubric]
    schema = {
        "type": "object",
        "properties": {
            "missing_requirement_ids": {
                "type": "array",
                "items": {"type": "string", "enum": rubric_ids},
            }
        },
        "required": ["missing_requirement_ids"],
        "additionalProperties": False,
    }
    messages = [
        {
            "role": "system",
            "content": (
                "Определи обязательные пункты rubric, которые кандидат совсем не раскрыл. "
                "Пункт считается покрытым только при содержательном ответе, а не при простом "
                "упоминании термина. Верни только идентификаторы отсутствующих пунктов."
            ),
        },
        {
            "role": "user",
            "content": (
                f"ВОПРОС:\n{question}\n\nRUBRIC:\n"
                f"{json.dumps(list(rubric), ensure_ascii=False, indent=2)}"
                f"\n\nОТВЕТ:\n{answer}"
            ),
        },
    ]
    result = client.complete_json(
        messages=messages,
        schema_name="missing_requirements",
        schema=schema,
        purpose="coverage judgement",
    )
    missing = [
        item
        for item in result.value.get("missing_requirement_ids", [])
        if item in rubric_ids
    ]
    return missing, _raw_metadata(result)


def evaluate_answer(
    sample: dict[str, Any], client: OpenRouterClient, *, judge_workers: int = 6
) -> dict[str, Any]:
    claims, extraction_raw = extract_claims(sample["question"], sample["answer"], client)
    def run_judge(claim: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        return judge_claim(sample["question"], sample["rubric"], claim, client)

    # Claims are still judged in separate OpenRouter requests. The bounded pool
    # only overlaps their I/O and map() preserves extraction order.
    with ThreadPoolExecutor(max_workers=max(1, min(judge_workers, len(claims) + 1))) as executor:
        coverage_future = executor.submit(
            _find_missing_requirements,
            sample["question"],
            sample["answer"],
            sample["rubric"],
            client,
        )
        judged_results = list(executor.map(run_judge, claims))
        missing, coverage_raw = coverage_future.result()
    judged = [item for item, _ in judged_results]
    judge_raw = [raw for _, raw in judged_results]
    return {
        "sample_id": sample["sample_id"],
        "question_id": sample["question_id"],
        "question": sample["question"],
        "answer": sample["answer"],
        "predicted_spans": judged,
        "predicted_missing_requirements": missing,
        "run": {
            "prompt_version": PROMPT_VERSION,
            "requested_model": client.model,
            "extraction": extraction_raw,
            "judgements": judge_raw,
            "coverage": coverage_raw,
        },
    }


def generate_dataset(
    question_records: Sequence[dict[str, Any]],
    client: OpenRouterClient,
    *,
    variants_per_question: int = 3,
) -> list[dict[str, Any]]:
    """Generate an unreviewed draft; it never writes or replaces the gold set."""
    schema = {
        "type": "object",
        "properties": {
            "answers": {
                "type": "array",
                "minItems": variants_per_question,
                "maxItems": variants_per_question,
                "items": {
                    "type": "object",
                    "properties": {
                        "intended_quality": {
                            "type": "string",
                            "enum": ["correct", "incorrect", "mixed"],
                        },
                        "answer": {"type": "string"},
                    },
                    "required": ["intended_quality", "answer"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["answers"],
        "additionalProperties": False,
    }
    output: list[dict[str, Any]] = []
    for question in question_records:
        messages = [
            {
                "role": "system",
                "content": (
                    "Сгенерируй три реалистичных ответа русскоязычных кандидатов: один "
                    "технически корректный, один с явными ошибками и один смешанный. "
                    "Ошибки должны находиться в конкретных фразах, а ответы не должны "
                    "ссылаться на rubric. Добавляй проверяемые утверждения о личном опыте."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"ВОПРОС:\n{question['question']}\n\nRUBRIC:\n"
                    f"{json.dumps(question['rubric'], ensure_ascii=False, indent=2)}"
                ),
            },
        ]
        result = client.complete_json(
            messages=messages,
            schema_name="answer_generation",
            schema=schema,
            purpose="answer generation",
        )
        for index, item in enumerate(result.value.get("answers", []), start=1):
            output.append(
                {
                    "sample_id": f"{question['question_id']}-draft-{index}",
                    "question_id": question["question_id"],
                    "question": question["question"],
                    "rubric": question["rubric"],
                    "answer": item["answer"],
                    "provenance": "synthetic-openrouter-unreviewed",
                    "intended_quality": item["intended_quality"],
                    "generation": _raw_metadata(result),
                }
            )
    return output


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        Path(path).read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PipelineError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise PipelineError(f"Expected object at {path}:{line_number}")
        records.append(value)
    return records


def write_jsonl(path: str | Path, records: Iterable[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records)
    target.write_text(text, encoding="utf-8")


def validate_gold(records: Sequence[dict[str, Any]]) -> None:
    seen: set[str] = set()
    errors: list[str] = []
    for record in records:
        sample_id = str(record.get("sample_id", "<missing>"))
        if sample_id in seen:
            errors.append(f"{sample_id}: duplicate sample_id")
        seen.add(sample_id)
        answer = record.get("answer")
        rubric = record.get("rubric")
        spans = record.get("gold_spans")
        if not isinstance(answer, str) or not isinstance(rubric, list) or not isinstance(spans, list):
            errors.append(f"{sample_id}: missing answer/rubric/gold_spans")
            continue
        rubric_ids = {str(item.get("id")) for item in rubric if isinstance(item, dict)}
        previous_end = -1
        for span in sorted(spans, key=lambda item: (item.get("start", -1), item.get("end", -1))):
            start, end = span.get("start"), span.get("end")
            if not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end <= len(answer)):
                errors.append(f"{sample_id}: invalid span bounds {start}:{end}")
                continue
            if start < previous_end:
                errors.append(f"{sample_id}: overlapping spans near {start}:{end}")
            previous_end = end
            if answer[start:end] != span.get("text"):
                errors.append(f"{sample_id}: span text mismatch at {start}:{end}")
            if span.get("label") not in LABELS:
                errors.append(f"{sample_id}: unsupported label {span.get('label')!r}")
            unknown = set(span.get("rubric_ids", [])) - rubric_ids
            if unknown:
                errors.append(f"{sample_id}: unknown rubric ids {sorted(unknown)}")
        missing = set(record.get("gold_missing_requirements", []))
        if missing - rubric_ids:
            errors.append(f"{sample_id}: unknown missing ids {sorted(missing - rubric_ids)}")
    if errors:
        raise PipelineError("Gold validation failed:\n- " + "\n- ".join(errors))


def _span_iou(left: dict[str, Any], right: dict[str, Any]) -> float:
    intersection = max(0, min(left["end"], right["end"]) - max(left["start"], right["start"]))
    union = max(left["end"], right["end"]) - min(left["start"], right["start"])
    return intersection / union if union else 0.0


def _match_spans(
    gold: Sequence[dict[str, Any]],
    predicted: Sequence[dict[str, Any]],
    *,
    exact: bool,
    threshold: float = 0.5,
) -> list[tuple[int, int, float]]:
    candidates: list[tuple[float, int, int]] = []
    for gi, gold_span in enumerate(gold):
        for pi, pred_span in enumerate(predicted):
            score = _span_iou(gold_span, pred_span)
            eligible = (
                gold_span["start"] == pred_span["start"]
                and gold_span["end"] == pred_span["end"]
            ) if exact else score >= threshold
            if eligible:
                candidates.append((score, gi, pi))
    matches: list[tuple[int, int, float]] = []
    used_gold: set[int] = set()
    used_pred: set[int] = set()
    for score, gi, pi in sorted(candidates, reverse=True):
        if gi not in used_gold and pi not in used_pred:
            used_gold.add(gi)
            used_pred.add(pi)
            matches.append((gi, pi, score))
    return matches


def _prf(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def validate(
    gold_records: Sequence[dict[str, Any]],
    prediction_records: Sequence[dict[str, Any]],
    *,
    allow_partial: bool = False,
) -> dict[str, Any]:
    validate_gold(gold_records)
    predictions = {item["sample_id"]: item for item in prediction_records}
    missing_predictions = [item["sample_id"] for item in gold_records if item["sample_id"] not in predictions]
    if missing_predictions and not allow_partial:
        raise PipelineError(f"Missing predictions for {len(missing_predictions)} samples")
    evaluated_gold = [item for item in gold_records if item["sample_id"] in predictions]
    if not evaluated_gold:
        raise PipelineError("No predictions match the gold sample ids")

    span_counts = {"exact": Counter(), "relaxed": Counter(), "end_to_end": Counter()}
    label_confusion: dict[str, Counter[str]] = defaultdict(Counter)
    missing_counts = Counter()
    examples: list[dict[str, Any]] = []
    gold_distribution = Counter()
    predicted_distribution = Counter()
    for gold_record in evaluated_gold:
        predicted_record = predictions[gold_record["sample_id"]]
        gold_spans = gold_record["gold_spans"]
        pred_spans = predicted_record.get("predicted_spans", [])
        gold_distribution.update(span["label"] for span in gold_spans)
        predicted_distribution.update(span.get("label") for span in pred_spans)
        exact_matches = _match_spans(gold_spans, pred_spans, exact=True)
        relaxed_matches = _match_spans(gold_spans, pred_spans, exact=False)
        for name, matches in (("exact", exact_matches), ("relaxed", relaxed_matches)):
            span_counts[name]["tp"] += len(matches)
            span_counts[name]["fp"] += len(pred_spans) - len(matches)
            span_counts[name]["fn"] += len(gold_spans) - len(matches)
        correctly_labeled = 0
        for gi, pi, _ in relaxed_matches:
            gold_label = gold_spans[gi]["label"]
            pred_label = pred_spans[pi].get("label")
            label_confusion[gold_label][str(pred_label)] += 1
            if gold_label == pred_label:
                correctly_labeled += 1
        span_counts["end_to_end"]["tp"] += correctly_labeled
        span_counts["end_to_end"]["fp"] += len(pred_spans) - correctly_labeled
        span_counts["end_to_end"]["fn"] += len(gold_spans) - correctly_labeled

        gold_missing = set(gold_record.get("gold_missing_requirements", []))
        pred_missing = set(predicted_record.get("predicted_missing_requirements", []))
        missing_counts["tp"] += len(gold_missing & pred_missing)
        missing_counts["fp"] += len(pred_missing - gold_missing)
        missing_counts["fn"] += len(gold_missing - pred_missing)
        if len(examples) < 12 and (
            len(relaxed_matches) != len(gold_spans)
            or correctly_labeled != len(relaxed_matches)
            or gold_missing != pred_missing
        ):
            examples.append(
                {
                    "sample_id": gold_record["sample_id"],
                    "gold_spans": gold_spans,
                    "predicted_spans": pred_spans,
                    "gold_missing": sorted(gold_missing),
                    "predicted_missing": sorted(pred_missing),
                }
            )

    per_class: dict[str, dict[str, float | int]] = {}
    for label in LABELS:
        tp = label_confusion[label][label]
        fp = sum(label_confusion[other][label] for other in LABELS if other != label)
        fn = sum(label_confusion[label][other] for other in LABELS if other != label)
        per_class[label] = _prf(tp, fp, fn)
    macro_f1 = sum(float(item["f1"]) for item in per_class.values()) / len(LABELS)
    return {
        "samples": len(evaluated_gold),
        "gold_samples_total": len(gold_records),
        "partial": bool(missing_predictions),
        "missing_prediction_ids": missing_predictions,
        "prompt_version": PROMPT_VERSION,
        "span_exact": _prf(**span_counts["exact"]),
        "span_relaxed_iou_0_5": _prf(**span_counts["relaxed"]),
        "end_to_end_relaxed_span_and_label": _prf(**span_counts["end_to_end"]),
        "labels": {"per_class": per_class, "macro_f1": macro_f1, "confusion": {k: dict(v) for k, v in label_confusion.items()}},
        "missing_requirements": _prf(**missing_counts),
        "distribution": {"gold": dict(gold_distribution), "predicted": dict(predicted_distribution)},
        "error_examples": examples,
    }


def render_report(report: dict[str, Any]) -> str:
    def metric(name: str, value: dict[str, Any]) -> str:
        return f"| {name} | {value['precision']:.3f} | {value['recall']:.3f} | {value['f1']:.3f} |"

    lines = [
        "# Диагностический отчёт",
        "",
        f"Обработано ответов: **{report['samples']} из {report.get('gold_samples_total', report['samples'])}**. "
        f"Отчёт {'частичный' if report.get('partial') else 'полный'}; порог pass/fail не применяется.",
        "",
        "## Метрики",
        "",
        "| Метрика | Precision | Recall | F1 |",
        "|---|---:|---:|---:|",
        metric("Exact spans", report["span_exact"]),
        metric("Relaxed spans, IoU ≥ 0.5", report["span_relaxed_iou_0_5"]),
        metric("Span + category", report["end_to_end_relaxed_span_and_label"]),
        metric("Missing requirements", report["missing_requirements"]),
        "",
        f"Macro-F1 категорий на сопоставленных спанах: **{report['labels']['macro_f1']:.3f}**.",
        "",
        "## Распределение классов",
        "",
        "```json",
        json.dumps(report["distribution"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Матрица ошибок",
        "",
        "```json",
        json.dumps(report["labels"]["confusion"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Примеры расхождений",
        "",
    ]
    for example in report["error_examples"]:
        lines.extend(
            [
                f"### {example['sample_id']}",
                "",
                "```json",
                json.dumps(example, ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    if not report["error_examples"]:
        lines.append("Расхождений не обнаружено.")
    return "\n".join(lines) + "\n"


def _unique_questions(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        by_id.setdefault(
            record["question_id"],
            {"question_id": record["question_id"], "question": record["question"], "rubric": record["rubric"]},
        )
    return list(by_id.values())


def read_question_template(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if source.suffix.lower() == ".json":
        value = json.loads(source.read_text(encoding="utf-8-sig"))
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise PipelineError("Question template JSON must be an array of objects")
        return value
    records = read_jsonl(source)
    validate_gold(records)
    return _unique_questions(records)


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default=".env", help="dotenv file")
    parser.add_argument("--model", help=f"OpenRouter model (default: {DEFAULT_MODEL})")
    parser.add_argument("--refresh", action="store_true", help="ignore response cache")
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate", help="generate an unreviewed 30-answer draft")
    generate.add_argument("--template", default="data/questions.json")
    generate.add_argument("--output", default="data/generated_draft.jsonl")
    evaluate = sub.add_parser("evaluate", help="run extraction and judging")
    evaluate.add_argument("--input", default="data/gold.jsonl")
    evaluate.add_argument("--output", default="artifacts/predictions.jsonl")
    validation = sub.add_parser("validate", help="compare predictions with gold")
    validation.add_argument("--gold", default="data/gold.jsonl")
    validation.add_argument("--predictions", default="artifacts/predictions.jsonl")
    validation.add_argument("--report", default="artifacts/validation_report.json")
    validation.add_argument("--allow-partial", action="store_true")
    all_command = sub.add_parser("all", help="evaluate gold and produce both reports")
    all_command.add_argument("--gold", default="data/gold.jsonl")
    all_command.add_argument("--predictions", default="artifacts/predictions.jsonl")
    all_command.add_argument("--report", default="artifacts/validation_report.json")
    smoke = sub.add_parser("smoke", help="one minimal structured-output API request")
    smoke.add_argument("--output", default="artifacts/smoke.json")
    return parser


def _client(args: argparse.Namespace) -> OpenRouterClient:
    return OpenRouterClient.from_env(args.env, model=args.model, refresh=args.refresh)


def _run_evaluate(input_path: str, output_path: str, client: OpenRouterClient) -> None:
    records = read_jsonl(input_path)
    validate_gold(records)
    output: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        print(f"[{index}/{len(records)}] {record['sample_id']}", file=sys.stderr, flush=True)
        output.append(evaluate_answer(record, client))
        write_jsonl(output_path, output)


def _run_validate(
    gold_path: str,
    predictions_path: str,
    report_path: str,
    *,
    allow_partial: bool = False,
) -> dict[str, Any]:
    report = validate(
        read_jsonl(gold_path),
        read_jsonl(predictions_path),
        allow_partial=allow_partial,
    )
    target = Path(report_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    target.with_suffix(".md").write_text(render_report(report), encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = _make_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            questions = read_question_template(args.template)
            write_jsonl(args.output, generate_dataset(questions, _client(args)))
        elif args.command == "evaluate":
            _run_evaluate(args.input, args.output, _client(args))
        elif args.command == "validate":
            report = _run_validate(
                args.gold,
                args.predictions,
                args.report,
                allow_partial=args.allow_partial,
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "all":
            client = _client(args)
            _run_evaluate(args.gold, args.predictions, client)
            report = _run_validate(args.gold, args.predictions, args.report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "smoke":
            schema = {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            }
            result = _client(args).complete_json(
                messages=[{"role": "user", "content": "Верни JSON, где ok=true."}],
                schema_name="smoke_test",
                schema=schema,
                purpose="smoke test",
            )
            target = Path(args.output)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(_raw_metadata(result), ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result.value, ensure_ascii=False))
        return 0
    except PipelineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
