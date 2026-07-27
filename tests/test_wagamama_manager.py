import sys
import os
import json
import logging
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

# Path setup to include backend parent (workspace root)
sys.path.insert(0, str(Path(__file__).parent.parent))

import backend.wagamama_manager as wm_module


@pytest.fixture
def mock_wagamama_env(tmp_path, monkeypatch):
    """WagamamaManagerのファイルパスをテスト用の一時ディレクトリに差し替える"""
    test_data_dir = tmp_path / "branding"
    test_ledger_file = test_data_dir / "wagamama_ledger.json"

    # モジュールのグローバル変数を差し替え
    monkeypatch.setattr(wm_module, "DATA_DIR", test_data_dir)
    monkeypatch.setattr(wm_module, "LEDGER_FILE", test_ledger_file)

    # 差し替えたパスでクリーンにインスタンスを作成
    manager = wm_module.WagamamaManager()
    return manager, test_ledger_file


def test_manager_initialization_creates_file(mock_wagamama_env):
    """初期化時にファイルが存在しない場合、初期テンプレートでファイルが作成されること"""
    manager, ledger_file = mock_wagamama_env
    assert ledger_file.exists()
    
    with open(ledger_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["version"] == "1.0"
    assert data["name"] == "Wagamama Ledger"
    assert isinstance(data["records"], list)
    assert len(data["records"]) == 0


def test_manager_initialization_corrupted_json(tmp_path, monkeypatch):
    """JSONが破損している場合、初期化エラーをログ出力し、空レコードにフォールバックされること"""
    test_data_dir = tmp_path / "branding"
    test_data_dir.mkdir(parents=True, exist_ok=True)
    test_ledger_file = test_data_dir / "wagamama_ledger.json"
    
    # 壊れたJSONを書き込む
    with open(test_ledger_file, "w", encoding="utf-8") as f:
        f.write("{invalid json: broken")
        
    monkeypatch.setattr(wm_module, "DATA_DIR", test_data_dir)
    monkeypatch.setattr(wm_module, "LEDGER_FILE", test_ledger_file)
    
    import safe_io
    with patch.object(safe_io.logger, "error") as mock_log:
        manager = wm_module.WagamamaManager()
        
        # エラーログが出力されたことを検証
        mock_log.assert_called()
        assert any("JSONファイル読み込みエラー" in call[0][0] for call in mock_log.call_args_list)
        # 空のレコードリストでフォールバックされていること
        assert manager.ledger_data == manager.store._default


def test_manager_save_exception(mock_wagamama_env):
    """保存時にファイル書き込みエラーが発生した場合、例外がキャッチされエラーログが出力されること"""
    manager, ledger_file = mock_wagamama_env
    
    # store.save で例外を発生させるようにモック
    with patch.object(manager.store, "save", side_effect=IOError("Permission denied")),          patch.object(wm_module.logger, "error") as mock_log:
        manager._save()
        mock_log.assert_called_with("Failed to save wagamama ledger: Permission denied")


def test_manager_initialization_save_exception(tmp_path, monkeypatch):
    """初期化時のファイル保存エラー発生時、例外がキャッチされエラーログが出力されること"""
    test_data_dir = tmp_path / "branding"
    test_ledger_file = test_data_dir / "wagamama_ledger.json"
    
    monkeypatch.setattr(wm_module, "DATA_DIR", test_data_dir)
    monkeypatch.setattr(wm_module, "LEDGER_FILE", test_ledger_file)
    
    import safe_io
    with patch.object(safe_io.SafeJsonStore, "save", side_effect=IOError("Disk full")),          patch.object(wm_module.logger, "error") as mock_log:
        manager = wm_module.WagamamaManager()
        
        # _ensure_file_exists 内で発生したエラーがログ出力されたことを検証
        mock_log.assert_any_call("Failed to initialize wagamama ledger file: Disk full")


def test_create_experience_story(mock_wagamama_env):
    """正常にストーリーを起票し、レコード構造と発番が正しいこと"""
    manager, ledger_file = mock_wagamama_env
    
    w_id1 = manager.create_experience_story(
        user_voice="フォントサイズが小さくて見づらい",
        detected_by="test_nexus",
        feature_id="ft_font_adjust"
    )
    
    # 発番チェック (W-001)
    assert w_id1 == "W-001"
    
    # 2件目の起票で発番がカウントアップされること (W-002)
    w_id2 = manager.create_experience_story("動画出力時にカクつく")
    assert w_id2 == "W-002"
    
    # 保存されたJSONデータを確認
    with open(ledger_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    records = data["records"]
    assert len(records) == 2
    
    rec1 = records[0]
    assert rec1["wagamama_id"] == "W-001"
    assert rec1["feature_id"] == "ft_font_adjust"
    assert rec1["lanes"]["experience"]["pain"] == "フォントサイズが小さくて見づらい"
    assert rec1["lanes"]["experience"]["pain_detected_by"] == "test_nexus"
    assert "pain_timestamp" in rec1["lanes"]["experience"]
    assert rec1["quality_gap"] is True
    assert rec1["status"] == "investigating"


def test_link_council_session(mock_wagamama_env):
    """存在するレコードに対して議会セッションを正常にリンクし、存在しない場合はFalseを返すこと"""
    manager, _ = mock_wagamama_env
    
    # 存在しないIDに対してはFalseを返す
    success = manager.link_council_session("W-999", "session_abc", "log.txt", {"summary": "Resolved font issues"})
    assert success is False
    
    # 起票
    w_id = manager.create_experience_story("音声ボリューム調整が面倒")
    
    success = manager.link_council_session(
        w_id,
        session_id="session_abc",
        log_file="council_session_abc.log",
        synthesis={"summary": "Use auto-ducking feature"}
    )
    assert success is True
    
    # レコード検証
    record = manager.get_record(w_id)
    assert record["status"] == "in_debate"
    council = record["lanes"]["experience"]["council"]
    assert council["session_id"] == "session_abc"
    assert council["log_file"] == "council_session_abc.log"
    assert council["synthesis"] == "Use auto-ducking feature"


def test_resolve_story_and_quality_gaps(mock_wagamama_env):
    """正常にストーリーを解決し、品質ギャップ警告とマニュアル紐付けを制御できること"""
    manager, _ = mock_wagamama_env
    
    # 存在しないIDに対してはFalse
    assert manager.resolve_story("W-999", "Solved") is False
    
    # 起票
    w_id = manager.create_experience_story("BGMの種類が少なすぎる")
    
    # マニュアル紐付けがない状態で解決した際のログ警告を検証
    with patch.object(wm_module.logger, "warning") as mock_warn:
        success = manager.resolve_story(w_id, "BGMアセットライブラリに20曲追加", emotion="非常に満足")
        assert success is True
        mock_warn.assert_called_with(f"⚠️ [Wagamama Ledger] {w_id} は解決されましたが、USER_MANUALへの紐付けがありません（品質ギャップ）。")
        
    record = manager.get_record(w_id)
    assert record["status"] == "resolved"
    assert record["lanes"]["experience"]["magic"] == "BGMアセットライブラリに20曲追加"
    assert record["lanes"]["experience"]["emotion"] == "非常に満足"
    assert "resolved_at" in record["lanes"]["experience"]
    assert record["quality_gap"] is True
    
    # 品質ギャップが抽出できることを検証
    gaps = manager.get_quality_gaps()
    assert len(gaps) == 1
    assert gaps[0]["id"] == w_id
    assert gaps[0]["pain"] == "BGMの種類が少なすぎる"
    
    # マニュアル紐付けを行い品質ギャップを解消
    assert manager.link_manual_section("W-999", "sec_9") is False
    
    success = manager.link_manual_section(w_id, "USER_MANUAL.md#sec_bgm")
    assert success is True
    
    record = manager.get_record(w_id)
    assert record["manual_section"] == "USER_MANUAL.md#sec_bgm"
    assert record["quality_gap"] is False
    
    # ギャップがゼロになったことを検証
    assert len(manager.get_quality_gaps()) == 0


def test_set_youtube_video_id(mock_wagamama_env):
    """YouTubeの動画IDが正常に紐付けられること"""
    manager, _ = mock_wagamama_env
    
    assert manager.set_youtube_video_id("W-999", "vid_xyz") is False
    
    w_id = manager.create_experience_story("動画公開フローをテスト")
    success = manager.set_youtube_video_id(w_id, "vid_xyz")
    assert success is True
    
    record = manager.get_record(w_id)
    assert record["youtube_video_id"] == "vid_xyz"


def test_enterprise_gate_check(mock_wagamama_env):
    """Go/No-Goゲートチェックの判定結果とメッセージが正しいこと"""
    manager, _ = mock_wagamama_env
    
    # 存在しないID
    res = manager.enterprise_gate_check("W-999", predicted_ctr=5.5)
    assert res["status"] == "error"
    assert "message" in res
    
    w_id = manager.create_experience_story("高エンゲージメント動画企画")
    
    # Go 判定 (閾値 3.0 に対し 4.5)
    res_go = manager.enterprise_gate_check(w_id, predicted_ctr=4.5, min_threshold=3.0)
    assert res_go["is_go"] is True
    assert "承認" in res_go["message"]
    
    record = manager.get_record(w_id)
    gate = record["lanes"]["experience"]["enterprise_gate"]
    assert gate["predicted_ctr"] == 4.5
    assert gate["threshold"] == 3.0
    assert "Go" in gate["result"]
    
    # No-Go 判定 (閾値 3.0 に対し 2.0)
    res_nogo = manager.enterprise_gate_check(w_id, predicted_ctr=2.0, min_threshold=3.0)
    assert res_nogo["is_go"] is False
    assert "下回っています" in res_nogo["message"]
    
    record = manager.get_record(w_id)
    gate = record["lanes"]["experience"]["enterprise_gate"]
    assert gate["predicted_ctr"] == 2.0
    assert "No-Go" in gate["result"]


def test_add_distilled_knowledge(mock_wagamama_env):
    """蒸留知識が重複なく蓄積され、自動発番とタイムスタンプが付与されること"""
    manager, _ = mock_wagamama_env
    
    k_id1 = manager.add_distilled_knowledge(
        topic="CTR_Improvement",
        pattern="冒頭3秒に派手なテロップを表示",
        confidence=0.95
    )
    assert k_id1 == "K-001"
    
    k_id2 = manager.add_distilled_knowledge("Audio_Mix", "BGMを-20dBに下げる")
    assert k_id2 == "K-002"
    
    # 保存内容の確認
    knowledge_base = manager.ledger_data["knowledge_base"]
    assert len(knowledge_base) == 2
    
    k1 = knowledge_base[0]
    assert k1["id"] == "K-001"
    assert k1["topic"] == "CTR_Improvement"
    assert k1["pattern"] == "冒頭3秒に派手なテロップを表示"
    assert k1["confidence"] == 0.95
    assert "distilled_at" in k1

def test_auto_detect_manual_section_os_error(mock_wagamama_env):
    """USER_MANUAL.md の読み込み時に OSError が発生した場合、例外がキャッチされ、エラーログが出力され、Noneが返されること"""
    manager, _ = mock_wagamama_env
    
    # 読み込み時に OSError を発生させるために open を mock する
    with patch("builtins.open", side_effect=OSError("Read error")), \
         patch.object(wm_module.logger, "error") as mock_log:
        
        record = {"feature_id": "test_feature"}
        result = manager._auto_detect_manual_section(record)
        
        assert result is None
        mock_log.assert_called_with("Failed to auto detect manual section: Read error")


def test_create_experience_story_invalid_types(mock_wagamama_env):
    """引数に不正な型が渡された場合に TypeError が発生するか、あるいは適切に処理されること"""
    manager, _ = mock_wagamama_env
    with pytest.raises(TypeError):
        manager.create_experience_story(user_voice=123)  # user_voice は文字列である必要がある
        
    with pytest.raises(TypeError):
        manager.create_experience_story(user_voice="test", detected_by=123)
        
    with pytest.raises(TypeError):
        manager.create_experience_story(user_voice="test", feature_id=123)

    with pytest.raises(TypeError):
        manager.create_experience_story(user_voice="test", youtube_video_id=123)


def test_link_council_session_invalid_types(mock_wagamama_env):
    """引数に不正な型が渡された場合に TypeError が発生すること"""
    manager, _ = mock_wagamama_env
    w_id = manager.create_experience_story("テストボイス")
    
    with pytest.raises(TypeError):
        manager.link_council_session(wagamama_id=123, session_id="sess", log_file="log", synthesis={})
        
    with pytest.raises(TypeError):
        manager.link_council_session(wagamama_id=w_id, session_id=123, log_file="log", synthesis={})
        
    with pytest.raises(TypeError):
        manager.link_council_session(wagamama_id=w_id, session_id="sess", log_file=123, synthesis={})


def test_resolve_story_invalid_types(mock_wagamama_env):
    """引数に不正な型が渡された場合に TypeError が発生すること"""
    manager, _ = mock_wagamama_env
    w_id = manager.create_experience_story("テストボイス")
    
    with pytest.raises(TypeError):
        manager.resolve_story(wagamama_id=123, solution_description="解決")
        
    with pytest.raises(TypeError):
        manager.resolve_story(wagamama_id=w_id, solution_description=123)
        
    with pytest.raises(TypeError):
        manager.resolve_story(wagamama_id=w_id, solution_description="解決", emotion=123)


def test_find_matching_story_invalid_types(mock_wagamama_env):
    """引数に不正な型が渡された場合に安全に処理されること"""
    manager, _ = mock_wagamama_env
    # tags が非リスト型の場合
    assert manager.find_matching_story("topic", tags="not_a_list") is None
    
    # topic が非文字列の場合
    assert manager.find_matching_story(123) is None


def test_corrupted_ledger_structure(mock_wagamama_env):
    """台帳データの構造が一部破損している（recordsがリストでない、または必要なキーがない）場合でもクラッシュせず安全にフォールバックすること"""
    manager, _ = mock_wagamama_env
    
    # records を辞書にして破損させる
    manager.ledger_data["records"] = {"not": "a_list"}
    with pytest.raises(ValueError):
        manager.create_experience_story("テスト")
        
    # records が欠落している場合
    del manager.ledger_data["records"]
    w_id = manager.create_experience_story("テスト")
    assert w_id == "W-001"
    assert isinstance(manager.ledger_data["records"], list)
    
    # レコード内の lanes が破損している場合
    record = manager.get_record(w_id)
    del record["lanes"]
    
    # link_council_session は lanes がなくても安全に作成して続行できること
    success = manager.link_council_session(w_id, "sess", "log", {"summary": "OK"})
    assert success is True
    assert "lanes" in record
    assert "experience" in record["lanes"]
    
    # resolve_story も lanes がない状態から安全に解決できること
    w_id2 = manager.create_experience_story("テスト2")
    record2 = manager.get_record(w_id2)
    del record2["lanes"]
    
    success = manager.resolve_story(w_id2, "解決")
    assert success is True
    assert "lanes" in record2
    assert "experience" in record2["lanes"]
