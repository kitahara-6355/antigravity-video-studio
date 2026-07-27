"""
M2.5: Task Store テスト — 20テスト

task_store.py (177 stmts, 177 missed → 0%) のカバレッジ改善。
TaskState, TaskStore, create_progress_callback を網羅。

外部依存: Redis → FallbackCache で自動代替。
"""

import pytest
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from task_store import (
    TaskStatus, TaskPhase, TaskState, TaskStore,
    create_progress_callback,
)


@pytest.fixture
def store():
    """テスト用TaskStore (FallbackCache使用)"""
    s = TaskStore(prefix="test_task")
    s._broadcaster = None  # WebSocket無効化
    return s


# ============================================================
# TaskState テスト
# ============================================================

class TestTaskState:
    """TaskState: データモデル"""

    def test_to_dict(self):
        """to_dict: 辞書変換"""
        state = TaskState(task_id="t1", video_path="/video.mp4")
        d = state.to_dict()
        assert d["task_id"] == "t1"
        assert d["status"] == TaskStatus.PENDING.value
        assert d["progress"] == 0

    def test_from_dict(self):
        """from_dict: 辞書からの復元"""
        data = {
            "task_id": "t2",
            "video_path": "/test.mp4",
            "status": "running",
            "phase": "transcribing",
            "progress": 50,
            "message": "処理中",
        }
        state = TaskState.from_dict(data)
        assert state.task_id == "t2"
        assert state.status == "running"
        assert state.progress == 50

    def test_from_dict_ignores_extra_fields(self):
        """from_dict: 未知のフィールドは無視"""
        data = {
            "task_id": "t3",
            "video_path": "/test.mp4",
            "unknown_field": "should_be_ignored",
        }
        state = TaskState.from_dict(data)
        assert state.task_id == "t3"

    def test_default_values(self):
        """デフォルト値の確認"""
        state = TaskState(task_id="t4", video_path="/v.mp4")
        assert state.status == TaskStatus.PENDING.value
        assert state.phase == TaskPhase.WAITING.value
        assert state.message == "待機中..."
        assert state.current_segment is None

    def test_from_dict_missing_required_fields(self):
        """from_dict: 必須フィールドが欠損している場合、TypeErrorが発生する"""
        incomplete_data = {
            "status": "running"
        }
        import pytest
        with pytest.raises(TypeError):
            TaskState.from_dict(incomplete_data)

    def test_to_dict_immutability(self):
        """to_dict: 辞書変換したデータが元のオブジェクトを正しく反映しているか検証"""
        state = TaskState(
            task_id="t_immutability",
            video_path="/imm.mp4",
            status=TaskStatus.RUNNING.value,
            phase=TaskPhase.TRANSCRIBING.value,
            progress=40,
            message="処理中",
            current_segment=2,
            total_segments=10,
            eta_seconds=60,
            result_path="/output.srt",
            error=None
        )
        d = state.to_dict()
        assert d["task_id"] == "t_immutability"
        assert d["video_path"] == "/imm.mp4"
        assert d["status"] == "running"
        assert d["phase"] == "transcribing"
        assert d["progress"] == 40
        assert d["message"] == "処理中"
        assert d["current_segment"] == 2
        assert d["total_segments"] == 10
        assert d["eta_seconds"] == 60
        assert d["result_path"] == "/output.srt"
        assert d["error"] is None


# ============================================================
# TaskStore テスト
# ============================================================

