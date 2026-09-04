# Signal interview API

FastAPI backend for the local end-to-end hiring interview demo. The active
workflow persists structured state in PostgreSQL, stores original documents and
interview media in S3-compatible MinIO, and sends model calls to OpenRouter.

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
- candidate briefing, consent, TTS, answer media upload, STT and adaptive
  follow-up questions;
- interview completion and structured analysis;
- private media/transcript download links;
- per-item review heartbeats and the server-enforced decision gate;
- the candidate-facing recruiter outcome, without the internal reason.

Question generation, follow-up selection and analysis use structured OpenRouter
chat responses. Transcription uses OpenRouter's speech-to-text endpoint and
question audio uses its text-to-speech endpoint. Model names are configured with
`OPENROUTER_CHAT_MODEL`, `OPENROUTER_STT_MODEL` and `OPENROUTER_TTS_MODEL`.

Legacy stateless endpoints for the earlier prototype remain available for
compatibility. The React product flow does not call them.

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
