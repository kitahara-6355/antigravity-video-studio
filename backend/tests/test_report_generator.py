import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
import os
import sys
from pathlib import Path

cwd = Path.cwd()
workspace_root = str(cwd)
workspace_backend = str(cwd / 'backend')
if workspace_root not in sys.path:
    sys.path.insert(0, workspace_root)
if workspace_backend not in sys.path:
    sys.path.insert(0, workspace_backend)

import backend.agents.orchestration.report_generator as rg

def test_constants():
    assert hasattr(rg, 'WORKSPACE_DIR')
    assert hasattr(rg, 'ORCHESTRATION_DIR')
    assert hasattr(rg, 'TASK_QUEUE_PATH')
    assert hasattr(rg, 'FLASH_SESSION_PATH')
    assert hasattr(rg, 'FLASH_REPORTS_PATH')
    assert hasattr(rg, 'OFFICIAL_ARTIFACT_DIR')
    assert hasattr(rg, 'REPORT_BASE_DIR')
    assert hasattr(rg, 'PERIODIC_REPORT_DIR')
    assert hasattr(rg, 'BULLETIN_REPORT_DIR')
    assert hasattr(rg, 'RANKING_REPORT_DIR')

def test_parse_iso_datetime():
    dt = rg.parse_iso_datetime('2026-06-14T12:00:00Z')
    assert dt == datetime(2026, 6, 14, 12, 0, 0, tzinfo=timezone.utc)
    dt2 = rg.parse_iso_datetime('2026-06-14T12:00:00+09:00')
    assert dt2.hour == 12
    assert dt2.tzinfo is not None
    assert rg.parse_iso_datetime('') is None
    assert rg.parse_iso_datetime(None) is None
    assert rg.parse_iso_datetime('invalid-date') is None

def test_format_duration():
    assert rg.format_duration(3665) == '1h 1m'
    assert rg.format_duration(125) == '2m 5s'
    assert rg.format_duration(45) == '45s'
    assert rg.format_duration(0) == '0s'

def test_extract_date(tmp_path):
    assert rg.extract_date('daily_report_20260522.md') == '2026-05-22'
    assert rg.extract_date('report_20260522_extra.md') == '2026-05-22'
    dummy_file = tmp_path / 'report_no_date.md'
    dummy_file.write_text('dummy content')
    # 日付ラベルは JST 固定。期待値をローカル時刻で作ると、UTC 環境（CI）では
    # 00:00〜09:00 JST の時間帯だけ 1 日ずれて落ちる（2026-07-26 の CI で発生）。
    from backend.agents.orchestration.jst_time import jst_date

    expected_date = jst_date(os.path.getmtime(str(dummy_file)))
    assert rg.extract_date(str(dummy_file)) == expected_date
    res = rg.extract_date('non_existent_file.md')
    assert isinstance(res, str)

def test_get_week_range_str():
    res = rg.get_week_range_str('2026-05-22')
    assert '2026-05-18' in res
    assert '2026-05-24' in res
    assert '第21週' in res
    assert rg.get_week_range_str('invalid') == 'その他の週'
    assert rg.get_week_range_str(None) == 'その他の週'

def test_find_latest_brain_report():
    with patch('os.path.exists', return_value=True):
        with patch('glob.glob', return_value=['C:\\path\\daily_report_20260523.md', 'C:\\path\\daily_report_20260524.md']):
            with patch('os.path.getmtime', side_effect=[100, 200]):
                latest = rg.find_latest_brain_report()
                assert latest == 'C:\\path\\daily_report_20260524.md'
