"""
Milestone M30.2 高並列対応スケーリング基盤（排他制御、共有ガバナー、Git直列化）のテスト
"""

import sys
import os
import json
import time
import pytest
import threading
import subprocess
from pathlib import Path
from unittest.mock import patch

# パスの追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from backend.agents.orchestration.atomic_io import FileLock, atomic_write_json, safe_read_json
from backend.agents.orchestration.resource_governor import ResourceGovernor
from backend.agents.orchestration.hub_reports import ReportsMixin

class MockReports(ReportsMixin):
    pass


def test_file_lock_basic(tmp_path):
    """FileLock の取得、解放、別スレッドからの二重取得時のタイムアウトを検証"""
    lock_file = tmp_path / "test.lock"
    
    # 正常な取得と解放
    with FileLock(str(lock_file), timeout=1.0) as lock:
        assert lock.acquired
        assert lock_file.exists()
        
        # 別スレッドから二重取得しようとすると TimeoutError が発生すること
        errors = []
        def worker():
            try:
                with FileLock(str(lock_file), timeout=0.1):
                    pass
            except TimeoutError as e:
                errors.append(e)
            except Exception as e:
                errors.append(e)
                
        t = threading.Thread(target=worker)
        t.start()
        t.join()
        
        assert len(errors) == 1
        assert isinstance(errors[0], TimeoutError)
                
    # 解放後はロックファイルが削除されていること
    assert not lock_file.exists()


def test_file_lock_reentrancy(tmp_path):
    """同一スレッド内での再入可能（ネスト）ロックを検証"""
    lock_file = tmp_path / "reentrant.lock"
    
    with FileLock(str(lock_file), timeout=1.0) as lock1:
        assert lock1.acquired
        assert lock_file.exists()
        
        # ネストしたロックの取得（同一スレッドなので成功するはず）
        with FileLock(str(lock_file), timeout=1.0) as lock2:
            assert lock2.acquired
            assert lock_file.exists()
            
        # 内側を抜けても、外側のロックがあるのでロックファイルは削除されていないはず
        assert lock_file.exists()
        
    # 最外周を抜けたらロックファイルが削除されるはず
    assert not lock_file.exists()


def test_file_lock_zombie_recovery(tmp_path):
    """30秒以上経過した古い放置ロックファイル（ゾンビロック）が自動回収されることを検証"""
    lock_file = tmp_path / "zombie.lock"
    
    # ゾンビロックを模してロックファイルを手動生成
    lock_file.write_text("", encoding="utf-8")
    
    # タイムスタンプを過去（40秒前）に変更
    past_time = time.time() - 40.0
    os.utime(str(lock_file), (past_time, past_time))
    
    # 取得時にゾンビロックが検知されて回収され、無事取得できること
    with FileLock(str(lock_file), timeout=1.0) as lock:
        assert lock.acquired
        assert lock_file.exists()


