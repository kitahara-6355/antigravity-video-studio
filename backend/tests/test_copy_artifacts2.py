import sys
import os
import runpy
from unittest.mock import patch, MagicMock
import pytest

# プロジェクトルートパスを sys.path に追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.agents.orchestration.copy_artifacts2 import copy_artifacts

def test_copy_artifacts2_function_success_with_tmp(tmp_path):
    # tmp_path を使ったモックなしの正常系テスト
    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    
    src_dir.mkdir()
    # コピーに必要なファイルをダミーで作成
    p1 = src_dir / "backend" / "tests" / "test_shared"
    p1.mkdir(parents=True)
    (p1 / "test_pipeline_coordinator.py").write_text("print('coordinator')", encoding="utf-8")
    (p1 / "test_pipeline_coordinator_coverage.py").write_text("print('coverage')", encoding="utf-8")
    
    p2 = src_dir / "backend" / "tests"
    (p2 / "test_pipeline_tools.py").write_text("print('tools')", encoding="utf-8")
    
    # 実行
    result = copy_artifacts(src_base=str(src_dir), dest_base=str(dest_dir))
    
    # 検証
    assert result is True
    assert (dest_dir / "backend" / "tests" / "test_shared" / "test_pipeline_coordinator.py").exists()
    assert (dest_dir / "backend" / "tests" / "test_shared" / "test_pipeline_coordinator_coverage.py").exists()
    assert (dest_dir / "backend" / "tests" / "test_pipeline_tools.py").exists()

def test_copy_artifacts2_function_alt_path(tmp_path):
    # 代替ソースパス (tests/test_pipeline_tools.py) が使われるケース
    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    
    p1 = src_dir / "backend" / "tests" / "test_shared"
    p1.mkdir(parents=True)
    (p1 / "test_pipeline_coordinator.py").write_text("print('coordinator')", encoding="utf-8")
    (p1 / "test_pipeline_coordinator_coverage.py").write_text("print('coverage')", encoding="utf-8")
    
    # backend/tests ではなく tests/ 直下に test_pipeline_tools.py を作成する
    p2_alt = src_dir / "tests"
    p2_alt.mkdir(parents=True)
    (p2_alt / "test_pipeline_tools.py").write_text("print('tools_alt')", encoding="utf-8")
    
    # 実行
    result = copy_artifacts(src_base=str(src_dir), dest_base=str(dest_dir))
    
    # 検証
    assert result is True
    assert (dest_dir / "backend" / "tests" / "test_pipeline_tools.py").exists()
    assert (dest_dir / "backend" / "tests" / "test_pipeline_tools.py").read_text(encoding="utf-8") == "print('tools_alt')"

def test_copy_artifacts2_function_failure_missing_file(tmp_path):
    # ファイルが一部欠けている場合の異常系テスト（例外を出さずに False を返すこと）
    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    
    # 一部のファイルのみ作成
    p1 = src_dir / "backend" / "tests" / "test_shared"
    p1.mkdir(parents=True)
    (p1 / "test_pipeline_coordinator.py").write_text("print('coordinator')", encoding="utf-8")
    
    # 実行
    result = copy_artifacts(src_base=str(src_dir), dest_base=str(dest_dir))
    
    # 検証
    assert result is False

def test_copy_artifacts2_main_execution(tmp_path):
    # runpy を使用した CLI 実行 (__main__) のモックテスト
    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    
    # ダミーファイルを生成
    p1 = src_dir / "backend" / "tests" / "test_shared"
    p1.mkdir(parents=True)
    (p1 / "test_pipeline_coordinator.py").write_text("coordinator", encoding="utf-8")
    (p1 / "test_pipeline_coordinator_coverage.py").write_text("coverage", encoding="utf-8")
    p2 = src_dir / "backend" / "tests"
    (p2 / "test_pipeline_tools.py").write_text("tools", encoding="utf-8")

    # 環境変数をパッチして runpy を動かす
    target_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../agents/orchestration/copy_artifacts2.py"))
    
    with patch.dict(os.environ, {"SRC_BASE": str(src_dir), "DEST_BASE": str(dest_dir)}):
        runpy.run_path(target_path, run_name="__main__")
        
    # コピーされたか検証
    assert (dest_dir / "backend" / "tests" / "test_shared" / "test_pipeline_coordinator.py").exists()
    assert (dest_dir / "backend" / "tests" / "test_shared" / "test_pipeline_coordinator_coverage.py").exists()
    assert (dest_dir / "backend" / "tests" / "test_pipeline_tools.py").exists()


def test_copy_artifacts2_function_failure_other_exception(tmp_path, capsys):
    # shutil.copy2 で TypeError が発生した場合の検証
    src_dir = tmp_path / "src"
    dest_dir = tmp_path / "dest"
    src_dir.mkdir()
    
    p1 = src_dir / "backend" / "tests" / "test_shared"
    p1.mkdir(parents=True)
    (p1 / "test_pipeline_coordinator.py").write_text("coordinator", encoding="utf-8")
    (p1 / "test_pipeline_coordinator_coverage.py").write_text("coverage", encoding="utf-8")
    p2 = src_dir / "backend" / "tests"
    (p2 / "test_pipeline_tools.py").write_text("tools", encoding="utf-8")

    with patch("shutil.copy2", side_effect=TypeError("Mock TypeError")):
        result = copy_artifacts(src_base=str(src_dir), dest_base=str(dest_dir))
        assert result is False

    captured = capsys.readouterr()
    assert "Error occurred during copy: Mock TypeError" in captured.err

