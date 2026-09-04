from typing import Any


class ApplicationError(Exception):
    code = "application_error"
    message = "The request could not be completed."

    def __init__(self, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(self.message)
        self.details = details


class ContextNotFoundError(ApplicationError):
    code = "context_not_found"
    message = "Context file was not found."

    def __init__(self, file_id: str) -> None:
        super().__init__(details={"file_id": file_id})


class InvalidContextError(ApplicationError):
    code = "invalid_context"
    message = "Context file must contain valid UTF-8 text."

    def __init__(self, file_id: str) -> None:
        super().__init__(details={"file_id": file_id})


class InvalidDocumentError(ApplicationError):
    code = "invalid_document"
    message = "The document is empty, damaged, or contains no extractable text."

    def __init__(self, filename: str | None) -> None:
        super().__init__(details={"filename": filename})


class UnsupportedDocumentTypeError(ApplicationError):
    code = "unsupported_document_type"
    message = "Only PDF, DOCX, and UTF-8 TXT documents are supported."

    def __init__(self, filename: str | None) -> None:
        super().__init__(details={"filename": filename})


class DocumentTooLargeError(ApplicationError):
    code = "document_too_large"
    message = "The uploaded document exceeds the configured size limit."

    def __init__(self, filename: str | None, max_bytes: int) -> None:
        super().__init__(details={"filename": filename, "max_bytes": max_bytes})


class ExtractedTextTooLargeError(ApplicationError):
    code = "extracted_text_too_large"
    message = "The extracted document text exceeds the configured limit."

    def __init__(self, filename: str | None, max_characters: int) -> None:
        super().__init__(
            details={"filename": filename, "max_characters": max_characters}
        )


class InsufficientContextError(ApplicationError):
    code = "insufficient_context"
    message = "Vacancy or requirements context is required for core questions."


class MissingContextDocumentsError(ApplicationError):
    code = "missing_context_documents"
    message = "At least one context document must be uploaded."


class InvalidAudioError(ApplicationError):
    code = "invalid_audio"
    message = "Audio is empty or could not be decoded."


class PayloadTooLargeError(ApplicationError):
    code = "payload_too_large"
    message = "The uploaded audio exceeds the configured size limit."


class ProviderTimeoutError(ApplicationError):
    code = "provider_timeout"
    message = "The AI provider timed out."


class ProviderUnavailableError(ApplicationError):
    code = "provider_unavailable"
    message = "The AI provider is temporarily unavailable."


class ProviderResponseError(ApplicationError):
    code = "invalid_provider_response"
    message = "The AI provider returned an invalid response."


class ServiceNotConfiguredError(ApplicationError):
    code = "service_not_configured"
    message = "The requested service is not configured."

    def __init__(self, service: str) -> None:
        super().__init__(details={"service": service})
