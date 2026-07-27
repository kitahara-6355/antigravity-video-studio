import pytest
import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
from decision_logger import DecisionLogger, Decision

@pytest.fixture
def temp_logger(tmp_path):
    """テスト用の独立した DecisionLogger インスタンスを返します"""
    log_dir = tmp_path / "branding"
    log_file = log_dir / "decision_log.json"
    
    with patch("decision_logger.Path") as mock_path:
        mock_file_path = MagicMock()
        mock_file_path.parent = tmp_path
        mock_path.return_value = mock_file_path
        
        logger = DecisionLogger()
        logger.log_dir = log_dir
        logger.log_file = log_file
        logger.decisions = []
        return logger

# =====================================================================
# 1. _load() 例外系のテスト
# =====================================================================

def test_load_json_decode_error(temp_logger):
    """_load において JSONDecodeError が発生した時、空の決定リストに初期化されログ出力されること"""
    temp_logger.log_dir.mkdir(parents=True, exist_ok=True)
    with open(temp_logger.log_file, "w", encoding="utf-8") as f:
        f.write("invalid json")
        
    with patch("decision_logger.logger.error") as mock_log_err:
        temp_logger._load()
        assert temp_logger.decisions == []
        mock_log_err.assert_called_once()
        assert "Invalid JSON in decision log" in mock_log_err.call_args[0][0]

def test_load_permission_error(temp_logger):
    """_load において PermissionError が発生した時、空の決定リストになりログ出力されること"""
    temp_logger.log_dir.mkdir(parents=True, exist_ok=True)
    with open(temp_logger.log_file, "w", encoding="utf-8") as f:
        f.write("{}")
        
    with patch("builtins.open", side_effect=PermissionError("Permission denied")):
        with patch("decision_logger.logger.error") as mock_log_err:
            temp_logger._load()
            assert temp_logger.decisions == []
            mock_log_err.assert_called_once()
            assert "Permission denied reading decision log" in mock_log_err.call_args[0][0]

def test_load_file_not_found_error(temp_logger):
    """_load において FileNotFoundError が発生した時、空の決定リストになりログ出力されること"""
    temp_logger.log_dir.mkdir(parents=True, exist_ok=True)
    with patch.object(Path, "exists", return_value=True):
        with patch("builtins.open", side_effect=FileNotFoundError("Not found")):
            with patch("decision_logger.logger.error") as mock_log_err:
                temp_logger._load()
                assert temp_logger.decisions == []
                mock_log_err.assert_called_once()
                assert "Decision log file not found" in mock_log_err.call_args[0][0]

def test_load_general_exception(temp_logger):
    """_load において 一般例外が発生した時、空の決定リストになりログ出力されること"""
    temp_logger.log_dir.mkdir(parents=True, exist_ok=True)
    with patch.object(Path, "exists", return_value=True):
        with patch("builtins.open", side_effect=OSError("Generic error")):
            with patch("decision_logger.logger.error") as mock_log_err:
                temp_logger._load()
                assert temp_logger.decisions == []
                mock_log_err.assert_called_once()
                assert "Failed to load decision log" in mock_log_err.call_args[0][0]

def test_load_type_error(temp_logger):
    """_load において TypeError が発生した時、空の決定リストになりログ出力されること"""
    temp_logger.log_dir.mkdir(parents=True, exist_ok=True)
    with patch.object(Path, "exists", return_value=True):
        with patch("builtins.open", MagicMock()):
            with patch("json.load", return_value={"decisions": [{"invalid_key": "val"}]}):
                with patch("decision_logger.logger.error") as mock_log_err:
                    temp_logger._load()
                    assert temp_logger.decisions == []
                    mock_log_err.assert_called_once()
                    assert "Failed to load decision log" in mock_log_err.call_args[0][0]

