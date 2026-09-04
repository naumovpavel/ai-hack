# AI Interview Backend MVP

Minimal FastAPI backend for question generation and audio transcription.
Question generation uses a local Ollama provider with Pydantic structured output.
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

Install Ollama, then download the configured model:

```bash
ollama pull qwen3:4b
```

The default local endpoint is `http://127.0.0.1:11434`. Configure it through
`OLLAMA_HOST`, `OLLAMA_QUESTION_MODEL`, and `OLLAMA_TIMEOUT_SECONDS`.

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
settings in `.env` if needed. Tests inject fake providers and never call Ollama,
download models, or use an external API.

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
