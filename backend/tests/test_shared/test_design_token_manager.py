import os
import json
import logging
from pathlib import Path
import pytest
from unittest.mock import patch

from design_system.design_token_manager import DesignTokenManager

@pytest.fixture
def mock_branding_env(tmp_path):
    """DesignTokenManagerの各ファイルパスを一時ディレクトリのモックに差し替えるフィクスチャ"""
    # モック用フォルダ作成
    branding_dir = tmp_path / "branding"
    branding_dir.mkdir()
    frontend_src_dir = tmp_path / "frontend" / "src"
    frontend_src_dir.mkdir(parents=True)
    
    # モック用ファイルパス
    constitution_path = branding_dir / "constitution.json"
    history_path = branding_dir / "design_tokens_history.json"
    evolution_log_path = branding_dir / "evolution_log.json"
    design_tokens_path = frontend_src_dir / "design_tokens.json"
    
    # 初期データ書き込み
    constitution_data = {
        "channel_name": "TestChannel",
        "design_tokens": {
            "elegant": {
                "color_palette": {"main": "#7C3AED", "accent": "#10B981"},
                "typography": {"font_family": "Outfit"},
                "motion": {"duration": "0.3s"},
                "imagen_prompt_suffix": "elegant suffix",
                "veo_prompt_suffix": "elegant veo suffix"
            },
            "dynamic": {
                "color_palette": {"main": "#EF4444"},
                "typography": {"font_family": "Inter"}
            }
        }
    }
    with open(constitution_path, "w", encoding="utf-8") as f:
        json.dump(constitution_data, f, ensure_ascii=False, indent=2)
        
    frontend_tokens_data = {
        "themes": {
            "light": {
                "color": {
                    "bg": {"primary": "#FAFAF9"},
                    "text": {"primary": "#1e293b"}
                },
                "typography": {"font-body": "Noto Sans JP"}
            },
            "dark": {
                "color": {
                    "bg": {"primary": "#0d0d0f"}
                },
                "typography": {"font-body": "Noto Sans JP"}
            }
        }
    }
    with open(design_tokens_path, "w", encoding="utf-8") as f:
        json.dump(frontend_tokens_data, f, ensure_ascii=False, indent=2)
        
    # テスト対象のインスタンスを生成してパスを差し替える
    manager = DesignTokenManager()
    manager._branding_dir = branding_dir
    manager._constitution_path = constitution_path
    manager._history_path = history_path
    manager._evolution_log_path = evolution_log_path
    manager._design_tokens_path = design_tokens_path
    
    return manager

def test_get_tokens_success(mock_branding_env):
    manager = mock_branding_env
    # 正常に指定したムードのトークンが取得できること
    tokens = manager.get_tokens("dynamic")
    assert tokens["color_palette"]["main"] == "#EF4444"
    
    # defaultのelegantが取得できること
    tokens_elegant = manager.get_tokens("elegant")
    assert tokens_elegant["color_palette"]["main"] == "#7C3AED"

def test_get_tokens_fallback(mock_branding_env, caplog):
    manager = mock_branding_env
    with caplog.at_level(logging.WARNING):
        tokens = manager.get_tokens("invalid_mood")
        # 存在しないムードが指定された場合、elegantにフォールバックすること
        assert tokens["color_palette"]["main"] == "#7C3AED"
        assert "Mood 'invalid_mood' not found, falling back to elegant" in caplog.text

def test_get_all_tokens(mock_branding_env):
    manager = mock_branding_env
    all_tokens = manager.get_all_tokens()
    assert "elegant" in all_tokens
    assert "dynamic" in all_tokens

def test_get_specific_properties(mock_branding_env):
    manager = mock_branding_env
    assert manager.get_color_palette("elegant") == {"main": "#7C3AED", "accent": "#10B981"}
    assert manager.get_typography("elegant") == {"font_family": "Outfit"}
    assert manager.get_motion("elegant") == {"duration": "0.3s"}

def test_get_prompt_suffix(mock_branding_env):
    manager = mock_branding_env
    assert manager.get_prompt_suffix("elegant", "imagen") == "elegant suffix"
    assert manager.get_prompt_suffix("elegant", "veo") == "elegant veo suffix"
    assert manager.get_prompt_suffix("elegant", "other") == ""

