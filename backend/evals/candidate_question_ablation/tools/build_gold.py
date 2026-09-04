"""Build the fixed reviewed gold corpus from source transcripts and LLM drafts.

The annotation rules below are deliberately separate from the production LLM
prompts.  They turn reviewed clauses into exact offsets and keep rebuilding the
JSONL deterministic when source formatting changes.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from interview_pipeline import LABELS, write_jsonl  # noqa: E402


SOURCE_QUESTIONS = [
    "Расскажите почему вы сейчас находитесь в поиске работы и что для себя ищите? Каким проектом и какими задачами хотелось бы заниматься?",
    "Расскажите про свой продакшн-сервис на Python с очередью — Kafka или RabbitMQ. Какие библиотеки, как добивались, чтобы сообщение не потерялось и не обработалось дважды, и что делали с необработанными сообщениями?",
    "Как вы загружали большие объёмы данных в PostgreSQL? Назовите объёмы, как была устроена загрузка и как находили причину медленных запросов?",
    "Расскажите про CI/CD-пайплайн для Python-сервиса в контейнерах, который настраивали сами. Что делал пайплайн, как собирали Docker-образ, как деплоили и откатывались?",
    "Когда выбираете асинхронный код, а когда синхронный? На примере из своего проекта. И что будет, если внутри асинхронного кода вызвать блокирующую функцию?",
    "Расскажите как используете ИИ в своей работе?",
]


RUBRIC_KEYWORDS = {
    "q01_motivation": {
        "q01_reason": ("поиск", "увол", "проект заверш", "реорганизац", "росту", "финанс"),
        "q01_project": ("проект", "домен", "команд"),
        "q01_tasks": ("задач", "интеграц", "python", "backend", "бэкенд", "api"),
        "q01_growth": ("развив", "рост", "учиться", "лидер"),
    },
    "q02_messaging": {
        "q02_stack": ("kafka", "rabbit", "aiokafka", "pika", "faststream", "confluent"),
        "q02_delivery": ("ack", "offset", "outbox", "достав", "потер"),
        "q02_idempotency": ("дубл", "id", "guid", "идемпот", "уникаль"),
        "q02_failures": ("retry", "dlq", "dead-letter", "ошиб", "необработ", "ретр"),
    },
    "q03_postgresql": {
        "q03_scale": ("гб", "млн", "объём", "час", "секунд", "строк"),
        "q03_load": ("copy", "insert", "batch", "батч", "staging", "on conflict", "загруз"),
        "q03_diagnosis": ("explain", "индекс", "статист", "work_mem", "scan", "запрос"),
        "q03_locking": ("lock", "блокир", "лоч"),
    },
    "q04_cicd": {
        "q04_ci": ("тест", "линтер", "ci", "job", "джоб", "security"),
        "q04_image": ("docker", "образ", "registry", "sha", "тег"),
        "q04_deploy": ("деплой", "kubernetes", "helm", "стенд", "rollout"),
        "q04_rollback": ("откат", "rollback", "revert", "предыдущ"),
    },
    "q05_async": {
        "q05_choice": ("i/o", "io ", "cpu", "синхрон", "асинхрон"),
        "q05_loop": ("event loop", "await", "корутин", "событийн"),
        "q05_blocking": ("блокир", "time.sleep", "requests", "executor"),
        "q05_example": ("проект", "сервис", "бот", "приложен"),
    },
    "q06_ai": {
        "q06_cases": ("тест", "код", "документ", "проект", "sql", "анализ"),
        "q06_verification": ("провер", "разбира", "пониман", "review", "pytest"),
        "q06_security": ("клиент", "соглас", "закрыт", "данн", "песочниц"),
        "q06_effect": ("быстр", "ускор", "эконом", "эффект"),
    },
    "q07_fastapi": {
        "q07_contract": ("pydantic", "схем", "валидац", "код", "верси"),
        "q07_idempotency": ("idempot", "идемпот", "ключ", "payload", "дубл"),
        "q07_load": ("нагруз", "пул", "timeout", "backpressure", "event loop", "rps"),
        "q07_observe": ("метрик", "prometheus", "tracing", "лог", "авторизац", "rate"),
    },
    "q08_cqrs": {
        "q08_store": ("event store", "событ", "version", "неизмен", "конкур"),
        "q08_projection": ("read model", "проекц", "eventual", "rabbit"),
        "q08_replay": ("replay", "повтор", "идемпот", "снапшот", "восстанов"),
        "q08_schema": ("схем", "upcast", "v2", "старые", "совмест"),
    },
    "q09_etl": {
        "q09_increment": ("watermark", "lsn", "cdc", "инкремент", "checkpoint", "окн"),
        "q09_transform": ("тип", "null", "контроль", "crc", "quarantine", "качест"),
        "q09_dedupe": ("дедуп", "replacing", "final", "дубл", "version"),
        "q09_restart": ("перезапуск", "staging", "partition", "повтор", "checkpoint"),
    },
    "q10_k8s": {
        "q10_probes": ("probe", "readiness", "liveness", "startup", "проб"),
        "q10_resources": ("requests", "limits", "hpa", "cpu", "ресурс"),
        "q10_rollout": ("rollout", "rolling", "canary", "образ", "surge", "откат"),
        "q10_monitoring": ("монитор", "latency", "errors", "slo", "алерт", "prometheus"),
    },
}


INCORRECT_MARKERS = {
    "q02_messaging-source-c1": (
        "дублирование там вроде настроено",
        "необработанные сообщения, но это решалось сразу же после включения",
    ),
    "q03_postgresql-source-c1": (
        "clickhouse, вертикальные базы",
        "надо в какую-то очередь ставить",
        "таблица лочится",
        "составные индексы, что вроде constraint",
        "префетчами докидывали",
    ),
    "q05_async-source-c1": (
        "это все быстрее делать через асинхронщину",
        "когда есть четкая последовательность",
        "django-нигде, там не было асинхронного",
        "на django нет",
    ),
    "q02_messaging-source-c2": ("таким образом, у нас сообщение обрабатывается единожды",),
    "q04_cicd-source-c2": ("сделать откат реквеста в самом gitlab",),
    "q05_async-source-c2": ("асинхронный код больше подходит, когда у нас нет io задачи",),
    "q07_fastapi-draft-3": (
        "фибоначеский префикс",
        "вернёт 422",
        "верну 200 наличному ранее ключу не проверив",
        "одном процессе и использовал синхронные",
        "драйвера sqlite",
        "логировали request body",
    ),
    "q08_cqrs-draft-3": (
        "редактируем документ на месте",
        "событие теряется",
        "не написали upcasters",
        "историю приходится вручную править",
    ),
    "q09_etl-draft-3": (
        "увеличивал watermark на час вперед",
        "гарантирует уникальность сразу",
        "не использовал final",
        "контрольные суммы не считал",
        "clickhouse сам проверяет целостность",
        "не сохранял checkpoint",
    ),
    "q10_k8s-draft-3": (
        "только requests, без limits",
        "алерты настрою на пороговые значения",
        "slo сложно считать",
    ),
}


CORRECT_MARKERS = (
    "outbox",
    "закоммитился offset",
    "explain",
    "manual commit",
    "коммитил offset после обработки",
    "уникальн",
    "retry",
    "dead-letter",
    "dlq",
    "батч",
    "copy",
    "статистик",
    "work_mem",
    "линтер",
    "тест",
    "предыдущий имейдж",
    "i/o",
    "event loop",
    "событийн",
    "блокируется событийный цикл",
    "asyncio.sleep",
    "согласован",
    "разбираюсь в нём целиком",
)


REVIEW_MARKERS = (
    "в прошлом",
    "в прошлом году",
    "на прошлом проекте",
    "в предыдущей",
    "я 10 лет",
    "мой последний проект",
    "у меня был опыт",
    "я так делал",
    "мы использовали",
    "я использовал",
    "я настраивал",
    "я загружал",
    "я сделал",
    "я сталкивался",
    "это сократило",
    "время упало",
    "экономия примерно",
    "с которой работал",
    "позволило сократить",
)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def source_answers() -> dict[str, str]:
    text = normalize((ROOT / "Вопросы_ответы_оценка.txt").read_text(encoding="utf-8-sig"))
    candidates = re.split(r"(?=\b[12] кандидат\b)", text)
    result: dict[str, str] = {}
    for candidate_number, block in enumerate((candidates[-2], candidates[-1]), start=1):
        transcript = block.rsplit("Оценка видеоинтервью", 1)[1]
        transcript = re.sub(r"^\s*\d+(?:\.\d+)?\s*", "", transcript)
        cursor = 0
        for index, question in enumerate(SOURCE_QUESTIONS):
            start = transcript.find(question, cursor)
            if start < 0:
                raise RuntimeError(f"Cannot find source question {index + 1} for candidate {candidate_number}")
            answer_start = start + len(question)
            if index + 1 < len(SOURCE_QUESTIONS):
                answer_end = transcript.find(SOURCE_QUESTIONS[index + 1], answer_start)
            else:
                answer_end = transcript.find("ВАРИАНТ ОБРАТНОЙ СВЯЗИ", answer_start)
            if answer_end < 0:
                raise RuntimeError(f"Cannot find answer end for candidate {candidate_number}, q{index + 1}")
            qid = f"q{index + 1:02d}_{['motivation','messaging','postgresql','cicd','async','ai'][index]}"
            result[f"{qid}-source-c{candidate_number}"] = transcript[answer_start:answer_end].strip()
            cursor = answer_end
    return result


def clause_spans(answer: str) -> list[tuple[int, int, str]]:
    """Create independently-defined gold clauses while preserving exact text."""
    spans: list[tuple[int, int, str]] = []
    for match in re.finditer(r"[^.!?]+(?:[.!?]+|$)", answer):
        start, end = match.span()
        while start < end and answer[start].isspace():
            start += 1
        while end > start and answer[end - 1].isspace():
            end -= 1
        if end - start < 15:
            continue
        # Very long speech-recognition sentences are split at commas into
        # readable 80–180 character clauses without altering the source.
        if end - start > 220:
            part_start = start
            comma_ends = [m.end() for m in re.finditer(r",\s+", answer[start:end])]
            for relative_end in comma_ends:
                cut = start + relative_end
                if cut - part_start >= 90:
                    piece_end = cut
                    while piece_end > part_start and answer[piece_end - 1].isspace():
                        piece_end -= 1
                    spans.append((part_start, piece_end, answer[part_start:piece_end]))
                    part_start = cut
            if end - part_start >= 15:
                spans.append((part_start, end, answer[part_start:end]))
        else:
            spans.append((start, end, answer[start:end]))
    return spans


def rubric_ids(qid: str, text: str) -> list[str]:
    lowered = text.lower()
    found = [
        rid
        for rid, keywords in RUBRIC_KEYWORDS[qid].items()
        if any(keyword in lowered for keyword in keywords)
    ]
    return found or [next(iter(RUBRIC_KEYWORDS[qid]))]


def is_review(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in REVIEW_MARKERS)


def label_clause(sample_id: str, quality: str, text: str) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in INCORRECT_MARKERS.get(sample_id, ())):
        return "неправильный"
    if quality == "incorrect":
        return "рекомендуется проверка" if is_review(text) else "неправильный"
    if quality == "correct":
        return "рекомендуется проверка" if is_review(text) else "правильный"
    if quality == "mixed":
        return "рекомендуется проверка" if is_review(text) else "правильный"
    if any(marker in lowered for marker in CORRECT_MARKERS):
        return "правильный"
    return "рекомендуется проверка"


def rationale(label: str) -> str:
    return {
        "правильный": "Формулировка релевантна и согласуется с reference context.",
        "неправильный": "Формулировка технически ошибочна, вводит в заблуждение или не отвечает критерию.",
        "рекомендуется проверка": "Это утверждение о личном опыте или результате нельзя подтвердить данным контекстом.",
    }[label]


def annotate(sample_id: str, qid: str, answer: str, quality: str) -> list[dict]:
    output = []
    for start, end, text in clause_spans(answer):
        label = label_clause(sample_id, quality, text)
        assert label in LABELS
        output.append(
            {
                "start": start,
                "end": end,
                "text": text,
                "label": label,
                "rationale": rationale(label),
                "rubric_ids": rubric_ids(qid, text),
            }
        )
    return output


def missing_requirements(qid: str, spans: list[dict], rubric: list[dict]) -> list[str]:
    covered = {
        rid
        for span in spans
        if span["label"] != "неправильный"
        for rid in span["rubric_ids"]
    }
    return [item["id"] for item in rubric if item.get("required") and item["id"] not in covered]


def main() -> None:
    questions = json.loads((ROOT / "data/questions.json").read_text(encoding="utf-8"))
    question_by_id = {item["question_id"]: item for item in questions}
    drafts = [
        json.loads(line)
        for line in (ROOT / "data/generated_draft.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    draft_by_id = {item["sample_id"]: item for item in drafts}
    chosen = {
        "q01_motivation-draft-2",
        "q02_messaging-draft-2",
        "q03_postgresql-draft-2",
        "q04_cicd-draft-1",
        "q05_async-draft-1",
        "q06_ai-draft-2",
        *(item["sample_id"] for item in drafts if item["question_id"].startswith(("q07_", "q08_", "q09_", "q10_"))),
    }
    source = source_answers()
    records: list[dict] = []
    for qid in question_by_id:
        question = question_by_id[qid]
        for candidate in (1, 2):
            source_id = f"{qid}-source-c{candidate}"
            if source_id not in source:
                continue
            answer = source[source_id]
            spans = annotate(source_id, qid, answer, "source")
            records.append(
                {
                    "sample_id": source_id,
                    "question_id": qid,
                    "question": question["question"],
                    "rubric": question["rubric"],
                    "answer": answer,
                    "provenance": "Вопросы_ответы_оценка.txt",
                    "intended_quality": "source",
                    "gold_spans": spans,
                    "gold_missing_requirements": missing_requirements(qid, spans, question["rubric"]),
                }
            )
        for draft in drafts:
            if draft["question_id"] != qid or draft["sample_id"] not in chosen:
                continue
            answer = normalize(draft["answer"])
            quality = draft["intended_quality"]
            spans = annotate(draft["sample_id"], qid, answer, quality)
            records.append(
                {
                    "sample_id": draft["sample_id"],
                    "question_id": qid,
                    "question": question["question"],
                    "rubric": question["rubric"],
                    "answer": answer,
                    "provenance": "synthetic-deepseek-v4-flash-reviewed",
                    "intended_quality": quality,
                    "gold_spans": spans,
                    "gold_missing_requirements": missing_requirements(qid, spans, question["rubric"]),
                }
            )
    if len(records) != 30:
        raise RuntimeError(f"Expected 30 records, got {len(records)}")
    write_jsonl(ROOT / "data/gold.jsonl", records)


if __name__ == "__main__":
    main()
