# -*- coding: utf-8 -*-
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import os
import sys

# パス設定
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.tdr_resolver import TDRResolver
from agents.memory.technical_debt import TechnicalDebtEntry

def test_resolve_minor_debts_no_targets():
    mock_store = MagicMock()
    mock_store.get_open_entries.return_value = []
    
    resolver = TDRResolver(debt_store=mock_store)
    res = resolver.resolve_minor_debts()
    assert res["total_found"] == 0
    assert res["resolved"] == 0

def test_resolve_minor_debts_success(tmp_path):
    mock_store = MagicMock()
    entry = TechnicalDebtEntry(
        debt_id="TD-999",
        category="MINOR_INFRA",
        file_path="dummy_file.py",
        line_number=10,
        pattern="except Exception as e:",
        cause_pattern="DP-01",
        fix_pattern="except Exception as e:\n    logger.exception(e)\n    raise",
        status="open",
        registered_at="2026-05-24T00:00:00",
        registered_by="manual",
        fixed_at=None,
        fixed_by=None,
        fix_evidence=None,
        related_test="backend/tests/test_fitness_functions.py"
    )
    mock_store.get_open_entries.return_value = [entry]
    
    dummy_file = tmp_path / "dummy_file.py"
    dummy_file.write_text("try:\n    pass\nexcept Exception as e:\n    pass", encoding="utf-8")
    
    resolver = TDRResolver(debt_store=mock_store, project_root=tmp_path)
    
    with patch.object(resolver, "_check_ast", return_value=True), \
         patch.object(resolver, "_run_tests", return_value=True), \
         patch.object(resolver, "_commit_fix", return_value=True):
         
        res = resolver.resolve_minor_debts()
        assert res["total_found"] == 1
        assert res["resolved"] == 1
        
        content = dummy_file.read_text(encoding="utf-8")
        assert "logger.exception(e)" in content
        mock_store.resolve_debt.assert_called_once()

def test_resolve_minor_debts_file_missing():
    mock_store = MagicMock()
    entry = TechnicalDebtEntry(
        debt_id="TD-999",
        category="MINOR_INFRA",
        file_path="nonexistent_file.py",
        line_number=10,
        pattern="except Exception as e:",
        cause_pattern="DP-01",
        fix_pattern="except Exception as e:\n    logger.exception(e)\n    raise",
        status="open",
        registered_at="2026-05-24T00:00:00",
        registered_by="manual",
        fixed_at=None,
        fixed_by=None,
        fix_evidence=None,
        related_test="backend/tests/test_fitness_functions.py"
    )
    mock_store.get_open_entries.return_value = [entry]
    
    resolver = TDRResolver(debt_store=mock_store)
    res = resolver.resolve_minor_debts()
    assert res["total_found"] == 1
    assert res["resolved"] == 0
    assert res["failed"] == 1

def test_resolve_minor_debts_rollback_on_test_fail(tmp_path):
    mock_store = MagicMock()
    entry = TechnicalDebtEntry(
        debt_id="TD-999",
        category="MINOR_INFRA",
        file_path="dummy_file.py",
        line_number=10,
        pattern="except Exception as e:",
        cause_pattern="DP-01",
        fix_pattern="except Exception as e:\n    logger.exception(e)\n    raise",
        status="open",
        registered_at="2026-05-24T00:00:00",
        registered_by="manual",
        fixed_at=None,
        fixed_by=None,
        fix_evidence=None,
        related_test="backend/tests/test_fitness_functions.py"
    )
    mock_store.get_open_entries.return_value = [entry]
    
    dummy_file = tmp_path / "dummy_file.py"
    dummy_file.write_text("try:\n    pass\nexcept Exception as e:\n    pass", encoding="utf-8")
    
    resolver = TDRResolver(debt_store=mock_store, project_root=tmp_path)
    
    with patch.object(resolver, "_check_ast", return_value=True), \
         patch.object(resolver, "_run_tests", return_value=False), \
         patch.object(resolver, "_rollback") as mock_rollback:
         
        res = resolver.resolve_minor_debts()
        assert res["total_found"] == 1
        assert res["resolved"] == 0
        assert res["failed"] == 1
        assert res["rolled_back"] == 1
        
        mock_rollback.assert_called_once()

