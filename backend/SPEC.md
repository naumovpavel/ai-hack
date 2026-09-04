# AI Interview Backend MVP

> Historical specification for the original stateless/local-model prototype.
> The persistent OpenRouter workflow is documented in `README.md` and the root
> `README.md`.

## Goal

Build a small FastAPI backend for an AI technical interview prototype.

All AI inference runs locally. The backend must not require paid external AI
APIs or API keys.

The current MVP contains:

1. Initial interview question generation from context documents.
2. Audio transcription.

The architecture must allow us to add realtime transcription and adaptive
follow-up questions later without rewriting existing business logic.

## Tech stack

- Python 3.12
- FastAPI
- Pydantic v2
- Uvicorn
- OpenRouter API
- GPT-5.6 Luna for question generation
- faster-whisper for local transcription
- pytest
- pydantic-settings
- python-multipart
- pypdf
- python-docx
- ruff

Do not introduce:
- databases;
- Redis;
- Celery;
- Kafka;
- LangChain;
- vector databases.

## Model inference

Question generation runs through OpenRouter using structured JSON output.

Default question-generation configuration:

- `QUESTION_GENERATION_MODEL=openai/gpt-5.6-luna`;
- `OPENROUTER_TIMEOUT_SECONDS=90`;
- `OPENROUTER_MAX_RETRIES=1`.

The model name, credentials and proxy URL must come from configuration. Routes
and services must not hardcode them.

Transcription runs in-process using faster-whisper and CTranslate2.

Default transcription configuration prioritizes compatibility with developer
machines:

- `WHISPER_MODEL_SIZE=small` (multilingual model);
- `WHISPER_DEVICE=cpu`;
- `WHISPER_COMPUTE_TYPE=int8`.

The model, device and compute type must come from configuration. A machine with
a compatible NVIDIA GPU may instead use `turbo`, `cuda` and `float16` without
changing API or service code.

Models may be downloaded during explicit local setup. Runtime inference must
not call a hosted inference API.

## Endpoint 1

POST /api/v1/questions/generate

multipart/form-data:

- `cv`: optional PDF, DOCX, or UTF-8 TXT file;
- `vacancy`: optional PDF, DOCX, or UTF-8 TXT file;
- `requirements`: optional PDF, DOCX, or UTF-8 TXT file;
- `question_count`: required integer;
- `core_question_count`: required integer;
- `language`: required language code.

At least one document is required. Vacancy or requirements is required when
`core_question_count` is greater than zero.

The API extracts document text for the current request and does not persist the
uploaded files or extracted text. Scanned PDFs without a text layer and legacy
DOC files are not supported in this MVP.

The question generator creates:
- core questions based only on vacancy and requirements;
- personalized questions based on vacancy, requirements and CV.

Every question has:
- id;
- type: core | personalized;
- text;
- competency;
- source_file_ids.

CV claims must not be treated as confirmed facts.
Questions must not invent candidate experience.

## Endpoint 2

POST /api/v1/transcriptions

multipart/form-data:

- audio: required
- language: optional
- interview_id: optional
- question_id: optional

Response:

{
  "text": "...",
  "is_final": true,
  "question_id": "...",
  "meta": {
    "provider": "faster-whisper"
  }
}

## Endpoint 3

GET /health

Returns HTTP 200.

## Architecture

Use separate layers:

API routes
    ↓
services
    ↓
provider interfaces
    ↓
provider implementations

Current implementations:

- OpenRouterQuestionGenerationProvider;
- FasterWhisperTranscriptionProvider.

Required abstractions:

QuestionGenerationProvider
TranscriptionProvider
DocumentTextExtractor

Routes must not call OpenRouter, faster-whisper or another provider SDK directly.

Question prompts must live outside route code.

OpenRouter calls must have timeouts, retries and graceful error handling.
Local transcription failures must be translated to application errors.
CPU/GPU-bound transcription must not block the asyncio event loop.

Use structured model output for question generation.

Do not hardcode provider model names in routes or services.
Load all model names and inference settings from environment variables.

## Realtime readiness

Do NOT implement realtime/WebSockets yet.

However, TranscriptionProvider and QuestionGenerationService must not depend
on HTTP request objects, so they can later be reused from a WebSocket handler.

Future architecture should support:

audio chunks
→ streaming transcription
→ final answer
→ follow-up generation.

The batch TranscriptionProvider must remain stable. Realtime transcription
should later use a separate StreamingTranscriptionProvider that accepts audio
chunks and emits partial/final transcription events.

Whisper-style models are not natively realtime. A future streaming adapter may
use faster-whisper with windowing/VAD or another local streaming ASR engine
without changing the current HTTP route or batch service.

## Testing

Unit/API tests must not call OpenRouter, load a real Whisper model or download
model weights.

Mock provider interfaces.

Provider adapter tests must mock the OpenRouter client and faster-whisper model.

Tests required for:
- health endpoint;
- successful question generation;
- invalid question_count;
- unsupported, empty, and oversized uploaded documents;
- successful transcription;
- invalid/empty audio;
- provider error.

## Code quality

- async where external IO is involved;
- type hints;
- small functions;
- no unnecessary abstractions;
- no provider clients or models created inside route functions;
- heavy local models are created once during application startup and reused;
- configuration through environment variables.

Add README with local run instructions and curl examples.