def test_load_key_error(temp_logger):
    """_load において KeyError が発生した時、空の決定リストになりログ出力されること"""
    temp_logger.log_dir.mkdir(parents=True, exist_ok=True)
    with patch.object(Path, "exists", return_value=True):
        with patch("builtins.open", MagicMock()):
            mock_data = MagicMock()
            mock_data.get.side_effect = KeyError("decisions")
            with patch("json.load", return_value=mock_data):
                with patch("decision_logger.logger.error") as mock_log_err:
                    temp_logger._load()
                    assert temp_logger.decisions == []
                    mock_log_err.assert_called_once()
                    assert "Failed to load decision log" in mock_log_err.call_args[0][0]

# =====================================================================
# 2. _save() 例外系のテスト
# =====================================================================

def test_save_permission_error(temp_logger):
    """_save において PermissionError が発生した時、ログ出力されること"""
    temp_logger.decisions = [
        Decision("id1", 123.4, "2026-05-29", "type1", "path1", "desc1", "approve", "reason1")
    ]
    with patch("builtins.open", side_effect=PermissionError("Permission denied")):
        with patch("decision_logger.logger.error") as mock_log_err:
            temp_logger._save()
            mock_log_err.assert_called_once()
            assert "Permission denied writing decision log" in mock_log_err.call_args[0][0]

def test_save_type_error(temp_logger):
    """_save において TypeError（シリアライズ不能なオブジェクト等）が発生した時、ログ出力されること"""
    temp_logger.decisions = [
        Decision("id1", 123.4, "2026-05-29", "type1", "path1", "desc1", "approve", "reason1")
    ]
    with patch("json.dump", side_effect=TypeError("Type error")):
        with patch("decision_logger.logger.error") as mock_log_err:
            temp_logger._save()
            mock_log_err.assert_called_once()
            assert "Type error encoding decision log to JSON" in mock_log_err.call_args[0][0]

def test_save_general_exception(temp_logger):
    """_save において 一般例外が発生した時、ログ出力されること"""
    temp_logger.decisions = [
        Decision("id1", 123.4, "2026-05-29", "type1", "path1", "desc1", "approve", "reason1")
    ]
    with patch("builtins.open", side_effect=OSError("Generic write error")):
        with patch("decision_logger.logger.error") as mock_log_err:
            temp_logger._save()
            mock_log_err.assert_called_once()
            assert "Failed to save decision log" in mock_log_err.call_args[0][0]

# =====================================================================
# 3. get_similar_decisions() のテスト
# =====================================================================

def test_get_similar_decisions(temp_logger):
    """get_similar_decisions が条件（target_type, tags）でフィルタおよびソート、リミット処理されること"""
    t1 = time.time() - 100
    t2 = time.time() - 50
    t3 = time.time()
    
    d1 = Decision("id1", t1, "2026-05-29T10:00:00", "screenshot", "path1", "desc1", "approve", "reason1", tags=["color", "tempo"])
    d2 = Decision("id2", t2, "2026-05-29T10:01:00", "draft", "path2", "desc2", "reject", "reason2", tags=["tempo"])
    d3 = Decision("id3", t3, "2026-05-29T10:02:00", "screenshot", "path3", "desc3", "approve", "reason3", tags=["font"])
    
    temp_logger.decisions = [d1, d2, d3]
    
    res = temp_logger.get_similar_decisions()
    assert res == [d3, d2, d1]
    
    res = temp_logger.get_similar_decisions(target_type="screenshot")
    assert res == [d3, d1]
    
    res = temp_logger.get_similar_decisions(tags=["tempo"])
    assert res == [d2, d1]
    
    res = temp_logger.get_similar_decisions(tags=["color", "font"])
    assert res == [d3, d1]
    
    res = temp_logger.get_similar_decisions(limit=2)
    assert res == [d3, d2]

# =====================================================================
# 4. get_ai_context() のテスト
# =====================================================================

