import pytest

pytest.importorskip("webview")  # pywebview is only installed on Windows and macOS

from video_cutter.desktop import DesktopApi  # noqa: E402
from video_cutter.jobs import Job, Registry  # noqa: E402


class FakeWindow:
    def __init__(self, answer):
        self.answer = answer
        self.asked = None

    def create_file_dialog(self, dialog_type, save_filename="", file_types=()):
        self.asked = save_filename
        return self.answer


def make_api(tmp_path, answer):
    registry = Registry(tmp_path)
    result = tmp_path / "result.mp4"
    result.write_bytes(b"video")
    job = Job(id="job1", kind="cut", state="done", result={"path": str(result), "filename": "clip - cut.mp4"})
    registry.jobs[job.id] = job
    api = DesktopApi(registry)
    window = FakeWindow(answer)
    api.attach(window)
    return api, window


def test_save_result_copies_file_and_adds_extension(tmp_path):
    target = tmp_path / "out" / "my clip"
    target.parent.mkdir()
    api, window = make_api(tmp_path, (str(target),))
    res = api.save_result("job1")
    assert window.asked == "clip - cut.mp4"
    assert res == {"saved": str(target.with_suffix(".mp4"))}
    assert target.with_suffix(".mp4").read_bytes() == b"video"


def test_save_result_cancelled(tmp_path):
    api, _ = make_api(tmp_path, None)
    assert api.save_result("job1") == {"cancelled": True}


def test_save_result_unknown_job(tmp_path):
    api, _ = make_api(tmp_path, None)
    assert "error" in api.save_result("nope")
