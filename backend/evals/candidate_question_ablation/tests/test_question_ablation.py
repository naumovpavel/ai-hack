from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from interview_pipeline import LLMResult, PipelineError
from question_ablation import (
    Arm,
    QuestionVariantGenerator,
    RetryingStructuredClient,
    _question_context,
    build_arm_records,
    compare_reports,
    evaluate_records,
    paired_primary_effects,
    validate_arms,
)


def gold_record() -> dict:
    answer = "Kafka хранит сообщения."
    return {
        "sample_id": "s1",
        "question_id": "q1",
        "question": "Расскажите подробно, как Kafka хранит сообщения и подтверждает запись?",
        "answer": answer,
        "rubric": [
            {"id": "r1", "criterion": "Хранение", "support": "Лог", "required": True}
        ],
        "gold_spans": [
            {
                "start": 0,
                "end": len(answer),
                "text": answer,
                "label": "правильный",
                "rationale": "ok",
                "rubric_ids": ["r1"],
            }
        ],
        "gold_missing_requirements": [],
    }


class FakeGenerationClient:
    model = "fake"
    fallback_model = None

    def complete_json(self, *, schema_name, **_kwargs):
        if schema_name == "concise_interview_question":
            value = {"question": "Как Kafka хранит сообщения?"}
        else:
            value = {"questions": ["Как подтверждали запись?"]}
        return LLMResult(
            value=value,
            raw={"id": "fake", "model": "fake", "provider": "test"},
            cached=False,
        )


class FakeEvaluationClient:
    model = "fake"

    def complete_json(self, *, schema_name, **_kwargs):
        values = {
            "claim_extraction": {
                "claims": [{"text": "Kafka хранит сообщения.", "start": 0, "end": 24}]
            },
            "claim_judgement": {
                "label": "правильный",
                "rationale": "ok",
                "rubric_ids": ["r1"],
            },
            "missing_requirements": {"missing_requirement_ids": []},
        }
        return LLMResult(
            value=values[schema_name],
            raw={"id": "fake", "model": "fake", "provider": "test"},
            cached=False,
        )


class FlakyClient:
    model = "fake"
    fallback_model = None

    def __init__(self):
        self.calls = 0

    def complete_json(self, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            raise PipelineError("Structured output must be a JSON object")
        return "ok"


class ArmTests(unittest.TestCase):
    def test_retries_structured_output_with_same_model(self):
        flaky = FlakyClient()
        client = RetryingStructuredClient(flaky, retries=1)
        self.assertEqual(client.complete_json(), "ok")
        self.assertEqual(flaky.calls, 2)

    def test_rejects_two_changed_hyperparameters(self):
        with self.assertRaises(PipelineError):
            validate_arms(
                [
                    Arm("baseline"),
                    Arm("confounded", max_question_words=20, follow_up_count=1),
                ]
            )

    def test_builds_concise_arm_without_mutating_gold(self):
        source = gold_record()
        original = copy.deepcopy(source)
        records, manifest = build_arm_records(
            [source],
            Arm("short", max_question_words=20),
            QuestionVariantGenerator(FakeGenerationClient()),
        )
        self.assertEqual(records[0]["question"], "Как Kafka хранит сообщения?")
        self.assertEqual(source, original)
        self.assertEqual(manifest[0]["original_question"], original["question"])

    def test_builds_follow_up_context(self):
        records, manifest = build_arm_records(
            [gold_record()],
            Arm("follow", follow_up_count=1),
            QuestionVariantGenerator(FakeGenerationClient()),
        )
        self.assertIn("Уточняющие вопросы", records[0]["question"])
        self.assertEqual(manifest[0]["follow_ups"], ["Как подтверждали запись?"])
        self.assertEqual(
            _question_context("База?", ["Уточнение?"]),
            "База?\n\nУточняющие вопросы:\n1. Уточнение?",
        )

    def test_reuses_seeded_follow_up_without_model_call(self):
        seeded = _question_context(gold_record()["question"], ["Что осталось неясным?"])
        records, manifest = build_arm_records(
            [gold_record()],
            Arm("follow", follow_up_count=1),
            None,
            seeded_questions={"s1": seeded},
        )
        self.assertEqual(records[0]["question"], seeded)
        self.assertEqual(manifest[0]["follow_ups"], ["Что осталось неясным?"])
        self.assertEqual(manifest[0]["generation"], {"seeded": True})

    def test_evaluation_checkpoints_and_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "predictions.jsonl"
            first = evaluate_records([gold_record()], FakeEvaluationClient(), output)
            second = evaluate_records([gold_record()], FakeEvaluationClient(), output)
        self.assertEqual(first, second)
        self.assertEqual(len(second), 1)


class ComparisonTests(unittest.TestCase):
    def test_reports_deltas_from_baseline(self):
        base = {
            "samples": 1,
            "span_exact": {"f1": 0.5},
            "span_relaxed_iou_0_5": {"f1": 0.6},
            "end_to_end_relaxed_span_and_label": {"f1": 0.4},
            "labels": {"macro_f1": 0.3},
            "missing_requirements": {"f1": 0.2},
        }
        changed = copy.deepcopy(base)
        changed["end_to_end_relaxed_span_and_label"]["f1"] = 0.55
        summary = compare_reports(
            {"baseline": base, "follow": changed},
            [Arm("baseline"), Arm("follow", follow_up_count=1)],
        )
        self.assertAlmostEqual(
            summary["arms"][1]["delta_vs_baseline"]["span_and_label_f1"],
            0.15,
        )

    def test_paired_effects_report_wins_and_interval(self):
        record = gold_record()
        correct = {
            "sample_id": "s1",
            "predicted_spans": [dict(record["gold_spans"][0])],
            "predicted_missing_requirements": [],
        }
        empty = {
            "sample_id": "s1",
            "predicted_spans": [],
            "predicted_missing_requirements": [],
        }
        effects = paired_primary_effects(
            [record],
            {"baseline": [empty], "follow": [correct]},
            [Arm("baseline"), Arm("follow", follow_up_count=1)],
            bootstrap_samples=10,
        )
        self.assertEqual(effects[1]["wins"], 1)
        self.assertEqual(effects[1]["bootstrap_95_ci"], [1.0, 1.0])


if __name__ == "__main__":
    unittest.main()