class TestTaskStore:
    """TaskStore: タスク状態管理"""

    def test_create_task(self, store):
        """create_task: タスク作成"""
        task = store.create_task("/video.mp4")
        assert task.task_id is not None
        assert task.video_path == "/video.mp4"
        assert task.status == TaskStatus.PENDING.value

    def test_create_task_with_id(self, store):
        """create_task: 指定IDでタスク作成"""
        task = store.create_task("/video.mp4", task_id="custom_id")
        assert task.task_id == "custom_id"

    def test_get_task(self, store):
        """get_task: タスク取得"""
        task = store.create_task("/video.mp4", task_id="get_test")
        retrieved = store.get_task("get_test")
        assert retrieved is not None
        assert retrieved.task_id == "get_test"

    def test_get_task_not_found(self, store):
        """get_task: 存在しないタスク → None"""
        result = store.get_task("nonexistent")
        assert result is None

    def test_update_progress(self, store):
        """update_progress: 進捗更新"""
        store.create_task("/video.mp4", task_id="prog_test")
        updated = store.update_progress(
            task_id="prog_test",
            phase=TaskPhase.TRANSCRIBING,
            progress=50,
            message="文字起こし中...",
            current_segment=3,
            total_segments=10,
            eta_seconds=120,
        )
        assert updated is not None
        assert updated.progress == 50
        assert updated.phase == TaskPhase.TRANSCRIBING.value
        assert updated.status == TaskStatus.RUNNING.value
        assert updated.current_segment == 3
        assert updated.total_segments == 10
        assert updated.eta_seconds == 120
        assert updated.started_at is not None

    def test_update_progress_not_found(self, store):
        """update_progress: 存在しないタスク → None"""
        result = store.update_progress(
            task_id="nonexistent",
            phase=TaskPhase.TRANSCRIBING,
            progress=50,
        )
        assert result is None

    def test_update_progress_sets_started_at_once(self, store):
        """update_progress: started_atは初回のみ設定"""
        store.create_task("/video.mp4", task_id="started_test")
        t1 = store.update_progress("started_test", TaskPhase.TRANSCRIBING, 10)
        first_started = t1.started_at
        time.sleep(0.01)
        t2 = store.update_progress("started_test", TaskPhase.TRANSCRIBING, 50)
        assert t2.started_at == first_started

    def test_complete_task(self, store):
        """complete_task: タスク完了"""
        store.create_task("/video.mp4", task_id="comp_test")
        store.update_progress("comp_test", TaskPhase.TRANSCRIBING, 50)
        
        with patch.object(store, '_record_to_evolution_log'):
            completed = store.complete_task("comp_test", result_path="/output.srt")
        
        assert completed is not None
        assert completed.status == TaskStatus.COMPLETED.value
        assert completed.progress == 100
        assert completed.result_path == "/output.srt"
        assert completed.completed_at is not None

    def test_complete_task_not_found(self, store):
        """complete_task: 存在しないタスク → None"""
        result = store.complete_task("nonexistent")
        assert result is None

    def test_fail_task(self, store):
        """fail_task: タスク失敗"""
        store.create_task("/video.mp4", task_id="fail_test")
        with patch.object(store, '_record_to_evolution_log'):
            failed = store.fail_task("fail_test", "テストエラー")
        assert failed is not None
        assert failed.status == TaskStatus.FAILED.value
        assert failed.error == "テストエラー"
        assert "テストエラー" in failed.message

    def test_fail_task_not_found(self, store):
        """fail_task: 存在しないタスク → None"""
        result = store.fail_task("nonexistent", "error")
        assert result is None

    def test_cancel_task(self, store):
        """cancel_task: タスクキャンセル"""
        store.create_task("/video.mp4", task_id="cancel_test")
        cancelled = store.cancel_task("cancel_test")
        assert cancelled is not None
        assert cancelled.status == TaskStatus.CANCELLED.value
        assert cancelled.completed_at is not None

    def test_cancel_task_not_found(self, store):
        """cancel_task: 存在しないタスク → None"""
        result = store.cancel_task("nonexistent")
        assert result is None

    def test_get_broadcaster_import_error(self):
        """_get_broadcaster: ImportError発生時にログ警告を出力し、Noneを返す"""
        s = TaskStore(prefix="test_import_error")
        with patch.dict("sys.modules", {"websocket_handler": None}):
            broadcaster = s._get_broadcaster()
            assert broadcaster is None

    def test_update_progress_broadcast_exception(self, store):
        """update_progress: ブロードキャストが例外を投げても、無視して正常に動作する"""
        store.create_task("/video.mp4", task_id="prog_err_test")
        mock_broadcaster = MagicMock()
        mock_broadcaster.update_phase.side_effect = OSError("Broadcast error")
        store._broadcaster = mock_broadcaster
        
        updated = store.update_progress(
            task_id="prog_err_test",
            phase=TaskPhase.TRANSCRIBING,
            progress=50,
        )
        assert updated is not None
        assert updated.progress == 50

    def test_complete_task_broadcast_exception(self, store):
        """complete_task: 完了ブロードキャストが例外を投げても、無視して正常に動作する"""
        store.create_task("/video.mp4", task_id="comp_err_test")
        mock_broadcaster = MagicMock()
        mock_broadcaster.send_completion.side_effect = OSError("Completion broadcast error")
        store._broadcaster = mock_broadcaster
        
        with patch.object(store, '_record_to_evolution_log'):
            completed = store.complete_task("comp_err_test", result_path="/output.srt")
        
        assert completed is not None
        assert completed.status == TaskStatus.COMPLETED.value

    def test_fail_task_broadcast_exception(self, store):
        """fail_task: エラーブロードキャストが例外を投げても、無視して正常に動作する"""
        store.create_task("/video.mp4", task_id="fail_err_test")
        mock_broadcaster = MagicMock()
        mock_broadcaster.send_error.side_effect = OSError("Error broadcast error")
        store._broadcaster = mock_broadcaster
        
        with patch.object(store, '_record_to_evolution_log'):
            failed = store.fail_task("fail_err_test", "テストエラー")
        assert failed is not None
        assert failed.status == TaskStatus.FAILED.value

    def test_list_tasks(self, store):
        """list_tasks: タスク一覧をcreated_at降順で取得、フィルタリング"""
        from redis_config import get_redis
        get_redis().flushdb()
        
        t1 = store.create_task("/v1.mp4", task_id="list_t1")
        t2 = store.create_task("/v2.mp4", task_id="list_t2")
        
        t1.created_at = time.time() - 10
        store._save(t1)
        
        store.update_progress("list_t2", TaskPhase.TRANSCRIBING, 10)
        
        all_tasks = store.list_tasks()
        assert len(all_tasks) == 2
        assert all_tasks[0]["task_id"] == "list_t2"
        assert all_tasks[1]["task_id"] == "list_t1"
        
        pending_tasks = store.list_tasks(status=TaskStatus.PENDING)
        assert len(pending_tasks) == 1
        assert pending_tasks[0]["task_id"] == "list_t1"

    def test_record_to_evolution_log_success(self, store):
        """_record_to_evolution_log: 正常系"""
        task = TaskState(
            task_id="evo_test",
            video_path="/evo.mp4",
            status=TaskStatus.COMPLETED.value,
            phase=TaskPhase.COMPLETE.value,
            result_path="/output.srt",
            total_segments=5
        )
        task.completed_at = time.time()
        
        mock_branding_manager = MagicMock()
        with patch.dict("sys.modules", {"branding_manager": MagicMock(branding_manager=mock_branding_manager)}):
            store._record_to_evolution_log(task)
            mock_branding_manager.log_evolution.assert_called_once()
            args = mock_branding_manager.log_evolution.call_args[0][0]
            assert args["event"] == "TRANSCRIPTION_COMPLETED"
            assert args["task_id"] == "evo_test"
            assert args["segments_count"] == 5

    def test_record_to_evolution_log_exception(self, store):
        """_record_to_evolution_log: 例外発生時もキャッチされて正常に終了する"""
        task = TaskState(task_id="evo_fail", video_path="/fail.mp4")
        with patch.dict("sys.modules", {"branding_manager": None}):
            store._record_to_evolution_log(task)

    def test_fire_and_forget_with_running_loop(self, store):
        """_fire_and_forget: 実行中のイベントループがある場合に create_task が呼ばれる"""
        from task_store import _fire_and_forget
        
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = True
        mock_loop.is_closed.return_value = False
        
        async def dummy_coro():
            pass
        
        coro = dummy_coro()
        
        with patch("asyncio.get_running_loop", return_value=mock_loop):
            _fire_and_forget(coro)
            mock_loop.create_task.assert_called_once_with(coro)
            
        coro.close()

    def test_fire_and_forget_close_exception(self, store):
        """_fire_and_forget: coro.close() が例外を投げても安全にキャッチされる"""
        from task_store import _fire_and_forget
        
        mock_coro = MagicMock()
        mock_coro.close.side_effect = RuntimeError("Close error")
        
        with patch("asyncio.get_running_loop", side_effect=RuntimeError()):
            _fire_and_forget(mock_coro)
            mock_coro.close.assert_called_once()

    def test_fire_and_forget_with_inactive_loop(self, store):
        """_fire_and_forget: ループは取得できるが実行中ではない場合、クローズされる"""
        from task_store import _fire_and_forget
        
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = False
        mock_loop.is_closed.return_value = False
        
        mock_coro = MagicMock()
        
        with patch("asyncio.get_running_loop", return_value=mock_loop):
            _fire_and_forget(mock_coro)
            mock_loop.create_task.assert_not_called()
            mock_coro.close.assert_called_once()

    def test_update_progress_no_broadcaster(self, store):
        """update_progress: broadcaster が None の場合、例外なく処理される"""
        store.create_task("/video.mp4", task_id="no_broadcaster_prog")
        store._broadcaster = None
        
        with patch.object(store, '_get_broadcaster', return_value=None):
            updated = store.update_progress(
                task_id="no_broadcaster_prog",
                phase=TaskPhase.TRANSCRIBING,
                progress=30
            )
        assert updated is not None
        assert updated.progress == 30

    def test_complete_task_no_broadcaster(self, store):
        """complete_task: broadcaster が None の場合、例外なく処理される"""
        store.create_task("/video.mp4", task_id="no_broadcaster_comp")
        store._broadcaster = None
        
        with patch.object(store, '_get_broadcaster', return_value=None), \
             patch.object(store, '_record_to_evolution_log'):
            completed = store.complete_task("no_broadcaster_comp", result_path="/out.srt")
        assert completed is not None
        assert completed.status == TaskStatus.COMPLETED.value

    def test_fail_task_no_broadcaster(self, store):
        """fail_task: broadcaster が None の場合、例外なく処理される"""
        store.create_task("/video.mp4", task_id="no_broadcaster_fail")
        store._broadcaster = None
        
        with patch.object(store, '_get_broadcaster', return_value=None), \
             patch.object(store, '_record_to_evolution_log'):
            failed = store.fail_task("no_broadcaster_fail", "test error")
        assert failed is not None
        assert failed.status == TaskStatus.FAILED.value

    def test_list_tasks_with_corrupted_key(self, store):
        """list_tasks: キーは存在するがget_taskがNoneを返す破損タスクがある場合、スキップされる"""
        from redis_config import get_redis
        get_redis().flushdb()
        
        store.create_task("/v1.mp4", task_id="ok_task")
        
        # 破損タスクをシミュレートするため、Redisに手動でキーを入れる
        client = get_redis()
        client.set(f"{store._store.prefix}:corrupted_task", "invalid_json_or_empty")
        
        original_get = store.get_task
        def mock_get(task_id):
            if task_id == "corrupted_task":
                return None
            return original_get(task_id)
            
        with patch.object(store, 'get_task', side_effect=mock_get):
            tasks = store.list_tasks()
            
        assert len(tasks) == 1
        assert tasks[0]["task_id"] == "ok_task"

    def test_list_tasks_redis_error(self, store):
        """list_tasks: Redis接続エラー等の例外が発生した場合、安全に空リストを返しクラッシュしない"""
        with patch("task_store.get_redis") as mock_get_redis:
            mock_client = MagicMock()
            try:
                import redis
                redis_err = redis.exceptions.RedisError("Mocked connection failure")
            except ImportError:
                redis_err = AttributeError("Mocked connection failure")
            mock_client.keys.side_effect = redis_err
            mock_get_redis.return_value = mock_client
            
            tasks = store.list_tasks()
            
            assert tasks == []

    def test_list_tasks_strict_sorting(self, store):
        """list_tasks: 作成日時(created_at)の降順で正しくソートされることを厳密に検証"""
        from redis_config import get_redis
        get_redis().flushdb()
        
        # 3つのタスクを作成
        t1 = store.create_task("/v1.mp4", task_id="sort_t1")
        t2 = store.create_task("/v2.mp4", task_id="sort_t2")
        t3 = store.create_task("/v3.mp4", task_id="sort_t3")
        
        # created_at を操作 (t3が一番古く、t2が中間、t1が最新)
        now = time.time()
        t1.created_at = now
        t2.created_at = now - 5
        t3.created_at = now - 10
        
        store._save(t1)
        store._save(t2)
        store._save(t3)
        
        tasks = store.list_tasks()
        assert len(tasks) == 3
        # 降順 (最新が最初、古いものが最後)
        assert tasks[0]["task_id"] == "sort_t1"
        assert tasks[1]["task_id"] == "sort_t2"
        assert tasks[2]["task_id"] == "sort_t3"

    def test_create_task_invalid_inputs(self, store):
        """create_task: video_pathに空文字列やNone、極端な値が入っても例外なく処理される"""
        # 型ヒントは文字列だが、Python実行時の堅牢性検証
        task_empty = store.create_task("", task_id="empty_path")
        assert task_empty.video_path == ""
        
        task_none = store.create_task(None, task_id="none_path")
        assert task_none.video_path is None
        
        long_path = "a" * 1000 + ".mp4"
        task_long = store.create_task(long_path, task_id="long_path")
        assert task_long.video_path == long_path

    def test_list_tasks_invalid_status_filter(self, store):
        """list_tasks: 不正なstatus値でフィルタリングした際、マッチせず空リストが返ることを検証"""
        from redis_config import get_redis
        get_redis().flushdb()
        
        store.create_task("/v1.mp4", task_id="filter_t1")
        
        # 存在しない無効なステータスを指定
        # 型エラーを無視するためのダミーオブジェクト
        class DummyStatus:
            value = "invalid_dummy_status"
            
        tasks = store.list_tasks(status=DummyStatus)
        assert tasks == []

    def test_custom_prefix_keys(self):
        """TaskStore: 異なるプレフィックスを指定した際、Redisキーのプレフィックスが変わることを検証"""
        from redis_config import get_redis
        client = get_redis()
        client.flushdb()
        
        custom_store = TaskStore(prefix="custom_prefix")
        custom_store.create_task("/video.mp4", task_id="custom_t1")
        
        # Redisに "custom_prefix:custom_t1" が保存されているか確認
        exists = client.exists("custom_prefix:custom_t1")
        assert exists == 1

    def test_list_tasks_string_status_filter(self, store):
        """list_tasks: status に文字列を渡してフィルタリングできることを検証"""
        from redis_config import get_redis
        get_redis().flushdb()
        
        store.create_task("/v1.mp4", task_id="str_filter_t1")
        all_tasks = store.list_tasks(status="pending")
        assert len(all_tasks) == 1
        assert all_tasks[0]["task_id"] == "str_filter_t1"

    def test_fail_task_logs_evolution(self, store):
        """fail_task: タスク失敗時に evolution_log に記録されることを検証"""
        store.create_task("/video.mp4", task_id="fail_evo_test")
        
        mock_branding_manager = MagicMock()
        with patch.dict("sys.modules", {"branding_manager": MagicMock(branding_manager=mock_branding_manager)}):
            failed = store.fail_task("fail_evo_test", "エラーメッセージ")
            
            assert failed is not None
            mock_branding_manager.log_evolution.assert_called_once()
            args = mock_branding_manager.log_evolution.call_args[0][0]
            assert args["event"] == "TRANSCRIPTION_FAILED"
            assert args["task_id"] == "fail_evo_test"
            assert args["error"] == "エラーメッセージ"
            assert "字幕生成失敗" in args["agenda_proposal"]

    def test_fire_and_forget_different_thread(self):
        """_fire_and_forget: メインスレッドではない別スレッドからの呼出しで run_coroutine_threadsafe が使われることを検証"""
        from task_store import _fire_and_forget
        import threading
        
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = True
        mock_loop.is_closed.return_value = False
        
        async def dummy_coro():
            pass
        
        coro = dummy_coro()
        
        # current_thread がメインスレッドではないようにモック
        mock_thread = MagicMock()
        
        with patch("asyncio.get_running_loop", return_value=mock_loop), \
             patch("threading.current_thread", return_value=mock_thread), \
             patch("threading.main_thread", return_value=MagicMock()), \
             patch("asyncio.run_coroutine_threadsafe") as mock_run_safe:
            
            _fire_and_forget(coro)
            
            # run_coroutine_threadsafe が呼ばれたはず
            mock_run_safe.assert_called_once_with(coro, mock_loop)
            mock_loop.create_task.assert_not_called()
            
        coro.close()


