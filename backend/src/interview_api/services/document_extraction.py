import asyncio
from collections.abc import Sequence

from interview_api.domain.errors import (
    DocumentTooLargeError,
    ExtractedTextTooLargeError,
    InvalidDocumentError,
)
from interview_api.domain.models import DocumentInput, LoadedContext
from interview_api.providers.interfaces import DocumentTextExtractor


class DocumentExtractionService:
    def __init__(
        self,
        extractor: DocumentTextExtractor,
        *,
        max_document_bytes: int,
        max_document_characters: int,
    ) -> None:
        self._extractor = extractor
        self.max_document_bytes = max_document_bytes
        self._max_document_characters = max_document_characters

    async def extract_all(
        self,
        documents: Sequence[DocumentInput],
    ) -> list[LoadedContext]:
        return list(await asyncio.gather(*(self._extract(document) for document in documents)))

    async def _extract(self, document: DocumentInput) -> LoadedContext:
        if document.size_bytes == 0:
            raise InvalidDocumentError(document.filename)
        if document.size_bytes > self.max_document_bytes:
            raise DocumentTooLargeError(document.filename, self.max_document_bytes)

        text = await self._extractor.extract(document)
        if len(text) > self._max_document_characters:
            raise ExtractedTextTooLargeError(
                document.filename,
                self._max_document_characters,
            )
        return LoadedContext(
            type=document.context_type,
            file_id=document.file_id,
            text=text,
        )
