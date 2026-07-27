import sys
import os
import time
import pytest
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from agents.resolution_tracker import ResolutionTracker, Resolution, ResolutionStatus, resolution_tracker

def test_resolution_status_values():
    assert ResolutionStatus.DRAFT == "draft"
    assert ResolutionStatus.DEBATE == "debate"
    assert ResolutionStatus.VOTING == "voting"
    assert ResolutionStatus.APPROVED == "approved"
    assert ResolutionStatus.REJECTED == "rejected"

def test_resolution_init():
    res_id = "test-123"
    title = "Test Title"
    description = "Test Desc"
    changes = {"key": "val"}
    session_id = "session-999"
    
    res = Resolution(res_id, title, description, changes, session_id)
    assert res.id == res_id
    assert res.title == title
    assert res.description == description
    assert res.proposed_changes == changes
    assert res.session_id == session_id
    assert res.status == ResolutionStatus.DRAFT
    assert res.votes == {}
    assert res.gavel_decision is None
    assert isinstance(res.created_at, float)
    assert isinstance(res.updated_at, float)

def test_resolution_to_dict_and_progress():
    res = Resolution("id", "title", "desc", {}, "sess")
    
    # DRAFT progress
    res.status = ResolutionStatus.DRAFT
    d = res.to_dict()
    assert d["progress"] == 0.2
    
    # DEBATE progress
    res.status = ResolutionStatus.DEBATE
    assert res.to_dict()["progress"] == 0.5
    
    # VOTING progress
    res.status = ResolutionStatus.VOTING
    assert res.to_dict()["progress"] == 0.8
    
    # APPROVED progress
    res.status = ResolutionStatus.APPROVED
    assert res.to_dict()["progress"] == 1.0
    
    # REJECTED progress
    res.status = ResolutionStatus.REJECTED
    assert res.to_dict()["progress"] == 1.0
    
    # Unknown status progress (fallback)
    res.status = "unknown_status"
    assert res.to_dict()["progress"] == 0.0

def test_tracker_init_directory_creation(tmp_path):
    archive_dir = tmp_path / "test_resolutions_dir"
    assert not archive_dir.exists()
    
    tracker = ResolutionTracker(archive_dir=str(archive_dir))
    assert archive_dir.exists()
    assert tracker.active_resolutions == {}

def test_tracker_create_resolution(tmp_path):
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    
    res = tracker.create_resolution(
        title="Test Res",
        description="Testing creation",
        proposed_changes={"param": 1},
        session_id="session-1"
    )
    
    assert res.id in tracker.active_resolutions
    assert tracker.get_resolution(res.id) == res
    
    # Check if saved to disk
    file_path = tmp_path / f"resolution_{res.id}.json"
    assert file_path.exists()
    
    with open(file_path, "r", encoding="utf-8") as f:
        import json
        saved_data = json.load(f)
    assert saved_data["id"] == res.id
    assert saved_data["title"] == "Test Res"

def test_tracker_update_status(tmp_path):
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    res = tracker.create_resolution("T", "D", {}, "S")
    
    assert res.status == ResolutionStatus.DRAFT
    
    # Update status to DEBATE
    tracker.update_status(res.id, ResolutionStatus.DEBATE)
    assert res.status == ResolutionStatus.DEBATE
    
    # Verify file is updated
    file_path = tmp_path / f"resolution_{res.id}.json"
    with open(file_path, "r", encoding="utf-8") as f:
        import json
        saved_data = json.load(f)
    assert saved_data["status"] == "debate"
    
    # Try updating non-existent id (should not raise exception, just no-op)
    tracker.update_status("non-existent-id", ResolutionStatus.APPROVED)

