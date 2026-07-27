import pytest
import sys
import os
import ast
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

# プロジェクトルートと backend ディレクトリを sys.path に追加してインポート可能にする
project_root = Path(__file__).resolve().parents[1]
backend_path = project_root / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from services.tdr_resolver import TDRResolver
from agents.memory.technical_debt import TechnicalDebtEntry

@pytest.fixture
def dummy_entry():
    return TechnicalDebtEntry(
        debt_id="TD-999",
        category="MINOR_INFRA",
        file_path="dummy_file.py",
        line_number=10,
        pattern="except Exception as e:",
        cause_pattern="DP-01",
        fix_pattern="except Exception as e:\n    logger.exception(e)\n    raise",
        status="open",
        registered_at="2026-05-26T00:00:00",
        registered_by="test",
        related_test="tests/test_dummy.py"
    )

# --------------------------------------------------------
# 3.1. __init__
# --------------------------------------------------------
def test_init_defaults():
    with patch("services.tdr_resolver.TechnicalDebtStore") as mock_store_class:
        resolver = TDRResolver()
        assert resolver.debt_store is not None
        mock_store_class.assert_called_once()
        import services.tdr_resolver
        expected_root = Path(services.tdr_resolver.__file__).resolve().parents[2]
        assert resolver.project_root == expected_root

def test_init_custom():
    mock_store = MagicMock()
    custom_root = Path("/tmp/custom_root")
    resolver = TDRResolver(debt_store=mock_store, project_root=custom_root)
    assert resolver.debt_store == mock_store
    assert resolver.project_root == custom_root

# --------------------------------------------------------
# 3.2. resolve_minor_debts
# --------------------------------------------------------
def test_resolve_minor_debts():
    mock_store = MagicMock()
    entry_minor1 = MagicMock(spec=TechnicalDebtEntry, category="MINOR_INFRA")
    entry_minor2 = MagicMock(spec=TechnicalDebtEntry, category="MINOR_INFRA")
    entry_other = MagicMock(spec=TechnicalDebtEntry, category="CRITICAL_ROUTER")
    
    mock_store.get_open_entries.return_value = [entry_minor1, entry_minor2, entry_other]
    
    resolver = TDRResolver(debt_store=mock_store)
    
    with patch.object(resolver, "_apply_fix") as mock_apply_fix:
        # 1つ目は成功、2つ目は失敗
        mock_apply_fix.side_effect = [True, False]
        
        summary = resolver.resolve_minor_debts("MINOR_INFRA")
        
        assert summary["total_found"] == 2
        assert summary["resolved"] == 1
        assert summary["failed"] == 1
        assert summary["rolled_back"] == 1
        
        mock_apply_fix.assert_any_call(entry_minor1)
        mock_apply_fix.assert_any_call(entry_minor2)

# --------------------------------------------------------
# 3.3. _apply_fix
# --------------------------------------------------------
def test_apply_fix_file_not_found(tmp_path, dummy_entry):
    resolver = TDRResolver(project_root=tmp_path)
    assert resolver._apply_fix(dummy_entry) is False

def test_apply_fix_read_oserror(tmp_path, dummy_entry):
    resolver = TDRResolver(project_root=tmp_path)
    file_path = tmp_path / dummy_entry.file_path
    file_path.touch()
    
    with patch("builtins.open", side_effect=OSError("Read error")):
        assert resolver._apply_fix(dummy_entry) is False

def test_apply_fix_pattern_not_found(tmp_path, dummy_entry):
    resolver = TDRResolver(project_root=tmp_path)
    file_path = tmp_path / dummy_entry.file_path
    file_path.write_text("def my_func():\n    pass\n", encoding="utf-8")
    
    assert resolver._apply_fix(dummy_entry) is False

def test_apply_fix_empty_fix_pattern_default_exception(tmp_path, dummy_entry):
    dummy_entry.fix_pattern = ""
    dummy_entry.pattern = "except Exception as e:"
    
    resolver = TDRResolver(project_root=tmp_path)
    file_path = tmp_path / dummy_entry.file_path
    file_path.write_text("def my_func():\n    try:\n        pass\n    except Exception as e:\n        pass\n", encoding="utf-8")
    
    with patch.object(resolver, "_check_ast", return_value=True), \
         patch.object(resolver, "_run_tests", return_value=True), \
         patch.object(resolver, "_commit_fix", return_value=True):
        
        assert resolver._apply_fix(dummy_entry) is True
        
        content = file_path.read_text(encoding="utf-8")
        assert "except Exception as e:\n    logger.exception(e)\n    raise" in content

def test_apply_fix_empty_fix_pattern_not_exception(tmp_path, dummy_entry):
    dummy_entry.fix_pattern = ""
    dummy_entry.pattern = "some_other_pattern"
    
    resolver = TDRResolver(project_root=tmp_path)
    file_path = tmp_path / dummy_entry.file_path
    file_path.write_text("def my_func():\n    some_other_pattern\n", encoding="utf-8")
    
    assert resolver._apply_fix(dummy_entry) is False

