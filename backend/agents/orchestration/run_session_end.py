
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import official_artifact_dir as _official_artifact_dir
except ImportError:
    from path_resolver import official_artifact_dir as _official_artifact_dir
import sys
import os
import traceback
import json
from datetime import datetime, timezone
from typing import TypedDict, Optional, Dict, Any
from dataclasses import dataclass

_current_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.dirname(os.path.dirname(_current_dir))
_repo_root = os.path.dirname(_backend_dir)
if _backend_dir not in sys.path:
    sys.path.append(_backend_dir)
if _repo_root not in sys.path:
    sys.path.append(_repo_root)

from backend.agents.orchestration import OrchestrationHub

class HubCommunicationError(Exception):
    """OrchestrationHubとの通信エラー"""
    pass
class ReportWriteError(Exception):
    """完了レポートの書き込みエラー"""
    pass

class SessionEndReportData(TypedDict):
    opus_conversation_id: Optional[str]
    conversation_id: Optional[str]
    tasks_completed_in_session: int
    batches_in_session: int
    current_batch_id: str
    context_consumption_pct: int
    ended_at: str
    exit_reason: str

class ErrorContext(TypedDict):
    step: str
    phase: int
    milestone: str
    timestamp: str
    extra_info: Optional[Dict[str, Any]]
class ErrorResolution(TypedDict):
    action: str  # "retry", "fallback", "fail", "ignore"
    custom_exception: Optional[Exception]
    message: str

def _get_exception_line(tb, default_line: int) -> int:
    """例外のトレースバックから、このファイル内での発生行番号を抽出する"""
    if not tb:
        return default_line
    import traceback
    tb_list = traceback.extract_tb(tb)
    this_file = os.path.basename(__file__)
    for fs in reversed(tb_list):
        if os.path.basename(fs.filename) == this_file:
            return fs.lineno
    return default_line

class SessionEndErrorHandler:
    """セッション終了処理における例外の分類、ロギング、および技術負債登録を行うクラス"""
    def handle_exception(self, exception: Exception, context: ErrorContext) -> ErrorResolution:
        """例外を分類し、推奨する解決アクションを決定するメソッド"""
        if isinstance(exception, (HubCommunicationError, ReportWriteError)):
            return {
                "action": "fail",
                "custom_exception": exception,
                "message": f"セッション終了処理の致命的エラー: {exception}"
            }
        elif isinstance(exception, (TypeError, ValueError, KeyError, AttributeError, json.JSONDecodeError)):
            return {
                "action": "fallback",
                "custom_exception": exception,
                "message": f"想定されるデータ構造エラー: {exception}"
            }
        elif isinstance(exception, OSError):
            return {
                "action": "fallback",
                "custom_exception": exception,
                "message": f"I/Oエラーが発生しました: {exception}"
            }
        else:
            return {
                "action": "fail",
                "custom_exception": exception,
                "message": f"予期せぬ例外が発生しました: {exception}"
            }

    def log_error(self, exception: Exception, context: ErrorContext) -> None:
        """詳細なエラーログとスタックトレースを出力するメソッド"""
        step = context.get("step", "unknown_step")
        phase = context.get("phase", 33)
        milestone = context.get("milestone", "unknown_milestone")
        
        # 以前の標準エラー出力形式との互換性を保つためのメッセージを出力
        if step == "get_phase_state":
            print(f"Warning: Unexpected error during phase state retrieval: {exception} ({type(exception).__name__})", file=sys.stderr)
        elif step == "flash_session_end":
            print(f"Warning: Failed to mark flash session end in OrchestrationHub: {exception} ({type(exception).__name__})", file=sys.stderr)
        elif step == "get_session_info":
            print(f"Error retrieving flash session info: {exception} ({type(exception).__name__})", file=sys.stderr)
        elif step == "save_report":
            print(f"Error saving session complete report to file: {exception} ({type(exception).__name__})", file=sys.stderr)
        elif step == "fallback_report":
            print(f"Failed to generate fallback report content: {exception} ({type(exception).__name__})", file=sys.stderr)

        print(f"[{datetime_now_str()}] Error occurred during session end at step '{step}' (Phase {phase}/{milestone}): {exception} ({type(exception).__name__})", file=sys.stderr)
        traceback.print_exception(exception, file=sys.stderr)

    def register_debt_if_needed(self, exception: Exception, context: ErrorContext) -> None:
        """予期せぬ例外の場合に技術負債台帳に登録するメソッド"""
        # テスト実行中は技術負債の登録をスキップする（台帳の意図しない汚染を防止）
        # ただし、テスト自体で動作検証を行いたい場合は環境変数で強制的に有効化できる
        import os
        import sys
        if "pytest" in sys.modules and not os.environ.get("FORCE_DEBT_REGISTRATION"):
            return

        expected_exceptions = (
            HubCommunicationError,
            ReportWriteError,
            TypeError,
            ValueError,
            KeyError,
            AttributeError,
            OSError,
            json.JSONDecodeError,
            SystemExit
        )
        if not isinstance(exception, expected_exceptions):
            try:
                from backend.agents.memory.technical_debt import TechnicalDebtStore
                store = TechnicalDebtStore()
                step = context.get("step", "unknown_step")
                
                # 例外の発生行番号をトレースバックから動的に抽出する
                line_no = _get_exception_line(exception.__traceback__, 289)
                
                store.register_debt(
                    category="IMPORTANT_SERVICE",
                    file_path="agents/orchestration/run_session_end.py",
                    line_number=line_no,
                    pattern=f"{type(exception).__name__}: {str(exception)}",
                    cause_pattern="DP-01",
                    fix_pattern="例外の原因を特定し、型チェックまたは条件ガードを追加する",
                    registered_by="bug_hunter_P33",
                    notes=f"セッション終了処理のステップ '{step}' にて予期せぬ例外が発生しました。詳細は context: {context} を参照。"
                )
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as debt_e:
                print(f"Warning: Failed to register technical debt: {debt_e}", file=sys.stderr)


