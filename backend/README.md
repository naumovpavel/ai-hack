# Signal interview API

FastAPI backend for the local end-to-end hiring interview demo. The active
workflow persists structured state in PostgreSQL, stores original documents and
interview media in S3-compatible MinIO, and sends model calls to OpenRouter.

The earlier stateless endpoints remain available: question generation uses
GPT-5.6 Luna through OpenRouter with structured output, technical answer
evaluation uses the same proxy-backed client, and their batch transcription
endpoint keeps the local faster-whisper adapter.

The application deliberately does not make an autonomous hiring decision. It
produces job-related evidence and keeps the AI recommendation locked until the
reviewer has opened every analysis item for at least the configured review time.

## Run the complete stack

Use the repository-level Compose configuration:

```bash
cd ..
cp .env.example .env
# Fill PostgreSQL, MinIO and a rotated OpenRouter credential.
docker compose up --build
```

The API is available at `http://localhost:8000`; interactive documentation is at
`http://localhost:8000/docs`.

## Workflow API

The `/api/v1` workflow covers:

- demo user sessions (`/dev/users`, `/dev/session`, `/session`);
- positions with vacancy uploads and interview constraints (`/positions`);
- resume upload and generated question drafts (`/positions/{id}/candidates`);
- question editing, approval and candidate invite URLs;
- isolated practice-question sets that use a broad role family, grade, and
  generalized topic categories, and never
  receive the vacancy text, resume, requirements, seed questions or real
  interview questions;
- candidate-private persisted practice recordings, analysis and self-review;
- owner-only deletion of candidates, interview plans and vacancies with dependent
  records and invitation revocation;
- candidate briefing, consent, TTS, answer media upload, STT and adaptive
  follow-up questions;
- interview completion and structured analysis;
- private media/transcript download links;
- per-question assessment and an initial human judgment before the overall AI
  recommendation is revealed, with a server-enforced decision gate;
- the candidate-facing recruiter outcome, without the internal reason.

Question generation, follow-up selection and analysis use structured OpenRouter
chat responses. Transcription uses OpenRouter's speech-to-text endpoint and
question audio uses its text-to-speech endpoint. Model names are configured with
`OPENROUTER_CHAT_MODEL`, `OPENROUTER_STT_MODEL` and `OPENROUTER_TTS_MODEL`.

Legacy stateless endpoints for the earlier prototype remain available for
compatibility. The React product flow does not call them.

## Legacy stateless API

Set both `OPENAI_API_KEY` and `OPENAI_PROXY_URL` to enable OpenRouter-backed
question generation and answer evaluation. The client requires the proxy and
never falls back to a direct connection. Question generation uses
`openai/gpt-5.6-luna` by default and is configured with
`QUESTION_GENERATION_MODEL`.

## Technical answer evaluation

Prompt version `interview-technical-errors-v8` adds coverage-only rules selected
in a separate retrospective Luna eval. Extraction and factual judging are
unchanged. See [results, provenance and limitations](docs/luna-coverage-v8.md).
These measurements are not a new evaluation of this backend or its separate
product-workflow analyzer.

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

Requires Python 3.12:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
PYTHONDONTWRITEBYTECODE=1 pytest
ruff check src tests
```

The workflow integration test exercises the complete HR → candidate → HR →
candidate state machine with SQLite and deterministic in-memory test doubles. It
does not spend OpenRouter credits or require Docker. PostgreSQL and MinIO are used
by the Compose runtime.