def test_tracker_record_vote(tmp_path):
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    res = tracker.create_resolution("T", "D", {}, "S")
    
    tracker.record_vote(res.id, "agent_1", "APPROVE")
    assert res.votes["agent_1"] == "APPROVE"
    
    # Verify file is updated
    file_path = tmp_path / f"resolution_{res.id}.json"
    with open(file_path, "r", encoding="utf-8") as f:
        import json
        saved_data = json.load(f)
    assert saved_data["votes"]["agent_1"] == "APPROVE"
    
    # Try voting on non-existent id (should be no-op)
    tracker.record_vote("non-existent-id", "agent_1", "APPROVE")

def test_tracker_apply_gavel(tmp_path):
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    res = tracker.create_resolution("T", "D", {}, "S")
    
    # Test Approve decision
    success = tracker.apply_gavel(res.id, "APPROVE")
    assert success is True
    assert res.gavel_decision == "APPROVE"
    assert res.status == ResolutionStatus.APPROVED
    
    # Verify file is updated
    file_path = tmp_path / f"resolution_{res.id}.json"
    with open(file_path, "r", encoding="utf-8") as f:
        import json
        saved_data = json.load(f)
    assert saved_data["gavel_decision"] == "APPROVE"
    assert saved_data["status"] == "approved"
    
    # Test Reject decision
    res2 = tracker.create_resolution("T2", "D2", {}, "S2")
    success2 = tracker.apply_gavel(res2.id, "REJECT")
    assert success2 is True
    assert res2.gavel_decision == "REJECT"
    assert res2.status == ResolutionStatus.REJECTED
    
    # Test other decision strings (should also default to REJECTED based on code structure)
    res3 = tracker.create_resolution("T3", "D3", {}, "S3")
    success3 = tracker.apply_gavel(res3.id, "SOME_OTHER_DECISION")
    assert success3 is True
    assert res3.gavel_decision == "SOME_OTHER_DECISION"
    assert res3.status == ResolutionStatus.REJECTED
    
    # Test non-existent id (should return False)
    success_none = tracker.apply_gavel("non-existent-id", "APPROVE")
    assert success_none is False

def test_tracker_get_resolution(tmp_path):
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    res = tracker.create_resolution("T", "D", {}, "S")
    
    assert tracker.get_resolution(res.id) == res
    assert tracker.get_resolution("invalid-id") is None

def test_tracker_list_resolutions(tmp_path):
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    
    # Create resolutions at different times to test sorting
    with patch("time.time") as mock_time:
        mock_time.return_value = 1000.0
        res1 = tracker.create_resolution("T1", "D1", {}, "S1")
        
        mock_time.return_value = 2000.0
        res2 = tracker.create_resolution("T2", "D2", {}, "S2")
        
        mock_time.return_value = 1500.0
        res3 = tracker.create_resolution("T3", "D3", {}, "S3")
        
    # Default order should be descending by updated_at: res2 (2000.0) -> res3 (1500.0) -> res1 (1000.0)
    all_res = tracker.list_resolutions()
    assert len(all_res) == 3
    assert all_res[0]["id"] == res2.id
    assert all_res[1]["id"] == res3.id
    assert all_res[2]["id"] == res1.id
    
    # Test status filter
    tracker.update_status(res3.id, ResolutionStatus.DEBATE)
    tracker.update_status(res2.id, ResolutionStatus.APPROVED)
    
    debate_res = tracker.list_resolutions(status=ResolutionStatus.DEBATE)
    assert len(debate_res) == 1
    assert debate_res[0]["id"] == res3.id
    
    approved_res = tracker.list_resolutions(status=ResolutionStatus.APPROVED)
    assert len(approved_res) == 1
    assert approved_res[0]["id"] == res2.id

def test_tracker_save_resolution_oserror(tmp_path):
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    res = Resolution("id-error", "T", "D", {}, "S")
    
    # Mock SafeJsonStore.save to raise OSError
    with patch("safe_io.SafeJsonStore.save", side_effect=OSError("Disk Full")):
        with patch("agents.resolution_tracker.logger.error") as mock_log_err:
            tracker._save_resolution(res)
            # The exception should be caught and logged
            mock_log_err.assert_called_once_with("Failed to save resolution id-error: Disk Full")

