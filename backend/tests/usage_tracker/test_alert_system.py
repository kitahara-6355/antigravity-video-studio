import sys
from unittest.mock import MagicMock

# Python 3.13における pydantic.root_model の KeyError によるインポートハングを防ぐためのモック
class DummyGenAIError(Exception):
    pass

mock_genai_errors = MagicMock()
mock_genai_errors.APIError = DummyGenAIError
mock_genai_errors.ClientError = DummyGenAIError
mock_genai_errors.ServerError = DummyGenAIError

sys.modules['google.genai.errors'] = mock_genai_errors
sys.modules['google.genai'] = MagicMock()

import pytest
from unittest.mock import patch
import logging
from datetime import datetime, timedelta

from usage_tracker.alert_system import (
    AlertLevel,
    AlertSystem,
    alert_system,
    emit_info,
    emit_warning,
    emit_block,
    emit_critical,
)


def test_alert_system_basic():
    # インスタンスの新規作成
    system = AlertSystem()
    
    # register_handler / emit の動作
    handler_called = []
    def dummy_handler(alert):
        handler_called.append(alert)
        
    system.register_handler(AlertLevel.INFO, dummy_handler)
    
    alert = system.emit(AlertLevel.INFO, "test-model", "Test message", {"key": "val"})
    
    assert len(handler_called) == 1
    assert handler_called[0]["message"] == "Test message"
    assert handler_called[0]["model"] == "test-model"
    assert handler_called[0]["data"] == {"key": "val"}
    assert alert["level"] == "info"


def test_alert_system_handler_exception():
    # ハンドラーが例外を投げた場合でも emit が正常終了すること
    system = AlertSystem()
    
    def bad_handler(alert):
        raise ValueError("Bad handler error")
        
    system.register_handler(AlertLevel.WARNING, bad_handler)
    
    # ログ出力されるのでログ監視
    with patch("usage_tracker.alert_system.logger.error") as mock_log:
        alert = system.emit(AlertLevel.WARNING, "test-model", "Test message")
        assert alert["level"] == "warning"
        mock_log.assert_called_once()
        # "Alert handler failed: Bad handler error" が含まれること
        args, _ = mock_log.call_args
        assert "Alert handler failed" in args[0]


def test_alert_system_history_limit():
    # 履歴の上限
    system = AlertSystem()
    # 101回 emit
    for i in range(105):
        system.emit(AlertLevel.INFO, "model", f"msg {i}")
        
    assert len(system._history) == 100
    # 最初のは消えているはず
    assert system._history[0]["message"] == "msg 5"
    assert system._history[-1]["message"] == "msg 104"


def test_alert_system_log_output():
    # _log_alert の全レベルでのログ出力を検証
    system = AlertSystem()
    
    with patch("usage_tracker.alert_system.logger.critical") as mock_crit, \
         patch("usage_tracker.alert_system.logger.error") as mock_err, \
         patch("usage_tracker.alert_system.logger.warning") as mock_warn, \
         patch("usage_tracker.alert_system.logger.info") as mock_info:
         
        system.emit(AlertLevel.CRITICAL, "m1", "crit msg")
        mock_crit.assert_called_once_with("🛑 CRITICAL [m1]: crit msg")
        
        system.emit(AlertLevel.BLOCK, "m2", "block msg")
        mock_err.assert_called_once_with("🛑 BLOCK [m2]: block msg")
        
        system.emit(AlertLevel.WARNING, "m3", "warn msg")
        mock_warn.assert_called_once_with("⚠️ WARNING [m3]: warn msg")
        
        system.emit(AlertLevel.INFO, "m4", "info msg")
        mock_info.assert_called_once_with("ℹ️ INFO [m4]: info msg")
        
        # NORMAL ではログ出力しない
        system.emit(AlertLevel.NORMAL, "m5", "normal msg")


