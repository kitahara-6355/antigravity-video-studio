import sys
import json
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

# バックエンドおよびアーカイブパスを sys.path に追加
backend_dir = Path(__file__).parent.parent.parent
archives_dir = backend_dir / "archives"
sys.path.insert(0, str(backend_dir))
sys.path.insert(0, str(archives_dir))

from unified.learning_unified import learning_unified, LearningInsight, LearningUnified


@pytest.fixture
def temp_branding_env(tmp_path):
    """
    テストごとにクリーンな branding 環境を構築するフィクスチャ。
    learning_unified シングルトンのパスを tmp_path にパッチし、
    初期の constitution.json を作成します。
    """
    # オリジナルのパスを退避
    orig_branding_dir = learning_unified._branding_dir
    orig_evolution_log = learning_unified._evolution_log_path
    orig_constitution = learning_unified._constitution_path
    orig_design_tokens = learning_unified._design_tokens_path

    # パスを tmp_path に書き換え
    learning_unified._branding_dir = tmp_path
    learning_unified._evolution_log_path = tmp_path / "evolution_log.json"
    learning_unified._constitution_path = tmp_path / "constitution.json"
    learning_unified._design_tokens_path = tmp_path / "design_tokens.json"

    # 初期 constitution.json を作成
    initial_constitution = {
        "content_policy": [],
        "brand_personality": {
            "keywords": []
        },
        "design_tokens": {}
    }
    with open(learning_unified._constitution_path, "w", encoding="utf-8") as f:
        json.dump(initial_constitution, f, ensure_ascii=False, indent=2)

    yield tmp_path

    # パスを元に戻す
    learning_unified._branding_dir = orig_branding_dir
    learning_unified._evolution_log_path = orig_evolution_log
    learning_unified._constitution_path = orig_constitution
    learning_unified._design_tokens_path = orig_design_tokens


def test_learning_insight_dataclass():
    """LearningInsight dataclass の初期化をテスト"""
    insight = LearningInsight(
        source="decision",
        category="color",
        insight="Avoid red subtitle text",
        confidence=0.9
    )
    assert insight.source == "decision"
    assert insight.category == "color"
    assert insight.insight == "Avoid red subtitle text"
    assert insight.confidence == 0.9
    assert insight.timestamp is not None


def test_record_decision_approve(temp_branding_env):
    """意思決定の記録（承認）と evolution_log への追記をテスト"""
    res = learning_unified.record_decision(
        decision_type="approve",
        target="font_size",
        outcome="approve",
        reason="Good readability",
        tags=["font", "readability"]
    )
    assert res["status"] == "recorded"
    assert res["entry"]["type"] == "approve"
    assert res["entry"]["target"] == "font_size"
    assert res["entry"]["outcome"] == "approve"
    assert res["entry"]["reason"] == "Good readability"
    assert "font" in res["entry"]["tags"]

    # evolution_log.json に追記されたことを確認
    log = learning_unified._load_evolution_log()
    assert len(log["entries"]) == 1
    assert log["entries"][0]["target"] == "font_size"
    assert log["entries"][0]["outcome"] == "approve"


def test_record_decision_reject(temp_branding_env):
    """意思決定の記録（却下）と evolution_log への追記をテスト"""
    res = learning_unified.record_decision(
        decision_type="reject",
        target="tempo_fast",
        outcome="reject",
        reason="Too fast for aging audience",
        tags=["tempo", "audience"]
    )
    assert res["status"] == "recorded"
    assert res["entry"]["outcome"] == "reject"

    log = learning_unified._load_evolution_log()
    assert len(log["entries"]) == 1
    assert log["entries"][0]["outcome"] == "reject"


def test_load_evolution_log_io_error(temp_branding_env):
    """evolution_log.json 読み込み時の例外処理をテスト"""
    # 既存の evolution_log を破損した JSON にする
    with open(learning_unified._evolution_log_path, "w", encoding="utf-8") as f:
        f.write("{ invalid json }")

    # 例外が再送出されることを確認
    with pytest.raises(json.JSONDecodeError):
        learning_unified._load_evolution_log()


def test_save_evolution_log_io_error(temp_branding_env):
    """evolution_log.json 保存時の例外処理をテスト"""
    # 書込み不可能なパスにするために、パスをディレクトリとして作成しておく
    learning_unified._evolution_log_path.mkdir(parents=True, exist_ok=True)

    # 保存処理を実行すると例外が発生することを確認
    with pytest.raises(OSError):
        learning_unified._save_evolution_log({"entries": []})

    # 一方、追記処理（_append_to_evolution_log）は例外をキャッチして安全に終了することを確認
    learning_unified._append_to_evolution_log({"entry": "test"})


