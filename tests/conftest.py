import subprocess
from pathlib import Path

import pytest

from video_cutter.ffmpeg_tools import ffmpeg_path


def make_video(path: Path, seconds: int = 10, audio: bool = True) -> Path:
    """Test clip whose frame number is visible, so cut points can be checked."""
    cmd = [
        ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size=320x240:rate=25:duration={seconds}",
    ]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "250", str(path)]
    subprocess.run(cmd, check=True)
    return path


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory) -> Path:
    return make_video(tmp_path_factory.mktemp("media") / "sample.mp4")


@pytest.fixture(scope="session")
def silent_video(tmp_path_factory) -> Path:
    return make_video(tmp_path_factory.mktemp("media") / "silent.mp4", seconds=6, audio=False)
