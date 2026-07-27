"""jst_time — ダッシュボードの日付・時刻を JST に固定するヘルパのテスト

実行環境のローカルタイムゾーン（開発機=JST / CI=UTC）に結果が左右されないことを検証する。
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

ORCHESTRATION_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "agents", "orchestration")
)
if ORCHESTRATION_DIR not in sys.path:
    sys.path.insert(0, ORCHESTRATION_DIR)

from backend.agents.orchestration.jst_time import (  # noqa: E402
    JST,
    jst_compact_date,
    jst_date,
    jst_from_timestamp,
    jst_stamp,
    now_jst,
    parse_jst,
)


def test_jst_is_utc_plus_9():
    assert JST.utcoffset(None) == timedelta(hours=9)


def test_now_jst_is_aware_and_matches_utc():
    """now_jst() は UTC+9。ローカルタイムゾーンに依存しない。"""
    n = now_jst()
    assert n.tzinfo is not None, "naive datetime を返してはいけない（ローカル時刻依存になる）"
    assert n.utcoffset() == timedelta(hours=9)

    expected = datetime.now(timezone.utc) + timedelta(hours=9)
    # 壁時計の表示値が UTC+9 と一致すること（±5秒）
    diff = abs((n.replace(tzinfo=None) - expected.replace(tzinfo=None)).total_seconds())
    assert diff < 5, f"UTC+9 とずれている: {n} vs {expected}"


def test_jst_from_timestamp_is_absolute():
    """epoch → JST は絶対変換。実行環境のタイムゾーンで変わらない。"""
    assert jst_from_timestamp(0).strftime("%Y-%m-%d %H:%M") == "1970-01-01 09:00"
    # 2026-07-26 00:30 JST = 2026-07-25 15:30 UTC
    ts = datetime(2026, 7, 25, 15, 30, tzinfo=timezone.utc).timestamp()
    assert jst_from_timestamp(ts).strftime("%Y-%m-%d %H:%M") == "2026-07-26 00:30"


def test_date_helpers_use_jst_day_boundary():
    """UTC 換算では前日でも、JST の日付を返す。"""
    # 2026-07-26 05:00 JST = 2026-07-25 20:00 UTC → JST では 07-26
    dt = datetime(2026, 7, 25, 20, 0, tzinfo=timezone.utc)
    assert jst_date(dt) == "2026-07-26"
    assert jst_compact_date(dt) == "20260726"
    assert jst_stamp(dt) == "2026-07-26 05:00 JST"


def test_date_helpers_accept_epoch():
    ts = datetime(2026, 7, 25, 20, 0, tzinfo=timezone.utc).timestamp()
    assert jst_date(ts) == "2026-07-26"
    assert jst_compact_date(ts) == "20260726"


def test_date_helpers_default_to_now():
    assert jst_date() == now_jst().strftime("%Y-%m-%d")
    assert len(jst_compact_date()) == 8


def test_naive_datetime_is_treated_as_jst():
    """既存ログの naive な JST 時刻を渡しても、UTC 扱いにならない。"""
    naive = datetime(2026, 7, 26, 5, 0)
    assert jst_date(naive) == "2026-07-26"
    assert jst_stamp(naive) == "2026-07-26 05:00 JST"


def test_parse_jst_roundtrip():
    dt = parse_jst("2026-05-28 12:05 JST")
    assert dt is not None
    assert dt.utcoffset() == timedelta(hours=9)
    assert jst_stamp(dt) == "2026-05-28 12:05 JST"


@pytest.mark.parametrize("bad", ["", "not a date", None, 123, "2026-13-99 99:99 JST"])
def test_parse_jst_rejects_garbage(bad):
    assert parse_jst(bad) is None