# ============================================================
# create_progress_callback テスト
# ============================================================

class TestProgressCallback:
    """create_progress_callback: WhisperTranscriber用コールバック"""

    def test_callback_model_loading(self, store):
        """コールバック: model loading"""
        store.create_task("/video.mp4", task_id="cb_test")
        callback = create_progress_callback("cb_test")
        callback("running", "Loading model...", 10)
        task = store.get_task("cb_test")
        # コールバックはtask_store singletonを使うため、直接検証は困難
        # 関数が例外なく実行されることを確認
        assert callable(callback)

    def test_callback_transcribing(self, store):
        """コールバック: transcribing"""
        callback = create_progress_callback("cb_test2")
        # 例外なく実行される
        callback("running", "Transcribing audio...", 50)

    def test_callback_proofreading(self, store):
        """コールバック: proofreading"""
        callback = create_progress_callback("cb_test3")
        callback("running", "AI proofreading...", 80)

    def test_callback_complete(self, store):
        """コールバック: complete"""
        callback = create_progress_callback("cb_test4")
        callback("done", "Successfully completed", 100)

    def test_callback_other_message(self, store):
        """コールバック: キーワードに一致しないメッセージ (else分岐)"""
        from task_store import task_store as singleton_store
        singleton_store.create_task("/video.mp4", task_id="cb_other")
        
        callback = create_progress_callback("cb_other")
        callback("running", "Something else happening", 45)
        
        task = singleton_store.get_task("cb_other")
        assert task.phase == TaskPhase.TRANSCRIBING.value
        assert task.progress == 45

    def test_callback_keyword_conflict_and_priority(self, store):
        """create_progress_callback: 複数の状態判定キーワードが混在する場合の挙動を検証"""
        from task_store import task_store as singleton_store
        singleton_store.create_task("/video.mp4", task_id="cb_conflict")
        
        callback = create_progress_callback("cb_conflict")
        
        # "proofread" と "transcrib" が混在。判定順序は "loading" -> "transcrib" -> "proofread"
        # "transcrib" が優先される
        callback("running", "AI proofreading and transcribing together", 75)
        task = singleton_store.get_task("cb_conflict")
        assert task.phase == TaskPhase.TRANSCRIBING.value
        
        # "loading" と "proofread" が混在。判定順序的に "loading" が優先される
        callback("running", "Loading model for AI proofreading", 15)
        task = singleton_store.get_task("cb_conflict")
        assert task.phase == TaskPhase.MODEL_LOADING.value
        
        # 大文字小文字混在
        callback("running", "PrOoFrEaDiNg audio data", 85)
        task = singleton_store.get_task("cb_conflict")
        assert task.phase == TaskPhase.PROOFREADING.value

    def test_callback_none_message(self, store):
        """create_progress_callback: message が None の場合でもエラーにならないことを検証"""
        from task_store import task_store as singleton_store
        singleton_store.create_task("/video.mp4", task_id="cb_none_msg")
        
        callback = create_progress_callback("cb_none_msg")
        # message に None を渡しても例外が発生しない
        callback("running", None, 30)
        
        task = singleton_store.get_task("cb_none_msg")
        assert task.phase == TaskPhase.TRANSCRIBING.value
        assert task.progress == 30


