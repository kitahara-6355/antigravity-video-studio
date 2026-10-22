"""書き出しの左上にロゴが無いかを画素で確かめる道具（backend/logo_check.py）の計算部分。"""
import pytest

import logo_check


def test_output_time_maps_back_through_the_kept_ranges():
    ranges = [(10.0, 20.0), (50.0, 55.0)]
    assert logo_check.source_time(ranges, 3.0) == 13.0
    assert logo_check.source_time(ranges, 12.0) == 52.0
    with pytest.raises(ValueError):
        logo_check.source_time(ranges, 16.0)


def test_a_white_logo_on_black_is_far_over_the_limit():
    w, h = logo_check.CORNER[2:]
    black = bytes(w * h)
    logo = bytes([255] * (w * h // 2) + [0] * (w * h - w * h // 2))
    assert logo_check.diff(black, black) == 0
    assert logo_check.diff(logo, black) > logo_check.LIMIT