def validate_report_data(data: dict) -> SessionEndReportData:
    """セッションデータを検証し、SessionEndReportData型に整形する関数

    引数:
        data (dict): 検証対象のセッションデータ辞書

    例外:
        TypeError: データ型が不正な場合
        ValueError: 必要なキーが不足している、または値が不正な場合
    """
    if not isinstance(data, dict):
        raise TypeError(f"入力データは dict である必要があります。取得した型: {type(data).__name__}")

    validated: dict = {}

    # Optional[str] fields
    for field in ["opus_conversation_id", "conversation_id"]:
        val = data.get(field)
        if val is not None and not isinstance(val, str):
            raise TypeError(f"フィールド '{field}' は str または None である必要があります。取得した型: {type(val).__name__}")
        validated[field] = val

    # int fields
    for field in ["tasks_completed_in_session", "batches_in_session", "context_consumption_pct"]:
        if field not in data:
            raise ValueError(f"必須フィールド '{field}' が不足しています。")
        val = data.get(field)
        if not isinstance(val, int) or isinstance(val, bool):
            raise TypeError(f"フィールド '{field}' は int である必要があります。取得した型: {type(val).__name__}")
        if field in ["tasks_completed_in_session", "batches_in_session"] and val < 0:
            raise ValueError(f"フィールド '{field}' は 0 以上である必要があります。取得した値: {val}")
        if field == "context_consumption_pct" and (val < 0 or val > 100):
            raise ValueError(f"フィールド 'context_consumption_pct' は 0 以上 100 以下である必要があります。取得した値: {val}")
        validated[field] = val

    # str fields
    for field in ["current_batch_id", "ended_at", "exit_reason"]:
        if field not in data:
            raise ValueError(f"必須フィールド '{field}' が不足しています。")
        val = data.get(field)
        if not isinstance(val, str):
            raise TypeError(f"フィールド '{field}' は str である必要があります。取得した型: {type(val).__name__}")
        validated[field] = val

    return validated # type: ignore

class FlashSessionInfo(TypedDict):
    opus_conversation_id: Optional[str]
    conversation_id: Optional[str]
    tasks_completed_in_session: int
    batches_in_session: int
    current_batch_id: str
    context_consumption_pct: int

@dataclass
class SessionEndConfig:
    reason: str = ""
    inbox_dir: str = str(_official_artifact_dir() / "受信トレイ")

