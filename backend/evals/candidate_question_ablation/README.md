# Ablation уточняющих и коротких вопросов

Каталог содержит eval-пайплайн из `demo.zip` (`interview_pipeline.py`), его 30
gold-примеров и надстройку `question_ablation.py`. Расчёт метрик и исходные
evaluator prompts не менялись; в клиент добавлен только отдельный лимит в 160
output-токенов для генерации вариантов вопросов.

Надстройка сравнивает несколько arms при одинаковых ответах, gold-разметке,
rubric, evaluator prompt и модели:

- `baseline` — исходный вопрос;
- `short_30_words`, `short_20_words` — меняется только лимит слов основного вопроса;
- `follow_up_1` — добавляется один уточняющий вопрос.

Конфигурация валидируется как one-factor-at-a-time: arm не может одновременно
сокращать основной вопрос и добавлять follow-up. Модель фиксируется, а fallback
по умолчанию выключен, чтобы смена провайдера/модели не смешивалась с эффектом
формулировки.

## Что измеряет эксперимент

Во всех arms используется один и тот же ответ кандидата. Поэтому дельты показывают
чувствительность evaluator-а к контексту вопроса. Они **не доказывают**, что кандидат
после уточнения даст больше полезной информации. Для такого вывода нужен отдельный
gold-набор диалогов с реальными ответами на follow-up.

Основная метрика — `end_to_end_relaxed_span_and_label.f1`. Дополнительно сравниваются
exact/relaxed span F1, macro-F1 категорий и F1 отсутствующих требований.

## Запуск

Требуются `OPENAI_API_KEY` и обязательный `OPENAI_PROXY_URL` в `.env`. Секреты,
кэш и результаты игнорируются Git.

```powershell
cd backend\evals\candidate_question_ablation
python -m pip install -r requirements.txt
python question_ablation.py --env C:\path\to\.env
```

Быстрый частичный прогон и переиспользование совместимых baseline predictions:

```powershell
python question_ablation.py `
  --env C:\path\to\.env `
  --limit 8 `
  --baseline-predictions C:\path\to\demo\artifacts\predictions.jsonl
```

Результаты сохраняются в `artifacts/ablation/`: отдельный отчёт для каждого arm,
`question_manifest.jsonl` с фактическими формулировками и сводные `summary.json` /
`summary.md`. Прогон возобновляется с последнего целого prediction; `--refresh`
игнорирует LLM-кэш, а `--no-resume` — checkpoints. Невалидный structured JSON
повторяется один раз на той же закреплённой модели; лимит настраивается через
`--structured-retries` и не включает model fallback.

По умолчанию берутся первые 8 gold-примеров. Полные 30 запускаются только явно
через `--limit 30`. Сводку по уже готовым checkpoints можно пересчитать совсем
без LLM-вызовов:

```powershell
python question_ablation.py --summarize-only --output-dir artifacts\ablation_8
```

Экономная генерация только формулировок для реальных интервью может переиспользовать
уже готовые question contexts. Так модель вызывается лишь для отсутствующих записей:

```powershell
python question_ablation.py `
  --arms arms_followup_only.json `
  --limit 30 --source-only --generate-only `
  --seed-question-predictions artifacts\ablation_8\follow_up_1\predictions.jsonl
```

Если импортированный baseline содержит единичный fallback на другую модель,
такой пример следует убрать из всех arms через повторяемый флаг
`--exclude-sample SAMPLE_ID`, а причину зафиксировать в отчёте.

## Тесты

```powershell
python -m unittest discover -s tests -v
```

Тесты не обращаются к сети и не расходуют токены.
