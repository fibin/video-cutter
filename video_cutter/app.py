"""Local web server: serves the UI and runs downloads and cuts in the background."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from urllib.parse import unquote

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

from . import ffmpeg_tools, youtube
from .jobs import Job, Registry, Source, safe_filename
from .timecode import build_segments, format_time

STATIC_DIR = Path(__file__).parent / "static"


def default_data_dir() -> Path:
    return Path(os.environ.get("VIDEO_CUTTER_DATA", Path.home() / "VideoCutter"))


def create_app(data_dir: Path | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    registry = Registry(data_dir or default_data_dir())
    app.config["registry"] = registry

    def error(message: str, status: int = 400):
        return jsonify({"error": message}), status

    def source_json(source: Source) -> dict:
        return {
            "id": source.id,
            "title": source.title,
            "duration": source.duration,
            "duration_text": format_time(source.duration),
            "has_audio": source.has_audio,
            "video_url": f"/api/sources/{source.id}/video",
        }

    def register_file(source_id: str, path: Path, title: str) -> Source:
        info = ffmpeg_tools.probe(path)
        return registry.add_source(
            Source(id=source_id, path=path, title=title, duration=info.duration, has_audio=info.has_audio)
        )

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/static/<path:name>")
    def static_files(name: str):
        return send_from_directory(STATIC_DIR, name)

    @app.post("/api/upload")
    def upload():
        """Raw request body is the file; the name comes URL-encoded in X-Filename."""
        name = unquote(request.headers.get("X-Filename", "video.mp4"))
        suffix = Path(name).suffix.lower() or ".mp4"
        source_id = registry.new_id()
        folder = registry.source_dir(source_id)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"source{suffix}"
        with path.open("wb") as fh:
            shutil.copyfileobj(request.stream, fh, length=1024 * 1024)
        try:
            source = register_file(source_id, path, Path(name).stem)
        except ffmpeg_tools.FFmpegError as exc:
            shutil.rmtree(folder, ignore_errors=True)
            return error(str(exc))
        return jsonify(source_json(source))

    @app.post("/api/youtube")
    def from_link():
        url = (request.get_json(silent=True) or {}).get("url", "").strip()
        if not url.startswith(("http://", "https://")):
            return error("Paste a link that starts with http:// or https://")
        source_id = registry.new_id()
        folder = registry.source_dir(source_id)

        def work(job: Job) -> dict:
            job.stage = "Downloading"

            def on_progress(fraction, speed, eta):
                job.percent = round(fraction * 100, 1) if fraction is not None else None
                bits = []
                if speed:
                    bits.append(f"{speed / 1024 / 1024:.1f} MB/s")
                if eta is not None:
                    bits.append(f"{format_time(eta)} left")
                job.detail = ", ".join(bits)

            path, title = youtube.download(url, folder, on_progress)
            job.stage = "Checking the file"
            job.detail = ""
            source = register_file(source_id, path, title)
            return {"source": source_json(source)}

        job = registry.start_job("download", work)
        return jsonify(job.to_dict())

    @app.get("/api/sources/<source_id>/video")
    def source_video(source_id: str):
        source = registry.get_source(source_id) or abort(404)
        return send_file(source.path, conditional=True)

    @app.post("/api/cut")
    def cut():
        body = request.get_json(silent=True) or {}
        source = registry.get_source(body.get("source_id", ""))
        if not source:
            return error("Choose a video first")
        try:
            segments = build_segments(body.get("segments") or [], source.duration, body.get("mode", "keep"))
        except ValueError as exc:
            return error(str(exc))

        out_dir = registry.data_dir / "results"
        base = safe_filename(f"{source.title} - cut")

        def work(job: Job) -> dict:
            job.stage = "Cutting"
            output = out_dir / f"{base}-{job.id}.mp4"

            def on_progress(fraction, piece, total):
                job.percent = round(fraction * 100, 1)
                job.detail = f"piece {piece} of {total}"

            info = ffmpeg_tools.MediaInfo(source.duration, True, source.has_audio)
            ffmpeg_tools.cut_and_join(source.path, segments, output, on_progress, info)
            total = sum(s.duration for s in segments)
            return {
                "download_url": f"/api/jobs/{job.id}/download",
                "preview_url": f"/api/jobs/{job.id}/download?inline=1",
                "filename": f"{base}.mp4",
                "path": str(output),
                "duration_text": format_time(total),
                "pieces": len(segments),
            }

        job = registry.start_job("cut", work)
        return jsonify(job.to_dict())

    @app.get("/api/jobs/<job_id>")
    def job_status(job_id: str):
        job = registry.get_job(job_id) or abort(404)
        return jsonify(job.to_dict())

    @app.get("/api/jobs/<job_id>/download")
    def job_download(job_id: str):
        job = registry.get_job(job_id)
        if not job or job.state != "done" or "path" not in job.result:
            abort(404)
        inline = request.args.get("inline") == "1"
        return send_file(
            job.result["path"],
            as_attachment=not inline,
            download_name=job.result["filename"],
            conditional=True,
        )

    return app
