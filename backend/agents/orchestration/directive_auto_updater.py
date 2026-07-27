"""
Directive自動更新エンジン

Phase遷移時にOpus Directiveを自動更新する。
学習エンジンの分析結果と収穫逓減検出を反映し、
ユーザー介入なしでFlashの戦略を最新Phaseに追従させる。
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent
_DIRECTIVE_PATH = _BASE_DIR / "opus_directive.json"
_PHASE_STATE_PATH = _BASE_DIR.parent / "memory" / "phase_state.json"


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def auto_update_directive(current_phase: Optional[int] = None) -> dict:
    """Phase遷移時にDirectiveを自動更新する。

    学習エンジンの分析結果を反映:
    - グループ別打率に基づく配分最適化
    - 収穫逓減モジュールの自動blacklist追加
    - 未投資モジュールのfocus追加

    Args:
        current_phase: 現在のPhase。Noneの場合はphase_stateから取得。

    Returns:
        更新後のDirective辞書
    """
    # Phase取得
    if current_phase is None:
        ps = _read_json(_PHASE_STATE_PATH)
        current_phase = ps.get("current_phase", 29)

    # 既存Directiveロード
    old_directive = _read_json(_DIRECTIVE_PATH)
    old_phase = _extract_phase_from_id(old_directive.get("directive_id", ""))

    # 同じPhaseなら更新不要
    if old_phase == current_phase:
        logger.info(f"[DirectiveUpdate] Phase {current_phase} unchanged, skip")
        return old_directive

    # 学習エンジンから最適配分を取得
    try:
        from backend.agents.orchestration.task_learning_engine import TaskLearningEngine
        engine = TaskLearningEngine()
        group_report = engine.get_group_performance_report()
        diminishing = engine.detect_diminishing_returns(threshold=0.5)
    except (ImportError, FileNotFoundError, json.JSONDecodeError, PermissionError, ValueError) as e:
        logger.warning(f"[DirectiveUpdate] Learning engine unavailable: {e}")
        group_report = {}
        diminishing = []

    # 配分を打率に基づいて計算（合計100%）
    priorities = _calculate_priorities(group_report)

    # 収穫逓減モジュールをblacklistに
    old_blacklist = old_directive.get("blacklist_override", [])
    new_blacklist = list(set(old_blacklist + [d["module"] for d in diminishing]))

    # focus_modulesは既存を維持（手動設定を尊重）
    focus = old_directive.get("focus_modules", [])

    # 新Directive構築
    new_directive = {
        "directive_id": f"D-opus-auto-p{current_phase}-v1",
        "issued_at": _now_iso(),
        "issued_by": "opus_auto",
        "priorities": priorities,
        "focus_modules": focus,
        "blacklist_override": new_blacklist,
        "resume": True,
        "notes": (
            f"Phase {current_phase} 自動生成Directive。"
            f"学習エンジン分析に基づく配分最適化。"
            f"収穫逓減{len(diminishing)}モジュールをblacklist追加。"
        ),
        "auto_generated": True,
        "previous_directive_id": old_directive.get("directive_id"),
    }

    _write_json(_DIRECTIVE_PATH, new_directive)
    logger.info(
        f"[DirectiveUpdate] Updated: Phase {old_phase}→{current_phase}, "
        f"priorities={priorities}"
    )

    return new_directive


def _extract_phase_from_id(directive_id: str) -> Optional[int]:
    """Directive IDからPhase番号を抽出する。
    例: 'D-opus-session-p27-diversified-v1' → 27
    """
    import re
    match = re.search(r'-p(\d+)-', directive_id)
    if match:
        return int(match.group(1))
    return None


def _calculate_priorities(group_report: dict) -> dict:
    """グループ別パフォーマンスから最適な配分を計算する。

    打率の高いグループに多く配分し、低打率グループは削減する。
    ただし最低5%を保証（打率0でも探索の余地を残す）。
    """
    if not group_report:
        return {
            "test_weaver": 20,
            "bug_hunter": 20,
            "refactor": 20,
            "tdr_cleanup": 15,
            "thumbnail": 15,
            "design_stock": 10,
        }

    # 基本グループ（design_stockは固定10%）
    groups = ["test_weaver", "bug_hunter", "refactor", "tdr_cleanup", "thumbnail"]
    allocatable = 90  # 100 - 10(design_stock)
    min_per_group = 5

    # 打率の重み付け（打率^1.5で高打率を強調）
    weights = {}
    for g in groups:
        rate = group_report.get(g, {}).get("hit_rate", 0.5)
        weights[g] = max(rate, 0.1) ** 1.5

    total_weight = sum(weights.values())
    if total_weight == 0:
        total_weight = 1

    priorities = {"design_stock": 10}
    remaining = allocatable

    # 重み付け配分
    for g in groups:
        share = max(min_per_group, round(allocatable * weights[g] / total_weight))
        share = min(share, remaining - min_per_group * (len(groups) - len(priorities) + 1 - 1))
        if share < min_per_group:
            share = min_per_group
        priorities[g] = share
        remaining -= share

    # 残りを最高打率に追加
    if remaining > 0:
        best = max(weights, key=weights.get)
        priorities[best] += remaining
    elif remaining < 0:
        # 超過した場合は最低打率から削減
        worst = min(weights, key=weights.get)
        priorities[worst] = max(min_per_group, priorities[worst] + remaining)

    return priorities


def should_update(current_phase: Optional[int] = None) -> bool:
    """Directiveの更新が必要かどうかを判定する。"""
    if current_phase is None:
        ps = _read_json(_PHASE_STATE_PATH)
        current_phase = ps.get("current_phase", 29)

    old = _read_json(_DIRECTIVE_PATH)
    old_phase = _extract_phase_from_id(old.get("directive_id", ""))
    return old_phase != current_phase