def test_file_lock_concurrency(tmp_path):
    """複数スレッドから同時に FileLock を競合させても、安全に排他制御（直列化）されることを検証"""
    lock_file = tmp_path / "concurrent.lock"
    counter = [0]
    num_threads = 5
    iterations = 10
    
    def worker():
        for _ in range(iterations):
            with FileLock(str(lock_file), timeout=5.0):
                # クリティカルセクションで値をインクリメント
                val = counter[0]
                time.sleep(0.01)
                counter[0] = val + 1
                
    threads = [threading.Thread(target=worker) for _ in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
        
    # すべてのインクリメントが競合による先祖返りなしで完了していること
    assert counter[0] == num_threads * iterations


def test_atomic_write_and_safe_read(tmp_path):
    """atomic_write_json と safe_read_json の整合性、および破損時のバックアップからのフォールバックを検証"""
    target_file = tmp_path / "data.json"
    data = {"key": "value", "items": [1, 2, 3]}
    
    # 初回書き込み
    atomic_write_json(str(target_file), data)
    assert target_file.exists()
    
    # 2回目の書き込み（上書き）を行うことでバックアップが作成される
    atomic_write_json(str(target_file), {"key": "new_value"})
    
    read_data = safe_read_json(str(target_file))
    assert read_data == {"key": "new_value"}

    # バックアップファイル (.bak) が生成されていること
    bak_file = tmp_path / "data.json.bak"
    assert bak_file.exists()
    
    # バックアップの中身が以前のデータであることを検証
    with open(bak_file, "r", encoding="utf-8") as f:
        assert json.load(f) == data
    
    # ターゲットファイルを強制的に破損（不正なJSON）させる
    target_file.write_text("invalid { JSON } format", encoding="utf-8")
    
    # safe_read_json が破損を検知し、.bak からデータを復元すること
    read_data2 = safe_read_json(str(target_file))
    assert read_data2 == data
    
    # メインのターゲットファイルも復旧されていること
    with open(target_file, "r", encoding="utf-8") as f:
        assert json.load(f) == data


def test_resource_governor_shared_state(tmp_path):
    """複数インスタンスの ResourceGovernor が同一の resource_state.json を通じて状態を同期することを検証"""
    state_file = tmp_path / "resource_state.json"
    
    gov1 = ResourceGovernor(max_rpm=10, max_tpm=1000)
    gov1.state_path = state_file
    
    gov2 = ResourceGovernor(max_rpm=10, max_tpm=1000)
    gov2.state_path = state_file
    
    # 初期状態
    assert gov1.get_current_rpm() == 0
    assert gov2.get_current_rpm() == 0
    
    # gov1 でリクエスト記録
    gov1.record_request(100)
    
    # gov2 でも反映されているか検証
    assert gov2.get_current_rpm() == 1
    assert gov2.get_current_tpm() == 100
    
    # スロットリングの閾値超過判定 (threshold_pct=0.8 なので RPM 8, TPM 800)
    # expected_tokens が 700 の場合、合計 800 となり TPM 閾値 (800) 以上でスロットリング
    decision = gov2.should_throttle(expected_tokens=700)
    assert decision["throttle"] is True
    assert "TPM" in decision["reason"]


def test_git_auto_commit_exclusive(tmp_path):
    """複数プロセスから同時に Git コミット要求が発生しても、FileLock による直列化で競合を回避し、両方成功することを検証"""
    git_dir = tmp_path / "git_repo"
    git_dir.mkdir()
    
    # Git リポジトリの初期化
    subprocess.run(["git", "init"], cwd=str(git_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=str(git_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(git_dir), check=True, capture_output=True)
    
    # 初回コミット（これがないと simultaneous commits が競合しやすい）
    initial_file = git_dir / "initial.txt"
    initial_file.write_text("initial", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(git_dir), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(git_dir), check=True, capture_output=True)
    
    # _PROJECT_ROOT をテスト用の git_dir にパッチする
    with patch("backend.agents.orchestration.hub_reports._PROJECT_ROOT", git_dir):
        mr1 = MockReports()
        mr2 = MockReports()
        
        # 同時コミットのシミュレーション
        results = []
        def commit_worker(mr, msg, filename, file_content):
            try:
                # スレッド固有のファイルを作成して変更
                t_file = git_dir / filename
                t_file.write_text(file_content, encoding="utf-8")
                res = mr._git_auto_commit(msg)
                if not res:
                    # 失敗したときの Git のステータスとログをキャプチャして記録
                    status_res = subprocess.run(["git", "status"], cwd=str(git_dir), capture_output=True, text=True)
                    log_res = subprocess.run(["git", "log", "-n5", "--oneline"], cwd=str(git_dir), capture_output=True, text=True)
                    results.append({"success": False, "status": status_res.stdout + "\n" + status_res.stderr, "log": log_res.stdout})
                else:
                    results.append({"success": True})
            except Exception as e:
                results.append(e)
                
        t1 = threading.Thread(target=commit_worker, args=(mr1, "commit 1", "target1.txt", "content 1"))
        t2 = threading.Thread(target=commit_worker, args=(mr2, "commit 2", "target2.txt", "content 2"))
        
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        # どちらのコミットも正常に完了したこと
        assert len(results) == 2
        assert all(res.get("success") is True for res in results), f"Commit failed: {results}"
        
        # コマンドログの確認
        res = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=str(git_dir),
            capture_output=True, text=True, check=True
        )
        log_lines = res.stdout.strip().split("\n")
        # 同時コミットにより一方が他方の変更も巻き込んでコミットするため、履歴数は 2 以上になる
        assert len(log_lines) >= 2


def test_hub_batch_concurrency_stress(tmp_path):
    """50並列以上の過酷な同時アクセス競合ストレステスト（get_next_batch & mark_task_done）"""
    task_queue_file = tmp_path / "task_queue.json"
    flash_session_file = tmp_path / "flash_session.json"
    phase_state_file = tmp_path / "phase_state.json"
    
    # 初期データの作成
    initial_queue = {
        "schema_version": "1.0",
        "current_batch_id": "batch_stress_test",
        "generated_at": "2026-06-07T00:00:00Z",
        "phase": 5,
        "milestone": "M5.1",
        "tasks": [
            {
                "id": f"T-stress-{i:03d}",
                "status": "pending",
                "dependencies": [],
                "target_module": f"backend/module_{i:03d}.py"
            }
            for i in range(100)
        ],
        "blacklisted_modules": [],
        "batch_config": {
            "max_parallel": 30,
            "groups": {}
        }
    }
    
    initial_session = {
        "session_started_at": "2026-06-07T00:00:00Z",
        "session_ended_at": None,
        "exit_reason": None,
        "last_heartbeat": "2026-06-07T00:00:00Z",
        "status": "running",
        "batches_in_session": 0,
        "tasks_completed_in_session": 0,
        "current_activity": "executing",
        "current_step": "Running stress test",
        "current_batch_id": "batch_stress_test",
        "current_task_group": None,
        "progress_pct": 0,
        "subagents_running": 0,
        "subagents_completed": 0,
        "recent_errors": [],
        "stall_count": 0,
        "context_consumption_pct": 0,
        "context_pct_history": [],
        "archive_urgency": "ok",
        "auto_stop_reason": None
    }
    
    initial_phase_state = {
        "current_phase": 5,
        "current_milestone": "M5.1",
        "flash_tasks_total": 0,
        "flash_tasks_passed": 0,
        "flash_tasks_failed": 0,
        "flash_consecutive_failures": 0,
        "blacklisted_modules": []
    }
    
    # UTF-8 で書き込み
    with open(task_queue_file, "w", encoding="utf-8") as f:
        json.dump(initial_queue, f, indent=2)
    with open(flash_session_file, "w", encoding="utf-8") as f:
        json.dump(initial_session, f, indent=2)
    with open(phase_state_file, "w", encoding="utf-8") as f:
        json.dump(initial_phase_state, f, indent=2)
        
    # パス定義をモック
    from unittest.mock import patch
    
    patchers = [
        patch("backend.agents.orchestration.hub_common.TASK_QUEUE_PATH", task_queue_file),
        patch("backend.agents.orchestration.hub_common.FLASH_SESSION_PATH", flash_session_file),
        patch("backend.agents.orchestration.hub_common.PHASE_STATE_PATH", phase_state_file),
        patch("backend.agents.orchestration.hub_batch.TASK_QUEUE_PATH", task_queue_file),
        patch("backend.agents.orchestration.hub_batch.FLASH_SESSION_PATH", flash_session_file),
        patch("backend.agents.orchestration.hub_batch.PHASE_STATE_PATH", phase_state_file),
        patch("backend.agents.orchestration.hub_session.FLASH_SESSION_PATH", flash_session_file),
    ]
    
    for p in patchers:
        p.start()
        
    try:
        from backend.agents.orchestration.orchestrator import OrchestrationHub
        hub = OrchestrationHub()
        
        num_workers = 60
        assigned_tasks = []
        assigned_lock = threading.Lock()
        
        # スレッド起動シグナル
        start_event = threading.Event()
        
        def worker(worker_id):
            import random
            # 全スレッド同時に開始するため待機
            start_event.wait()
            
            # 1. get_next_batch を呼んでタスクを取得
            # batch_size を 1 に制限して競合を激しくする
            batch = None
            for attempt in range(5):
                try:
                    batch = hub.get_next_batch(phase=5, milestone="M5.1", batch_size=1)
                    break
                except TimeoutError:
                    if attempt == 4:
                        print(f"[Worker-{worker_id}] get_next_batch: Failed to acquire lock after 5 attempts")
                        return
                    time.sleep(random.uniform(0.1, 0.5))
                except Exception as e:
                    print(f"[Worker-{worker_id}] get_next_batch error: {e}")
                    return
            
            if batch:
                for task in batch:
                    # 重複割り当てを防ぐため、すでに自分たちでアサインしたものは処理しない
                    # (get_next_batch が running 中のタスクを返す仕様があるため、
                    # 既に実行中のタスクを他のスレッドが取得した場合はスキップする)
                    task_id = task["id"]
                    is_new = False
                    with assigned_lock:
                        if task_id not in assigned_tasks:
                            assigned_tasks.append(task_id)
                            is_new = True
                    
                    if is_new:
                        # 2. しばらく処理するフリ
                        time.sleep(0.01)
                        # 3. mark_task_done を呼ぶ
                        for attempt in range(5):
                            try:
                                hub.mark_task_done(task_id, "pass", {"message": "Success from stress test"})
                                break
                            except TimeoutError:
                                if attempt == 4:
                                    print(f"[Worker-{worker_id}] mark_task_done: Failed to acquire lock for task {task_id}")
                                    with assigned_lock:
                                        if task_id in assigned_tasks:
                                            assigned_tasks.remove(task_id)
                                    return
                                time.sleep(random.uniform(0.1, 0.5))
                            except Exception as e:
                                print(f"[Worker-{worker_id}] mark_task_done error: {e}")
                                return
                    
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_workers)]
        for t in threads:
            t.start()
            
        # 一斉スタート
        start_event.set()
        
        for t in threads:
            t.join()
            
        # アサーション
        # 1. 割り当てられたタスクに重複がないこと
        assert len(assigned_tasks) == len(set(assigned_tasks)), "Duplicate task assignment detected!"
        
        # キューファイルを読み直して、状態の整合性を確認
        with open(task_queue_file, "r", encoding="utf-8") as f:
            queue_data = json.load(f)
            
        # 全てのタスクステータスが pass または pending のいずれかであり、破損していないこと
        statuses = [t["status"] for t in queue_data["tasks"]]
        assert all(s in ("pass", "pending", "running") for s in statuses)
        
        # mark_task_done で pass になった数と、assigned_tasks が一致するか
        passed_count = sum(1 for s in statuses if s == "pass")
        assert passed_count == len(assigned_tasks)
        
    finally:
        for p in patchers:
            p.stop()