class SessionEndManager:
    def verify_session_state(self, session_info: dict) -> None:
        """セッション情報が有効な状態であるかを事前に検証するメソッド

        引数:
            session_info (dict): 検証対象のセッション情報

        例外:
            TypeError: セッション情報が辞書でない場合、または値の型が不正な場合
            ValueError: セッション情報が空であるか、必須キーが不足している、または値が不正な場合
        """
        if session_info is None:
            raise ValueError("セッション情報が None です。")
        if not isinstance(session_info, dict):
            raise TypeError(f"セッション情報は dict である必要があります。取得した型: {type(session_info).__name__}")
        if not session_info:
            raise ValueError("セッション情報が空です。")

        # 必須のキーチェックと型検証
        for field in ["tasks_completed_in_session", "batches_in_session", "context_consumption_pct"]:
            if field in session_info:
                val = session_info[field]
                if val is None or not isinstance(val, int) or isinstance(val, bool):
                    raise TypeError(f"フィールド '{field}' は int である必要があります。取得した型: {type(val).__name__}")
                if val is not None and field in ["tasks_completed_in_session", "batches_in_session"] and val < 0:
                    raise ValueError(f"フィールド '{field}' は 0 以上である必要があります。取得した値: {val}")
                if val is not None and field == "context_consumption_pct" and (val < 0 or val > 100):
                    raise ValueError(f"フィールド 'context_consumption_pct' は 0 以上 100 以下である必要があります。取得した値: {val}")
            else:
                raise ValueError(f"必須フィールド '{field}' が不足しています。")

        if "current_batch_id" in session_info:
            val = session_info["current_batch_id"]
            if val is None or not isinstance(val, str):
                raise TypeError(f"フィールド 'current_batch_id' は str である必要があります。取得した型: {type(val).__name__}")
        else:
            raise ValueError("必須フィールド 'current_batch_id' が不足しています。")

    def handle_session_end_error(self, error: Exception, step: str, extra_info: Optional[dict] = None) -> None:
        """各ステップで発生したエラーをエラーハンドラに委ねるメソッド"""
        if isinstance(error, (NameError, AssertionError, SystemExit, KeyboardInterrupt)):
            raise error

        context: ErrorContext = {
            "step": step,
            "phase": 33,
            "milestone": "M33.1",
            "timestamp": datetime_now_str(),
            "extra_info": extra_info
        }
        self.error_handler.log_error(error, context)
        self.error_handler.register_debt_if_needed(error, context)
        resolution = self.error_handler.handle_exception(error, context)
        if resolution["action"] == "fail":
            raise resolution["custom_exception"] or error

    def __init__(self, hub: Optional[OrchestrationHub] = None, config: Optional[SessionEndConfig] = None) -> None:
        self.hub = hub if hub is not None else OrchestrationHub()
        self.config = config if config is not None else SessionEndConfig()
        self.error_handler = SessionEndErrorHandler()
        if not self.config.reason:
            phase = 33
            milestone = "M33.1"
            try:
                state = self.hub.get_phase_state()
                if not isinstance(state, dict):
                    raise TypeError("get_phase_state returned a non-dict object")
                phase = state.get("current_phase", 33)
                if not isinstance(phase, (int, str)) or isinstance(phase, bool):
                    raise TypeError("current_phase must be an int or str")
                milestone = state.get("current_milestone", f"M{phase}.1")
                if not isinstance(milestone, str) or isinstance(milestone, bool):
                    raise TypeError("current_milestone must be a str")
            except (NameError, AssertionError):
                raise
            except Exception as e:
                context: ErrorContext = {
                    "step": "get_phase_state",
                    "phase": phase,
                    "milestone": milestone,
                    "timestamp": datetime_now_str(),
                    "extra_info": None
                }
                self.error_handler.log_error(e, context)
                self.error_handler.register_debt_if_needed(e, context)
                phase = 33
                milestone = "M33.1"
            self.config.reason = f"セッション寿命（アーカイブ推奨閾値）到達による終了: P{phase}/{milestone}" 

    def get_session_info(self) -> dict:
        session = self.hub.get_flash_session()
        if session is None:
            raise ValueError("Failed to retrieve flash session (session is None).")
            
        if not isinstance(session, dict):
            raise TypeError(f"Invalid flash session format (expected dict, got {type(session).__name__}).")
            
        if not session:
            raise ValueError("Failed to retrieve flash session (session is empty).")
            
        return session

    def generate_report(self, session_info: SessionEndReportData, timestamp: Optional[str] = None) -> str:
        ts = timestamp if timestamp is not None else datetime_now_str()
        report_content = f"""# 🏁 Flashセッション完了レポート (寿命到達)

- **セッション終了日時**: {ts}
- **終了理由**: {self.config.reason}
- **現在Phase**: Phase 33 / M33.1
- **セッション内完了タスク数**: {session_info.get('tasks_completed_in_session', 0)} 件
- **セッション内バッチ数**: {session_info.get('batches_in_session', 0)} バッチ
- **最終バッチID**: {session_info.get('current_batch_id', 'N/A')}
- **最終コンテキスト消費率**: ~{session_info.get('context_consumption_pct', 0)}%

📦 本セッション is アーカイブ可能です。
   Opusセッション側で新規Flashセッションの開設判断を行ってください。
"""
        return report_content

    def save_report(self, report_content: str, timestamp: Optional[str] = None) -> str:
        ts = timestamp if timestamp is not None else datetime_now_str()
        inbox_dir = self.config.inbox_dir
        if not os.path.isabs(inbox_dir):
            inbox_path = os.path.abspath(os.path.join(_repo_root, inbox_dir))
        else:
            inbox_path = os.path.abspath(inbox_dir)
        os.makedirs(inbox_path, exist_ok=True)
        report_path = os.path.join(inbox_path, f"session_complete_report_{ts}.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)
        return report_path

    def execute(self) -> None:
        # 1. セッション終了マーク
        hub_error = None
        try:
            self.hub.flash_session_end(self.config.reason)
        except (NameError, AssertionError):
            raise
        except Exception as e:
            hub_error = e
            try:
                self.handle_session_end_error(e, "flash_session_end", {"reason": self.config.reason})
            except (NameError, AssertionError):
                raise
            except Exception as handler_e:
                hub_error = handler_e

        # 2. session情報を取得と検証
        session_info = None
        validated_report_data = None
        timestamp = datetime_now_str()
        try:
            session_info = self.get_session_info()
            # 事前検証の実行
            self.verify_session_state(session_info)
            
            # レポート用に整形・検証
            report_data_dict = dict(session_info)
            report_data_dict["exit_reason"] = self.config.reason
            report_data_dict["ended_at"] = timestamp
            validated_report_data = validate_report_data(report_data_dict)
            
            opus_id = validated_report_data.get("opus_conversation_id") or validated_report_data.get("conversation_id")
            print(f"OPUS_CONV_ID:{opus_id}")
        except (NameError, AssertionError):
            raise
        except Exception as e:
            try:
                self.handle_session_end_error(e, "get_session_info")
            except (NameError, AssertionError):
                raise
            except Exception as handler_e:
                if hub_error is not None:
                    handler_e.__context__ = None
                    raise handler_e from hub_error
                raise handler_e
            # もし handle_session_end_error が例外を再送出しなかった場合でも、
            # get_session_info 失敗時はこれ以上進めないため、強制的に再送出する
            if hub_error is not None:
                e.__context__ = None
                raise e from hub_error
            raise e

        # 3. 完了レポートを生成して保存
        try:
            # 検証済みの validated_report_data を使用
            report_content = self.generate_report(validated_report_data, timestamp=timestamp)
            report_path = self.save_report(report_content, timestamp=timestamp)
            print(f"Report saved to: {report_path}")
        except (NameError, AssertionError):
            raise
        except Exception as e:
            # ログ記録と負債登録を handle_session_end_error 経由で実行（例外は一旦投げさせない）
            context: ErrorContext = {
                "step": "save_report",
                "phase": 33,
                "milestone": "M33.1",
                "timestamp": timestamp,
                "extra_info": None
            }
            self.error_handler.log_error(e, context)
            self.error_handler.register_debt_if_needed(e, context)
            
            # フォールバックとして標準エラー出力にレポート内容を出力
            print("--- FALLBACK SESSION COMPLETE REPORT START ---", file=sys.stderr)
            try:
                print(self.generate_report(validated_report_data, timestamp=timestamp), file=sys.stderr)
            except (NameError, AssertionError):
                raise
            except Exception as report_err:
                report_context: ErrorContext = {
                    "step": "fallback_report",
                    "phase": 33,
                    "milestone": "M33.1",
                    "timestamp": timestamp,
                    "extra_info": None
                }
                self.error_handler.log_error(report_err, report_context)
                self.error_handler.register_debt_if_needed(report_err, report_context)
            print("--- FALLBACK SESSION COMPLETE REPORT END ---", file=sys.stderr)
            if hub_error is not None:
                e.__context__ = None
                raise e from hub_error
            raise e

        if hub_error is not None:
            hub_error.__context__ = None
            raise hub_error

def datetime_now_str() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_UTC')

def main():
    try:
        manager = SessionEndManager()
        manager.execute()
    except Exception as e:
        handler = SessionEndErrorHandler()
        context: ErrorContext = {
            "step": "main_execution",
            "phase": 33,
            "milestone": "M33.1",
            "timestamp": datetime_now_str(),
            "extra_info": None
        }
        handler.log_error(e, context)
        handler.register_debt_if_needed(e, context)
        
        if isinstance(e, (TypeError, ValueError)):
            print(f"Error: {e}", file=sys.stderr)
        elif isinstance(e, OSError):
            print(f"I/O Error occurred during session end: {e}", file=sys.stderr)
        elif isinstance(e, (KeyError, AttributeError, NameError, RuntimeError)):
            print(f"Error occurred during session end: {e}", file=sys.stderr)
        else:
            print(f"Unexpected error occurred during session end: {e} ({type(e).__name__})", file=sys.stderr)
            
        sys.exit(1)

if __name__ == "__main__":
    main()
