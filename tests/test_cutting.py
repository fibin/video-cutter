import pytest

from video_cutter.ffmpeg_tools import FFmpegError, cut_and_join, probe
from video_cutter.timecode import Segment


def test_probe(sample_video, silent_video):
    info = probe(sample_video)
    assert info.duration == pytest.approx(10, abs=0.1)
    assert info.has_audio
    assert not probe(silent_video).has_audio


def test_probe_rejects_non_video(tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("hello")
    with pytest.raises(FFmpegError):
        probe(bad)


def test_cut_and_join_duration_and_progress(sample_video, tmp_path):
    updates = []
    out = cut_and_join(
        sample_video,
        [Segment(1, 3), Segment(6.5, 8), Segment(0, 0.5)],
        tmp_path / "out.mp4",
        on_progress=lambda f, piece, total: updates.append((f, piece, total)),
    )
    info = probe(out)
    # 2 + 1.5 + 0.5 seconds; allow one frame of slack at 25 fps.
    assert info.duration == pytest.approx(4.0, abs=0.08)
    assert info.has_audio
    assert updates[0] == (0.0, 1, 3)
    assert updates[-1] == (1.0, 3, 3)
    fractions = [u[0] for u in updates]
    assert fractions == sorted(fractions)
    assert {u[1] for u in updates} >= {1, 3}


def test_cut_cuts_on_exact_frame(sample_video, tmp_path):
    """Starting mid-GOP (keyframe only at 0s) must still start at the requested frame."""
    out = cut_and_join(sample_video, [Segment(4.0, 5.0)], tmp_path / "one.mp4")
    assert probe(out).duration == pytest.approx(1.0, abs=0.05)


def test_cut_video_without_audio(silent_video, tmp_path):
    out = cut_and_join(silent_video, [Segment(0, 1), Segment(3, 4)], tmp_path / "silent-out.mp4")
    info = probe(out)
    assert info.duration == pytest.approx(2.0, abs=0.08)
    assert not info.has_audio
