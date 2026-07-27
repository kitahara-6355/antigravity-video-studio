import os
import sys
import shutil
import time
import pytest
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.agents.orchestration.cleanup_disk import main

def test_cleanup_disk_success(tmp_path):
    # テスト用の brain_dir を作成
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()

    # テスト用フォルダ
    old_folder = brain_dir / "old-session-id"
    old_folder.mkdir()
    
    # ダミーファイルを作成
    dummy_file = old_folder / "dummy.txt"
    dummy_file.write_text("dummy content")

    # 更新時刻を2日前に設定
    now = time.time()
    two_days_ago = now - (2 * 24 * 60 * 60)
    os.utime(old_folder, (two_days_ago, two_days_ago))
    os.utime(dummy_file, (two_days_ago, two_days_ago))

    # クリーンアップ実行
    # プロダクションコードが main(brain_dir=...) に対応している前提で呼び出す
    # (現時点では未対応なので、引数を渡すと失敗するか、動作が異なるはず)
    main(brain_dir=str(brain_dir), active_ids=set(), keep_days=1)

    # 検証: 古いフォルダが削除されていること
    assert not old_folder.exists()

def test_cleanup_disk_skip_active(tmp_path):
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()

    # アクティブなフォルダ
    active_folder = brain_dir / "active-session-id"
    active_folder.mkdir()
    
    dummy_file = active_folder / "dummy.txt"
    dummy_file.write_text("dummy content")

    # 更新時刻を2日前に設定 (アクティブなので残るべき)
    two_days_ago = time.time() - (2 * 24 * 60 * 60)
    os.utime(active_folder, (two_days_ago, two_days_ago))

    main(brain_dir=str(brain_dir), active_ids={"active-session-id"}, keep_days=1)

    # 検証: アクティブフォルダが残っていること
    assert active_folder.exists()

def test_cleanup_disk_skip_recent(tmp_path):
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()

    # 最近更新されたフォルダ
    recent_folder = brain_dir / "recent-session-id"
    recent_folder.mkdir()
    
    # クリーンアップ実行
    main(brain_dir=str(brain_dir), active_ids=set(), keep_days=1)

    # 検証: 最近のフォルダが残っていること
    assert recent_folder.exists()

def test_cleanup_disk_mtime_error(tmp_path):
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()

    error_folder = brain_dir / "error-session-id"
    error_folder.mkdir()

    # os.path.getmtime が OSError を投げるようにモックする
    with patch("os.path.getmtime", side_effect=OSError("Permission denied")):
        main(brain_dir=str(brain_dir), active_ids=set(), keep_days=1)

    # 検証: 安全のため、mtime 取得失敗時は削除されずに残ること
    assert error_folder.exists()

def test_cleanup_disk_dynamic_active_id(tmp_path):
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()

    # 現在のセッションIDを模擬
    current_session = "current-session-id"
    current_folder = brain_dir / current_session
    current_folder.mkdir()
    
    two_days_ago = time.time() - (2 * 24 * 60 * 60)
    os.utime(current_folder, (two_days_ago, two_days_ago))

    # 環境変数に会話IDを設定
    with patch.dict(os.environ, {"CONVERSATION_ID": current_session}):
        main(brain_dir=str(brain_dir), active_ids=set(), keep_days=1)

    # 検証: 環境変数から取得したセッションIDが保護されていること
    assert current_folder.exists()


def test_cleanup_disk_onexc_compatibility(tmp_path):
    # shutil.rmtree has been patched to verify onexc/onerror usage depending on python version
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()
    
    old_folder = brain_dir / "old-session"
    old_folder.mkdir()
    
    # 2 days ago
    two_days_ago = time.time() - (2 * 24 * 60 * 60)
    os.utime(old_folder, (two_days_ago, two_days_ago))
    
    import sys
    from unittest.mock import patch
    with patch("shutil.rmtree") as mock_rmtree:
        main(brain_dir=str(brain_dir), active_ids=set(), keep_days=1)
        mock_rmtree.assert_called_once()
        _, kwargs = mock_rmtree.call_args
        if sys.version_info >= (3, 12):
            assert "onexc" in kwargs
            assert kwargs["onexc"].__name__ == "_handle_remove_readonly"
        else:
            assert "onerror" in kwargs
            assert kwargs["onerror"].__name__ == "_handle_remove_readonly"

def test_cleanup_disk_merge_default_active_ids(tmp_path):
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()

    # 1. default_active_ids に含まれるIDのフォルダ
    default_id = "73fb2ff8-094c-4b1a-ae5d-ce40a3bd0e6e"
    default_folder = brain_dir / default_id
    default_folder.mkdir()

    # 2. 明示的に指定するアクティブID
    explicit_id = "explicit-active-id"
    explicit_folder = brain_dir / explicit_id
    explicit_folder.mkdir()

    # 3. 古い、保護対象外のフォルダ
    old_folder = brain_dir / "old-session-id"
    old_folder.mkdir()

    # 時刻設定 (2日前)
    two_days_ago = time.time() - (2 * 24 * 60 * 60)
    os.utime(default_folder, (two_days_ago, two_days_ago))
    os.utime(explicit_folder, (two_days_ago, two_days_ago))
    os.utime(old_folder, (two_days_ago, two_days_ago))

    # クリーンアップ実行 (explicit_id のみを active_ids に渡す)
    main(brain_dir=str(brain_dir), active_ids={explicit_id}, keep_days=1)

    # 検証
    # 明示指定したIDとデフォルトIDの両方が保護されていること
    assert explicit_folder.exists()
    assert default_folder.exists()
    # 対象外は削除されていること
    assert not old_folder.exists()


def test_cleanup_disk_dynamic_path_protection(tmp_path):
    brain_dir = tmp_path / "brain"
    brain_dir.mkdir()

    # 実行ファイルパスやカレントディレクトリから抽出されるセッションIDを模擬
    dynamic_id = "dynamic-mock-session-12345"
    dynamic_folder = brain_dir / dynamic_id
    dynamic_folder.mkdir()

    # 2日前の時刻を設定
    two_days_ago = time.time() - (2 * 24 * 60 * 60)
    os.utime(dynamic_folder, (two_days_ago, two_days_ago))

    # os.path.abspath をモックして、パス内に dynamic_id が含まれるようにする
    fake_filepath = f"C:\\Users\\PC_User\\.gemini\\antigravity\\brain\\{dynamic_id}\\backend\\agents\\orchestration\\cleanup_disk.py"
    
    with patch("os.path.abspath", return_value=fake_filepath):
        main(brain_dir=str(brain_dir), active_ids=set(), keep_days=1)

    # 検証: 動的に抽出されたIDフォルダが保護されていること
    assert dynamic_folder.exists()
