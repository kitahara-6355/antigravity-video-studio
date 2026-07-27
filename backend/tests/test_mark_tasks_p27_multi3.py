import sys
from pathlib import Path
import unittest
import os
import asyncio
from unittest.mock import MagicMock, patch

# backend ディレクトリを sys.path に追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from agents.orchestration.mark_tasks_p27_multi3 import (
    initialize_hub,
    mark_completed_tasks,
    print_status,
    main,
    DEFAULT_CONVERSATION_ID,
    generate_thumbnail_p27,
    validate_thumbnail_p27,
    run_thumbnail_task_p27
)

class TestMarkTasksP27Multi3(unittest.TestCase):
    @patch('agents.orchestration.mark_tasks_p27_multi3.OrchestrationHub')
    def test_initialize_hub(self, mock_hub_class):
        mock_hub = MagicMock()
        mock_hub_class.return_value = mock_hub
        
        hub = initialize_hub("dummy-conv-id")
        
        mock_hub_class.assert_called_once()
        mock_hub.register_flash_conversation_id.assert_called_once_with("dummy-conv-id")
        mock_hub.flash_update_heartbeat.assert_called_once()
        self.assertEqual(hub, mock_hub)

    def test_mark_completed_tasks(self):
        mock_hub = MagicMock()
        
        mark_completed_tasks(mock_hub)
        
        self.assertEqual(mock_hub.mark_task_done.call_count, 2)
        mock_hub.mark_task_done.assert_any_call("T-batch_a97ee3-test_weaver-001", "pass", {
            "message": "decision_logger.py のテスト拡充。分岐カバレッジ 99% -> 100% へ向上。",
            "changed_files": ["backend/tests/test_decision_logger_branches.py"]
        })
        mock_hub.mark_task_done.assert_any_call("T-batch_a97ee3-bug_hunter-000", "pass", {
            "message": "metadata_generator.py のエラーハンドリング強化とTDR登録（TD-834）。",
            "changed_files": [
                "backend/metadata_generator.py",
                "backend/tests/test_metadata_generator.py",
                "backend/agents/memory/technical_debt_index.json"
            ]
        })

    def test_print_status(self):
        mock_hub = MagicMock()
        mock_hub.generate_flash_status.return_value = {"status": "ok"}
        
        with patch('builtins.print') as mock_print:
            print_status(mock_hub)
            mock_print.assert_called_once_with('FLASH_STATUS:{"status": "ok"}')

    @patch('agents.orchestration.mark_tasks_p27_multi3.initialize_hub')
    @patch('agents.orchestration.mark_tasks_p27_multi3.mark_completed_tasks')
    @patch('agents.orchestration.mark_tasks_p27_multi3.print_status')
    def test_main(self, mock_print_status, mock_mark_completed, mock_init_hub):
        mock_hub = MagicMock()
        mock_init_hub.return_value = mock_hub
        
        main()
        
        mock_init_hub.assert_called_once()
        mock_mark_completed.assert_called_once_with(mock_hub)
        mock_print_status.assert_called_once_with(mock_hub)

    @patch('backend.agents.orchestration.OrchestrationHub')
    def test_main_execution_block(self, mock_hub_class):
        import runpy
        mock_hub = MagicMock()
        mock_hub.generate_flash_status.return_value = {"status": "ok"}
        mock_hub_class.return_value = mock_hub
        script_path = str(backend_dir / 'agents' / 'orchestration' / 'mark_tasks_p27_multi3.py')
        with patch('builtins.print'):
            runpy.run_path(script_path, run_name='__main__')
        mock_hub_class.assert_called_once()

    @patch('backend.agents.orchestration.OrchestrationHub._generate_error_debug_report')
    @patch('backend.agents.orchestration.OrchestrationHub.flash_report_error')
    @patch('backend.agents.orchestration.OrchestrationHub.flash_update_status')
    @patch('backend.agents.orchestration.orchestrator._read_json')
    @patch('backend.agents.orchestration.orchestrator._write_json')
    def test_mark_task_done_error_debug_report_exception(
        self, mock_write_json, mock_read_json, mock_update_status, mock_report_error, mock_generate_report
    ):
        # TD-759: _generate_error_debug_report で例外が発生した際、サイレントにキャッチ（pass）されることを確認する。
        mock_generate_report.side_effect = Exception("Forced exception for TD-759")
        
        # モックのJSONデータを用意
        mock_read_json.side_effect = lambda path: {
            "tasks": [{"id": "T-001", "status": "pending", "target_module": "dummy"}],
            "current_batch_id": "batch_dummy",
            "phase": 27,
            "milestone": "M27.1"
        } if "task_queue.json" in str(path) else {
            "current_phase": 27,
            "flash_tasks_failed": 0,
            "flash_consecutive_failures": 0
        } if "phase_state.json" in str(path) else {
            "last_heartbeat": None,
            "tasks_completed_in_session": 0
        }
        
        from backend.agents.orchestration import OrchestrationHub
        hub = OrchestrationHub()
        
        try:
            hub.mark_task_done("T-001", "fail", {"error": "some error"})
        except Exception as e:
            self.fail(f"Exceptions should be caught inside mark_task_done: {e}")
            
        mock_generate_report.assert_called_once()
        mock_report_error.assert_called_once()

    # ============================================================
    # サムネイル生成・品質検証・StageBoundAgent連携 テストケース
    # ============================================================

    def test_thumbnail_generation_success(self):
        # 1280x720 16:9 の画像を生成し、検証が通ることを確認
        temp_dir = Path("backend/temp_test_thumbnails")
        temp_dir.mkdir(parents=True, exist_ok=True)
        out_path = temp_dir / "test_success.png"
        if out_path.exists():
            out_path.unlink()
            
        try:
            generate_thumbnail_p27(out_path, width=1280, height=720, text="Test Success")
            self.assertTrue(out_path.exists())
            
            result = validate_thumbnail_p27(out_path)
            self.assertEqual(result["width"], 1280)
            self.assertEqual(result["height"], 720)
            self.assertTrue(result["size_bytes"] < 4 * 1024 * 1024)
            self.assertTrue(result["size_bytes"] > 0)
        finally:
            if 'loop' in locals():
                try:
                    loop.close()
                except Exception:
                    pass
            if out_path.exists():
                out_path.unlink()
            if temp_dir.exists():
                try:
                    temp_dir.rmdir()
                except Exception:
                    pass

    def test_thumbnail_generation_invalid_dimensions(self):
        # アスペクト比が16:9でない場合や、解像度が1280x720未満の場合にエラーになること
        temp_dir = Path("backend/temp_test_thumbnails")
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. 解像度が低すぎる (例えば 1000x562)
        out_path = temp_dir / "test_low_res.png"
        try:
            # 独自に生成する場合は低解像度はOKだが、validate_thumbnail_p27 で解像度が引っかかる
            generate_thumbnail_p27(out_path, width=1024, height=576, text="Low Res")
            with self.assertRaises(ValueError) as ctx:
                validate_thumbnail_p27(out_path)
            self.assertIn("Resolution must be at least 1280x720", str(ctx.exception))
        finally:
            if 'loop' in locals():
                try:
                    loop.close()
                except Exception:
                    pass
            if out_path.exists():
                out_path.unlink()
                
        # 2. アスペクト比が16:9でない (例えば 1280x800)
        out_path2 = temp_dir / "test_invalid_aspect.png"
        try:
            with self.assertRaises(ValueError) as ctx:
                generate_thumbnail_p27(out_path2, width=1280, height=800, text="Invalid Aspect")
            self.assertIn("Aspect ratio must be 16:9", str(ctx.exception))
        finally:
            if out_path2.exists():
                out_path2.unlink()
            if temp_dir.exists():
                try:
                    temp_dir.rmdir()
                except Exception:
                    pass

    def test_thumbnail_validation_corrupted_image(self):
        # ファイルサイズ超過 (4MB以上) や 破損ファイルでエラーになること
        temp_dir = Path("backend/temp_test_thumbnails")
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. 破損ファイル (0バイト)
        out_path = temp_dir / "test_corrupted.png"
        try:
            out_path.touch()
            with self.assertRaises(ValueError) as ctx:
                validate_thumbnail_p27(out_path)
            self.assertIn("Image verification failed", str(ctx.exception))
        finally:
            if 'loop' in locals():
                try:
                    loop.close()
                except Exception:
                    pass
            if out_path.exists():
                out_path.unlink()
                
        # 2. 4MB以上のダミーファイル
        out_path2 = temp_dir / "test_large.png"
        try:
            # 4MB以上のダミーデータを書き込む
            with open(out_path2, "wb") as f:
                f.seek(4 * 1024 * 1024 + 100)
                f.write(b"\0")
            with self.assertRaises(ValueError) as ctx:
                validate_thumbnail_p27(out_path2)
            self.assertIn("File size exceeds 4MB limit", str(ctx.exception))
        finally:
            if out_path2.exists():
                out_path2.unlink()
            if temp_dir.exists():
                try:
                    temp_dir.rmdir()
                except Exception:
                    pass

    def test_stage_bound_agent_integration(self):
        # StageBoundAgent と連携し、自動リトライ、結果保存、および DBマイグレーションを検証
        import tempfile
        import sqlite3
        
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db:
            db_path = tmp_db.name
            
        temp_dir = Path("backend/temp_test_thumbnails")
        temp_dir.mkdir(parents=True, exist_ok=True)
        out_path = temp_dir / "test_agent.png"
        if out_path.exists():
            out_path.unlink()
            
        loop = asyncio.new_event_loop()
        try:
            # 1. DBマイグレーション検証
            # 初期状態の sqlite db を作成
            conn = sqlite3.connect(db_path)
            # 古いスキーマの tasks テーブル (result や retry_count が存在しないもの) を作成
            conn.execute("""
                CREATE TABLE tasks (
                    id TEXT PRIMARY KEY,
                    stage TEXT,
                    status TEXT,
                    error TEXT,
                    created_at REAL,
                    updated_at REAL
                )
            """)
            conn.commit()
            conn.close()
            
            # StageBoundAgent の初期化により、自動的に result, retry_count カラムが追加（マイグレーション）されるか
            # 実行してみる
            task_status = loop.run_until_complete(
                run_thumbnail_task_p27(
                    task_id="t1",
                    db_path=db_path,
                    output_path=str(out_path),
                    width=1280,
                    height=720,
                    text="Agent Test",
                    max_retries=1
                )
            )
            self.assertEqual(task_status, "COMPLETED")
            self.assertTrue(out_path.exists())
            
            # DBの中身を確認し、結果が保存されているか
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM tasks WHERE id = 't1'")
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["status"], "COMPLETED")
            # result カラムが存在し、値が入っているか
            self.assertIn("path", row["result"])
            self.assertEqual(row["retry_count"], 0)
            conn.close()
            
            # 2. 自動リトライ検証
            # 意図的に失敗する関数を process_func_override として渡す
            fail_count = 0
            async def failing_process_func(tid: str) -> str:
                nonlocal fail_count
                fail_count += 1
                if fail_count < 2:
                    raise RuntimeError("Temporary failure")
                # 2回目は成功させる
                generate_thumbnail_p27(out_path, width=1280, height=720, text="Retry Success")
                return "success"
                
            task_status2 = loop.run_until_complete(
                run_thumbnail_task_p27(
                    task_id="t2",
                    db_path=db_path,
                    output_path=str(out_path),
                    width=1280,
                    height=720,
                    text="Retry Test",
                    max_retries=2,
                    process_func_override=failing_process_func
                )
            )
            self.assertEqual(task_status2, "COMPLETED")
            self.assertEqual(fail_count, 2)  # 2回呼び出されたことを確認
            
            # DBで retry_count が記録されていることを確認
            conn = sqlite3.connect(db_path)
            cursor = conn.execute("SELECT retry_count, status, error FROM tasks WHERE id = 't2'")
            row = cursor.fetchone()
            self.assertEqual(row[0], 1)  # 1回リトライした
            self.assertEqual(row[1], "COMPLETED")
            conn.close()
            
        finally:
            if 'loop' in locals():
                try:
                    loop.close()
                except Exception:
                    pass
            if out_path.exists():
                out_path.unlink()
            if temp_dir.exists():
                try:
                    temp_dir.rmdir()
                except Exception:
                    pass
            if os.path.exists(db_path):
                try:
                    os.unlink(db_path)
                except Exception:
                    pass

    def test_thumbnail_generation_none_text(self):
        # text に None や数値を指定してもエラーにならないことを検証
        temp_dir = Path("backend/temp_test_thumbnails")
        temp_dir.mkdir(parents=True, exist_ok=True)
        out_path = temp_dir / "test_none_text.png"
        if out_path.exists():
            out_path.unlink()
            
        try:
            # None を指定
            generate_thumbnail_p27(out_path, width=1280, height=720, text=None)
            self.assertTrue(out_path.exists())
            result = validate_thumbnail_p27(out_path)
            self.assertEqual(result["width"], 1280)
            
            # 数値を指定
            generate_thumbnail_p27(out_path, width=1280, height=720, text=12345)
            self.assertTrue(out_path.exists())
            result2 = validate_thumbnail_p27(out_path)
            self.assertEqual(result2["width"], 1280)
        finally:
            if 'loop' in locals():
                try:
                    loop.close()
                except Exception:
                    pass
            if out_path.exists():
                out_path.unlink()
            if temp_dir.exists():
                try:
                    temp_dir.rmdir()
                except Exception:
                    pass

    def test_thumbnail_validation_directory(self):
        # ディレクトリパスを渡した場合に ValueError が発生することを検証
        temp_dir = Path("backend/temp_test_thumbnails_dir")
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            with self.assertRaises(ValueError) as ctx:
                validate_thumbnail_p27(temp_dir)
            self.assertIn("Thumbnail path is not a file", str(ctx.exception))
        finally:
            if temp_dir.exists():
                try:
                    temp_dir.rmdir()
                except Exception:
                    pass

    def test_run_thumbnail_task_timeout(self):
        # タスク実行がタイムアウトした場合、DBが FAILED に更新されることを検証
        import tempfile
        import sqlite3
        
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db:
            db_path = tmp_db.name
            
        loop = asyncio.new_event_loop()
        try:
            # 意図的に極めて長くスリープするタスクを実行
            async def slow_process_func(tid: str) -> str:
                await asyncio.sleep(10.0)  # 5秒の制限を超える
                return "completed"
                
            
            # タイムアウトを引き起こすために time.time() をモック
            time_values = [100.0, 100.0, 106.0]
            def mock_time():
                if time_values:
                    return time_values.pop(0)
                return 200.0
                
            with patch('time.time', side_effect=mock_time):
                task_status = loop.run_until_complete(
                    run_thumbnail_task_p27(
                        task_id="timeout_t1",
                        db_path=db_path,
                        output_path="dummy.png",
                        width=1280,
                        height=720,
                        text="Timeout Test",
                        max_retries=1,
                        process_func_override=slow_process_func
                    )
                )
                
            self.assertEqual(task_status, "FAILED")
            
            # DBのステータスを確認
            conn = sqlite3.connect(db_path)
            cursor = conn.execute("SELECT status, error FROM tasks WHERE id = 'timeout_t1'")
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "FAILED")
            self.assertIn("Task execution timed out", row[1])
            conn.close()
            
        finally:
            if 'loop' in locals():
                try:
                    loop.close()
                except Exception:
                    pass
            if os.path.exists(db_path):
                try:
                    os.unlink(db_path)
                except Exception:
                    pass

    def test_thumbnail_validation_file_not_found(self):
        # 存在しないパスを validate_thumbnail_p27 に渡したときに FileNotFoundError が発生することを確認
        with self.assertRaises(FileNotFoundError):
            validate_thumbnail_p27("non_existent_file_path_12345.png")

    def test_thumbnail_validation_handles_file_lock(self):
        # 画像検証後にファイルハンドルが正しく閉じられ、Windowsでも即座に削除（unlink）可能であることを検証するテスト
        temp_dir = Path("backend/temp_test_thumbnails_lock")
        temp_dir.mkdir(parents=True, exist_ok=True)
        out_path = temp_dir / "test_lock_verify.png"
        
        try:
            generate_thumbnail_p27(out_path, width=1280, height=720, text="Lock Test")
            self.assertTrue(out_path.exists())
            
            # 検証を実行
            result = validate_thumbnail_p27(out_path)
            self.assertEqual(result["width"], 1280)
            
            # Windowsでのロックリークがないか検証するため、即座に unlink を試みる
            # ハンドルがリークしていると、ここで PermissionError が発生する
            out_path.unlink()
            self.assertFalse(out_path.exists())
        finally:
            if out_path.exists():
                try:
                    out_path.unlink()
                except Exception:
                    pass
            if temp_dir.exists():
                try:
                    temp_dir.rmdir()
                except Exception:
                    pass

if __name__ == '__main__':
    unittest.main()
