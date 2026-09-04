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
`create_all` does not upgrade an existing schema; introduce versioned Alembic
migrations before relying on persistent environments across schema changes.

## What the smoke check proves

`make smoke` verifies that PostgreSQL accepts connections, the workflow schema
and demo HR user exist, the private MinIO bucket exists, and both HTTP processes
answer inside their containers. After it passes, run the browser scenario below
to verify the product workflow as well.

## Manual end-to-end scenario

1. Open the UI as the HR test user and create a position with a vacancy file,
   requirements, desired question count, duration, and optional seed questions.
2. Upload a candidate resume, review/edit the generated questions, approve them,
   and copy the invite URL.
3. Switch to the candidate test user, open the invite URL, grant camera and
   microphone permissions, and complete the interview.
4. Return to the HR user and wait for analysis. Verify audio, video, transcript,
   evidence, and recommendation.
5. Open every required analysis item for at least ten active seconds. Confirm
   that an earlier decision attempt is rejected, then invite or reject the
   candidate. For rejection, enter an original internal reason and candidate
   feedback.
6. Switch back to the candidate and verify that the human decision and feedback
   are visible.

Use a short interview and small media samples for this smoke run. Model calls go
through OpenRouter; PostgreSQL, MinIO, the API, and the UI stay local.

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
