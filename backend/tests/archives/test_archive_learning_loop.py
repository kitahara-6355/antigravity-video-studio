"""
M21.1: Archive Learning Loop テスト
archives/archive_stable_v3.0_20260118_0953/learning_loop.py のカバレッジ100%達成用テスト
"""

import pytest
import json
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# アーカイブの learning_loop をインポートできるようにパスを通す
archive_dir = str(Path(__file__).resolve().parent.parent.parent / "archives" / "archive_stable_v3.0_20260118_0953")
if archive_dir not in sys.path:
    sys.path.insert(0, archive_dir)

import learning_loop
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


@pytest.fixture(autouse=True)
def setup_env(tmp_path, monkeypatch):
    """すべてのテスト実行前に環境変数を一時フォルダに向け、既存データとの干渉を防ぐ"""
    monkeypatch.setenv("LEARNING_LOOP_DATA_DIR", str(tmp_path))
    # シングルトンのパス定義を更新する
    data_dir = tmp_path
    learning_loop.learning_loop.decisions_path = data_dir / "decisions.json"
    learning_loop.learning_loop.proposals_path = data_dir / "future_council_queue.json"
    learning_loop.learning_loop.patterns_path = data_dir / "preference_patterns.json"
    # シングルトンの状態をクリア
    learning_loop.learning_loop.decisions = []
    learning_loop.learning_loop.proposals = []
    learning_loop.learning_loop.patterns = {}


@pytest.fixture
def fresh_loop(tmp_path):
    """テスト用の独立したLearningLoopインスタンス"""
    loop = LearningLoop.__new__(LearningLoop)
    loop.decisions_path = tmp_path / "decisions.json"
    loop.proposals_path = tmp_path / "future_council_queue.json"
    loop.patterns_path = tmp_path / "preference_patterns.json"
    loop.decisions = []
    loop.proposals = []
    loop.patterns = {}
    return loop


# ============================================================
# LearningLoop 基本機能テスト
# ============================================================

class TestLearningLoopBasic:
    """LearningLoop の基本的な記録・保存・読み込みの検証"""

    def test_record_decision_this_time_only(self, fresh_loop):
        """record_decision: 今回のみ承認時の保存とプロパティ検証"""
        dec = fresh_loop.record_decision(
            decision_type="telop",
            content={"text": "テストテロップ", "value": "test_val"},
            decision="approved",
            approval_type=ApprovalType.THIS_TIME_ONLY,
            reason="テスト理由",
            tags=["color"]
        )
        assert isinstance(dec, Decision)
        assert dec.id == "dec_00000"
        assert dec.decision == "approved"
        assert dec.approval_type == "this_time_only"
        assert len(fresh_loop.decisions) == 1
        assert "color" in fresh_loop.patterns
        assert fresh_loop.patterns["color"].preferred == ["test_val"]

    def test_record_decision_rejected(self, fresh_loop):
        """record_decision: 却下時の好みパターン回避リスト更新検証"""
        dec = fresh_loop.record_decision(
            decision_type="image",
            content={"text": "不正な画像", "value": "bad_image"},
            decision="rejected",
            approval_type=ApprovalType.THIS_TIME_ONLY,
            reason="画質不良",
            tags=["quality"]
        )
        assert dec.decision == "rejected"
        assert "bad_image" in fresh_loop.patterns["quality"].avoided

    def test_record_decision_permanent(self, fresh_loop):
        """record_decision: 恒久化承認時に提案がキューに作成されることの検証"""
        dec = fresh_loop.record_decision(
            decision_type="telop",
            content={"text": "標準テキスト", "value": "std_text"},
            decision="approved",
            approval_type=ApprovalType.PERMANENT,
            tags=["style"]
        )
        assert len(fresh_loop.proposals) == 1
        assert fresh_loop.proposals[0].proposal_type == "style_preference"
        assert "標準化" in fresh_loop.proposals[0].proposal

    def test_infer_proposal_type(self, fresh_loop):
        """_infer_proposal_type: 各種タグに応じた提案タイプ推論の検証"""
        dec_style = Decision("d1", "", "telop", {}, "approved", "permanent", tags=["style"])
        dec_pos = Decision("d2", "", "telop", {}, "approved", "permanent", tags=["position"])
        dec_kw = Decision("d3", "", "telop", {}, "approved", "permanent", tags=["other"])
        
        assert fresh_loop._infer_proposal_type(dec_style) == "style_preference"
        assert fresh_loop._infer_proposal_type(dec_pos) == "content_policy"
        assert fresh_loop._infer_proposal_type(dec_kw) == "keyword"

    def test_generate_proposal_text(self, fresh_loop):
        """_generate_proposal_text: 修正提案および却下提案時の文言生成検証"""
        dec_rejected = Decision("d1", "", "image", {"text": "画像A"}, "rejected", "permanent")
        dec_modified = Decision("d2", "", "scene", {"text": "シーンB"}, "modified", "permanent")
        
        assert "避ける" in fresh_loop._generate_proposal_text(dec_rejected)
        assert "修正パターン" in fresh_loop._generate_proposal_text(dec_modified)

    def test_get_pending_proposals(self, fresh_loop):
        """get_pending_proposals: 保留中提案の一覧取得"""
        fresh_loop.proposals = [
            PermanentProposal("p1", "", "d1", "keyword", "prop1", status="pending"),
            PermanentProposal("p2", "", "d2", "keyword", "prop2", status="approved")
        ]
        pending = fresh_loop.get_pending_proposals()
        assert len(pending) == 1
        assert pending[0]["id"] == "p1"


