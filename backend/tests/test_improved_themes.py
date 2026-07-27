import os
import json
from pathlib import Path
from unittest.mock import patch
import sys
import runpy

# テスト対象をインポートできるように PYTHONPATH を調整
sys.path.insert(0, str(Path(__file__).parent.parent))
import improved_themes

def test_improved_themes_data():
    # IMPROVED_THEMESが正しい構造を持っていることを確認
    assert "scene01" in improved_themes.IMPROVED_THEMES
    assert "scene03" in improved_themes.IMPROVED_THEMES
    assert "scene04" in improved_themes.IMPROVED_THEMES
    
    # 構造のチェック
    for scene, data in improved_themes.IMPROVED_THEMES.items():
        assert "themes" in data
        for theme in data["themes"]:
            assert "id" in theme
            assert "original" in theme
            assert "improved" in theme
            assert "timing" in theme
            assert "description" in theme

def test_save_improved_themes(tmp_path, monkeypatch, capsys):
    # 保存先のパスを tmp_path に変更して副作用を防ぐ
    output_file = tmp_path / "improved_themes.json"
    monkeypatch.setenv("IMPROVED_THEMES_OUTPUT_FILE", str(output_file))
            
    res = improved_themes.save_improved_themes()
    
    # 戻り値の確認
    assert res == improved_themes.IMPROVED_THEMES
    
    # ファイルが作成されたことの確認
    assert output_file.exists()
    with open(output_file, 'r', encoding='utf-8') as f:
        saved_data = json.load(f)
        assert saved_data == improved_themes.IMPROVED_THEMES
        
    # 標準出力の確認
    captured = capsys.readouterr()
    assert "改善されたテーマテキスト一覧" in captured.out
    assert "シーン" in captured.out

def test_main_block(tmp_path, monkeypatch, capsys):
    # 保存先のパスを tmp_path に変更して副作用を防ぐ
    output_file = tmp_path / "main_improved_themes.json"
    monkeypatch.setenv("IMPROVED_THEMES_OUTPUT_FILE", str(output_file))

    # improved_themes.pyの __main__ ブロックをカバーする
    # 既存の sys.modules から削除して再ロード実行されるようにする
    if "improved_themes" in sys.modules:
        del sys.modules["improved_themes"]
        
    runpy.run_module("improved_themes", run_name="__main__")
    
    captured = capsys.readouterr()
    assert "改善ポイント" in captured.out
    assert output_file.exists()


def test_save_improved_themes_mkdir_error():
    # 親ディレクトリ作成時に例外が発生した場合の挙動
    with patch("improved_themes.Path.mkdir") as mock_mkdir:
        mock_mkdir.side_effect = FileExistsError("File exists as a file")
        
        import pytest
        with pytest.raises(FileExistsError):
            improved_themes.save_improved_themes()


def test_save_improved_themes_write_error():
    # ファイルオープン/書き込み時に例外が発生した場合の挙動
    with patch("builtins.open") as mock_open:
        mock_open.side_effect = PermissionError("Permission denied")
        
        import pytest
        with pytest.raises(PermissionError):
            improved_themes.save_improved_themes()


def test_save_improved_themes_io_error_handling(capsys):
    # OSError が発生した際のエラーメッセージ表示と再スローの検証
    with patch("builtins.open") as mock_open:
        mock_open.side_effect = OSError("Disk full")
        
        import pytest
        with pytest.raises(OSError, match="Disk full"):
            improved_themes.save_improved_themes()
            
        captured = capsys.readouterr()
        assert "Failed to save improved themes" in captured.out


def test_export_themes_as_srt_io_error_handling(tmp_path, capsys):
    # export_themes_as_srt で OSError が発生した際のハンドリング検証
    test_themes = {
        "scene99": {
            "themes": [
                {
                    "id": "scene99_theme1",
                    "original": "テスト元",
                    "improved": "テスト改善",
                    "timing": "1:00-2:30",
                    "description": "テスト説明"
                }
            ]
        }
    }
    with patch("builtins.open") as mock_open:
        mock_open.side_effect = OSError("Write protected")
        
        import pytest
        with pytest.raises(OSError, match="Write protected"):
            improved_themes.export_themes_as_srt(test_themes, output_dir=tmp_path)
            
        captured = capsys.readouterr()
        assert "Failed to export SRT subtitle" in captured.out




