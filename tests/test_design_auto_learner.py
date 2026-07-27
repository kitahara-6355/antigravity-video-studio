import pytest
import json
from unittest.mock import patch, MagicMock
from pathlib import Path
from design_system.design_auto_learner import DesignAutoLearner, design_auto_learner

@pytest.fixture
def temp_store_path(tmp_path):
    # テストごとにユニークな一時ファイルパスを返す
    return tmp_path / "design_learning_store.json"

@pytest.fixture
def learner(temp_store_path):
    l = DesignAutoLearner()
    l._learning_store_path = temp_store_path
    return l

def test_learning_store_path_property():
    # デフォルトの学習ストアパスがPathインスタンスであることを確認
    l = DesignAutoLearner()
    path = l.learning_store_path
    assert isinstance(path, Path)
    assert path.name == "design_learning_store.json"

def test_learn_from_decision_success(learner):
    # 正常系の意思決定学習
    context = {"mood": "elegant", "custom_key": "custom_val"}
    result = learner.learn_from_decision(
        target_type="thumbnail",
        decision="approve",
        reason="Good composition",
        context=context
    )
    
    assert result["status"] == "learned"
    assert "entry" in result
    entry = result["entry"]
    assert entry["target_type"] == "thumbnail"
    assert entry["decision"] == "approve"
    assert entry["reason"] == "Good composition"
    assert entry["mood"] == "elegant"
    assert entry["context"] == context
    
    # 保存されたファイルを確認
    store = learner._load_store()
    assert len(store["entries"]) == 1
    assert store["entries"][0]["reason"] == "Good composition"

def test_learn_from_decision_suggestion_color(learner):
    # カラー関連の提案閾値到達テスト
    context = {"mood": "elegant"}
    
    # 3回同じカラー理由でrejectされる
    reason = "色が薄い"
    
    # 1回目
    r1 = learner.learn_from_decision("thumbnail", "reject", reason, context)
    assert r1["status"] == "learned"
    
    # 2回目
    r2 = learner.learn_from_decision("thumbnail", "reject", reason, context)
    assert r2["status"] == "learned"
    
    # 3回目 (閾値到達)
    r3 = learner.learn_from_decision("thumbnail", "reject", reason, context)
    assert r3["status"] == "suggestion"
    assert r3["suggestion"]["type"] == "color_palette"
    assert r3["suggestion"]["affected_moods"] == ["elegant"]

def test_learn_from_decision_suggestion_typography(learner):
    # タイポグラフィ関連の提案閾値到達テスト
    context = {"mood": "bold"}
    reason = "文字が小さすぎる"
    
    # 3回繰り返す
    learner.learn_from_decision("thumbnail", "reject", reason, context)
    learner.learn_from_decision("thumbnail", "reject", reason, context)
    r = learner.learn_from_decision("thumbnail", "reject", reason, context)
    
    assert r["status"] == "suggestion"
    assert r["suggestion"]["type"] == "typography"
    assert "typography" in r["suggestion"]["suggestion"].lower() or "タイポグラフィ" in r["suggestion"]["suggestion"].lower()

def test_learn_from_decision_suggestion_motion(learner):
    # モーション関連の提案閾値到達テスト
    context = {"mood": "pop"}
    reason = "動きが遅い"
    
    # 3回繰り返す
    learner.learn_from_decision("video", "reject", reason, context)
    learner.learn_from_decision("video", "reject", reason, context)
    r = learner.learn_from_decision("video", "reject", reason, context)
    
    assert r["status"] == "suggestion"
    assert r["suggestion"]["type"] == "motion"

def test_learn_from_decision_suggestion_other_reason(learner):
    # 閾値到達するが、提案対象のキーワードが含まれない場合
    context = {"mood": "pop"}
    reason = "その他何らかの理由"
    
    learner.learn_from_decision("video", "reject", reason, context)
    learner.learn_from_decision("video", "reject", reason, context)
    r = learner.learn_from_decision("video", "reject", reason, context)
    
    assert r["status"] == "learned"

def test_learn_from_quality_check_high_score(learner):
    # 品質チェック高スコア (スコア >= 80)
    result = learner.learn_from_quality_check({"score": 85, "issues": []}, mood="cool")
    assert result["status"] == "reinforced"
    assert "cool" in result["mood"]

