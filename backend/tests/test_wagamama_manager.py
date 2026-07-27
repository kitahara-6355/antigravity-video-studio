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


def test_auto_detect_manual_section_unicode_decode_error(mock_wagamama_env):
    """USER_MANUAL.md のデコード時に UnicodeDecodeError が発生した場合、例外がキャッチされ、エラーログが出力され、Noneが返されること"""
    manager, _ = mock_wagamama_env
    
    decode_error = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
    with patch("builtins.open", side_effect=decode_error), \
         patch.object(wm_module.logger, "error") as mock_log:
        
        record = {"feature_id": "test_feature"}
        result = manager._auto_detect_manual_section(record)
        
        assert result is None
        mock_log.assert_called_with("Failed to auto detect manual section: 'utf-8' codec can't decode byte 0xff in position 0: invalid start byte")


def test_auto_detect_manual_section_edge_cases(mock_wagamama_env, tmp_path):
    """manual_pathが存在しない場合、feature_idが無い場合、見出しに部分一致する場合の挙動をテスト"""
    manager, _ = mock_wagamama_env

    # 1. manual_path が存在しない場合
    manager.manual_path = tmp_path / "non_existent_manual.md"
    record = {"feature_id": "ft_test"}
    assert manager._auto_detect_manual_section(record) is None

    # 2. manual_path を None にした場合
    manager.manual_path = None
    assert manager._auto_detect_manual_section(record) is None

    # 3. record に feature_id が無い場合
    manager.manual_path = tmp_path / "USER_MANUAL.md"
    with open(manager.manual_path, "w", encoding="utf-8") as f:
        f.write("# ft_test_section\n")
    assert manager._auto_detect_manual_section({}) is None
    assert manager._auto_detect_manual_section({"feature_id": ""}) is None

    # 4. 見出しに feature_id が部分一致する場合
    record = {"feature_id": "ft_test"}
    assert manager._auto_detect_manual_section(record) == "ft_test_section"


def test_find_matching_story(mock_wagamama_env):
    """find_matching_story メソッドがトピック、タグ、痛みの内容に基づいて正しく進行中ストーリーを検索できること"""
    manager, _ = mock_wagamama_env

    # レコードが無い状態
    assert manager.find_matching_story("ft_test") is None

    # レコード作成 (status: investigating)
    w_id = manager.create_experience_story(
        user_voice="フォントサイズが小さくて見づらい",
        detected_by="test_nexus",
        feature_id="ft_font_adjust"
    )

    # 1. feature_id が topic に含まれる場合
    assert manager.find_matching_story("Improve ft_font_adjust size") == w_id

    # 2. tags 内に feature_id が含まれる場合
    assert manager.find_matching_story("Improve size", tags=["ft_font_adjust", "other"]) == w_id

    # 3. pain の内容が topic に部分一致する場合
    assert manager.find_matching_story("フォントサイズが小さくて困っている") == w_id

    # 4. 一致しない場合
    assert manager.find_matching_story("全く関係ないトピック") is None

    # 5. ステータスが resolved の場合は検索対象外
    manager.resolve_story(w_id, "フォント調整機能を追加")
    assert manager.find_matching_story("ft_font_adjust") is None


def test_resolve_story_auto_detect_manual(mock_wagamama_env, tmp_path):
    """ストーリー解決時に、USER_MANUAL.md の見出しから自動検出して manual_section が設定されること"""
    manager, _ = mock_wagamama_env

    # マニュアルファイルを作成
    manager.manual_path = tmp_path / "USER_MANUAL.md"
    with open(manager.manual_path, "w", encoding="utf-8") as f:
        f.write("# ft_auto_detect_section\n")

    w_id = manager.create_experience_story(
        user_voice="自動検出のテスト",
        feature_id="ft_auto_detect"
    )

    # 解決処理を実行（マニュアルセクションが自動検出されるはず）
    success = manager.resolve_story(w_id, "解決策")
    assert success is True

    record = manager.get_record(w_id)
    assert record["status"] == "resolved"
    assert record["manual_section"] == "ft_auto_detect_section"
    assert record["quality_gap"] is False


