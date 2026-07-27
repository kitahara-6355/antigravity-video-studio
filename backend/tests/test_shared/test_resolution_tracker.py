import os
import json
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from agents.resolution_tracker import Resolution, ResolutionStatus, ResolutionTracker

@pytest.fixture
def temp_archive_dir():
    """テスト用の一時ディレクトリを作成・削除するフィクスチャ"""
    temp_dir = tempfile.mkdtemp(prefix="test_resolutions_")
    yield temp_dir
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)

def test_resolution_init_and_to_dict():
    """Resolution クラスの初期化と dict 変換のテスト"""
    proposed_changes = {"key": "value"}
    res = Resolution(
        resolution_id="test-id-123",
        title="テスト議案",
        description="これはテストです",
        proposed_changes=proposed_changes,
        session_id="session-456"
    )
    
    assert res.id == "test-id-123"
    assert res.title == "テスト議案"
    assert "テストです" in res.description
    assert res.proposed_changes == proposed_changes
    assert res.session_id == "session-456"
    assert res.status == ResolutionStatus.DRAFT
    assert res.votes == {}
    assert res.gavel_decision is None
    assert isinstance(res.created_at, float)
    assert isinstance(res.updated_at, float)

    d = res.to_dict()
    assert d["id"] == "test-id-123"
    assert d["title"] == "テスト議案"
    assert d["description"] == "これはテストです"
    assert d["proposed_changes"] == proposed_changes
    assert d["session_id"] == "session-456"
    assert d["status"] == "draft"
    assert d["votes"] == {}
    assert d["gavel_decision"] is None
    assert d["progress"] == 0.2

def test_resolution_progress():
    """_calculate_progress メソッドの各ステータス値のテスト"""
    res = Resolution("id", "t", "d", {}, "s")
    
    res.status = ResolutionStatus.DRAFT
    assert res._calculate_progress() == 0.2
    
    res.status = ResolutionStatus.DEBATE
    assert res._calculate_progress() == 0.5
    
    res.status = ResolutionStatus.VOTING
    assert res._calculate_progress() == 0.8
    
    res.status = ResolutionStatus.APPROVED
    assert res._calculate_progress() == 1.0
    
    res.status = ResolutionStatus.REJECTED
    assert res._calculate_progress() == 1.0
    
    res.status = "invalid_status"
    assert res._calculate_progress() == 0.0

def test_tracker_creation_and_dir_init(temp_archive_dir):
    """ResolutionTracker 初期化時のアーカイブディレクトリ作成検証"""
    sub_dir = os.path.join(temp_archive_dir, "new_sub_dir")
    assert not os.path.exists(sub_dir)
    
    tracker = ResolutionTracker(archive_dir=sub_dir)
    assert os.path.exists(sub_dir)
    assert tracker.active_resolutions == {}

def test_create_resolution(temp_archive_dir):
    """create_resolution のテストと保存ファイルの存在検証"""
    tracker = ResolutionTracker(archive_dir=temp_archive_dir)
    
    res = tracker.create_resolution(
        title="新規議案",
        description="詳細説明",
        proposed_changes={"theme": "dark"},
        session_id="session-abc"
    )
    
    assert res.id in tracker.active_resolutions
    assert tracker.get_resolution(res.id) == res
    
    # ファイルが保存されているか検証
    filename = f"resolution_{res.id}.json"
    filepath = os.path.join(temp_archive_dir, filename)
    assert os.path.exists(filepath)
    
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["id"] == res.id
        assert data["title"] == "新規議案"

def test_update_status(temp_archive_dir):
    """update_status によるステータス更新と保存の検証"""
    tracker = ResolutionTracker(archive_dir=temp_archive_dir)
    res = tracker.create_resolution("議案", "説明", {}, "session")
    
    time.sleep(0.01)  # updated_at の変化を保証するため
    old_updated = res.updated_at
    
    tracker.update_status(res.id, ResolutionStatus.DEBATE)
    
    assert res.status == ResolutionStatus.DEBATE
    assert res.updated_at > old_updated
    
    # 保存ファイルでも更新されているか
    filepath = os.path.join(temp_archive_dir, f"resolution_{res.id}.json")
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["status"] == "debate"

def test_record_vote(temp_archive_dir):
    """record_vote による投票記録と保存の検証"""
    tracker = ResolutionTracker(archive_dir=temp_archive_dir)
    res = tracker.create_resolution("議案", "説明", {}, "session")
    
    tracker.record_vote(res.id, "Agent1", "APPROVE")
    assert res.votes["Agent1"] == "APPROVE"
    
    filepath = os.path.join(temp_archive_dir, f"resolution_{res.id}.json")
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["votes"]["Agent1"] == "APPROVE"