def test_learn_from_quality_check_low_score(learner):
    # 品質チェック低スコア (スコア < 80)
    quality_result = {
        "score": 50,
        "issues": [
            {"type": "color_contrast", "description": "Too low contrast"},
            {"type": "readability", "description": "Font too small"},
            {"type": "unknown_issue", "description": "Something else"}
        ]
    }
    result = learner.learn_from_quality_check(quality_result, mood="modern")
    assert result["status"] == "analyzed"
    assert result["score"] == 50
    assert len(result["suggestions"]) == 2
    
    suggestions = result["suggestions"]
    # color_contrast
    assert any(s["type"] == "color_palette" and "コントラスト" in s["suggestion"] for s in suggestions)
    # readability
    assert any(s["type"] == "typography" and "フォントサイズ" in s["suggestion"] for s in suggestions)

def test_load_store_broken_json(learner, temp_store_path):
    # 壊れたJSONファイルが保存されている場合の _load_store 挙動 (TD-212 修正確認)
    with open(temp_store_path, "w", encoding="utf-8") as f:
        f.write("{broken json")
    
    store = learner._load_store()
    assert isinstance(store, dict)
    assert "entries" in store
    assert len(store["entries"]) == 0

def test_load_store_file_not_found(learner):
    # ファイルが存在しない場合の _load_store 挙動
    assert not learner.learning_store_path.exists()
    store = learner._load_store()
    assert isinstance(store, dict)
    assert "entries" in store
    assert len(store["entries"]) == 0

def test_get_learning_summary(learner):
    # 空の集計
    summary = learner.get_learning_summary()
    assert summary["total_entries"] == 0
    assert summary["by_decision"] == {"approve": 0, "reject": 0, "modify": 0}
    assert summary["by_mood"] == {}
    
    # データを追加して集計
    learner.learn_from_decision("thumbnail", "approve", "Reason 1", {"mood": "elegant"})
    learner.learn_from_decision("thumbnail", "reject", "Reason 2", {"mood": "elegant"})
    learner.learn_from_decision("video", "modify", "Reason 3", {"mood": "bold"})
    # 未知のdecision値を追加して偽ルートを通過させる
    learner.learn_from_decision("thumbnail", "other", "Reason 4", {"mood": "cool"})
    
    summary = learner.get_learning_summary()
    assert summary["total_entries"] == 4
    assert summary["by_decision"] == {"approve": 1, "reject": 1, "modify": 1}
    assert summary["by_mood"] == {"elegant": 2, "bold": 1, "cool": 1}
    assert summary["last_updated"] is not None

def test_is_similar_reason_edge_cases(learner):
    # _is_similar_reason のエッジケーステスト
    assert not learner._is_similar_reason("", "some reason")
    assert not learner._is_similar_reason("some reason", "")
    assert not learner._is_similar_reason("", "")
    
    assert not learner._is_similar_reason("hello", "world")
    
    assert learner._is_similar_reason("フォント が 小さい", "フォント が 薄い")

def test_singleton_instance():
    # シングルトンインスタンスが正しくインポートできること
    assert design_auto_learner is not None
    assert isinstance(design_auto_learner, DesignAutoLearner)

def test_save_store_creates_parent_directory(learner, tmp_path):
    # 親ディレクトリが存在しないストアパスを設定
    non_existent_dir = tmp_path / "new_branding_dir"
    store_path = non_existent_dir / "design_learning_store.json"
    learner._learning_store_path = store_path
    
    assert not non_existent_dir.exists()
    
    # 保存を実行
    test_store = {"entries": [{"test": "data"}]}
    learner._save_store(test_store)
    
    # ディレクトリが作成され、ファイルが保存されていることを確認
    assert non_existent_dir.exists()
    assert store_path.exists()
    
    # 読み込んで内容を確認
    loaded = learner._load_store()
    assert loaded["entries"][0]["test"] == "data"

def test_create_decision_entry(learner):
    entry = learner._create_decision_entry(
        target_type="thumbnail",
        decision="reject",
        reason="too dark",
        context={"mood": "elegant", "extra": "info"}
    )
    assert entry["target_type"] == "thumbnail"
    assert entry["decision"] == "reject"
    assert entry["reason"] == "too dark"
    assert entry["mood"] == "elegant"
    assert entry["context"] == {"mood": "elegant", "extra": "info"}
    assert "timestamp" in entry