def test_check_ast_valid(tmp_path):
    resolver = TDRResolver()
    f = tmp_path / "valid.py"
    f.write_text("def f(): pass", encoding="utf-8")
    assert resolver._check_ast(f) is True

def test_check_ast_invalid(tmp_path):
    resolver = TDRResolver()
    f = tmp_path / "invalid.py"
    f.write_text("def f():", encoding="utf-8")
    assert resolver._check_ast(f) is False

def test_run_tests(tmp_path):
    resolver = TDRResolver(project_root=tmp_path)
    entry = TechnicalDebtEntry(
        debt_id="TD-1", category="MINOR_INFRA", file_path="x.py",
        line_number=1, pattern="x", cause_pattern="DP-01", fix_pattern="y",
        status="open", registered_at="2026-05-24T00:00:00", registered_by="manual",
        fixed_at=None, fixed_by=None, fix_evidence=None, related_test="test_x.py"
    )
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert resolver._run_tests(entry) is True
        
        mock_run.return_value = MagicMock(returncode=1, stdout="failed", stderr="")
        assert resolver._run_tests(entry) is False
        
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["pytest"], timeout=60)
        assert resolver._run_tests(entry) is False

def test_commit_fix(tmp_path):
    resolver = TDRResolver(project_root=tmp_path)
    entry = TechnicalDebtEntry(
        debt_id="TD-1", category="MINOR_INFRA", file_path="x.py",
        line_number=1, pattern="x", cause_pattern="DP-01", fix_pattern="y",
        status="open", registered_at="2026-05-24T00:00:00", registered_by="manual",
        fixed_at=None, fixed_by=None, fix_evidence=None, related_test="test_x.py"
    )
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert resolver._commit_fix(entry) is True
        
        mock_run.side_effect = [MagicMock(returncode=1, stderr="add failed")]
        assert resolver._commit_fix(entry) is False

def test_apply_fix_read_file_error(tmp_path):
    mock_store = MagicMock()
    entry = TechnicalDebtEntry(
        debt_id="TD-999", category="MINOR_INFRA", file_path="dummy_file.py",
        line_number=10, pattern="except Exception as e:", cause_pattern="DP-01",
        fix_pattern="except Exception as e:\n    logger.exception(e)\n    raise",
        status="open", registered_at="2026-05-24T00:00:00", registered_by="manual",
        fixed_at=None, fixed_by=None, fix_evidence=None, related_test="test.py"
    )
    mock_store.get_open_entries.return_value = [entry]
    
    dummy_file = tmp_path / "dummy_file.py"
    dummy_file.write_text("except Exception as e:", encoding="utf-8")
    
    resolver = TDRResolver(debt_store=mock_store, project_root=tmp_path)
    
    original_open = open
    def mock_open(file, mode, *args, **kwargs):
        if str(file) == str(dummy_file) and "r" in mode:
            raise OSError("Read error")
        return original_open(file, mode, *args, **kwargs)
        
    with patch("builtins.open", side_effect=mock_open):
        res = resolver.resolve_minor_debts()
        assert res["failed"] == 1

def test_apply_fix_pattern_not_found(tmp_path):
    mock_store = MagicMock()
    entry = TechnicalDebtEntry(
        debt_id="TD-999", category="MINOR_INFRA", file_path="dummy_file.py",
        line_number=10, pattern="not_existing_pattern", cause_pattern="DP-01",
        fix_pattern="xxx", status="open", registered_at="2026-05-24T00:00:00",
        registered_by="manual", fixed_at=None, fixed_by=None, fix_evidence=None, related_test="test.py"
    )
    mock_store.get_open_entries.return_value = [entry]
    
    dummy_file = tmp_path / "dummy_file.py"
    dummy_file.write_text("some content", encoding="utf-8")
    
    resolver = TDRResolver(debt_store=mock_store, project_root=tmp_path)
    res = resolver.resolve_minor_debts()
    assert res["failed"] == 1