def test_apply_gavel(temp_archive_dir):
    """apply_gavel (議長決済) のテスト (APPROVE / REJECT)"""
    tracker = ResolutionTracker(archive_dir=temp_archive_dir)
    
    # 存在しないIDに対する gavel
    assert not tracker.apply_gavel("non-existent-id", "APPROVE")
    
    # 可決 (APPROVE) の場合
    res_approve = tracker.create_resolution("可決議案", "説明", {}, "session")
    success = tracker.apply_gavel(res_approve.id, "APPROVE")
    assert success
    assert res_approve.status == ResolutionStatus.APPROVED
    assert res_approve.gavel_decision == "APPROVE"
    
    # 否決 (REJECT) の場合
    res_reject = tracker.create_resolution("否決議案", "説明", {}, "session")
    success = tracker.apply_gavel(res_reject.id, "REJECT")
    assert success
    assert res_reject.status == ResolutionStatus.REJECTED
    assert res_reject.gavel_decision == "REJECT"

def test_list_resolutions(temp_archive_dir):
    """list_resolutions のソートおよびフィルタの検証"""
    tracker = ResolutionTracker(archive_dir=temp_archive_dir)
    
    # 複数議案を作成
    res1 = tracker.create_resolution("議案1", "説明1", {}, "session")
    time.sleep(0.02)
    res2 = tracker.create_resolution("議案2", "説明2", {}, "session")
    time.sleep(0.02)
    res3 = tracker.create_resolution("議案3", "説明3", {}, "session")
    
    # ステータスを変更して分類
    tracker.update_status(res1.id, ResolutionStatus.DEBATE)
    tracker.update_status(res2.id, ResolutionStatus.VOTING)
    
    # 全件取得（更新日時の降順ソート）
    # 直前に更新された res2 が先頭、次が res1、最後が res3 になる
    all_res = tracker.list_resolutions()
    assert len(all_res) == 3
    assert all_res[0]["id"] == res2.id
    assert all_res[1]["id"] == res1.id
    assert all_res[2]["id"] == res3.id
    
    # ステータスフィルタ
    debate_res = tracker.list_resolutions(status=ResolutionStatus.DEBATE)
    assert len(debate_res) == 1
    assert debate_res[0]["id"] == res1.id

@patch("agents.resolution_tracker.SafeJsonStore.save")
@patch("agents.resolution_tracker.logger")
def test_save_resolution_exception(mock_logger, mock_save, temp_archive_dir):
    """_save_resolution メソッドでの OSError 発生時のロギング検証"""
    mock_save.side_effect = OSError("Disk full")
    
    tracker = ResolutionTracker(archive_dir=temp_archive_dir)
    res = Resolution("test-ex-id", "title", "desc", {}, "session")
    
    # 内部で例外が発生するがキャッチされてロギングされるはず
    tracker._save_resolution(res)
    
    mock_logger.error.assert_called_once()
    log_args = mock_logger.error.call_args[0][0]
    assert "Failed to save resolution" in log_args
    assert "test-ex-id" in log_args

def test_tracker_missing_resolution(temp_archive_dir):
    """存在しないIDに対する操作時の挙動確認"""
    tracker = ResolutionTracker(archive_dir=temp_archive_dir)
    missing_id = "non-existent-id-xyz"
    
    # get_resolution は None を返すこと
    assert tracker.get_resolution(missing_id) is None
    
    # update_status は例外をスローせず安全に無視されること
    try:
        tracker.update_status(missing_id, ResolutionStatus.DEBATE)
    except Exception as e:
        pytest.fail(f"update_status raised an exception on missing ID: {e}")
        
    # record_vote は例外をスローせず安全に無視されること
    try:
        tracker.record_vote(missing_id, "AgentXYZ", "APPROVE")
    except Exception as e:
        pytest.fail(f"record_vote raised an exception on missing ID: {e}")

def test_tracker_get_existing_resolution(temp_archive_dir):
    """存在するIDに対する get_resolution の確認"""
    tracker = ResolutionTracker(archive_dir=temp_archive_dir)
    res = tracker.create_resolution("テスト議案", "説明", {}, "session")
    
    retrieved = tracker.get_resolution(res.id)
    assert retrieved is not None
    assert retrieved.id == res.id
    assert retrieved.title == "テスト議案"