def test_rejection_pattern_trigger(temp_branding_env):
    """却下パターンの累積による content_policy 自動更新をテスト"""
    # REJECTION_THRESHOLD = 3
    # 同一タグでの却下を3回発生させる
    for i in range(2):
        learning_unified.record_decision(
            decision_type="reject",
            target="red_color",
            outcome="reject",
            reason="Avoid red text",
            tags=["red_style"]
        )

    # まだ閾値未満のためポリシーは追加されていないはず
    constitution = learning_unified._load_constitution()
    assert len(constitution.get("content_policy", [])) == 0

    # 3回目の却下を実行
    learning_unified.record_decision(
        decision_type="reject",
        target="red_color",
        outcome="reject",
        reason="Avoid red text",
        tags=["red_style"]
    )

    # 閾値に達したので、content_policy が追加されていることを確認
    constitution = learning_unified._load_constitution()
    policies = constitution.get("content_policy", [])
    assert len(policies) == 1
    assert "Avoid 'red_style' adjustments" in policies[0]

    # 重複して追加されないことを確認するため、4回目を実行
    learning_unified.record_decision(
        decision_type="reject",
        target="red_color",
        outcome="reject",
        reason="Avoid red text",
        tags=["red_style"]
    )
    constitution = learning_unified._load_constitution()
    assert len(constitution.get("content_policy", [])) == 1


def test_approval_pattern_trigger(temp_branding_env):
    """承認パターンの累積による keywords 自動更新をテスト"""
    # APPROVAL_THRESHOLD = 5
    # 同一タグでの承認を5回発生させる
    for i in range(4):
        learning_unified.record_decision(
            decision_type="approve",
            target="neon_glow",
            outcome="approve",
            reason="Neon fits dark mode theme",
            tags=["neon"]
        )

    # まだ閾値未満のため keywords は追加されていないはず
    constitution = learning_unified._load_constitution()
    assert "neon" not in constitution.get("brand_personality", {}).get("keywords", [])

    # 5回目の承認を実行
    learning_unified.record_decision(
        decision_type="approve",
        target="neon_glow",
        outcome="approve",
        reason="Neon fits dark mode theme",
        tags=["neon"]
    )

    # 閾値に達したので、keywords が追加されていることを確認
    constitution = learning_unified._load_constitution()
    keywords = constitution.get("brand_personality", {}).get("keywords", [])
    assert "neon" in keywords

    # 重複して追加されないことを確認するため、6回目を実行
    learning_unified.record_decision(
        decision_type="approve",
        target="neon_glow",
        outcome="approve",
        reason="Neon fits dark mode theme",
        tags=["neon"]
    )
    constitution = learning_unified._load_constitution()
    assert len(constitution.get("brand_personality", {}).get("keywords", [])) == 1


def test_load_constitution_io_error(temp_branding_env):
    """constitution.json 読み込み時の例外処理をテスト"""
    # constitution.json を破損した JSON にする
    with open(learning_unified._constitution_path, "w", encoding="utf-8") as f:
        f.write("{ invalid json }")

    # 例外が再送出されることを確認
    with pytest.raises(json.JSONDecodeError):
        learning_unified._load_constitution()


def test_add_to_content_policy_exception(temp_branding_env):
    """_add_to_content_policy 内部での例外発生時の挙動をテスト"""
    # _load_constitution が OSError を投げるようにモック化
    with patch.object(learning_unified, "_load_constitution", side_effect=OSError("mocked error")):
        # 例外がキャッチされ、処理が安全に終了することを確認
        learning_unified._add_to_content_policy("dummy_tag", "dummy_reason")


def test_add_to_keywords_exception(temp_branding_env):
    """_add_to_keywords 内部での例外発生時の挙動をテスト"""
    # _load_constitution が OSError を投げるようにモック化
    with patch.object(learning_unified, "_load_constitution", side_effect=OSError("mocked error")):
        # 例外がキャッチされ、処理が安全に終了することを確認
        learning_unified._add_to_keywords("dummy_keyword")


def test_update_design_tokens_success(temp_branding_env):
    """update_design_tokens の正常系および変更履歴の記録をテスト"""
    updates = {"font_size": 24, "font_color": "#ffffff"}
    res = learning_unified.update_design_tokens(
        mood="elegant",
        updates=updates,
        source="manual"
    )
    assert res["status"] == "updated"
    assert res["mood"] == "elegant"
    assert res["updates"] == updates

    # constitution.json にトークンが正しく保存されたことを確認
    constitution = learning_unified._load_constitution()
    assert constitution["design_tokens"]["elegant"]["font_size"] == 24
    assert constitution["design_tokens"]["elegant"]["font_color"] == "#ffffff"

    # evolution_log.json に変更履歴が記録されたことを確認
    log = learning_unified._load_evolution_log()
    assert len(log["token_changes"]) == 1
    assert log["token_changes"][0]["mood"] == "elegant"
    assert log["token_changes"][0]["updates"] == updates
    assert log["token_changes"][0]["source"] == "manual"


def test_update_design_tokens_nested_dict(temp_branding_env):
    """update_design_tokens で辞書型のネストされた値の更新をテスト"""
    # 事前に辞書型のトークンを設定
    constitution = learning_unified._load_constitution()
    constitution["design_tokens"] = {
        "elegant": {
            "subtitle_style": {
                "font": "Inter",
                "size": 18
            }
        }
    }
    learning_unified._save_constitution(constitution)

    # ネストされた値を部分更新
    updates = {
        "subtitle_style": {
            "size": 22,
            "color": "#000000"
        }
    }
    res = learning_unified.update_design_tokens(
        mood="elegant",
        updates=updates
    )
    assert res["status"] == "updated"

    # size が更新され、font が維持され、color が追加されていることを確認
    constitution = learning_unified._load_constitution()
    style = constitution["design_tokens"]["elegant"]["subtitle_style"]
    assert style["font"] == "Inter"
    assert style["size"] == 22
    assert style["color"] == "#000000"


