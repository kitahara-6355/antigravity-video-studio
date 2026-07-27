"""
M2.5: Learning Loop テスト — 18テスト

learning_loop.py (182 stmts, 97 missed) のカバレッジ改善。
LearningLoop の全メソッドを網羅: record_decision, proposal, pattern learning, preferences。

外部依存: ファイルI/O → tmp_path で代替。
"""

import pytest
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from learning_loop import (
    LearningLoop,
    ApprovalType,
    Decision,
    PermanentProposal,
    PreferencePattern,
    record_approval,
    record_rejection,
    get_council_agenda,
)


@pytest.fixture
def fresh_loop(tmp_path):
    """一時ディレクトリを使用するLearningLoop"""
    loop = LearningLoop.__new__(LearningLoop)
    loop.decisions_path = tmp_path / "decisions.json"
    loop.proposals_path = tmp_path / "future_council_queue.json"
    loop.patterns_path = tmp_path / "preference_patterns.json"
    loop.decisions = []
    loop.proposals = []
    loop.patterns = {}
    return loop


# ============================================================
# LearningLoop テスト
# ============================================================

class TestLearningLoop:
    """LearningLoop: 学習ループシステム"""

    def test_record_decision_returns_decision(self, fresh_loop):
        """record_decision: Decisionが返る"""
        dec = fresh_loop.record_decision(
            decision_type="telop",
            content={"text": "テスト"},
            decision="approved",
            approval_type=ApprovalType.THIS_TIME_ONLY,
            reason="テスト理由",
        )
        assert isinstance(dec, Decision)
        assert dec.decision == "approved"
        assert dec.type == "telop"

    def test_record_decision_saves_to_file(self, fresh_loop):
        """record_decision: ファイルに保存される"""
        fresh_loop.record_decision(
            decision_type="image",
            content={"text": "画像"},
            decision="rejected",
            approval_type=ApprovalType.THIS_TIME_ONLY,
        )
        assert fresh_loop.decisions_path.exists()

    def test_record_decision_invalid_decision_value(self, fresh_loop):
        """record_decision: 不正なdecision値の場合にValueErrorを投げること"""
        with pytest.raises(ValueError) as excinfo:
            fresh_loop.record_decision(
                decision_type="telop",
                content={"text": "テスト"},
                decision="invalid_val",
                approval_type=ApprovalType.THIS_TIME_ONLY,
            )
        assert "Invalid decision value: invalid_val" in str(excinfo.value)

    def test_record_decision_invalid_approval_type(self, fresh_loop):
        """record_decision: 不正なapproval_typeの場合にTypeErrorを投げること"""
        with pytest.raises(TypeError) as excinfo:
            fresh_loop.record_decision(
                decision_type="telop",
                content={"text": "テスト"},
                decision="approved",
                approval_type="not_an_approval_type",  # type: ignore
            )
        assert "approval_type must be an instance of ApprovalType" in str(excinfo.value)

    def test_record_permanent_creates_proposal(self, fresh_loop):
        """record_decision: PERMANENT → 提案作成"""
        fresh_loop.record_decision(
            decision_type="telop",
            content={"text": "テロップ"},
            decision="approved",
            approval_type=ApprovalType.PERMANENT,
            tags=["style"],
        )
        assert len(fresh_loop.proposals) == 1
        assert fresh_loop.proposals[0].proposal_type == "style_preference"

    def test_infer_proposal_type_style(self, fresh_loop):
        """_infer_proposal_type: styleタグ → style_preference"""
        dec = Decision(id="d1", timestamp="", type="telop",
                       content={}, decision="approved",
                       approval_type="permanent", tags=["style"])
        assert fresh_loop._infer_proposal_type(dec) == "style_preference"

    def test_infer_proposal_type_position(self, fresh_loop):
        """_infer_proposal_type: positionタグ → content_policy"""
        dec = Decision(id="d1", timestamp="", type="telop",
                       content={}, decision="approved",
                       approval_type="permanent", tags=["position"])
        assert fresh_loop._infer_proposal_type(dec) == "content_policy"

    def test_infer_proposal_type_default(self, fresh_loop):
        """_infer_proposal_type: その他 → keyword"""
        dec = Decision(id="d1", timestamp="", type="telop",
                       content={}, decision="approved",
                       approval_type="permanent", tags=["unknown"])
        assert fresh_loop._infer_proposal_type(dec) == "keyword"

    def test_generate_proposal_text_approved(self, fresh_loop):
        """_generate_proposal_text: approved"""
        dec = Decision(id="d1", timestamp="", type="telop",
                       content={"text": "テスト"}, decision="approved",
                       approval_type="permanent")
        text = fresh_loop._generate_proposal_text(dec)
        assert "標準化" in text

    def test_generate_proposal_text_rejected(self, fresh_loop):
        """_generate_proposal_text: rejected"""
        dec = Decision(id="d1", timestamp="", type="telop",
                       content={"text": "テスト"}, decision="rejected",
                       approval_type="permanent")
        text = fresh_loop._generate_proposal_text(dec)
        assert "避ける" in text

    def test_learn_pattern_approved(self, fresh_loop):
        """_learn_pattern: approved → preferred追加"""
        fresh_loop.record_decision(
            decision_type="telop",
            content={"text": "明るい色"},
            decision="approved",
            approval_type=ApprovalType.THIS_TIME_ONLY,
            tags=["color"],
        )
        assert "color" in fresh_loop.patterns
        assert "明るい色" in fresh_loop.patterns["color"].preferred

    def test_learn_pattern_rejected(self, fresh_loop):
        """_learn_pattern: rejected → avoided追加"""
        fresh_loop.record_decision(
            decision_type="telop",
            content={"text": "暗い色"},
            decision="rejected",
            approval_type=ApprovalType.THIS_TIME_ONLY,
            tags=["color"],
        )
        assert "暗い色" in fresh_loop.patterns["color"].avoided

    def test_learn_pattern_confidence_grows(self, fresh_loop):
        """_learn_pattern: sample_count増加で信頼度上昇"""
        for i in range(10):
            fresh_loop.record_decision(
                decision_type="telop",
                content={"text": f"テスト{i}"},
                decision="approved",
                approval_type=ApprovalType.THIS_TIME_ONLY,
                tags=["color"],
            )
        assert fresh_loop.patterns["color"].confidence == 1.0
        assert fresh_loop.patterns["color"].sample_count == 10

    def test_get_pending_proposals(self, fresh_loop):
        """get_pending_proposals: 保留中の提案"""
        fresh_loop.record_decision(
            decision_type="telop",
            content={"text": "テスト"},
            decision="approved",
            approval_type=ApprovalType.PERMANENT,
        )
        pending = fresh_loop.get_pending_proposals()
        assert len(pending) == 1
        assert pending[0]["status"] == "pending"

    def test_review_proposal_approve(self, fresh_loop):
        """review_proposal: 承認"""
        fresh_loop.record_decision(
            decision_type="telop",
            content={"text": "テスト"},
            decision="approved",
            approval_type=ApprovalType.PERMANENT,
        )
        prop_id = fresh_loop.proposals[0].id
        result = fresh_loop.review_proposal(prop_id, approved=True)
        assert result is True
        assert fresh_loop.proposals[0].status == "approved"

    def test_review_proposal_reject(self, fresh_loop):
        """review_proposal: 却下"""
        fresh_loop.record_decision(
            decision_type="telop",
            content={"text": "テスト"},
            decision="approved",
            approval_type=ApprovalType.PERMANENT,
        )
        prop_id = fresh_loop.proposals[0].id
        result = fresh_loop.review_proposal(prop_id, approved=False)
        assert result is True
        assert fresh_loop.proposals[0].status == "rejected"

    def test_review_proposal_not_found(self, fresh_loop):
        """review_proposal: 存在しないID → False"""
        result = fresh_loop.review_proposal("nonexistent", approved=True)
        assert result is False

    def test_get_preferences_all(self, fresh_loop):
        """get_preferences: 全カテゴリ"""
        fresh_loop.record_decision(
            decision_type="telop",
            content={"text": "テスト"},
            decision="approved",
            approval_type=ApprovalType.THIS_TIME_ONLY,
            tags=["color"],
        )
        prefs = fresh_loop.get_preferences()
        assert "color" in prefs

    def test_get_preferences_by_category(self, fresh_loop):
        """get_preferences: 特定カテゴリ"""
        fresh_loop.record_decision(
            decision_type="telop",
            content={"text": "テスト"},
            decision="approved",
            approval_type=ApprovalType.THIS_TIME_ONLY,
            tags=["color"],
        )
        prefs = fresh_loop.get_preferences("color")
        assert prefs["category"] == "color"
        assert prefs.get("preferred") is not None

    def test_apply_preferences(self, fresh_loop):
        """apply_preferences: 好みを提案に適用"""
        fresh_loop.patterns["style"] = PreferencePattern(
            category="style",
            preferred=["bold", "clean"],
            avoided=["messy"],
            confidence=0.8,
            sample_count=5,
        )
        proposal = {"style": "default"}
        result = fresh_loop.apply_preferences(proposal, "style")
        assert "recommended_styles" in result
        assert "avoid_styles" in result

    def test_env_var_data_dir(self, monkeypatch, tmp_path):
        """LEARNING_LOOP_DATA_DIR 環境変数が設定されている場合、そのディレクトリを使用する"""
        custom_dir = tmp_path / "custom_branding"
        monkeypatch.setenv("LEARNING_LOOP_DATA_DIR", str(custom_dir))
        
        loop = LearningLoop()
        assert loop.decisions_path.parent == custom_dir
        assert loop.proposals_path.parent == custom_dir
        assert loop.patterns_path.parent == custom_dir

    def test_save_atomic_success(self, fresh_loop):
        """_save_atomic: 正常にファイルが保存される"""
        test_data = {"test_key": "test_val"}
        fresh_loop._save_atomic(fresh_loop.decisions_path, test_data)
        
        assert fresh_loop.decisions_path.exists()
        with open(fresh_loop.decisions_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        assert saved == test_data

    def test_save_atomic_failure_cleanup(self, fresh_loop, monkeypatch):
        """_save_atomic: 書き込みエラーが発生した際に一時ファイルがクリーンアップされる"""
        def mock_dump(*args, **kwargs):
            raise IOError("Disk Full")
            
        import json
        monkeypatch.setattr(json, "dump", mock_dump)
        
        with pytest.raises(IOError, match="Disk Full"):
            fresh_loop._save_atomic(fresh_loop.decisions_path, {"test": 1})
            
        assert not fresh_loop.decisions_path.exists()
        # 一時ファイル (*.tmp) も残っていないことを確認
        tmp_files = list(fresh_loop.decisions_path.parent.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_apply_preferences_no_pattern(self, fresh_loop):
        """apply_preferences: パターンが存在しない場合はそのまま返す"""
        proposal = {"style": "default"}
        result = fresh_loop.apply_preferences(proposal, "nonexistent")
        assert result == proposal

    def test_generate_proposal_text_other(self, fresh_loop):
        """_generate_proposal_text: approved/rejected 以外の場合"""
        dec = Decision(id="d1", timestamp="", type="telop",
                       content={"text": "テスト"}, decision="modified",
                       approval_type="permanent")
        text = fresh_loop._generate_proposal_text(dec)
        assert "修正パターン" in text

    def test_apply_to_constitution_no_file(self, fresh_loop, monkeypatch, tmp_path):
        """_apply_to_constitution: constitution.json が存在しない場合は何もしない"""
        monkeypatch.setenv("LEARNING_LOOP_DATA_DIR", str(tmp_path))
        prop = PermanentProposal(
            id="prop_0001",
            created_at="",
            source_decision_id="dec_0001",
            proposal_type="content_policy",
            proposal="ポリシー提案",
        )
        fresh_loop._apply_to_constitution(prop)
        assert not (tmp_path / "constitution.json").exists()

    def test_apply_to_constitution_content_policy_init(self, fresh_loop, monkeypatch, tmp_path):
        """_apply_to_constitution: content_policyキーがない場合初期化して追加"""
        monkeypatch.setenv("LEARNING_LOOP_DATA_DIR", str(tmp_path))
        const_path = tmp_path / "constitution.json"
        with open(const_path, "w", encoding="utf-8") as f:
            json.dump({}, f)

        prop = PermanentProposal(
            id="prop_0001",
            created_at="",
            source_decision_id="dec_0001",
            proposal_type="content_policy",
            proposal="新規ポリシー",
        )
        fresh_loop._apply_to_constitution(prop)

        with open(const_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["content_policy"] == ["新規ポリシー"]

    def test_apply_to_constitution_keyword_init(self, fresh_loop, monkeypatch, tmp_path):
        """_apply_to_constitution: brand_personality/keywordsがない場合初期化して追加"""
        monkeypatch.setenv("LEARNING_LOOP_DATA_DIR", str(tmp_path))
        const_path = tmp_path / "constitution.json"
        
        # 1. 完全空のオブジェクト
        with open(const_path, "w", encoding="utf-8") as f:
            json.dump({}, f)

        prop = PermanentProposal(
            id="prop_0001",
            created_at="",
            source_decision_id="dec_0001",
            proposal_type="keyword",
            proposal="キーワード1",
        )
        fresh_loop._apply_to_constitution(prop)

        with open(const_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["brand_personality"]["keywords"] == ["キーワード1"]

        # 2. brand_personalityはあるがkeywordsがないオブジェクト
        with open(const_path, "w", encoding="utf-8") as f:
            json.dump({"brand_personality": {}}, f)

        prop2 = PermanentProposal(
            id="prop_0002",
            created_at="",
            source_decision_id="dec_0002",
            proposal_type="keyword",
            proposal="キーワード2",
        )
        fresh_loop._apply_to_constitution(prop2)

        with open(const_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["brand_personality"]["keywords"] == ["キーワード2"]

    def test_apply_to_constitution_keyword_duplicate(self, fresh_loop, monkeypatch, tmp_path):
        """_apply_to_constitution: 重複するキーワードは追加しない"""
        monkeypatch.setenv("LEARNING_LOOP_DATA_DIR", str(tmp_path))
        const_path = tmp_path / "constitution.json"
        with open(const_path, "w", encoding="utf-8") as f:
            json.dump({"brand_personality": {"keywords": ["既存キーワード"]}}, f)

        prop = PermanentProposal(
            id="prop_0001",
            created_at="",
            source_decision_id="dec_0001",
            proposal_type="keyword",
            proposal="既存キーワード",
        )
        fresh_loop._apply_to_constitution(prop)

        with open(const_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["brand_personality"]["keywords"] == ["既存キーワード"]

    def test_apply_to_constitution_exception(self, fresh_loop, monkeypatch, tmp_path):
        """_apply_to_constitution: 読み込みや書き込みで例外が発生した場合はログを出力して続行"""
        monkeypatch.setenv("LEARNING_LOOP_DATA_DIR", str(tmp_path))
        const_path = tmp_path / "constitution.json"
        with open(const_path, "w", encoding="utf-8") as f:
            f.write("{invalid json")

        prop = PermanentProposal(
            id="prop_0001",
            created_at="",
            source_decision_id="dec_0001",
            proposal_type="content_policy",
            proposal="例外ポリシー",
        )
        
        with patch("learning_loop.logger.error") as mock_log:
            fresh_loop._apply_to_constitution(prop)
            mock_log.assert_called_once()
            assert "憲法適用エラー" in mock_log.call_args[0][0]

    def test_load_exceptions(self, tmp_path):
        """_load: JSONが破損している場合、各例外ハンドラが呼び出されてログを記録する"""
        decisions_file = tmp_path / "decisions.json"
        proposals_file = tmp_path / "future_council_queue.json"
        patterns_file = tmp_path / "preference_patterns.json"

        with open(decisions_file, "w", encoding="utf-8") as f:
            f.write("{invalid decisions")
        with open(proposals_file, "w", encoding="utf-8") as f:
            f.write("{invalid proposals")
        with open(patterns_file, "w", encoding="utf-8") as f:
            f.write("{invalid patterns")

        with patch("learning_loop.get_data_dir", return_value=tmp_path), \
             patch("learning_loop.logger.error") as mock_log:
            loop = LearningLoop()
            assert mock_log.call_count == 3
            log_messages = [call[0][0] for call in mock_log.call_args_list]
            assert any("意思決定履歴読み込みエラー" in msg for msg in log_messages)
            assert any("未来議会キュー読み込みエラー" in msg for msg in log_messages)
            assert any("好みパターン読み込みエラー" in msg for msg in log_messages)
            assert loop.decisions == []
            assert loop.proposals == []
            assert loop.patterns == {}

    def test_save_atomic_remove_temp_exception(self, fresh_loop, monkeypatch):
        """_save_atomic: 保存失敗時に一時ファイルの削除でも例外が発生した場合、エラーがログ出力され、元の例外が伝播する"""
        import os
        def mock_dump(*args, **kwargs):
            raise IOError("Write Error")
        
        def mock_remove(path):
            raise OSError("Permission Denied")

        monkeypatch.setattr(json, "dump", mock_dump)
        monkeypatch.setattr(os, "remove", mock_remove)

        with patch("learning_loop.logger.error") as mock_log:
            with pytest.raises(IOError, match="Write Error"):
                fresh_loop._save_atomic(fresh_loop.decisions_path, {"test": 1})
            mock_log.assert_called_once()
            assert "アトミック保存エラー" in mock_log.call_args[0][0]

    def test_dotenv_load_exception(self, monkeypatch):
        """load_dotenvインポート・実行例外時のハンドリング"""
        import sys
        import importlib
        import dotenv
        
        def mock_load_dotenv():
            raise Exception("Dotenv Load Failure")
        
        monkeypatch.setattr(dotenv, "load_dotenv", mock_load_dotenv)
        
        import learning_loop
        try:
            importlib.reload(learning_loop)
            assert learning_loop.load_dotenv_available is False
        finally:
            monkeypatch.undo()
            importlib.reload(learning_loop)
            assert learning_loop.load_dotenv_available is True

    def test_save_atomic_fd_leak_prevention(self, fresh_loop, monkeypatch):
        """_save_atomic: os.fdopenやjson.dumpが例外を投げた際、fdがクローズされリークしないこと"""
        import os
        import tempfile
        
        # os.closeが呼ばれたかを検知するためのラッパー
        close_called_with = []
        original_close = os.close
        def mock_close(fd):
            close_called_with.append(fd)
            try:
                original_close(fd)
            except OSError:
                pass
        monkeypatch.setattr(os, "close", mock_close)
        
        # fdopenが例外を投げるようにモック
        def mock_fdopen(*args, **kwargs):
            raise ValueError("fdopen failed")
        monkeypatch.setattr(os, "fdopen", mock_fdopen)
        
        # mkstempで返されるfdを記録
        original_mkstemp = tempfile.mkstemp
        created_fds = []
        def mock_mkstemp(*args, **kwargs):
            fd, path = original_mkstemp(*args, **kwargs)
            created_fds.append(fd)
            return fd, path
        monkeypatch.setattr(tempfile, "mkstemp", mock_mkstemp)
        
        with pytest.raises(ValueError, match="fdopen failed"):
            fresh_loop._save_atomic(fresh_loop.decisions_path, {"test": 1})
            
        # mkstempで開かれたfdが、os.closeで閉じられていることを確認
        assert len(created_fds) == 1
        assert created_fds[0] in close_called_with

    def test_apply_to_constitution_atomic(self, fresh_loop, monkeypatch, tmp_path):
        """_apply_to_constitution: 憲法適用時に_save_atomicが呼び出されること"""
        monkeypatch.setenv("LEARNING_LOOP_DATA_DIR", str(tmp_path))
        const_path = tmp_path / "constitution.json"
        
        # 初期状態の書き込み
        with open(const_path, "w", encoding="utf-8") as f:
            json.dump({"content_policy": ["ポリシー1"]}, f)
            
        prop = PermanentProposal(
            id="prop_0001",
            created_at="",
            source_decision_id="dec_0001",
            proposal_type="content_policy",
            proposal="新規アトミックポリシー",
        )
        
        save_atomic_called = []
        original_save_atomic = fresh_loop._save_atomic
        def mock_save_atomic(file_path, data):
            save_atomic_called.append((file_path, data))
            original_save_atomic(file_path, data)
            
        monkeypatch.setattr(fresh_loop, "_save_atomic", mock_save_atomic)
        
        fresh_loop._apply_to_constitution(prop)
        
        # _save_atomicが呼ばれて、正しいパスとデータが渡されたことを検証
        assert len(save_atomic_called) == 1
        assert save_atomic_called[0][0] == const_path
        assert "新規アトミックポリシー" in save_atomic_called[0][1]["content_policy"]

    def test_load_json_decode_error(self, fresh_loop, tmp_path):
        """_load_json_data: JSONDecodeErrorが発生したときにログを記録しNoneを返すこと"""
        corrupted_file = tmp_path / "corrupted.json"
        with open(corrupted_file, "w", encoding="utf-8") as f:
            f.write("{invalid_json:")
            
        with patch("learning_loop.logger.error") as mock_log:
            result = fresh_loop._load_json_data(corrupted_file, "テスト読み込みエラー")
            assert result is None
            mock_log.assert_called_once()
            assert "JSONデコードエラー" in mock_log.call_args[0][0]


# ============================================================
# ショートカット関数テスト
# ============================================================

class TestShortcutFunctions:
    """record_approval, record_rejection, get_council_agenda"""

    def test_record_approval(self):
        """record_approval: 承認記録"""
        with patch("learning_loop.learning_loop") as mock_loop:
            mock_loop.record_decision.return_value = MagicMock()
            result = record_approval({"type": "telop", "text": "テスト"})
            mock_loop.record_decision.assert_called_once()

    def test_record_rejection(self):
        """record_rejection: 却下記録"""
        with patch("learning_loop.learning_loop") as mock_loop:
            mock_loop.record_decision.return_value = MagicMock()
            result = record_rejection({"type": "telop"}, reason="テスト理由")
            mock_loop.record_decision.assert_called_once()

    def test_get_council_agenda(self):
        """get_council_agenda: 議題取得"""
        with patch("learning_loop.learning_loop") as mock_loop:
            mock_loop.get_pending_proposals.return_value = [{"id": "prop_0001"}]
            result = get_council_agenda()
            assert result == [{"id": "prop_0001"}]
            mock_loop.get_pending_proposals.assert_called_once()