def test_get_ai_context(temp_logger):
    """get_ai_context が過去のデータがある時とない時で正しくコンテキストを生成すること"""
    assert temp_logger.get_ai_context() == ""
    
    d1 = Decision("id1", time.time(), "2026-05-29T10:00:00", "screenshot", "path1", "テスト対象1", "approve", "納得の品質")
    temp_logger.decisions = [d1]
    
    context = temp_logger.get_ai_context()
    assert "## ユーザーの過去の意思決定" in context
    assert "テスト対象1" in context
    assert "approve" in context
    assert "納得の品質" in context
    assert "上記の意思決定を尊重し、同じ質問を繰り返さないでください。" in context

# =====================================================================
# 5. get_rejection_patterns() & get_stats() のテスト
# =====================================================================

def test_rejection_patterns_and_stats(temp_logger):
    """却下パターン分析と統計情報の取得ができること"""
    stats = temp_logger.get_stats()
    assert stats["total_decisions"] == 0
    assert stats["approval_rate"] == 0
    assert stats["rejection_patterns"] == {}
    
    d1 = Decision("id1", time.time(), "2026-05-29T10:00:00", "screenshot", "path1", "desc1", "approve", "reason1", tags=["color"])
    d2 = Decision("id2", time.time(), "2026-05-29T10:01:00", "screenshot", "path2", "desc2", "reject", "reason2", tags=["color", "tempo"])
    d3 = Decision("id3", time.time(), "2026-05-29T10:02:00", "screenshot", "path3", "desc3", "reject", "reason3", tags=["tempo"])
    d4 = Decision("id4", time.time(), "2026-05-29T10:03:00", "screenshot", "path4", "desc4", "modify", "reason4", tags=["font"])
    
    temp_logger.decisions = [d1, d2, d3, d4]
    
    patterns = temp_logger.get_rejection_patterns()
    assert patterns == {"tempo": 2, "color": 1}
    
    stats = temp_logger.get_stats()
    assert stats["total_decisions"] == 4
    assert stats["approvals"] == 1
    assert stats["rejections"] == 2
    assert stats["modifications"] == 1
    assert stats["learned_by_ai"] == 0
    assert stats["approval_rate"] == 25.0
    assert stats["rejection_patterns"] == {"tempo": 2, "color": 1}

# =====================================================================
# 6. mark_as_learned() のテスト
# =====================================================================

