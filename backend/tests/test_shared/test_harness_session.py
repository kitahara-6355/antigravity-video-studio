"""
test_harness_session.py — M2.3 Sprint 2.3.3 SessionManager 15テスト + 追加カバレッジテスト

テスト対象: backend/harness/session_manager.py (386行, 28分岐)
  - SessionManager: create/get/resume/update/complete/pause/error
  - ディスク永続化: _save_session, _load_active_sessions, cleanup_old_sessions
  - 一覧・統計: list_sessions, get_stats, record_tool_call

6カテゴリ構成:
  C1: セッション作成・取得 (3)
  C2: セッション状態遷移 (3)
  C3: 履歴・一覧 (3)
  C4: ディスク永続化・エラー耐性 (3)
  C5: クリーンアップ (1)
  C6: 性能 (2)
  C7: 追加カバレッジおよび例外ハンドリング検証（100%化）(10)

テスト設計方針:
  - session_dir は tmp_path で隔離
  - 既存 test_harness.py #8-#9 との重複回避
  - JSON I/O テスト is リアルなファイル操作で検証
"""

import sys
import json
import time
import pytest
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import asdict

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from harness.session_manager import SessionManager, SessionState


# ============================================================
# フィクスチャ
# ============================================================

@pytest.fixture
def session_mgr(tmp_path):
    """各テストで新規SessionManagerを生成（session_dir=tmp_path）"""
    return SessionManager(session_dir=tmp_path)


@pytest.fixture
def tmp_session_dir(tmp_path):
    """テスト用セッションディレクトリ（直接アクセス用）"""
    return tmp_path


# ============================================================
# C1: セッション作成・取得 (3)
# ============================================================

class TestC1Creation:
    """C1: セッション作成・取得テスト"""

    def test_S_C1_01_create_session_auto_id(self, session_mgr):
        """S-C1-01: session_id 省略時に UUID が自動生成されること"""
        session = session_mgr.create_session(video_path="/test/video.mp4")

        assert session.session_id is not None
        assert len(session.session_id) == 36  # UUID format: 8-4-4-4-12
        assert session.video_path == "/test/video.mp4"
        assert session.status == "active"

    def test_S_C1_02_create_session_explicit_id(self, session_mgr):
        """S-C1-02: session_id 指定時にその ID が使用されること"""
        session = session_mgr.create_session(
            video_path="/test/video.mp4",
            session_id="custom-session-123",
            metadata={"key": "value"},
        )

        assert session.session_id == "custom-session-123"
        assert session.metadata == {"key": "value"}

    def test_S_C1_03_get_session_nonexistent(self, session_mgr):
        """S-C1-03: 存在しない session_id で get_session() が None を返すこと"""
        result = session_mgr.get_session("nonexistent-id")
        assert result is None


# ============================================================
# C2: セッション状態遷移 (3)
# ============================================================

class TestC2StateTransition:
    """C2: セッション状態遷移テスト"""

    def test_S_C2_01_resume_from_disk(self, tmp_session_dir):
        """S-C2-01: メモリにないセッションをディスクから復元し、status が active になること"""
        # ステップ1: セッションを作成してディスクに保存
        mgr1 = SessionManager(session_dir=tmp_session_dir)
        session = mgr1.create_session(
            video_path="/test/video.mp4",
            session_id="disk-resume-test",
        )
        mgr1.pause_session("disk-resume-test")

        # ステップ2: 新しい SessionManager を作成（メモリにはない状態をシミュレート）
        mgr2 = SessionManager(session_dir=tmp_session_dir)

        # _load_active_sessions で復元されているが、明示的に pop して
        # ディスクからの resume をテスト
        mgr2._active_sessions.pop("disk-resume-test", None)

        # ステップ3: ディスクから resume
        resumed = mgr2.resume_session("disk-resume-test")

        assert resumed is not None
        assert resumed.status == "active"
        assert resumed.video_path == "/test/video.mp4"

    def test_S_C2_02_resume_nonexistent(self, session_mgr):
        """S-C2-02: メモリにもディスクにもないセッションで None が返ること"""
        result = session_mgr.resume_session("totally-nonexistent-id")
        assert result is None

    def test_S_C2_03_error_session(self, session_mgr):
        """S-C2-03: error_session() で status が error、metadata に last_error が設定されること"""
        session = session_mgr.create_session(video_path="/test.mp4")
        sid = session.session_id

        session_mgr.error_session(sid, "FFmpeg crashed with code 1")

        updated = session_mgr.get_session(sid)
        assert updated.status == "error"
        assert updated.metadata["last_error"] == "FFmpeg crashed with code 1"


