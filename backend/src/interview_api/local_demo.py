"""Click-ready local app when Docker/MinIO are unavailable.

Production-like local runs should use the repository Compose stack. This module
keeps the same workflow API while using SQLite and a private temporary-file
object store, so the product can be exercised immediately on a developer Mac.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import create_async_engine

from interview_api.config import Settings
from interview_api.main import create_app
from interview_api.workflow.ai import DeterministicWorkflowAI, WorkflowAIGateway
from interview_api.workflow.openrouter import OpenRouterWorkflowAI
from interview_api.workflow.repository import SqlAlchemyWorkflowRepository
from interview_api.workflow.service import WorkflowService
from interview_api.workflow.storage import StoredObject


class LocalObjectStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._downloads: dict[str, tuple[str, str]] = {}

    async def ensure_bucket(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError("Unsafe object key")
        return path

    async def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        metadata: object | None = None,
    ) -> StoredObject:
        del metadata
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredObject(key=key, size_bytes=len(data), content_type=content_type)

    async def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    async def presign_download(
        self, key: str, *, filename: str, expires_seconds: int = 900
    ) -> str:
        del expires_seconds
        token = secrets.token_urlsafe(24)
        self._downloads[token] = (key, filename)
        return f"http://127.0.0.1:8000/api/v1/local-media/{quote(token)}"

    def resolve_download(self, token: str) -> tuple[Path, str]:
        try:
            key, filename = self._downloads[token]
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Download expired") from exc
        return self._path(key), filename


settings = Settings(app_env="test", _env_file=None)
engine = create_async_engine(
    "sqlite+aiosqlite:////private/tmp/signal-interview-demo.sqlite3"
)
repository = SqlAlchemyWorkflowRepository.from_engine(engine)
storage = LocalObjectStorage(Path("/private/tmp/signal-interview-media"))

key = settings.openrouter_api_key
ai: WorkflowAIGateway
if key:
    ai = OpenRouterWorkflowAI(
        api_key=key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        chat_model=settings.openrouter_chat_model,
        stt_model=settings.openrouter_stt_model,
        tts_model=settings.openrouter_tts_model,
        tts_voice=settings.openrouter_tts_voice,
        timeout_seconds=settings.openrouter_timeout_seconds,
        max_retries=settings.openrouter_max_retries,
    )
else:
    ai = DeterministicWorkflowAI()

workflow = WorkflowService(
    repository=repository,
    storage=storage,
    ai=ai,
    invite_base_url="http://localhost:3000/?invite=",
    required_review_seconds=settings.review_seconds_per_item,
)
app = create_app(
    settings=settings,
    workflow_service=workflow,
    workflow_engine=engine,
)


@app.get("/api/v1/local-media/{token}", include_in_schema=False)
async def local_media(token: str) -> FileResponse:
    path, filename = storage.resolve_download(token)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=filename)