def test_has_keywords(learner):
    assert learner._has_color_keywords("色が薄い")
    assert not learner._has_color_keywords("サイズが小さい")
    
    assert learner._has_typography_keywords("文字が小さい")
    assert not learner._has_typography_keywords("コントラストが低い")
    
    assert learner._has_motion_keywords("動きが早い")
    assert not learner._has_motion_keywords("フォントがダサい")


def test_learn_from_decision_default_mood(learner):
    # context に mood が含まれない場合、デフォルト値の "elegant" が使われること
    result = learner.learn_from_decision(
        target_type="thumbnail",
        decision="approve",
        reason="Good composition",
        context={}
    )
    assert result["status"] == "learned"
    assert result["entry"]["mood"] == "elegant"

def test_learn_from_quality_check_default_mood(learner):
    # mood 引数を省略した場合、デフォルトの "elegant" が使われること
    # 高スコアのケース
    result_high = learner.learn_from_quality_check({"score": 90, "issues": []})
    assert result_high["status"] == "reinforced"
    assert result_high["mood"] == "elegant"

    # 低スコアのケース
    result_low = learner.learn_from_quality_check({
        "score": 50,
        "issues": [{"type": "color_contrast"}]
    })
    assert result_low["status"] == "analyzed"
    assert result_low["suggestions"][0]["mood"] == "elegant"

def test_is_similar_reason_overlap_ratio_branch(learner):
    # overlap < 2 だが、比率が 0.5 より大きくて True になるケース
    # 単語数が共に 1 で、1単語が共通している場合 (overlap = 1, min_len = 1, ratio = 1.0 > 0.5)
    assert learner._is_similar_reason("フォント", "フォント")
    
    # 比率が 0.5 以下になって False になるケース
    # keywords_ref = {"フォント", "サイズ"} (len=2), keywords_tgt = {"カラー"} (len=1), overlap=0, ratio = 0.0 <= 0.5
    assert not learner._is_similar_reason("フォント サイズ", "カラー")

def test_generate_token_suggestion_missing_reason(learner):
    # patterns に reason が含まれない場合のエッジケース
    assert learner._generate_token_suggestion({}) is None
    # patterns["reason"] が None の場合、AttributeError が発生することを検証 (L1制約のため挙動を固定)
    with pytest.raises(AttributeError):
        learner._generate_token_suggestion({"reason": None})


def test_load_store_os_error(learner):
    with patch.object(Path, "exists", return_value=True):
        with patch("builtins.open", side_effect=OSError("Disk failure")):
            store = learner._load_store()
            assert store == {"entries": []}

def test_load_store_exists_os_error(learner):
    with patch.object(Path, "exists", side_effect=OSError("Permission denied")):
        store = learner._load_store()
        assert store == {"entries": []}

def test_save_store_os_error(learner):
    with patch("builtins.open", side_effect=OSError("Read-only filesystem")):
        learner._save_store({"entries": []})

def test_learn_from_decision_invalid_args(learner):
    # context=None
    r1 = learner.learn_from_decision("thumbnail", "approve", "Reason", None)
    assert r1["status"] == "learned"
    assert r1["entry"]["mood"] == "elegant"
    assert r1["entry"]["context"] == {}
    
    # reason=None
    r2 = learner.learn_from_decision("thumbnail", "approve", None, {"mood": "cool"})
    assert r2["status"] == "learned"
    assert r2["entry"]["reason"] == ""
    
    # reason が文字列以外 (例: 数値)
    r3 = learner.learn_from_decision("thumbnail", "approve", 123, {"mood": "cool"})
    assert r3["status"] == "learned"
    assert r3["entry"]["reason"] == "123"

def test_learn_from_quality_check_invalid_args(learner):
    # quality_result=None
    r1 = learner.learn_from_quality_check(None)
    assert r1["status"] == "error"
    assert "Invalid" in r1["message"]
    
    # quality_result が辞書以外
    r2 = learner.learn_from_quality_check("not a dict")
    assert r2["status"] == "error"
    
    # issues がリスト以外、score がパース不可能
    quality_result = {"score": "not_a_number", "issues": "not_a_list"}
    r3 = learner.learn_from_quality_check(quality_result, mood="modern")
    assert r3["status"] == "analyzed"
    assert r3["score"] == 0
    assert r3["suggestions"] == []