def test_update_tokens_new_key_and_deep_merge(mock_branding_env):
    manager = mock_branding_env
    # 既存の辞書のマージ
    updates = {
        "color_palette": {"main": "#000000", "new_color": "#ffffff"},
        "typography": "new_typo_string",  # 辞書から文字列への置き換えテスト
        "new_config": {"key": "val"}
    }
    
    result = manager.update_tokens("elegant", updates, source="test", reason="unit test update")
    assert result["status"] == "updated"
    assert result["source"] == "test"
    
    # 更新が反映されていること
    tokens = manager.get_tokens("elegant")
    assert tokens["color_palette"]["main"] == "#000000"
    assert tokens["color_palette"]["new_color"] == "#ffffff"
    assert tokens["color_palette"]["accent"] == "#10B981" # 既存が残っていること（deep merge）
    assert tokens["typography"] == "new_typo_string"
    assert tokens["new_config"] == {"key": "val"}
    
    # 履歴が記録されていること
    history = manager.get_change_history()
    assert len(history) == 1
    assert history[0]["mood"] == "elegant"
    assert history[0]["updates"] == updates
    assert history[0]["old_values"]["color_palette"] == {"main": "#7C3AED", "accent": "#10B981"}
    assert history[0]["old_values"]["typography"] == {"font_family": "Outfit"}
    assert "new_config" not in history[0]["old_values"] # 元々存在しなかったキー

def test_load_constitution_cache(mock_branding_env):
    manager = mock_branding_env
    # 初回ロード
    tokens1 = manager.get_tokens("elegant")
    
    # キャッシュから読まれていることを確認するために、mtimeが変わらない限りファイルを書き換えてもキャッシュが使われるかテスト
    # 直接ファイルを書き換える
    with open(manager._constitution_path, "w", encoding="utf-8") as f:
        json.dump({"design_tokens": {"elegant": {"color_palette": {"main": "#CHANGED"}}}}, f)
        
    # mtimeを戻す（キャッシュのmtimeと同じかそれ以下にする）
    os.utime(manager._constitution_path, (manager._cache_mtime, manager._cache_mtime))
    
    tokens2 = manager.get_tokens("elegant")
    assert tokens2["color_palette"]["main"] == "#7C3AED" # キャッシュが使われている
    
    # mtimeを新しくする
    new_mtime = manager._cache_mtime + 10.0
    os.utime(manager._constitution_path, (new_mtime, new_mtime))
    
    tokens3 = manager.get_tokens("elegant")
    assert tokens3["color_palette"]["main"] == "#CHANGED" # キャッシュが無効化され、再ロードされた

def test_load_constitution_exception(mock_branding_env, caplog):
    manager = mock_branding_env
    # constitution_path を無効なパスにするか、ファイルを壊す
    with open(manager._constitution_path, "w", encoding="utf-8") as f:
        f.write("invalid json")
        
    # キャッシュをクリアしておく
    manager._cache = None
    
    with caplog.at_level(logging.ERROR):
        tokens = manager.get_all_tokens()
        assert tokens == {}
        assert "Failed to parse constitution JSON" in caplog.text

def test_load_history_exception_and_empty(mock_branding_env):
    manager = mock_branding_env
    # 履歴ファイルが存在しない初期状態
    assert not manager._history_path.exists()
    history = manager._load_history()
    assert history == {"changes": []}
    
    # 履歴ファイルが壊れている場合
    manager._history_path.write_text("invalid json", encoding="utf-8")
    history_err = manager._load_history()
    assert history_err == {"changes": []}

def test_get_change_history_limit(mock_branding_env):
    manager = mock_branding_env
    # 3回更新して履歴を作る
    manager.update_tokens("elegant", {"k1": "v1"}, reason="1")
    manager.update_tokens("elegant", {"k2": "v2"}, reason="2")
    manager.update_tokens("elegant", {"k3": "v3"}, reason="3")
    
    # limit=2
    history_limit2 = manager.get_change_history(limit=2)
    assert len(history_limit2) == 2
    assert history_limit2[0]["reason"] == "2"
    assert history_limit2[1]["reason"] == "3"
    
    # limit=0 (全件)
    history_all = manager.get_change_history(limit=0)
    assert len(history_all) == 3

def test_record_to_evolution_log_exception(mock_branding_env, caplog):
    manager = mock_branding_env
    # evolution_log_pathへのアクセスを不可能にして例外を発生させる
    with patch("builtins.open", side_effect=PermissionError("permission denied")):
        with caplog.at_level(logging.WARNING):
            manager._record_to_evolution_log("elegant", {"k": "v"}, {}, "test", "reason")
            assert "Failed to write design token change to evolution_log" in caplog.text

def test_get_frontend_tokens_non_existent_and_exception(mock_branding_env, caplog):
    manager = mock_branding_env
    # ファイルを削除する
    manager._design_tokens_path.unlink()
    assert manager.get_frontend_tokens() is None
    
    # 例外を発生させる
    with patch.object(Path, "exists", side_effect=OSError("filesystem error")):
        with caplog.at_level(logging.WARNING):
            assert manager.get_frontend_tokens() is None
            assert "Failed to read frontend design tokens" in caplog.text

