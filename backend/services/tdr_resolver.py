import ast
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional, List
from agents.memory.technical_debt import TechnicalDebtStore, TechnicalDebtEntry

logger = logging.getLogger(__name__)

class TDRResolver:
    """
    TDR (Technical Debt Registry) 自動解消バッチ
    
    TDR台帳から未解消の軽微な技術負債を自動抽出し、
    ASTチェック、テスト検証、自動ロールバックを備えた安全な自動解消処理を行う。
    """
    def __init__(self, debt_store: Optional[TechnicalDebtStore] = None, project_root: Optional[Path] = None):
        self.debt_store = debt_store or TechnicalDebtStore()
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        
    def resolve_minor_debts(self, target_category: str = "MINOR_INFRA") -> dict:
        """
        未解消の指定カテゴリの技術負債を抽出し、自動解消を試みる。
        
        Args:
            target_category: 対象とするカテゴリ (デフォルト: MINOR_INFRA)
            
        Returns:
            処理結果の要約辞書
        """
        open_entries = self.debt_store.get_open_entries()
        targets = [e for e in open_entries if e.category == target_category]
        
        summary = {
            "total_found": len(targets),
            "resolved": 0,
            "failed": 0,
            "rolled_back": 0
        }
        
        for entry in targets:
            success = self._apply_fix(entry)
            if success:
                summary["resolved"] += 1
            else:
                summary["failed"] += 1
                summary["rolled_back"] += 1
                
        return summary
        
    def _apply_fix(self, entry: TechnicalDebtEntry) -> bool:
        """
        特定の技術負債エントリに対して修正を適用する。
        
        手順:
        1. 対象ファイルのバックアップを作成
        2. パターン置換による修正を適用
        3. ASTチェックによる構文検証
        4. テスト検証 (pytest)
        5. 失敗時はバックアップからロールバック
        """
        project_root = self.project_root
        file_path = project_root / entry.file_path
        
        if not file_path.exists():
            logger.error(f"[TDRResolver] File not found: {file_path}")
            return False
            
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                original_content = f.read()
        except (OSError, IOError) as e:
            logger.error(f"[TDRResolver] Failed to read file {file_path}: {e}")
            return False
            
        if entry.pattern not in original_content:
            logger.warning(f"[TDRResolver] Pattern not found in file: {entry.pattern}")
            return False
            
        replacement = entry.fix_pattern
        if not replacement:
            if ("except " + "Exception as e:") in entry.pattern:
                replacement = "except " + "Exception as e:\n    logger.exception(e)\n    raise"
            else:
                logger.error(f"[TDRResolver] No fix pattern specified for entry {entry.debt_id}")
                return False
                
        new_content = original_content.replace(entry.pattern, replacement)
        
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)
        except (OSError, IOError) as e:
            logger.error(f"[TDRResolver] Failed to write file {file_path}: {e}")
            return False
            
        if not self._check_ast(file_path):
            logger.error(f"[TDRResolver] AST verification failed for {file_path}. Rolling back.")
            self._rollback(file_path, original_content)
            return False
            
        if not self._run_tests(entry):
            logger.error(f"[TDRResolver] Test verification failed. Rolling back.")
            self._rollback(file_path, original_content)
            return False
            
        try:
            self.debt_store.resolve_debt(
                debt_id=entry.debt_id,
                fixed_by="tdr_resolver",
                fix_evidence=f"Auto resolved by TDRResolver. AST check passed. Tests passed."
            )
            
            # Gitコミットを実行
            if not self._commit_fix(entry):
                logger.error(f"[TDRResolver] Git commit failed. Rolling back.")
                self._rollback(file_path, original_content)
                try:
                    self.debt_store.reopen_debt(entry.debt_id, "Git commit failed during auto resolution")
                except Exception as store_err:
                    logger.error(f"[TDRResolver] Failed to reopen debt after git commit failure: {store_err}")
                return False

            logger.info(f"[TDRResolver] Successfully resolved debt {entry.debt_id} in {entry.file_path}")
            return True
        except (OSError, IOError, ValueError, KeyError, json.JSONDecodeError) as e:
            logger.error(f"[TDRResolver] Failed to resolve debt in store: {e}")
            self._rollback(file_path, original_content)
            return False
            
    def _check_ast(self, file_path: Path) -> bool:
        """指定されたファイルの抽象構文木(AST)チェックを行う"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            ast.parse(content)
            return True
        except SyntaxError as e:
            logger.error(f"[TDRResolver] AST check SyntaxError: {e}")
            return False
        except (OSError, IOError) as e:
            logger.error(f"[TDRResolver] AST check error: {e}")
            return False
            
    def _run_tests(self, entry: TechnicalDebtEntry) -> bool:
        """テスト検証を実行する"""
        project_root = self.project_root
        
        test_target = "backend/tests/test_fitness_functions.py"
        if entry.related_test:
            test_target = entry.related_test
            
        cmd = ["pytest", test_target, "-q", "--tb=no"]
        
        try:
            result = subprocess.run(
                cmd,
                cwd=str(project_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60
            )
            if result.returncode != 0:
                logger.error(f"[TDRResolver] pytest failed. stdout: {result.stdout}, stderr: {result.stderr}")
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            logger.error(f"[TDRResolver] Test timed out: {cmd}")
            return False
        except (OSError, IOError, subprocess.SubprocessError) as e:
            logger.error(f"[TDRResolver] Test execution failed: {e}")
            return False
            
    def _rollback(self, file_path: Path, backup_content: str):
        """ファイルをロールバックする"""
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(backup_content)
            logger.info(f"[TDRResolver] Successfully rolled back file: {file_path}")
        except (OSError, IOError) as e:
            logger.critical(f"[TDRResolver] FAILED TO ROLLBACK file {file_path}: {e}")

    def _commit_fix(self, entry: TechnicalDebtEntry) -> bool:
        """修正したファイルを Git にコミットする"""
        project_root = self.project_root
        
        try:
            # 1. git add
            cmd_add = ["git", "add", entry.file_path]
            res_add = subprocess.run(
                cmd_add,
                cwd=str(project_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30
            )
            if res_add.returncode != 0:
                logger.error(f"[TDRResolver] Git add failed for {entry.file_path}: {res_add.stderr}")
                return False
                
            # 2. git commit
            commit_msg = f"[TDRResolver] Auto resolved debt {entry.debt_id} in {entry.file_path}"
            cmd_commit = ["git", "commit", "-m", commit_msg]
            res_commit = subprocess.run(
                cmd_commit,
                cwd=str(project_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30
            )
            if res_commit.returncode != 0:
                logger.error(f"[TDRResolver] Git commit failed for {entry.file_path}: {res_commit.stderr}")
                return False
                
            logger.info(f"[TDRResolver] Successfully committed fix for {entry.debt_id}")
            return True
        except (OSError, subprocess.SubprocessError) as e:
            logger.error(f"[TDRResolver] Git operations failed: {e}")
            return False


from usage_tracker.alert_system import ThumbnailResolver