def test_convert_time_to_srt_format():
    from improved_themes import convert_time_to_srt_format, _parse_time_code, _normalize_time_components
    assert convert_time_to_srt_format("0:00") == "00:00:00,000"
    assert convert_time_to_srt_format("2:45") == "00:02:45,000"
    assert convert_time_to_srt_format("10:00") == "00:10:00,000"
    assert convert_time_to_srt_format("1:02:45") == "01:02:45,000"
    
    # 新設したヘルパー関数の検証
    assert _parse_time_code("0:00") == (0, 0, 0)
    assert _parse_time_code("1:02:45") == (1, 2, 45)
    assert _normalize_time_components(0, 0, 60) == (0, 1, 0)
    assert _normalize_time_components(0, 59, 60) == (1, 0, 0)
    
    import pytest
    with pytest.raises(ValueError):
        convert_time_to_srt_format("abc")
    with pytest.raises(ValueError):
        convert_time_to_srt_format("12:34:56:78")
    with pytest.raises(ValueError):
        convert_time_to_srt_format("")


def test_export_themes_as_srt(tmp_path):
    from improved_themes import export_themes_as_srt
    
    test_themes = {
        "scene99": {
            "themes": [
                {
                    "id": "scene99_theme1",
                    "original": "テスト元",
                    "improved": "テスト改善",
                    "timing": "1:00-2:30",
                    "description": "テスト説明"
                }
            ]
        }
    }
    
    srt_files = export_themes_as_srt(test_themes, output_dir=tmp_path)
    assert len(srt_files) == 1
    
    srt_file = srt_files[0]
    assert srt_file.name == "scene99_themes.srt"
    assert srt_file.exists()
    
    content = srt_file.read_text(encoding="utf-8")
    assert "1" in content
    assert "00:01:00,000 --> 00:02:30,000" in content
    assert "テスト改善" in content
    assert "テスト説明" in content


def test_theme_utilities():
    from improved_themes import get_theme_by_id, get_themes_by_scene, search_themes, add_or_update_theme
    
    test_themes = {
        "scene99": {
            "themes": [
                {
                    "id": "theme_a",
                    "original": "りんごの基本",
                    "improved": "美味しい林檎の選び方",
                    "timing": "0:00-1:00",
                    "description": "青森のりんごについて紹介"
                },
                {
                    "id": "theme_b",
                    "original": "みかんの未来",
                    "improved": "愛媛の蜜柑の魅力",
                    "timing": "1:00-2:00",
                    "description": "みかんの甘さの秘密"
                }
            ]
        }
    }
    
    # get_theme_by_id
    assert get_theme_by_id("theme_a", test_themes)["original"] == "りんごの基本"
    assert get_theme_by_id("non_existent", test_themes) is None
    
    # get_themes_by_scene
    assert len(get_themes_by_scene("scene99", test_themes)) == 2
    assert len(get_themes_by_scene("scene_invalid", test_themes)) == 0
    
    # search_themes
    assert len(search_themes("林檎", test_themes)) == 1
    assert len(search_themes("みかん", test_themes)) == 1
    assert len(search_themes("バナナ", test_themes)) == 0
    
    # add_or_update_theme
    # 追加
    updated = add_or_update_theme("scene99", "バナナの話", "絶品バナナ", "2:00-3:00", "バナナの紹介", target_theme_id="theme_c", themes_data=test_themes)
    assert len(get_themes_by_scene("scene99", updated)) == 3
    assert get_theme_by_id("theme_c", updated)["improved"] == "絶品バナナ"
    
    # 更新
    updated = add_or_update_theme("scene99", "りんごの基本", "超美味しい林檎", "0:00-1:00", "青森のりんごについて紹介", target_theme_id="theme_a", themes_data=updated)
    assert get_theme_by_id("theme_a", updated)["improved"] == "超美味しい林檎"


def test_convert_time_to_srt_format_extra_errors():
    from improved_themes import convert_time_to_srt_format
    import pytest
    
    # L118-119: コロンが2つで非整数の場合
    with pytest.raises(ValueError, match="Invalid non-integer value"):
        convert_time_to_srt_format("a:b")
    
    # L123-124: コロンが3つで非整数の場合
    with pytest.raises(ValueError, match="Invalid non-integer value"):
        convert_time_to_srt_format("a:b:c")