def test_create_experience_story_edge_cases(mock_wagamama_env):
    """create_experience_story に None や極端な値、不正型を渡した際のエッジケーステスト"""
    manager, _ = mock_wagamama_env
    
    # 1. 極端に巨大な入力
    huge_voice = "A" * 10000
    w_id = manager.create_experience_story(huge_voice)
    record = manager.get_record(w_id)
    assert record["lanes"]["experience"]["pain"] == huge_voice

    # 2. None 入力 / 不正型による TypeError の発生を検証
    with pytest.raises(TypeError):
        manager.create_experience_story(None)

    with pytest.raises(TypeError):
        manager.create_experience_story(12345)


def test_link_council_session_edge_cases(mock_wagamama_env):
    """link_council_session に None や不正な dictionary 構造を渡した際のエッジケーステスト"""
    manager, _ = mock_wagamama_env
    w_id = manager.create_experience_story("テスト")

    # 1. synthesis に 'summary' キーが含まれない空の辞書を渡した場合
    success = manager.link_council_session(w_id, "session_1", "log.txt", {})
    assert success is True
    record = manager.get_record(w_id)
    assert record["lanes"]["experience"]["council"]["synthesis"] == "No synthesis logic provided"

    # 2. synthesis が None の場合、TypeError が発生することを期待する
    with pytest.raises(TypeError):
        manager.link_council_session(w_id, "session_2", "log.txt", None)


def test_find_matching_story_edge_cases(mock_wagamama_env):
    """find_matching_story における None, 空文字, 空リストなどの入力"""
    manager, _ = mock_wagamama_env

    # 1. topic が None または空文字列の場合の挙動
    assert manager.find_matching_story(None) is None
    assert manager.find_matching_story("") is None

    # レコード作成
    w_id = manager.create_experience_story("痛みの声", feature_id="ft_test")

    # 1-2. レコードが存在する状態での topic=None または空文字列 of 挙動 (バグ検証用)
    assert manager.find_matching_story(None) is None
    assert manager.find_matching_story("") is None

    # 2. tags が None または空リストの場合の挙動
    assert manager.find_matching_story("Improve ft_test", tags=None) == w_id
    assert manager.find_matching_story("Improve ft_test", tags=[]) == w_id

    # 3. 巨大トピック
    huge_topic = "A" * 10000 + " ft_test " + "B" * 10000
    assert manager.find_matching_story(huge_topic) == w_id


def test_enterprise_gate_check_edge_cases(mock_wagamama_env):
    """enterprise_gate_check における境界値と不正型入力"""
    manager, _ = mock_wagamama_env
    w_id = manager.create_experience_story("企画")

    # 1. 境界値: predicted_ctr == min_threshold
    res = manager.enterprise_gate_check(w_id, predicted_ctr=3.0, min_threshold=3.0)
    assert res["is_go"] is True

    # 2. 境界値: predicted_ctr が min_threshold よりわずかに小さい
    res = manager.enterprise_gate_check(w_id, predicted_ctr=2.999, min_threshold=3.0)
    assert res["is_go"] is False

    # 3. 負の値
    res = manager.enterprise_gate_check(w_id, predicted_ctr=-1.0, min_threshold=3.0)
    assert res["is_go"] is False

    # 4. 100%を超える値
    res = manager.enterprise_gate_check(w_id, predicted_ctr=150.0, min_threshold=3.0)
    assert res["is_go"] is True


def test_add_distilled_knowledge_edge_cases(mock_wagamama_env):
    """add_distilled_knowledge におけるエッジケース（巨大入力、特殊な信頼度値）"""
    manager, _ = mock_wagamama_env

    # 1. 極端な信頼度値
    k_id1 = manager.add_distilled_knowledge("Topic", "Pattern", confidence=-0.5)
    k_id2 = manager.add_distilled_knowledge("Topic", "Pattern", confidence=999.9)

    knowledge_base = manager.ledger_data["knowledge_base"]
    assert knowledge_base[0]["confidence"] == -0.5
    assert knowledge_base[1]["confidence"] == 999.9