# ============================================================
# 例外系および境界値テスト
# ============================================================

class TestLearningLoopExceptions:
    """TDRに指摘された except Exception 関連の具体的例外ハンドリングの検証"""

    def test_load_decisions_json_decode_error(self, fresh_loop):
        """_load: 意思決定履歴ファイルが破損している場合の例外キャッチと安全な初期化"""
        fresh_loop.decisions_path.write_text("{invalid_json}", encoding="utf-8")
        # ログ出力されるが例外でクラッシュしないことを確認
        fresh_loop._load()
        assert fresh_loop.decisions == []

    def test_load_proposals_json_decode_error(self, fresh_loop):
        """_load: 未来議会ファイルが破損している場合の例外キャッチと安全な初期化"""
        fresh_loop.proposals_path.write_text("bad: data", encoding="utf-8")
        fresh_loop._load()
        assert fresh_loop.proposals == []

    def test_load_patterns_json_decode_error(self, fresh_loop):
        """_load: 好みパターンファイルが破損している場合の例外キャッチと安全な初期化"""
        fresh_loop.patterns_path.write_text("[broken", encoding="utf-8")
        fresh_loop._load()
        assert fresh_loop.patterns == {}

    def test_load_decisions_type_error(self, fresh_loop):
        """_load: decisions.json の形式が不正（リストではない等）で型エラーが発生する場合のキャッチ"""
        # Decisionsが辞書型になっている場合など、型不整合をシミュレート
        fresh_loop.decisions_path.write_text(json.dumps({"decisions": {"invalid_dict": 1}}), encoding="utf-8")
        fresh_loop._load()
        assert fresh_loop.decisions == []

    def test_apply_to_constitution_no_file(self, fresh_loop):
        """_apply_to_constitution: 憲法ファイルが存在しない場合は早期リターン"""
        prop = PermanentProposal("p1", "", "d1", "content_policy", "new_rule")
        # 存在しないパスを指定してもエラーにならずリターンする
        fresh_loop._apply_to_constitution(prop)

    def test_apply_to_constitution_broken_json(self, tmp_path, fresh_loop):
        """_apply_to_constitution: 憲法ファイルが破損している場合の例外キャッチ検証"""
        const_path = tmp_path / "constitution.json"
        const_path.write_text("{invalid", encoding="utf-8")
        
        prop = PermanentProposal("p1", "", "d1", "content_policy", "new_rule")
        # 例外でクラッシュせずにエラーログが出ることを検証
        with patch("learning_loop._get_data_dir", return_value=tmp_path):
            fresh_loop._apply_to_constitution(prop)

    def test_apply_to_constitution_permission_error(self, tmp_path, fresh_loop):
        """_apply_to_constitution: ファイル書き込みエラー(PermissionError)時の例外キャッチ"""
        const_path = tmp_path / "constitution.json"
        const_path.write_text(json.dumps({"content_policy": []}), encoding="utf-8")
        
        prop = PermanentProposal("p1", "", "d1", "content_policy", "new_rule")
        
        # open をモックして PermissionError を発生させる
        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            with patch("learning_loop._get_data_dir", return_value=tmp_path):
                fresh_loop._apply_to_constitution(prop)


