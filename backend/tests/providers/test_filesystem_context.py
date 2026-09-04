import asyncio

import pytest

from interview_api.domain.errors import ContextNotFoundError, InvalidContextError
from interview_api.domain.models import ContextReference
from interview_api.providers.filesystem_context import FilesystemContextLoader


def test_filesystem_context_loader_reads_utf8_text(local_tmp_path) -> None:
    (local_tmp_path / "cv-1.txt").write_text("Опыт с Python", encoding="utf-8")
    loader = FilesystemContextLoader(local_tmp_path)

    loaded = asyncio.run(loader.load(ContextReference(type="cv", file_id="cv-1")))

    assert loaded.text == "Опыт с Python"
    assert loaded.file_id == "cv-1"


def test_filesystem_context_loader_reports_missing_file(local_tmp_path) -> None:
    loader = FilesystemContextLoader(local_tmp_path)

    with pytest.raises(ContextNotFoundError):
        asyncio.run(loader.load(ContextReference(type="cv", file_id="missing")))


def test_filesystem_context_loader_rejects_empty_file(local_tmp_path) -> None:
    (local_tmp_path / "cv-1.txt").write_text("   ", encoding="utf-8")
    loader = FilesystemContextLoader(local_tmp_path)

    with pytest.raises(InvalidContextError):
        asyncio.run(loader.load(ContextReference(type="cv", file_id="cv-1")))