def test_update_design_tokens_exception(temp_branding_env):
    """update_design_tokens での例外発生時の挙動をテスト"""
    # _load_constitution が OSError を投げるようにモック化
    with patch.object(learning_unified, "_load_constitution", side_effect=OSError("mocked error")):
        res = learning_unified.update_design_tokens(mood="elegant", updates={})
        assert res["status"] == "error"
        assert "mocked error" in res["error"]


def test_prevent_data_loss_on_corrupt_file(temp_branding_env):
    """破損したファイルが存在するときに更新が走っても、データ消失・上書きを行わないことをテスト"""
    # 破損させる（不正なJSON）
    with open(learning_unified._constitution_path, "w", encoding="utf-8") as f:
        f.write("{ corrupt json ")

    # この状態で content_policy の追加を試みる
    learning_unified._add_to_content_policy("style_tag", "reason")

    # ファイルの中身が上書きされて上書き保存されてしまっていないか（破損したまま残っている＝上書きされていない）を確認
    with open(learning_unified._constitution_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert content == "{ corrupt json "


def test_get_director_profile(temp_branding_env):
    """get_director_profile の結果集計および好悪の抽出をテスト"""
    # 好み (approve > reject) となるタグ
    for _ in range(3):
        learning_unified.record_decision(
            decision_type="approve", target="target1", outcome="approve", tags=["like_tag"]
        )
    learning_unified.record_decision(
        decision_type="reject", target="target1", outcome="reject", tags=["like_tag"]
    )

    # 嫌い (reject > approve) となるタグ
    for _ in range(2):
        learning_unified.record_decision(
            decision_type="reject", target="target2", outcome="reject", tags=["dislike_tag"]
        )

    # 哲学 (philosophies) を手動で evolution_log.json に書き込み
    log = learning_unified._load_evolution_log()
    log["philosophies"] = ["Keep it simple", "High contrast subtitle"]
    learning_unified._save_evolution_log(log)

    # プロファイルを取得
    profile = learning_unified.get_director_profile()
    assert "like_tag" in profile["preferences"]
    assert "dislike_tag" in profile["dislikes"]
    assert profile["total_decisions"] == 6
    assert "Keep it simple" in profile["philosophies"]
    assert "High contrast subtitle" in profile["philosophies"]


def test_add_to_keywords_on_corrupt_file(temp_branding_env):
    """破損したファイルが存在するときに brand personality keywords の追加が走っても、データ消失・上書きを行わないことをテスト"""
    # 破損させる（不正なJSON）
    with open(learning_unified._constitution_path, "w", encoding="utf-8") as f:
        f.write("{ corrupt json ")

    # この状態で keywords の追加を試みる
    learning_unified._add_to_keywords("brand_keyword")

    # ファイルの中身が上書きされて上書き保存されてしまっていないか（破損したまま残っている＝上書きされていない）を確認
    with open(learning_unified._constitution_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert content == "{ corrupt json "


def test_append_to_evolution_log_type_error(temp_branding_env):
    """_append_to_evolution_log で TypeError/AttributeError が発生したときに再送出されることをテスト"""
    with patch.object(learning_unified, "_load_evolution_log", return_value=None):
        with pytest.raises(AttributeError):
            learning_unified._append_to_evolution_log({"entry": "test"})


def test_add_to_content_policy_type_error(temp_branding_env):
    """_add_to_content_policy で TypeError/AttributeError が発生したときに再送出されることをテスト"""
    with patch.object(learning_unified, "_load_constitution", return_value=None):
        with pytest.raises(AttributeError):
            learning_unified._add_to_content_policy("style_tag", "reason")


def test_add_to_keywords_type_error(temp_branding_env):
    """_add_to_keywords で TypeError/AttributeError が発生したときに再送出されることをテスト"""
    with patch.object(learning_unified, "_load_constitution", return_value=None):
        with pytest.raises(AttributeError):
            learning_unified._add_to_keywords("brand_keyword")


def test_update_design_tokens_type_error(temp_branding_env):
    """update_design_tokens で TypeError/AttributeError が発生したときに再送出されることをテスト"""
    with patch.object(learning_unified, "_load_constitution", return_value=None):
        with pytest.raises(AttributeError):
            learning_unified.update_design_tokens("elegant", {"key": "val"})


def test_record_token_change_type_error(temp_branding_env):
    """_record_token_change で TypeError/AttributeError が発生したときに再送出されることをテスト"""
    with patch.object(learning_unified, "_load_evolution_log", return_value=None):
        with pytest.raises(AttributeError):
            learning_unified._record_token_change("elegant", {"key": "val"}, "manual")
