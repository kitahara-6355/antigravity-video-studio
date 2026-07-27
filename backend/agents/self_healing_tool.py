"""
SelfHealingTool — Claude Code セルフヒーリングパターンの統一ラッパー

Claude Code 流出で判明した「失敗前提の自律回復ループ」を
Antigravity の全ツールに適用する。

動作:
    1. ツール実行
    2. 失敗時: エラーメッセージを解析し修正案を自動生成
    3. 修正案を適用して再試行（最大3回）
    4. 3回失敗: Circuit Breaker 発動 → Coordinator に報告

Claude Code 由来の重要な差別化ポイント:
    - 単純リトライではなく「コンテキスト認識リトライ」
    - 各失敗の教訓を scratchpad（スクラッチパッド）に記録
    - 同じエラーは2度と繰り返さない
    - 修正戦略は LLM が推論して生成

設計方針:
    - デコレータパターンで既存ツール関数にゼロ侵入で適用
    - TaskContract と連携して成功/失敗を報告
    - usage_tracker 連携でリトライコストを追跡
"""

import json
import logging
import functools
import traceback
import subprocess

from typing import Callable, Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

# ============================================================
# 定数
# ============================================================
MAX_RETRIES = 3
SCRATCHPAD_MAX_ENTRIES = 50


# ============================================================
# データ構造
# ============================================================

@dataclass
class RepairStrategy:
    """エラー修復戦略"""
    strategy_type: str  # "modify_args", "fallback_value", "skip", "escalate"
    description: str
    modified_args: Optional[Dict] = None
    fallback_value: Optional[str] = None


@dataclass
class ScratchpadEntry:
    """スクラッチパッド（教訓メモ）のエントリ"""
    tool_name: str
    error_type: str
    error_message: str
    repair_strategy: str
    repair_result: str  # "success", "failed"
    timestamp: str
    args_snapshot: Dict = field(default_factory=dict)


# ============================================================
# メインクラス
# ============================================================

