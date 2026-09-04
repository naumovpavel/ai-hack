"""One-factor-at-a-time ablation of interview question wording.

The experiment keeps the answer, rubric, gold spans, evaluator prompt and
evaluator model fixed.  An arm changes either the maximum length of the base
question or the number of answer-conditioned follow-up questions, never both.

This measures sensitivity of the answer evaluator to question context.  It does
not measure how a candidate would change their answer after hearing a follow-up;
that requires a separate gold dataset with actual follow-up answers.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import random
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from interview_pipeline import (
    DEFAULT_MODEL,
    OpenRouterClient,
    PipelineError,
    evaluate_answer,
    load_env,
    read_jsonl,
    render_report,
    validate,
    validate_gold,
    write_jsonl,
)


EXPERIMENT_VERSION = "question-context-ablation-v1"
FOLLOW_UP_MAX_WORDS = 18
PRIMARY_METRIC = "end_to_end_relaxed_span_and_label.f1"
METRICS = {
    "span_exact_f1": ("span_exact", "f1"),
    "span_relaxed_f1": ("span_relaxed_iou_0_5", "f1"),
    "span_and_label_f1": ("end_to_end_relaxed_span_and_label", "f1"),
    "label_macro_f1": ("labels", "macro_f1"),
    "missing_requirements_f1": ("missing_requirements", "f1"),
}


@dataclass(frozen=True, slots=True)
class Arm:
    name: str
    max_question_words: int | None = None
    follow_up_count: int = 0

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Arm":
        allowed = {"name", "max_question_words", "follow_up_count"}
        unknown = set(value) - allowed
        if unknown:
            raise PipelineError(f"Unknown arm fields: {sorted(unknown)}")
        return cls(
            name=str(value.get("name", "")).strip(),
            max_question_words=value.get("max_question_words"),
            follow_up_count=value.get("follow_up_count", 0),
        )


def load_arms(path: str | Path) -> list[Arm]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError(f"Cannot read arm configuration {path}: {exc}") from exc
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise PipelineError("Arm configuration must be a JSON array of objects")
    arms = [Arm.from_dict(item) for item in raw]
    validate_arms(arms)
    return arms


def validate_arms(arms: Sequence[Arm]) -> None:
    if not arms:
        raise PipelineError("At least one experiment arm is required")
    names = [arm.name for arm in arms]
    if any(not name for name in names):
        raise PipelineError("Every experiment arm needs a non-empty name")
    if len(set(names)) != len(names):
        raise PipelineError("Experiment arm names must be unique")

    baseline = [
        arm
        for arm in arms
        if arm.max_question_words is None and arm.follow_up_count == 0
    ]
    if len(baseline) != 1 or baseline[0].name != "baseline":
        raise PipelineError(
            "Define exactly one unchanged arm named 'baseline'"
        )

    for arm in arms:
        max_words = arm.max_question_words
        follow_up_count = arm.follow_up_count
        if max_words is not None and (
            not isinstance(max_words, int)
            or isinstance(max_words, bool)
            or max_words < 8
        ):
            raise PipelineError(
                f"{arm.name}: max_question_words must be null or an integer >= 8"
            )
        if (
            not isinstance(follow_up_count, int)
            or isinstance(follow_up_count, bool)
            or not 0 <= follow_up_count <= 5
        ):
            raise PipelineError(
                f"{arm.name}: follow_up_count must be an integer from 0 to 5"
            )
        changed = int(max_words is not None) + int(follow_up_count > 0)
        if arm.name != "baseline" and changed != 1:
            raise PipelineError(
                f"{arm.name}: change exactly one hyperparameter from baseline"
            )


def _word_count(value: str) -> int:
    return len(value.split())


def _minimal_result_metadata(result: Any) -> dict[str, Any]:
    raw = result.raw if isinstance(result.raw, dict) else {}
    return {
        "id": raw.get("id"),
        "model": raw.get("model"),
        "provider": raw.get("provider"),
        "usage": raw.get("usage"),
        "cached": bool(result.cached),
    }


class QuestionVariantGenerator:
    """Generate deterministic question contexts through the pipeline client."""

    def __init__(self, client: OpenRouterClient) -> None:
        self.client = client
        self._short_cache: dict[tuple[str, int], tuple[str, dict[str, Any]]] = {}

    def shorten(
        self,
        *,
        question_id: str,
        question: str,
        rubric: Sequence[dict[str, Any]],
        max_words: int,
    ) -> tuple[str, dict[str, Any]]:
        key = (question_id, max_words)
        if key in self._short_cache:
            return self._short_cache[key]
        schema = {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
            "additionalProperties": False,
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "Перепиши вопрос интервью по-русски максимально коротко. "
                    "Сохрани все проверяемые аспекты rubric, не подсказывай ответ, "
                    "не добавляй новые требования и верни один вопрос. "
                    f"Жёсткий лимит: не более {max_words} слов."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"question": question, "rubric": list(rubric)},
                    ensure_ascii=False,
                ),
            },
        ]
        attempts: list[dict[str, Any]] = []
        generated = ""
        for attempt in range(3):
            result = self.client.complete_json(
                messages=messages,
                schema_name="concise_interview_question",
                schema=schema,
                purpose="question variation generation",
            )
            attempts.append(_minimal_result_metadata(result))
            generated = str(result.value.get("question", "")).strip()
            if generated and _word_count(generated) <= max_words:
                value = (generated, {"attempts": attempts})
                self._short_cache[key] = value
                return value
            if attempt < 2:
                messages = [
                    *messages,
                    {
                        "role": "user",
                        "content": (
                            f"Предыдущий вариант содержит {_word_count(generated)} слов: "
                            f"{generated!r}. Сократи его до {max_words} слов или меньше, "
                            "сохранив те же аспекты."
                        ),
                    },
                ]
        if not generated:
            raise PipelineError(f"{question_id}: generated an empty concise question")
        raise PipelineError(
            f"{question_id}: concise question has {_word_count(generated)} words, "
            f"expected at most {max_words} after 3 attempts"
        )

    def follow_ups(
        self,
        *,
        question_id: str,
        question: str,
        answer: str,
        rubric: Sequence[dict[str, Any]],
        count: int,
    ) -> tuple[list[str], dict[str, Any]]:
        schema = {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "minItems": count,
                    "maxItems": count,
                    "items": {"type": "string"},
                }
            },
            "required": ["questions"],
            "additionalProperties": False,
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "Сформулируй ровно указанное число коротких уточняющих вопросов "
                    "к ответу кандидата. Выбирай самый важный нераскрытый или "
                    "неоднозначный проверяемый аспект rubric. Не повторяй основной "
                    "вопрос, не подсказывай правильный ответ и не меняй критерии. "
                    f"Каждый вопрос — не более {FOLLOW_UP_MAX_WORDS} слов."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "questionId": question_id,
                        "question": question,
                        "answer": answer,
                        "rubric": list(rubric),
                        "followUpCount": count,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        attempts: list[dict[str, Any]] = []
        questions: list[str] = []
        for attempt in range(3):
            result = self.client.complete_json(
                messages=messages,
                schema_name="interview_follow_up_ablation",
                schema=schema,
                purpose="question variation generation",
            )
            attempts.append(_minimal_result_metadata(result))
            raw = result.value.get("questions")
            questions = [str(item).strip() for item in raw] if isinstance(raw, list) else []
            valid_count = len(questions) == count and all(questions)
            valid_length = all(
                _word_count(item) <= FOLLOW_UP_MAX_WORDS for item in questions
            )
            if valid_count and valid_length:
                return questions, {"attempts": attempts}
            if attempt < 2:
                messages = [
                    *messages,
                    {
                        "role": "user",
                        "content": (
                            "Исправь предыдущий результат: верни ровно "
                            f"{count} непустых вопросов, каждый не длиннее "
                            f"{FOLLOW_UP_MAX_WORDS} слов."
                        ),
                    },
                ]
        if len(questions) != count or any(not item for item in questions):
            raise PipelineError(
                f"{question_id}: expected {count} non-empty follow-ups, got {len(questions)}"
            )
        too_long = [item for item in questions if _word_count(item) > FOLLOW_UP_MAX_WORDS]
        raise PipelineError(
            f"{question_id}: follow-up exceeds {FOLLOW_UP_MAX_WORDS} words "
            f"after 3 attempts: {too_long[0]}"
        )


class RetryingStructuredClient:
    """Retry malformed structured output without changing the pinned model."""

    def __init__(self, client: OpenRouterClient, *, retries: int) -> None:
        self._client = client
        self.retries = retries
        self.model = client.model
        self.fallback_model = client.fallback_model

    def complete_json(self, **kwargs: Any) -> Any:
        last_error: PipelineError | None = None
        for attempt in range(self.retries + 1):
            try:
                return self._client.complete_json(**kwargs)
            except PipelineError as exc:
                last_error = exc
                message = str(exc).casefold()
                is_structured_error = (
                    "structured output" in message or "json object" in message
                )
                if not is_structured_error or attempt == self.retries:
                    raise
        raise last_error or PipelineError("Structured output retry failed")


def _question_context(base: str, follow_ups: Sequence[str]) -> str:
    if not follow_ups:
        return base
    numbered = "\n".join(f"{index}. {text}" for index, text in enumerate(follow_ups, 1))
    return f"{base.rstrip()}\n\nУточняющие вопросы:\n{numbered}"


def _follow_ups_from_context(question: str) -> list[str]:
    marker = "\n\nУточняющие вопросы:\n"
    if marker not in question:
        return []
    return [
        line.split(". ", 1)[-1].strip()
        for line in question.split(marker, 1)[1].splitlines()
        if line.strip()
    ]


def _seeded_questions(paths: Sequence[str | Path]) -> dict[str, str]:
    seeded: dict[str, str] = {}
    for path in paths:
        seeded.update(
            {
                str(item["sample_id"]): str(item["question"])
                for item in read_jsonl(path)
                if item.get("sample_id") and item.get("question")
            }
        )
    return seeded


def build_arm_records(
    gold_records: Sequence[dict[str, Any]],
    arm: Arm,
    generator: QuestionVariantGenerator | None,
    *,
    seeded_questions: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []
    for source in gold_records:
        record = copy.deepcopy(source)
        original = str(source["question"])
        generated_question = original
        follow_ups: list[str] = []
        generation: dict[str, Any] | None = None
        if arm.max_question_words is not None:
            if generator is None:
                raise PipelineError("A question generator is required for non-baseline arms")
            generated_question, generation = generator.shorten(
                question_id=str(source["question_id"]),
                question=original,
                rubric=source["rubric"],
                max_words=arm.max_question_words,
            )
        elif arm.follow_up_count:
            seeded = (seeded_questions or {}).get(str(source["sample_id"]))
            seeded_follow_ups = _follow_ups_from_context(seeded or "")
            if len(seeded_follow_ups) == arm.follow_up_count:
                follow_ups = seeded_follow_ups
                generated_question = str(seeded)
                generation = {"seeded": True}
            else:
                if generator is None:
                    raise PipelineError("A question generator is required for non-baseline arms")
                follow_ups, generation = generator.follow_ups(
                    question_id=str(source["question_id"]),
                    question=original,
                    answer=str(source["answer"]),
                    rubric=source["rubric"],
                    count=arm.follow_up_count,
                )
                generated_question = _question_context(original, follow_ups)
        record["question"] = generated_question
        records.append(record)
        manifest.append(
            {
                "sample_id": source["sample_id"],
                "question_id": source["question_id"],
                "arm": arm.name,
                "original_question": original,
                "question": generated_question,
                "follow_ups": follow_ups,
                "generation": generation,
            }
        )
    return records, manifest


def _matching_predictions(
    path: str | Path,
    records: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return []
    expected = {str(item["sample_id"]): str(item["question"]) for item in records}
    matches: dict[str, dict[str, Any]] = {}
    for item in read_jsonl(source):
        sample_id = str(item.get("sample_id", ""))
        if expected.get(sample_id) == str(item.get("question", "")):
            matches[sample_id] = item
    return [matches[item["sample_id"]] for item in records if item["sample_id"] in matches]


def evaluate_records(
    records: Sequence[dict[str, Any]],
    client: OpenRouterClient,
    output_path: str | Path,
    *,
    seed_predictions: str | Path | None = None,
    resume: bool = True,
) -> list[dict[str, Any]]:
    predictions = _matching_predictions(output_path, records) if resume else []
    if seed_predictions is not None:
        seeded = _matching_predictions(seed_predictions, records)
        by_id = {str(item["sample_id"]): item for item in [*predictions, *seeded]}
        predictions = [
            by_id[item["sample_id"]]
            for item in records
            if item["sample_id"] in by_id
        ]
    completed = {str(item["sample_id"]) for item in predictions}
    write_jsonl(output_path, predictions)
    for index, record in enumerate(records, start=1):
        if str(record["sample_id"]) in completed:
            continue
        print(
            f"[{index}/{len(records)}] {record['sample_id']}",
            file=sys.stderr,
            flush=True,
        )
        predictions.append(evaluate_answer(record, client))
        write_jsonl(output_path, predictions)
    by_id = {str(item["sample_id"]): item for item in predictions}
    return [by_id[str(item["sample_id"])] for item in records]


def _metric(report: dict[str, Any], path: tuple[str, str]) -> float:
    return float(report[path[0]][path[1]])


def compare_reports(
    reports: dict[str, dict[str, Any]],
    arms: Sequence[Arm],
) -> dict[str, Any]:
    baseline = reports["baseline"]
    rows: list[dict[str, Any]] = []
    for arm in arms:
        report = reports[arm.name]
        values = {name: _metric(report, path) for name, path in METRICS.items()}
        deltas = {
            name: values[name] - _metric(baseline, path)
            for name, path in METRICS.items()
        }
        rows.append({"arm": asdict(arm), "metrics": values, "delta_vs_baseline": deltas})
    return {
        "experiment_version": EXPERIMENT_VERSION,
        "primary_metric": PRIMARY_METRIC,
        "samples": baseline["samples"],
        "arms": rows,
        "interpretation_limit": (
            "The same answers are used in every arm. Deltas measure evaluator sensitivity "
            "to question context, not information gained from a candidate's follow-up answer."
        ),
    }


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def paired_primary_effects(
    gold_records: Sequence[dict[str, Any]],
    predictions_by_arm: dict[str, Sequence[dict[str, Any]]],
    arms: Sequence[Arm],
    *,
    bootstrap_samples: int = 10_000,
) -> list[dict[str, Any]]:
    baseline_predictions = {
        str(item["sample_id"]): item for item in predictions_by_arm["baseline"]
    }
    baseline_scores: dict[str, float] = {}
    for record in gold_records:
        sample_id = str(record["sample_id"])
        report = validate([record], [baseline_predictions[sample_id]])
        baseline_scores[sample_id] = _metric(
            report,
            ("end_to_end_relaxed_span_and_label", "f1"),
        )
    rng = random.Random(0)
    results: list[dict[str, Any]] = []
    for arm in arms:
        predictions = {
            str(item["sample_id"]): item for item in predictions_by_arm[arm.name]
        }
        deltas: list[float] = []
        for record in gold_records:
            sample_id = str(record["sample_id"])
            score = _metric(
                validate([record], [predictions[sample_id]]),
                ("end_to_end_relaxed_span_and_label", "f1"),
            )
            deltas.append(score - baseline_scores[sample_id])
        bootstrapped = sorted(
            sum(rng.choice(deltas) for _ in deltas) / len(deltas)
            for _ in range(bootstrap_samples)
        )
        epsilon = 1e-12
        results.append(
            {
                "arm": arm.name,
                "mean_paired_delta": sum(deltas) / len(deltas),
                "bootstrap_95_ci": [
                    _percentile(bootstrapped, 0.025),
                    _percentile(bootstrapped, 0.975),
                ],
                "wins": sum(delta > epsilon for delta in deltas),
                "ties": sum(abs(delta) <= epsilon for delta in deltas),
                "losses": sum(delta < -epsilon for delta in deltas),
            }
        )
    return results


def render_comparison(summary: dict[str, Any]) -> str:
    excluded = summary.get("excluded_samples", [])
    lines = [
        "# Question-context ablation",
        "",
        f"Samples: **{summary['samples']}**. Primary metric: "
        f"`{summary['primary_metric']}`.",
        f"Excluded sample ids: `{', '.join(excluded)}`." if excluded else "",
        "",
        "| Arm | Max base words | Follow-ups | Span+label F1 | Δ | Missing F1 | Δ |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["arms"]:
        arm = row["arm"]
        values = row["metrics"]
        deltas = row["delta_vs_baseline"]
        lines.append(
            "| {name} | {words} | {followups} | {score:.3f} | {delta:+.3f} | "
            "{missing:.3f} | {missing_delta:+.3f} |".format(
                name=arm["name"],
                words=arm["max_question_words"] or "—",
                followups=arm["follow_up_count"],
                score=values["span_and_label_f1"],
                delta=deltas["span_and_label_f1"],
                missing=values["missing_requirements_f1"],
                missing_delta=deltas["missing_requirements_f1"],
            )
        )
    lines.extend(
        [
            "",
            "## Paired primary-metric effect",
            "",
            "| Arm | Mean per-sample Δ | Bootstrap 95% CI | Wins / ties / losses |",
            "|---|---:|---:|---:|",
        ]
    )
    for effect in summary.get("paired_primary_effects", []):
        interval = effect["bootstrap_95_ci"]
        lines.append(
            f"| {effect['arm']} | {effect['mean_paired_delta']:+.3f} | "
            f"[{interval[0]:+.3f}, {interval[1]:+.3f}] | "
            f"{effect['wins']} / {effect['ties']} / {effect['losses']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            summary["interpretation_limit"],
            "",
            "A causal information-gain result requires gold conversations containing the "
            "candidate's actual answer to each follow-up.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def summarize_existing(
    *,
    arms: Sequence[Arm],
    gold_records: Sequence[dict[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    reports: dict[str, dict[str, Any]] = {}
    included_arms: list[Arm] = []
    skipped_arms: list[dict[str, Any]] = []
    manifests: list[dict[str, Any]] = []
    predictions_by_arm: dict[str, Sequence[dict[str, Any]]] = {}
    expected_ids = [str(item["sample_id"]) for item in gold_records]
    for arm in arms:
        predictions_path = output_dir / arm.name / "predictions.jsonl"
        predictions = read_jsonl(predictions_path) if predictions_path.exists() else []
        by_id = {str(item.get("sample_id", "")): item for item in predictions}
        missing = [sample_id for sample_id in expected_ids if sample_id not in by_id]
        if missing:
            skipped_arms.append(
                {"name": arm.name, "reason": "incomplete", "missing_samples": missing}
            )
            continue
        selected = [by_id[sample_id] for sample_id in expected_ids]
        records: list[dict[str, Any]] = []
        for source, prediction in zip(gold_records, selected, strict=True):
            record = copy.deepcopy(source)
            question = str(prediction.get("question", source["question"]))
            record["question"] = question
            records.append(record)
            marker = "\n\nУточняющие вопросы:\n"
            follow_ups = (
                [line.split(". ", 1)[-1] for line in question.split(marker, 1)[1].splitlines()]
                if marker in question
                else []
            )
            manifests.append(
                {
                    "sample_id": source["sample_id"],
                    "question_id": source["question_id"],
                    "arm": arm.name,
                    "original_question": source["question"],
                    "question": question,
                    "follow_ups": follow_ups,
                    "generation": None,
                }
            )
        report = validate(records, selected)
        reports[arm.name] = report
        predictions_by_arm[arm.name] = selected
        included_arms.append(arm)
        arm_dir = output_dir / arm.name
        _write_json(arm_dir / "report.json", report)
        (arm_dir / "report.md").write_text(render_report(report), encoding="utf-8")
    if "baseline" not in reports:
        raise PipelineError("A complete baseline checkpoint is required for --summarize-only")
    summary = compare_reports(reports, included_arms)
    summary["paired_primary_effects"] = paired_primary_effects(
        gold_records,
        predictions_by_arm,
        included_arms,
    )
    summary["skipped_arms"] = skipped_arms
    summary["source"] = "existing checkpoints; no model calls"
    write_jsonl(output_dir / "question_manifest.jsonl", manifests)
    _write_json(output_dir / "summary.json", summary)
    (output_dir / "summary.md").write_text(render_comparison(summary), encoding="utf-8")
    return summary


def _build_client(args: argparse.Namespace) -> RetryingStructuredClient:
    values = {**load_env(args.env), **os.environ}
    fallback = args.fallback_model.strip() or None
    return RetryingStructuredClient(
        OpenRouterClient(
            api_key=values.get("OPENAI_API_KEY", ""),
            proxy_url=values.get("OPENAI_PROXY_URL", ""),
            model=args.model or values.get("OPENROUTER_MODEL", DEFAULT_MODEL),
            fallback_model=fallback,
            cache_dir=Path(args.output_dir) / "cache",
            refresh=args.refresh,
        ),
        retries=args.structured_retries,
    )


def _parser() -> argparse.ArgumentParser:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", default=str(here / "data" / "gold.jsonl"))
    parser.add_argument("--arms", default=str(here / "arms.json"))
    parser.add_argument("--output-dir", default=str(here / "artifacts" / "ablation"))
    parser.add_argument("--env", default=str(here / ".env"))
    parser.add_argument(
        "--model",
        help=f"Pinned evaluator/generator model (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--fallback-model",
        default="",
        help="Optional fallback; empty by default to keep the model fixed across arms",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=8,
        help="Evaluate the first N gold samples (default: 8; use 30 explicitly for full run)",
    )
    parser.add_argument(
        "--exclude-sample",
        action="append",
        default=[],
        help="Exclude a sample id from every arm (repeatable)",
    )
    parser.add_argument(
        "--baseline-predictions",
        help="Optional compatible predictions JSONL used to seed the baseline arm",
    )
    parser.add_argument("--refresh", action="store_true", help="Ignore the LLM response cache")
    parser.add_argument("--no-resume", action="store_true", help="Ignore arm checkpoints")
    parser.add_argument(
        "--summarize-only",
        action="store_true",
        help="Build reports from complete checkpoints without any model calls",
    )
    parser.add_argument(
        "--generate-only",
        action="store_true",
        help="Generate question manifests without evaluating answers",
    )
    parser.add_argument(
        "--source-only",
        action="store_true",
        help="Use only real source-candidate records from the gold dataset",
    )
    parser.add_argument(
        "--seed-question-predictions",
        action="append",
        default=[],
        help=(
            "Reuse question contexts from a predictions JSONL before generating "
            "missing follow-ups (repeatable)"
        ),
    )
    parser.add_argument(
        "--structured-retries",
        type=int,
        default=1,
        help="Retries for malformed JSON from the same pinned model (default: 1)",
    )
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.structured_retries < 0:
        raise PipelineError("--structured-retries cannot be negative")
    arms = load_arms(args.arms)
    gold_records = read_jsonl(args.gold)
    validate_gold(gold_records)
    if args.limit is not None:
        if args.limit < 1:
            raise PipelineError("--limit must be at least 1")
        gold_records = gold_records[: args.limit]
    excluded = set(args.exclude_sample)
    gold_records = [
        item for item in gold_records if str(item["sample_id"]) not in excluded
    ]
    if args.source_only:
        gold_records = [
            item for item in gold_records if "-source-c" in str(item["sample_id"])
        ]
    if not gold_records:
        raise PipelineError("No gold samples remain after filtering")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.summarize_only:
        summary = summarize_existing(
            arms=arms,
            gold_records=gold_records,
            output_dir=output_dir,
        )
        summary["excluded_samples"] = sorted(excluded)
        _write_json(output_dir / "summary.json", summary)
        (output_dir / "summary.md").write_text(render_comparison(summary), encoding="utf-8")
        return summary
    client = _build_client(args)
    generator = QuestionVariantGenerator(client)
    seeded_questions = _seeded_questions(args.seed_question_predictions)
    if args.generate_only:
        manifests: list[dict[str, Any]] = []
        for arm in arms:
            _records, manifest = build_arm_records(
                gold_records,
                arm,
                generator,
                seeded_questions=seeded_questions if arm.follow_up_count else None,
            )
            manifests.extend(manifest)
        target = output_dir / "generated_question_manifest.jsonl"
        write_jsonl(target, manifests)
        return {
            "experiment_version": EXPERIMENT_VERSION,
            "mode": "generate_only",
            "samples": len(gold_records),
            "arms": [asdict(arm) for arm in arms],
            "manifest": str(target),
            "model": client.model,
            "fallback_model": client.fallback_model,
        }
    reports: dict[str, dict[str, Any]] = {}
    predictions_by_arm: dict[str, Sequence[dict[str, Any]]] = {}
    manifests: list[dict[str, Any]] = []
    for arm in arms:
        print(f"=== {arm.name} ===", file=sys.stderr, flush=True)
        records, manifest = build_arm_records(
            gold_records,
            arm,
            generator,
            seeded_questions=seeded_questions if arm.follow_up_count else None,
        )
        manifests.extend(manifest)
        arm_dir = output_dir / arm.name
        predictions = evaluate_records(
            records,
            client,
            arm_dir / "predictions.jsonl",
            seed_predictions=args.baseline_predictions if arm.name == "baseline" else None,
            resume=not args.no_resume and not args.refresh,
        )
        report = validate(records, predictions)
        reports[arm.name] = report
        predictions_by_arm[arm.name] = predictions
        _write_json(arm_dir / "report.json", report)
        (arm_dir / "report.md").write_text(render_report(report), encoding="utf-8")
    write_jsonl(output_dir / "question_manifest.jsonl", manifests)
    summary = compare_reports(reports, arms)
    summary["paired_primary_effects"] = paired_primary_effects(
        gold_records,
        predictions_by_arm,
        arms,
    )
    summary["model"] = client.model
    summary["fallback_model"] = client.fallback_model
    summary["arms_config"] = [asdict(arm) for arm in arms]
    summary["excluded_samples"] = sorted(excluded)
    _write_json(output_dir / "summary.json", summary)
    (output_dir / "summary.md").write_text(render_comparison(summary), encoding="utf-8")
    return summary


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        summary = run(args)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except PipelineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
