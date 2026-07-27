import json
import logging
from pathlib import Path
from datetime import datetime, date, timedelta
import pytest
from unittest.mock import patch, MagicMock

from usage_tracker.api_usage_tracker import (
    APIUsageTracker,
    EscalationLevel,
    FREE_TIER_LIMIT,
    record_api_call,
    get_usage_status,
    should_block_api,
    usage_tracker
)

@pytest.fixture
def temp_usage_file(tmp_path):
    """テスト用の一時的な使用量ファイルパスを提供するフィクスチャ"""
    return tmp_path / "temp_daily_usage.json"

def test_init_default_and_custom_path(temp_usage_file):
    """初期化とデフォルトデータのロードをテスト"""
    tracker = APIUsageTracker(usage_path=temp_usage_file)
    assert tracker.usage_path == temp_usage_file
    assert tracker._data == {"daily": {}, "limit": FREE_TIER_LIMIT}
    assert tracker._last_escalation is None
    assert tracker.override_active is False
    assert tracker.thresholds == {"info": 0.60, "warning": 0.80, "critical": 0.95}

def test_load_exception_handling(temp_usage_file):
    """JSON読み込み時の例外処理をテスト"""
    temp_usage_file.write_text("invalid json content", encoding="utf-8")
    tracker = APIUsageTracker(usage_path=temp_usage_file)
    assert tracker._data == {"daily": {}, "limit": FREE_TIER_LIMIT}