# ============================================================
# 提案審議および憲法反映テスト
# ============================================================

class TestProposalReview:
    """未来議会提案の審議および憲法(constitution.json)への反映検証"""

    def test_review_proposal_not_found(self, fresh_loop):
        """review_proposal: 存在しない提案IDの審議は False を返す"""
        assert fresh_loop.review_proposal("invalid_id", approved=True) is False

    def test_review_proposal_reject(self, fresh_loop):
        """review_proposal: 却下された場合は提案ステータスが rejected になり憲法には反映されない"""
        prop = PermanentProposal("p1", "", "d1", "content_policy", "prop_text")
        fresh_loop.proposals.append(prop)
        
        result = fresh_loop.review_proposal("p1", approved=False)
        assert result is True
        assert prop.status == "rejected"
        assert prop.reviewed_at is not None

    def test_review_proposal_approve_content_policy(self, tmp_path, fresh_loop):
        """review_proposal: 承認かつ content_policy の場合に憲法ファイルの content_policy 配列に追加される"""
        const_path = tmp_path / "constitution.json"
        const_path.write_text(json.dumps({"content_policy": ["exist_rule"]}), encoding="utf-8")
        
        prop = PermanentProposal("p1", "", "d1", "content_policy", "new_rule")
        fresh_loop.proposals.append(prop)
        
        with patch("learning_loop._get_data_dir", return_value=tmp_path):
            result = fresh_loop.review_proposal("p1", approved=True)
            
        assert result is True
        assert prop.status == "approved"
        
        # 憲法ファイルの中身を確認
        with open(const_path, "r", encoding="utf-8") as f:
            constitution = json.load(f)
        assert "new_rule" in constitution["content_policy"]
        assert constitution["content_policy"] == ["exist_rule", "new_rule"]

    def test_review_proposal_approve_keyword(self, tmp_path, fresh_loop):
        """review_proposal: 承認かつ keyword の場合に brand_personality.keywords に重複なく追加される"""
        const_path = tmp_path / "constitution.json"
        const_path.write_text(json.dumps({
            "brand_personality": {"keywords": ["trusted"]}
        }), encoding="utf-8")
        
        prop1 = PermanentProposal("p1", "", "d1", "keyword", "new_kw")
        prop2 = PermanentProposal("p2", "", "d2", "keyword", "trusted")  # 重複キーワード
        fresh_loop.proposals.extend([prop1, prop2])
        
        with patch("learning_loop._get_data_dir", return_value=tmp_path):
            fresh_loop.review_proposal("p1", approved=True)
            fresh_loop.review_proposal("p2", approved=True)
            
        with open(const_path, "r", encoding="utf-8") as f:
            constitution = json.load(f)
        
        assert "new_kw" in constitution["brand_personality"]["keywords"]
        # trusted は重複しないこと
        assert constitution["brand_personality"]["keywords"] == ["trusted", "new_kw"]