def test_default_singleton():
    assert isinstance(resolution_tracker, ResolutionTracker)
    assert resolution_tracker.archive_dir == "archives/resolutions"

def test_tracker_apply_gavel_invalid_decision(tmp_path):
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    res = tracker.create_resolution("T", "D", {}, "S")
    
    # Test invalid decision (should default to REJECTED)
    success = tracker.apply_gavel(res.id, "ABSTAIN")
    assert success is True
    assert res.gavel_decision == "ABSTAIN"
    assert res.status == ResolutionStatus.REJECTED
    
    # Test None decision (should also default to REJECTED)
    res2 = tracker.create_resolution("T2", "D2", {}, "S2")
    success2 = tracker.apply_gavel(res2.id, None)
    assert success2 is True
    assert res2.gavel_decision is None
    assert res2.status == ResolutionStatus.REJECTED

def test_tracker_record_vote_overwrite(tmp_path):
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    res = tracker.create_resolution("T", "D", {}, "S")
    
    # First vote
    tracker.record_vote(res.id, "agent_1", "APPROVE")
    assert res.votes["agent_1"] == "APPROVE"
    
    # Overwrite vote
    tracker.record_vote(res.id, "agent_1", "REJECT")
    assert res.votes["agent_1"] == "REJECT"
    
    # Verify file has the updated vote
    file_path = tmp_path / f"resolution_{res.id}.json"
    with open(file_path, "r", encoding="utf-8") as f:
        import json
        saved_data = json.load(f)
    assert saved_data["votes"]["agent_1"] == "REJECT"

def test_tracker_list_resolutions_same_timestamp(tmp_path):
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    
    with patch("time.time") as mock_time:
        mock_time.return_value = 1000.0
        res1 = tracker.create_resolution("T1", "D1", {}, "S1")
        res2 = tracker.create_resolution("T2", "D2", {}, "S2")
        
    all_res = tracker.list_resolutions()
    assert len(all_res) == 2
    # Ensure both are present
    ids = {r["id"] for r in all_res}
    assert ids == {res1.id, res2.id}

def test_tracker_save_resolution_typeerror(tmp_path):
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    # proposed_changes contains a set, which is not JSON serializable
    res = Resolution("id-type-error", "T", "D", {"unserializable": {1, 2, 3}}, "S")
    
    with pytest.raises(TypeError):
        tracker._save_resolution(res)

def test_resolution_progress_invalid_types():
    """_calculate_progress に None や数値などの非文字列、あるいは未定義のステータスが設定された場合に 0.0 が返ることを検証。"""
    res = Resolution("id-invalid-status", "T", "D", {}, "S")
    
    # None の場合
    res.status = None
    assert res._calculate_progress() == 0.0
    
    # 数値の場合
    res.status = 123
    assert res._calculate_progress() == 0.0
    
    # 未定義文字列の場合
    res.status = "undefined_status"
    assert res._calculate_progress() == 0.0

    # 辞書（unhashable な型）の場合は TypeError が発生することを検証
    res.status = {"status": "active"}
    with pytest.raises(TypeError):
        res._calculate_progress()

def test_tracker_update_status_invalid_type(tmp_path):
    """update_status に ResolutionStatus 以外の不正なオブジェクトや None を渡した際、クラッシュせずに更新・保存されることを検証。"""
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    res = tracker.create_resolution("T", "D", {}, "S")
    
    # 不正な文字列
    tracker.update_status(res.id, "invalid_status_string")
    assert res.status == "invalid_status_string"
    
    # None
    tracker.update_status(res.id, None)
    assert res.status is None
    
    # ファイルに正常に保存されているか（保存段階で TypeError などが発生しないことを確認）
    file_path = tmp_path / f"resolution_{res.id}.json"
    with open(file_path, "r", encoding="utf-8") as f:
        import json
        saved_data = json.load(f)
    assert saved_data["status"] is None