def test_save_creates_directory_and_file(temp_usage_file):
    """保存時に親ディレクトリとファイルが正しく作成されるかテスト"""
    nested_path = temp_usage_file.parent / "nested_dir" / "usage.json"
    tracker = APIUsageTracker(usage_path=nested_path)
    tracker._save()
    
    assert nested_path.exists()
    with open(nested_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data == {"daily": {}, "limit": FREE_TIER_LIMIT}

def test_record_calls_and_check_escalation(temp_usage_file):
    """record_calls と 4段階エスカレーション判定をテスト"""
    tracker = APIUsageTracker(usage_path=temp_usage_file)
    today = date.today().isoformat()
    
    # 1. 最初の記録 (NORMAL: 60%未満)
    with patch("usage_tracker.api_usage_tracker.logger") as mock_logger:
        tracker.record_calls(count=10, source="test_source")
        assert tracker._data["daily"][today]["total"] == 10
        assert tracker._data["daily"][today]["sources"]["test_source"] == 10
        assert tracker._last_escalation == EscalationLevel.NORMAL
        mock_logger.info.assert_not_called()
        mock_logger.warning.assert_not_called()
        mock_logger.error.assert_not_called()
        mock_logger.critical.assert_not_called()

    # 2. 60%に達する記録 (INFO: 60%以上, 300回)
    # 300 / 500 = 60%
    with patch("usage_tracker.api_usage_tracker.logger") as mock_logger:
        tracker.record_calls(count=290, source="another_source")
        assert tracker._data["daily"][today]["total"] == 300
        assert tracker._data["daily"][today]["sources"]["another_source"] == 290
        assert tracker._last_escalation == EscalationLevel.INFO
        mock_logger.info.assert_called_once()

        # 同じレベルでは繰り返さないことを確認
        mock_logger.reset_mock()
        tracker.record_calls(count=5, source="another_source")
        mock_logger.info.assert_not_called()

    # 3. 80%に達する記録 (WARNING: 80%以上, 400回)
    # 405 / 500 = 81%
    with patch("usage_tracker.api_usage_tracker.logger") as mock_logger:
        tracker.record_calls(count=100, source="test_source")
        assert tracker._last_escalation == EscalationLevel.WARNING
        mock_logger.warning.assert_called_once()

    # 4. 95%に達する記録 (BLOCKED: 95%以上, 475回)
    # 475 / 500 = 95%
    with patch("usage_tracker.api_usage_tracker.logger") as mock_logger:
        tracker.record_calls(count=70, source="test_source")
        assert tracker._last_escalation == EscalationLevel.BLOCKED
        mock_logger.error.assert_called_once()

    # 5. 100%に達する記録 (BANNED: 100%以上, 500回)
    with patch("usage_tracker.api_usage_tracker.logger") as mock_logger:
        tracker.record_calls(count=25, source="test_source")
        assert tracker._last_escalation == EscalationLevel.BANNED
        mock_logger.critical.assert_called_once()

def test_should_block(temp_usage_file):
    """should_block メソッドの判定テスト (95% サスペンド, 100% Banned)"""
    tracker = APIUsageTracker(usage_path=temp_usage_file)
    assert not tracker.should_block()
    
    # サスペンド閾値未満
    tracker.record_calls(count=474)
    assert not tracker.should_block()
    
    # 95% 到達 (自動サスペンド)
    tracker.record_calls(count=1)
    assert tracker.should_block()
    
    # オーバーライドを有効にする
    tracker.set_override(True)
    assert not tracker.should_block()
    
    # 100% に到達 (強制禁止)
    tracker.record_calls(count=25)
    assert tracker.should_block()  # オーバーライドが有効でも100%はブロックされる

def test_get_escalation_level(temp_usage_file):
    """get_escalation_level の正確な判定テスト"""
    tracker = APIUsageTracker(usage_path=temp_usage_file)
    assert tracker.get_escalation_level() == EscalationLevel.NORMAL
    
    # 60%未満 (299回)
    tracker.record_calls(count=299)
    assert tracker.get_escalation_level() == EscalationLevel.NORMAL
    
    # 60% (300回)
    tracker.record_calls(count=1)
    assert tracker.get_escalation_level() == EscalationLevel.INFO
    
    # 80% (400回)
    tracker.record_calls(count=100)
    assert tracker.get_escalation_level() == EscalationLevel.WARNING
    
    # 95% (475回)
    tracker.record_calls(count=75)
    assert tracker.get_escalation_level() == EscalationLevel.BLOCKED
    
    # 100% (500回)
    tracker.record_calls(count=25)
    assert tracker.get_escalation_level() == EscalationLevel.BANNED

def test_get_today_usage(temp_usage_file):
    """get_today_usage の戻り値の構造と中身をテスト"""
    tracker = APIUsageTracker(usage_path=temp_usage_file)
    today = date.today().isoformat()
    
    # 初期状態
    usage = tracker.get_today_usage()
    assert usage["date"] == today
    assert usage["used"] == 0
    assert usage["limit"] == FREE_TIER_LIMIT
    assert usage["remaining"] == FREE_TIER_LIMIT
    assert usage["usage_pct"] == 0.0
    assert usage["escalation_level"] == "normal"
    assert usage["sources"] == {}
    assert usage["can_run_pipeline"] is True
    
    # 一部使用後
    tracker.record_calls(count=100, source="test_src")
    usage = tracker.get_today_usage()
    assert usage["used"] == 100
    assert usage["remaining"] == 400
    assert usage["usage_pct"] == 20.0
    assert usage["sources"] == {"test_src": 100}
    assert usage["can_run_pipeline"] is True
    
    # 95% 到達時点で should_block が True となり can_run_pipeline が False になる
    tracker.record_calls(count=375)  # 合計 475 (95%)
    usage = tracker.get_today_usage()
    assert usage["used"] == 475
    assert usage["remaining"] == 25
    assert usage["can_run_pipeline"] is False

def test_estimate_pipeline_cost(temp_usage_file):
    """estimate_pipeline_cost の計算ロジックをテスト"""
    tracker = APIUsageTracker(usage_path=temp_usage_file)
    
    # segment_count = 120 の場合のコスト計算
    cost = tracker.estimate_pipeline_cost(segment_count=120)
    assert cost["estimated_calls"] == 6
    assert cost["can_proceed"] is True
    
    # サスペンド閾値(95%)を超えさせて proceeds できないことを確認
    tracker.record_calls(count=470)  # 残り30回
    cost = tracker.estimate_pipeline_cost(segment_count=120)  # 必要6回、残りは24回になるが、95%に達するため should_block になり can_proceed は False
    assert cost["can_proceed"] is False

def test_cleanup_old_data(temp_usage_file):
    """cleanup_old_data の有効期限切れデータ削除をテスト"""
    tracker = APIUsageTracker(usage_path=temp_usage_file)
    
    today = date.today()
    date_today = today.isoformat()
    date_yesterday = (today - timedelta(days=1)).isoformat()
    date_old = (today - timedelta(days=35)).isoformat()
    
    tracker._data["daily"] = {
        date_today: {"total": 10},
        date_yesterday: {"total": 20},
        date_old: {"total": 30}
    }
    
    tracker.cleanup_old_data(keep_days=1)
    
    assert date_today in tracker._data["daily"]
    assert date_yesterday not in tracker._data["daily"]
    assert date_old not in tracker._data["daily"]

def test_module_helper_functions(temp_usage_file):
    """モジュールレベルのラッパー関数の動作確認"""
    original_path = usage_tracker.usage_path
    original_data = usage_tracker._data
    original_last_escalation = usage_tracker._last_escalation
    
    try:
        usage_tracker.usage_path = temp_usage_file
        usage_tracker._data = {"daily": {}, "limit": FREE_TIER_LIMIT}
        usage_tracker._last_escalation = None
        
        record_api_call(count=10, source="helper_test")
        today = date.today().isoformat()
        assert usage_tracker._data["daily"][today]["total"] == 10
        
        status = get_usage_status()
        assert status["used"] == 10
        
        assert should_block_api() is False
        usage_tracker.record_calls(count=465)  # 合計475
        assert should_block_api() is True
        
    finally:
        usage_tracker.usage_path = original_path
        usage_tracker._data = original_data
        usage_tracker._last_escalation = original_last_escalation

def test_update_thresholds(temp_usage_file):
    """update_thresholds の検証とガードレールをテスト"""
    tracker = APIUsageTracker(usage_path=temp_usage_file)
    
    # 正常ケース
    tracker.update_thresholds(0.50, 0.70, 0.90)
    assert tracker.thresholds == {"info": 0.50, "warning": 0.70, "critical": 0.90}
    
    # 異常ケース（入力ガードレールが効くか）
    with pytest.raises(ValueError):
        tracker.update_thresholds(0.80, 0.70, 0.90)  # info >= warning
    with pytest.raises(ValueError):
        tracker.update_thresholds(-0.1, 0.70, 0.90)  # 負の値
    with pytest.raises(ValueError):
        tracker.update_thresholds(0.50, 0.70, 1.1)   # 1.0より大きい

def test_record_calls_zero_and_negative(temp_usage_file):
    """record_callsに0や負の値を指定した場合の動作をテスト（入力ガードレール）"""
    tracker = APIUsageTracker(usage_path=temp_usage_file)
    
    with pytest.raises(ValueError):
        tracker.record_calls(count=0, source="test_zero")
        
    with pytest.raises(ValueError):
        tracker.record_calls(count=-5, source="test_neg")

def test_cleanup_old_data_invalid_keep_days(temp_usage_file):
    """cleanup_old_dataに0や負の値を指定した場合の動作をテスト"""
    tracker = APIUsageTracker(usage_path=temp_usage_file)
    with pytest.raises(ValueError):
        tracker.cleanup_old_data(keep_days=0)
    with pytest.raises(ValueError):
        tracker.cleanup_old_data(keep_days=-1)
