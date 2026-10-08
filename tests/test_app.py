import io
import time
import zipfile
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
        if job["state"] not in ("running", "queued"):
            return job
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def upload(client, path, name="Мой ролик.mp4"):  # non-ASCII on purpose
    return client.post(
        "/api/upload",
        data=path.read_bytes(),
        headers={"X-Filename": quote(name), "Content-Type": "application/octet-stream"},
    )


def download(client, url, tmp_path, name):
    res = client.get(url)
    assert res.status_code == 200
    out = tmp_path / name
    out.write_bytes(res.data)
    return out


def test_index_and_translations_served(client):
    assert "Video Cutter" in client.get("/").get_data(as_text=True)
    i18n = client.get("/static/i18n.json").get_json()
    assert set(i18n) == {"en", "uk"}


def test_upload_cut_download(client, sample_video, tmp_path):
    res = upload(client, sample_video)
    assert res.status_code == 200
    source = res.get_json()
    assert source["title"] == "Мой ролик"
    assert source["duration"] == pytest.approx(10, abs=0.1)

    video = client.get(source["video_url"], headers={"Range": "bytes=0-99"})
    assert video.status_code == 206

    # Segments are cut in the order given, not sorted by time.
    res = client.post(
        "/api/cut",
        json={"source_id": source["id"], "segments": [{"start": "8", "end": ""}, {"start": "0:01", "end": "0:02"}]},
    )
    assert res.status_code == 200
    job = wait_for(client, res.get_json()["id"])
    assert job["state"] == "done", job["error"]
    assert job["percent"] == 100
    assert job["detail"] == {"key": "detail_piece", "params": {"piece": 2, "total": 2}}
    files = job["result"]["files"]
    assert len(files) == 1

    res = client.get(files[0]["download_url"])
    assert "attachment" in res.headers["Content-Disposition"]
    out = download(client, files[0]["download_url"], tmp_path, "downloaded.mp4")
    assert probe(out).duration == pytest.approx(3.0, abs=0.08)


def test_separate_files_and_zip(client, sample_video, tmp_path):
    source = upload(client, sample_video).get_json()
    res = client.post(
        "/api/cut",
        json={
            "source_id": source["id"],
            "segments": [{"start": "1", "end": "2"}, {"start": "5", "end": "7"}, {"start": "9", "end": ""}],
            "separate": True,
        },
    )
    job = wait_for(client, res.get_json()["id"])
    assert job["state"] == "done", job["error"]
    files = job["result"]["files"]
    assert [f["name"] for f in files] == [
        "Мой ролик - part 01.mp4",
        "Мой ролик - part 02.mp4",
        "Мой ролик - part 03.mp4",
    ]
    durations = [probe(download(client, f["download_url"], tmp_path, f"p{i}.mp4")).duration for i, f in enumerate(files)]
    assert durations == pytest.approx([1, 2, 1], abs=0.08)

    res = client.get(f"/api/jobs/{job['id']}/zip")
    assert res.status_code == 200
    with zipfile.ZipFile(io.BytesIO(res.data)) as zf:
        assert sorted(zf.namelist()) == sorted(f["name"] for f in files)


def test_remove_mode(client, sample_video):
    source = upload(client, sample_video).get_json()
    res = client.post(
        "/api/cut",
        json={"source_id": source["id"], "segments": [{"start": "2", "end": "9"}], "mode": "remove"},
    )
    job = wait_for(client, res.get_json()["id"])
    assert job["state"] == "done", job["error"]
    assert job["result"]["pieces"] == 2


def test_bad_segments_rejected_with_message_key(client, sample_video):
    source = upload(client, sample_video).get_json()
    res = client.post("/api/cut", json={"source_id": source["id"], "segments": [{"start": "9", "end": "3"}]})
    assert res.status_code == 400
    err = res.get_json()["error"]
    assert err["key"] == "segment_end_before_start"
    assert err["params"] == {"index": 1}


def test_upload_non_video(client, tmp_path):
    bad = tmp_path / "x.txt"
    bad.write_text("not a video")
    res = upload(client, bad, "x.txt")
    assert res.status_code == 400
    assert res.get_json()["error"]["key"] == "not_a_video"


def test_join_mixed_videos(client, sample_video, silent_video, small_video, tmp_path):
    """Different sizes and a video without sound still join into one clip."""
    ids = [upload(client, v, f"v{i}.mp4").get_json()["id"] for i, v in enumerate([sample_video, silent_video, small_video])]
    res = client.post("/api/join", json={"source_ids": ids})
    job = wait_for(client, res.get_json()["id"])
    assert job["state"] == "done", job["error"]
    assert job["detail"]["key"] == "detail_video"
    out = download(client, job["result"]["files"][0]["download_url"], tmp_path, "joined.mp4")
    info = probe(out)
    assert info.duration == pytest.approx(10 + 6 + 3, abs=0.2)
    assert info.has_audio
    assert (info.width, info.height) == (320, 240)


def test_join_needs_two_videos(client, sample_video):
    source = upload(client, sample_video).get_json()
    res = client.post("/api/join", json={"source_ids": [source["id"]]})
    assert res.status_code == 400
    assert res.get_json()["error"]["key"] == "join_need_two"


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
    assert res.get_json()["error"]["key"] == "link_invalid"


def test_output_folder_setting(client, sample_video, tmp_path):
    settings = client.get("/api/settings").get_json()
    assert settings["is_default"]
    assert settings["output_dir"] == settings["default_output_dir"]

    target = tmp_path / "My clips"
    res = client.post("/api/settings", json={"output_dir": str(target)})
    assert res.status_code == 200
    assert res.get_json()["output_dir"] == str(target.resolve())
    assert target.is_dir()

    # Results go into the chosen folder; a second cut never overwrites the first.
    source = upload(client, sample_video).get_json()
    names = []
    for _ in range(2):
        res = client.post("/api/cut", json={"source_id": source["id"], "segments": [{"start": "1", "end": "2"}]})
        job = wait_for(client, res.get_json()["id"])
        assert job["state"] == "done", job["error"]
        names.append(job["result"]["files"][0]["name"])
    assert names == ["Мой ролик - cut.mp4", "Мой ролик - cut (2).mp4"]
    assert sorted(p.name for p in target.iterdir()) == sorted(names)

    res = client.post("/api/settings", json={"output_dir": ""})
    assert res.get_json()["is_default"]


def test_output_folder_must_be_absolute(client):
    res = client.post("/api/settings", json={"output_dir": "relative/folder"})
    assert res.status_code == 400
    assert res.get_json()["error"]["key"] == "output_dir_invalid"


def test_failed_job_leaves_no_empty_file(client, sample_video, tmp_path, monkeypatch):
    target = tmp_path / "out"
    client.post("/api/settings", json={"output_dir": str(target)})
    source = upload(client, sample_video).get_json()

    def broken(*args, **kwargs):
        raise app_module.ffmpeg_tools.FFmpegError("ffmpeg_failed", code=1)

    monkeypatch.setattr(app_module.ffmpeg_tools, "cut_and_join", broken)
    res = client.post("/api/cut", json={"source_id": source["id"], "segments": [{"start": "1", "end": "2"}]})
    assert wait_for(client, res.get_json()["id"])["state"] == "error"
    assert list(target.iterdir()) == []