def test_tracker_record_vote_edge_cases(tmp_path):
    """record_vote の引数に空文字、極端に長いエージェント名、および "APPROVE"/"REJECT" 以外の投票値が渡された際、適切に辞書に記録され保存されることを検証。"""
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    res = tracker.create_resolution("T", "D", {}, "S")
    
    # 空文字のエージェント名と投票
    tracker.record_vote(res.id, "", "")
    assert res.votes[""] == ""
    
    # 極端に長いエージェント名
    long_agent = "Agent_" + "A" * 1000
    tracker.record_vote(res.id, long_agent, "APPROVE")
    assert res.votes[long_agent] == "APPROVE"
    
    # 不正な投票値 (ABSTAIN, None, 数値)
    tracker.record_vote(res.id, "agent_1", "ABSTAIN")
    tracker.record_vote(res.id, "agent_2", None)
    tracker.record_vote(res.id, "agent_3", 999)
    
    assert res.votes["agent_1"] == "ABSTAIN"
    assert res.votes["agent_2"] is None
    assert res.votes["agent_3"] == 999
    
    # 保存内容の検証
    file_path = tmp_path / f"resolution_{res.id}.json"
    with open(file_path, "r", encoding="utf-8") as f:
        import json
        saved_data = json.load(f)
    assert saved_data["votes"][""] == ""
    assert saved_data["votes"][long_agent] == "APPROVE"
    assert saved_data["votes"]["agent_1"] == "ABSTAIN"
    assert saved_data["votes"]["agent_2"] is None
    assert saved_data["votes"]["agent_3"] == 999

def test_tracker_apply_gavel_edge_cases(tmp_path):
    """議長決済において decision に None や任意の文字列が渡された際、一律でステータスが REJECTED になる仕様が安全に動作することを検証。"""
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    
    # decision = "PENDING"
    res1 = tracker.create_resolution("T1", "D1", {}, "S1")
    success1 = tracker.apply_gavel(res1.id, "PENDING")
    assert success1 is True
    assert res1.gavel_decision == "PENDING"
    assert res1.status == ResolutionStatus.REJECTED
    
    # decision = "" (空文字)
    res2 = tracker.create_resolution("T2", "D2", {}, "S2")
    success2 = tracker.apply_gavel(res2.id, "")
    assert success2 is True
    assert res2.gavel_decision == ""
    assert res2.status == ResolutionStatus.REJECTED
    
    # decision = 123 (数値)
    res3 = tracker.create_resolution("T3", "D3", {}, "S3")
    success3 = tracker.apply_gavel(res3.id, 123)
    assert success3 is True
    assert res3.gavel_decision == 123
    assert res3.status == ResolutionStatus.REJECTED

def test_tracker_save_resolution_permission_error(tmp_path):
    """ファイル保存処理中に PermissionError (書き込み権限なし) が発生した際、OSError として安全にキャッチされ、エラーログが出力されることを検証。"""
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    res = Resolution("id-permission-error", "T", "D", {}, "S")
    
    # PermissionError は OSError のサブクラス
    with patch("safe_io.SafeJsonStore.save", side_effect=PermissionError("Permission Denied")):
        with patch("agents.resolution_tracker.logger.error") as mock_log_err:
            tracker._save_resolution(res)
            # 例外がキャッチされ、ログが出力されていること
            mock_log_err.assert_called_once()
            log_msg = mock_log_err.call_args[0][0]
            assert "Failed to save resolution id-permission-error" in log_msg
            assert "Permission Denied" in log_msg


def test_tracker_list_resolutions_empty(tmp_path):
    """決議案が1つもない（空リスト）の状態で list_resolutions が空リストを返すことを検証。"""
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    assert tracker.list_resolutions() == []
    assert tracker.list_resolutions(status=ResolutionStatus.DRAFT) == []


