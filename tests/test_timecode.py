import pytest

from video_cutter.timecode import Segment, build_segments, format_time, parse_time


@pytest.mark.parametrize(
    "text, seconds",
    [("90", 90), ("1:30", 90), ("01:02:03", 3723), ("0:05.5", 5.5), ("0:05,25", 5.25), (12, 12)],
)
def test_parse_time(text, seconds):
    assert parse_time(text) == pytest.approx(seconds)


@pytest.mark.parametrize("text", ["", "abc", "1:2:3:4", "-5"])
def test_parse_time_rejects_garbage(text):
    with pytest.raises(ValueError):
        parse_time(text)


def test_format_time():
    assert format_time(5) == "00:05"
    assert format_time(65.25) == "01:05.25"
    assert format_time(3723) == "1:02:03"


def test_keep_mode_preserves_order_and_clamps_end():
    segs = build_segments([{"start": "5", "end": "8"}, {"start": "1", "end": "99"}], duration=10)
    assert segs == [Segment(5, 8), Segment(1, 10)]


def test_empty_end_means_until_the_end():
    assert build_segments([{"start": "7", "end": ""}], duration=10) == [Segment(7, 10)]


def test_remove_mode_inverts_and_merges_overlaps():
    segs = build_segments(
        [{"start": "6", "end": "8"}, {"start": "0", "end": "2"}, {"start": "7", "end": "9"}],
        duration=10,
        mode="remove",
    )
    assert segs == [Segment(2, 6), Segment(9, 10)]


@pytest.mark.parametrize(
    "raw",
    [[], [{"start": "5", "end": "3"}], [{"start": "11", "end": ""}]],
)
def test_invalid_segments(raw):
    with pytest.raises(ValueError):
        build_segments(raw, duration=10)


def test_removing_everything_is_an_error():
    with pytest.raises(ValueError):
        build_segments([{"start": "0", "end": ""}], duration=10, mode="remove")
