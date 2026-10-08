"""Downloading videos by link with yt-dlp."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .ffmpeg_tools import ffmpeg_path

DownloadProgress = Callable[[float | None, float | None, float | None], None]
"""Called with (fraction 0..1 or None, speed bytes/s or None, eta seconds or None)."""


class DownloadError(RuntimeError):
    pass


def download(url: str, target_dir: Path, on_progress: DownloadProgress | None = None) -> tuple[Path, str]:
    """Download `url` into `target_dir` as mp4. Returns (file path, video title)."""
    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover - dependency is in requirements
        raise DownloadError("yt-dlp is not installed. Run: pip install -r requirements.txt") from exc

    target_dir.mkdir(parents=True, exist_ok=True)

    def hook(status: dict) -> None:
        if not on_progress or status.get("status") != "downloading":
            return
        total = status.get("total_bytes") or status.get("total_bytes_estimate")
        done = status.get("downloaded_bytes")
        fraction = done / total if total and done is not None else None
        on_progress(fraction, status.get("speed"), status.get("eta"))

    options = {
        # Prefer mp4/m4a so the merge needs no re-encoding; fall back to anything.
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
        "merge_output_format": "mp4",
        "outtmpl": str(target_dir / "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [hook],
        "ffmpeg_location": ffmpeg_path(),
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            path = Path(ydl.prepare_filename(info))
    except yt_dlp.utils.DownloadError as exc:
        # Drop yt-dlp's "ERROR:" prefix and its "please report this issue" tail.
        message = str(exc).removeprefix("ERROR: ").split("; please report")[0]
        raise DownloadError(f"Could not download the video: {message}") from exc

    # After merging, the real file may have a different extension than prepare_filename reports.
    if not path.exists():
        candidates = sorted(target_dir.glob("source.*"))
        candidates = [c for c in candidates if not c.name.endswith((".part", ".ytdl"))]
        if not candidates:
            raise DownloadError("The video was downloaded but the file was not found")
        path = candidates[0]
    return path, info.get("title") or "video"