def test_export_themes_as_srt_defaults_and_skips(tmp_path, capsys):
    from improved_themes import export_themes_as_srt
    
    # L140: themes_data が None の場合 (IMPROVED_THEMESを使用)
    srt_files = export_themes_as_srt(None, output_dir=tmp_path)
    assert len(srt_files) > 0
    for f in srt_files:
        assert f.exists()
        
    # L150: themes リストが空の場合の skip
    # L158: timing にハイフンがない場合の skip
    # L164-167: format_srt_time が ValueError の場合の skip + 警告出力
    custom_themes = {
        "scene_empty": {
            "themes": []
        },
        "scene_skip": {
            "themes": [
                {
                    "id": "skip_1",
                    "original": "テスト",
                    "improved": "テスト改善",
                    "timing": "0:00",  # ハイフンなし
                    "description": "テスト説明"
                },
                {
                    "id": "skip_2",
                    "original": "テスト2",
                    "improved": "テスト改善2",
                    "timing": "abc-def",  # ValueError を発生させる
                    "description": "テスト説明2"
                }
            ]
        }
    }
    
    srt_files_custom = export_themes_as_srt(custom_themes, output_dir=tmp_path)
    assert len(srt_files_custom) == 0  # skip されたためファイルは出力されない
    
    captured = capsys.readouterr()
    assert "⚠️ Warning: Skip invalid timing 'abc-def'" in captured.out


def test_utilities_default_themes():
    from improved_themes import get_theme_by_id, get_themes_by_scene, search_themes
    
    # L187: get_theme_by_id で themes_data が None の場合
    theme = get_theme_by_id("scene01_theme1")
    assert theme is not None
    assert theme["original"] == "対談：手書き文字の価値"
    
    # L199: get_themes_by_scene で themes_data が None の場合
    themes = get_themes_by_scene("scene01")
    assert len(themes) == 3
    
    # L209: search_themes で themes_data が None の場合
    results = search_themes("筆職人")
    assert len(results) == 1
    assert results[0]["id"] == "scene01_theme2"


def test_add_or_update_theme_defaults():
    from improved_themes import add_or_update_theme
    
    # L230: themes_data が None の場合
    # L236: 存在しない scene_id の場合 (新規作成)
    # L242: theme_id が None の場合 (自動生成)
    updated = add_or_update_theme(
        scene_id="scene99",
        original="新規テーマ元",
        improved="新規テーマ改善",
        timing="1:00-2:00",
        description="新規テーマ説明",
        target_theme_id=None,
        themes_data=None
    )
    
    # scene99 が作られ、そこにテーマが追加されているはず
    assert "scene99" in updated
    themes_99 = updated["scene99"]["themes"]
    assert len(themes_99) == 1
    
    new_theme = themes_99[0]
    assert new_theme["id"] == "scene99_theme1"
    assert new_theme["original"] == "新規テーマ元"
    
    # デフォルトの IMPROVED_THEMES は変更されていないはず
    import improved_themes
    assert "scene99" not in improved_themes.IMPROVED_THEMES


def test_save_improved_themes_with_explicit_args(tmp_path, capsys):
    from improved_themes import save_improved_themes
    
    custom_themes = {
        "scene99": {
            "themes": [
                {
                    "id": "scene99_theme_explicit",
                    "original": "明示的オリジナル",
                    "improved": "明示的改善",
                    "timing": "0:00-1:00",
                    "description": "明示的説明"
                }
            ]
        }
    }
    
    output_file = tmp_path / "explicit_themes.json"
    
    # 引数を明示的に指定して実行
    res = save_improved_themes(themes_data=custom_themes, output_file=output_file)
    
    # 戻り値の確認
    assert res == custom_themes
    
    # ファイルが作成されたことの確認
    assert output_file.exists()
    with open(output_file, 'r', encoding='utf-8') as f:
        saved_data = json.load(f)
        assert saved_data == custom_themes
        
    # 標準出力の確認
    captured = capsys.readouterr()
    assert "改善されたテーマテキスト一覧" in captured.out
    assert "シーン99" in captured.out


