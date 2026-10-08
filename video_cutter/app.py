"""Local web server: serves the UI and runs downloads, cuts and joins in the background."""

from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path
from urllib.parse import unquote

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

from . import ffmpeg_tools, youtube
from .jobs import Job, Registry, Source, safe_filename
from .messages import UserError
from .timecode import build_segments, format_time

STATIC_DIR = Path(__file__).parent / "static"


def default_data_dir() -> Path:
    return Path(os.environ.get("VIDEO_CUTTER_DATA", Path.home() / "VideoCutter"))


def create_app(data_dir: Path | None = None, parallel_jobs: int | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    registry = Registry(data_dir or default_data_dir(), parallel_jobs)
    app.config["registry"] = registry

    def error(exc: UserError, status: int = 400):
        return jsonify({"error": exc.to_json()}), status

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
            Source(
                id=source_id,
                path=path,
                title=title,
                duration=info.duration,
                has_audio=info.has_audio,
                info=info,
            )
        )

    def file_entry(job_id: str, index: int, path: Path, name: str, duration: float) -> dict:
        return {
            "name": name,
            "path": str(path),
            "duration_text": format_time(duration),
            "download_url": f"/api/jobs/{job_id}/files/{index}",
            "preview_url": f"/api/jobs/{job_id}/files/{index}?inline=1",
        }

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
        except UserError as exc:
            shutil.rmtree(folder, ignore_errors=True)
            return error(exc)
        return jsonify(source_json(source))

    @app.post("/api/youtube")
    def from_link():
        url = (request.get_json(silent=True) or {}).get("url", "").strip()
        if not url.startswith(("http://", "https://")):
            return error(UserError("link_invalid"))
        source_id = registry.new_id()
        folder = registry.source_dir(source_id)

        def work(job: Job) -> dict:
            job.stage = "stage_downloading"

            def on_progress(fraction, speed, eta):
                job.percent = round(fraction * 100, 1) if fraction is not None else None
                job.set_detail("detail_download", speed=speed, eta=eta)

            path, title = youtube.download(url, folder, on_progress)
            job.stage, job.detail, job.percent = "stage_checking", None, None
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
            return error(UserError("source_missing"))
        try:
            segments = build_segments(body.get("segments") or [], source.duration, body.get("mode", "keep"))
        except UserError as exc:
            return error(exc)
        separate = bool(body.get("separate"))
        title = safe_filename(source.title)
        info = source.info or ffmpeg_tools.MediaInfo(source.duration, True, source.has_audio)

        def work(job: Job) -> dict:
            job.stage = "stage_cutting"
            out_dir = registry.data_dir / "results"
            files = []
            if not separate:
                output = out_dir / f"{title} - cut-{job.id}.mp4"

                def on_progress(fraction, piece, total):
                    job.percent = round(fraction * 100, 1)
                    job.set_detail("detail_piece", piece=piece, total=total)

                ffmpeg_tools.cut_and_join(source.path, segments, output, on_progress, info)
                total = sum(s.duration for s in segments)
                files.append(file_entry(job.id, 0, output, f"{title} - cut.mp4", total))
            else:
                # Each segment becomes its own file; progress spans all of them.
                folder = out_dir / f"{title} - parts-{job.id}"
                grand_total = sum(s.duration for s in segments)
                done_before = 0.0
                for index, seg in enumerate(segments):
                    name = f"{title} - part {index + 1:02d}.mp4"

                    def on_progress(fraction, _piece, _total, index=index, seg=seg, done_before=done_before):
                        job.percent = round((done_before + fraction * seg.duration) / grand_total * 100, 1)
                        job.set_detail("detail_piece", piece=index + 1, total=len(segments))

                    output = folder / name
                    ffmpeg_tools.cut_and_join(source.path, [seg], output, on_progress, info)
                    files.append(file_entry(job.id, index, output, name, seg.duration))
                    done_before += seg.duration
            total = sum(s.duration for s in segments)
            return {"files": files, "pieces": len(segments), "duration_text": format_time(total)}

        job = registry.start_job("cut", work, queued=True)
        return jsonify(job.to_dict())

    @app.post("/api/join")
    def join():
        ids = (request.get_json(silent=True) or {}).get("source_ids") or []
        sources = [registry.get_source(i) for i in ids]
        if any(s is None for s in sources):
            return error(UserError("source_missing"))
        if len(sources) < 2:
            return error(UserError("join_need_two"))
        title = safe_filename(sources[0].title)

        def work(job: Job) -> dict:
            job.stage = "stage_joining"
            output = registry.data_dir / "results" / f"{title} - joined-{job.id}.mp4"
            videos = [(s.path, s.info or ffmpeg_tools.probe(s.path)) for s in sources]

            def on_progress(fraction, piece, total):
                job.percent = round(fraction * 100, 1)
                job.set_detail("detail_video", piece=piece, total=total)

            ffmpeg_tools.join_videos(videos, output, on_progress)
            total = sum(s.duration for s in sources)
            return {
                "files": [file_entry(job.id, 0, output, f"{title} - joined.mp4", total)],
                "pieces": len(sources),
                "duration_text": format_time(total),
            }

        job = registry.start_job("join", work, queued=True)
        return jsonify(job.to_dict())

    @app.get("/api/jobs/<job_id>")
    def job_status(job_id: str):
        job = registry.get_job(job_id) or abort(404)
        return jsonify(job.to_dict())

    def finished_files(job_id: str) -> list[dict]:
        job = registry.get_job(job_id)
        if not job or job.state != "done" or not job.result.get("files"):
            abort(404)
        return job.result["files"]

    @app.get("/api/jobs/<job_id>/files/<int:index>")
    def job_file(job_id: str, index: int):
        files = finished_files(job_id)
        if not 0 <= index < len(files):
            abort(404)
        entry = files[index]
        inline = request.args.get("inline") == "1"
        return send_file(entry["path"], as_attachment=not inline, download_name=entry["name"], conditional=True)

    @app.get("/api/jobs/<job_id>/zip")
    def job_zip(job_id: str):
        files = finished_files(job_id)
        archive = Path(files[0]["path"]).parent / f"all-{job_id}.zip"
        if not archive.exists():
            # Videos are already compressed, so store them as they are.
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as zf:
                for entry in files:
                    zf.write(entry["path"], arcname=entry["name"])
        name = Path(files[0]["name"]).stem.rsplit(" - part", 1)[0] + ".zip"
        return send_file(archive, as_attachment=True, download_name=name)

    return app
