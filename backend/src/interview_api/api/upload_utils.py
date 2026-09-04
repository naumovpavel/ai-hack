from fastapi import UploadFile

_UPLOAD_SCAN_CHUNK_BYTES = 1024 * 1024


async def measure_upload(upload: UploadFile, *, max_bytes: int) -> int:
    """Measure a spooled upload without retaining another full in-memory copy."""

    if upload.size is not None:
        size = upload.size
    else:
        size = 0
        while chunk := await upload.read(_UPLOAD_SCAN_CHUNK_BYTES):
            size += len(chunk)
            if size > max_bytes:
                break

    await upload.seek(0)
    return size