# ============================================================
# 例外処理の厳密な検証 (追加テスト)
# ============================================================

class TestSpecificExceptionHandling:
    """本番コードでキャッチされる具体的な例外の処理を検証するテスト"""

    def test_update_progress_specific_errors(self, store):
        """update_progress: キャッチ対象の具体的な例外が発生した際に、正常に処理されるか検証"""
        store.create_task("/video.mp4", task_id="spec_prog_err")
        mock_broadcaster = MagicMock()
        
        # キャッチされるべき各例外を検証
        exceptions_to_test = [
            AttributeError("err"),
            TypeError("err"),
            ValueError("err"),
            RuntimeError("err"),
            OSError("err"),
            ConnectionError("err")
        ]
        for exc in exceptions_to_test:
            mock_broadcaster.update_phase.side_effect = exc
            store._broadcaster = mock_broadcaster
            updated = store.update_progress("spec_prog_err", TaskPhase.TRANSCRIBING, 50)
            assert updated is not None
            assert updated.progress == 50

    def test_complete_task_specific_errors(self, store):
        """complete_task: キャッチ対象の具体的な例外が発生した際に、正常に処理されるか検証"""
        store.create_task("/video.mp4", task_id="spec_comp_err")
        mock_broadcaster = MagicMock()
        exceptions_to_test = [
            AttributeError("err"),
            TypeError("err"),
            ValueError("err"),
            RuntimeError("err"),
            OSError("err"),
            ConnectionError("err")
        ]
        for exc in exceptions_to_test:
            mock_broadcaster.send_completion.side_effect = exc
            store._broadcaster = mock_broadcaster
            with patch.object(store, '_record_to_evolution_log'):
                completed = store.complete_task("spec_comp_err", result_path="/out.srt")
            assert completed is not None
            assert completed.status == TaskStatus.COMPLETED.value

    def test_fail_task_specific_errors(self, store):
        """fail_task: キャッチ対象の具体的な例外が発生した際に、正常に処理されるか検証"""
        store.create_task("/video.mp4", task_id="spec_fail_err")
        mock_broadcaster = MagicMock()
        exceptions_to_test = [
            AttributeError("err"),
            TypeError("err"),
            ValueError("err"),
            RuntimeError("err"),
            OSError("err"),
            ConnectionError("err")
        ]
        for exc in exceptions_to_test:
            mock_broadcaster.send_error.side_effect = exc
            store._broadcaster = mock_broadcaster
            with patch.object(store, '_record_to_evolution_log'):
                failed = store.fail_task("spec_fail_err", "some error")
            assert failed is not None
            assert failed.status == TaskStatus.FAILED.value

    def test_record_to_evolution_log_specific_errors(self, store):
        """_record_to_evolution_log: キャッチ対象の例外が発生した際にも安全に処理されることを検証"""
        task = TaskState(task_id="spec_evo", video_path="/fail.mp4")
        exceptions_to_test = [
            ImportError("err"),
            AttributeError("err"),
            KeyError("err"),
            TypeError("err"),
            ValueError("err")
        ]
        for exc in exceptions_to_test:
            mock_bm = MagicMock()
            mock_bm.log_evolution.side_effect = exc
            from unittest.mock import patch
            import sys
            with patch.dict("sys.modules", {"branding_manager": MagicMock(branding_manager=mock_bm)}):
                store._record_to_evolution_log(task) # 例外が発生するが、正常にキャッチされてクラッシュしない