def test_tracker_list_resolutions_invalid_status(tmp_path):
    """存在しないステータスや不正なステータスを指定して list_resolutions を呼んだ際、空リストが返ることを検証。"""
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    tracker.create_resolution("T1", "D1", {}, "S1")
    
    # 存在しないステータス文字列
    assert tracker.list_resolutions(status="non-existent-status") == []
    # 不正な型 (数値)
    assert tracker.list_resolutions(status=12345) == []
    # None の場合はフィルタされずに全件が返る
    assert len(tracker.list_resolutions(status=None)) == 1


def test_tracker_list_resolutions_large_volume(tmp_path):
    """大量（100件）の決議案を作成した際、list_resolutions が正しくソートして全件取得できることを検証。"""
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    created_resolutions = []
    
    # 時間をずらしながら 100 件作成
    for i in range(100):
        with patch("time.time", return_value=1000.0 + i):
            res = tracker.create_resolution(f"Title {i}", f"Desc {i}", {"index": i}, f"session-{i}")
            created_resolutions.append(res)
            
    all_res = tracker.list_resolutions()
    assert len(all_res) == 100
    # 最新（updated_atが最大、i=99）のものが最初に来ていることを検証
    assert all_res[0]["id"] == created_resolutions[-1].id
    assert all_res[-1]["id"] == created_resolutions[0].id


def test_resolution_init_invalid_types():
    """Resolution の初期化引数に None や不正な型を渡した際の挙動を検証。"""
    # 正常系に近いが、None や空文字の許容
    res = Resolution(
        resolution_id="",
        title=None,
        description="",
        proposed_changes=None,
        session_id=12345  # 不正型
    )
    assert res.id == ""
    assert res.title is None
    assert res.description == ""
    assert res.proposed_changes is None
    assert res.session_id == 12345