def test_apply_fix_no_fix_pattern_fallback(tmp_path):
    mock_store = MagicMock()
    entry = TechnicalDebtEntry(
        debt_id="TD-999", category="MINOR_INFRA", file_path="dummy_file.py",
        line_number=10, pattern="except Exception as e:", cause_pattern="DP-01",
        fix_pattern=None, status="open", registered_at="2026-05-24T00:00:00",
        registered_by="manual", fixed_at=None, fixed_by=None, fix_evidence=None, related_test="test.py"
    )
    mock_store.get_open_entries.return_value = [entry]
    
    dummy_file = tmp_path / "dummy_file.py"
    dummy_file.write_text("except Exception as e:", encoding="utf-8")
    
    resolver = TDRResolver(debt_store=mock_store, project_root=tmp_path)
    with patch.object(resolver, "_check_ast", return_value=True), \
         patch.object(resolver, "_run_tests", return_value=True), \
         patch.object(resolver, "_commit_fix", return_value=True):
        res = resolver.resolve_minor_debts()
        assert res["resolved"] == 1

def test_apply_fix_no_fix_pattern_error(tmp_path):
    mock_store = MagicMock()
    entry = TechnicalDebtEntry(
        debt_id="TD-999", category="MINOR_INFRA", file_path="dummy_file.py",
        line_number=10, pattern="other_pattern", cause_pattern="DP-01",
        fix_pattern=None, status="open", registered_at="2026-05-24T00:00:00",
        registered_by="manual", fixed_at=None, fixed_by=None, fix_evidence=None, related_test="test.py"
    )
    mock_store.get_open_entries.return_value = [entry]
    
    dummy_file = tmp_path / "dummy_file.py"
    dummy_file.write_text("other_pattern", encoding="utf-8")
    
    resolver = TDRResolver(debt_store=mock_store, project_root=tmp_path)
    res = resolver.resolve_minor_debts()
    assert res["failed"] == 1

def test_apply_fix_write_file_error(tmp_path):
    mock_store = MagicMock()
    entry = TechnicalDebtEntry(
        debt_id="TD-999", category="MINOR_INFRA", file_path="dummy_file.py",
        line_number=10, pattern="except Exception as e:", cause_pattern="DP-01",
        fix_pattern="except Exception as e:\n    logger.exception(e)\n    raise",
        status="open", registered_at="2026-05-24T00:00:00", registered_by="manual",
        fixed_at=None, fixed_by=None, fix_evidence=None, related_test="test.py"
    )
    mock_store.get_open_entries.return_value = [entry]
    
    dummy_file = tmp_path / "dummy_file.py"
    dummy_file.write_text("except Exception as e:", encoding="utf-8")
    
    resolver = TDRResolver(debt_store=mock_store, project_root=tmp_path)
    
    original_open = open
    def mock_open(file, mode, *args, **kwargs):
        if str(file) == str(dummy_file) and "w" in mode:
            raise OSError("Write error")
        return original_open(file, mode, *args, **kwargs)
        
    with patch("builtins.open", side_effect=mock_open):
        res = resolver.resolve_minor_debts()
        assert res["failed"] == 1

def test_apply_fix_ast_verification_failed(tmp_path):
    mock_store = MagicMock()
    entry = TechnicalDebtEntry(
        debt_id="TD-999", category="MINOR_INFRA", file_path="dummy_file.py",
        line_number=10, pattern="except Exception as e:", cause_pattern="DP-01",
        fix_pattern="except Exception as e:\n    logger.exception(e)\n    raise",
        status="open", registered_at="2026-05-24T00:00:00", registered_by="manual",
        fixed_at=None, fixed_by=None, fix_evidence=None, related_test="test.py"
    )
    mock_store.get_open_entries.return_value = [entry]
    
    dummy_file = tmp_path / "dummy_file.py"
    dummy_file.write_text("except Exception as e:", encoding="utf-8")
    
    resolver = TDRResolver(debt_store=mock_store, project_root=tmp_path)
    with patch.object(resolver, "_check_ast", return_value=False):
        res = resolver.resolve_minor_debts()
        assert res["failed"] == 1
        
        # 実際にロールバックされて元のファイル内容になっていることを確認
        assert dummy_file.read_text(encoding="utf-8") == "except Exception as e:"

