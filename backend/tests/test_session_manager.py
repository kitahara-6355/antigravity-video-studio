import json
import logging
import pytest
import sys
import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

# pytest-cov が正しく計測できるようにモジュールを再インポートする
if "harness.session_manager" in sys.modules:
    del sys.modules["harness.session_manager"]
import harness.session_manager
from harness.session_manager import SessionManager, SessionState

# テスト用のロガー設定
logger = logging.getLogger(__name__)


@pytest.fixture
def temp_session_dir(tmp_path):
    """テスト用の一時セッションディレクトリを提供するフィクスチャ"""
    return tmp_path / "sessions"


@pytest.fixture
def manager(temp_session_dir):
    """テスト用の SessionManager インスタンスを提供するフィクスチャ"""
    return SessionManager(session_dir=temp_session_dir)


def test_create_session(manager, temp_session_dir):
    # 1. デフォルト設定でのセッション作成
    session = manager.create_session()
    assert session.session_id is not None
    assert session.status == "active"
    assert session.video_path is None
    assert session.metadata == {}

    # ディスクにファイルが保存されたか確認
    file_path = temp_session_dir / f"{session.session_id}.json"
    assert file_path.exists()

    # 2. パラメータ指定でのセッション作成
    custom_id = "test-session-123"
    session2 = manager.create_session(
        video_path="path/to/video.mp4",
        metadata={"user": "test_user"},
        session_id=custom_id
    )
    assert session2.session_id == custom_id
    assert session2.video_path == "path/to/video.mp4"
    assert session2.metadata == {"user": "test_user"}
    assert (temp_session_dir / f"{custom_id}.json").exists()


def test_get_session(manager):
    session = manager.create_session()
    retrieved = manager.get_session(session.session_id)
    assert retrieved == session

    # 存在しないセッション
    assert manager.get_session("non-existent") is None


def test_resume_session_memory(manager):
    session = manager.create_session()
    session.status = "paused"
    
    # メモリからのリジューム
    resumed = manager.resume_session(session.session_id)
    assert resumed is not None
    assert resumed.status == "active"
    assert resumed.session_id == session.session_id


def test_resume_session_disk(manager, temp_session_dir):
    session = manager.create_session(video_path="disk_video.mp4")
    sid = session.session_id

    # メモリ上から削除してディスクからのみ読めるようにする
    manager._active_sessions.pop(sid)
    assert manager.get_session(sid) is None

    # ディスクからのリジューム
    resumed = manager.resume_session(sid)
    assert resumed is not None
    assert resumed.status == "active"
    assert resumed.video_path == "disk_video.mp4"
    assert manager.get_session(sid) == resumed


def test_resume_session_not_found(manager):
    assert manager.resume_session("non-existent") is None


def test_update_stage(manager):
    session = manager.create_session()
    sid = session.session_id

    # ステージ更新
    manager.update_stage(sid, stage=2, detail="AI校閲完了", data={"confidence": 0.95})
    
    updated = manager.get_session(sid)
    assert updated.current_stage == 2
    assert updated.metadata["confidence"] == 0.95
    assert len(updated.tool_history) == 1
    assert updated.tool_history[0]["stage"] == 2
    assert updated.tool_history[0]["detail"] == "AI校閲完了"

    # 存在しないセッションの更新（無視されること）
    manager.update_stage("non-existent", stage=3)


def test_update_stage_history_limit(manager):
    session = manager.create_session()
    sid = session.session_id

    # 履歴上限のテスト (MAX_TOOL_HISTORY = 50)
    for i in range(60):
        manager.update_stage(sid, stage=1, detail=f"Step {i}")

    updated = manager.get_session(sid)
    assert len(updated.tool_history) == 50
    assert updated.tool_history[0]["detail"] == "Step 10"
    assert updated.tool_history[-1]["detail"] == "Step 59"