def test_wagamama_id_generation_overflow(mock_wagamama_env):
    """起票数が 999 を超える場合の ID 生成挙動（境界値）"""
    manager, _ = mock_wagamama_env

    # records リストの長さをモックして、1000件目の起票をシミュレートする
    manager.ledger_data["records"] = [{"wagamama_id": f"W-{i:03d}"} for i in range(1, 1000)]

    w_id = manager.create_experience_story("1000件目の不満")
    # W-1000 になることを確認
    assert w_id == "W-1000"


def test_get_record_invalid_types(mock_wagamama_env):
    """get_record に不正な型を渡した際、TypeError が発生すること"""
    manager, _ = mock_wagamama_env
    with pytest.raises(TypeError):
        manager.get_record(123)
    with pytest.raises(TypeError):
        manager.get_record(None)


def test_create_experience_story_type_and_structure_exceptions(mock_wagamama_env):
    """create_experience_story の引数の型例外および records 構造の例外検証"""
    manager, _ = mock_wagamama_env

    # 1. 各引数の型例外検証 (detected_by, feature_id, youtube_video_id)
    with pytest.raises(TypeError):
        manager.create_experience_story("Voice", detected_by=123)
    with pytest.raises(TypeError):
        manager.create_experience_story("Voice", feature_id=123)
    with pytest.raises(TypeError):
        manager.create_experience_story("Voice", youtube_video_id=123)

    # 2. records is None の場合のパス検証
    manager.ledger_data["records"] = None
    w_id = manager.create_experience_story("Voice")
    assert w_id == "W-001"
    assert isinstance(manager.ledger_data["records"], list)

    # 3. records が list ではない場合の ValueError 検証
    manager.ledger_data["records"] = "invalid_records_type"
    with pytest.raises(ValueError, match="wagamama ledger records must be a list"):
        manager.create_experience_story("Voice")


def test_link_council_session_type_and_structure_exceptions(mock_wagamama_env):
    """link_council_session の引数の型例外および lanes 構造の例外検証"""
    manager, _ = mock_wagamama_env
    w_id = manager.create_experience_story("Voice")

    # 1. 各引数の型例外検証 (wagamama_id, session_id, log_file, synthesis)
    with pytest.raises(TypeError):
        manager.link_council_session(123, session_id="session", log_file="log.txt", synthesis={})
    with pytest.raises(TypeError):
        manager.link_council_session(w_id, session_id=123, log_file="log.txt", synthesis={})
    with pytest.raises(TypeError):
        manager.link_council_session(w_id, session_id="session", log_file=123, synthesis={})
    with pytest.raises(TypeError):
        manager.link_council_session(w_id, session_id="session", log_file="log.txt", synthesis="invalid_synthesis")

    # 2. record["lanes"] が辞書ではない場合
    # record["lanes"] を int に設定してシミュレート
    record = manager.get_record(w_id)
    record["lanes"] = 123
    success = manager.link_council_session(w_id, "session", "log.txt", {})
    assert success is True
    record = manager.get_record(w_id)
    assert isinstance(record["lanes"], dict)

    # 3. record["lanes"]["experience"] が辞書ではない場合
    # record["lanes"]["experience"] を int に設定してシミュレート
    record["lanes"]["experience"] = 123
    success = manager.link_council_session(w_id, "session2", "log.txt", {})
    assert success is True
    record = manager.get_record(w_id)
    assert isinstance(record["lanes"]["experience"], dict)


