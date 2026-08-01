"""
【S4-1】タスク結果の構造化学習エンジン

flash_reports.jsonl の過去バッチ結果を分析し、次のバッチ生成の品質を向上させる。
OrchestrationHub から呼び出され、バッチ生成時の判断材料を提供する。

主な機能:
  - モジュール×グループの有効打率マトリックス構築
  - 最適なグループ配分の提案
  - 収穫逓減の検出（同一モジュールへの投資効率低下）
  - モジュール別の推奨グループ提案
"""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent
_FLASH_REPORTS_PATH = _BASE_DIR / "flash_reports.jsonl"
_LEARNING_CACHE_PATH = _writable_path("backend/agents/orchestration/task_learning_cache.json")


def _read_jsonl(path: Path) -> list[dict]:
    """JSONLファイルを読み込んでリストで返す"""
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding="utf-8").strip().split("\n"):
        line = line.strip()
        if line:
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return result


def _write_json(path: Path, data: dict) -> None:
    """JSONファイルをUTF-8で書き込む"""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class TaskLearningEngine:
    """タスク結果から学習し、次バッチの品質を向上させる。

    flash_reports.jsonl の全バッチ結果を分析し、以下の知見を抽出:
    1. モジュール×グループの有効打率マトリックス
    2. グループ別の最適配分
    3. 収穫逓減モジュールの検出
    4. モジュール別の推奨グループ
    """

    def __init__(self, reports_path: Optional[Path] = None,
                 cache_path: Optional[Path] = None):
        self.reports_path = reports_path or _FLASH_REPORTS_PATH
        self.cache_path = cache_path or _LEARNING_CACHE_PATH
        self._matrix: dict[str, dict[str, dict]] = {}  # module -> group -> stats
        self._group_stats: dict[str, dict] = {}  # group -> stats
        self._module_timeline: dict[str, list[dict]] = {}  # module -> list of tasks
        self._loaded = False

    def _load_and_analyze(self, lookback: int = 100) -> None:
        """直近N件のバッチ結果を分析してマトリックスを構築する。"""
        reports = _read_jsonl(self.reports_path)
        if not reports:
            self._loaded = True
            return

        recent = reports[-lookback:]

        # モジュール × グループ のクロス集計
        matrix: dict[str, dict[str, dict]] = defaultdict(
            lambda: defaultdict(lambda: {"hits": 0, "total": 0, "durations": []})
        )
        group_stats: dict[str, dict] = defaultdict(
            lambda: {"hits": 0, "total": 0, "durations": []}
        )
        module_timeline: dict[str, list[dict]] = defaultdict(list)

        for report in recent:
            if not isinstance(report, dict):
                continue
            batch_id = report.get("batch_id", "?")
            tasks = report.get("tasks")
            if not isinstance(tasks, list):
                continue
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                group = task.get("group", "unknown")
                module = task.get("target_module", "unknown")
                result = task.get("result")

                changed_files = result.get("changed_files") if isinstance(result, dict) else None
                changed_list = changed_files if isinstance(changed_files, list) else []
                # 【弱点①修正】ファイル変更 AND テストPASS の両方を要求。
                # 変更したがFAILしたタスクを偽陽性として除外する。
                task_status = task.get("status", "")
                is_hit = (
                    len(changed_list) > 0
                    and task_status in ("pass", "completed")
                )

                # クロス集計
                cell = matrix[module][group]
                cell["total"] += 1
                if is_hit:
                    cell["hits"] += 1

                # グループ別集計
                gs = group_stats[group]
                gs["total"] += 1
                if is_hit:
                    gs["hits"] += 1

                # 処理時間
                started = task.get("started_at")
                completed = task.get("completed_at")
                if started and completed:
                    try:
                        from datetime import datetime, timezone
                        s = datetime.fromisoformat(started)
                        c = datetime.fromisoformat(completed)
                        duration = (c - s).total_seconds()
                        cell["durations"].append(duration)
                        gs["durations"].append(duration)
                    except (ValueError, TypeError):
                        pass

                # タイムライン（収穫逓減分析用）
                changed_count = len(changed_list)
                module_timeline[module].append({
                    "batch_id": batch_id,
                    "group": group,
                    "is_hit": is_hit,
                    "changed_files": changed_count,
                })

        self._matrix = dict(matrix)
        self._group_stats = dict(group_stats)
        self._module_timeline = dict(module_timeline)
        self._loaded = True

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._load_and_analyze()

    def get_module_group_affinity(self, top_n: int = 10) -> list[dict]:
        """モジュールごとに最も効果的なグループを推薦する。

        Returns:
            [{"module": "...", "best_group": "...", "hit_rate": 0.85, 
              "sample_size": 10, "all_groups": {...}}, ...]
        """
        self._ensure_loaded()
        results = []

        for module, groups in self._matrix.items():
            best_group = None
            best_rate = -1
            all_group_rates = {}

            for group, stats in groups.items():
                if stats["total"] >= 2:  # 最低2サンプル
                    rate = stats["hits"] / stats["total"]
                    all_group_rates[group] = {
                        "hit_rate": round(rate, 2),
                        "total": stats["total"],
                        "hits": stats["hits"],
                    }
                    if rate > best_rate:
                        best_rate = rate
                        best_group = group

            if best_group:
                results.append({
                    "module": module,
                    "best_group": best_group,
                    "hit_rate": round(best_rate, 2),
                    "sample_size": sum(g["total"] for g in groups.values()),
                    "all_groups": all_group_rates,
                })

        # 打率の低いモジュールを優先的に改善対象に
        results.sort(key=lambda x: x["hit_rate"])
        return results[:top_n]

    def suggest_optimal_batch_composition(self, batch_size: int = 12) -> dict[str, int]:
        """最適なグループ配分を提案する。

        過去のバッチ結果から各グループの有効打率を算出し、
        打率に比例した配分を提案する。

        Returns:
            {"test_weaver": 3, "bug_hunter": 4, "refactor": 2, ...}
        """
        self._ensure_loaded()

        if not self._group_stats:
            # データなし → デフォルト均等配分
            groups = ["test_weaver", "bug_hunter", "refactor", "tdr_cleanup", "thumbnail"]
            per_group = batch_size // len(groups)
            remainder = batch_size - per_group * len(groups)
            result = {g: per_group for g in groups}
            result[groups[0]] += remainder  # 余りを先頭グループに
            return result

        # 各グループの有効打率を計算
        group_rates = {}
        for group, stats in self._group_stats.items():
            if stats["total"] >= 3:
                group_rates[group] = stats["hits"] / stats["total"]
            else:
                group_rates[group] = 0.5  # サンプル不足時は中立

        # 最低1スロット保証を考慮した配分
        allocation = {}
        remaining = batch_size
        sorted_groups = sorted(group_rates.items(), key=lambda x: x[1], reverse=True)

        # 1. まず全員に最低 1 スロットを配る (batch_size が許す限り)
        for g, _ in sorted_groups:
            if remaining > 0:
                allocation[g] = 1
                remaining -= 1
            else:
                allocation[g] = 0

        # 2. 残りスロットがある場合、打率に比例して追加配分する
        if remaining > 0:
            total_rate = sum(group_rates.values())
            if total_rate == 0:
                total_rate = 1.0

            original_remaining = remaining
            for g, rate in sorted_groups:
                if remaining <= 0:
                    break
                extra = round(original_remaining * rate / total_rate)
                extra = min(extra, remaining)
                allocation[g] += extra
                remaining -= extra

            # 丸め誤差などで残りがあれば最高打率グループに追加
            if remaining > 0:
                best = sorted_groups[0][0]
                allocation[best] += remaining

        return allocation

    def detect_diminishing_returns(self, threshold: float = 0.3) -> list[dict]:
        """収穫逓減に入ったモジュールを検出する。

        直近5回のタスクで変更ファイル数が減少傾向にあるモジュールを特定。

        Args:
            threshold: 減少率の閾値（0.3 = 30%以上減少で検出）

        Returns:
            [{"module": "...", "trend": "declining", "recent_avg": 0.5,
              "earlier_avg": 2.0, "decline_rate": 0.75}, ...]
        """
        self._ensure_loaded()
        results = []

        for module, timeline in self._module_timeline.items():
            if len(timeline) < 6:
                continue

            # 前半と後半に分割
            mid = len(timeline) // 2
            earlier = timeline[:mid]
            recent = timeline[mid:]

            earlier_avg = sum(t["changed_files"] for t in earlier) / len(earlier) if earlier else 0
            recent_avg = sum(t["changed_files"] for t in recent) / len(recent) if recent else 0

            if earlier_avg > 0:
                decline_rate = 1 - (recent_avg / earlier_avg)
                if decline_rate >= threshold:
                    results.append({
                        "module": module,
                        "trend": "declining",
                        "recent_avg": round(recent_avg, 2),
                        "earlier_avg": round(earlier_avg, 2),
                        "decline_rate": round(decline_rate, 2),
                        "total_tasks": len(timeline),
                    })

        results.sort(key=lambda x: x["decline_rate"], reverse=True)
        return results

    def get_group_performance_report(self) -> dict[str, dict]:
        """グループ別のパフォーマンスレポートを生成する。

        Returns:
            {"test_weaver": {"hit_rate": 0.4, "total": 25, "hits": 10,
                             "avg_duration_sec": 180, "trend": "stable"}, ...}
        """
        self._ensure_loaded()
        report = {}

        for group, stats in self._group_stats.items():
            hit_rate = stats["hits"] / stats["total"] if stats["total"] > 0 else 0
            avg_duration = (
                sum(stats["durations"]) / len(stats["durations"])
                if stats["durations"] else 0
            )

            report[group] = {
                "hit_rate": round(hit_rate, 2),
                "total": stats["total"],
                "hits": stats["hits"],
                "avg_duration_sec": round(avg_duration, 1),
            }

        return report

    def suggest_module_for_group(self, group: str, 
                                 available_modules: list[str],
                                 exclude: Optional[set] = None) -> Optional[str]:
        """指定グループに最も効果的なモジュールを推薦する。

        過去の実績データから、そのグループで高打率だったモジュールを優先。
        未投資モジュール（データなし）も候補に含める。

        Returns:
            推奨モジュール名、候補なしの場合はNone
        """
        self._ensure_loaded()
        exclude = exclude or set()

        candidates = []
        for module in available_modules:
            if module in exclude:
                continue

            groups = self._matrix.get(module, {})
            group_stats = groups.get(group)

            if group_stats and group_stats["total"] >= 2:
                rate = group_stats["hits"] / group_stats["total"]
                candidates.append((module, rate, group_stats["total"]))
            else:
                # 未投資モジュール → 中程度のスコアで候補に
                candidates.append((module, 0.5, 0))

        if not candidates:
            return None

        # 打率でソート（同率なら未投資を優先 = 探索のため）
        candidates.sort(key=lambda x: (-x[1], x[2]))
        
        # ε-greedy探索: 20%の確率で未投資モジュールをランダム探索
        import random
        epsilon = 0.2
        if random.random() < epsilon:
            # 未投資モジュール（total=0）を優先的に探索
            unexplored = [c for c in candidates if c[2] == 0]
            if unexplored:
                return random.choice(unexplored)[0]
            # 未投資がない場合はランダムに1つ選択
            return random.choice(candidates)[0]
        
        return candidates[0][0]

    def save_cache(self) -> None:
        """分析結果をキャッシュに保存する。"""
        self._ensure_loaded()
        cache = {
            "group_performance": self.get_group_performance_report(),
            "diminishing_returns": self.detect_diminishing_returns(),
            "optimal_composition_12": self.suggest_optimal_batch_composition(12),
            "module_affinity_top10": self.get_module_group_affinity(10),
        }
        try:
            _write_json(self.cache_path, cache)
        except (OSError, TypeError) as e:
            logger.warning(f"Failed to save learning cache: {e}")
            raise

    def get_summary(self) -> str:
        """分析結果のサマリーを人間可読な文字列で返す。"""
        self._ensure_loaded()
        lines = ["=== タスク学習エンジン レポート ===\n"]

        # グループ別パフォーマンス
        lines.append("【グループ別有効打率】")
        for group, stats in sorted(
            self.get_group_performance_report().items(),
            key=lambda x: x[1]["hit_rate"], reverse=True
        ):
            lines.append(
                f"  {group}: {stats['hit_rate']*100:.0f}% "
                f"({stats['hits']}/{stats['total']}) "
                f"avg={stats['avg_duration_sec']:.0f}秒"
            )

        # 収穫逓減
        declining = self.detect_diminishing_returns()
        if declining:
            lines.append(f"\n【収穫逓減モジュール】({len(declining)}件)")
            for d in declining[:5]:
                lines.append(
                    f"  {d['module']}: 変更量 {d['earlier_avg']:.1f}→{d['recent_avg']:.1f} "
                    f"({d['decline_rate']*100:.0f}%減少)"
                )

        # 最適配分提案
        comp = self.suggest_optimal_batch_composition(12)
        lines.append(f"\n【推奨バッチ配分（12タスク）】")
        for g, c in sorted(comp.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"  {g}: {c}スロット")

        return "\n".join(lines)