def test_record_tool_call(manager):
    session = manager.create_session()
    sid = session.session_id

    # ツール呼び出し記録
    manager.record_tool_call(
        session_id=sid,
        tool_name="image_generator",
        args={"prompt": "beautiful sunset", "ratio": 1.5},
        result={"url": "http://example.com/ sunset.png"},
        duration_seconds=1.23,
        is_error=False
    )

    updated = manager.get_session(sid)
    assert len(updated.tool_history) == 1
    assert updated.tool_history[0]["type"] == "tool_call"
    assert updated.tool_history[0]["tool_name"] == "image_generator"
    assert updated.tool_history[0]["duration_s"] == 1.23
    assert updated.tool_history[0]["is_error"] is False
    assert updated.tool_history[0]["args_summary"] == {
        "prompt": "beautiful sunset",
        "ratio": "1.5"
    }

    # 存在しないセッションへのツール記録（無視されること）
    manager.record_tool_call("non-existent", "tool", {}, None, 0.1)


def test_record_tool_call_history_limit(manager):
    session = manager.create_session()
    sid = session.session_id

    # 履歴上限のテスト (MAX_TOOL_HISTORY = 50)
    for i in range(60):
        manager.record_tool_call(sid, f"tool_{i}", {}, None, 0.1)

    updated = manager.get_session(sid)
    assert len(updated.tool_history) == 50
    assert updated.tool_history[0]["tool_name"] == "tool_10"
    assert updated.tool_history[-1]["tool_name"] == "tool_59"


def test_complete_session(manager):
    session = manager.create_session()
    sid = session.session_id

    manager.complete_session(sid, quality_score=85, final_data={"output_url": "http://..."})

    updated = manager.get_session(sid)
    assert updated.status == "completed"
    assert updated.quality_score == 85
    assert updated.pipeline_completed_at is not None
    assert updated.metadata["output_url"] == "http://..."

    # 存在しないセッションの完了（無視されること）
    manager.complete_session("non-existent")


def test_pause_session(manager):
    session = manager.create_session()
    sid = session.session_id

    manager.pause_session(sid)
    updated = manager.get_session(sid)
    assert updated.status == "paused"

    # 存在しないセッションの一時停止（無視されること）
    manager.pause_session("non-existent")


def test_error_session(manager):
    session = manager.create_session()
    sid = session.session_id

    manager.error_session(sid, error="API Quota Exceeded")
    updated = manager.get_session(sid)
    assert updated.status == "error"
    assert updated.metadata["last_error"] == "API Quota Exceeded"

    # 存在しないセッションのエラー（無視されること）
    manager.error_session("non-existent", "error")


def test_list_sessions(manager):
    # テスト用セッションを複数作成
    s1 = manager.create_session()
    s2 = manager.create_session()
    s3 = manager.create_session()

    manager.pause_session(s2.session_id)
    manager.complete_session(s3.session_id)

    # 1. 全件取得
    all_sessions = manager.list_sessions()
    assert len(all_sessions) >= 3

    # 2. ステータスフィルタ
    paused_sessions = manager.list_sessions(status="paused")
    assert len(paused_sessions) == 1
    assert paused_sessions[0]["session_id"] == s2.session_id

    # 3. リミット制限
    limited = manager.list_sessions(limit=2)
    assert len(limited) == 2


def test_get_stats(manager):
    s1 = manager.create_session()
    s2 = manager.create_session()
    s3 = manager.create_session()
    s4 = manager.create_session()

    manager.pause_session(s2.session_id)
    manager.complete_session(s3.session_id)
    manager.error_session(s4.session_id, "error")

    stats = manager.get_stats()
    assert stats["total"] >= 4
    assert stats["active"] >= 1
    assert stats["paused"] >= 1
    assert stats["completed"] >= 1
    assert stats["error"] >= 1


def test_cleanup_old_sessions(manager, temp_session_dir):
    s1 = manager.create_session()
    s2 = manager.create_session()

    # s1 のファイルを過去の日付に書き換える (35日前)
    past_time = datetime.now() - timedelta(days=35)
    s1.last_active_at = past_time.isoformat()
    
    # メモリとディスク両方に反映
    manager._save_session(s1)

    # クリーンアップ実行
    removed = manager.cleanup_old_sessions()
    assert removed == 1

    # メモリおよびディスクから削除されたことを確認
    assert manager.get_session(s1.session_id) is None
    assert not (temp_session_dir / f"{s1.session_id}.json").exists()
    assert manager.get_session(s2.session_id) is not None


# ============================================================
# 異常系テスト
# ============================================================

