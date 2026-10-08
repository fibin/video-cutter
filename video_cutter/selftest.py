"""`--self-test`: checks that a build has everything it needs (used by CI on the packaged exe)."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

from . import ffmpeg_tools, youtube
from .app import create_app
from .timecode import Segment


def _check_ffmpeg_cut(workdir: Path) -> str:
    clip = workdir / "clip.mp4"
    subprocess.run(
        [
            ffmpeg_tools.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=6",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip),
        ],
        check=True,
        capture_output=True,
        **ffmpeg_tools.NO_WINDOW,
    )
    out = ffmpeg_tools.cut_and_join(clip, [Segment(1, 2), Segment(4, 5.5)], workdir / "out.mp4")
    duration = ffmpeg_tools.probe(out).duration
    if abs(duration - 2.5) > 0.1:
        raise AssertionError(f"expected 2.5 s, got {duration}")
    joined = ffmpeg_tools.join_videos(
        [(clip, ffmpeg_tools.probe(clip)), (out, ffmpeg_tools.probe(out))], workdir / "joined.mp4"
    )
    joined_duration = ffmpeg_tools.probe(joined).duration
    if abs(joined_duration - 8.5) > 0.2:
        raise AssertionError(f"expected 8.5 s after joining, got {joined_duration}")
    return f"cut and join ok ({duration:.2f} s, {joined_duration:.2f} s) with {ffmpeg_tools.ffmpeg_path()}"


def _check_web_app(workdir: Path) -> str:
    client = create_app(workdir / "data").test_client()
    for url in ("/", "/static/app.js", "/static/style.css"):
        res = client.get(url)
        if res.status_code != 200:
            raise AssertionError(f"{url} returned {res.status_code}")
    return "UI files served"


def _check_youtube() -> str:
    import yt_dlp  # noqa: F401
    import yt_dlp_ejs  # noqa: F401

    runtimes = youtube.js_runtimes()
    if runtimes is None:
        if getattr(sys, "frozen", False):
            raise AssertionError("deno is missing from the build")
        return "yt-dlp ok, deno taken from the environment"
    path = Path(runtimes["deno"]["path"])
    version = subprocess.run(
        [str(path), "--version"], capture_output=True, text=True, check=True, **ffmpeg_tools.NO_WINDOW
    ).stdout
    return f"yt-dlp ok, bundled deno: {version.splitlines()[0]}"


def _check_window() -> str:
    import webview  # noqa: F401

    return "pywebview importable"


def run_self_test(report_path: str) -> int:
    lines = []
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        checks = [
            ("ffmpeg", lambda: _check_ffmpeg_cut(workdir)),
            ("web app", lambda: _check_web_app(workdir)),
            ("youtube", _check_youtube),
            ("window", _check_window),
        ]
        for name, check in checks:
            started = time.time()
            try:
                lines.append(f"PASS {name}: {check()} [{time.time() - started:.1f}s]")
            except Exception:
                ok = False
                lines.append(f"FAIL {name}:\n{traceback.format_exc()}")
    Path(report_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if ok else 1
