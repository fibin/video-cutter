import time
from urllib.parse import quote

import pytest

from video_cutter import app as app_module
from video_cutter.app import create_app
from video_cutter.ffmpeg_tools import probe


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path / "data")
    app.config["TESTING"] = True
    return app.test_client()


def wait_for(client, job_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").get_json()
        if job["state"] != "running":
            return job
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def upload(client, path, name="Мой ролик.mp4"):  # non-ASCII on purpose
    return client.post(
        "/api/upload",
        data=path.read_bytes(),
        headers={"X-Filename": quote(name), "Content-Type": "application/octet-stream"},
    )


def test_index_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Video Cutter" in res.get_data(as_text=True)


def test_upload_cut_download(client, sample_video, tmp_path):
    res = upload(client, sample_video)
    assert res.status_code == 200
    source = res.get_json()
    assert source["title"] == "Мой ролик"
    assert source["duration"] == pytest.approx(10, abs=0.1)

    video = client.get(source["video_url"], headers={"Range": "bytes=0-99"})
    assert video.status_code == 206

    res = client.post(
        "/api/cut",
        json={"source_id": source["id"], "segments": [{"start": "0:01", "end": "0:02"}, {"start": "8", "end": ""}]},
    )
    assert res.status_code == 200
    job = wait_for(client, res.get_json()["id"])
    assert job["state"] == "done", job["error"]
    assert job["percent"] == 100
    assert job["detail"] == "piece 2 of 2"

    download = client.get(job["result"]["download_url"])
    assert download.status_code == 200
    assert "attachment" in download.headers["Content-Disposition"]
    out = tmp_path / "downloaded.mp4"
    out.write_bytes(download.data)
    assert probe(out).duration == pytest.approx(3.0, abs=0.08)


def test_remove_mode(client, sample_video):
    source = upload(client, sample_video).get_json()
    res = client.post(
        "/api/cut",
        json={"source_id": source["id"], "segments": [{"start": "2", "end": "9"}], "mode": "remove"},
    )
    job = wait_for(client, res.get_json()["id"])
    assert job["state"] == "done", job["error"]
    assert job["result"]["pieces"] == 2


def test_bad_segments_rejected(client, sample_video):
    source = upload(client, sample_video).get_json()
    res = client.post("/api/cut", json={"source_id": source["id"], "segments": [{"start": "9", "end": "3"}]})
    assert res.status_code == 400
    assert "end must be after the start" in res.get_json()["error"]


def test_upload_non_video(client, tmp_path):
    bad = tmp_path / "x.txt"
    bad.write_text("not a video")
    res = upload(client, bad, "x.txt")
    assert res.status_code == 400


def test_link_download_uses_youtube_module(client, sample_video, monkeypatch):
    """The real download needs the internet; here yt-dlp is replaced by a copy of the sample."""

    def fake_download(url, folder, on_progress):
        folder.mkdir(parents=True, exist_ok=True)
        on_progress(0.5, 1024 * 1024, 3)
        target = folder / "source.mp4"
        target.write_bytes(sample_video.read_bytes())
        return target, "YouTube video"

    monkeypatch.setattr(app_module.youtube, "download", fake_download)
    res = client.post("/api/youtube", json={"url": "https://www.youtube.com/watch?v=abc"})
    job = wait_for(client, res.get_json()["id"])
    assert job["state"] == "done", job["error"]
    assert job["result"]["source"]["title"] == "YouTube video"


def test_link_must_be_url(client):
    res = client.post("/api/youtube", json={"url": "hello"})
    assert res.status_code == 400
