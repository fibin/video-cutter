"""In-memory registry of sources and background jobs with progress."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .messages import UserError


def default_parallel_jobs() -> int:
    """How many encodes may run at once. ffmpeg already uses several cores per encode,
    so two at a time keeps the machine responsive; the rest wait in a queue."""
    return int(os.environ.get("VIDEO_CUTTER_PARALLEL", "2"))


@dataclass
class Source:
    id: str
    path: Path
    title: str
    duration: float
    has_audio: bool
    info: Any = None  # ffmpeg_tools.MediaInfo


@dataclass
class Job:
    id: str
    kind: str  # "download" | "cut" | "join"
    state: str = "running"  # queued | running | done | error
    stage: str = ""  # message key, see messages.EN
    percent: float | None = 0.0
    detail: dict[str, Any] | None = None  # {"key": ..., "params": {...}}
    error: dict[str, Any] | None = None  # UserError.to_json()
    result: dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    partial: list[Path] = field(default_factory=list)  # outputs to delete if the job fails

    def set_detail(self, key: str, **params: Any) -> None:
        self.detail = {"key": key, "params": params}

    def remove_partial(self) -> None:
        for path in self.partial:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("partial")
        data["elapsed"] = round(time.time() - self.started_at, 1)
        return data


class Registry:
    def __init__(self, data_dir: Path, parallel_jobs: int | None = None):
        self.data_dir = data_dir
        self.sources: dict[str, Source] = {}
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._encode_slots = threading.Semaphore(parallel_jobs or default_parallel_jobs())
        self._settings_file = data_dir / "settings.json"
        try:
            self.settings: dict[str, Any] = json.loads(self._settings_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.settings = {}

    @property
    def default_output_dir(self) -> Path:
        return self.data_dir / "results"

    @property
    def output_dir(self) -> Path:
        """Where finished videos are written; the user can change it in the UI."""
        custom = self.settings.get("output_dir")
        return Path(custom) if custom else self.default_output_dir

    def set_output_dir(self, folder: str | None) -> Path:
        """Remember `folder` as the output folder (None or "" resets to the default)."""
        if folder:
            path = Path(folder).expanduser()
            if not path.is_absolute():
                raise UserError("output_dir_invalid", path=folder)
            try:
                path.mkdir(parents=True, exist_ok=True)
                probe = path / f".video-cutter-{uuid.uuid4().hex[:6]}"
                probe.write_bytes(b"")
                probe.unlink()
            except OSError as exc:
                raise UserError("output_dir_invalid", path=folder, detail=str(exc)) from None
            self.settings["output_dir"] = str(path.resolve())
        else:
            self.settings.pop("output_dir", None)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._settings_file.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        return self.output_dir

    def reserve_path(self, folder: Path, stem: str, suffix: str = ".mp4", is_dir: bool = False) -> Path:
        """A new, not yet existing path "stem.mp4", "stem (2).mp4", ... created right away,
        so parallel jobs never pick the same name and old results are never overwritten."""
        folder.mkdir(parents=True, exist_ok=True)
        with self._lock:
            n = 1
            while True:
                name = stem if n == 1 else f"{stem} ({n})"
                path = folder / (name if is_dir else name + suffix)
                if not path.exists():
                    path.mkdir() if is_dir else path.touch()
                    return path
                n += 1

    def new_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def source_dir(self, source_id: str) -> Path:
        return self.data_dir / "sources" / source_id

    def add_source(self, source: Source) -> Source:
        with self._lock:
            self.sources[source.id] = source
        return source

    def get_source(self, source_id: str) -> Source | None:
        return self.sources.get(source_id)

    def get_job(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def start_job(self, kind: str, work: Callable[[Job], dict[str, Any]], queued: bool = False) -> Job:
        """Run `work` in a background thread. `queued` jobs (encodes) wait for a free slot."""
        job = Job(id=self.new_id(), kind=kind)
        if queued:
            job.state, job.stage, job.percent = "queued", "stage_queued", None
        with self._lock:
            self.jobs[job.id] = job

        def run() -> None:
            try:
                if queued:
                    with self._encode_slots:
                        job.state, job.started_at = "running", time.time()
                        job.result = work(job) or {}
                else:
                    job.result = work(job) or {}
                job.percent = 100.0
                job.state = "done"
            except UserError as exc:
                job.error = exc.to_json()
                job.state = "error"
                job.remove_partial()
            except Exception as exc:  # unexpected: still show something useful
                job.error = UserError("unexpected", detail=f"{exc}\n{traceback.format_exc(limit=3)}").to_json()
                job.state = "error"
                job.remove_partial()

        threading.Thread(target=run, daemon=True).start()
        return job


def safe_filename(name: str, fallback: str = "video") -> str:
    """Keep letters (any alphabet), digits, spaces, dots, dashes and underscores."""
    cleaned = re.sub(r"[^\w\s.\-]", "_", name, flags=re.UNICODE).strip(" ._")
    return cleaned[:80] or fallback
