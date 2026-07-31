"""Quality Feedback Trigger — NHKスコアラ結果に基づくbug_hunterタスク自動生成。

パイプライン完了後に自動実行され、品質スコアが閾値以下の軸があれば
自動的にbug_hunterタスクをOrchestrationHub経由でキューに投入する。
"""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path
import json
import logging
import math
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TASK_QUEUE_PATH = _writable_path("backend/agents/orchestration/task_queue.json")
QUALITY_SCORE_HISTORY_PATH = _PROJECT_ROOT / "backend" / "quality_score_history.jsonl"



def _safe_float(val: Any, default: float) -> float:
    if val is None:
        return default
    try:
        f_val = float(val)
        if math.isnan(f_val) or math.isinf(f_val):
            logger.warning("スコアが NaN または Infinity です: %r", val)
            return default
        return f_val
    except (ValueError, TypeError, OverflowError):
        is_na = isinstance(val, str) and val == "N/A"
        if not is_na:
            logger.warning("スコアの数値変換に失敗しました: %r (%s)", val, type(val).__name__)
        return default


class QualityFeedbackTrigger:
    """NHKスコアレポートに基づき、閾値以下の軸に対して
    bug_hunterタスクを自動生成する。"""

    def __init__(self, threshold: float = 60.0):
        self.threshold = threshold

    def evaluate_and_trigger(self, score_report: dict) -> dict:
        """スコアレポートを評価し、必要ならbug_hunterタスクを生成。
        
        Args:
            score_report: NHKScoreReport.to_dict() の出力
        
        Returns:
            {
                "triggered": bool,
                "low_axes": [...],
                "tasks_created": int,
                "details": str
            }
        """
        try:
            if not isinstance(score_report, dict):
                logger.error("無効なスコアレポートが渡されました: %r", score_report)
                return {
                    "triggered": False,
                    "low_axes": [],
                    "tasks_created": 0,
                    "details": "無効なスコアレポート形式のため処理をスキップしました。"
                }
            axes = score_report.get("axes", [])
            if not isinstance(axes, list):
                logger.error("axesがリストではありません: %r", axes)
                return {
                    "triggered": False,
                    "low_axes": [],
                    "tasks_created": 0,
                    "details": "axesがリスト形式ではないため処理をスキップしました。"
                }
            low_axes = []
            for axis in axes:
                if not isinstance(axis, dict):
                    logger.warning("無効なaxis要素をスキップしました: %r", axis)
                    continue
                name_val = axis.get("name")
                if not name_val or not isinstance(name_val, str):
                    logger.warning("無効または非文字列の軸名をスキップしました: %r", name_val)
                    continue
                if axis.get("grade") == "N/A":
                    continue
                score_val = _safe_float(axis.get("score"), 100.0)
                thresh_val = _safe_float(axis.get("threshold"), self.threshold)
                if score_val < thresh_val:
                    low_axes.append(axis)
            
            if not low_axes:
                self._record_score(score_report, triggered=False)
                return {
                    "triggered": False,
                    "low_axes": [],
                    "tasks_created": 0,
                    "details": "全軸閾値以上。タスク生成なし。"
                }
            
            # bug_hunterタスクを生成
            tasks = []
            for axis in low_axes:
                score_val = _safe_float(axis.get("score"), 0.0)
                max_score_val = _safe_float(axis.get("max_score"), 100.0)
                task = {
                    "group": "bug_hunter",
                    "level": "L2",
                    "instruction": (
                        f"【品質フィードバック】{axis['name']} "
                        f"スコア {score_val:.1f}/{max_score_val:.1f}。"
                        f"\n改善提案: {axis.get('suggestion') or 'N/A'}"
                        f"\n\n【作業指示】上記の品質問題を調査し、原因を特定して修正せよ。"
                        "テスト追加必須。変更は3ファイル以内。"
                    ),
                    "target_module": self._axis_to_module(axis["name"]),
                    "status": "pending",
                    "source": "quality_feedback_trigger",
                    "axis_name": axis["name"],
                    "axis_score": score_val,
                }
                tasks.append(task)
            
            # タスクキューに注入
            injected = self._inject_tasks(tasks)
            self._record_score(score_report, triggered=True, tasks_count=len(tasks))
            
            return {
                "triggered": True,
                "low_axes": [a["name"] for a in low_axes],
                "tasks_created": injected,
                "details": f"{len(low_axes)}軸が閾値以下。{injected}件のbug_hunterタスクを生成。"
            }
        except Exception as e:
            report_meta = {}
            if isinstance(score_report, dict):
                try:
                    report_meta = {
                        "overall_score": score_report.get("overall_score"),
                        "overall_grade": score_report.get("overall_grade"),
                        "axes_count": len(score_report.get("axes", [])) if isinstance(score_report.get("axes"), list) else 0
                    }
                except Exception:
                    report_meta = {"meta_error": "Failed to extract score_report meta fields"}
            logger.error(
                "スコアレポート評価中にエラーが発生しました (%s): %s, コンテキスト: %r",
                type(e).__name__,
                str(e),
                report_meta,
                exc_info=True
            )
            return {
                "triggered": False,
                "low_axes": [],
                "tasks_created": 0,
                "details": f"評価中にエラーが発生しました: {str(e)}"
            }
 
    def _inject_tasks(self, tasks: List[dict]) -> int:
        """タスクキューにタスクを注入する"""
        if not isinstance(tasks, list):
            logger.error("注入するタスクがリストではありません: %r", tasks)
            raise TypeError("tasks must be a list")

        # タスクオブジェクトの事前生成（IDや作成日時はリトライ毎に変更されないようループ外で設定）
        # また、引数ミューテーションを防ぐためにコピーを注入する
        tasks_to_inject = []
        batch_id = "quality_fix"
        for task in tasks:
            if not isinstance(task, dict):
                raise TypeError("Each task must be a dict")
            t_copy = task.copy()
            t_copy["id_placeholder"] = True
            t_copy["created_at"] = datetime.now(timezone.utc).isoformat()
            t_copy["assigned_agent"] = None
            t_copy["result"] = None
            tasks_to_inject.append(t_copy)

        max_retries = 5
        retry_delay = 0.1
        
        for attempt in range(max_retries):
            temp_path = None
            try:
                queue = {}
                try:
                    with open(TASK_QUEUE_PATH, "r", encoding="utf-8") as f:
                        queue = json.load(f)
                except FileNotFoundError:
                    logger.info("タスクキューファイルが存在しないため、新規作成します: %s", TASK_QUEUE_PATH)
                    queue = {}
                except json.JSONDecodeError as jde:
                    # ファイルが存在し、かつサイズが0より大きい場合は、書き込み競合を疑いリトライさせるために例外を投げる
                    if TASK_QUEUE_PATH.exists() and TASK_QUEUE_PATH.stat().st_size > 0:
                        raise jde
                    else:
                        logger.info("タスクキューファイルが空であるため、新規作成します")
                        queue = {}
                
                existing_tasks = queue.get("tasks", [])
                if not isinstance(existing_tasks, list):
                    logger.warning("タスクキュー内のtasksがリストではありません。新規リストとして初期化します。")
                    existing_tasks = []
                
                actual_batch_id = queue.get("current_batch_id", "quality_fix")
                
                # 実際のbatch_idを用いてタスクIDを確定させる
                final_tasks = []
                for t in tasks_to_inject:
                    t_final = t.copy()
                    if t_final.pop("id_placeholder", False):
                        t_final["id"] = f"T-{actual_batch_id}-qf-{uuid.uuid4().hex[:8]}"
                    final_tasks.append(t_final)

                existing_tasks.extend(final_tasks)
                queue["tasks"] = existing_tasks
                
                # 親ディレクトリ作成を保証し、ユニークな一時ファイルへ書き込む
                temp_path = TASK_QUEUE_PATH.with_name(f"{TASK_QUEUE_PATH.name}.{uuid.uuid4().hex}.tmp")
                TASK_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(queue, f, ensure_ascii=False, indent=2)
                
                # アトミックに置換
                os.replace(temp_path, TASK_QUEUE_PATH)
                temp_path = None
                
                logger.info("品質フィードバック: %d件のbug_hunterタスクをキューに注入", len(tasks))
                return len(tasks)

            except (json.JSONDecodeError, PermissionError, OSError) as e:
                # 一時ファイルが存在すればループ内でクリーンアップし、リークを防ぐ
                if temp_path:
                    try:
                        temp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    temp_path = None

                if attempt < max_retries - 1:
                    logger.warning(
                        "タスクキューの操作中に一時的なエラーが発生しました (リトライ %d/%d): %s",
                        attempt + 1, max_retries, str(e)
                    )
                    time.sleep(retry_delay)
                    continue
                else:
                    logger.error("タスクキューの操作がリトライ上限に達しても失敗しました: %s", str(e), exc_info=True)
                    raise e
            finally:
                # 最終的にループを抜ける際（成功時またはリトライ対象外エラー発生時）のクリーンアップ
                if temp_path:
                    try:
                        temp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
        return 0

    def _record_score(self, score_report: dict, triggered: bool,
                     tasks_count: int = 0) -> None:
        """品質スコア履歴を記録"""
        record = None
        try:
            if not isinstance(score_report, dict):
                raise TypeError("score_report must be a dict")
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "overall_score": score_report.get("overall_score", 0),
                "overall_grade": score_report.get("overall_grade", ""),
                "triggered": triggered,
                "tasks_created": tasks_count,
            }
            os.makedirs(QUALITY_SCORE_HISTORY_PATH.parent, exist_ok=True)
            
            # Windows環境等での一時的なI/O競合への対策としてリトライを実施
            max_retries = 3
            retry_delay = 0.05
            for attempt in range(max_retries):
                try:
                    with open(QUALITY_SCORE_HISTORY_PATH, "a", encoding="utf-8") as f:
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")
                    break
                except (OSError, PermissionError) as ioe:
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                    else:
                        raise ioe
        except Exception as e:
            logger.warning(
                "品質スコア履歴の記録に失敗しました (%s): %s, レコード: %r（処理は継続します）",
                type(e).__name__,
                str(e),
                record,
                exc_info=True
            )

    @staticmethod
    def _axis_to_module(axis_name: str) -> Optional[str]:
        """軸名から関連モジュールを推定"""
        if not isinstance(axis_name, str):
            logger.warning("軸名が文字列ではありません: %r", axis_name)
            return None
        mapping = {
            "字幕タイミング精度": "antigravity_pipeline.py",
            "字幕表示時間": "antigravity_pipeline.py",
            "テロップ可読性": "services/gen_telops.py",
            "音量バランス": "services/audio_master.py",
            "カット割りリズム": "services/video_editor_engine.py",
        }
        return mapping.get(axis_name)
