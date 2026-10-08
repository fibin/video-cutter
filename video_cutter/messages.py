"""User-facing messages.

The server never sends finished sentences to the UI. It sends a message key plus
parameters, and the page translates them (see static/i18n.json). English texts
here are used for logs, the self-test report and tests.
"""

from __future__ import annotations

from typing import Any

EN: dict[str, str] = {
    # errors
    "time_invalid": "Invalid time format: {value}",
    "time_negative": "Time cannot be negative",
    "segments_empty": "Add at least one segment",
    "segment_end_missing": "Segment {index}: set the end",
    "segment_start_after_video": "Segment {index}: start {start} is after the end of the video ({duration})",
    "segment_end_before_start": "Segment {index}: the end must be after the start",
    "mode_unknown": "Unknown mode: {mode}",
    "duration_unknown": "Could not determine the video duration",
    "nothing_left": "Nothing is left after removing these segments",
    "ffmpeg_missing": "ffmpeg not found. Install the dependencies: pip install -r requirements.txt",
    "not_a_video": "Could not read the file. Is it really a video?",
    "no_video_track": "The file has no video track",
    "no_segments": "No segments to cut",
    "ffmpeg_failed": "ffmpeg failed (exit code {code})",
    "ytdlp_missing": "yt-dlp is not installed. Run: pip install -r requirements.txt",
    "download_failed": "Could not download the video",
    "download_file_missing": "The video was downloaded but the file was not found",
    "link_invalid": "Paste a link that starts with http:// or https://",
    "source_missing": "This video is no longer available. Add it again.",
    "join_need_two": "Add at least two videos to join",
    "unexpected": "Something went wrong",
    "result_missing": "The result is not available any more",
    # job stages and details
    "stage_queued": "Waiting in queue",
    "stage_downloading": "Downloading",
    "stage_checking": "Checking the file",
    "stage_cutting": "Cutting",
    "stage_joining": "Joining",
    "detail_piece": "piece {piece} of {total}",
    "detail_video": "video {piece} of {total}",
    "detail_download": "{speed} B/s, {eta} s left",
}


def render(key: str, params: dict[str, Any] | None = None) -> str:
    return EN.get(key, key).format(**(params or {}))


class UserError(ValueError):
    """An error the user can understand and act on, carried as a translatable key."""

    def __init__(self, key: str, detail: str = "", **params: Any):
        if key not in EN:
            raise KeyError(f"unknown message key: {key}")
        self.key = key
        self.params = params
        self.detail = detail
        text = render(key, params)
        super().__init__(f"{text}\n{detail}" if detail else text)

    def to_json(self) -> dict[str, Any]:
        return {"key": self.key, "params": self.params, "detail": self.detail, "text": str(self)}