def test_improved_themes_edge_cases(tmp_path):
    from improved_themes import (
        convert_time_to_srt_format,
        export_themes_as_srt,
        save_improved_themes,
        get_theme_by_id,
        get_themes_by_scene,
        search_themes,
        add_or_update_theme
    )
    import pytest

    # --- convert_time_to_srt_format エッジケース ---
    # None入力
    with pytest.raises((TypeError, AttributeError)):
        convert_time_to_srt_format(None)
    
    # 値の正規化・繰り上がり
    assert convert_time_to_srt_format("0:60") == "00:01:00,000"
    assert convert_time_to_srt_format("59:60") == "01:00:00,000"
    assert convert_time_to_srt_format("23:59:60") == "24:00:00,000"
    assert convert_time_to_srt_format("100:00") == "01:40:00,000"
    
    # 不正フォーマット
    with pytest.raises(ValueError, match="Invalid non-integer value"):
        convert_time_to_srt_format(":")
    with pytest.raises(ValueError, match="Invalid non-integer value"):
        convert_time_to_srt_format("::")
    with pytest.raises(ValueError, match="Invalid time format"):
        convert_time_to_srt_format("1:2:3:4")

    # --- export_themes_as_srt エッジケース ---
    # 空辞書
    assert export_themes_as_srt({}, output_dir=tmp_path) == []
    
    # themes属性がないシーンデータ
    assert export_themes_as_srt({"scene01": {}}, output_dir=tmp_path) == []
    
    # themesの要素が辞書ではない場合
    invalid_structure = {"scene01": {"themes": ["not_a_dict"]}}
    with pytest.raises(AttributeError):
        export_themes_as_srt(invalid_structure, output_dir=tmp_path)
        
    # timing属性がない、またはNone
    missing_timing = {"scene01": {"themes": [{"id": "t1", "original": "o", "improved": "i", "description": "d"}]}}
    assert export_themes_as_srt(missing_timing, output_dir=tmp_path) == []
    
    none_timing = {"scene01": {"themes": [{"id": "t1", "original": "o", "improved": "i", "description": "d", "timing": None}]}}
    with pytest.raises(TypeError):
        export_themes_as_srt(none_timing, output_dir=tmp_path)

    # --- save_improved_themes エッジケース ---
    # 空データ
    empty_file = tmp_path / "empty_themes.json"
    res_empty = save_improved_themes(themes_data={}, output_file=empty_file)
    assert res_empty == {}
    assert empty_file.exists()
    
    # 不正な型での例外
    with pytest.raises(AttributeError):
        save_improved_themes(themes_data="invalid_string", output_file=tmp_path / "should_fail.json")

    # --- get_theme_by_id エッジケース ---
    # IDがNone/不正型/空
    assert get_theme_by_id(None) is None
    assert get_theme_by_id(123) is None
    assert get_theme_by_id("") is None
    
    # 構造が不正な場合
    with pytest.raises(AttributeError):
        get_theme_by_id("some_id", themes_data={"scene01": "not_dict_with_get"})

    # --- get_themes_by_scene エッジケース ---
    # None/不正型/空
    assert get_themes_by_scene(None) == []
    assert get_themes_by_scene(123) == []
    assert get_themes_by_scene("") == []

    # --- search_themes エッジケース ---
    # 空文字列 (全てマッチするはず)
    all_results = search_themes("")
    assert len(all_results) == 7
    
    # None入力
    with pytest.raises(AttributeError):
        search_themes(None)
        
    # 正常検索と大文字小文字混在
    shodoka_results = search_themes("書道家")
    assert len(shodoka_results) >= 1

    # --- add_or_update_theme エッジケース ---
    # バリデーションの確認
    # None入力や空文字、不正なtimingで例外が発生することを確認
    with pytest.raises(TypeError):
        add_or_update_theme(
            scene_id="scene99",
            original=None,
            improved="improved",
            timing="0:00-1:00",
            description="desc",
            themes_data={}
        )
    with pytest.raises(ValueError):
        add_or_update_theme(
            scene_id="scene99",
            original="original",
            improved="improved",
            timing="0:00-1:00",
            description="  ",
            themes_data={}
        )
    with pytest.raises(ValueError):
        # timingのフォーマット不正（ハイフンなし）
        add_or_update_theme(
            scene_id="scene99",
            original="original",
            improved="improved",
            timing="0:00",
            description="desc",
            themes_data={}
        )
    with pytest.raises(ValueError):
        # timingのフォーマット不正（非整数）
        add_or_update_theme(
            scene_id="scene99",
            original="original",
            improved="improved",
            timing="0:00-abc",
            description="desc",
            themes_data={}
        )

    # target_theme_id の型不正（非str）
    with pytest.raises(TypeError, match="'target_theme_id' must be a string"):
        add_or_update_theme(
            scene_id="scene99",
            original="original",
            improved="improved",
            timing="0:00-1:00",
            description="desc",
            target_theme_id=123,
            themes_data={}
        )

    # target_theme_id の値不正（空文字列）
    with pytest.raises(ValueError, match="'target_theme_id' cannot be empty or whitespace only"):
        add_or_update_theme(
            scene_id="scene99",
            original="original",
            improved="improved",
            timing="0:00-1:00",
            description="desc",
            target_theme_id="  ",
            themes_data={}
        )
        
    # 正常なデータでの追加・更新
    updated = add_or_update_theme(
        scene_id="scene99",
        original="original",
        improved="improved",
        timing="0:00-1:00",
        description="description",
        target_theme_id="theme_ok",
        themes_data={}
    )
    added_theme = updated["scene99"]["themes"][0]
    assert added_theme["original"] == "original"
    assert added_theme["improved"] == "improved"
    assert added_theme["id"] == "theme_ok"

