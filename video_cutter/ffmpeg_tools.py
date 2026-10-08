"""Thin wrappers around ffmpeg: probing and cutting with progress."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .timecode import Segment

ProgressCallback = Callable[[float, int, int], None]
"""Called with (fraction 0..1, current piece 1-based, total pieces)."""


# Keep ffmpeg from flashing a console window when the app runs as a windowed exe.
NO_WINDOW: dict = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


class FFmpegError(RuntimeError):
    pass


def ffmpeg_path() -> str:
    """Use ffmpeg from PATH, otherwise the copy bundled with imageio-ffmpeg.

    A packaged exe always uses its bundled copy, so it behaves the same on every machine.
    """
    found = None if getattr(sys, "frozen", False) else shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
    except ImportError as exc:  # pragma: no cover - dependency is in requirements
        raise FFmpegError("ffmpeg not found. Install the dependencies: pip install -r requirements.txt") from exc
    return imageio_ffmpeg.get_ffmpeg_exe()


@dataclass
class MediaInfo:
    duration: float
    has_video: bool
    has_audio: bool


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def probe(path: Path) -> MediaInfo:
    """Read duration and stream types from `ffmpeg -i` output (no ffprobe needed)."""
    result = subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **NO_WINDOW,
    )
    output = result.stderr
    match = _DURATION_RE.search(output)
    if not match:
        raise FFmpegError("Could not read the file. Is it really a video?")
    hours, minutes, seconds = match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    has_video = re.search(r"Stream #.*: Video:", output) is not None
    has_audio = re.search(r"Stream #.*: Audio:", output) is not None
    if not has_video:
        raise FFmpegError("The file has no video track")
    return MediaInfo(duration=duration, has_video=has_video, has_audio=has_audio)


def build_cut_command(source: Path, segments: list[Segment], output: Path, has_audio: bool) -> list[str]:
    """One ffmpeg run: each segment is an accurately seeked input, joined by the concat filter."""
    cmd = [ffmpeg_path(), "-hide_banner", "-y", "-nostdin"]
    for seg in segments:
        cmd += ["-ss", f"{seg.start:.3f}", "-t", f"{seg.duration:.3f}", "-i", str(source)]

    parts = []
    for i in range(len(segments)):
        # Normalise timestamps so pieces join without gaps.
        parts.append(f"[{i}:v:0]setpts=PTS-STARTPTS[v{i}]")
        if has_audio:
            parts.append(f"[{i}:a:0]asetpts=PTS-STARTPTS[a{i}]")
    inputs = "".join(f"[v{i}][a{i}]" if has_audio else f"[v{i}]" for i in range(len(segments)))
    audio_flag = 1 if has_audio else 0
    outputs = "[outv][outa]" if has_audio else "[outv]"
    parts.append(f"{inputs}concat=n={len(segments)}:v=1:a={audio_flag}{outputs}")

    cmd += ["-filter_complex", ";".join(parts), "-map", "[outv]"]
    if has_audio:
        cmd += ["-map", "[outa]", "-c:a", "aac", "-b:a", "192k"]
    cmd += [
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-progress", "pipe:1",
        "-nostats",
        str(output),
    ]
    return cmd


def cut_and_join(
    source: Path,
    segments: list[Segment],
    output: Path,
    on_progress: ProgressCallback | None = None,
    info: MediaInfo | None = None,
) -> Path:
    """Cut `segments` out of `source` (frame-accurate, re-encoded) and join them into `output`."""
    if not segments:
        raise ValueError("No segments to cut")
    info = info or probe(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_cut_command(source, segments, output, info.has_audio)

    total = sum(s.duration for s in segments)
    bounds = []
    acc = 0.0
    for seg in segments:
        acc += seg.duration
        bounds.append(acc)

    def report(done: float) -> None:
        if not on_progress:
            return
        piece = next((i + 1 for i, b in enumerate(bounds) if done < b), len(segments))
        on_progress(min(done / total, 1.0) if total else 1.0, piece, len(segments))

    report(0.0)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **NO_WINDOW,
    )
    # stderr is drained in a thread so a chatty ffmpeg never blocks on a full pipe.
    err_lines: list[str] = []
    err_thread = threading.Thread(target=lambda: err_lines.extend(proc.stderr), daemon=True)
    err_thread.start()

    assert proc.stdout is not None
    for line in proc.stdout:
        key, _, value = line.strip().partition("=")
        if key == "out_time_us" and value.isdigit():
            report(int(value) / 1_000_000)
    proc.wait()
    err_thread.join(timeout=5)
    if proc.returncode != 0:
        tail = "".join(err_lines[-15:])
        raise FFmpegError(f"ffmpeg failed ({proc.returncode}):\n{tail}")
    if on_progress:
        on_progress(1.0, len(segments), len(segments))
    return output
