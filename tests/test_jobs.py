import threading
import time

from video_cutter.jobs import Registry
from video_cutter.messages import UserError


def wait(job, timeout=5):
    deadline = time.time() + timeout
    while job.state in ("queued", "running") and time.time() < deadline:
        time.sleep(0.01)


def test_queue_limits_parallel_encodes(tmp_path):
    registry = Registry(tmp_path, parallel_jobs=2)
    release = threading.Event()
    running = []
    peak = []

    def work(job):
        running.append(job.id)
        peak.append(len(running))
        release.wait(5)
        running.remove(job.id)
        return {}

    jobs = [registry.start_job("cut", work, queued=True) for _ in range(3)]
    time.sleep(0.2)
    assert sorted(j.state for j in jobs) == ["queued", "running", "running"]
    assert next(j for j in jobs if j.state == "queued").stage == "stage_queued"
    release.set()
    for job in jobs:
        wait(job)
    assert [j.state for j in jobs] == ["done"] * 3
    assert max(peak) == 2


def test_user_error_becomes_message_key(tmp_path):
    registry = Registry(tmp_path)

    def work(job):
        raise UserError("nothing_left")

    job = registry.start_job("cut", work)
    wait(job)
    assert job.state == "error"
    assert job.error["key"] == "nothing_left"


def test_unexpected_error_is_reported(tmp_path):
    registry = Registry(tmp_path)

    def work(job):
        raise RuntimeError("boom")

    job = registry.start_job("cut", work)
    wait(job)
    assert job.error["key"] == "unexpected"
    assert "boom" in job.error["detail"]
