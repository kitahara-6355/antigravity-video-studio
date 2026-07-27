import os
import time
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from backend.cleanup_manager import CleanupManager, CleanupRule

@pytest.fixture
def temp_cleanup_manager(tmp_path):
    """テスト用の一時的な CleanupManager インスタンスを作成する fixture"""
    manager = CleanupManager()
    # テスト用にルールの一時ディレクトリを tmp_path の配下に変更する
    for key, rule in manager.rules.items():
        rule.directory = tmp_path / key
    return manager

def test_initial_rules():
    manager = CleanupManager()
    assert "screenshots" in manager.rules
    assert "raw" in manager.rules
    assert manager.rules["raw"].protected is True
    assert manager.rules["screenshots"].protected is False

def test_ensure_directories_exist(temp_cleanup_manager):
    manager = temp_cleanup_manager
    # 初期状態ではディレクトリは存在しない
    for rule in manager.rules.values():
        assert not rule.directory.exists()
    
    # 呼び出し後に作成されること
    manager._ensure_directories_exist()
    for rule in manager.rules.values():
        assert rule.directory.exists()

def test_ensure_directories_exist_error(temp_cleanup_manager):
    manager = temp_cleanup_manager
    # 不正なディレクトリ型を設定してエラーハンドリングを確認
    manager.rules["screenshots"].directory = None
    
    # 例外がスローされずに警告ログが出ることを検証
    manager._ensure_directories_exist()
    # screenshots 以外は正常に作成されるはず
    assert manager.rules["raw"].directory.exists()

def test_is_protected(temp_cleanup_manager):
    manager = temp_cleanup_manager
    manager._ensure_directories_exist()
    
    # 保護対象のディレクトリ内のファイル
    raw_file = manager.rules["raw"].directory / "source_video.mp4"
    raw_file.touch()
    assert manager.is_protected(str(raw_file)) is True

    # 保護対象ではないディレクトリ内のファイル
    scr_file = manager.rules["screenshots"].directory / "preview.png"
    scr_file.touch()
    assert manager.is_protected(str(scr_file)) is False

    # 無効な入力の検証
    assert manager.is_protected(None) is False
    assert manager.is_protected(123) is False

def test_cleanup_dry_run(temp_cleanup_manager):
    manager = temp_cleanup_manager
    manager._ensure_directories_exist()
    
    # screenshots カテゴリにファイル作成
    scr_dir = manager.rules["screenshots"].directory
    f1 = scr_dir / "test1.png"
    f1.touch()
    
    # retention_daysを極端に短くして削除対象にする
    manager.rules["screenshots"].retention_days = 0
    time.sleep(0.1) # mtime の時間差を作るため
    
    # dry_run = True でクリーンアップ
    res = manager.cleanup(category="screenshots", dry_run=True)
    assert str(f1) in res["deleted"]
    assert f1.exists() # 削除されていないこと

def test_cleanup_execution(temp_cleanup_manager):
    manager = temp_cleanup_manager
    manager._ensure_directories_exist()
    
    scr_dir = manager.rules["screenshots"].directory
    f1 = scr_dir / "test1.png"
    f1.touch()
    
    manager.rules["screenshots"].retention_days = 0
    
    # 実際のクリーンアップ実行
    res = manager.cleanup(category="screenshots", dry_run=False)
    assert str(f1) in res["deleted"]
    assert not f1.exists() # 削除されていること

def test_cleanup_max_count(temp_cleanup_manager):
    manager = temp_cleanup_manager
    manager._ensure_directories_exist()
    
    scr_dir = manager.rules["screenshots"].directory
    # max_count を 2 に設定
    manager.rules["screenshots"].max_count = 2
    manager.rules["screenshots"].retention_days = None # 保持期限は無制限
    
    # 3つファイルを作成 (時間をずらす)
    f1 = scr_dir / "test1.png"
    f1.touch()
    os.utime(f1, (time.time() - 100, time.time() - 100))
    
    f2 = scr_dir / "test2.png"
    f2.touch()
    os.utime(f2, (time.time() - 50, time.time() - 50))
    
    f3 = scr_dir / "test3.png"
    f3.touch()
    
    res = manager.cleanup(category="screenshots")
    # 最も古い f1 が削除されるはず
    assert str(f1) in res["deleted"]
    assert str(f2) not in res["deleted"]
    assert str(f3) not in res["deleted"]
    assert not f1.exists()
    assert f2.exists()
    assert f3.exists()

def test_get_storage_stats(temp_cleanup_manager):
    manager = temp_cleanup_manager
    manager._ensure_directories_exist()
    
    scr_dir = manager.rules["screenshots"].directory
    f1 = scr_dir / "test1.png"
    f1.write_bytes(b"a" * 1024 * 1024 * 2) # 2 MB
    
    stats = manager.get_storage_stats()
    assert stats["total_size_mb"] > 0
    assert stats["categories"]["screenshots"]["count"] == 1

def test_report_to_evolution_log(temp_cleanup_manager, tmp_path):
    manager = temp_cleanup_manager
    evo_log_path = tmp_path / "evolution_log.json"
    
    cleanup_result = {
        "deleted": ["file1.mp4"],
        "protected": [],
        "freed_bytes": 1024 * 1024,
        "dry_run": False
    }
    
    # evolution_log が存在しない状態から自動作成して追記されること
    manager.report_to_evolution_log(cleanup_result, evolution_log_path=evo_log_path)
    
    assert evo_log_path.exists()
    with open(evo_log_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data["entries"]) == 1
    assert data["entries"][0]["deleted_count"] == 1
    assert data["entries"][0]["freed_mb"] == 1.0

def test_auto_cleanup(temp_cleanup_manager, tmp_path):
    manager = temp_cleanup_manager
    # モックを使用して外部サービスのインポート/呼び出しを追跡
    with patch("services.evolution_trigger_service.EvolutionTriggerService") as mock_trigger_service, \
         patch("services.philosophy_proposal_service.PhilosophyProposalService") as mock_proposal_service:
        
        # モックのセットアップ
        mock_trigger_inst = MagicMock()
        mock_trigger_service.return_value = mock_trigger_inst
        mock_trigger_inst._load_evolution_log.return_value = {"entries": []}
        
        mock_proposal_inst = MagicMock()
        mock_proposal_service.return_value = mock_proposal_inst
        
        # 実行
        manager.auto_cleanup()
        
        # 呼び出し検証
        mock_trigger_inst._load_evolution_log.assert_called_once()
        mock_trigger_inst._trim_trust_history.assert_called_once()
        mock_trigger_inst._save_evolution_log.assert_called_once()
        mock_proposal_inst._trim_pending_proposals.assert_called_once()
