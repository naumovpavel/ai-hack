"""Real media integration; runs automatically in the backend Docker image."""
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from interview_api.workflow.integrity_media import IntegrityMedia
from interview_api.workflow.storage import MemoryObjectStorage

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                               reason="FFmpeg/FFprobe are installed in the backend Docker image")


@pytest.mark.asyncio
async def test_actual_webm_stream_becomes_seekable_mp4_with_audio_and_temporary_clips(tmp_path):
    original = tmp_path / "camera.webm"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
        "testsrc=size=160x120:rate=10", "-f", "lavfi", "-i", "sine=frequency=440",
        "-t", "2", "-c:v", "libvpx", "-c:a", "libopus", str(original)], check=True)
    data = original.read_bytes()
    storage = MemoryObjectStorage()
    chunks = []
    # Timeslice boundaries need not align with WebM headers; byte concatenation must restore it.
    middle = len(data) // 2
    for index, part in enumerate([data[:middle], data[middle:]]):
        key = f"chunk-{index}"
        await storage.put_bytes(key, part, content_type="video/webm")
        chunks.append(SimpleNamespace(sequence=index, object_key=key,
            start_ms=500 + index * 1000, end_ms=1500 + index * 1000))
    media = IntegrityMedia(storage)
    prepared = await media.prepare_stream(chunks, object_key="continuous.mp4")
    assert prepared.start_ms == 500
    assert 2400 <= prepared.end_ms <= 2500
    mp4 = await storage.get_bytes("continuous.mp4")
    assert mp4.index(b"moov") < mp4.index(b"mdat")  # faststart metadata precedes samples
    rows = [SimpleNamespace(id="camera", kind="camera", start_ms=prepared.start_ms,
        end_ms=prepared.end_ms, object_key=prepared.object_key)]
    parts = await media.interval_parts(rows, 1000, 2000)
    assert len(parts) == 1 and parts[0].audio[:4] == b"RIFF"
    assert (parts[0].start_ms, parts[0].end_ms) == (1000, 2000)
    assert b"ftyp" in parts[0].video[:32]
    assert set(storage.objects) == {"chunk-0", "chunk-1", "continuous.mp4"}
