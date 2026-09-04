# AI Interview Backend MVP

Minimal FastAPI backend for question generation, audio transcription, and technical
answer evaluation.
Question generation uses GPT-5.6 Luna through OpenRouter with structured output.
Audio transcription uses a local faster-whisper model.

## Local setup

Requires Python 3.12.

```bash
python -m venv .venv
.venv/Scripts/activate
python -m pip install -e ".[dev]"
copy .env.example .env
uvicorn interview_api.main:app --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Set both `OPENAI_API_KEY` and `OPENAI_PROXY_URL` to enable OpenRouter-backed
question generation and answer evaluation. The client requires the proxy and
never falls back to a direct connection. Question generation uses
`openai/gpt-5.6-luna` by default and is configured with
`QUESTION_GENERATION_MODEL`.

## Technical answer evaluation

Luna (`openai/gpt-5.6-luna`) is the primary model; DeepSeek V4 Flash is used only
when the primary model is unavailable. Both model names are configurable through
`OPENROUTER_MODEL` and `OPENROUTER_FALLBACK_MODEL`.

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/interviews/evaluate-answer" `
  -H "Content-Type: application/json" `
  -d '{"question":"How does MVCC work?","answer":"MVCC locks every row."}'
```

The response contains only technically incorrect claims and low-confidence claims.
Confidently correct claims are omitted. Labels are `неправильный` and
`рекомендуется проверка`; the latter is based only on judge uncertainty, not on
personal experience or unavailable biographical context. Every answer annotation
is an exact `[start, end)` span. Concrete question parts omitted from the answer are
returned separately in `missing_aspects` as spans into the question.

Question generation accepts PDF, DOCX, or UTF-8 TXT files directly and does not
persist them:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/v1/questions/generate" `
  -F "cv=@C:\path\resume.pdf" `
  -F "vacancy=@C:\path\vacancy.docx" `
  -F "requirements=@C:\path\requirements.txt" `
  -F "question_count=6" `
  -F "core_question_count=3" `
  -F "language=ru"
```

At least one document is required. Scanned PDFs without a text layer and legacy
`.doc` files are not supported. Upload and extracted-text limits are configured
with `MAX_DOCUMENT_BYTES` and `MAX_DOCUMENT_CHARACTERS`.

The first application startup downloads the configured Whisper model. The default
CPU-friendly configuration is `small`, `cpu`, and `int8`; change the `WHISPER_*`
settings in `.env` if needed. Tests inject fake providers and never call
OpenRouter, download models, or use an external API.

Transcription request (PowerShell):

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/transcriptions `
  -F "audio=@answer.webm" `
  -F "language=ru" `
  -F "interview_id=interview-1" `
  -F "question_id=question-1"
```

## Tests

```bash
pytest
ruff check .
```