# ============================================================
# C3: 履歴・一覧 (3)
# ============================================================

class TestC3HistoryListing:
    """C3: 履歴・一覧テスト"""

    def test_S_C3_01_tool_history_truncation(self, session_mgr):
        """S-C3-01: record_tool_call を51回呼び出した後、tool_history が MAX_TOOL_HISTORY に切り詰められること"""
        session = session_mgr.create_session(session_id="history-test")
        sid = session.session_id

        for i in range(51):
            session_mgr.record_tool_call(
                sid,
                tool_name=f"tool_{i}",
                args={"arg": i},
                result={"ok": True},
                duration_seconds=0.1,
            )

        updated = session_mgr.get_session(sid)
        assert len(updated.tool_history) == SessionManager.MAX_TOOL_HISTORY  # 50
        # 最新のエントリが残っていること
        assert updated.tool_history[-1]["tool_name"] == "tool_50"

    def test_S_C3_02_list_sessions_status_filter(self, session_mgr):
        """S-C3-02: list_sessions(status="active") が active セッションのみを返すこと"""
        s1 = session_mgr.create_session(session_id="s1")
        s2 = session_mgr.create_session(session_id="s2")
        s3 = session_mgr.create_session(session_id="s3")

        session_mgr.pause_session("s2")
        session_mgr.complete_session("s3", quality_score=90)

        active_list = session_mgr.list_sessions(status="active")
        assert len(active_list) == 1
        assert active_list[0]["session_id"] == "s1"

        paused_list = session_mgr.list_sessions(status="paused")
        assert len(paused_list) == 1
        assert paused_list[0]["session_id"] == "s2"

    def test_S_C3_03_update_stage_with_data(self, session_mgr):
        """S-C3-03: update_stage() で data 辞書が metadata にマージされること"""
        session = session_mgr.create_session(session_id="stage-test")
        sid = session.session_id

        session_mgr.update_stage(
            sid, stage=3, detail="SmartCut完了",
            data={"cut_percent": 25.0, "segments_selected": 8},
        )

        updated = session_mgr.get_session(sid)
        assert updated.current_stage == 3
        assert updated.metadata["cut_percent"] == 25.0
        assert updated.metadata["segments_selected"] == 8
        assert len(updated.tool_history) >= 1
        assert updated.tool_history[-1]["detail"] == "SmartCut完了"


# ============================================================
# C4: ディスク永続化・エラー耐性 (3)
# ============================================================

class TestC4Persistence:
    """C4: ディスク永続化・エラー耐性テスト"""

    def test_S_C4_01_save_and_load_roundtrip(self, tmp_session_dir):
        """S-C4-01: セッションをディスクに保存後、新しい SessionManager で復元し全フィールドが一致すること"""
        # 作成と更新
        mgr1 = SessionManager(session_dir=tmp_session_dir)
        session = mgr1.create_session(
            video_path="/test/important.mp4",
            session_id="roundtrip-test",
            metadata={"template": "gaming"},
        )
        mgr1.update_stage("roundtrip-test", stage=2, detail="校閲完了")
        mgr1.record_tool_call(
            "roundtrip-test", "proofread_subtitles",
            {"segments": 10}, {"corrections": 3}, 5.2,
        )

        # 新しいインスタンスで復元
        mgr2 = SessionManager(session_dir=tmp_session_dir)
        restored = mgr2.get_session("roundtrip-test")

        assert restored is not None
        assert restored.video_path == "/test/important.mp4"
        assert restored.metadata["template"] == "gaming"
        assert restored.current_stage == 2
        assert len(restored.tool_history) == 2  # update_stage + record_tool_call
        # 復元時に active → paused に変更されること
        assert restored.status == "paused"

    def test_S_C4_02_load_corrupted_json(self, tmp_session_dir):
        """S-C4-02: 破損 JSON ファイルがセッションディレクトリにある場合、スキップしてエラーにならないこと"""
        # 破損JSONを作成
        corrupted_path = tmp_session_dir / "corrupted-session.json"
        corrupted_path.write_text("{invalid json content", encoding="utf-8")

        # 正常なセッションも作成
        valid_data = {
            "session_id": "valid-session",
            "created_at": datetime.now().isoformat(),
            "last_active_at": datetime.now().isoformat(),
            "status": "active",
            "video_path": "/test.mp4",
            "current_stage": 0,
            "total_stages": 7,
            "quality_score": 0,
            "tool_history": [],
            "metadata": {},
            "pipeline_started_at": datetime.now().isoformat(),
            "pipeline_completed_at": None,
        }
        valid_path = tmp_session_dir / "valid-session.json"
        valid_path.write_text(
            json.dumps(valid_data, ensure_ascii=False),
            encoding="utf-8",
        )

        # 新しいManagerで読み込み → 破損ファイルはスキップ、正常ファイルは復元
        mgr = SessionManager(session_dir=tmp_session_dir)
        assert mgr.get_session("valid-session") is not None
        assert mgr.get_session("corrupted-session") is None

    def test_S_C4_03_load_restores_active_as_paused(self, tmp_session_dir):
        """S-C4-03: 前回 active だったセッションが _load_active_sessions で paused に変更されること"""
        # active 状態のセッションを直接ディスクに書き込む
        active_data = {
            "session_id": "was-active",
            "created_at": datetime.now().isoformat(),
            "last_active_at": datetime.now().isoformat(),
            "status": "active",  # 前回のプロセスで active だった
            "video_path": "/test.mp4",
            "current_stage": 3,
            "total_stages": 7,
            "quality_score": 0,
            "tool_history": [],
            "metadata": {},
            "pipeline_started_at": datetime.now().isoformat(),
            "pipeline_completed_at": None,
        }
        path = tmp_session_dir / "was-active.json"
        path.write_text(json.dumps(active_data), encoding="utf-8")

        # completed 状態のセッションも配置
        completed_data = dict(active_data)
        completed_data["session_id"] = "was-completed"
        completed_data["status"] = "completed"
        path2 = tmp_session_dir / "was-completed.json"
        path2.write_text(json.dumps(completed_data), encoding="utf-8")

        # 新しいManagerで読み込み
        mgr = SessionManager(session_dir=tmp_session_dir)

        # active → paused に変更されていること
        was_active = mgr.get_session("was-active")
        assert was_active.status == "paused"

        # completed はそのままであること
        was_completed = mgr.get_session("was-completed")
        assert was_completed.status == "completed"


