import sys
import os
import logging
import json
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

# Path setup to include backend parent (workspace root)
sys.path.insert(0, str(Path(__file__).parent.parent))

import backend.model_guardian as mg_module


@pytest.fixture
def dummy_workspace(tmp_path, monkeypatch):
    """スキャンテスト用のダミーファイル階層を構築する"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    
    # BACKEND_DIRを差し替えて relative_to がエラーにならないようにする
    monkeypatch.setattr(mg_module, "BACKEND_DIR", workspace)
    
    # 1. 検出対象の非推奨モデル名の直書き (ERROR)
    file1 = workspace / "bad_file.py"
    file1.write_text("model = 'gemini-1.5-pro'\n", encoding="utf-8")
    
    # 2. 許容パターン: コメント内
    file2 = workspace / "comment_ok.py"
    file2.write_text("# This uses gemini-1.5-pro inside a comment\n", encoding="utf-8")
    
    # 3. 許容パターン: get_model() 経由
    file3 = workspace / "get_model_ok.py"
    file3.write_text("MODEL = get_model('gemini-1.5-pro')\n", encoding="utf-8")
    
    # 4. 除外ディレクトリ: _deprecated
    dep_dir = workspace / "_deprecated"
    dep_dir.mkdir()
    file_dep = dep_dir / "dep_file.py"
    file_dep.write_text("model = 'gemini-1.5-pro'\n", encoding="utf-8")
    
    # 5. 除外ファイル: model_guardian.py 自身
    file_self = workspace / "model_guardian.py"
    file_self.write_text("model = 'gemini-1.5-pro'\n", encoding="utf-8")
    
    # 6. 定義ファイル: model_registry.py
    file_reg = workspace / "model_registry.py"
    file_reg.write_text("model = 'gemini-1.5-pro'\n", encoding="utf-8")
    
    # 7. 現行モデルの直書き (WARNING)
    file4 = workspace / "warning_file.py"
    file4.write_text("model = 'gemini-2.5-flash'\n", encoding="utf-8")
    
    return workspace


def test_model_guardian_scan_finds_bad_file(dummy_workspace):
    """bad_file.py の直書きモデルが ERROR として検出され、warning_file.py は WARNING として検出されること"""
    guardian = mg_module.ModelGuardian()
    issues = guardian.scan(root=dummy_workspace)
    
    # スキャンされたファイル数
    assert guardian._scanned_files == 4  # bad_file.py, comment_ok.py, get_model_ok.py, warning_file.py
    
    # 検出された問題の確認
    errors = [i for i in issues if i["severity"] == "ERROR"]
    warns = [i for i in issues if i["severity"] == "WARNING"]
    
    assert len(errors) == 1
    assert "bad_file.py" in errors[0]["file"]
    assert errors[0]["model"] == "gemini-1.5-pro"
    
    assert len(warns) == 1
    assert "warning_file.py" in warns[0]["file"]
    assert warns[0]["model"] == "gemini-2.5-flash"


def test_model_guardian_exclude_check():
    """_is_excludedが除外パターンに合致するファイルを正しく判別すること"""
    guardian = mg_module.ModelGuardian()
    
    # 除外されるべきもの
    assert guardian._is_excluded(Path("backend/archives/old_code.py")) is True
    assert guardian._is_excluded(Path("backend/__pycache__/some.pyc")) is True
    assert guardian._is_excluded(Path("backend/sub_deprecated/test.py")) is True
    
    # 除外されるべきではないもの
    assert guardian._is_excluded(Path("backend/services/good_service.py")) is False


def test_model_guardian_scan_io_error_handling(tmp_path, monkeypatch):
    """ファイル読み込み時に例外が発生した場合でも、処理がクラッシュせず安全にスキップされること"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    
    monkeypatch.setattr(mg_module, "BACKEND_DIR", workspace)
    
    bad_read_file = workspace / "unreadable.py"
    bad_read_file.write_text("some content\n", encoding="utf-8")
    
    guardian = mg_module.ModelGuardian()
    
    # read_textが例外を投げるようにモックする
    with patch.object(Path, "read_text", side_effect=PermissionError("Permission denied")):
        # 例外が発生するが、scan自体は正常終了する
        issues = guardian.scan(root=workspace)
        assert len(issues) == 0
        assert guardian._scanned_files == 1


def test_model_guardian_get_summary(dummy_workspace):
    """エラー検出時と未検出時で正しいサマリー文字列が返されること"""
    guardian = mg_module.ModelGuardian()
    
    # スキャン前（クリーンな状態）
    assert "clean" in guardian.get_summary()
    
    # スキャン実行（エラーと警告検出）
    guardian.scan(root=dummy_workspace)
    summary = guardian.get_summary()
    assert "errors" in summary
    assert "warnings" in summary


def test_run_guardian_check():
    """run_guardian_checkが例外なく呼び出せること"""
    with patch.object(mg_module.model_guardian, "scan", return_value=[]) as mock_scan:
        issues = mg_module.run_guardian_check()
        assert isinstance(issues, list)
        mock_scan.assert_called_once()


def test_model_guardian_scan_with_warnings(dummy_workspace):
    """WARNING レベルの問題が検出された場合、ログ警告が出力されること"""
    guardian = mg_module.ModelGuardian()
    
    # scan内で _scan_file が呼ばれた際、手動で WARNING レベルの issue を差し込むようにモック
    def mock_scan_file(path):
        guardian._issues.append({
            "file": path.name,
            "line": 1,
            "model": "some-model",
            "severity": "WARNING",
            "content": "some warning content"
        })
        
    with patch.object(guardian, "_scan_file", side_effect=mock_scan_file), \
         patch.object(mg_module.logger, "warning") as mock_warn:
        issues = guardian.scan(root=dummy_workspace)
        assert len(issues) == 4
        assert issues[0]["severity"] == "WARNING"
        mock_warn.assert_called()


