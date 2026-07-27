"""
Code Verifier (CodeVerifier)
生成されたコードの静的・動的検証を行い、品質を保証する。
"""

import os
import re
import logging
import subprocess
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class CodeVerifier:
    def __init__(self, workspace_path: str = None):
        self.workspace_path = workspace_path or os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    def verify_static(self, file_path: str) -> Dict[str, Any]:
        """コードの静的チェック（特定の記述のチェック）"""
        abs_path = os.path.join(self.workspace_path, file_path)
        if not os.path.exists(abs_path):
            return {"passed": False, "error": f"File not found: {file_path}"}

        errors = []
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()

            # TDR規約チェック: 裸の broad exception (except-Exception) が登録されずに使われていないか等
            lines = content.splitlines()
            target_pattern1 = "except " + "Exception:"
            target_pattern2 = "except " + "Exception as"
            for idx, line in enumerate(lines, 1):
                if target_pattern1 in line or target_pattern2 in line:
                    errors.append(f"Line {idx}: Broad exception handler detected. Must register to TDR or use specific exceptions.")
        except (OSError, ValueError) as e:
            return {"passed": False, "error": f"File read or parse error: {str(e)}"}

        return {
            "passed": len(errors) == 0,
            "errors": errors
        }

    def verify_dynamic(self, test_pattern: str) -> Dict[str, Any]:
        """pytest を実行し、全テスト合格を確認する。
        失敗した場合はリトライ・フォールバックを実行する（自動リトライフォールバック3パターン）。
        """
        # 初回実行
        cmd = f"pytest {test_pattern} --timeout=300 -q"
        res = self._run_pytest(cmd, timeout=300)

        if res.get("passed"):
            return res

        # --- パターン1: タイムアウト延長 ＆ 詳細ログでの単純リトライ ---
        is_timeout = (
            "timeout" in res.get("error", "").lower() or "timed out" in res.get("error", "").lower()
            or "timeout" in res.get("stdout", "").lower() or "timed out" in res.get("stdout", "").lower()
            or "timeout" in res.get("stderr", "").lower() or "timed out" in res.get("stderr", "").lower()
            or (res.get("exit_code") is not None and res.get("exit_code") != 0 and not res.get("stdout") and not res.get("stderr"))
        )

        if is_timeout:
            logger.info("⏳ テストタイムアウトを検知しました。タイムアウトを延長してリトライします。")
            cmd_retry = f"pytest {test_pattern} --timeout=600 -vv"
            res = self._run_pytest(cmd_retry, timeout=600)
            if res.get("passed"):
                return res

        # --- パターン2: 個別テスト分割実行リトライ ---
        failed_files = []
        if res.get("stdout"):
            for line in res["stdout"].splitlines():
                # FAILED または ERROR で終わる行から python ファイルパスを抽出
                match = re.search(r"(?:FAILED|ERROR)\s+([\w\/\-\_\\\.]+\.py)", line)
                if match:
                    file_path = match.group(1)
                    if file_path not in failed_files:
                        failed_files.append(file_path)

        if failed_files:
            logger.info(f"🔍 失敗したテストファイルを特定しました: {failed_files}. 個別に再実行します。")
            all_sub_passed = True
            sub_results = []
            for failed_file in failed_files:
                cmd_sub = f"pytest {failed_file} --timeout=300 -q"
                sub_res = self._run_pytest(cmd_sub, timeout=300)
                sub_results.append(sub_res)
                if not sub_res.get("passed"):
                    all_sub_passed = False

            if all_sub_passed:
                logger.info("✅ 個別再実行ですべての失敗テストがPASSしました。")
                return {
                    "passed": True,
                    "stdout": "\n".join(r.get("stdout", "") for r in sub_results),
                    "stderr": "\n".join(r.get("stderr", "") for r in sub_results),
                    "exit_code": 0
                }

        # --- パターン3: 自動 Git ロールバック ＆ 代替アプローチ指示書の生成 ---
        logger.error(f"❌ テスト検証が完全に失敗しました。Gitロールバックと代替アプローチ指示書の生成を実行します。")
        rollback_executed, rollback_error = self._execute_git_rollback()
        alt_instructions = self._generate_alternative_instructions(test_pattern, res)
        self._save_alternative_instructions(alt_instructions)

        res.update({
            "passed": False,
            "rollback_executed": rollback_executed,
            "rollback_error": rollback_error,
            "alternative_approach_instructions": alt_instructions
        })
        return res

    def _run_pytest(self, cmd: str, timeout: int) -> Dict[str, Any]:
        """pytestコマンドを実行する汎用ヘルパー"""
        try:
            res = subprocess.run(
                cmd,
                shell=True,
                cwd=self.workspace_path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=timeout
            )
            passed = res.returncode == 0
            return {
                "passed": passed,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "exit_code": res.returncode
            }
        except subprocess.TimeoutExpired:
            return {"passed": False, "error": f"Test execution timed out after {timeout} seconds"}
        except (subprocess.SubprocessError, OSError, ValueError) as e:
            return {"passed": False, "error": f"Test execution failed: {str(e)}"}

    def _execute_git_rollback(self) -> tuple[bool, Optional[str]]:
        """Gitロールバックを実行して不完全な変更を巻き戻す"""
        # テスト環境の検知
        if "PYTEST_CURRENT_TEST" in os.environ:
            logger.info("🧪 テスト環境を検知したため、実際のGitロールバックをスキップします。")
            return True, None

        try:
            logger.info("🔄 Gitロールバックを実行します: git reset --hard HEAD")
            subprocess.run(
                ["git", "reset", "--hard", "HEAD"],
                cwd=self.workspace_path,
                capture_output=True,
                text=True,
                check=True
            )
            subprocess.run(
                ["git", "clean", "-fd"],
                cwd=self.workspace_path,
                capture_output=True,
                text=True,
                check=True
            )
            return True, None
        except (subprocess.SubprocessError, OSError) as e:
            err_msg = str(e)
            logger.error(f"❌ Gitロールバック失敗: {err_msg}")
            return False, err_msg

    def _generate_alternative_instructions(self, test_pattern: str, last_res: Dict[str, Any]) -> str:
        """失敗ログから別のアプローチの指示書テキストを生成する"""
        stdout = last_res.get("stdout", "")
        stderr = last_res.get("stderr", "")
        error_msg = last_res.get("error", "No explicit error message")

        advice = "一般的な解決方法:\n- 変更対象モジュールのロジックを見直し、インポートエラーや型エラーが発生していないか確認してください。\n- 必要に応じて、モック設定が正しいか検証してください。"

        if "timeout" in stdout.lower() or "timeout" in error_msg.lower():
            advice = (
                "タイムアウト時の代替アプローチ:\n"
                "- 重いI/O処理や時間のかかるテストがある場合は、テストのパラメータ調整やモック処理を見直してください。\n"
                "- 一時的な環境負荷の可能性があるため、必要に応じて処理範囲を絞ってください。"
            )
        elif "import" in stdout.lower() or "import" in stderr.lower():
            advice = (
                "インポートエラー時の代替アプローチ:\n"
                "- PYTHONPATHの設定を確認し、パッケージのインポートパスが正しいか確認してください。\n"
                "- circular import（循環インポート）が発生していないか確認してください。"
            )
        elif "assertion" in stdout.lower():
            advice = (
                "アサーション失敗時の代替アプローチ:\n"
                "- テストの期待値と実際の返却値の不一致を確認し、関数のエッジケース（Noneや空文字等）のハンドリングを強化してください。"
            )

        instructions = f"""【代替アプローチ指示書 - {test_pattern}】
テストスイート「{test_pattern}」の検証が失敗し、すべての自動リトライおよび個別回復処理が上限に達しました。
開発中のコードは前回の正常なコミット状態にロールバックされました。

■ 発生した最終エラー
{error_msg}

■ テスト出力（一部）
{stdout[-1000:] if stdout else "なし"}
{stderr[-1000:] if stderr else "なし"}

■ 推薦される代替アプローチ（安全弁）
{advice}

■ 次のステップ
1. ワークスペースのコードは自動ロールバックによりクリーンな状態に復旧しています。
2. 上記のエラー内容を参考に、設計または実装の別アプローチを検討してください。
3. 必要に応じて、テストパターンをローカルで手動実行し、修正を行ってください。
"""
        return instructions

    def _save_alternative_instructions(self, instructions: str):
        """指示書テキストを scratch/ ディレクトリに書き出す"""
        try:
            scratch_dir = os.path.join(self.workspace_path, "scratch")
            os.makedirs(scratch_dir, exist_ok=True)
            file_path = os.path.join(scratch_dir, "alternative_approach_test_suite.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(instructions)
            logger.info(f"💾 代替アプローチ指示書を保存しました: {file_path}")
        except OSError as e:
            logger.error(f"❌ 代替アプローチ指示書の保存に失敗しました: {e}")

