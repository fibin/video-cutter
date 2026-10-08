"""In-memory registry of sources and background jobs with progress."""

from __future__ import annotations

import os
import re
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

    def set_detail(self, key: str, **params: Any) -> None:
        self.detail = {"key": key, "params": params}

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["elapsed"] = round(time.time() - self.started_at, 1)
        return data


class Registry:
    def __init__(self, data_dir: Path, parallel_jobs: int | None = None):
        self.data_dir = data_dir
        self.sources: dict[str, Source] = {}
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._encode_slots = threading.Semaphore(parallel_jobs or default_parallel_jobs())

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
            except Exception as exc:  # unexpected: still show something useful
                job.error = UserError("unexpected", detail=f"{exc}\n{traceback.format_exc(limit=3)}").to_json()
                job.state = "error"

        threading.Thread(target=run, daemon=True).start()
        return job


def safe_filename(name: str, fallback: str = "video") -> str:
    """Keep letters (any alphabet), digits, spaces, dots, dashes and underscores."""
    cleaned = re.sub(r"[^\w\s.\-]", "_", name, flags=re.UNICODE).strip(" ._")
    return cleaned[:80] or fallback