def test_apply_fix_git_commit_failed_reopen_error(tmp_path):
    mock_store = MagicMock()
    entry = TechnicalDebtEntry(
        debt_id="TD-999", category="MINOR_INFRA", file_path="dummy_file.py",
        line_number=10, pattern="except Exception as e:", cause_pattern="DP-01",
        fix_pattern="except Exception as e:\n    logger.exception(e)\n    raise",
        status="open", registered_at="2026-05-24T00:00:00", registered_by="manual",
        fixed_at=None, fixed_by=None, fix_evidence=None, related_test="test.py"
    )
    mock_store.get_open_entries.return_value = [entry]
    mock_store.reopen_debt.side_effect = Exception("Store error")
    
    dummy_file = tmp_path / "dummy_file.py"
    dummy_file.write_text("except Exception as e:", encoding="utf-8")
    
    resolver = TDRResolver(debt_store=mock_store, project_root=tmp_path)
    with patch.object(resolver, "_check_ast", return_value=True), \
         patch.object(resolver, "_run_tests", return_value=True), \
         patch.object(resolver, "_commit_fix", return_value=False), \
         patch.object(resolver, "_rollback") as mock_rollback:
        res = resolver.resolve_minor_debts()
        assert res["failed"] == 1
        mock_rollback.assert_called_once()
        mock_store.reopen_debt.assert_called_once()

def test_apply_fix_resolve_debt_error(tmp_path):
    mock_store = MagicMock()
    entry = TechnicalDebtEntry(
        debt_id="TD-999", category="MINOR_INFRA", file_path="dummy_file.py",
        line_number=10, pattern="except Exception as e:", cause_pattern="DP-01",
        fix_pattern="except Exception as e:\n    logger.exception(e)\n    raise",
        status="open", registered_at="2026-05-24T00:00:00", registered_by="manual",
        fixed_at=None, fixed_by=None, fix_evidence=None, related_test="test.py"
    )
    mock_store.get_open_entries.return_value = [entry]
    mock_store.resolve_debt.side_effect = ValueError("Resolve error")
    
    dummy_file = tmp_path / "dummy_file.py"
    dummy_file.write_text("except Exception as e:", encoding="utf-8")
    
    resolver = TDRResolver(debt_store=mock_store, project_root=tmp_path)
    with patch.object(resolver, "_check_ast", return_value=True), \
         patch.object(resolver, "_run_tests", return_value=True), \
         patch.object(resolver, "_rollback") as mock_rollback:
        res = resolver.resolve_minor_debts()
        assert res["failed"] == 1
        mock_rollback.assert_called_once()

def test_check_ast_read_error(tmp_path):
    resolver = TDRResolver()
    f = tmp_path / "valid.py"
    f.write_text("def f(): pass", encoding="utf-8")
    
    with patch("builtins.open", side_effect=OSError("Read error")):
        assert resolver._check_ast(f) is False

def test_run_tests_os_error(tmp_path):
    resolver = TDRResolver(project_root=tmp_path)
    entry = TechnicalDebtEntry(
        debt_id="TD-1", category="MINOR_INFRA", file_path="x.py",
        line_number=1, pattern="x", cause_pattern="DP-01", fix_pattern="y",
        status="open", registered_at="2026-05-24T00:00:00", registered_by="manual",
        fixed_at=None, fixed_by=None, fix_evidence=None, related_test="test_x.py"
    )
    
    with patch("subprocess.run", side_effect=OSError("OS Error")):
        assert resolver._run_tests(entry) is False