# ============================================================
# C5: クリーンアップ (1)
# ============================================================

class TestC5Cleanup:
    """C5: クリーンアップテスト"""

    def test_S_C5_01_cleanup_old_sessions(self, tmp_session_dir):
        """S-C5-01: CLEANUP_DAYS 超過のセッションファイルが削除され、メモリからも除去されること"""
        # 古いセッション（31日前）をディスクに直接配置
        old_time = (datetime.now() - timedelta(days=31)).isoformat()
        old_data = {
            "session_id": "old-session",
            "created_at": old_time,
            "last_active_at": old_time,
            "status": "completed",
            "video_path": "/old.mp4",
            "current_stage": 7,
            "total_stages": 7,
            "quality_score": 85,
            "tool_history": [],
            "metadata": {},
            "pipeline_started_at": old_time,
            "pipeline_completed_at": old_time,
        }
        old_path = tmp_session_dir / "old-session.json"
        old_path.write_text(json.dumps(old_data), encoding="utf-8")

        # 新しいセッション（今日）もディスクに配置
        new_time = datetime.now().isoformat()
        new_data = dict(old_data)
        new_data["session_id"] = "new-session"
        new_data["created_at"] = new_time
        new_data["last_active_at"] = new_time
        new_data["status"] = "active"
        new_path = tmp_session_dir / "new-session.json"
        new_path.write_text(json.dumps(new_data), encoding="utf-8")

        mgr = SessionManager(session_dir=tmp_session_dir)

        # old-session は _load_active_sessions で既に削除されている可能性があるため
        # 念のためクリーンアップも実行
        removed = mgr.cleanup_old_sessions()

        # 古いセッションが削除されていること
        assert not old_path.exists()
        assert mgr.get_session("old-session") is None

        # 新しいセッションは残っていること
        assert new_path.exists()
        assert mgr.get_session("new-session") is not None


# ============================================================
# C6: 性能 (2)
# ============================================================

class TestC6Performance:
    """C6: 性能テスト"""

    def test_S_C6_01_create_100_sessions_speed(self, session_mgr):
        """S-C6-01: 100セッション作成が1秒以内に完了すること"""
        start = time.perf_counter()
        for i in range(100):
            session_mgr.create_session(
                video_path=f"/test/video_{i}.mp4",
                session_id=f"perf-test-{i}",
            )
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"100セッション作成: {elapsed*1000:.0f}ms (> 1000ms)"
        assert len(session_mgr._active_sessions) == 100

    def test_S_C6_02_list_sessions_sorting(self, session_mgr):
        """S-C6-02: list_sessions() が last_active_at 降順で返されること"""
        import time as time_mod

        # 異なるタイムスタンプで3セッションを作成
        s1 = session_mgr.create_session(session_id="sort-1")
        time_mod.sleep(0.01)
        s2 = session_mgr.create_session(session_id="sort-2")
        time_mod.sleep(0.01)
        s3 = session_mgr.create_session(session_id="sort-3")

        listing = session_mgr.list_sessions()

        # 最新のものが先頭に来ること
        assert listing[0]["session_id"] == "sort-3"
        assert listing[1]["session_id"] == "sort-2"
        assert listing[2]["session_id"] == "sort-1"


