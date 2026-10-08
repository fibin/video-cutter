import pytest

pytest.importorskip("webview")  # pywebview is only installed on Windows and macOS

from video_cutter.desktop import DesktopApi  # noqa: E402
from video_cutter.jobs import Job, Registry  # noqa: E402


class FakeWindow:
    def __init__(self, answer):
        self.answer = answer
        self.asked = None

    def create_file_dialog(self, dialog_type, save_filename="", file_types=(), directory=""):
        self.asked = save_filename
        return self.answer


def make_api(tmp_path, answer, count=1):
    registry = Registry(tmp_path)
    files = []
    for i in range(count):
        path = tmp_path / f"result{i}.mp4"
        path.write_bytes(f"video{i}".encode())
        files.append({"path": str(path), "name": f"clip - part {i + 1:02d}.mp4"})
    job = Job(id="job1", kind="cut", state="done", result={"files": files})
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
    assert window.asked == "clip - part 01.mp4"
    assert res == {"saved": str(target.with_suffix(".mp4"))}
    assert target.with_suffix(".mp4").read_bytes() == b"video0"


def test_save_all_copies_every_file(tmp_path):
    folder = tmp_path / "picked"
    folder.mkdir()
    api, _ = make_api(tmp_path, (str(folder),), count=3)
    assert api.save_all("job1") == {"saved": str(folder), "count": 3}
    assert sorted(p.name for p in folder.iterdir()) == [f"clip - part {i:02d}.mp4" for i in (1, 2, 3)]


def test_save_result_cancelled(tmp_path):
    api, _ = make_api(tmp_path, None)
    assert api.save_result("job1") == {"cancelled": True}


def test_save_result_unknown_job(tmp_path):
    api, _ = make_api(tmp_path, None)
    assert api.save_result("nope") == {"error": "result_missing"}


def test_choose_output_dir_is_remembered(tmp_path):
    folder = tmp_path / "My videos"
    folder.mkdir()
    api, _ = make_api(tmp_path, (str(folder),))
    assert api.choose_output_dir() == {"output_dir": str(folder.resolve())}
    assert Registry(tmp_path).output_dir == folder.resolve()


def test_choose_output_dir_cancelled(tmp_path):
    api, _ = make_api(tmp_path, None)
    assert api.choose_output_dir() == {"cancelled": True}
