from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from interview_pipeline import (
    LABELS,
    OpenRouterClient,
    PipelineError,
    align_claims,
    load_env,
    validate,
    validate_gold,
)


class FakeResponse:
    def __init__(self, status: int, payload: dict) -> None:
        self.status = status
        self.data = json.dumps(payload).encode("utf-8")


class FakePool:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls = 0

    def request(self, *args, **kwargs):
        response = self.responses[self.calls]
        self.calls += 1
        return response


def raw_response(value: dict) -> dict:
    return {
        "id": "test",
        "model": "deepseek/deepseek-v4-flash-0731",
        "choices": [{"message": {"content": json.dumps(value, ensure_ascii=False)}}],
    }


def rubric() -> list[dict]:
    return [{"id": "r1", "criterion": "criterion", "support": "fact", "required": True}]


class EnvTests(unittest.TestCase):
    def test_load_env_supports_quotes_and_equals(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("A='one=two'\n# ignored\nB= plain \n", encoding="utf-8")
            self.assertEqual(load_env(path), {"A": "one=two", "B": "plain"})

    def test_proxy_is_mandatory(self):
        with self.assertRaises(PipelineError):
            OpenRouterClient(api_key="key", proxy_url="")

    @patch("urllib3.ProxyManager")
    def test_proxy_credentials_become_proxy_authorization(self, manager):
        client = OpenRouterClient(
            api_key="key", proxy_url="https://user:p%40ss@example.test:443"
        )
        client._get_pool()
        args, kwargs = manager.call_args
        self.assertEqual(args[0], "https://example.test:443")
        self.assertIn("proxy-authorization", {key.lower() for key in kwargs["proxy_headers"]})


class AlignmentTests(unittest.TestCase):
    def test_repeated_quote_uses_hint_and_avoids_overlap(self):
        answer = "Факт верен. Факт верен."
        spans = align_claims(
            answer,
            [
                {"text": "Факт верен.", "start": 12, "end": 23},
                {"text": "Факт верен.", "start": 0, "end": 11},
            ],
        )
        self.assertEqual([(item["start"], item["end"]) for item in spans], [(0, 11), (12, 23)])

    def test_non_verbatim_claim_is_rejected(self):
        self.assertEqual(align_claims("Исходный ответ", [{"text": "Пересказ", "start": 0}]), [])


class ClientTests(unittest.TestCase):
    @patch("interview_pipeline.time.sleep", return_value=None)
    def test_retry_then_success(self, _sleep):
        pool = FakePool(
            [
                FakeResponse(500, {"error": "temporary"}),
                FakeResponse(200, raw_response({"ok": True})),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            client = OpenRouterClient(
                api_key="key",
                proxy_url="https://proxy.test",
                fallback_model=None,
                cache_dir=directory,
                max_retries=1,
            )
            client._pool = pool
            schema = {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            }
            result = client.complete_json(
                messages=[{"role": "user", "content": "test"}],
                schema_name="test",
                schema=schema,
                purpose="test",
            )
            self.assertEqual(result.value, {"ok": True})
            self.assertEqual(pool.calls, 2)

    def test_malformed_structured_response(self):
        with self.assertRaises(PipelineError):
            OpenRouterClient._extract_value({"choices": [{"message": {"content": "no"}}]})


class ValidationTests(unittest.TestCase):
    def record(self):
        answer = "Kafka хранит сообщения. Опыт был в банке."
        return {
            "sample_id": "s1",
            "question_id": "q1",
            "question": "Вопрос",
            "answer": answer,
            "rubric": rubric(),
            "gold_spans": [
                {
                    "start": 0,
                    "end": 23,
                    "text": "Kafka хранит сообщения.",
                    "label": "правильный",
                    "rationale": "ok",
                    "rubric_ids": ["r1"],
                },
                {
                    "start": 24,
                    "end": len(answer),
                    "text": "Опыт был в банке.",
                    "label": "рекомендуется проверка",
                    "rationale": "check",
                    "rubric_ids": ["r1"],
                },
            ],
            "gold_missing_requirements": [],
        }

    def test_gold_rejects_wrong_offset(self):
        record = self.record()
        record["gold_spans"][0]["end"] = 10
        with self.assertRaises(PipelineError):
            validate_gold([record])

    def test_metrics_perfect_prediction(self):
        record = self.record()
        prediction = {
            "sample_id": "s1",
            "predicted_spans": [dict(item) for item in record["gold_spans"]],
            "predicted_missing_requirements": [],
        }
        report = validate([record], [prediction])
        self.assertEqual(report["span_exact"]["f1"], 1.0)
        self.assertEqual(report["end_to_end_relaxed_span_and_label"]["f1"], 1.0)
        self.assertEqual(report["labels"]["macro_f1"], 2 / len(LABELS))

    def test_partial_validation_is_explicit(self):
        first = self.record()
        second = self.record()
        second["sample_id"] = "s2"
        prediction = {
            "sample_id": "s1",
            "predicted_spans": [dict(item) for item in first["gold_spans"]],
            "predicted_missing_requirements": [],
        }
        with self.assertRaises(PipelineError):
            validate([first, second], [prediction])
        report = validate([first, second], [prediction], allow_partial=True)
        self.assertTrue(report["partial"])
        self.assertEqual(report["samples"], 1)
        self.assertEqual(report["gold_samples_total"], 2)
        self.assertEqual(report["missing_prediction_ids"], ["s2"])


if __name__ == "__main__":
    unittest.main()