def test_save_session_oserror(manager, temp_session_dir):
    session = manager.create_session()
    
    # _save_session 中に write_text が OSError を投げるようにモックする
    with patch("pathlib.Path.write_text", side_effect=OSError("Disk Full")):
        with patch("harness.session_manager.logger.error") as mock_log:
            result = manager._save_session(session)
            assert result is False
            mock_log.assert_called_once()
            assert "Session save failed" in mock_log.call_args[0][0]


def test_save_session_typeerror(manager):
    session = manager.create_session()
    
    # シリアライズ不可能なオブジェクトをメタデータに突っ込む
    session.metadata = {"unserializable": object()}
    
    with patch("harness.session_manager.logger.error") as mock_log:
        result = manager._save_session(session)
        assert result is False
        mock_log.assert_called_once()
        assert "Session save failed" in mock_log.call_args[0][0]


def test_resume_session_disk_json_decode_error(manager, temp_session_dir):
    sid = "bad-json-session"
    file_path = temp_session_dir / f"{sid}.json"
    bad_path = temp_session_dir / f"{sid}.json.bad"
    
    # 壊れたJSONを書き込む
    file_path.write_text("{invalid json", encoding="utf-8")

    with patch("harness.session_manager.logger.error") as mock_log:
        resumed = manager.resume_session(sid)
        assert resumed is None
        # 破損ファイルが隔離されていること
        assert not file_path.exists()
        assert bad_path.exists()
        mock_log.assert_called_once()
        assert "Session resume failed due to corrupted data" in mock_log.call_args[0][0]


def test_resume_session_disk_type_value_error(manager, temp_session_dir):
    sid = "bad-data-session"
    file_path = temp_session_dir / f"{sid}.json"
    bad_path = temp_session_dir / f"{sid}.json.bad"
    
    # SessionStateに適合しない余分なデータや型不整合データ
    bad_data = {
        "session_id": sid,
        "created_at": "now",
        "last_active_at": "now",
        "invalid_field_name_xyz": 12345
    }
    file_path.write_text(json.dumps(bad_data), encoding="utf-8")

    with patch("harness.session_manager.logger.error") as mock_log:
        resumed = manager.resume_session(sid)
        assert resumed is None
        # 破損ファイルが隔離されていること
        assert not file_path.exists()
        assert bad_path.exists()
        mock_log.assert_called_once()
        assert "Session resume failed due to corrupted data" in mock_log.call_args[0][0]


def test_resume_session_disk_oserror(manager, temp_session_dir):
    sid = "oserror-session"
    file_path = temp_session_dir / f"{sid}.json"
    file_path.write_text("{}", encoding="utf-8") # とりあえず作っておく
    
    # read_text 時に OSError を発生させる
    with patch("pathlib.Path.read_text", side_effect=OSError("Permission Denied")):
        with patch("harness.session_manager.logger.error") as mock_log:
            resumed = manager.resume_session(sid)
            assert resumed is None
            mock_log.assert_called_once()
            assert "Session resume failed" in mock_log.call_args[0][0]


def test_load_active_sessions_errors(temp_session_dir):
    # テスト用のファイルを準備
    # 1. 正常なセッション (last_active_at を現在時刻にして期限切れを防ぐ)
    now_str = datetime.now().isoformat()
    s_ok = SessionState(session_id="ok-id", created_at=now_str, last_active_at=now_str)
    (temp_session_dir / "ok-id.json").parent.mkdir(parents=True, exist_ok=True)
    (temp_session_dir / "ok-id.json").write_text(json.dumps(s_ok.__dict__), encoding="utf-8")

    # 2. 壊れたJSONのセッション
    (temp_session_dir / "bad-json.json").write_text("invalid json", encoding="utf-8")

    # 3. 30日以上前のクリーンアップ対象セッション
    past_time = datetime.now() - timedelta(days=40)
    s_old = SessionState(session_id="old-id", created_at=past_time.isoformat(), last_active_at=past_time.isoformat())
    (temp_session_dir / "old-id.json").write_text(json.dumps(s_old.__dict__), encoding="utf-8")

    # ロード中のエラー発生を検証
    with patch("harness.session_manager.logger.error") as mock_log:
        manager = SessionManager(session_dir=temp_session_dir)
        
        # 壊れたJSONによるエラーログが記録されていることを確認
        assert mock_log.call_count >= 1
        # 壊れたJSONのセッションファイルが隔離されていること
        assert not (temp_session_dir / "bad-json.json").exists()
        assert (temp_session_dir / "bad-json.json.bad").exists()
        # 正常なものはロードされ、かつ active から paused に切り替わっていることを確認
        assert "ok-id" in manager._active_sessions
        assert manager._active_sessions["ok-id"].status == "paused"
        # 古いものは削除されていることを確認
        assert "old-id" not in manager._active_sessions
        assert not (temp_session_dir / "old-id.json").exists()


