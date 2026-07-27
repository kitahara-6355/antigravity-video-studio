import pytest
import os
import subprocess
import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from services.tdr_resolver import TDRResolver
from agents.memory.technical_debt import TechnicalDebtStore, TechnicalDebtEntry

# テスト隔離環境のフィクスチャ
@pytest.fixture
def test_env(tmp_path):
    # 1. Gitの初期化
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), capture_output=True, check=True)
    
    # 2. ダミーモジュール（負債付き）の作成
    # 負債パターン: except Exception as e:
    dummy_code = """import logging
logger = logging.getLogger(__name__)

def do_something():
    try:
        x = 1 / 0
    except Exception as e:
        pass
"""
    dummy_module_path = tmp_path / "dummy_module.py"
    with open(dummy_module_path, "w", encoding="utf-8") as f:
        f.write(dummy_code)
        
    # Gitコミットしてクリーンな状態にする
    subprocess.run(["git", "add", "dummy_module.py"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(tmp_path), capture_output=True, check=True)

    # 3. ダミーテストの作成（成功するもの）
    test_code_success = f"""import sys
sys.path.insert(0, r"{tmp_path}")
import dummy_module

def test_do_something():
    try:
        dummy_module.do_something()
    except ZeroDivisionError:
        pass
"""
    test_success_path = tmp_path / "test_success.py"
    with open(test_success_path, "w", encoding="utf-8") as f:
        f.write(test_code_success)
        
    # 4. ダミーテストの作成（失敗するもの）
    test_code_fail = f"""import sys
sys.path.insert(0, r"{tmp_path}")
import dummy_module

def test_do_something():
    dummy_module.do_something()
    assert False, "Forced failure"
"""
    test_fail_path = tmp_path / "test_fail.py"
    with open(test_fail_path, "w", encoding="utf-8") as f:
        f.write(test_code_fail)

    # 5. TDR台帳 (technical_debt_index.json) の作成
    debt_index = {
        "version": "1.1",
        "last_updated": "2026-05-24T12:00:00",
        "entry_count": 1,
        "entries": [
            {
                "debt_id": "TD-001",
                "category": "MINOR_INFRA",
                "file_path": "dummy_module.py",
                "line_number": 6,
                "pattern": "    except Exception as e:\n        pass",
                "cause_pattern": "DP-01",
                "fix_pattern": "    except Exception as e:\n        logger.exception(e)\n        raise",
                "status": "open",
                "registered_at": "2026-05-24T12:00:00",
                "registered_by": "test",
                "fixed_at": None,
                "fixed_by": None,
                "fix_evidence": None,
                "related_test": "test_success.py",
                "notes": "",
                "tags": [],
                "last_verified_at": None,
                "confidence": 1.0,
                "estimated_fix_minutes": 10
            }
        ],
        "cause_patterns": [],
        "changelog": []
    }
    
    # 隔離環境のagents/memoryフォルダを作成し、そこにTDRインデックスを置く
    memory_dir = tmp_path / "agents" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    debt_index_path = memory_dir / "technical_debt_index.json"
    with open(debt_index_path, "w", encoding="utf-8") as f:
        json.dump(debt_index, f, ensure_ascii=False, indent=2)
        
    store = TechnicalDebtStore(debt_dir=memory_dir)
    
    return {
        "tmp_path": tmp_path,
        "dummy_module_path": dummy_module_path,
        "test_success_path": test_success_path,
        "test_fail_path": test_fail_path,
        "debt_index_path": debt_index_path,
        "store": store
    }

# 1. 正常系のE2Eテスト
def test_e2e_tdr_resolve_success(test_env):
    resolver = TDRResolver(debt_store=test_env["store"], project_root=test_env["tmp_path"])
    
    res = resolver.resolve_minor_debts(target_category="MINOR_INFRA")
    
    assert res["total_found"] == 1
    assert res["resolved"] == 1
    assert res["failed"] == 0
    assert res["rolled_back"] == 0
    
    # ファイル内容が修正されているか確認
    with open(test_env["dummy_module_path"], "r", encoding="utf-8") as f:
        content = f.read()
    assert "logger.exception(e)" in content
    assert "raise" in content
    
    # TDRストア上の状態がfixedになっているか確認
    entry = test_env["store"].get_entry("TD-001")
    assert entry.status == "fixed"
    assert entry.fixed_by == "tdr_resolver"
    
    # Gitコミットが実行されているか確認
    git_log = subprocess.run(["git", "log", "-n", "1", "--oneline"], cwd=str(test_env["tmp_path"]), capture_output=True, text=True, check=True)
    assert "[TDRResolver] Auto resolved debt TD-001 in dummy_module.py" in git_log.stdout

# 2. 異常系: テスト失敗時のロールバックとソースコード保護
def test_e2e_tdr_resolve_rollback_on_test_failure(test_env):
    # テストファイルを失敗するものに変更
    entry = test_env["store"].get_entry("TD-001")
    entry.related_test = "test_fail.py"
    # 台帳ファイルを再度保存して同期
    test_env["store"]._save()
    
    resolver = TDRResolver(debt_store=test_env["store"], project_root=test_env["tmp_path"])
    res = resolver.resolve_minor_debts(target_category="MINOR_INFRA")
    
    assert res["total_found"] == 1
    assert res["resolved"] == 0
    assert res["failed"] == 1
    assert res["rolled_back"] == 1
    
    # ファイルが元の内容にロールバックされているか確認
    with open(test_env["dummy_module_path"], "r", encoding="utf-8") as f:
        content = f.read()
    assert "logger.exception(e)" not in content
    assert "raise" not in content
    assert "pass" in content  # 元のまま
    
    # TDRストア上の状態がopenのままであること
    entry_after = test_env["store"].get_entry("TD-001")
    assert entry_after.status == "open"
    
    # Gitコミットが行われていないこと（Initial commit のままであること）
    git_log = subprocess.run(["git", "log", "--oneline"], cwd=str(test_env["tmp_path"]), capture_output=True, text=True, check=True)
    assert "Auto resolved debt" not in git_log.stdout

# 3. 異常系: ASTチェック失敗時のロールバック
def test_e2e_tdr_resolve_rollback_on_ast_failure(test_env):
    # fix_pattern を文法エラーになる値に設定
    entry = test_env["store"].get_entry("TD-001")
    entry.fix_pattern = "    except Exception as e:\n        logger.exception(e)\n        invalid python syntax error here!!!"
    test_env["store"]._save()
    
    resolver = TDRResolver(debt_store=test_env["store"], project_root=test_env["tmp_path"])
    res = resolver.resolve_minor_debts(target_category="MINOR_INFRA")
    
    assert res["resolved"] == 0
    assert res["failed"] == 1
    assert res["rolled_back"] == 1
    
    # 元に戻っているか
    with open(test_env["dummy_module_path"], "r", encoding="utf-8") as f:
        content = f.read()
    assert "invalid python syntax" not in content
    assert "pass" in content
    
    entry_after = test_env["store"].get_entry("TD-001")
    assert entry_after.status == "open"

# 4. 異常系: Gitコミット失敗時のロールバック
def test_e2e_tdr_resolve_rollback_on_git_commit_failure(test_env):
    resolver = TDRResolver(debt_store=test_env["store"], project_root=test_env["tmp_path"])
    
    # Gitコミットが失敗するように _commit_fix をモック化して False を返すようにする
    with patch.object(resolver, "_commit_fix", return_value=False):
        res = resolver.resolve_minor_debts(target_category="MINOR_INFRA")
        
        assert res["resolved"] == 0
        assert res["failed"] == 1
        assert res["rolled_back"] == 1
        
        # ロールバックされて元の内容になっているか
        with open(test_env["dummy_module_path"], "r", encoding="utf-8") as f:
            content = f.read()
        assert "logger.exception(e)" not in content
        assert "pass" in content
        
        # TDRストアで reopen されて status="open" になっていること
        entry = test_env["store"].get_entry("TD-001")
        assert entry.status == "open"

# 5. カバレッジ網羅用: 境界エラーと例外ハンドリング
def test_tdr_resolver_edge_cases(test_env):
    resolver = TDRResolver(debt_store=test_env["store"], project_root=test_env["tmp_path"])
    
    # ファイルが存在しない場合
    entry_nonexistent = test_env["store"].get_entry("TD-001")
    entry_nonexistent.file_path = "non_existent_file.py"
    assert resolver._apply_fix(entry_nonexistent) is False
    
    # ファイル読み込みエラー (PermissionError/IOError)
    entry = test_env["store"].get_entry("TD-001")
    entry.file_path = "dummy_module.py"
    with patch("builtins.open", side_effect=IOError("Mock read error")):
        assert resolver._apply_fix(entry) is False
        
    # パターンが見つからない場合
    entry.pattern = "non_existent_pattern_to_match_in_file"
    assert resolver._apply_fix(entry) is False
    
    # ファイル書き込みエラー (PermissionError/IOError)
    entry.pattern = "    except Exception as e:\n        pass"
    # m_openのモック
    m_open = MagicMock()
    # 読み込みは成功させ、書き込みだけ失敗させる
    with open(test_env["dummy_module_path"], "r", encoding="utf-8") as f:
        original_data = f.read()
        
    original_open = open
    def mock_open_fn(file, mode="r", *args, **kwargs):
        if "w" in mode:
            raise IOError("Mock write error")
        # 読み込み用には通常の実体ファイルを返す
        return original_open(file, mode, *args, **kwargs)
        
    with patch("builtins.open", side_effect=mock_open_fn):
        assert resolver._apply_fix(entry) is False

    # ASTチェック時のファイル読み込みエラー
    call_count = 0
    original_open = open

    def mock_open_for_ast_fail(file, mode="r", *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 3:
            raise IOError("AST read error")
        return original_open(file, mode, *args, **kwargs)

    with patch("builtins.open", side_effect=mock_open_for_ast_fail):
        assert resolver._apply_fix(entry) is False

    # テスト実行時のタイムアウトエラー
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="pytest", timeout=60)):
        assert resolver._run_tests(entry) is False
        
    # テスト実行時のSubprocessError
    with patch("subprocess.run", side_effect=subprocess.SubprocessError("Mock error")):
        assert resolver._run_tests(entry) is False
        
    # ロールバック失敗時のクリティカルエラーパス
    with patch("builtins.open", side_effect=IOError("Rollback write error")):
        resolver._rollback(test_env["dummy_module_path"], "backup")
        # ログにCRITICALが出力され、例外にならず終了することを確認

