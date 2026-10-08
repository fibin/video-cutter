"""Parsing and formatting of time codes and segment lists."""

from __future__ import annotations

import re
from dataclasses import dataclass

_TIME_RE = re.compile(r"^\s*(?:(\d+):)?(?:(\d+):)?(\d+(?:[.,]\d+)?)\s*$")


@dataclass(frozen=True)
class Segment:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def parse_time(value: str | int | float) -> float:
    """Convert '90', '1:30', '01:01:30.5' or a number into seconds."""
    if isinstance(value, (int, float)):
        seconds = float(value)
    else:
        match = _TIME_RE.match(str(value))
        if not match:
            raise ValueError(f"Invalid time format: {value!r}")
        first, second, secs = match.groups()
        if second is not None:
            hours, minutes = int(first), int(second)
        elif first is not None:
            hours, minutes = 0, int(first)
        else:
            hours, minutes = 0, 0
        seconds = hours * 3600 + minutes * 60 + float(secs.replace(",", "."))
    if seconds < 0:
        raise ValueError("Time cannot be negative")
    return seconds


def format_time(seconds: float) -> str:
    """Format seconds as H:MM:SS.mmm (hours omitted when zero)."""
    millis = int(round(seconds * 1000))
    hours, rest = divmod(millis, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    text = f"{minutes:02d}:{secs:02d}"
    if millis:
        text += f".{millis:03d}".rstrip("0")
    return f"{hours}:{text}" if hours else text


def build_segments(raw: list[dict], duration: float | None, mode: str = "keep") -> list[Segment]:
    """Validate user segments and return the list of pieces to keep.

    mode="keep": the given segments are kept, in the given order.
    mode="remove": the given segments are cut out and the rest is kept.
    """
    if not raw:
        raise ValueError("Add at least one segment")
    segments = []
    for index, item in enumerate(raw, start=1):
        start = parse_time(item.get("start", ""))
        end_value = item.get("end", "")
        if end_value in ("", None):
            if duration is None:
                raise ValueError(f"Segment {index}: set the end")
            end = duration
        else:
            end = parse_time(end_value)
        if duration is not None:
            if start >= duration:
                raise ValueError(
                    f"Segment {index}: start {format_time(start)} is after the end of the video ({format_time(duration)})"
                )
            end = min(end, duration)
        if end <= start:
            raise ValueError(f"Segment {index}: the end must be after the start")
        segments.append(Segment(start, end))

    if mode == "keep":
        return segments
    if mode != "remove":
        raise ValueError(f"Unknown mode: {mode}")
    if duration is None:
        raise ValueError("Could not determine the video duration")

    keep: list[Segment] = []
    cursor = 0.0
    for seg in sorted(segments, key=lambda s: s.start):
        if seg.start > cursor:
            keep.append(Segment(cursor, seg.start))
        cursor = max(cursor, seg.end)
    if cursor < duration:
        keep.append(Segment(cursor, duration))
    # Drop slivers shorter than one frame at 60 fps.
    keep = [s for s in keep if s.duration > 1 / 60]
    if not keep:
        raise ValueError("Nothing is left after removing these segments")
    return keep
