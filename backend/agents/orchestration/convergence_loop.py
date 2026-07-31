"""
Convergence Loop (収束ループ)

サブエージェントがタスク失敗(fail)を返した際、エラーログやスタックトレースを解析し、
修正のためのフィードバックプロンプトを生成してリトライを指示する司令塔。

リトライ上限(MAX_RETRIES, デフォルト3回)に達するまで同一モジュールの
修正・検証を繰り返し実行させる。

# satisfies: REQ-CONV-01
"""

try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent
TASK_QUEUE_PATH = _writable_path("backend/agents/orchestration/task_queue.json")
FLASH_REPORTS_PATH = _BASE_DIR / "flash_reports.jsonl"

# デフォルトのリトライ上限
DEFAULT_MAX_RETRIES = 3


def _now_iso() -> str:
    """現在時刻をISO 8601形式で返す"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict:
    """JSONファイルを安全に読み込む"""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to read json from {path}: {e}")
        return {}


def _write_json(path: Path, data: dict) -> None:
    """JSONファイルをUTF-8で安全に書き込む"""
    import uuid
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f".tmp-{uuid.uuid4().hex}")
    try:
        with open(temp_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        temp_path.replace(path)
    except OSError as e:
        logger.error(f"Failed to write json to {path} atomically: {e}")
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise e


def _append_jsonl(path: Path, record: dict) -> None:
    """JSONLファイルに1行追記する"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