def test_rollback_error(tmp_path):
    resolver = TDRResolver()
    bad_file = tmp_path / "subdir" / "file.py"
    resolver._rollback(bad_file, "content")

def test_commit_fix_commit_failed(tmp_path):
    resolver = TDRResolver(project_root=tmp_path)
    entry = TechnicalDebtEntry(
        debt_id="TD-1", category="MINOR_INFRA", file_path="x.py",
        line_number=1, pattern="x", cause_pattern="DP-01", fix_pattern="y",
        status="open", registered_at="2026-05-24T00:00:00", registered_by="manual",
        fixed_at=None, fixed_by=None, fix_evidence=None, related_test="test_x.py"
    )
    
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=1, stderr="commit failed")
        ]
        assert resolver._commit_fix(entry) is False

def test_commit_fix_os_error(tmp_path):
    resolver = TDRResolver(project_root=tmp_path)
    entry = TechnicalDebtEntry(
        debt_id="TD-1", category="MINOR_INFRA", file_path="x.py",
        line_number=1, pattern="x", cause_pattern="DP-01", fix_pattern="y",
        status="open", registered_at="2026-05-24T00:00:00", registered_by="manual",
        fixed_at=None, fixed_by=None, fix_evidence=None, related_test="test_x.py"
    )
    
    with patch("subprocess.run", side_effect=OSError("OS error")):
        assert resolver._commit_fix(entry) is False


# --------------------------------------------------------
# ThumbnailResolver Tests
# --------------------------------------------------------
from services.tdr_resolver import ThumbnailResolver
from agents.stage_bound_agent import StageBoundAgent
from PIL import Image
import json
import sqlite3
import asyncio

def test_thumbnail_generation_success(tmp_path):
    output_path = tmp_path / "test_thumb.png"
    resolver = ThumbnailResolver(output_dir=tmp_path)
    
    res_path = resolver.generate_thumbnail(output_path, text="Hello World")
    assert res_path.exists()
    
    with Image.open(res_path) as img:
        assert img.size == (1280, 720)


