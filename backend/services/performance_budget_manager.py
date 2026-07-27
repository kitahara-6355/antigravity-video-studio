"""
PerformanceBudgetManager — Worker実行時間の予算管理と計測

PB-01: Worker実行時間の自動記録
PB-02: 合計実行時間バジェット監視
PB-03: 予算超過時のgraceful degradation
PB-04: パフォーマンスレポート生成
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import math
import tempfile

logger = logging.getLogger(__name__)


@dataclass
class WorkerPerformance:
    """個別Workerのパフォーマンス記録"""
    worker_name: str
    duration_seconds: float
    budget_seconds: float
    over_budget: bool


@dataclass
class PerformanceBudgetReport:
    """セッション全体のパフォーマンスレポート"""
    session_id: str
    total_duration: float
    total_budget: float
    over_budget: bool
    workers: List[WorkerPerformance] = field(default_factory=list)
    degradation_applied: List[str] = field(default_factory=list)
    timestamp: str = ""


# デフォルトのWorker別バジェット（秒）
DEFAULT_WORKER_BUDGETS: Dict[str, dict] = {
    "文字起こし": {"budget_seconds": 120, "priority": "critical"},
    "AI校閲": {"budget_seconds": 60, "priority": "critical"},
    "SmartCut構成": {"budget_seconds": 30, "priority": "critical"},
    "プレビュー生成": {"budget_seconds": 90, "priority": "degradable"},
    "YouTube最適化": {"budget_seconds": 60, "priority": "degradable"},
    "品質チェック": {"budget_seconds": 30, "priority": "critical"},
    "最終レンダリング": {"budget_seconds": 180, "priority": "critical"},
}

DEFAULT_TOTAL_BUDGET = 570  # 5分動画での基準バジェット
REFERENCE_DURATION_MIN = 5  # バジェット基準のでの動画尺 (分)

# degradation優先順序（先にdegradeされるものが先頭）
# degradation対象: degradable Workerのみ (§8.2: 品質ゲートはcritical=スキップ不可)
DEFAULT_DEGRADATION_RULES = [
    {"worker": "YouTube最適化", "action": "cache_first", "savings_percent": 40},
    {"worker": "プレビュー生成", "action": "lower_resolution", "savings_percent": 30},
]


class PerformanceBudgetManager:
    """Worker実行時間の予算管理と計測

    使用方法:
        mgr = PerformanceBudgetManager()
        mgr.record_worker_time("文字起こし", 45.0)
        mgr.record_worker_time("AI校閲", 30.0)
        if not mgr.check_budget("AI校閲"):
            targets = mgr.get_degradation_targets()
        report = mgr.generate_report("session_123")
        mgr.save_report(report)
    """

    BUDGET_THRESHOLD_RATIO = 0.8  # 80%超過でdegradation発動

    def __init__(self, budget_path: Optional[Path | str] = None,
                 output_dir: Optional[Path | str] = None,
                 video_duration_min: Optional[float] = None):
        self._budget_path = Path(budget_path) if budget_path else None
        self._output_dir = Path(output_dir) if output_dir else Path("output/performance")
        self._config = self._load_budgets()
        if not isinstance(self._config, dict):
            self._config = {}

        # worker_budgetsの堅牢なロードと検証
        self._initialize_worker_budgets(self._config.get("worker_budgets"))

        # トータルバジェットと尺によるスケーリング
        self._initialize_total_budget(video_duration_min)

        # degradationルールの初期化
        self._initialize_degradation_rules(self._config.get("degradation_rules"))

        # セッション中のWorker実行時間記録
        self._current_session: Dict[str, float] = {}
        self._degradation_applied: List[str] = []

    def _initialize_worker_budgets(self, config_budgets: Optional[dict]) -> None:
        """Workerごとのバジェット設定をロードして初期化・検証する"""
        if not isinstance(config_budgets, dict):
            config_budgets = DEFAULT_WORKER_BUDGETS

        self._worker_budgets = {}
        for worker_name, budget_config in config_budgets.items():
            worker_name = str(worker_name)
            self._worker_budgets[worker_name] = self._parse_single_worker_budget(worker_name, budget_config)

    def _extract_budget_seconds(self, budget_config: any, default_budget: float) -> float:
        """バジェット設定値から秒数を安全に抽出する"""
        if isinstance(budget_config, dict):
            budget_seconds = budget_config.get("budget_seconds")
        else:
            budget_seconds = budget_config

        try:
            parsed_budget = float(budget_seconds) if budget_seconds is not None else default_budget
            return max(0.0, parsed_budget)
        except (ValueError, TypeError):
            return default_budget

    def _extract_priority(self, budget_config: any, default_priority: str) -> str:
        """バジェット設定値から優先度を安全に抽出する"""
        if isinstance(budget_config, dict):
            priority = budget_config.get("priority")
        else:
            priority = None

        if priority in ("critical", "degradable"):
            return priority
        return default_priority

    def _parse_single_worker_budget(self, worker_name: str, budget_config: any) -> dict:
        """個別Workerのバジェット設定を安全にパースする"""
        default_entry = DEFAULT_WORKER_BUDGETS.get(worker_name, {})
        default_budget = default_entry.get("budget_seconds", 0.0)
        default_priority = default_entry.get("priority", "critical")

        parsed_budget = self._extract_budget_seconds(budget_config, default_budget)
        priority = self._extract_priority(budget_config, default_priority)

        return {
            "budget_seconds": parsed_budget,
            "priority": priority
        }

    def _parse_float_fallback(self, value: any, fallback: float, must_be_positive: bool = False) -> float:
        """非数値や境界値などを考慮して float に変換する。失敗時は fallback を返す。"""
        try:
            val = float(value)
            if must_be_positive and val <= 0:
                return fallback
            return val
        except (ValueError, TypeError):
            return fallback

    def _initialize_total_budget(self, video_duration_min: Optional[float]) -> None:
        """トータルバジェット値および動画尺スケーリングの設定・検証を行う"""
        base_budget = self._parse_float_fallback(
            self._config.get("total_budget_seconds"),
            DEFAULT_TOTAL_BUDGET,
            must_be_positive=True
        )
        ref_duration = self._parse_float_fallback(
            self._config.get("reference_duration_minutes"),
            REFERENCE_DURATION_MIN,
            must_be_positive=True
        )

        is_valid_duration = False
        if video_duration_min is not None:
            try:
                video_duration_min_val = float(video_duration_min)
                if video_duration_min_val > 0:
                    is_valid_duration = True
            except (ValueError, TypeError):
                pass

        if is_valid_duration:
            scale = video_duration_min_val / ref_duration
            self._total_budget = base_budget * scale
        else:
            self._total_budget = base_budget

    def _initialize_degradation_rules(self, config_rules: Optional[list]) -> None:
        """Degradationルールリストのロードと検証を行う"""
        if not isinstance(config_rules, list):
            config_rules = DEFAULT_DEGRADATION_RULES

        self._degradation_rules = []
        for rule in config_rules:
            if isinstance(rule, dict) and "worker" in rule and "action" in rule and "savings_percent" in rule:
                try:
                    savings_percent_val = float(rule["savings_percent"])
                    self._degradation_rules.append({
                        "worker": str(rule["worker"]),
                        "action": str(rule["action"]),
                        "savings_percent": savings_percent_val
                    })
                except (ValueError, TypeError):
                    pass
        if not self._degradation_rules:
            self._degradation_rules = [dict(rule) for rule in DEFAULT_DEGRADATION_RULES]

    def _load_budgets(self) -> dict:
        """JSONからバジェット定義を読込。なければデフォルト値を使用。"""
        if self._budget_path and self._budget_path.exists():
            try:
                with open(self._budget_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    logger.warning(f"バジェットファイルの構造が不正（辞書型ではありません）: {self._budget_path}")
                    return {}
                logger.info(f"パフォーマンスバジェット読込: {self._budget_path}")
                return data
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
                logger.warning(f"バジェットファイル読込失敗 ({e}), デフォルト使用")
        return {}

    def _sanitize_duration(self, duration: any, worker_name: str) -> float:
        """入力された実行時間を検証し、無効な場合は警告を出して 0.0 を返す"""
        try:
            val = float(duration)
            if math.isnan(val) or math.isinf(val):
                logger.warning(f"無効なduration ({duration}) が {worker_name} に渡されました。0.0として処理します。")
                return 0.0
            if val < 0:
                logger.warning(f"負のduration ({duration}) が {worker_name} に渡されました。0.0として処理します。")
                return 0.0
            return val
        except (ValueError, TypeError):
            logger.warning(f"非数値のduration ({duration}) が {worker_name} に渡されました。0.0として処理します。")
            return 0.0

    def record_worker_time(self, worker_name: str, duration: float) -> None:
        """Worker実行時間を記録する (PB-01)

        W-03明確化: 並列Workerは各Workerの壁時計時間を個別記録する。
        3 Workerが並列で60秒ずつなら、累積=180秒としてバジェット判定する。
        これはWorker単体のリソース消費を正確に反映するための設計判断。
        """
        # 入力バリデーション
        if not worker_name:
            logger.warning("記録対象のWorker名が空です。スキップします。")
            return
        worker_name = str(worker_name)
        
        val = self._sanitize_duration(duration, worker_name)

        # BUG-01修正: 上書きではなく累積加算。リトライ時の全実行時間を正確に反映する。
        self._current_session[worker_name] = self._current_session.get(worker_name, 0.0) + val
        logger.debug(f"⏱️ {worker_name}: +{val:.1f}s (累積: {self._current_session[worker_name]:.1f}s)")

    def get_cumulative_time(self) -> float:
        """現時点の累積実行時間を返す"""
        return sum(self._current_session.values())

    def get_worker_budget(self, worker_name: str) -> float:
        """指定Workerのバジェット値を返す"""
        entry = self._worker_budgets.get(worker_name, {})
        val = entry.get("budget_seconds", 0.0) if isinstance(entry, dict) else entry
        try:
            return float(val) if val is not None else 0.0
        except (ValueError, TypeError):
            return 0.0

    def check_budget(self, worker_name: str) -> bool:
        """累積時間がバジェット内か判定 (PB-02) (Unused: worker_name)

        Returns:
            True: バジェット内, False: バジェット超過
        """
        cumulative = self.get_cumulative_time()
        return cumulative <= self._total_budget

    def check_individual_budget(self, worker_name: str) -> bool:
        """個別Workerのバジェット内か判定

        Returns:
            True: バジェット内, False: 超過
        """
        actual = self._current_session.get(worker_name, 0)
        budget = self.get_worker_budget(worker_name)
        if budget <= 0:
            return True
        return actual <= budget

    def get_degradation_targets(self) -> List[str]:
        """予算超過時にdegradeすべきWorker名リストを返す (PB-03)

        累積時間がtotal_budget * 0.8 を超過した場合のみ返却。
        degradation_rulesの順序で優先度決定。
        critical Workerは含まれない。
        """
        cumulative = self.get_cumulative_time()
        threshold = self._total_budget * self.BUDGET_THRESHOLD_RATIO

        if cumulative <= threshold:
            return []

        targets = []
        for rule in self._degradation_rules:
            worker_name = rule.get("worker")
            if not worker_name:
                continue
            entry = self._worker_budgets.get(worker_name)
            priority = entry.get("priority", "critical") if entry else "critical"
            if priority == "degradable":
                targets.append(worker_name)
        return targets

    def generate_report(self, session_id: str) -> PerformanceBudgetReport:
        """セッション終了時のパフォーマンスレポート生成 (PB-01/PB-02)"""
        workers = []
        for name, duration in self._current_session.items():
            budget = self.get_worker_budget(name)
            workers.append(WorkerPerformance(
                worker_name=name,
                duration_seconds=round(duration, 2),
                budget_seconds=budget,
                over_budget=duration > budget if budget > 0 else False,
            ))

        total_duration = self.get_cumulative_time()
        
        # session_id の型保護
        session_id_str = str(session_id) if session_id is not None else "unknown_session"
        
        return PerformanceBudgetReport(
            session_id=session_id_str,
            total_duration=round(total_duration, 2),
            total_budget=self._total_budget,
            over_budget=total_duration > self._total_budget,
            workers=workers,
            degradation_applied=list(self._degradation_applied),
            timestamp=datetime.now().isoformat(),
        )

    def _write_report_file(self, dir_path: Path, filename: str, data: dict) -> Path:
        """レポートファイルを指定ディレクトリに JSON 保存する"""
        dir_path.mkdir(parents=True, exist_ok=True)
        filepath = dir_path / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return filepath

    def _sanitize_session_id(self, session_id: any) -> str:
        """セッションIDをサニタイズして、パストラバーサルを防止する (TD-641)"""
        session_id_str = str(session_id) if session_id else "unknown_session"
        safe_session_id = "".join(c for c in session_id_str if c.isalnum() or c in ("-", "_"))
        return safe_session_id if safe_session_id else "unknown_session"

    def save_report(self, report: PerformanceBudgetReport) -> Path:
        """worker_perf_{session}.json に保存 (PB-01)"""
        try:
            safe_session_id = self._sanitize_session_id(report.session_id)
            filename = f"worker_perf_{safe_session_id}.json"
            data = asdict(report)
            filepath = self._write_report_file(self._output_dir, filename, data)
            logger.info(f"📊 パフォーマンスレポート保存: {filepath}")
            return filepath
        except (OSError, TypeError, ValueError, AttributeError) as e:
            if 'data' not in locals() or 'filename' not in locals():
                raise e
            logger.error(f"パフォーマンスレポート保存失敗 (出力ディレクトリ: {self._output_dir}): {e}. 代替フォルダへの保存を試みます。")
            try:
                fallback_dir = Path(tempfile.gettempdir()) / "performance_fallback"
                filepath = self._write_report_file(fallback_dir, filename, data)
                logger.info(f"📊 パフォーマンスレポート代替保存成功: {filepath}")
                return filepath
            except (OSError, TypeError, ValueError, AttributeError) as fallback_err:
                logger.critical(f"パフォーマンスレポートの代替保存も失敗しました: {fallback_err}")
                raise OSError(f"Failed to save performance report anywhere: {fallback_err}") from e

    def _validate_history_limit(self, limit: any) -> int:
        """履歴の取得件数リミット値を検証し、安全な整数を返す"""
        try:
            parsed_limit = int(limit)
            if parsed_limit < 0:
                return 20
            return parsed_limit
        except (ValueError, TypeError):
            return 20

    def _get_recent_report_files(self, limit: int) -> List[Path]:
        """出力ディレクトリから更新日時の新しい順にレポートファイルのパスリストを取得する"""
        if not self._output_dir.exists():
            return []

        try:
            found_files = list(self._output_dir.glob("worker_perf_*.json"))
        except OSError as e:
            logger.warning(f"レポート一覧の走査に失敗しました: {e}")
            return []

        valid_files = []
        for p in found_files:
            try:
                valid_files.append((p, p.stat().st_mtime))
            except (FileNotFoundError, OSError):
                continue

        valid_files.sort(key=lambda x: x[1], reverse=True)
        return [p for p, _ in valid_files[:limit]]

    def _load_report_contents(self, file_paths: List[Path]) -> List[dict]:
        """レポートファイルの内容を読み込む"""
        history = []
        for fp in file_paths:
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    history.append(json.load(f))
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
                logger.warning(f"レポートファイル読み込み失敗 ({fp}): {e}")
                continue
        return history

    def get_history(self, limit: int = 20) -> List[dict]:
        """過去のパフォーマンスレポート一覧 (PB-04)"""
        validated_limit = self._validate_history_limit(limit)
        files = self._get_recent_report_files(validated_limit)
        return self._load_report_contents(files)

    def get_budget_config(self) -> dict:
        """現在のバジェット設定を返す (PB-04)"""
        return {
            "total_budget_seconds": self._total_budget,
            "worker_budgets": self._worker_budgets,
            "degradation_rules": self._degradation_rules,
            "threshold_ratio": self.BUDGET_THRESHOLD_RATIO,
        }

    # EDGE-03: 品質ゲート等のcritical Workerはpriority変更禁止 (§8.2)
    PROTECTED_CRITICAL_WORKERS = frozenset({"品質チェック", "文字起こし", "最終レンダリング"})

    def update_budget_config(self, updates: dict) -> dict:
        """バジェット設定を更新する (PB-04)

        EDGE-03: critical Workerのpriorityをdegradableに変更する操作は
        黙殺される。§8.2品質ゲート義務のAPI経由の突破を防止。
        """
        if not isinstance(updates, dict):
            logger.warning(f"無効な更新パラメータ型 (dictである必要があります): {type(updates)}")
            return self.get_budget_config()

        if "total_budget_seconds" in updates:
            self._update_total_budget_config(updates["total_budget_seconds"])

        if "worker_budgets" in updates:
            self._update_worker_budgets_config(updates["worker_budgets"])

        return self.get_budget_config()

    def _update_total_budget_config(self, total_budget_val: any) -> None:
        """トータルバジェット設定値を検証・更新する"""
        try:
            total_budget_seconds = float(total_budget_val)
            if total_budget_seconds > 0:
                self._total_budget = total_budget_seconds
            else:
                logger.warning(f"無効なtotal_budget_seconds値 ({total_budget_val})。正数のみ受け付けます。")
        except (ValueError, TypeError):
            logger.warning(f"数値に変換できないtotal_budget_seconds値 ({total_budget_val})")

    def _update_worker_budgets_config(self, worker_budgets_updates: any) -> None:
        """複数Workerのバジェット設定値の一括更新を処理する"""
        if not isinstance(worker_budgets_updates, dict):
            logger.warning(f"無効なworker_budgets構造: {worker_budgets_updates}")
            return

        for worker_name, budget_value in worker_budgets_updates.items():
            worker_name = str(worker_name)
            if worker_name in self._worker_budgets:
                self._update_single_worker_budget(worker_name, budget_value)

    def _update_worker_budget_from_dict(self, worker_name: str, budget_value: dict) -> None:
        """辞書型の更新データからWorkerのバジェット設定値を更新する"""
        sanitized_value = {}
        if "budget_seconds" in budget_value:
            parsed_val = self._parse_update_budget_seconds(budget_value["budget_seconds"])
            if parsed_val is not None:
                sanitized_value["budget_seconds"] = parsed_val
        
        if "priority" in budget_value:
            priority_val = self._parse_update_priority(worker_name, budget_value["priority"])
            if priority_val is not None:
                sanitized_value["priority"] = priority_val

        self._worker_budgets[worker_name].update(sanitized_value)

    def _update_worker_budget_from_value(self, worker_name: str, budget_value: any) -> None:
        """単一値の更新データからWorkerのバジェット秒数を更新する"""
        parsed_val = self._parse_update_budget_seconds(budget_value)
        if parsed_val is not None:
            self._worker_budgets[worker_name]["budget_seconds"] = parsed_val

    def _update_single_worker_budget(self, worker_name: str, budget_value: any) -> None:
        """個々のWorkerのバジェット設定値を検証・更新する"""
        if isinstance(budget_value, dict):
            self._update_worker_budget_from_dict(worker_name, budget_value)
        else:
            self._update_worker_budget_from_value(worker_name, budget_value)

    def _parse_update_budget_seconds(self, value: any) -> Optional[float]:
        """更新用の budget_seconds を検証・変換する。無効な場合は None を返す。"""
        try:
            budget_seconds_val = float(value)
            if budget_seconds_val >= 0:
                return budget_seconds_val
        except (ValueError, TypeError):
            pass
        return None

    def _parse_update_priority(self, worker_name: str, value: any) -> Optional[str]:
        """更新用の priority を検証・変換する。変更不可または無効な場合は None を返す。"""
        if worker_name in self.PROTECTED_CRITICAL_WORKERS:
            logger.warning(f"保護されたWorker '{worker_name}' のpriorityは変更できません。")
            return None
        priority_val = str(value)
        if priority_val in ("critical", "degradable"):
            return priority_val
        return None

    def reset_session(self) -> None:
        """セッション記録をリセット"""
        self._current_session.clear()
        self._degradation_applied.clear()

    def get_progress_snapshot(self) -> dict:
        """C-02対策: 現在のバジェット消化状況のスナップショット。

        WebSocket経由でフロントエンドに送信するための軽量データ。
        PipelineCoordinator._notify() 内で利用想定。
        """
        cumulative = self.get_cumulative_time()
        remaining = max(0, self._total_budget - cumulative)
        completed = len(self._current_session)
        total_workers = len(self._worker_budgets)
        return {
            "type": "performance_budget_progress",
            "cumulative_seconds": round(cumulative, 1),
            "total_budget_seconds": round(self._total_budget, 1),
            "consumption_ratio": round(cumulative / self._total_budget, 3) if self._total_budget > 0 else 0,
            "remaining_seconds": round(remaining, 1),
            "workers_completed": completed,
            "workers_total": total_workers,
            "over_budget": cumulative > self._total_budget,
        }