class ConvergenceLoop:
    """
    収束ループ（Convergence Loop）

    タスク失敗時にエラーを解析し、修正指示（フィードバックプロンプト）を生成して
    リトライを自動管理する。

    # satisfies: REQ-CONV-01

    使用例:
        loop = ConvergenceLoop(max_retries=3)
        decision = loop.should_retry(task, report)
        if decision["retry"]:
            loop.prepare_retry(task_id, decision["feedback_prompt"])
    """

    def __init__(self, max_retries: int = DEFAULT_MAX_RETRIES,
                 task_queue_path: Optional[Path] = None,
                 flash_reports_path: Optional[Path] = None):
        """
        Args:
            max_retries: 1タスクあたりの最大リトライ回数
            task_queue_path: タスクキューのパス（テスト用にオーバーライド可能）
            flash_reports_path: レポートファイルのパス（テスト用にオーバーライド可能）
        """
        self.max_retries = max_retries
        self.task_queue_path = task_queue_path or TASK_QUEUE_PATH
        self.flash_reports_path = flash_reports_path or FLASH_REPORTS_PATH

    # =========================================================================
    # リトライ可否判定
    # =========================================================================

    def should_retry(self, task: dict, report: Optional[dict] = None) -> dict:
        """
        タスクのリトライ可否を判定し、リトライする場合はフィードバックプロンプトを生成する。

        # satisfies: REQ-CONV-03

        Args:
            task: タスクキュー内のタスクオブジェクト
            report: mark_task_done() に渡されたレポート（エラー情報含む）

        Returns:
            {
                "retry": bool,          # リトライすべきか
                "reason": str,          # 判定理由
                "retry_count": int,     # 現在のリトライ回数
                "feedback_prompt": str, # リトライ時の追加指示
            }
        """
        retry_count = task.get("retry_count", 0)

        # リトライ上限チェック
        if retry_count >= self.max_retries:
            return {
                "retry": False,
                "reason": f"リトライ上限({self.max_retries}回)に到達。手動対応が必要。",
                "retry_count": retry_count,
                "feedback_prompt": "",
            }

        # レポートがない場合、リトライ不可
        if not report:
            return {
                "retry": False,
                "reason": "エラーレポートが存在しないため、フィードバック生成不可。",
                "retry_count": retry_count,
                "feedback_prompt": "",
            }

        # エラー内容の解析
        error_msg = report.get("error", report.get("message", ""))
        traceback_str = report.get("traceback", "")
        changed_files = report.get("changed_files", [])

        # 致命的エラー（リトライ不適切）のパターン
        if self._is_fatal_error(error_msg, traceback_str):
            return {
                "retry": False,
                "reason": f"致命的エラーを検出。リトライは不適切: {error_msg[:100]}",
                "retry_count": retry_count,
                "feedback_prompt": "",
            }

        # フィードバックプロンプトの生成
        feedback = self._generate_feedback_prompt(
            task=task,
            error_msg=error_msg,
            traceback_str=traceback_str,
            changed_files=changed_files,
            retry_count=retry_count,
        )

        return {
            "retry": True,
            "reason": f"リトライ可能（{retry_count + 1}/{self.max_retries}回目）",
            "retry_count": retry_count,
            "feedback_prompt": feedback,
        }

    # =========================================================================
    # リトライの準備（キュー更新）
    # =========================================================================

    def prepare_retry(self, task_id: str, feedback_prompt: str) -> bool:
        """
        タスクをリトライ状態（pending）に戻し、フィードバックプロンプトを付与する。

        # satisfies: REQ-CONV-02, REQ-CONV-03

        Args:
            task_id: リトライ対象のタスクID
            feedback_prompt: エラー解析から生成されたフィードバック指示

        Returns:
            True: キューの更新に成功
            False: タスクが見つからない等の失敗
        """
        queue = _read_json(self.task_queue_path)
        task_found = False

        for task in queue.get("tasks", []):
            if task["id"] == task_id:
                task_found = True
                # retry_count をインクリメント（# satisfies: REQ-CONV-02）
                task["retry_count"] = task.get("retry_count", 0) + 1
                # ステータスを pending に戻す
                task["status"] = "pending"
                task["started_at"] = None
                task["assigned_agent"] = None
                # フィードバックプロンプトを instruction に追記
                original_instruction = task.get("instruction", "")
                retry_num = task["retry_count"]
                task["instruction"] = (
                    f"{original_instruction}\n\n"
                    f"---\n"
                    f"## 🔄 リトライ指示 (試行 {retry_num}/{self.max_retries})\n\n"
                    f"{feedback_prompt}"
                )
                task["result"] = None  # 前回の結果をクリア
                break

        if not task_found:
            logger.warning(f"Task {task_id} not found in queue for retry.")
            return False

        _write_json(self.task_queue_path, queue)
        logger.info(f"Task {task_id} prepared for retry (count={task.get('retry_count', '?')})")
        return True

    # =========================================================================
    # リトライ結果の記録
    # =========================================================================

    def record_retry_event(self, task_id: str, retry_count: int,
                           result: str, error_msg: str = "",
                           target_module: str = "") -> None:
        """
        リトライの発生と結果を flash_reports.jsonl に記録する。

        # satisfies: REQ-CONV-04

        Args:
            task_id: タスクID
            retry_count: リトライ回数
            result: "retry_success" or "retry_fail" or "retry_exhausted"
            error_msg: エラーメッセージ
            target_module: 対象モジュール
        """
        record = {
            "type": "convergence_loop_event",
            "task_id": task_id,
            "retry_count": retry_count,
            "result": result,
            "error_msg": error_msg[:500] if error_msg else "",
            "target_module": target_module,
            "timestamp": _now_iso(),
        }
        _append_jsonl(self.flash_reports_path, record)
        logger.info(
            f"[ConvergenceLoop] Recorded event: task={task_id}, "
            f"retry={retry_count}, result={result}"
        )

    # =========================================================================
    # 統計情報
    # =========================================================================

    def get_retry_stats(self) -> dict:
        """
        flash_reports.jsonl から収束ループのリトライ統計を集計する。

        Returns:
            {
                "total_retries": int,
                "retry_successes": int,
                "retry_failures": int,
                "retry_exhausted": int,
                "modules_retried": list[str],
            }
        """
        stats = {
            "total_retries": 0,
            "retry_successes": 0,
            "retry_failures": 0,
            "retry_exhausted": 0,
            "modules_retried": [],
        }

        if not self.flash_reports_path.exists():
            return stats

        try:
            with open(self.flash_reports_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if record.get("type") != "convergence_loop_event":
                        continue

                    stats["total_retries"] += 1
                    result = record.get("result", "")
                    if result == "retry_success":
                        stats["retry_successes"] += 1
                    elif result == "retry_fail":
                        stats["retry_failures"] += 1
                    elif result == "retry_exhausted":
                        stats["retry_exhausted"] += 1

                    module = record.get("target_module", "")
                    if module and module not in stats["modules_retried"]:
                        stats["modules_retried"].append(module)
        except OSError:
            pass

        return stats

    # =========================================================================
    # 内部メソッド
    # =========================================================================

    def _is_fatal_error(self, error_msg: str, traceback_str: str) -> bool:
        """
        リトライしても解決しない致命的エラーパターンを検出する。

        致命的パターン:
        - SyntaxError (コード自体が壊れている → AIの生成ミス)
        - ImportError / ModuleNotFoundError (依存関係の問題)
        - PermissionError (ファイルシステム権限)
        - MemoryError (リソース不足)
        - MAX_RETRIES_EXCEEDED (既に上限到達)
        """
        combined = f"{error_msg} {traceback_str}".lower()

        fatal_patterns = [
            "syntaxerror",
            "indentationerror",
            "modulenotfounderror",
            "permissionerror",
            "memoryerror",
            "max_retries_exceeded",
            "killed",  # OOM killer
        ]

        for pattern in fatal_patterns:
            if pattern in combined:
                return True

        return False

    def _generate_feedback_prompt(self, task: dict, error_msg: str,
                                   traceback_str: str,
                                   changed_files: list,
                                   retry_count: int) -> str:
        """
        エラー情報を解析し、リトライ用のフィードバックプロンプトを生成する。

        戦略:
        1. エラーメッセージとトレースバックから失敗箇所を特定
        2. エラータイプに応じた修正ガイダンスを付与
        3. 前回変更したファイルのコンテキストを提供
        """
        sections = []

        # 1. 前回の失敗サマリー
        sections.append(
            f"### 前回の失敗（試行 {retry_count} 回目）\n"
            f"**エラー**: {error_msg[:300]}\n"
        )

        # 2. トレースバック解析
        if traceback_str:
            # 最も関連する行を抽出
            relevant_lines = self._extract_relevant_traceback(traceback_str)
            if relevant_lines:
                sections.append(
                    f"### エラー箇所（トレースバック抜粋）\n"
                    f"```\n{relevant_lines}\n```\n"
                )

        # 3. エラータイプ別のガイダンス
        guidance = self._classify_error_guidance(error_msg, traceback_str)
        if guidance:
            sections.append(f"### 修正ガイダンス\n{guidance}\n")

        # 4. 前回変更ファイルの参照指示
        if changed_files:
            files_list = "\n".join(f"- `{f}`" for f in changed_files[:5])
            sections.append(
                f"### 前回変更したファイル（確認必須）\n{files_list}\n"
            )

        # 5. 一般的な注意事項
        sections.append(
            "### 注意事項\n"
            "- 前回のエラーを踏まえ、同じ失敗を繰り返さないこと\n"
            "- pytest --timeout=300 で全テストPASS確認必須\n"
            "- プロダクションコードの変更は最小限に留めること\n"
        )

        return "\n".join(sections)

    def _extract_relevant_traceback(self, traceback_str: str) -> str:
        """トレースバックから最も関連する部分（最後の5行）を抽出する"""
        lines = traceback_str.strip().splitlines()
        if len(lines) <= 8:
            return traceback_str.strip()

        # 最後の例外行と、直前のFile/行番号を含む部分を抽出
        relevant = []
        for i, line in enumerate(lines):
            if line.strip().startswith("File ") or \
               line.strip().startswith("  File ") or \
               i >= len(lines) - 3:
                relevant.append(line)

        # 最大8行に制限
        return "\n".join(relevant[-8:])

    def _classify_error_guidance(self, error_msg: str, traceback_str: str) -> str:
        """エラーの種類に応じた修正ガイダンスを返す"""
        combined = f"{error_msg} {traceback_str}".lower()

        if "assertionerror" in combined:
            return (
                "- **アサーションエラー**: テストの期待値が実装と一致していません。\n"
                "- 実装コードのロジックを再確認し、テストの期待値を修正するか、"
                "実装を修正してください。\n"
                "- `view_file` で対象ファイルの該当行を確認し、分岐条件を精査すること。"
            )

        if "typeerror" in combined:
            return (
                "- **型エラー**: 引数の型が不正、またはNone参照の可能性があります。\n"
                "- 引数のバリデーション（None チェック、型チェック）を追加してください。\n"
                "- Optional型のパラメータに `if x is None` ガードを設置すること。"
            )

        if "keyerror" in combined:
            return (
                "- **キーエラー**: 辞書に存在しないキーへのアクセスがあります。\n"
                "- `.get(key, default)` を使用するか、事前にキーの存在を確認してください。"
            )

        if "attributeerror" in combined:
            return (
                "- **属性エラー**: オブジェクトに存在しない属性へのアクセスがあります。\n"
                "- Noneチェック（`if obj is not None`）や、"
                "型ヒントの確認を行ってください。"
            )

        if "timeout" in combined or "timed out" in combined:
            return (
                "- **タイムアウト**: テストが規定時間内に完了しませんでした。\n"
                "- 無限ループやデッドロックの可能性を確認してください。\n"
                "- `subprocess.Popen` のモック設定（`poll()` の戻り値）を確認すること。\n"
                "- GEMINI.md の「subprocess.Popen モック安全規約」を遵守すること。"
            )

        if "filenotfounderror" in combined:
            return (
                "- **ファイル未検出**: 存在しないファイルパスを参照しています。\n"
                "- テスト内で `tmp_path` を使用し、一時ファイルを適切に作成すること。\n"
                "- パスのハードコーディングを避け、相対パスやfixture経由で取得すること。"
            )

        if "valueerror" in combined:
            return (
                "- **値エラー**: 引数の値が範囲外、または不正なフォーマットです。\n"
                "- 入力値のバリデーションを追加し、エッジケース（空文字、0、負数）を考慮すること。"
            )

        # デフォルト
        return (
            "- エラーメッセージとトレースバックを精読し、根本原因を特定してください。\n"
            "- 前回と同じアプローチでの修正は避け、別の解決策を検討すること。"
        )