def test_find_matching_story_exceptions_and_edge_cases(mock_wagamama_env):
    """find_matching_story における不正入力および異常なレコード構造の検証"""
    manager, _ = mock_wagamama_env

    # 1. tags が list ではない場合 (None を期待)
    assert manager.find_matching_story("ft_test", tags="invalid_tags_type") is None

    # 2. ledger_data["records"] が list ではない場合 (None を期待)
    manager.ledger_data["records"] = "invalid_records_type"
    assert manager.find_matching_story("ft_test") is None

    # 3. records リスト内に dict ではないオブジェクト（例: 文字列）が含まれる場合
    manager.ledger_data["records"] = ["not_a_dict"]
    assert manager.find_matching_story("ft_test") is None

    # 4. レコード内の feature_id が str ではない場合
    record_invalid_fid = {
        "wagamama_id": "W-001",
        "feature_id": 123,  # str ではない
        "status": "investigating",
        "lanes": {
            "experience": {
                "pain": "痛みの声",
                "pain_detected_by": "nexus",
            }
        }
    }
    manager.ledger_data["records"] = [record_invalid_fid]
    # マッチしない
    assert manager.find_matching_story("ft_test") is None

    # 5. lanes が辞書ではない場合
    record_invalid_lanes = {
        "wagamama_id": "W-002",
        "feature_id": "ft_test",
        "status": "investigating",
        "lanes": "not_a_dict"  # lanes が辞書ではない
    }
    manager.ledger_data["records"] = [record_invalid_lanes]
    # feature_id がマッチするので W-002 が返るはずだが、pain でのマッチを試すために topic を "other" にして lanes を検証する
    assert manager.find_matching_story("other_topic") is None

    # 6. lanes["experience"] が辞書ではない場合
    record_invalid_exp = {
        "wagamama_id": "W-003",
        "feature_id": "ft_test",
        "status": "investigating",
        "lanes": {
            "experience": "not_a_dict"  # exp が辞書ではない
        }
    }
    manager.ledger_data["records"] = [record_invalid_exp]
    assert manager.find_matching_story("other_topic") is None

    # 7. lanes["experience"]["pain"] が文字列ではない場合
    record_invalid_pain = {
        "wagamama_id": "W-004",
        "feature_id": "ft_test",
        "status": "investigating",
        "lanes": {
            "experience": {
                "pain": 12345  # pain が文字列ではない
            }
        }
    }
    manager.ledger_data["records"] = [record_invalid_pain]
    assert manager.find_matching_story("other_topic") is None


def test_resolve_story_type_and_structure_exceptions(mock_wagamama_env):
    """resolve_story の引数型例外および lanes 構造の例外検証"""
    manager, _ = mock_wagamama_env
    w_id = manager.create_experience_story("Voice")

    # 1. 各引数の型例外検証
    with pytest.raises(TypeError):
        manager.resolve_story(123, "Solution")
    with pytest.raises(TypeError):
        manager.resolve_story(w_id, 123)
    with pytest.raises(TypeError):
        manager.resolve_story(w_id, "Solution", emotion=123)

    # 2. record["lanes"] が辞書ではない場合
    record = manager.get_record(w_id)
    record["lanes"] = 123
    success = manager.resolve_story(w_id, "Solution")
    assert success is True
    record = manager.get_record(w_id)
    assert isinstance(record["lanes"], dict)
    assert record["lanes"]["experience"]["magic"] == "Solution"

    # 3. record["lanes"]["experience"] が辞書ではない場合
    record = manager.get_record(w_id)
    # statusを戻す
    record["status"] = "investigating"
    record["lanes"]["experience"] = 123
    success = manager.resolve_story(w_id, "Solution2")
    assert success is True
    record = manager.get_record(w_id)
    assert isinstance(record["lanes"]["experience"], dict)
    assert record["lanes"]["experience"]["magic"] == "Solution2"


def test_set_youtube_video_id_type_exceptions(mock_wagamama_env):
    """set_youtube_video_id の引数型例外検証"""
    manager, _ = mock_wagamama_env
    w_id = manager.create_experience_story("Voice")

    with pytest.raises(TypeError):
        manager.set_youtube_video_id(123, "vid_123")
    with pytest.raises(TypeError):
        manager.set_youtube_video_id(w_id, 123)


