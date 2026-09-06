import asyncio
from urllib.parse import urlparse

import pytest
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from interview_api.local_demo import LocalObjectStorage


def test_private_local_media_supports_range_cors_and_expiring_urls(tmp_path, monkeypatch):
    storage = LocalObjectStorage(tmp_path)
    data = bytes(range(256)) * 4
    asyncio.run(storage.put_bytes("candidates/c/integrity/video.mp4", data,
                                 content_type="video/mp4"))
    link = asyncio.run(storage.presign_download("candidates/c/integrity/video.mp4",
                                                filename="video.mp4", inline=True))
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"],
        allow_methods=["GET", "HEAD"], allow_headers=["Range"],
        expose_headers=["Accept-Ranges", "Content-Range", "Content-Length"])

    @app.get("/api/v1/local-media/{token}")
    def video(token: str):
        path, filename, inline = storage.resolve_download(token)
        return FileResponse(path, filename=filename,
                            content_disposition_type="inline" if inline else "attachment")

    client = TestClient(app)
    url = urlparse(link).path
    response = client.get(url, headers={"Range": "bytes=10-19", "Origin": "http://localhost:3000"})
    assert response.status_code == 206
    assert response.content == data[10:20]
    assert response.headers["content-range"] == f"bytes 10-19/{len(data)}"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert client.get(url, headers={"Range": "bytes=9999-"}).status_code == 416
    import time
    monkeypatch.setattr(time, "time", lambda: 10**12)
    assert client.get(url).status_code == 403
    with pytest.raises(ValueError):
        asyncio.run(storage.object_exists("../outside"))