def test_alert_system_get_recent_alerts():
    system = AlertSystem()
    
    system.emit(AlertLevel.INFO, "model", "msg info 1")
    system.emit(AlertLevel.WARNING, "model", "msg warn 1")
    system.emit(AlertLevel.INFO, "model", "msg info 2")
    
    # level指定なし、件数制限
    recent = system.get_recent_alerts(limit=2)
    assert len(recent) == 2
    assert recent[0]["message"] == "msg warn 1"
    assert recent[1]["message"] == "msg info 2"
    
    # level指定あり
    recent_info = system.get_recent_alerts(level=AlertLevel.INFO)
    assert len(recent_info) == 2
    assert recent_info[0]["message"] == "msg info 1"
    assert recent_info[1]["message"] == "msg info 2"
    
    recent_warn = system.get_recent_alerts(level=AlertLevel.WARNING, limit=1)
    assert len(recent_warn) == 1
    assert recent_warn[0]["message"] == "msg warn 1"


def test_alert_system_has_active_block():
    system = AlertSystem()
    
    # 何もない状態
    assert not system.has_active_block("model-a")
    
    # 違うモデルのアラート
    system.emit(AlertLevel.BLOCK, "model-b", "msg")
    assert not system.has_active_block("model-a")
    
    # 当該モデルだが WARNING
    system.emit(AlertLevel.WARNING, "model-a", "msg")
    assert not system.has_active_block("model-a")
    
    # 当該モデルで BLOCK (当日)
    system.emit(AlertLevel.BLOCK, "model-a", "msg")
    assert system.has_active_block("model-a")
    
    # 履歴をクリアして再テスト
    system = AlertSystem()
    
    # 前日の BLOCK
    yesterday = datetime.now() - timedelta(days=1)
    # emit して timestamp を手動で書き換える
    alert = system.emit(AlertLevel.BLOCK, "model-a", "msg")
    alert["timestamp"] = yesterday.isoformat()
    assert not system.has_active_block("model-a")
    
    # 当日の CRITICAL
    system.emit(AlertLevel.CRITICAL, "model-a", "msg")
    assert system.has_active_block("model-a")


def test_helper_functions():
    # シングルトンインスタンスをモックするか、または発行された結果を確認する
    # テストの前に alert_system._history をクリアしておく
    alert_system._history.clear()
    
    alert1 = emit_info("model-x", "info msg", {"meta": "data"})
    assert alert1["level"] == "info"
    assert alert1["data"] == {"meta": "data"}
    
    alert2 = emit_warning("model-x", "warn msg")
    assert alert2["level"] == "warning"
    
    alert3 = emit_block("model-x", "block msg")
    assert alert3["level"] == "block"
    
    alert4 = emit_critical("model-x", "crit msg")
    assert alert4["level"] == "critical"
    
    assert len(alert_system._history) == 4


def test_alert_system_invalid_level():
    # 不正なアラートレベルでの emit のテスト
    system = AlertSystem()
    with pytest.raises(AttributeError):
        system.emit("invalid_level", "model", "msg")


def test_alert_system_get_recent_alerts_edges():
    system = AlertSystem()
    # 空の履歴
    assert system.get_recent_alerts(limit=5) == []
    
    # limit=0 や負の場合の挙動の検証
    system.emit(AlertLevel.INFO, "model", "msg")
    
    recent_zero = system.get_recent_alerts(limit=0)
    assert len(recent_zero) == 1
    
    recent_negative = system.get_recent_alerts(limit=-1)
    assert len(recent_negative) == 0


def test_alert_system_has_active_block_time_edges():
    system = AlertSystem()
    today = datetime.now()
    
    # 今日の 00:00:00 (今日の始まり)
    start_of_day = datetime(today.year, today.month, today.day, 0, 0, 0)
    alert = system.emit(AlertLevel.BLOCK, "model-edge", "msg")
    alert["timestamp"] = start_of_day.isoformat()
    assert system.has_active_block("model-edge")
    
    # 今日の 23:59:59 (今日の終わり)
    end_of_day = datetime(today.year, today.month, today.day, 23, 59, 59)
    alert["timestamp"] = end_of_day.isoformat()
    assert system.has_active_block("model-edge")


# --------------------------------------------------------
# ThumbnailResolver & Alert Integration Tests
# --------------------------------------------------------
from usage_tracker.alert_system import ThumbnailResolver, AlertLevel
from agents.stage_bound_agent import StageBoundAgent
from PIL import Image
import json
import sqlite3
import asyncio
from pathlib import Path

def test_thumbnail_resolver_generation_success(tmp_path):
    output_path = tmp_path / "test_thumb.png"
    resolver = ThumbnailResolver(output_dir=tmp_path)
    
    res_path = resolver.generate_thumbnail(output_path, text="Hello World")
    assert res_path.exists()
    
    with Image.open(res_path) as img:
        assert img.size == (1280, 720)