def test_update_frontend_tokens_failures(mock_branding_env):
    manager = mock_branding_env
    # 1. design_tokens.jsonが存在しない場合
    manager._design_tokens_path.unlink()
    res1 = manager.update_frontend_tokens("light", "color", {"primary": "#000"})
    assert res1["status"] == "error"
    assert "design_tokens.json not found" in res1["message"]
    
    # 初期状態に戻す
    frontend_tokens_data = {
        "themes": {
            "light": {
                "color": {
                    "bg": {"primary": "#FAFAF9"},
                    "text": {"primary": "#1e293b"}
                }
            }
        }
    }
    with open(manager._design_tokens_path, "w", encoding="utf-8") as f:
        json.dump(frontend_tokens_data, f, ensure_ascii=False, indent=2)
        
    # 2. themeが存在しない場合
    res2 = manager.update_frontend_tokens("invalid_theme", "color", {"primary": "#000"})
    assert res2["status"] == "error"
    assert "theme 'invalid_theme' not found" in res2["message"]
    
    # 3. categoryが存在しない場合
    res3 = manager.update_frontend_tokens("light", "invalid_category", {"primary": "#000"})
    assert res3["status"] == "error"
    assert "category 'invalid_category' not found in theme 'light'" in res3["message"]

def test_update_frontend_tokens_success(mock_branding_env):
    manager = mock_branding_env
    updates = {
        "bg": {"primary": "#000000", "new_bg": "#ffffff"},
        "new_key": "new_val"
    }
    
    res = manager.update_frontend_tokens("light", "color", updates, source="frontend_test", reason="update color")
    assert res["status"] == "updated"
    assert res["theme"] == "light"
    assert res["category"] == "color"
    
    # 反映内容の確認
    tokens = manager.get_frontend_tokens()
    color_cat = tokens["themes"]["light"]["color"]
    assert color_cat["bg"]["primary"] == "#000000"
    assert color_cat["bg"]["new_bg"] == "#ffffff"
    assert color_cat["new_key"] == "new_val"
    
    # evolution_log に記録されていること
    with open(manager._evolution_log_path, "r", encoding="utf-8") as f:
        log_data = json.load(f)
    assert len(log_data["entries"]) == 1
    assert log_data["entries"][0]["type"] == "design_token_change"
    assert log_data["entries"][0]["detail"]["mood"] == "light/color"
    assert log_data["entries"][0]["detail"]["updates"] == updates

def test_get_prompt_suffix_missing(mock_branding_env):
    manager = mock_branding_env
    # imagen_prompt_suffix や veo_prompt_suffix が定義されていない場合の挙動
    assert manager.get_prompt_suffix("dynamic", "imagen") == ""
    assert manager.get_prompt_suffix("dynamic", "veo") == ""

def test_update_tokens_shallow_merge_behavior(mock_branding_env):
    manager = mock_branding_env
    # 2階層目以上のネストされた辞書が update_tokens で上書きされる（shallow merge）挙動を検証
    # 初期状態で color_palette: {main, accent}
    # まず 2階層目の辞書を挿入
    updates1 = {
        "nested_dict": {"level2": {"level3": "value3"}}
    }
    manager.update_tokens("elegant", updates1)
    
    # 2階層目に別のキーを適用しようとすると、level2 ごと上書きされ level3 は消える挙動をテスト
    updates2 = {
        "nested_dict": {"level2": {"level3_another": "value3_another"}}
    }
    manager.update_tokens("elegant", updates2)
    
    tokens = manager.get_tokens("elegant")
    assert "level3_another" in tokens["nested_dict"]["level2"]
    assert "level3" not in tokens["nested_dict"]["level2"]  # shallow mergeにより上書きされている

def test_record_to_evolution_log_corrupted_json(mock_branding_env, caplog):
    manager = mock_branding_env
    # evolution_log_path が破損した JSON の場合の例外ハンドリングをテスト
    manager._evolution_log_path.write_text("broken json file content", encoding="utf-8")
    
    with caplog.at_level(logging.WARNING):
        manager._record_to_evolution_log("elegant", {"k": "v"}, {}, "test", "reason")
        # 例外がキャッチされ、警告ログが出力されていること
        assert "Failed to parse evolution_log JSON" in caplog.text
        # ファイルは書き換わらずに元の壊れた状態を維持していること
        assert manager._evolution_log_path.read_text(encoding="utf-8") == "broken json file content"


