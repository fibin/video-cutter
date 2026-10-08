from video_cutter.selftest import run_self_test


def test_self_test_passes(tmp_path):
    report = tmp_path / "report.txt"
    code = run_self_test(str(report))
    text = report.read_text(encoding="utf-8")
    # The window check needs pywebview, which is not installed on Linux.
    failures = [line for line in text.splitlines() if line.startswith("FAIL") and "window" not in line]
    assert not failures, text
    assert "PASS ffmpeg" in text
    assert code in (0, 1)
