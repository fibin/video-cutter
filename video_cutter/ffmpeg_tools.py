"""Thin wrappers around ffmpeg: probing, cutting and joining with progress."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .messages import UserError
from .timecode import Segment

ProgressCallback = Callable[[float, int, int], None]
"""Called with (fraction 0..1, current piece 1-based, total pieces)."""


# Keep ffmpeg from flashing a console window when the app runs as a windowed exe.
NO_WINDOW: dict = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}

ENCODE_ARGS = [
    "-c:v", "libx264",
    "-preset", "veryfast",
    "-crf", "20",
    "-pix_fmt", "yuv420p",
    "-movflags", "+faststart",
]
AUDIO_ARGS = ["-c:a", "aac", "-b:a", "192k"]


class FFmpegError(UserError):
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
        raise FFmpegError("ffmpeg_missing") from exc
    return imageio_ffmpeg.get_ffmpeg_exe()


@dataclass
class MediaInfo:
    duration: float
    has_video: bool
    has_audio: bool
    width: int = 0
    height: int = 0
    fps: float = 0.0


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_VIDEO_LINE_RE = re.compile(r"Stream #.*: Video:.*")
_SIZE_RE = re.compile(r",\s*(\d{2,5})x(\d{2,5})[\s,\[]")
_FPS_RE = re.compile(r"([\d.]+)\s*(?:fps|tbr)")


def probe(path: Path) -> MediaInfo:
    """Read duration, size, frame rate and stream types from `ffmpeg -i` (no ffprobe needed)."""
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
        raise FFmpegError("not_a_video")
    hours, minutes, seconds = match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    video_line = _VIDEO_LINE_RE.search(output)
    if not video_line:
        raise FFmpegError("no_video_track")
    has_audio = re.search(r"Stream #.*: Audio:", output) is not None
    size = _SIZE_RE.search(video_line.group(0))
    fps = _FPS_RE.search(video_line.group(0))
    return MediaInfo(
        duration=duration,
        has_video=True,
        has_audio=has_audio,
        width=int(size.group(1)) if size else 0,
        height=int(size.group(2)) if size else 0,
        fps=float(fps.group(1)) if fps else 0.0,
    )


def _run_with_progress(cmd: list[str], durations: list[float], on_progress: ProgressCallback | None) -> None:
    """Run ffmpeg (with `-progress pipe:1` in cmd) and report which piece it is on."""
    total = sum(durations)
    bounds = []
    acc = 0.0
    for d in durations:
        acc += d
        bounds.append(acc)

    def report(done: float) -> None:
        if not on_progress:
            return
        piece = next((i + 1 for i, b in enumerate(bounds) if done < b), len(durations))
        on_progress(min(done / total, 1.0) if total else 1.0, piece, len(durations))

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
        raise FFmpegError("ffmpeg_failed", detail="".join(err_lines[-15:]), code=proc.returncode)
    if on_progress:
        on_progress(1.0, len(durations), len(durations))


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
        cmd += ["-map", "[outa]", *AUDIO_ARGS]
    cmd += [*ENCODE_ARGS, "-progress", "pipe:1", "-nostats", str(output)]
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
        raise UserError("no_segments")
    info = info or probe(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_cut_command(source, segments, output, info.has_audio)
    _run_with_progress(cmd, [s.duration for s in segments], on_progress)
    return output


def _even(value: int) -> int:
    return max(2, value - value % 2)


def build_join_command(videos: list[tuple[Path, MediaInfo]], output: Path) -> list[str]:
    """Join whole videos in order. All are fitted into the first one's frame (black bars if
    the shape differs) and frame rate; videos without sound get silence so the audio stays in sync."""
    first = videos[0][1]
    width, height = _even(first.width or 1280), _even(first.height or 720)
    fps = first.fps if 1 <= first.fps <= 240 else 30
    any_audio = any(info.has_audio for _, info in videos)

    cmd = [ffmpeg_path(), "-hide_banner", "-y", "-nostdin"]
    for path, _ in videos:
        cmd += ["-i", str(path)]

    parts = []
    for i, (_, info) in enumerate(videos):
        parts.append(
            f"[{i}:v:0]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps:g},format=yuv420p,"
            f"setpts=PTS-STARTPTS[v{i}]"
        )
        if any_audio:
            if info.has_audio:
                parts.append(
                    f"[{i}:a:0]aformat=sample_rates=48000:channel_layouts=stereo,"
                    f"apad,atrim=0:{info.duration:.3f},asetpts=PTS-STARTPTS[a{i}]"
                )
            else:
                parts.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{info.duration:.3f}[a{i}]")
    inputs = "".join(f"[v{i}][a{i}]" if any_audio else f"[v{i}]" for i in range(len(videos)))
    outputs = "[outv][outa]" if any_audio else "[outv]"
    parts.append(f"{inputs}concat=n={len(videos)}:v=1:a={1 if any_audio else 0}{outputs}")

    cmd += ["-filter_complex", ";".join(parts), "-map", "[outv]"]
    if any_audio:
        cmd += ["-map", "[outa]", *AUDIO_ARGS]
    cmd += [*ENCODE_ARGS, "-progress", "pipe:1", "-nostats", str(output)]
    return cmd


def join_videos(
    videos: list[tuple[Path, MediaInfo]],
    output: Path,
    on_progress: ProgressCallback | None = None,
) -> Path:
    """Join several whole videos, in the given order, into one mp4."""
    if len(videos) < 2:
        raise UserError("join_need_two")
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_join_command(videos, output)
    _run_with_progress(cmd, [info.duration for _, info in videos], on_progress)
    return output
