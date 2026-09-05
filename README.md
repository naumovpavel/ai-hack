# AI interview — local development

This repository contains a React/Vinext client and a FastAPI interview workflow.
The root Compose stack runs the application with PostgreSQL and private
S3-compatible storage in MinIO.

This stack is for local development only. It binds published ports to
`127.0.0.1` by default and does not provide production TLS, backups, secret
management, or hardened database/object-store identities.

## Security first

Do not paste API keys into source files, Compose files, issue trackers, or commit
history. Rotate any key that has already been shared in a chat before using it.
Only the ignored root `.env` file should contain local secrets.

## Start the local stack

Prerequisites: Docker Engine with Docker Compose v2.20+.

```bash
cp .env.example .env
```

Fill these required values in `.env`:

- `POSTGRES_PASSWORD`
- `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD`
- `S3_ACCESS_KEY` and `S3_SECRET_KEY`
- `OPENROUTER_API_KEY`

Chat, speech-to-text, and text-to-speech models are selected independently in
`.env`.

Validate and start:

```bash
docker compose config --quiet
docker compose up --build --detach
docker compose ps
make smoke
```

Local endpoints:

- UI: <http://localhost:3000>
- FastAPI docs: <http://localhost:8000/docs>
- FastAPI liveness: <http://localhost:8000/health>
- MinIO console: <http://localhost:9001>

Follow logs with `make logs`. Stop containers without deleting data with
`docker compose down`. To deliberately erase all local database and object data,
run `docker compose down --volumes`.

For this local MVP the API creates missing SQLAlchemy tables at startup.
The hiring workflow applies additive migrations for vacancy roles and interview
plan links while preserving existing records. Introduce versioned Alembic
migrations before relying on persistent environments across further schema changes.

## What the smoke check proves

`make smoke` verifies that PostgreSQL accepts connections, the workflow schema
and demo HR user exist, the private MinIO bucket exists, and both HTTP processes
answer inside their containers. After it passes, run the browser scenario below
to verify the product workflow as well.

## Manual end-to-end scenario

1. Open **Общий контекст** and upload the company's competency framework or other
   hiring documents. The backend normalizes each document through the LLM once,
   stores its text, and adapts the shared vacancy and interview templates.
2. Inspect **Шаблоны вакансий** using the role and grade filters. Generic IT
   templates are independent of the example company's materials. Edit company
   interview descriptions and evaluation criteria in **Шаблоны интервью**.
3. Create a vacancy by uploading a PDF/DOCX/TXT or selecting a template. Review
   and edit the title, role, grade, description, and requirements. Questions are
   generated only when an interview is added. Verify the option to skip adding
   an interview after vacancy creation.
4. Add an interview, select its type, and review its shared question pool as
   editable rows. Set the follow-up limit, personalized-question limit, and
   duration. These settings belong to the interview, allowing multiple
   interviews per vacancy.
5. Add a candidate from the interview overview. Upload a resume, review the
   profile and personalized question rows, then save. The invite link is copied
   and the recruiter stays on the interview overview. Check the global candidate
   search and its vacancy/interview labels.
6. Open the invite URL, grant camera and microphone permissions, and complete
   the interview. Questions are spoken through backend OpenRouter TTS; an
   explicit retry is offered if speech fails.
7. Return to the HR user and wait for analysis. Verify audio, video, transcript,
   evidence, and recommendation.
8. Open every required analysis item for at least ten active seconds. Confirm
   that an earlier decision attempt is rejected, then invite or reject the
   candidate. For rejection, enter an original internal reason and candidate
   feedback.
9. Switch back to the candidate and verify that the human decision and feedback
   are visible.

Use a short interview and small media samples for this smoke run. Model calls go
through OpenRouter; PostgreSQL, MinIO, the API, and the UI stay local.

The scripts in `backend/scripts/seed_*.py` are fixtures for
`interview_api.local_demo` only: they target its temporary SQLite database and
local file store. They do not seed the Compose PostgreSQL or MinIO services.

For development without Docker, the same API can use SQLite and private local
files. Set `OPENROUTER_API_KEY` in the ignored repository-root `.env`, then run
these commands in separate terminals:

```bash
backend/.venv/bin/uvicorn interview_api.local_demo:app --app-dir backend/src --host 127.0.0.1 --port 8000
pnpm --dir ui dev --port 3000
```

The local demo reads that `.env`; without a key it uses a deterministic test gateway.
`SIGNAL_LOCAL_DATABASE_URL` and `SIGNAL_LOCAL_MEDIA_ROOT` optionally select
isolated test storage. Existing defaults keep prior demo records available.

## Current backend checks

Use Python 3.12:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
python -m ruff check .
```

Keep fast unit tests isolated from external models. Integration tests should use
the Compose PostgreSQL and MinIO services, while browser E2E can replace model
calls with a deterministic fake gateway unless a separately labelled live-model
smoke test is intended.

## Current UI checks

Use Node.js 22.13+ and pnpm 11:

```bash
cd ui
corepack enable
corepack prepare pnpm@11.19.0 --activate
pnpm install --frozen-lockfile
pnpm exec tsc --noEmit --incremental false
pnpm run lint
```

Browser camera/microphone access works on `localhost`. A deployed non-localhost
origin must use HTTPS.
