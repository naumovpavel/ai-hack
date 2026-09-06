"""Prepare seekable continuous streams once; temporary analysis clips never leave disk."""
from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from interview_api.workflow.storage import ObjectStorage


@dataclass(frozen=True)
class PreparedStream:
    object_key: str
    start_ms: int
    end_ms: int
    duration_ms: int
    size_bytes: int


@dataclass(frozen=True)
class AnalysisPart:
    media_id: str
    kind: str
    start_ms: int
    end_ms: int
    video: bytes
    audio: bytes | None = None


def coverage_ms(ranges: list[tuple[int, int]]) -> int:
    """Union length, so overlaps/restarts do not inflate reported coverage."""
    total = 0
    right = 0
    for start, end in sorted(ranges):
        total += max(0, end - max(start, right))
        right = max(right, end)
    return total


def analysis_intervals(end_ms: int) -> list[tuple[int, int]]:
    result = []
    start = 0
    while start < end_ms:
        end = min(start + 120_000, end_ms)
        result.append((start, end))
        if end == end_ms:
            break
        start += 115_000
    return result


class IntegrityMedia:
    def __init__(self, storage: ObjectStorage, *, ffmpeg: str = "ffmpeg",
                 ffprobe: str = "ffprobe") -> None:
        self.storage = storage
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe

    async def _run(self, executable: str, *args: str) -> bytes:
        process = await asyncio.create_subprocess_exec(
            executable, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=600)
        except BaseException:
            process.kill()
            await process.wait()
            raise
        if process.returncode:
            # Never include raw media, paths, credentials or untrusted metadata in logs.
            raise RuntimeError(f"Media preparation failed ({executable}, {process.returncode})")
        return stdout

    async def prepare_stream(self, chunks: list[Any], *, object_key: str) -> PreparedStream:
        ordered = sorted(chunks, key=lambda item: item.sequence)
        contiguous = []
        for index, chunk in enumerate(ordered):
            if chunk.sequence != index:
                break
            # Timeslice blobs belong to ONE recorder, so concatenate bytes, not files
            # with the concat demuxer (later blobs do not contain container headers).
            contiguous.append(chunk)
        if not contiguous:
            raise ValueError("The beginning of this recorder stream is missing")
        with TemporaryDirectory(prefix="integrity-prepare-") as directory:
            root = Path(directory)
            source = root / "capture.webm"
            with source.open("wb") as output:
                for chunk in contiguous:
                    output.write(await self.storage.get_bytes(chunk.object_key))
            target = root / "stream.mp4"
            await self._run(
                self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-protocol_whitelist", "file,pipe", "-format_whitelist", "matroska,webm,mov",
                "-fflags", "+genpts", "-i", str(source), "-map", "0:v:0", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(target),
            )
            metadata = json.loads(await self._run(
                self.ffprobe, "-v", "error", "-show_entries", "format=duration",
                "-of", "json", str(target),
            ))
            seconds = float(metadata["format"]["duration"])
            if not math.isfinite(seconds) or seconds <= 0:
                raise ValueError("Invalid stream duration")
            duration_ms = round(seconds * 1000)
            start_ms = contiguous[0].start_ms
            # A browser-reported time cannot extend evidence past actual decoded frames.
            end_ms = min(contiguous[-1].end_ms, start_ms + duration_ms)
            if end_ms <= start_ms:
                raise ValueError("Empty stream")
            data = target.read_bytes()
            await self.storage.put_bytes(object_key, data, content_type="video/mp4")
            return PreparedStream(object_key, start_ms, end_ms, duration_ms, len(data))

    async def interval_parts(self, media: list[Any], start_ms: int,
                             end_ms: int) -> list[AnalysisPart]:
        parts = []
        with TemporaryDirectory(prefix="integrity-analysis-") as directory:
            root = Path(directory)
            for index, item in enumerate(media):
                start, end = max(start_ms, item.start_ms), min(end_ms, item.end_ms)
                if start >= end:
                    continue
                source, video = root / f"{index}.mp4", root / f"{index}-clip.mp4"
                source.write_bytes(await self.storage.get_bytes(item.object_key))
                seek = str((start - item.start_ms) / 1000)
                duration = str((end - start) / 1000)
                await self._run(
                    self.ffmpeg, "-v", "error", "-y", "-ss", seek, "-i", str(source),
                    "-t", duration, "-an", "-vf", "scale=960:-2,fps=5",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
                    "-movflags", "+faststart", str(video),
                )
                audio_data = None
                audio_streams = json.loads(await self._run(
                    self.ffprobe, "-v", "error", "-select_streams", "a",
                    "-show_entries", "stream=index", "-of", "json", str(source),
                )).get("streams", []) if item.kind == "camera" else []
                if audio_streams:
                    audio = root / f"{index}.wav"
                    await self._run(
                        self.ffmpeg, "-v", "error", "-y", "-ss", seek, "-i", str(source),
                        "-t", duration, "-vn", "-ac", "1", "-ar", "16000", str(audio),
                    )
                    audio_data = audio.read_bytes()
                parts.append(AnalysisPart(item.id, item.kind, start, end,
                                          video.read_bytes(), audio_data))
        return parts