def test_mark_as_learned(temp_logger):
    """学習済みマークが正常に設定されること"""
    d1 = Decision("id1", time.time(), "2026-05-29T10:00:00", "screenshot", "path1", "desc1", "approve", "reason1")
    temp_logger.decisions = [d1]
    
    assert temp_logger.mark_as_learned("non_existent") is False
    assert d1.learned is False
    
    assert temp_logger.mark_as_learned("id1") is True
    assert d1.learned is True
    
    with open(temp_logger.log_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["decisions"][0]["learned"] is True

# =====================================================================
# 7. get_director_preferences() & _generate_advice() のテスト
# =====================================================================

def test_director_preferences_and_advice(temp_logger):
    """監督の好み、こだわり、およびアドバイスの生成ができること"""
    # 1. データなし
    prefs = temp_logger.get_director_preferences()
    assert prefs["こだわり（却下傾向）"] == {}
    assert prefs["好み（承認傾向）"] == {}
    assert prefs["AI提案へのアドバイス"] == "まだ十分なデータがありません。"
    
    # 2. データあり (却下はあるが、承認がない場合)
    d1 = Decision("id1", time.time(), "2026-05-29T10:00:00", "screenshot", "path1", "desc1", "reject", "理由1", tags=["font"])
    temp_logger.decisions = [d1]
    prefs = temp_logger.get_director_preferences()
    assert prefs["AI提案へのアドバイス"] == "「font」に関する提案は慎重に.過去に却下されています。" or "「font」に関する提案は慎重に。過去に却下されています。"
    
    # 3. 却下はあるが、tag が None または空文字列で、top_rejection が Falsy になる場合（デッドコードのカバー）
    d_empty_tag = Decision("id2", time.time(), "2026-05-29T10:01:00", "screenshot", "path2", "desc2", "reject", "理由2", tags=[None])
    temp_logger.decisions = [d_empty_tag]
    prefs = temp_logger.get_director_preferences()
    assert prefs["AI提案へのアドバイス"] == "監督の好みを学習中です。"

    # 4. 承認はあるが、却下がない場合
    d2 = Decision("id3", time.time(), "2026-05-29T10:02:00", "screenshot", "path3", "desc3", "approve", "理由3", tags=["color", "layout"])
    d3 = Decision("id4", time.time(), "2026-05-29T10:03:00", "screenshot", "path4", "desc4", "approve", "理由4", tags=["color"])
    temp_logger.decisions = [d2, d3] # 却下履歴なしにリセット
    prefs = temp_logger.get_director_preferences()
    assert prefs["好み（承認傾向）"] == {"color": 2, "layout": 1}
    assert prefs["AI提案へのアドバイス"] == "まだ十分なデータがありません。"

# =====================================================================
# 8. sync_to_soul_narrative() & sync_to_evolution_log() のテスト
# =====================================================================

def test_sync_to_soul_narrative_no_unsynced(temp_logger):
    """未同期データがない場合、早期リターンすること"""
    res = temp_logger.sync_to_soul_narrative()
    assert res == {"synced": 0, "new_insights": []}
    
    d1 = Decision("id1", time.time(), "2026-05-29T10:00:00", "screenshot", "path1", "desc1", "approve", "reason1", learned=True)
    temp_logger.decisions = [d1]
    res = temp_logger.sync_to_soul_narrative()
    assert res == {"synced": 0, "new_insights": []}

def test_sync_to_soul_narrative_with_wagamama_import_error(temp_logger):
    """wagamama_manager がインポートできない場合でもエラーにならず、同期とインサイト生成が完了すること"""
    d_reject = Decision("id1", time.time(), "2026-05-29T10:00:00", "screenshot", "path1", "却下対象", "reject", "こだわり強い却下理由", tags=["font"], learned=False)
    d_approve = Decision("id2", time.time(), "2026-05-29T10:01:00", "screenshot", "path2", "承認対象", "approve", "良いフォント", tags=["font", "color"], learned=False)
    temp_logger.decisions = [d_reject, d_approve]
    
    evolution_log_path = temp_logger.log_dir / "evolution_log.json"
    assert not evolution_log_path.exists()
    
    with patch.dict("sys.modules", {"wagamama_manager": None}):
        res = temp_logger.sync_to_soul_narrative()
        
    assert res["synced"] == 2
    assert len(res["new_insights"]) == 2
    
    rejections_insight = next(ins for ins in res["new_insights"] if ins["source"] == "rejection_analysis")
    assert "こだわり強い却下理由" in rejections_insight["content"]
    assert rejections_insight["decision_ids"] == ["id1"]
    
    approvals_insight = next(ins for ins in res["new_insights"] if ins["source"] == "approval_analysis")
    assert "font" in approvals_insight["content"]
    assert "color" in approvals_insight["content"]
    assert approvals_insight["decision_ids"] == ["id2"]
    
    assert d_reject.learned is True
    assert d_approve.learned is True
    
    assert evolution_log_path.exists()
    with open(evolution_log_path, "r", encoding="utf-8") as f:
        evo_data = json.load(f)
        assert len(evo_data["decision_insights"]) == 2
        assert len(evo_data["entries"]) == 1
        assert evo_data["entries"][0]["summary"] == "2件の意思決定を同期"
        assert "こだわりが見えてきました" in evo_data["entries"][0]["insight"]

def test_sync_to_soul_narrative_with_existing_evolution_log(temp_logger):
    """既存の evolution_log.json がある場合、読み込んでマージ保存すること"""
    evolution_log_path = temp_logger.log_dir / "evolution_log.json"
    temp_logger.log_dir.mkdir(parents=True, exist_ok=True)
    
    initial_log = {
        "entries": [{"initial": "data"}],
        "philosophies": [],
        "decision_insights": [{"existing": "insight"}]
    }
    with open(evolution_log_path, "w", encoding="utf-8") as f:
        json.dump(initial_log, f)
        
    d1 = Decision("id1", time.time(), "2026-05-29T10:00:00", "screenshot", "path1", "desc1", "approve", "reason1", tags=["color"], learned=False)
    temp_logger.decisions = [d1]
    
    with patch.dict("sys.modules", {"wagamama_manager": None}):
        temp_logger.sync_to_soul_narrative()
        
    with open(evolution_log_path, "r", encoding="utf-8") as f:
        evo_data = json.load(f)
        assert len(evo_data["entries"]) == 2
        assert evo_data["entries"][0] == {"initial": "data"}
        assert evo_data["entries"][1]["summary"] == "1件の意思決定を同期"
        assert len(evo_data["decision_insights"]) == 2
        assert evo_data["decision_insights"][0] == {"existing": "insight"}

def test_sync_to_soul_narrative_with_wagamama_manager_integration(temp_logger):
    """wagamama_manager がインポート可能な場合、起票（Pain Detection）および解決（Resolution）が正しく連携されること"""
    mock_wagamama = MagicMock()
    
    t_now = time.time()
    d1 = Decision("id1", t_now - 10, "2026-05-29T10:00:00", "screenshot", "path1", "desc1", "reject", "フォントダメ", tags=["font"], learned=True)
    d2 = Decision("id2", t_now, "2026-05-29T10:01:00", "screenshot", "path2", "desc2", "reject", "フォントやはりダメ", tags=["font"], learned=False)
    d3 = Decision("id3", t_now + 10, "2026-05-29T10:02:00", "screenshot", "path3", "改善された画像", "approve", "フォント綺麗になった", tags=["wagamama_id:W-001"], learned=False)
    d4 = Decision("id4", t_now + 20, "2026-05-29T10:03:00", "screenshot", "path4", "レイアウト改善画像", "approve", "レイアウト納得", tags=["layout"], learned=False)
    
    temp_logger.decisions = [d1, d2, d3, d4]
    
    mock_wagamama.find_matching_story.side_effect = lambda topic, tags: "W-002" if "layout" in tags else None
    mock_wagamama.create_experience_story.return_value = "W-003"
    
    with patch.dict("sys.modules", {"wagamama_manager": MagicMock(wagamama_manager=mock_wagamama)}):
        res = temp_logger.sync_to_soul_narrative()
        
    assert res["synced"] == 3
    assert "wagamama_id:W-003" in d2.tags
    mock_wagamama.create_experience_story.assert_called_once_with(
        user_voice="フォントやはりダメ",
        detected_by="decision_logger",
        feature_id="font"
    )
    
    mock_wagamama.resolve_story.assert_any_call(
        wagamama_id="W-001",
        solution_description="フォント綺麗になった",
        emotion="満足"
    )
    
    mock_wagamama.resolve_story.assert_any_call(
        wagamama_id="W-002",
        solution_description="レイアウト納得",
        emotion="満足"
    )

def test_sync_to_evolution_log_alias(temp_logger):
    """sync_to_evolution_log エエイリアスが sync_to_soul_narrative に正しく委譲すること"""
    with patch.object(temp_logger, "sync_to_soul_narrative", return_value={"mock": "result"}) as mock_sync:
        res = temp_logger.sync_to_evolution_log()
        assert res == {"mock": "result"}
        mock_sync.assert_called_once()

# =====================================================================
# 9. record_decision() カバレッジのテスト
# =====================================================================

def test_record_decision(temp_logger):
    """record_decision() が意思決定を記録し、正しく動作して ID を返すこと"""
    decision_id = temp_logger.record_decision(
        target_type="screenshot",
        target_path="path/to/shot.png",
        target_description="テスト画像",
        decision="approve",
        reason="良好なレイアウト",
        tags=["レイアウト"]
    )
    
    assert decision_id is not None
    assert len(temp_logger.decisions) == 1
    assert temp_logger.decisions[0].decision_id == decision_id
    assert temp_logger.decisions[0].decision == "approve"
    assert temp_logger.decisions[0].reason == "良好なレイアウト"
    assert temp_logger.decisions[0].tags == ["レイアウト"]
    
    assert temp_logger.log_file.exists()
    with open(temp_logger.log_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["decisions"][0]["decision_id"] == decision_id

# =====================================================================
# 10. エッジケース・カバレッジ用テストケース (312, 319-320, 338, 405)
# =====================================================================

def test_sync_to_soul_narrative_with_missing_insights_key(temp_logger):
    """evolution_log.json に decision_insights キーが無い場合、初期化されて同期されること (405)"""
    evolution_log_path = temp_logger.log_dir / "evolution_log.json"
    temp_logger.log_dir.mkdir(parents=True, exist_ok=True)
    
    initial_log = {
        "entries": [],
        "philosophies": []
    }
    with open(evolution_log_path, "w", encoding="utf-8") as f:
        json.dump(initial_log, f)
        
    d1 = Decision("id1", time.time(), "2026-05-29T10:00:00", "screenshot", "path1", "desc1", "approve", "reason1", tags=["color"], learned=False)
    temp_logger.decisions = [d1]
    
    with patch.dict("sys.modules", {"wagamama_manager": None}):
        temp_logger.sync_to_soul_narrative()
        
    with open(evolution_log_path, "r", encoding="utf-8") as f:
        evo_data = json.load(f)
        assert "decision_insights" in evo_data
        assert len(evo_data["decision_insights"]) == 1

def test_sync_to_soul_narrative_with_value_error_fallback(temp_logger):
    """list.index が ValueError を返した場合、search_slice が self.decisions にフォールバックすること (319-320)"""
    mock_wagamama = MagicMock()
    
    t_now = time.time()
    d1 = Decision("id1", t_now - 10, "2026-05-29T10:00:00", "screenshot", "path1", "desc1", "reject", "フォントダメ", tags=["font"], learned=True)
    d2 = Decision("id2", t_now, "2026-05-29T10:01:00", "screenshot", "path2", "desc2", "reject", "フォントやはりダメ", tags=["font"], learned=False)
    
    class CustomList(list):
        def index(self, value, *args, **kwargs):
            raise ValueError("Mock value error")
            
    temp_logger.decisions = CustomList([d1, d2])
    
    mock_wagamama.find_matching_story.return_value = None
    mock_wagamama.create_experience_story.return_value = "W-003"
    
    with patch.dict("sys.modules", {"wagamama_manager": MagicMock(wagamama_manager=mock_wagamama)}):
        res = temp_logger.sync_to_soul_narrative()
            
    assert res["synced"] == 1
    assert "wagamama_id:W-003" in d2.tags

def test_sync_to_soul_narrative_with_reject_no_tags(temp_logger):
    """起票（Pain Detection）時に tags が None の場合、空リストに初期化され処理されること (312, 338)"""
    mock_wagamama = MagicMock()
    
    t_now = time.time()
    d1 = Decision("id1", t_now - 10, "2026-05-29T10:00:00", "screenshot", "path1", "desc1", "reject", "フォントダメ", tags=["temp_tag"], learned=True)
    d2 = Decision("id2", t_now, "2026-05-29T10:01:00", "screenshot", "path2", "desc2", "reject", "フォントやはりダメ", tags=["wagamama_id:old_story", "temp_tag"], learned=False)
    temp_logger.decisions = [d1, d2]
    
    def side_effect_find(*args, **kwargs):
        d2.tags = None
        return None
        
    mock_wagamama.find_matching_story.side_effect = side_effect_find
    mock_wagamama.create_experience_story.return_value = "W-003"
    
    with patch.dict("sys.modules", {"wagamama_manager": MagicMock(wagamama_manager=mock_wagamama)}):
        res = temp_logger.sync_to_soul_narrative()
        
    assert res["synced"] == 1
    assert d2.tags == ["wagamama_id:W-003"]