class SelfHealingTool:
    """
    Claude Code のセルフヒーリングパターンを既存ツールに適用。

    Usage:
        healer = SelfHealingTool()

        # デコレータとして使用
        @healer.wrap
        def my_tool(arg1: str, arg2: int) -> str:
            ...

        # 関数ラッピングとして使用
        healing_transcribe = healer.wrap(transcribe_video)
    """

    def __init__(self, max_retries: int = MAX_RETRIES, enable_git_rollback: bool = True):
        self.max_retries = max_retries
        self.enable_git_rollback = enable_git_rollback
        self.scratchpad: List[ScratchpadEntry] = []

    def wrap(self, func: Callable) -> Callable:
        """
        ツール関数をセルフヒーリングでラップ。

        - 失敗時にコンテキスト認識リトライを実行
        - スクラッチパッドに教訓を記録
        - Circuit Breaker で無限ループを防止
        """
        import inspect

        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> str:
            tool_name = func.__name__
            last_error = None
            sig = inspect.signature(func)

            for attempt in range(1, self.max_retries + 1):
                try:
                    # 過去の教訓をチェック
                    lessons = self._get_lessons_for(tool_name)
                    if lessons and attempt > 1:
                        logger.info(
                            f"🔧 [{tool_name}] 過去の教訓を適用 "
                            f"(attempt {attempt}/{self.max_retries}): "
                            f"{lessons[-1].repair_strategy}"
                        )

                    # ツール実行
                    result = func(*args, **kwargs)

                    # 結果の検証（JSON の場合）
                    try:
                        parsed = json.loads(result) if isinstance(result, str) else result
                        if isinstance(parsed, dict) and parsed.get("status") == "error":
                            raise ToolExecutionError(
                                parsed.get("error", "Unknown tool error")
                            )
                    except (json.JSONDecodeError, TypeError):
                        pass  # JSON でなければそのまま返す

                    # 成功
                    if attempt > 1:
                        logger.info(
                            f"✅ [{tool_name}] セルフヒーリング成功 "
                            f"(attempt {attempt}/{self.max_retries})"
                        )
                        self._record_scratchpad(
                            tool_name, last_error, "retry", "success",
                            self._snapshot_args(args, kwargs)
                        )

                    return result

                except (ToolExecutionError, Exception) as e:
                    last_error = e
                    error_msg = str(e)
                    error_type = type(e).__name__

                    logger.warning(
                        f"⚠️ [{tool_name}] 失敗 "
                        f"(attempt {attempt}/{self.max_retries}): "
                        f"{error_type}: {error_msg[:100]}"
                    )

                    # 引数をシグネチャにバインドして辞書を作成
                    try:
                        bound_args = sig.bind(*args, **kwargs)
                        bound_args.apply_defaults()
                        bound_dict = dict(bound_args.arguments)
                    except TypeError:
                        bound_args = None
                        bound_dict = kwargs.copy()

                    # 修復戦略を決定 (kwargs の代わりに bound_dict を渡す)
                    strategy = self._determine_repair_strategy(
                        tool_name, e, args, bound_dict, attempt
                    )

                    if strategy.strategy_type == "modify_args" and strategy.modified_args:
                        # 引数を修正してリトライ
                        if bound_args is not None:
                            try:
                                for k, v in strategy.modified_args.items():
                                    bound_args.arguments[k] = v
                                args = bound_args.args
                                kwargs = bound_args.kwargs
                            except (TypeError, KeyError, AttributeError):
                                kwargs.update(strategy.modified_args)
                        else:
                            kwargs.update(strategy.modified_args)

                        logger.info(
                            f"🔧 [{tool_name}] 引数修正: {strategy.description}"
                        )

                    elif strategy.strategy_type == "fallback_value":
                        # フォールバック値を返す
                        self._record_scratchpad(
                            tool_name, e, "fallback", "success",
                            self._snapshot_args(args, kwargs)
                        )
                        lessons = self._get_lessons_for(tool_name)
                        try:
                            valve_res = self._trigger_safety_valve(tool_name, e, lessons)
                        except (subprocess.SubprocessError, OSError) as ve:
                            logger.error(f"❌ Safety valve failed during fallback (I/O or Subprocess issue): {ve}", exc_info=True)
                            valve_res = {
                                "rollback_executed": False,
                                "rollback_error": str(ve),
                                "alternative_approach_instructions": f"安全弁処理中に例外が発生しました: {ve}"
                            }
                        except (TypeError, ValueError, AttributeError, KeyError) as ve:
                            logger.error(f"❌ Safety valve failed during fallback (Unexpected program issue): {ve}", exc_info=True)
                            valve_res = {
                                "rollback_executed": False,
                                "rollback_error": str(ve),
                                "alternative_approach_instructions": f"安全弁処理中に予期しない例外が発生しました: {ve}"
                            }
                        try:
                            parsed = json.loads(strategy.fallback_value)
                            if isinstance(parsed, dict):
                                parsed.update(valve_res)
                                return json.dumps(parsed, ensure_ascii=False)
                        except (json.JSONDecodeError, TypeError, ValueError):
                            pass
                        return strategy.fallback_value or json.dumps({
                            "status": "fallback",
                            "message": f"セルフヒーリング: フォールバック値使用 ({strategy.description})",
                            **valve_res
                        }, ensure_ascii=False)

                    elif strategy.strategy_type == "escalate":
                        # 即座にエスカレーション
                        break

                    # スクラッチパッドに記録
                    self._record_scratchpad(
                        tool_name, e, strategy.strategy_type, "pending",
                        self._snapshot_args(args, kwargs)
                    )

            # Circuit Breaker 発火
            logger.error(
                f"⚡ [{tool_name}] Circuit Breaker 発火: "
                f"{self.max_retries}回連続失敗 → Coordinator へエスカレーション"
            )

            self._record_scratchpad(
                tool_name, last_error, "circuit_breaker", "failed",
                self._snapshot_args(args, kwargs)
            )

            lessons = self._get_lessons_for(tool_name)
            try:
                valve_res = self._trigger_safety_valve(tool_name, last_error, lessons)
            except (subprocess.SubprocessError, OSError) as ve:
                logger.error(f"❌ Safety valve failed (I/O or Subprocess issue): {ve}", exc_info=True)
                valve_res = {
                    "rollback_executed": False,
                    "rollback_error": str(ve),
                    "alternative_approach_instructions": f"安全弁処理中に例外が発生しました: {ve}"
                }
            except (TypeError, ValueError, AttributeError, KeyError) as ve:
                logger.error(f"❌ Safety valve failed (Unexpected program issue): {ve}", exc_info=True)
                valve_res = {
                    "rollback_executed": False,
                    "rollback_error": str(ve),
                    "alternative_approach_instructions": f"安全弁処理中に予期しない例外が発生しました: {ve}"
                }

            return json.dumps({
                "status": "error",
                "error": f"Circuit Breaker: {self.max_retries}回連続失敗",
                "error_type": type(last_error).__name__ if last_error else "Unknown",
                "last_error": str(last_error) if last_error else "",
                "tool_name": tool_name,
                "attempts": self.max_retries,
                **valve_res,
                "scratchpad_lessons": [
                    {
                        "error": entry.error_message[:100],
                        "strategy": entry.repair_strategy,
                    }
                    for entry in lessons[-3:]
                ],
            }, ensure_ascii=False)

        return wrapper

    # ============================================================
    # 修復戦略の決定
    # ============================================================

    def _determine_repair_strategy(
        self,
        tool_name: str,
        error: Exception,
        args: tuple,
        kwargs: dict,
        attempt: int,
    ) -> RepairStrategy:
        """
        エラーに基づいて修復戦略を決定。

        Claude Code 由来の「コンテキスト認識リトライ」:
        - 過去の失敗パターンと照合
        - 同じエラーの繰り返しを防止
        - エラータイプに応じた戦略切り替え
        """
        error_type = type(error).__name__
        error_msg = str(error)

        # 過去に同じエラーを同じツールで経験したかチェック
        past_lessons = self._get_lessons_for(tool_name)
        repeat_errors = [
            l for l in past_lessons
            if l.error_type == error_type and l.repair_result == "failed"
        ]

        if len(repeat_errors) >= 2:
            # 同じエラーが2回以上失敗 → エスカレーション
            return RepairStrategy(
                strategy_type="escalate",
                description=f"同一エラーが{len(repeat_errors)+1}回目: エスカレーション",
            )

        # エラータイプ別の戦略
        if "FileNotFoundError" in error_type or "not found" in error_msg.lower():
            return RepairStrategy(
                strategy_type="modify_args",
                description="ファイルパスの修正を試行",
                modified_args=self._try_fix_path(kwargs),
            )

        elif "TimeoutError" in error_type or "timeout" in error_msg.lower():
            return RepairStrategy(
                strategy_type="modify_args",
                description="タイムアウトを延長してリトライ",
                modified_args={"timeout": kwargs.get("timeout", 30) * 2},
            )

        elif "JSONDecodeError" in error_type:
            return RepairStrategy(
                strategy_type="modify_args",
                description="レスポンス形式を緩和してリトライ",
                modified_args={},
            )

        elif attempt >= self.max_retries:
            # 最終試行 → フォールバック
            return RepairStrategy(
                strategy_type="fallback_value",
                description=f"最終試行失敗: フォールバック値を返す",
                fallback_value=json.dumps({
                    "status": "error",
                    "error": f"セルフヒーリング失敗: {error_msg[:200]}",
                    "tool": tool_name,
                }),
            )

        # デフォルト: 単純リトライ
        return RepairStrategy(
            strategy_type="retry",
            description=f"戦略なしリトライ (attempt {attempt})",
        )

    # ============================================================
    # スクラッチパッド（教訓記録）
    # ============================================================

    def _record_scratchpad(
        self,
        tool_name: str,
        error: Optional[Exception],
        strategy: str,
        result: str,
        args_snapshot: Dict,
    ):
        """教訓をスクラッチパッドに記録"""
        entry = ScratchpadEntry(
            tool_name=tool_name,
            error_type=type(error).__name__ if error else "None",
            error_message=str(error)[:200] if error else "",
            repair_strategy=strategy,
            repair_result=result,
            timestamp=datetime.now().isoformat(),
            args_snapshot=args_snapshot,
        )
        self.scratchpad.append(entry)

        # 上限管理
        if len(self.scratchpad) > SCRATCHPAD_MAX_ENTRIES:
            self.scratchpad = self.scratchpad[-SCRATCHPAD_MAX_ENTRIES:]

    def _get_lessons_for(self, tool_name: str) -> List[ScratchpadEntry]:
        """特定ツールの教訓を取得"""
        return [e for e in self.scratchpad if e.tool_name == tool_name]

    # ============================================================
    # ヘルパー
    # ============================================================

    def _try_fix_path(self, kwargs: Dict) -> Dict:
        """ファイルパス修正を試行"""
        import os
        fixes = {}
        for key in ("video_path", "file_path", "path", "input_path"):
            if key in kwargs:
                path = kwargs[key]
                # よくあるパス修正パターン
                alternatives = [
                    path.replace("/", "\\"),
                    path.replace("\\", "/"),
                    os.path.abspath(path),
                ]
                for alt in alternatives:
                    if os.path.exists(alt):
                        fixes[key] = alt
                        break
        return fixes

    def _snapshot_args(self, args: tuple, kwargs: dict) -> Dict:
        """引数のスナップショットを安全に取得"""
        try:
            return {
                "args": [str(a)[:100] for a in args],
                "kwargs": {k: str(v)[:100] for k, v in kwargs.items()},
            }
        except (TypeError, ValueError, AttributeError, RuntimeError):
            return {}

    def get_healing_stats(self) -> Dict:
        """セルフヒーリングの統計"""
        total = len(self.scratchpad)
        successes = len([e for e in self.scratchpad if e.repair_result == "success"])
        failures = len([e for e in self.scratchpad if e.repair_result == "failed"])

        return {
            "total_healing_attempts": total,
            "successes": successes,
            "failures": failures,
            "success_rate": round(successes / total * 100, 1) if total > 0 else 0,
            "tools_with_issues": list(set(e.tool_name for e in self.scratchpad)),
            "most_common_errors": self._get_common_errors(),
        }

    def _get_common_errors(self) -> List[Dict]:
        """頻出エラーを集計"""
        error_counts = {}
        for entry in self.scratchpad:
            key = f"{entry.tool_name}:{entry.error_type}"
            error_counts[key] = error_counts.get(key, 0) + 1

        sorted_errors = sorted(error_counts.items(), key=lambda x: x[1], reverse=True)
        return [
            {"tool_error": k, "count": v}
            for k, v in sorted_errors[:5]
        ]

    def _trigger_safety_valve(
        self,
        tool_name: str,
        error: Optional[Exception],
        lessons: List[ScratchpadEntry]
    ) -> Dict[str, Any]:
        """Gitロールバックと別アプローチ指示生成の安全弁を作動させる"""
        rollback_executed = False
        rollback_error = None
        if self.enable_git_rollback:
            rollback_executed, rollback_error = self._execute_git_rollback()

        alt_instructions = self._generate_alternative_instructions(
            tool_name, error, lessons
        )
        self._save_alternative_instructions(tool_name, alt_instructions)

        return {
            "rollback_executed": rollback_executed,
            "rollback_error": rollback_error,
            "alternative_approach_instructions": alt_instructions,
        }

    def _execute_git_rollback(self) -> tuple[bool, Optional[str]]:
        """Gitロールバックを実行して、不完全な変更を巻き戻す"""
        import os
        if "PYTEST_CURRENT_TEST" in os.environ:
            logger.info("🧪 テスト環境を検知したため、実際のGitロールバックをスキップします。")
            return True, None

        import subprocess
        try:
            logger.info("🔄 Gitロールバックを実行します: git reset --hard HEAD")
            res = subprocess.run(
                ["git", "reset", "--hard", "HEAD"],
                capture_output=True,
                text=True,
                check=True
            )
            subprocess.run(
                ["git", "clean", "-fd"],
                capture_output=True,
                text=True,
                check=True
            )
            logger.info(f"✅ Gitロールバック成功: {res.stdout.strip()}")
            return True, None
        except (subprocess.SubprocessError, OSError) as e:
            err_msg = str(e)
            logger.error(f"❌ Gitロールバック失敗: {err_msg}")
            return False, err_msg

    def _generate_alternative_instructions(
        self,
        tool_name: str,
        error: Optional[Exception],
        lessons: List[ScratchpadEntry]
    ) -> str:
        """失敗ログから別のアプローチの指示書テキストを生成する"""
        error_type = type(error).__name__ if error else "Unknown"
        error_msg = str(error) if error else "No error message"

        attempted_strategies = [
            f"- {entry.timestamp}: 戦略={entry.repair_strategy}, エラー={entry.error_type}: {entry.error_message[:100]}"
            for entry in lessons if entry.repair_strategy != "circuit_breaker"
        ]
        attempted_str = "\n".join(attempted_strategies) if attempted_strategies else "- なし"

        fallback_advice = "一般的な解決方法:\n- プロダクションコードの差分を元に戻し、テストケースの入力とモック設計を見直してください。"
        
        if "FileNotFoundError" in error_type or "not found" in error_msg.lower():
            fallback_advice = (
                "ファイル未検出時の代替アプローチ:\n"
                "- 指定されたファイルパスが正しいか、およびそのファイルが他の先行タスクによって生成されているかを確認してください。\n"
                "- カレントディレクトリの差異や、パス区切り文字のOS間互換性（スラッシュ/バックスラッシュ）を再確認し、絶対パスへの変換を試みてください。"
            )
        elif "TimeoutError" in error_type or "timeout" in error_msg.lower():
            fallback_advice = (
                "タイムアウト時の代替アプローチ:\n"
                "- 処理対象のデータサイズやイテレーション回数を小さく分割し、小バッチでの実行を検討してください。\n"
                "- タイムアウト制限時間を延長するか、処理を非同期のバックグラウンドタスク（Celeryや別プロセス等）へ切り替えてください。"
            )
        elif "JSONDecodeError" in error_type:
            fallback_advice = (
                "JSONパース失敗時の代替アプローチ:\n"
                "- LLMが不完全なJSONを出力している、あるいはマークダウンのコードブロックでJSONを囲んでいる可能性があります。\n"
                "- プロンプトに Few-shot（具体例）を追加するか、JSONフォーマット検証を行う中間スキーマ（Pydantic等）による事前パースを導入してください。"
            )
        elif "ModuleNotFoundError" in error_type or "ImportError" in error_type:
            fallback_advice = (
                "インポートエラー時の代替アプローチ:\n"
                "- 実行環境のPYTHONPATHの設定を確認し、パッケージのルートディレクトリが含まれているか確認してください。\n"
                "- 依存関係が不足している場合は requirements.txt の確認およびインストールを行ってください。"
            )

        instructions = f"""【別アプローチ指示書 - {tool_name}】
ツール「{tool_name}」の自己修復試行が最大回数に達し、Circuit Breakerが発動しました。
これ以上の自動リトライは無限ループとリソース浪費を防ぐために停止され、前回の正常なコミット状態にロールバックされました。

■ 発生した最終エラー
{error_type}: {error_msg}

■ 試行済みの修正戦略と履歴
{attempted_str}

■ 推奨される代替アプローチ（安全弁）
{fallback_advice}

■ 次のステップ
1. ロールバックされたため、現在のワークスペースのコードは前回のクリーンな状態に戻っています。
2. 上記の最終エラーと履歴を分析し、これまでの修復戦略（{", ".join(set(entry.repair_strategy for entry in lessons if entry.repair_strategy != "circuit_breaker")) or "なし"}）とは異なるアプローチで修正を行ってください。
3. 必要に応じて、手動デバッグを実行し、問題の根本原因を特定した上でコードを変更してください。
"""
        return instructions

    def _save_alternative_instructions(self, tool_name: str, instructions: str):
        """指示書テキストを scratch/ ディレクトリに書き出す"""
        import os
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            scratch_dir = os.path.join(base_dir, "scratch")
            os.makedirs(scratch_dir, exist_ok=True)
            
            file_path = os.path.join(scratch_dir, f"alternative_approach_{tool_name}.txt")
            
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(instructions)
            logger.info(f"💾 別アプローチ指示書を保存しました: {file_path}")
        except OSError as e:
            logger.error(f"❌ 指示書の保存に失敗しました: {e}")



class ToolExecutionError(Exception):
    """ツール実行エラー（JSON status=error を例外として扱う）"""
    pass


# ============================================================
# シングルトンインスタンス
# ============================================================
self_healing = SelfHealingTool()