def test_model_guardian_main():
    """__main__ブロックの動作検証(正常系)"""
    file_path = Path(mg_module.__file__)
    content = file_path.read_text(encoding="utf-8")
    
    main_index = content.find('if __name__ == "__main__":')
    assert main_index != -1
    main_code = content[main_index:]
    
    global_vars = {
        "__name__": "__main__",
        "run_guardian_check": mg_module.run_guardian_check,
        "logging": mg_module.logging,
        "print": print,
    }
    
    with patch.object(mg_module.model_guardian, "scan", return_value=[]) as mock_scan:
        leading_line_count = content[:main_index].count("\n")
        adjusted_code = "\n" * leading_line_count + main_code
        
        code_obj = compile(adjusted_code, str(file_path), "exec")
        exec(code_obj, global_vars)
        mock_scan.assert_called_once()


def test_model_guardian_main_with_issues():
    """__main__ブロックの動作検証(エラー検出時)"""
    file_path = Path(mg_module.__file__)
    content = file_path.read_text(encoding="utf-8")
    
    main_index = content.find('if __name__ == "__main__":')
    assert main_index != -1
    main_code = content[main_index:]
    
    fake_issues = [{
        "severity": "ERROR",
        "file": "test_file.py",
        "line": 10,
        "model": "gemini-1.5-pro",
        "content": "model = 'gemini-1.5-pro'"
    }]
    
    with patch.object(mg_module.model_guardian, "scan", return_value=fake_issues) as mock_scan, \
         patch("builtins.print") as mock_print:
         
        global_vars = {
            "__name__": "__main__",
            "run_guardian_check": mg_module.run_guardian_check,
            "logging": mg_module.logging,
            "print": mock_print,  # モックしたprintを渡す
        }
        
        leading_line_count = content[:main_index].count("\n")
        adjusted_code = "\n" * leading_line_count + main_code
        
        code_obj = compile(adjusted_code, str(file_path), "exec")
        exec(code_obj, global_vars)
        mock_scan.assert_called_once()
        mock_print.assert_called()


def test_model_guardian_config_load_exception(tmp_path, monkeypatch):
    """model_config.json 読み込み時に例外が発生した場合に正しく警告が出力され、デフォルトフォールバックが使われること"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    
    # 実際にファイルを作る
    config_file = workspace / "model_config.json"
    config_file.write_text("{}", encoding="utf-8")
    
    monkeypatch.setattr(mg_module, "BACKEND_DIR", workspace)
    
    # open 時に例外が発生するようにモックする (OSErrorを使用)
    with patch("builtins.open", side_effect=OSError("Read error")), \
         patch.object(mg_module.logger, "warning") as mock_warn:
         
        guardian = mg_module.ModelGuardian()
        # 例外がログに出力されていることを確認
        mock_warn.assert_called_with("Failed to load model config in ModelGuardian: Read error")
        # デフォルトフォールバックが使用されていることを確認
        assert "gemini-1.5-pro" in guardian._deprecated_models
        assert "gemini-2.5-flash" in guardian._current_models


def test_model_guardian_config_json_decode_exception(tmp_path, monkeypatch):
    """model_config.json が不正なJSONの場合に正しく警告が出力され、デフォルトフォールバックが使われること"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    
    config_file = workspace / "model_config.json"
    config_file.write_text("{invalid json", encoding="utf-8")
    
    monkeypatch.setattr(mg_module, "BACKEND_DIR", workspace)
    
    with patch.object(mg_module.logger, "warning") as mock_warn:
        guardian = mg_module.ModelGuardian()
        mock_warn.assert_called()
        assert "gemini-1.5-pro" in guardian._deprecated_models
        assert "gemini-2.5-flash" in guardian._current_models


def test_model_guardian_config_load_branch_coverage(tmp_path, monkeypatch):
    """model_config.json 読み込み時の分岐（default_modelなし、非dictのtier、modelキーなし、重複除外）をカバーする"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(mg_module, "BACKEND_DIR", workspace)
    
    config_data = {
        "deprecated": {
            "gemini-1.5-pro": {},
            "gemini-2.5-flash": {}
        },
        "text_generation": {
            "default_model": "gemini-3-flash-preview",
            "tiers": {
                "tier1": {"model": "gemini-2.5-flash"},
                "tier2": "invalid_string_instead_of_dict",
                "tier3": {"not_model": "foo"}
            }
        },
        "image_generation": {
            "tiers": {}
        }
    }
    
    config_file = workspace / "model_config.json"
    config_file.write_text(json.dumps(config_data), encoding="utf-8")
    
    guardian = mg_module.ModelGuardian()
    
    assert "gemini-2.5-flash" in guardian._deprecated_models
    assert "gemini-2.5-flash" not in guardian._current_models
    assert "gemini-3-flash-preview" in guardian._current_models


def test_model_guardian_scan_only_errors_no_warnings(tmp_path, monkeypatch):
    """scan実行時にERRORのみが検出され、WARNINGが検出されない場合のログ分岐をカバーする"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(mg_module, "BACKEND_DIR", workspace)
    
    bad_file = workspace / "bad_file.py"
    bad_file.write_text("model = 'gemini-1.5-pro'\n", encoding="utf-8")
    
    guardian = mg_module.ModelGuardian()
    
    with patch.object(mg_module.logger, "error") as mock_error, \
         patch.object(mg_module.logger, "warning") as mock_warning:
         
        issues = guardian.scan(root=workspace)
        
        assert len(issues) == 1
        assert issues[0]["severity"] == "ERROR"
        mock_error.assert_called()
        mock_warning.assert_not_called()
