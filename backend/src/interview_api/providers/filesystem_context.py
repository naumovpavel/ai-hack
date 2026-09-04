import asyncio
from pathlib import Path

from interview_api.domain.errors import ContextNotFoundError, InvalidContextError
from interview_api.domain.models import ContextReference, LoadedContext


class FilesystemContextLoader:
    """Load UTF-8 text documents from an application-owned directory."""

    def __init__(self, context_dir: Path) -> None:
        self._context_dir = context_dir.resolve()

    async def load(self, reference: ContextReference) -> LoadedContext:
        path = (self._context_dir / f"{reference.file_id}.txt").resolve()
        if path.parent != self._context_dir or not path.is_file():
            raise ContextNotFoundError(reference.file_id)

        try:
            text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise InvalidContextError(reference.file_id) from exc

        if not text.strip():
            raise InvalidContextError(reference.file_id)

        return LoadedContext(type=reference.type, file_id=reference.file_id, text=text)
