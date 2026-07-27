"""
M2.5: Decision Logger テスト — 18テスト

decision_logger.py (168 stmts, 124 missed) のカバレッジ改善。
Decision, DecisionLogger の全メソッドを網羅。

外部依存: ファイルI/O → tmpdir で代替。Gemini API不要。
"""

import pytest
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from decision_logger import Decision, DecisionLogger


@pytest.fixture
def tmp_logger(tmp_path):
    """一時ディレクトリを使用するDecisionLogger"""
    logger = DecisionLogger.__new__(DecisionLogger)
    logger.log_dir = tmp_path
    logger.log_file = tmp_path / "decision_log.json"
    logger.decisions = []
    return logger


# ============================================================
# DecisionLogger テスト
# ============================================================

class TestDecisionLogger:
    """DecisionLogger: 意思決定記録・分析"""

    def test_record_decision_returns_id(self, tmp_logger):
        """record_decision: IDが返る"""
        dec_id = tmp_logger.record_decision(
            target_type="screenshot",
            target_path="/path/to/file",
            target_description="テスト画像",
            decision="approve",
            reason="問題なし",
            tags=["色調整"],
        )
        assert isinstance(dec_id, str)
        assert len(dec_id) > 0

    def test_record_decision_saves_to_file(self, tmp_logger):
        """record_decision: ファイルに保存される"""
        tmp_logger.record_decision(
            target_type="draft",
            target_path="/path",
            target_description="ドラフト",
            decision="reject",
            reason="色が違う",
        )
        assert tmp_logger.log_file.exists()
        data = json.loads(tmp_logger.log_file.read_text(encoding="utf-8"))
        assert len(data["decisions"]) == 1

    def test_record_multiple_decisions(self, tmp_logger):
        """複数記録: decisionsリストに蓄積"""
        for i in range(5):
            tmp_logger.record_decision(
                target_type="screenshot",
                target_path=f"/path/{i}",
                target_description=f"テスト{i}",
                decision="approve" if i % 2 == 0 else "reject",
                reason=f"理由{i}",
                tags=[f"tag{i}"],
            )
        assert len(tmp_logger.decisions) == 5

    def test_get_similar_decisions_by_type(self, tmp_logger):
        """get_similar_decisions: target_typeでフィルタ"""
        tmp_logger.record_decision("screenshot", "/p", "s", "approve", "ok")
        tmp_logger.record_decision("draft", "/p", "d", "reject", "ng")
        tmp_logger.record_decision("screenshot", "/p2", "s2", "modify", "m")

        result = tmp_logger.get_similar_decisions(target_type="screenshot")
        assert len(result) == 2

    def test_get_similar_decisions_by_tags(self, tmp_logger):
        """get_similar_decisions: tagsでフィルタ"""
        tmp_logger.record_decision("screenshot", "/p", "s", "approve", "ok", tags=["色調整"])
        tmp_logger.record_decision("draft", "/p", "d", "reject", "ng", tags=["テンポ"])
        tmp_logger.record_decision("screenshot", "/p2", "s2", "approve", "ok", tags=["色調整", "字幕"])

        result = tmp_logger.get_similar_decisions(tags=["色調整"])
        assert len(result) == 2

    def test_get_similar_decisions_limit(self, tmp_logger):
        """get_similar_decisions: limit制限"""
        for i in range(10):
            tmp_logger.record_decision("screenshot", f"/p{i}", f"s{i}", "approve", f"ok{i}")
        result = tmp_logger.get_similar_decisions(limit=3)
        assert len(result) == 3

    def test_get_ai_context_empty(self, tmp_logger):
        """get_ai_context: 空の場合は空文字"""
        ctx = tmp_logger.get_ai_context()
        assert ctx == ""

    def test_get_ai_context_with_decisions(self, tmp_logger):
        """get_ai_context: 意思決定ありでコンテキスト生成"""
        tmp_logger.record_decision("screenshot", "/p", "テスト", "approve", "良い")
        ctx = tmp_logger.get_ai_context()
        assert "ユーザーの過去の意思決定" in ctx
        assert "approve" in ctx

    def test_get_rejection_patterns(self, tmp_logger):
        """get_rejection_patterns: 却下パターン分析"""
        tmp_logger.record_decision("s", "/p", "d", "reject", "r", tags=["色調整"])
        tmp_logger.record_decision("s", "/p", "d", "reject", "r", tags=["色調整", "テンポ"])
        tmp_logger.record_decision("s", "/p", "d", "approve", "r", tags=["字幕"])

        patterns = tmp_logger.get_rejection_patterns()
        assert patterns["色調整"] == 2
        assert patterns["テンポ"] == 1
        assert "字幕" not in patterns

    def test_mark_as_learned(self, tmp_logger):
        """mark_as_learned: learned=True"""
        dec_id = tmp_logger.record_decision("s", "/p", "d", "approve", "r")
        result = tmp_logger.mark_as_learned(dec_id)
        assert result is True
        assert tmp_logger.decisions[0].learned is True

    def test_mark_as_learned_not_found(self, tmp_logger):
        """mark_as_learned: 存在しないID → False"""
        result = tmp_logger.mark_as_learned("nonexistent")
        assert result is False

    def test_get_stats(self, tmp_logger):
        """get_stats: 統計情報"""
        tmp_logger.record_decision("s", "/p", "d", "approve", "r")
        tmp_logger.record_decision("s", "/p", "d", "reject", "r")
        tmp_logger.record_decision("s", "/p", "d", "modify", "r")

        stats = tmp_logger.get_stats()
        assert stats["total_decisions"] == 3
        assert stats["approvals"] == 1
        assert stats["rejections"] == 1
        assert stats["modifications"] == 1
        assert stats["approval_rate"] == pytest.approx(33.3, abs=0.1)

    def test_get_stats_empty(self, tmp_logger):
        """get_stats: 空の場合"""
        stats = tmp_logger.get_stats()
        assert stats["total_decisions"] == 0
        assert stats["approval_rate"] == 0

    def test_load_from_file(self, tmp_path):
        """_load: ファイルからの読み込み"""
        log_data = {
            "decisions": [
                {
                    "decision_id": "test001",
                    "timestamp": 1000.0,
                    "iso_time": "2026-01-01T00:00:00",
                    "target_type": "screenshot",
                    "target_path": "/test",
                    "target_description": "テスト",
                    "decision": "approve",
                    "reason": "OK",
                    "scene_info": {},
                    "mood_settings": {},
                    "tags": [],
                    "learned": False,
                }
            ]
        }
        log_file = tmp_path / "decision_log.json"
        log_file.write_text(json.dumps(log_data), encoding="utf-8")

        logger = DecisionLogger.__new__(DecisionLogger)
        logger.log_dir = tmp_path
        logger.log_file = log_file
        logger.decisions = []
        logger._load()
        assert len(logger.decisions) == 1
        assert logger.decisions[0].decision_id == "test001"

    def test_load_corrupt_file(self, tmp_path):
        """_load: 破損ファイル → 空リスト"""
        log_file = tmp_path / "decision_log.json"
        log_file.write_text("invalid json{{{", encoding="utf-8")

        logger = DecisionLogger.__new__(DecisionLogger)
        logger.log_dir = tmp_path
        logger.log_file = log_file
        logger.decisions = []
        logger._load()
        assert logger.decisions == []

    def test_get_director_preferences(self, tmp_logger):
        """get_director_preferences: 監督プロファイル"""
        tmp_logger.record_decision("s", "/p", "d", "approve", "r", tags=["明るい"])
        tmp_logger.record_decision("s", "/p", "d", "reject", "r", tags=["暗い"])

        prefs = tmp_logger.get_director_preferences()
        assert "こだわり（却下傾向）" in prefs
        assert "好み（承認傾向）" in prefs
        assert "AI提案へのアドバイス" in prefs

    def test_generate_advice_empty(self, tmp_logger):
        """_generate_advice: データなし"""
        advice = tmp_logger._generate_advice()
        assert "まだ十分なデータがありません" in advice

    def test_generate_advice_with_rejections(self, tmp_logger):
        """_generate_advice: 却下パターンありでアドバイス生成"""
        tmp_logger.record_decision("s", "/p", "d", "reject", "r", tags=["テンポ"])
        advice = tmp_logger._generate_advice()
        assert "テンポ" in advice

    def test_load_exceptions(self, tmp_path):
        """_load: FileNotFoundError, PermissionError, General Exception"""
        # FileNotFoundError
        logger = DecisionLogger.__new__(DecisionLogger)
        logger.log_dir = tmp_path
        logger.log_file = tmp_path / "nonexistent_file.json"
        logger.decisions = []
        
        # pathlib.Path.exists が True を返すようにモックする
        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", side_effect=FileNotFoundError("file not found")):
                with patch("decision_logger.logger.error") as mock_log:
                    logger._load()
                    assert logger.decisions == []
                    mock_log.assert_called_with("Decision log file not found: file not found")

            # PermissionError
            with patch("builtins.open", side_effect=PermissionError("permission denied")):
                with patch("decision_logger.logger.error") as mock_log:
                    logger._load()
                    assert logger.decisions == []
                    mock_log.assert_called_with("Permission denied reading decision log: permission denied")

            # Generic Exception
            with patch("builtins.open", side_effect=RuntimeError("unknown error")):
                with patch("decision_logger.logger.error") as mock_log:
                    logger._load()
                    assert logger.decisions == []
                    mock_log.assert_called_with("Failed to load decision log: unknown error")

    def test_save_exceptions(self, tmp_logger):
        """_save: PermissionError, TypeError, General Exception"""
        tmp_logger.record_decision("s", "/p", "d", "approve", "r")
        
        # PermissionError
        with patch("builtins.open", side_effect=PermissionError("permission denied")):
            with patch("decision_logger.logger.error") as mock_log:
                tmp_logger._save()
                mock_log.assert_called_with("Permission denied writing decision log: permission denied")

        # TypeError (for json.dump)
        with patch("json.dump", side_effect=TypeError("type error")):
            with patch("decision_logger.logger.error") as mock_log:
                tmp_logger._save()
                mock_log.assert_called_with("Type error encoding decision log to JSON: type error")

        # Generic Exception
        with patch("builtins.open", side_effect=RuntimeError("unknown error")):
            with patch("decision_logger.logger.error") as mock_log:
                tmp_logger._save()
                mock_log.assert_called_with("Failed to save decision log: unknown error")

    def test_sync_to_soul_narrative_not_exists(self, tmp_path):
        """sync_to_soul_narrative: evolution_log.jsonが存在しない場合"""
        logger = DecisionLogger.__new__(DecisionLogger)
        logger.log_dir = tmp_path
        logger.log_file = tmp_path / "decision_log.json"
        logger.decisions = []
        logger.record_decision("s", "/p", "d", "approve", "r", tags=["明るい"])
        
        # sync_to_soul_narrativeを実行
        result = logger.sync_to_soul_narrative()
        assert result["synced"] == 1
        assert len(result["new_insights"]) == 1
        assert logger.decisions[0].learned is True
        
        # evolution_log.jsonが生成されたことを確認
        evo_file = tmp_path / "evolution_log.json"
        assert evo_file.exists()
        evo_data = json.loads(evo_file.read_text(encoding="utf-8"))
        assert len(evo_data["entries"]) == 1
        assert len(evo_data["decision_insights"]) == 1

    def test_sync_to_soul_narrative_already_learned(self, tmp_path):
        """sync_to_soul_narrative: すべて学習済みの場合"""
        logger = DecisionLogger.__new__(DecisionLogger)
        logger.log_dir = tmp_path
        logger.log_file = tmp_path / "decision_log.json"
        logger.decisions = []
        logger.record_decision("s", "/p", "d", "approve", "r", tags=["明るい"])
        logger.decisions[0].learned = True
        
        result = logger.sync_to_soul_narrative()
        assert result["synced"] == 0
        assert result["new_insights"] == []

    def test_sync_to_soul_narrative_with_wagamama_integration(self, tmp_path):
        """sync_to_soul_narrative: wagamama_managerとの連携テスト"""
        logger = DecisionLogger.__new__(DecisionLogger)
        logger.log_dir = tmp_path
        logger.log_file = tmp_path / "decision_log.json"
        logger.decisions = []
        
        # 却下と承認の連続でストーリー起票/クローズを検証する
        # 同一タグでの却下が2回連続
        logger.record_decision("screenshot", "/p1", "desc1", "reject", "理由1", tags=["色調整"])
        logger.record_decision("screenshot", "/p2", "desc2", "reject", "理由2", tags=["色調整"])
        
        # 承認
        logger.record_decision("screenshot", "/p3", "desc3", "approve", "理由3", tags=["色調整"])
        
        # wagamama_manager モジュール全体を mock_wagamama に差し替える
        import sys
        mock_wagamama_module = MagicMock()
        mock_wagamama = mock_wagamama_module.wagamama_manager
        
        mock_wagamama.find_matching_story.side_effect = [None, "W-001"]
        mock_wagamama.create_experience_story.return_value = "W-001"
        
        original_module = sys.modules.get("wagamama_manager")
        sys.modules["wagamama_manager"] = mock_wagamama_module
        
        try:
            result = logger.sync_to_soul_narrative()
            assert result["synced"] == 3
            assert mock_wagamama.create_experience_story.called
            assert mock_wagamama.resolve_story.called
        finally:
            if original_module is not None:
                sys.modules["wagamama_manager"] = original_module
            else:
                sys.modules.pop("wagamama_manager", None)

    def test_sync_to_soul_narrative_import_error(self, tmp_path):
        """sync_to_soul_narrative: wagamama_managerのインポートエラー発生時"""
        logger = DecisionLogger.__new__(DecisionLogger)
        logger.log_dir = tmp_path
        logger.log_file = tmp_path / "decision_log.json"
        logger.decisions = []
        logger.record_decision("screenshot", "/p1", "desc1", "reject", "理由1", tags=["色調整"])
        logger.record_decision("screenshot", "/p2", "desc2", "reject", "理由2", tags=["色調整"])
        
        # wagamama_manager のインポートで ImportError を発生させる
        with patch("builtins.__import__", side_effect=ImportError("mock import error")):
            result = logger.sync_to_soul_narrative()
            assert result["synced"] == 2

    def test_generate_insight_summary_combinations(self, tmp_logger):
        """_generate_insight_summary: 承認のみ、却下のみ、両方の組み合わせ"""
        assert tmp_logger._generate_insight_summary([]) == "新しい意思決定が記録されました。"
        
        # approvals only
        tmp_logger.record_decision("s", "/p", "d", "approve", "r")
        assert "承認された1件の判断は" in tmp_logger._generate_insight_summary(tmp_logger.decisions)
        
        # rejections only
        tmp_logger.decisions = []
        tmp_logger.record_decision("s", "/p", "d", "reject", "r")
        assert "却下された1件の判断から" in tmp_logger._generate_insight_summary(tmp_logger.decisions)

    def test_generate_advice_fallback_patterns(self, tmp_logger):
        """_generate_advice: 却下パターンはあるがtop_rejectionがない場合など"""
        with patch.object(tmp_logger, "get_rejection_patterns", return_value={"": 1}):
            assert tmp_logger._generate_advice() == "監督の好みを学習中です。"

    def test_sync_to_evolution_log_alias(self, tmp_path):
        """sync_to_evolution_log: sync_to_soul_narrative へのエイリアス"""
        logger = DecisionLogger.__new__(DecisionLogger)
        logger.log_dir = tmp_path
        logger.log_file = tmp_path / "decision_log.json"
        logger.decisions = []
        logger.record_decision("s", "/p", "d", "approve", "r", tags=["明るい"])
        
        result = logger.sync_to_evolution_log()
        assert result["synced"] == 1

    def test_sync_to_soul_narrative_already_exists(self, tmp_path):
        """sync_to_soul_narrative: evolution_log.jsonが既に存在する場合"""
        logger = DecisionLogger.__new__(DecisionLogger)
        logger.log_dir = tmp_path
        logger.log_file = tmp_path / "decision_log.json"
        logger.decisions = []
        logger.record_decision("s", "/p", "d", "approve", "r", tags=["明るい"])
        
        evo_file = tmp_path / "evolution_log.json"
        evo_file.write_text(json.dumps({"entries": [], "philosophies": []}), encoding="utf-8")
        
        result = logger.sync_to_soul_narrative()
        assert result["synced"] == 1
        
        evo_data = json.loads(evo_file.read_text(encoding="utf-8"))
        assert len(evo_data["entries"]) == 1
        assert "decision_insights" in evo_data

    def test_sync_to_soul_narrative_wagamama_id_tag_skip(self, tmp_path):
        """sync_to_soul_narrative: wagamama_id:タグをスキップする分岐のテスト"""
        logger = DecisionLogger.__new__(DecisionLogger)
        logger.log_dir = tmp_path
        logger.log_file = tmp_path / "decision_log.json"
        logger.decisions = []
        
        logger.record_decision("screenshot", "/p1", "desc1", "reject", "理由1", tags=["wagamama_id:W-001"])
        logger.record_decision("screenshot", "/p2", "desc2", "reject", "理由2", tags=["wagamama_id:W-001"])
        
        import sys
        mock_wagamama_module = MagicMock()
        mock_wagamama = mock_wagamama_module.wagamama_manager
        
        original_module = sys.modules.get("wagamama_manager")
        sys.modules["wagamama_manager"] = mock_wagamama_module
        
        try:
            result = logger.sync_to_soul_narrative()
            assert result["synced"] == 2
            assert not mock_wagamama.create_experience_story.called
        finally:
            if original_module is not None:
                sys.modules["wagamama_manager"] = original_module
            else:
                sys.modules.pop("wagamama_manager", None)

    def test_sync_to_soul_narrative_value_error(self, tmp_path):
        """sync_to_soul_narrative: index(dec)でValueErrorが発生した場合のフォールバック"""
        logger = DecisionLogger.__new__(DecisionLogger)
        logger.log_dir = tmp_path
        logger.log_file = tmp_path / "decision_log.json"
        
        class MockableList(list):
            def index(self, *args, **kwargs):
                raise ValueError("mock value error")
                
        logger.decisions = MockableList()
        logger.record_decision("screenshot", "/p1", "desc1", "reject", "理由1", tags=["色調整"])
        logger.record_decision("screenshot", "/p2", "desc2", "reject", "理由2", tags=["色調整"])
        
        import sys
        mock_wagamama_module = MagicMock()
        mock_wagamama = mock_wagamama_module.wagamama_manager
        mock_wagamama.find_matching_story.return_value = None
        
        original_module = sys.modules.get("wagamama_manager")
        sys.modules["wagamama_manager"] = mock_wagamama_module
        try:
            result = logger.sync_to_soul_narrative()
            assert result["synced"] == 2
            assert mock_wagamama.create_experience_story.called
        finally:
            if original_module is not None:
                sys.modules["wagamama_manager"] = original_module
            else:
                sys.modules.pop("wagamama_manager", None)

    def test_sync_to_soul_narrative_none_tags(self, tmp_path):
        """sync_to_soul_narrative: dec.tags が None の場合のテスト"""
        logger = DecisionLogger.__new__(DecisionLogger)
        logger.log_dir = tmp_path
        logger.log_file = tmp_path / "decision_log.json"
        logger.decisions = []
        
        logger.record_decision("screenshot", "/p1", "desc1", "reject", "理由1", tags=["色調整"])
        logger.record_decision("screenshot", "/p2", "desc2", "reject", "理由2", tags=["色調整"])
        
        import sys
        mock_wagamama_module = MagicMock()
        mock_wagamama = mock_wagamama_module.wagamama_manager
        mock_wagamama.find_matching_story.return_value = None
        
        def mock_create(*args, **kwargs):
            logger.decisions[1].tags = None
            return "W-001"
        mock_wagamama.create_experience_story.side_effect = mock_create
        
        original_module = sys.modules.get("wagamama_manager")
        sys.modules["wagamama_manager"] = mock_wagamama_module
        try:
            result = logger.sync_to_soul_narrative()
            assert result["synced"] == 2
            assert logger.decisions[1].tags == ["wagamama_id:W-001"]
        finally:
            if original_module is not None:
                sys.modules["wagamama_manager"] = original_module
            else:
                sys.modules.pop("wagamama_manager", None)

    def test_sync_to_soul_narrative_approve_with_wagamama_id_tag(self, tmp_path):
        """sync_to_soul_narrative: 承認時にwagamama_idタグからIDを抽出して解決する"""
        logger = DecisionLogger.__new__(DecisionLogger)
        logger.log_dir = tmp_path
        logger.log_file = tmp_path / "decision_log.json"
        logger.decisions = []
        
        logger.record_decision("screenshot", "/p1", "desc1", "approve", "理由1", tags=["wagamama_id:W-100"])
        
        import sys
        mock_wagamama_module = MagicMock()
        mock_wagamama = mock_wagamama_module.wagamama_manager
        
        original_module = sys.modules.get("wagamama_manager")
        sys.modules["wagamama_manager"] = mock_wagamama_module
        try:
            result = logger.sync_to_soul_narrative()
            assert result["synced"] == 1
            mock_wagamama.resolve_story.assert_called_with(
                wagamama_id="W-100",
                solution_description="理由1",
                emotion="満足"
            )
        finally:
            if original_module is not None:
                sys.modules["wagamama_manager"] = original_module
            else:
                sys.modules.pop("wagamama_manager", None)

    def test_init_creates_directory_and_loads_file(self, tmp_path):
        """__init__: インスタンス初期化時にディレクトリが作成され、ファイルが読み込まれる"""
        import decision_logger
        original_file = decision_logger.__file__
        dummy_file = tmp_path / "decision_logger.py"
        decision_logger.__file__ = str(dummy_file)
        
        try:
            logger = DecisionLogger()
            assert logger.log_dir.exists()
            assert logger.log_dir.name == "branding"
            assert logger.decisions == []
        finally:
            decision_logger.__file__ = original_file

    def test_init_with_existing_file(self, tmp_path):
        """__init__: すでに decision_log.json が存在する場合に正しく読み込まれること"""
        import decision_logger
        original_file = decision_logger.__file__
        dummy_file = tmp_path / "decision_logger.py"
        decision_logger.__file__ = str(dummy_file)
        
        log_dir = tmp_path / "branding"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "decision_log.json"
        
        log_data = {
            "decisions": [
                {
                    "decision_id": "init001",
                    "timestamp": 1234.5,
                    "iso_time": "2026-05-26T00:00:00",
                    "target_type": "screenshot",
                    "target_path": "/test/path",
                    "target_description": "初期テスト",
                    "decision": "approve",
                    "reason": "初期OK",
                    "scene_info": {},
                    "mood_settings": {},
                    "tags": [],
                    "learned": False,
                }
            ]
        }
        log_file.write_text(json.dumps(log_data), encoding="utf-8")
        
        try:
            logger = DecisionLogger()
            assert len(logger.decisions) == 1
            assert logger.decisions[0].decision_id == "init001"
        finally:
            decision_logger.__file__ = original_file