def test_thumbnail_validation(tmp_path):
    resolver = ThumbnailResolver(output_dir=tmp_path)
    
    # 1. 正常な画像
    ok_path = tmp_path / "ok.png"
    resolver.generate_thumbnail(ok_path, width=1920, height=1080)
    result = resolver.validate_thumbnail(ok_path)
    assert result["width"] == 1920
    assert result["height"] == 1080
    
    # 2. 低解像度の画像
    bad_res_path = tmp_path / "bad_res.png"
    img_bad_res = Image.new("RGB", (640, 360), color="red")
    img_bad_res.save(bad_res_path)
    with pytest.raises(ValueError) as exc:
        resolver.validate_thumbnail(bad_res_path)
    assert "Resolution must be at least 1280x720" in str(exc.value)
    
    # 3. アスペクト比が正しくない (16:10 など)
    bad_aspect_path = tmp_path / "bad_aspect.png"
    img_bad_aspect = Image.new("RGB", (1280, 800), color="blue")
    img_bad_aspect.save(bad_aspect_path)
    with pytest.raises(ValueError) as exc:
        resolver.validate_thumbnail(bad_aspect_path)
    assert "Aspect ratio must be 16:9" in str(exc.value)
    
    # 4. ファイルが存在しない
    non_existent = tmp_path / "ghost.png"
    with pytest.raises(FileNotFoundError):
        resolver.validate_thumbnail(non_existent)
        
    # 5. 破損画像
    corrupted_path = tmp_path / "corrupt.png"
    corrupted_path.write_text("not an image at all", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        resolver.validate_thumbnail(corrupted_path)
    assert "Image is corrupted" in str(exc.value)


def test_thumbnail_validation_extra(tmp_path):
    resolver = ThumbnailResolver(output_dir=tmp_path)
    
    # 1. None または空パスの検証
    with pytest.raises(ValueError) as exc:
        resolver.validate_thumbnail(None)
    assert "File path must not be empty or None" in str(exc.value)
    
    with pytest.raises(ValueError) as exc:
        resolver.validate_thumbnail("")
    assert "File path must not be empty or None" in str(exc.value)
    
    # 2. サポートされていない拡張子
    gif_path = tmp_path / "invalid_ext.gif"
    gif_path.write_text("dummy", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        resolver.validate_thumbnail(gif_path)
    assert "Unsupported file format" in str(exc.value)
    
    # 3. サイズが4MBを超える検証
    huge_path = tmp_path / "huge.png"
    with open(huge_path, "wb") as f:
        f.seek(4 * 1024 * 1024)
        f.write(b" ")
        
    with pytest.raises(ValueError) as exc:
        resolver.validate_thumbnail(huge_path)
    assert "File size exceeds 4MB limit" in str(exc.value)


@pytest.mark.asyncio
async def test_thumbnail_stage_bound_agent_integration(tmp_path):
    db_file = tmp_path / "thumbnail_agent.db"
    resolver = ThumbnailResolver(project_root=tmp_path, output_dir=tmp_path)
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    task_id = "t_thumb_ok"
    await agent.register_task(task_id=task_id, initial_status="READY")
    
    # StageBoundAgent を開始し、resolver.resolve_thumbnail_task をプロセス関数として渡す
    await agent.start(resolver.resolve_thumbnail_task)
    
    # 非同期実行の完了を待機
    for _ in range(20):
        status = await agent.get_task_status(task_id)
        if status in ("COMPLETED", "FAILED"):
            break
        await asyncio.sleep(0.05)
        
    final_status = await agent.get_task_status(task_id)
    assert final_status == "COMPLETED"
    
    # 結果がDBに保存されているか検証
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT result, error, retry_count FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        result_data = json.loads(row[0])
        assert result_data["width"] == 1280
        assert result_data["height"] == 720
        assert row[1] is None
        assert row[2] == 0
    finally:
        conn.close()
        
    await agent.stop()


@pytest.mark.asyncio
async def test_thumbnail_stage_bound_agent_retry_on_failure(tmp_path):
    db_file = tmp_path / "thumbnail_retry.db"
    
    # 最初に失敗して、リトライ上限に達するケースを検証する。
    # 意図的に無効なパスに保存するなどのエラーを起こす。
    resolver = ThumbnailResolver(project_root=tmp_path, output_dir=Path("C:/invalid_dir_?:*"))
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    task_id = "t_thumb_fail"
    # max_retries = 2 とする
    await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
    
    await agent.start(resolver.resolve_thumbnail_task)
    
    for _ in range(20):
        status = await agent.get_task_status(task_id)
        if status == "FAILED":
            break
        await asyncio.sleep(0.05)
        
    final_status = await agent.get_task_status(task_id)
    assert final_status == "FAILED"
    
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT retry_count, status, error FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == 2 # 2回リトライされた
        assert row[1] == "FAILED"
        assert row[2] is not None # エラーメッセージが記録されていること
    finally:
        conn.close()
        
    await agent.stop()


# --------------------------------------------------------
# TDRResolver Edge Cases Tests
# --------------------------------------------------------
def test_tdr_resolver_init_defaults():
    resolver = TDRResolver()
    assert resolver.debt_store is not None
    assert resolver.project_root is not None
    assert resolver.project_root.exists()

def test_resolve_minor_debts_invalid_category_types(tmp_path):
    mock_store = MagicMock()
    entry = TechnicalDebtEntry(
        debt_id="TD-999", category="MINOR_INFRA", file_path="dummy.py",
        line_number=10, pattern="x", cause_pattern="DP-01", fix_pattern="y",
        status="open", registered_at="2026-05-24T00:00:00", registered_by="manual",
        fixed_at=None, fixed_by=None, fix_evidence=None, related_test="test.py"
    )
    mock_store.get_open_entries.return_value = [entry]
    resolver = TDRResolver(debt_store=mock_store, project_root=tmp_path)
    
    res_none = resolver.resolve_minor_debts(None)
    assert res_none["total_found"] == 0
    
    res_empty = resolver.resolve_minor_debts("")
    assert res_empty["total_found"] == 0

    res_int = resolver.resolve_minor_debts(123)
    assert res_int["total_found"] == 0

def test_apply_fix_default_test_target(tmp_path):
    mock_store = MagicMock()
    entry = TechnicalDebtEntry(
        debt_id="TD-999", category="MINOR_INFRA", file_path="dummy_file.py",
        line_number=10, pattern="except Exception as e:", cause_pattern="DP-01",
        fix_pattern="except Exception as e:\n    logger.exception(e)\n    raise",
        status="open", registered_at="2026-05-24T00:00:00", registered_by="manual",
        fixed_at=None, fixed_by=None, fix_evidence=None,
        related_test=None
    )
    mock_store.get_open_entries.return_value = [entry]
    
    dummy_file = tmp_path / "dummy_file.py"
    dummy_file.write_text("try:\n    pass\nexcept Exception as e:\n    pass", encoding="utf-8")
    
    resolver = TDRResolver(debt_store=mock_store, project_root=tmp_path)
    
    with patch.object(resolver, "_check_ast", return_value=True), \
         patch("subprocess.run") as mock_run, \
         patch.object(resolver, "_commit_fix", return_value=True):
         
        mock_run.return_value = MagicMock(returncode=0)
        res = resolver.resolve_minor_debts()
        assert res["resolved"] == 1
        
        called_args = mock_run.call_args[0][0]
        assert "backend/tests/test_fitness_functions.py" in called_args

def test_check_ast_with_invalid_path_type():
    resolver = TDRResolver()
    with pytest.raises(TypeError):
        resolver._check_ast(None)

def test_run_tests_subprocess_error(tmp_path):
    resolver = TDRResolver(project_root=tmp_path)
    entry = TechnicalDebtEntry(
        debt_id="TD-1", category="MINOR_INFRA", file_path="x.py",
        line_number=1, pattern="x", cause_pattern="DP-01", fix_pattern="y",
        status="open", registered_at="2026-05-24T00:00:00", registered_by="manual",
        fixed_at=None, fixed_by=None, fix_evidence=None, related_test="test_x.py"
    )
    
    import subprocess
    with patch("subprocess.run", side_effect=subprocess.SubprocessError("Subprocess failed")):
        assert resolver._run_tests(entry) is False

def test_apply_fix_file_path_none_raises(tmp_path):
    mock_store = MagicMock()
    entry = TechnicalDebtEntry(
        debt_id="TD-999", category="MINOR_INFRA",
        file_path=None,
        line_number=10, pattern="except Exception as e:", cause_pattern="DP-01",
        fix_pattern="except Exception as e:\n    logger.exception(e)\n    raise",
        status="open", registered_at="2026-05-24T00:00:00", registered_by="manual",
        fixed_at=None, fixed_by=None, fix_evidence=None, related_test="test.py"
    )
    mock_store.get_open_entries.return_value = [entry]
    resolver = TDRResolver(debt_store=mock_store, project_root=tmp_path)
    
    with pytest.raises(TypeError):
        resolver.resolve_minor_debts()

def test_apply_fix_pattern_none_raises(tmp_path):
    mock_store = MagicMock()
    entry = TechnicalDebtEntry(
        debt_id="TD-999", category="MINOR_INFRA", file_path="dummy.py",
        line_number=10,
        pattern=None,
        cause_pattern="DP-01",
        fix_pattern="xxx", status="open", registered_at="2026-05-24T00:00:00",
        registered_by="manual", fixed_at=None, fixed_by=None, fix_evidence=None, related_test="test.py"
    )
    mock_store.get_open_entries.return_value = [entry]
    
    dummy_file = tmp_path / "dummy.py"
    dummy_file.write_text("some content", encoding="utf-8")
    
    resolver = TDRResolver(debt_store=mock_store, project_root=tmp_path)
    with pytest.raises(TypeError):
        resolver.resolve_minor_debts()