def test_load_constitution_file_not_found(mock_branding_env, caplog):
    manager = mock_branding_env
    if manager._constitution_path.exists():
        manager._constitution_path.unlink()
    
    manager._cache = None
    with caplog.at_level(logging.WARNING):
        tokens = manager.get_all_tokens()
        assert tokens == {}
        assert "Constitution file not found" in caplog.text

def test_load_constitution_permission_error(mock_branding_env, caplog):
    manager = mock_branding_env
    manager._cache = None
    with patch("builtins.open", side_effect=PermissionError("Permission denied")):
        with caplog.at_level(logging.ERROR):
            tokens = manager.get_all_tokens()
            assert tokens == {}
            assert "Failed to access constitution file" in caplog.text

def test_record_to_evolution_log_json_decode_error(mock_branding_env, caplog):
    manager = mock_branding_env
    # evolution_log_path に壊れたJSONを書き込む
    manager._evolution_log_path.write_text("invalid json", encoding="utf-8")
    
    with caplog.at_level(logging.WARNING):
        manager._record_to_evolution_log("elegant", {"k": "v"}, {}, "test", "reason")
        assert "Failed to parse evolution_log JSON" in caplog.text

def test_record_to_evolution_log_permission_error(mock_branding_env, caplog):
    manager = mock_branding_env
    # evolution_log_path への書き込み時に例外を発生させる
    with patch("builtins.open", side_effect=PermissionError("Permission denied")):
        with caplog.at_level(logging.WARNING):
            manager._record_to_evolution_log("elegant", {"k": "v"}, {}, "test", "reason")
            assert "Failed to write design token change to evolution_log" in caplog.text

def test_get_frontend_tokens_json_decode_error(mock_branding_env, caplog):
    manager = mock_branding_env
    manager._design_tokens_path.write_text("invalid json", encoding="utf-8")
    
    with caplog.at_level(logging.WARNING):
        tokens = manager.get_frontend_tokens()
        assert tokens is None
        assert "Failed to parse frontend design tokens JSON" in caplog.text

def test_get_frontend_tokens_permission_error(mock_branding_env, caplog):
    manager = mock_branding_env
    with patch("builtins.open", side_effect=PermissionError("Permission denied")):
        with caplog.at_level(logging.WARNING):
            tokens = manager.get_frontend_tokens()
            assert tokens is None
            assert "Failed to read frontend design tokens" in caplog.text


def test_update_tokens_invalid_type_validation(mock_branding_env):
    manager = mock_branding_env
    with pytest.raises(TypeError, match="updates must be a dictionary"):
        manager.update_tokens("elegant", "invalid_updates")


def test_update_frontend_tokens_invalid_type_validation(mock_branding_env):
    manager = mock_branding_env
    with pytest.raises(TypeError, match="updates must be a dictionary"):
        manager.update_frontend_tokens("light", "color", "invalid_updates")


def test_update_frontend_tokens_merge_edge_cases(mock_branding_env):
    manager = mock_branding_env
    # 1. 既存が辞書で、更新データが非辞書（文字列）の場合（上書きされること）
    updates_str = {"bg": "#CHANGED_TO_STRING"}
    res1 = manager.update_frontend_tokens("light", "color", updates_str)
    assert res1["status"] == "updated"
    
    tokens = manager.get_frontend_tokens()
    assert tokens["themes"]["light"]["color"]["bg"] == "#CHANGED_TO_STRING"

    # 2. 既存が非辞書で、更新データが辞書の場合（上書きされること）
    updates_dict = {"bg": {"primary": "#NEW_HEX"}}
    res2 = manager.update_frontend_tokens("light", "color", updates_dict)
    assert res2["status"] == "updated"
    
    tokens2 = manager.get_frontend_tokens()
    assert tokens2["themes"]["light"]["color"]["bg"] == {"primary": "#NEW_HEX"}


def test_update_tokens_merge_edge_cases(mock_branding_env):
    manager = mock_branding_env
    # 1. 既存が辞書で、更新データが非辞書の場合（上書きされること）
    updates_str = {"color_palette": "#NOT_A_DICT"}
    manager.update_tokens("elegant", updates_str)
    tokens = manager.get_tokens("elegant")
    assert tokens["color_palette"] == "#NOT_A_DICT"

    # 2. 既存が非辞書で、更新データが辞書の場合（上書きされること）
    updates_dict = {"color_palette": {"main": "#HEX"}}
    manager.update_tokens("elegant", updates_dict)
    tokens2 = manager.get_tokens("elegant")
    assert tokens2["color_palette"] == {"main": "#HEX"}