def test_thumbnail_resolver_validation_and_alerts(tmp_path):
    resolver = ThumbnailResolver(output_dir=tmp_path)
    alert_system._history.clear()
    
    # 1. 正常な画像
    ok_path = tmp_path / "ok.png"
    resolver.generate_thumbnail(ok_path, width=1920, height=1080)
    result = resolver.validate_thumbnail(ok_path)
    assert result["width"] == 1920
    assert result["height"] == 1080
    assert len(alert_system._history) == 0  # 正常時はアラートなし
    
    # 2. 低解像度の画像
    bad_res_path = tmp_path / "bad_res.png"
    Image.new("RGB", (640, 360)).save(bad_res_path)
    with pytest.raises(ValueError) as exc:
        resolver.validate_thumbnail(bad_res_path)
    assert "Resolution must be at least 1280x720" in str(exc.value)
    
    # アラートが発行されていることを確認
    recent = alert_system.get_recent_alerts(level=AlertLevel.WARNING)
    assert len(recent) > 0
    assert "Resolution must be at least 1280x720" in recent[-1]["message"]
    assert recent[-1]["model"] == "thumbnail"
    
    # 3. アスペクト比が正しくない
    bad_aspect_path = tmp_path / "bad_aspect.png"
    Image.new("RGB", (1280, 800)).save(bad_aspect_path)
    with pytest.raises(ValueError) as exc:
        resolver.validate_thumbnail(bad_aspect_path)
    assert "Aspect ratio must be 16:9" in str(exc.value)
    
    recent = alert_system.get_recent_alerts(level=AlertLevel.WARNING)
    assert "Aspect ratio must be 16:9" in recent[-1]["message"]


@pytest.mark.asyncio
async def test_thumbnail_resolver_stage_bound_agent_integration(tmp_path):
    db_file = tmp_path / "thumbnail_agent.db"
    resolver = ThumbnailResolver(project_root=tmp_path, output_dir=tmp_path)
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    task_id = "t_thumb_ok"
    await agent.register_task(task_id=task_id, initial_status="READY")
    
    await agent.start(resolver.resolve_thumbnail_task)
    
    # 非同期実行の完了を待機
    for _ in range(20):
        status = await agent.get_task_status(task_id)
        if status in ("COMPLETED", "FAILED"):
            break
        await asyncio.sleep(0.05)
        
    final_status = await agent.get_task_status(task_id)
    assert final_status == "COMPLETED"
    
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT result, error, retry_count FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        result_data = json.loads(row[0])
        assert result_data["width"] == 1280
        assert result_data["height"] == 720
    finally:
        conn.close()
        
    await agent.stop()


def test_alert_system_multiple_handlers_isolation():
    # 複数ハンドラ登録時の独立性の検証
    system = AlertSystem()
    
    called_handlers = []
    
    def handler_raise(alert):
        called_handlers.append("raise")
        raise RuntimeError("Handler error")
        
    def handler_ok(alert):
        called_handlers.append("ok")
        
    system.register_handler(AlertLevel.WARNING, handler_raise)
    system.register_handler(AlertLevel.WARNING, handler_ok)
    
    with patch("usage_tracker.alert_system.logger.error") as mock_log:
        system.emit(AlertLevel.WARNING, "test-model", "test message")
        
        # 例外が発生したハンドラと正常なハンドラの両方が呼ばれていること
        assert called_handlers == ["raise", "ok"]
        # ログにエラーが記録されていること
        mock_log.assert_called_once()
        assert "Alert handler failed: Handler error" in mock_log.call_args[0][0]


def test_alert_system_dynamic_max_history():
    # max_history を動的に変更した場合の挙動
    system = AlertSystem()
    system._max_history = 3
    
    for i in range(5):
        system.emit(AlertLevel.INFO, "model", f"msg {i}")
        
    # 履歴上限3で切り捨てられていること
    assert len(system._history) == 3
    assert system._history[0]["message"] == "msg 2"
    assert system._history[-1]["message"] == "msg 4"


def test_alert_system_has_active_block_empty():
    # 履歴が空の場合の has_active_block の挙動
    system = AlertSystem()
    assert not system.has_active_block("model-a")