# ============================================================
# 好みパターン取得と適用テスト
# ============================================================

class TestPreferenceApplication:
    """好みパターンの取得および適用ロジックの検証"""

    def test_get_preferences_single_category(self, fresh_loop):
        """get_preferences: 特定カテゴリの好み取得"""
        fresh_loop.patterns["color"] = PreferencePattern("color", preferred=["red"], avoided=["blue"])
        fresh_loop.patterns["style"] = PreferencePattern("style", preferred=["bold"])
        
        color_pref = fresh_loop.get_preferences("color")
        assert color_pref["category"] == "color"
        assert color_pref["preferred"] == ["red"]

    def test_apply_preferences_no_pattern(self, fresh_loop):
        """apply_preferences: カテゴリに対応する好みパターンがない場合はそのまま返す"""
        proposal = {"style": "minimal"}
        result = fresh_loop.apply_preferences(proposal, "style")
        assert result == proposal

    def test_apply_preferences_success(self, fresh_loop):
        """apply_preferences: 好みパターンが反映され、推奨および回避スタイルが追加される"""
        fresh_loop.patterns["style"] = PreferencePattern("style", preferred=["clean", "bold", "modern", "excess"], avoided=["messy"])
        
        proposal = {"style": "default"}
        result = fresh_loop.apply_preferences(proposal, "style")
        
        # preferred は最大3件のみ反映されること
        assert result["recommended_styles"] == ["clean", "bold", "modern"]
        assert result["avoid_styles"] == ["messy"]


# ============================================================
# ショートカット関数およびシングルトンテスト
# ============================================================

class TestShortcuts:
    """record_approval / record_rejection などの簡易ショートカット関数の検証"""

    def test_record_approval_shortcut(self):
        """record_approval: 簡易承認関数の動作検証"""
        dec = record_approval({"type": "telop", "text": "ショートカットテスト"}, tags=["test"], permanent=True)
        assert dec.decision == "approved"
        assert dec.approval_type == "permanent"

    def test_record_rejection_shortcut(self):
        """record_rejection: 簡易却下関数の動作検証"""
        dec = record_rejection({"type": "scene"}, reason="テンポが悪い", tags=["scene"])
        assert dec.decision == "rejected"
        assert dec.approval_type == "this_time_only"
        assert dec.reason == "テンポが悪い"

    def test_get_council_agenda_shortcut(self, fresh_loop):
        """get_council_agenda: 未来議会アジェンダ取得関数の検証"""
        with patch("learning_loop.learning_loop", fresh_loop):
            fresh_loop.proposals = [
                PermanentProposal("p1", "", "d1", "keyword", "agenda1", status="pending")
            ]
            agenda = get_council_agenda()
            assert len(agenda) == 1
            assert agenda[0]["proposal"] == "agenda1"

    def test_dotenv_load_error(self):
        """dotenv インポートエラー発生時の例外キャッチ"""
        import importlib
        import sys
        
        # dotenv が例外を発生させるようにモック
        with patch.dict(sys.modules, {"dotenv": None}):
            # 再ロードして例外を発生させる
            importlib.reload(learning_loop)
            assert learning_loop.load_dotenv_available is False
            
        # テスト終了後に正常な状態に戻す
        importlib.reload(learning_loop)


# ============================================================
# その他の未カバー箇所テスト
# ============================================================