def test_cleanup_old_sessions_errors(manager, temp_session_dir):
    # 古いセッションファイルをディスクに配置
    past_time = datetime.now() - timedelta(days=40)
    
    # 1. OSError を起こすためのファイル
    sid_os = "os-err-id"
    s_os = SessionState(session_id=sid_os, created_at=past_time.isoformat(), last_active_at=past_time.isoformat())
    (temp_session_dir / f"{sid_os}.json").write_text(json.dumps(s_os.__dict__), encoding="utf-8")

    # 2. ValueError を起こすための不正な日付形式 (last_active_at) セッション
    sid_val = "val-err-id"
    bad_data = {
        "session_id": sid_val,
        "created_at": past_time.isoformat(),
        "last_active_at": "not-a-valid-date-format-1234"
    }
    (temp_session_dir / f"{sid_val}.json").write_text(json.dumps(bad_data), encoding="utf-8")

    # read_text で OSError になるようにモック
    orig_read_text = Path.read_text
    def mock_read_text(self, *args, **kwargs):
        if f"{sid_os}.json" in self.name:
            raise OSError("Permission Denied")
        return orig_read_text(self, *args, **kwargs)

    with patch("pathlib.Path.read_text", mock_read_text):
        with patch("harness.session_manager.logger.error") as mock_log:
            removed = manager.cleanup_old_sessions()
            # 不正な日付のセッションファイルが隔離されていること
            assert not (temp_session_dir / f"{sid_val}.json").exists()
            assert (temp_session_dir / f"{sid_val}.json.bad").exists()
            # エラーログが出力されていること (OSError と ValueError の 2 件)
            assert mock_log.call_count >= 2
            # 正常に削除された件数は 0
            assert removed == 0


def test_resume_session_memory_not_paused(manager):
    # status が "paused" 以外の状態でのリジュームテスト (153->155 の False 分岐カバー)
    session = manager.create_session()
    session.status = "completed"
    
    resumed = manager.resume_session(session.session_id)
    assert resumed is not None
    assert resumed.status == "completed"  # active に変更されないこと


def test_load_active_sessions_not_active(temp_session_dir):
    # status が "active" 以外の状態でのロードテスト (348->351 の False 分岐カバー)
    now_str = datetime.now().isoformat()
    s_completed = SessionState(session_id="comp-id", created_at=now_str, last_active_at=now_str, status="completed")
    
    (temp_session_dir / "comp-id.json").parent.mkdir(parents=True, exist_ok=True)
    (temp_session_dir / "comp-id.json").write_text(json.dumps(s_completed.__dict__), encoding="utf-8")

    manager = SessionManager(session_dir=temp_session_dir)
    assert "comp-id" in manager._active_sessions
    assert manager._active_sessions["comp-id"].status == "completed"  # paused に変更されないこと



def test_load_active_sessions_corrupted_missing_last_active(temp_session_dir):
    # last_active_at が欠落している場合、ValueError になり、隔離されることを検証する
    bad_data = {
        "session_id": "missing-last-active",
        "created_at": datetime.now().isoformat(),
    }
    (temp_session_dir / "missing-last-active.json").parent.mkdir(parents=True, exist_ok=True)
    (temp_session_dir / "missing-last-active.json").write_text(json.dumps(bad_data), encoding="utf-8")

    with patch("harness.session_manager.logger.error") as mock_log:
        manager = SessionManager(session_dir=temp_session_dir)
        assert "missing-last-active" not in manager._active_sessions
        assert not (temp_session_dir / "missing-last-active.json").exists()
        assert (temp_session_dir / "missing-last-active.json.bad").exists()
        assert mock_log.call_count >= 1