def test_apply_fix_write_oserror(tmp_path, dummy_entry):
    resolver = TDRResolver(project_root=tmp_path)
    file_path = tmp_path / dummy_entry.file_path
    file_path.write_text("except Exception as e:", encoding="utf-8")
    
    original_open = open
    def mock_open_fn(file, mode='r', *args, **kwargs):
        if 'w' in mode:
            raise OSError("Write error")
        return original_open(file, mode, *args, **kwargs)
        
    with patch("builtins.open", side_effect=mock_open_fn):
        assert resolver._apply_fix(dummy_entry) is False

def test_apply_fix_ast_failed(tmp_path, dummy_entry):
    resolver = TDRResolver(project_root=tmp_path)
    file_path = tmp_path / dummy_entry.file_path
    original_content = "except Exception as e:"
    file_path.write_text(original_content, encoding="utf-8")
    
    with patch.object(resolver, "_check_ast", return_value=False), \
         patch.object(resolver, "_rollback") as mock_rollback:
        
        assert resolver._apply_fix(dummy_entry) is False
        mock_rollback.assert_called_once_with(file_path, original_content)

def test_apply_fix_tests_failed(tmp_path, dummy_entry):
    resolver = TDRResolver(project_root=tmp_path)
    file_path = tmp_path / dummy_entry.file_path
    original_content = "except Exception as e:"
    file_path.write_text(original_content, encoding="utf-8")
    
    with patch.object(resolver, "_check_ast", return_value=True), \
         patch.object(resolver, "_run_tests", return_value=False), \
         patch.object(resolver, "_rollback") as mock_rollback:
        
        assert resolver._apply_fix(dummy_entry) is False
        mock_rollback.assert_called_once_with(file_path, original_content)

def test_apply_fix_commit_failed(tmp_path, dummy_entry):
    mock_store = MagicMock()
    resolver = TDRResolver(debt_store=mock_store, project_root=tmp_path)
    file_path = tmp_path / dummy_entry.file_path
    original_content = "except Exception as e:"
    file_path.write_text(original_content, encoding="utf-8")
    
    with patch.object(resolver, "_check_ast", return_value=True), \
         patch.object(resolver, "_run_tests", return_value=True), \
         patch.object(resolver, "_commit_fix", return_value=False), \
         patch.object(resolver, "_rollback") as mock_rollback:
        
        assert resolver._apply_fix(dummy_entry) is False
        mock_rollback.assert_called_once_with(file_path, original_content)
        mock_store.resolve_debt.assert_called_once()
        mock_store.reopen_debt.assert_called_once_with(dummy_entry.debt_id, "Git commit failed during auto resolution")

def test_apply_fix_commit_failed_reopen_exception(tmp_path, dummy_entry):
    mock_store = MagicMock()
    mock_store.reopen_debt.side_effect = Exception("Store error")
    
    resolver = TDRResolver(debt_store=mock_store, project_root=tmp_path)
    file_path = tmp_path / dummy_entry.file_path
    original_content = "except Exception as e:"
    file_path.write_text(original_content, encoding="utf-8")
    
    with patch.object(resolver, "_check_ast", return_value=True), \
         patch.object(resolver, "_run_tests", return_value=True), \
         patch.object(resolver, "_commit_fix", return_value=False), \
         patch.object(resolver, "_rollback") as mock_rollback:
        
        assert resolver._apply_fix(dummy_entry) is False
        mock_rollback.assert_called_once_with(file_path, original_content)
        mock_store.resolve_debt.assert_called_once()
        mock_store.reopen_debt.assert_called_once_with(dummy_entry.debt_id, "Git commit failed during auto resolution")

def test_apply_fix_store_exception(tmp_path, dummy_entry):
    mock_store = MagicMock()
    mock_store.resolve_debt.side_effect = ValueError("Invalid debt ID")
    
    resolver = TDRResolver(debt_store=mock_store, project_root=tmp_path)
    file_path = tmp_path / dummy_entry.file_path
    original_content = "except Exception as e:"
    file_path.write_text(original_content, encoding="utf-8")
    
    with patch.object(resolver, "_check_ast", return_value=True), \
         patch.object(resolver, "_run_tests", return_value=True), \
         patch.object(resolver, "_rollback") as mock_rollback:
        
        assert resolver._apply_fix(dummy_entry) is False
        mock_rollback.assert_called_once_with(file_path, original_content)

def test_apply_fix_success(tmp_path, dummy_entry):
    mock_store = MagicMock()
    resolver = TDRResolver(debt_store=mock_store, project_root=tmp_path)
    file_path = tmp_path / dummy_entry.file_path
    original_content = "except Exception as e:"
    file_path.write_text(original_content, encoding="utf-8")
    
    with patch.object(resolver, "_check_ast", return_value=True), \
         patch.object(resolver, "_run_tests", return_value=True), \
         patch.object(resolver, "_commit_fix", return_value=True), \
         patch.object(resolver, "_rollback") as mock_rollback:
        
        assert resolver._apply_fix(dummy_entry) is True
        mock_rollback.assert_not_called()
        mock_store.resolve_debt.assert_called_once_with(
            debt_id=dummy_entry.debt_id,
            fixed_by="tdr_resolver",
            fix_evidence="Auto resolved by TDRResolver. AST check passed. Tests passed."
        )