# 6. Gitコマンドのエラーケースカバレッジ
def test_git_commit_edge_cases(test_env):
    resolver = TDRResolver(debt_store=test_env["store"], project_root=test_env["tmp_path"])
    entry = test_env["store"].get_entry("TD-001")
    
    # git add 失敗
    mock_run_res = MagicMock()
    mock_run_res.returncode = 1
    mock_run_res.stderr = "Mock add error"
    with patch("subprocess.run", return_value=mock_run_res) as mock_run:
        assert resolver._commit_fix(entry) is False
        mock_run.assert_called_with(["git", "add", "dummy_module.py"], cwd=str(test_env["tmp_path"]), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        
    # git commit 失敗
    mock_run_add = MagicMock(returncode=0)
    mock_run_commit = MagicMock(returncode=1, stderr="Mock commit error")
    with patch("subprocess.run", side_effect=[mock_run_add, mock_run_commit]):
        assert resolver._commit_fix(entry) is False
        
    # git コマンド実行時の例外 (OSError等)
    with patch("subprocess.run", side_effect=OSError("Git not installed")):
        assert resolver._commit_fix(entry) is False

# 7. TDRストア保存失敗時の例外ハンドリング
def test_resolve_debt_store_error(test_env):
    resolver = TDRResolver(debt_store=test_env["store"], project_root=test_env["tmp_path"])
    
    # Store.resolve_debtが例外を投げる場合
    with patch.object(test_env["store"], "resolve_debt", side_effect=ValueError("Mock db write error")):
        res = resolver.resolve_minor_debts(target_category="MINOR_INFRA")
        assert res["resolved"] == 0
        assert res["failed"] == 1
        assert res["rolled_back"] == 1

# 8. reopen_debt失敗時の例外ハンドリング
def test_reopen_debt_failure_on_rollback(test_env):
    resolver = TDRResolver(debt_store=test_env["store"], project_root=test_env["tmp_path"])
    
    # _commit_fixを失敗させ、さらにreopen_debtも失敗させる
    with patch.object(resolver, "_commit_fix", return_value=False),          patch.object(test_env["store"], "reopen_debt", side_effect=ValueError("Reopen error")):
         
        res = resolver.resolve_minor_debts(target_category="MINOR_INFRA")
        assert res["resolved"] == 0
        assert res["failed"] == 1
        assert res["rolled_back"] == 1