def test_tracker_create_resolution_large_payload(tmp_path):
    """巨大な proposed_changes (巨大なネストされた辞書) を持つ決議案が正しく作成・保存されることを検証。"""
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    
    # 巨大な辞書の生成
    large_changes = {f"key_{i}": {"nested": ["a" * 100, i]} for i in range(1000)}
    
    res = tracker.create_resolution(
        title="Large Payload Res",
        description="Testing large dict serialization",
        proposed_changes=large_changes,
        session_id="session-large"
    )
    
    assert res.id in tracker.active_resolutions
    
    # 保存されたファイルを読み込んで検証
    file_path = tmp_path / f"resolution_{res.id}.json"
    assert file_path.exists()
    
    import json
    with open(file_path, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert saved_data["proposed_changes"]["key_999"]["nested"][1] == 999
    assert len(saved_data["proposed_changes"]) == 1000


def test_tracker_init_empty_or_special_dir(tmp_path):
    """archive_dir が空文字や特殊なパスの場合の挙動を検証。"""
    # 空文字（Windowsではmakedirsでエラーになるため、例外をキャッチして許容する）
    try:
        tracker = ResolutionTracker(archive_dir="")
        assert tracker.active_resolutions == {}
    except OSError:
        pass
    
    # 特殊文字を含むパス
    special_dir = tmp_path / "test_dir_*?<>|"
    try:
        tracker_special = ResolutionTracker(archive_dir=str(special_dir))
        assert tracker_special.active_resolutions == {}
    except OSError:
        # OSによって作成不可のOSErrorが発生することは許容
        pass


def test_tracker_create_resolution_edge_cases(tmp_path):
    """create_resolution において境界値や None 入力の挙動を検証。"""
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    
    # 巨大な文字列の title と description
    huge_title = "A" * 10000
    huge_desc = "B" * 100000
    
    res = tracker.create_resolution(
        title=huge_title,
        description=huge_desc,
        proposed_changes=None,
        session_id=""
    )
    assert res.title == huge_title
    assert res.description == huge_desc
    assert res.proposed_changes is None
    assert res.session_id == ""
    
    # ファイルに正常に保存されているか確認
    file_path = tmp_path / f"resolution_{res.id}.json"
    assert file_path.exists()


def test_tracker_get_resolution_invalid_inputs(tmp_path):
    """get_resolution において None や unhashable な型の resolution_id が渡された場合の挙動を検証。"""
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    
    # None
    assert tracker.get_resolution(None) is None
    
    # 空文字列
    assert tracker.get_resolution("") is None
    
    # リスト (unhashable) は dict.get() で TypeError を投げるため、例外送出を検証
    with pytest.raises(TypeError):
        tracker.get_resolution(["invalid-id"])


def test_tracker_apply_gavel_invalid_decision_type(tmp_path):
    """apply_gavel において decision に unhashable や特殊な型が指定された際の挙動を検証。"""
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    res = tracker.create_resolution("T", "D", {}, "S")
    
    # decision にリスト（不正型）を指定した場合
    # Resolution.status = ResolutionStatus.REJECTED になり、問題なく保存されることを検証
    success = tracker.apply_gavel(res.id, ["REJECT_LIST"])
    assert success is True
    assert res.gavel_decision == ["REJECT_LIST"]
    assert res.status == ResolutionStatus.REJECTED


def test_tracker_save_resolution_memory_error(tmp_path):
    """_save_resolution 内で OSError 以外の致命的エラー (例: MemoryError) が発生した際、
    安全に呼び出し元へ例外が伝播することを検証。
    """
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    res = Resolution("id-memory-error", "T", "D", {}, "S")
    
    # MemoryError は OSError のサブクラスではないため、キャッチされずに外に抜けるはず
    with patch("safe_io.SafeJsonStore.save", side_effect=MemoryError("Out of memory")):
        with pytest.raises(MemoryError):
            tracker._save_resolution(res)


def test_tracker_record_vote_massive_agents(tmp_path):
    """1つの決議案に対して、大量（1000個）のエージェント投票を記録し、正しく保存・メモリ更新されることを検証。"""
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    res = tracker.create_resolution("Massive Votes", "D", {}, "S")
    
    # 1000個の投票を記録
    for i in range(1000):
        tracker.record_vote(res.id, f"agent_{i}", "APPROVE" if i % 2 == 0 else "REJECT")
        
    assert len(res.votes) == 1000
    assert res.votes["agent_0"] == "APPROVE"
    assert res.votes["agent_999"] == "REJECT"
    
    # ファイルからも正しく読み込めるか検証
    file_path = tmp_path / f"resolution_{res.id}.json"
    with open(file_path, "r", encoding="utf-8") as f:
        import json
        saved_data = json.load(f)
    assert len(saved_data["votes"]) == 1000
    assert saved_data["votes"]["agent_500"] == "APPROVE"


def test_tracker_special_unicode_strings(tmp_path):
    """title, description, agent_name, vote, gavel_decision にサロゲートペアや制御文字、特殊絵文字が含まれる場合の挙動を検証。"""
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    
    special_title = "決議案 🌟 𩸽 (Surrogate Pair) \u200b (Zero Width Space) \x07 (Bell)"
    special_desc = "説明文: \n\t\r 𠮷野家 👍"
    special_changes = {"key": "value \U0001F600"}
    
    res = tracker.create_resolution(
        title=special_title,
        description=special_desc,
        proposed_changes=special_changes,
        session_id="session-special-unicode"
    )
    
    special_agent = "エージェント 🤖 🪐"
    special_vote = "投票 ✔️ ❌"
    tracker.record_vote(res.id, special_agent, special_vote)
    
    special_decision = "裁決 🏛️ ✨"
    tracker.apply_gavel(res.id, special_decision)
    
    assert res.title == special_title
    assert res.description == special_desc
    assert res.votes[special_agent] == special_vote
    assert res.gavel_decision == special_decision
    
    # ファイルが壊れることなく保存され、正常にロードできるか検証
    file_path = tmp_path / f"resolution_{res.id}.json"
    assert file_path.exists()
    
    with open(file_path, "r", encoding="utf-8") as f:
        import json
        saved_data = json.load(f)
    assert saved_data["title"] == special_title
    assert saved_data["description"] == special_desc
    assert saved_data["votes"][special_agent] == special_vote
    assert saved_data["gavel_decision"] == special_decision


def test_tracker_list_resolutions_abnormal_updated_at_sorting(tmp_path):
    """updated_at が 0.0、負の値、未来の値などの異常境界値を含む場合の list_resolutions の並び替え挙動を検証。"""
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    
    # updated_at を操作して複数の Resolution を作成
    res_zero = tracker.create_resolution("Zero", "D", {}, "S")
    res_zero.updated_at = 0.0
    tracker._save_resolution(res_zero)
    
    res_neg = tracker.create_resolution("Negative", "D", {}, "S")
    res_neg.updated_at = -12345.67
    tracker._save_resolution(res_neg)
    
    res_future = tracker.create_resolution("Future", "D", {}, "S")
    res_future.updated_at = 9999999999.9
    tracker._save_resolution(res_future)
    
    res_normal = tracker.create_resolution("Normal", "D", {}, "S")
    res_normal.updated_at = 1600000000.0
    tracker._save_resolution(res_normal)
    
    # updated_at の降順で返されるはず: Future (9999999999.9) -> Normal (1600000000.0) -> Zero (0.0) -> Negative (-12345.67)
    all_res = tracker.list_resolutions()
    assert len(all_res) == 4
    assert all_res[0]["id"] == res_future.id
    assert all_res[1]["id"] == res_normal.id
    assert all_res[2]["id"] == res_zero.id
    assert all_res[3]["id"] == res_neg.id


def test_tracker_list_resolutions_unhashable_status_filter(tmp_path):
    """list_resolutions に list や dict などの unhashable オブジェクトが渡された場合でも、TypeError などが発生しないことを検証。"""
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    tracker.create_resolution("T", "D", {}, "S")
    
    # list を status 引数に渡した場合（リスト同士の比較は通常 False を返すだけで例外は出ないはず）
    assert tracker.list_resolutions(status=[ResolutionStatus.DRAFT]) == []
    
    # dict を status 引数に渡した場合
    assert tracker.list_resolutions(status={"status": "draft"}) == []


def test_tracker_create_resolution_various_proposed_changes_types(tmp_path):
    """proposed_changes に dict 以外の型（数値、文字列、リスト、None）を渡した際のシリアライズ互換性を検証。"""
    tracker = ResolutionTracker(archive_dir=str(tmp_path))
    
    # None
    res_none = tracker.create_resolution("None Changes", "D", None, "S")
    assert res_none.proposed_changes is None
    
    # List
    res_list = tracker.create_resolution("List Changes", "D", [1, 2, 3, {"nested": True}], "S")
    assert res_list.proposed_changes == [1, 2, 3, {"nested": True}]
    
    # Primitive int
    res_int = tracker.create_resolution("Int Changes", "D", 12345, "S")
    assert res_int.proposed_changes == 12345
    
    # Primitive string
    res_str = tracker.create_resolution("Str Changes", "D", "flat-string-config", "S")
    assert res_str.proposed_changes == "flat-string-config"
    
    # ファイルに正常にシリアライズされて保存されているか確認
    for res in [res_none, res_list, res_int, res_str]:
        file_path = tmp_path / f"resolution_{res.id}.json"
        assert file_path.exists()
        with open(file_path, "r", encoding="utf-8") as f:
            import json
            saved_data = json.load(f)
        assert saved_data["proposed_changes"] == res.proposed_changes