# ============================================================
# C7: 追加カバレッジおよび例外ハンドリング検証 (10)
# ============================================================

class TestC7AdditionalCoverage:
    """C7: 追加カバレッジおよび例外ハンドリング検証（100%化）"""

    def test_S_C7_01_resume_paused_from_memory(self, session_mgr):
        """S-C7-01: メモリ上にあり status=paused のセッションを resume した際、status が active になること"""
        session = session_mgr.create_session(session_id="mem-paused-test")
        session_mgr.pause_session("mem-paused-test")
        assert session.status == "paused"

        resumed = session_mgr.resume_session("mem-paused-test")
        assert resumed is not None
        assert resumed.status == "active"

    def test_S_C7_02_resume_session_disk_exception(self, tmp_session_dir, caplog):
        """S-C7-02: ディスクからの resume 時に例外が発生した場合、None を返し、ログが出力されること"""
        mgr = SessionManager(session_dir=tmp_session_dir)
        # 意図的に破損したJSONを配置
        corrupted_path = tmp_session_dir / "bad-resume.json"
        corrupted_path.write_text("{invalid json", encoding="utf-8")

        with caplog.at_level("ERROR"):
            resumed = mgr.resume_session("bad-resume")
            assert resumed is None
            assert any("Session resume failed" in record.message for record in caplog.records)

    def test_S_C7_03_nonexistent_session_operations(self, session_mgr):
        """S-C7-03: 存在しない session_id に対して操作を行ってもエラーにならず無視されること"""
        # None や例外が出ずに正常終了することを確認
        session_mgr.update_stage("nonexistent", stage=1)
        session_mgr.record_tool_call("nonexistent", "tool", {}, {}, 1.0)
        session_mgr.complete_session("nonexistent")

    def test_S_C7_04_update_stage_history_truncation(self, session_mgr):
        """S-C7-04: update_stage を 51回呼び出した際、history が 50件に切り詰められること"""
        session = session_mgr.create_session(session_id="update-stage-trunc")
        sid = session.session_id

        for i in range(55):
            session_mgr.update_stage(sid, stage=1, detail=f"stage_{i}")

        updated = session_mgr.get_session(sid)
        assert len(updated.tool_history) == SessionManager.MAX_TOOL_HISTORY  # 50
        assert updated.tool_history[-1]["detail"] == "stage_54"

    def test_S_C7_05_complete_session_with_final_data(self, session_mgr):
        """S-C7-05: complete_session に final_data を指定した際、metadata にマージされること"""
        session = session_mgr.create_session(session_id="complete-final-data", metadata={"initial": 1})
        session_mgr.complete_session("complete-final-data", quality_score=95, final_data={"final": 2})

        updated = session_mgr.get_session("complete-final-data")
        assert updated.status == "completed"
        assert updated.quality_score == 95
        assert updated.metadata == {"initial": 1, "final": 2}

    def test_S_C7_06_get_stats(self, session_mgr):
        """S-C7-06: get_stats() が正しい状態別カウントを返すこと"""
        session_mgr.create_session(session_id="s-active")
        
        s_paused = session_mgr.create_session(session_id="s-paused")
        session_mgr.pause_session("s-paused")

        s_comp = session_mgr.create_session(session_id="s-completed")
        session_mgr.complete_session("s-completed", quality_score=80)

        s_err = session_mgr.create_session(session_id="s-error")
        session_mgr.error_session("s-error", "dummy error")

        stats = session_mgr.get_stats()
        assert stats["total"] == 4
        assert stats["active"] == 1
        assert stats["paused"] == 1
        assert stats["completed"] == 1
        assert stats["error"] == 1

    def test_S_C7_07_save_session_exception(self, tmp_session_dir, caplog):
        """S-C7-07: セッション保存時に OSError が発生した場合、適切にログ出力されること"""
        mgr = SessionManager(session_dir=tmp_session_dir)
        session = mgr.create_session(session_id="save-err-test")

        from unittest.mock import patch
        with patch("pathlib.Path.write_text", side_effect=OSError("Disk full")):
            with caplog.at_level("ERROR"):
                mgr._save_session(session)
                assert any("Session save failed" in record.message for record in caplog.records)

    def test_S_C7_08_load_active_sessions_exception(self, tmp_session_dir, caplog):
        """S-C7-08: _load_active_sessions 中に JSON パース例外が発生した際、ログが出力されること"""
        # 破損したJSON
        path = tmp_session_dir / "bad-load.json"
        path.write_text("{bad", encoding="utf-8")

        with caplog.at_level("ERROR"):
            mgr = SessionManager(session_dir=tmp_session_dir)
            assert any("Failed to load active session" in record.message for record in caplog.records)

    def test_S_C7_09_cleanup_old_sessions_exception(self, tmp_session_dir, caplog):
        """S-C7-09: cleanup_old_sessions 中に例外が発生した際、適切にハンドリングされてログが出力されること"""
        # CLEANUP_DAYS より古い、破損したセッションファイルを配置
        old_time = (datetime.now() - timedelta(days=31)).isoformat()
        bad_path = tmp_session_dir / "bad-cleanup.json"
        bad_path.write_text("{bad", encoding="utf-8")

        mgr = SessionManager(session_dir=tmp_session_dir)

        with caplog.at_level("ERROR"):
            removed = mgr.cleanup_old_sessions()
            assert removed == 0
            assert any("Failed to cleanup session" in record.message for record in caplog.records)

    def test_S_C7_10_cleanup_old_sessions_success_log(self, tmp_session_dir, caplog):
        """S-C7-10: 古いセッションのクリーンアップに成功した際、クリーンアップログが出力されること"""
        old_time = (datetime.now() - timedelta(days=31)).isoformat()
        old_data = {
            "session_id": "old-success",
            "created_at": old_time,
            "last_active_at": old_time,
            "status": "completed",
            "video_path": "/old.mp4",
            "current_stage": 7,
            "total_stages": 7,
            "quality_score": 85,
            "tool_history": [],
            "metadata": {},
            "pipeline_started_at": old_time,
            "pipeline_completed_at": old_time,
        }
        old_path = tmp_session_dir / "old-success.json"
        old_path.write_text(json.dumps(old_data), encoding="utf-8")

        mgr = SessionManager(session_dir=tmp_session_dir)
        old_path.write_text(json.dumps(old_data), encoding="utf-8")

        with caplog.at_level("INFO"):
            removed = mgr.cleanup_old_sessions()
            assert removed == 1
            assert any("old sessions cleaned up" in record.message for record in caplog.records)

    def test_S_C7_11_resume_non_paused_from_memory(self, session_mgr):
        """S-C7-11: メモリ上にあり status!=paused のセッションを resume した際、status が変更されず active のままであること"""
        session = session_mgr.create_session(session_id="mem-active-test")
        assert session.status == "active"

        resumed = session_mgr.resume_session("mem-active-test")
        assert resumed is not None
        assert resumed.status == "active"

    def test_S_C7_12_pause_nonexistent_session(self, session_mgr):
        """S-C7-12: 存在しない session_id に対して pause_session を呼び出した際、エラーにならず何もしないこと"""
        # 例外が発生せずに正常終了することを確認
        session_mgr.pause_session("nonexistent-paused")

    def test_S_C7_13_error_nonexistent_session(self, session_mgr):
        """S-C7-13: 存在しない session_id に対して error_session を呼び出した際、エラーにならず何もしないこと"""
        # 例外が発生せずに正常終了することを確認
        session_mgr.error_session("nonexistent-error", "some error")

    def test_S_C7_14_list_sessions_limit(self, session_mgr):
        """S-C7-14: list_sessions で limit パラメータが正しく機能すること"""
        session_mgr.create_session(session_id="limit-1")
        session_mgr.create_session(session_id="limit-2")
        session_mgr.create_session(session_id="limit-3")

        # limit=2 で呼び出した際、2件のみ取得できること
        sessions = session_mgr.list_sessions(limit=2)
        assert len(sessions) == 2
        # 最新のものが並んでいること
        assert sessions[0]["session_id"] == "limit-3"
        assert sessions[1]["session_id"] == "limit-2"

    def test_S_C7_15_record_tool_call_truncation(self, session_mgr):
        """S-C7-15: record_tool_call で 100文字超の引数が 100文字で切り捨てられること"""
        session = session_mgr.create_session(session_id="truncation-test")
        sid = session.session_id

        long_arg = "a" * 150
        session_mgr.record_tool_call(
            sid,
            tool_name="test_tool",
            args={"param": long_arg},
            result={},
            duration_seconds=1.0,
        )

        updated = session_mgr.get_session(sid)
        args_summary = updated.tool_history[-1]["args_summary"]
        assert len(args_summary["param"]) == 100
        assert args_summary["param"] == "a" * 100