def test_enterprise_gate_check_type_exceptions(mock_wagamama_env):
    """enterprise_gate_check の引数型例外検証"""
    manager, _ = mock_wagamama_env
    w_id = manager.create_experience_story("Voice")

    with pytest.raises(TypeError):
        manager.enterprise_gate_check(123, predicted_ctr=3.0)
    with pytest.raises(TypeError):
        manager.enterprise_gate_check(w_id, predicted_ctr="invalid")
    with pytest.raises(TypeError):
        manager.enterprise_gate_check(w_id, predicted_ctr=3.0, min_threshold="invalid")


def test_link_manual_section_type_exceptions(mock_wagamama_env):
    """link_manual_section の引数型例外検証"""
    manager, _ = mock_wagamama_env
    w_id = manager.create_experience_story("Voice")

    with pytest.raises(TypeError):
        manager.link_manual_section(123, "manual_sec")
    with pytest.raises(TypeError):
        manager.link_manual_section(w_id, 123)


def test_add_distilled_knowledge_type_exceptions(mock_wagamama_env):
    """add_distilled_knowledge の引数型例外検証"""
    manager, _ = mock_wagamama_env

    with pytest.raises(TypeError):
        manager.add_distilled_knowledge(123, "pattern")
    with pytest.raises(TypeError):
        manager.add_distilled_knowledge("topic", 123)
    with pytest.raises(TypeError):
        manager.add_distilled_knowledge("topic", "pattern", confidence="invalid")


def test_get_quality_gaps_unknown_pain(mock_wagamama_env):
    """get_quality_gaps で lanes が無かったり experience が無い場合の Unknown pain フォールバック検証"""
    manager, _ = mock_wagamama_env
    
    # 1. lanes 自体が無いレコードを追加
    record_no_lanes = {
        "wagamama_id": "W-001",
        "feature_id": "ft_no_lanes",
        "status": "resolved",
        "quality_gap": True
        # lanes キー無し
    }
    manager.ledger_data["records"] = [record_no_lanes]
    gaps = manager.get_quality_gaps()
    assert len(gaps) == 1
    assert gaps[0]["pain"] == "Unknown pain"


def test_new_input_validations(mock_wagamama_env):
    """新規追加した入力値バリデーション（NaN / Inf、synthesis['summary']の型）のテスト"""
    manager, _ = mock_wagamama_env
    w_id = manager.create_experience_story("Voice")

    # 1. link_council_session: synthesis['summary'] が文字列ではない場合
    with pytest.raises(TypeError, match=r"synthesis\['summary'\] must be a string"):
        manager.link_council_session(w_id, "session", "log.txt", {"summary": 123})

    # 2. enterprise_gate_check: predicted_ctr や min_threshold が NaN / Inf の場合
    import math
    with pytest.raises(ValueError, match="predicted_ctr must be a finite number"):
        manager.enterprise_gate_check(w_id, predicted_ctr=math.nan)
    with pytest.raises(ValueError, match="predicted_ctr must be a finite number"):
        manager.enterprise_gate_check(w_id, predicted_ctr=math.inf)
    with pytest.raises(ValueError, match="min_threshold must be a finite number"):
        manager.enterprise_gate_check(w_id, predicted_ctr=3.0, min_threshold=math.nan)
    with pytest.raises(ValueError, match="min_threshold must be a finite number"):
        manager.enterprise_gate_check(w_id, predicted_ctr=3.0, min_threshold=-math.inf)

    # 3. add_distilled_knowledge: confidence が NaN / Inf の場合
    with pytest.raises(ValueError, match="confidence must be a finite number"):
        manager.add_distilled_knowledge("Topic", "Pattern", confidence=math.nan)
    with pytest.raises(ValueError, match="confidence must be a finite number"):
        manager.add_distilled_knowledge("Topic", "Pattern", confidence=math.inf)