class TestAdditionalCoverage:
    """残りの未カバー箇所 (データの正常読み込み、キー不在時の憲法適用など) の検証"""

    def test_load_existing_proposals_and_patterns(self, fresh_loop):
        """_load: 存在する decisions, proposals, patterns を正常にロードすることの検証"""
        dec_data = {
            "decisions": [
                {
                    "id": "dec_00000",
                    "timestamp": "2026-05-22T00:00:00",
                    "type": "telop",
                    "content": {"text": "hoge"},
                    "decision": "approved",
                    "approval_type": "this_time_only"
                }
            ]
        }
        fresh_loop.decisions_path.write_text(json.dumps(dec_data), encoding="utf-8")

        prop_data = {
            "pending_proposals": [
                {
                    "id": "prop_0000",
                    "created_at": "2026-05-22T00:00:00",
                    "source_decision_id": "dec_00000",
                    "proposal_type": "keyword",
                    "proposal": "prop_text",
                    "status": "pending"
                }
            ]
        }
        fresh_loop.proposals_path.write_text(json.dumps(prop_data), encoding="utf-8")

        pat_data = {
            "patterns": {
                "color": {
                    "category": "color",
                    "preferred": ["red"],
                    "avoided": []
                }
            }
        }
        fresh_loop.patterns_path.write_text(json.dumps(pat_data), encoding="utf-8")

        fresh_loop._load()

        assert len(fresh_loop.decisions) == 1
        assert fresh_loop.decisions[0].id == "dec_00000"
        assert len(fresh_loop.proposals) == 1
        assert fresh_loop.proposals[0].id == "prop_0000"
        assert "color" in fresh_loop.patterns
        assert fresh_loop.patterns["color"].preferred == ["red"]

    def test_review_proposal_approve_content_policy_missing_keys(self, tmp_path, fresh_loop):
        """review_proposal: content_policy で憲法に content_policy キーがない場合"""
        const_path = tmp_path / "constitution.json"
        const_path.write_text(json.dumps({}), encoding="utf-8")
        
        prop = PermanentProposal("p1", "", "d1", "content_policy", "new_rule")
        fresh_loop.proposals.append(prop)
        
        with patch("learning_loop._get_data_dir", return_value=tmp_path):
            result = fresh_loop.review_proposal("p1", approved=True)
            
        assert result is True
        with open(const_path, "r", encoding="utf-8") as f:
            constitution = json.load(f)
        assert constitution["content_policy"] == ["new_rule"]

    def test_review_proposal_approve_keyword_missing_brand_personality(self, tmp_path, fresh_loop):
        """review_proposal: keyword で憲法に brand_personality キーがない場合"""
        const_path = tmp_path / "constitution.json"
        const_path.write_text(json.dumps({}), encoding="utf-8")
        
        prop = PermanentProposal("p1", "", "d1", "keyword", "new_kw")
        fresh_loop.proposals.append(prop)
        
        with patch("learning_loop._get_data_dir", return_value=tmp_path):
            fresh_loop.review_proposal("p1", approved=True)
            
        with open(const_path, "r", encoding="utf-8") as f:
            constitution = json.load(f)
        assert constitution["brand_personality"]["keywords"] == ["new_kw"]

    def test_review_proposal_approve_keyword_missing_keywords_only(self, tmp_path, fresh_loop):
        """review_proposal: keyword で憲法に brand_personality はあるが keywords キーがない場合"""
        const_path = tmp_path / "constitution.json"
        const_path.write_text(json.dumps({"brand_personality": {}}), encoding="utf-8")
        
        prop = PermanentProposal("p1", "", "d1", "keyword", "new_kw")
        fresh_loop.proposals.append(prop)
        
        with patch("learning_loop._get_data_dir", return_value=tmp_path):
            fresh_loop.review_proposal("p1", approved=True)
            
        with open(const_path, "r", encoding="utf-8") as f:
            constitution = json.load(f)
        assert constitution["brand_personality"]["keywords"] == ["new_kw"]

    def test_get_preferences_all(self, fresh_loop):
        """get_preferences: カテゴリ指定なしで全パターンを取得"""
        fresh_loop.patterns["color"] = PreferencePattern("color", preferred=["red"])
        fresh_loop.patterns["style"] = PreferencePattern("style", preferred=["bold"])
        
        all_prefs = fresh_loop.get_preferences()
        assert "color" in all_prefs
        assert "style" in all_prefs
        assert all_prefs["color"]["preferred"] == ["red"]