# --------------------------------------------------------
# 3.4. _check_ast
# --------------------------------------------------------
def test_check_ast_success(tmp_path):
    resolver = TDRResolver(project_root=tmp_path)
    file_path = tmp_path / "valid.py"
    file_path.write_text("def my_func():\n    return 42\n", encoding="utf-8")
    assert resolver._check_ast(file_path) is True

def test_check_ast_syntax_error(tmp_path):
    resolver = TDRResolver(project_root=tmp_path)
    file_path = tmp_path / "invalid.py"
    file_path.write_text("def my_func(\n", encoding="utf-8")
    assert resolver._check_ast(file_path) is False

def test_check_ast_read_oserror(tmp_path):
    resolver = TDRResolver(project_root=tmp_path)
    file_path = tmp_path / "error.py"
    file_path.touch()
    
    with patch("builtins.open", side_effect=OSError("Read error")):
        assert resolver._check_ast(file_path) is False

# --------------------------------------------------------
# 3.5. _run_tests
# --------------------------------------------------------
def test_run_tests_success(tmp_path, dummy_entry):
    resolver = TDRResolver(project_root=tmp_path)
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["pytest", "tests/test_dummy.py", "-q", "--tb=no"],
            returncode=0,
            stdout="OK",
            stderr=""
        )
        assert resolver._run_tests(dummy_entry) is True
        mock_run.assert_called_once()
        called_args = mock_run.call_args[0][0]
        assert called_args[1] == "tests/test_dummy.py"

def test_run_tests_failed(tmp_path, dummy_entry):
    resolver = TDRResolver(project_root=tmp_path)
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["pytest", "tests/test_dummy.py", "-q", "--tb=no"],
            returncode=1,
            stdout="FAIL",
            stderr="error"
        )
        assert resolver._run_tests(dummy_entry) is False

def test_run_tests_timeout(tmp_path, dummy_entry):
    resolver = TDRResolver(project_root=tmp_path)
    
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["pytest"], timeout=60)):
        assert resolver._run_tests(dummy_entry) is False

def test_run_tests_subprocess_error(tmp_path, dummy_entry):
    resolver = TDRResolver(project_root=tmp_path)
    
    with patch("subprocess.run", side_effect=subprocess.SubprocessError("Spawn error")):
        assert resolver._run_tests(dummy_entry) is False

def test_run_tests_default_target(tmp_path, dummy_entry):
    dummy_entry.related_test = None
    resolver = TDRResolver(project_root=tmp_path)
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0
        )
        assert resolver._run_tests(dummy_entry) is True
        called_args = mock_run.call_args[0][0]
        assert called_args[1] == "backend/tests/test_fitness_functions.py"

# --------------------------------------------------------
# 3.6. _rollback
# --------------------------------------------------------
def test_rollback_success(tmp_path):
    resolver = TDRResolver(project_root=tmp_path)
    file_path = tmp_path / "rollback.py"
    file_path.write_text("current content", encoding="utf-8")
    
    resolver._rollback(file_path, "backup content")
    assert file_path.read_text(encoding="utf-8") == "backup content"

def test_rollback_write_error(tmp_path):
    resolver = TDRResolver(project_root=tmp_path)
    file_path = tmp_path / "rollback.py"
    file_path.touch()
    
    with patch("builtins.open", side_effect=OSError("Write error")):
        resolver._rollback(file_path, "backup content")

# --------------------------------------------------------
# 3.7. _commit_fix
# --------------------------------------------------------
def test_commit_fix_success(tmp_path, dummy_entry):
    resolver = TDRResolver(project_root=tmp_path)
    
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=["git", "add"], returncode=0),
            subprocess.CompletedProcess(args=["git", "commit"], returncode=0)
        ]
        assert resolver._commit_fix(dummy_entry) is True
        assert mock_run.call_count == 2

def test_commit_fix_add_failed(tmp_path, dummy_entry):
    resolver = TDRResolver(project_root=tmp_path)
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=["git", "add"], returncode=1, stderr="git add error")
        assert resolver._commit_fix(dummy_entry) is False
        mock_run.assert_called_once()

def test_commit_fix_commit_failed(tmp_path, dummy_entry):
    resolver = TDRResolver(project_root=tmp_path)
    
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            subprocess.CompletedProcess(args=["git", "add"], returncode=0),
            subprocess.CompletedProcess(args=["git", "commit"], returncode=1, stderr="git commit error")
        ]
        assert resolver._commit_fix(dummy_entry) is False
        assert mock_run.call_count == 2

def test_commit_fix_subprocess_error(tmp_path, dummy_entry):
    resolver = TDRResolver(project_root=tmp_path)
    
    with patch("subprocess.run", side_effect=OSError("Git missing")):
        assert resolver._commit_fix(dummy_entry) is False
