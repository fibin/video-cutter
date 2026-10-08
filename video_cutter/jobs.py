"""In-memory registry of sources and background jobs with progress."""

from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class Source:
    id: str
    path: Path
    title: str
    duration: float
    has_audio: bool


@dataclass
class Job:
    id: str
    kind: str  # "download" | "cut"
    state: str = "running"  # running | done | error
    stage: str = ""
    percent: float | None = 0.0
    detail: str = ""
    error: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["elapsed"] = round(time.time() - self.started_at, 1)
        return data


class Registry:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.sources: dict[str, Source] = {}
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

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

    def start_job(self, kind: str, work: Callable[[Job], dict[str, Any]]) -> Job:
        job = Job(id=self.new_id(), kind=kind)
        with self._lock:
            self.jobs[job.id] = job

        def run() -> None:
            try:
                job.result = work(job) or {}
                job.percent = 100.0
                job.state = "done"
            except Exception as exc:  # shown to the user in the UI
                job.error = str(exc)
                job.state = "error"

        threading.Thread(target=run, daemon=True).start()
        return job


def safe_filename(name: str, fallback: str = "video") -> str:
    """Keep letters (any alphabet), digits, spaces, dots, dashes and underscores."""
    cleaned = re.sub(r"[^\w\s.\-]", "_", name, flags=re.UNICODE).strip(" ._")
    return cleaned[:80] or fallback
