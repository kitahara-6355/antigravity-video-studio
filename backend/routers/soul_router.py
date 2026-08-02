"""
soul_router.py — Soul Passportダッシュボード統合API（U-09）

チャンネル主の成長可視化:
- 演出哲学のサマリー
- 成長クロニクル（タイムライン）
- XPとランク
- 制作統計
"""

try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/soul", tags=["soul"])

BRANDING_DIR = Path(__file__).parent.parent / "branding"
# 実行のたびに追記される進化履歴。読み書きの両方をこの経路へ通すこと。
EVOLUTION_LOG_PATH = _writable_path("backend/branding/evolution_log.json")
CONSTITUTION_PATH = BRANDING_DIR / "constitution.json"

try:
    import google.adk
    HAS_ADK = True
except ImportError:
    HAS_ADK = False


# ============================================================
# ヘルパー
# ============================================================

def _load_json(path: Path) -> Dict:
    """JSONファイルを安全にロード"""
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except HTTPException:
        raise
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load {path.name}: {e}")
    return {}


def _safe_load_for_writing(path: Path) -> Dict:
    """書き込み用にJSONファイルをロード。ファイルが存在するが読み込めない場合は例外を投げる"""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except HTTPException:
        raise
    except json.JSONDecodeError as jde:
        logger.error(f"JSON format error in {path.name} before writing: {jde}")
        raise HTTPException(
            status_code=500,
            detail=f"Data file {path.name} is corrupted and cannot be updated safely: {str(jde)}"
        )
    except OSError as e:
        logger.error(f"Failed to load {path.name} before writing: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load data file {path.name} before writing: {str(e)}"
        )


def _calculate_xp(entries: List[Any]) -> int:
    """エントリー数とアクションからXPを算出"""
    xp = 0
    if not isinstance(entries, list):
        return 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        xp += 50  # 基本XP（エントリーごと）
        stats = entry.get("stat_changes")
        if isinstance(stats, list):
            xp += len(stats) * 10
        elif stats:  # リストではないが何かしら値がある場合
            xp += 10
        if entry.get("philosophy_evolved"):
            xp += 100
    return xp


def _determine_rank(xp: int) -> Dict[str, Any]:
    """XPからランクを決定"""
    ranks = [
        (0,    "Dreamer",     "🌱", "夢を見始めた段階"),
        (200,  "Scout",       "🔍", "探索している段階"),
        (500,  "Apprentice",  "📝", "見習い"),
        (1000, "Creator",     "🎨", "一人前のクリエイター"),
        (2000, "Expert",      "⚡", "熟練者"),
        (5000, "Master",      "👑", "マスター"),
        (10000, "Legend",     "🏆", "伝説"),
    ]
    rank = ranks[0]
    for threshold, name, icon, desc in ranks:
        if xp >= threshold:
            rank = (threshold, name, icon, desc)
    
    next_rank = None
    for threshold, name, icon, desc in ranks:
        if threshold > xp:
            next_rank = {"name": name, "threshold": threshold, "remaining": threshold - xp}
            break

    return {
        "level": rank[1],
        "icon": rank[2],
        "description": rank[3],
        "xp": xp,
        "next_rank": next_rank,
    }


# ============================================================
# エンドポイント
# ============================================================

@router.get("/dashboard")
async def get_soul_dashboard():
    """
    Soul Passportダッシュボード統合API

    チャンネル主・管理者それぞれの成長データを統合して返す。
    """
    evo_log = _load_json(EVOLUTION_LOG_PATH)
    constitution = _load_json(CONSTITUTION_PATH)

    # HAS_ADKが有効な場合、最新のダッシュボード状態についてCouncil of Mindsに意見を聞く
    if HAS_ADK:
        try:
            # 保存時に破損していないか事前にチェック（データ保護のため）
            _safe_load_for_writing(EVOLUTION_LOG_PATH)

            from agents.council_graph import run_council
            entries_for_xp = evo_log.get("entries", []) if isinstance(evo_log.get("entries"), list) else []
            decisions_for_count = evo_log.get("decision_insights", []) if isinstance(evo_log.get("decision_insights"), list) else []

            query = f"現在のXP: {_calculate_xp(entries_for_xp)}, 意思決定数: {len(decisions_for_count)}"
            council_res = await run_council(user_query=query, council_mode="post_production")
            
            if council_res.get("status") == "success" and council_res.get("synthesis"):
                latest_insight = {
                    "summary": "Council Insight",
                    "insight": council_res["synthesis"],
                    "timestamp": datetime.now().timestamp(),
                    "action": "council_analysis"
                }
                current_decisions = evo_log.get("decision_insights", [])
                if not isinstance(current_decisions, list):
                    current_decisions = []

                evo_log["decision_insights"] = [
                    d for d in current_decisions
                    if isinstance(d, dict) and d.get("action") != "council_analysis"
                ]
                evo_log["decision_insights"].append(latest_insight)
                
                try:
                    with open(EVOLUTION_LOG_PATH, "w", encoding="utf-8") as f:
                        json.dump(evo_log, f, ensure_ascii=False, indent=2)
                except HTTPException:
                    raise
                except (TypeError, OSError) as save_err:
                    logger.error(f"Failed to save evolution log in dashboard: {save_err}")
                    raise HTTPException(status_code=500, detail=f"Failed to save log: {str(save_err)}")
        except HTTPException:
            raise
        except (ImportError, ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            logger.error(f"ADK integration failed in dashboard: {e}")
            raise HTTPException(status_code=500, detail=f"ADK integration failed: {str(e)}")

    entries = evo_log.get("entries", [])
    if not isinstance(entries, list):
        entries = []
    philosophies = evo_log.get("philosophies", [])
    if not isinstance(philosophies, list):
        philosophies = []
    decisions = evo_log.get("decision_insights", [])
    if not isinstance(decisions, list):
        decisions = []

    # XP & ランク
    total_xp = _calculate_xp(entries)
    rank = _determine_rank(total_xp)

    # 最新の演出哲学
    latest_philosophy = philosophies[-1] if philosophies else "まだ哲学が確立されていません"
    if isinstance(latest_philosophy, dict):
        latest_philosophy = latest_philosophy.get("text", str(latest_philosophy))

    # 制作統計
    total_sessions = len(entries)
    total_decisions = len(decisions)
    approval_count = sum(1 for d in decisions if isinstance(d, dict) and d.get("action") == "approve")
    rejection_count = sum(1 for d in decisions if isinstance(d, dict) and d.get("action") == "reject")

    # ブランドキーワード
    brand = constitution.get("brand_personality", {}) if isinstance(constitution, dict) else {}
    if not isinstance(brand, dict):
        brand = {}
    keywords = brand.get("keywords", [])
    if not isinstance(keywords, list):
        keywords = []

    # 成長クロニクル（最新10件）
    chronicle = []
    for entry in entries[-10:]:
        if isinstance(entry, dict):
            chronicle.append({
                "summary": entry.get("summary", ""),
                "insight": entry.get("insight", ""),
                "timestamp": entry.get("timestamp"),
                "stat_changes": entry.get("stat_changes", []) if isinstance(entry.get("stat_changes"), list) else [],
            })

    return {
        "philosophy": {
            "current": latest_philosophy,
            "total_philosophies": len(philosophies),
            "history": philosophies[-5:] if len(philosophies) > 5 else philosophies,
        },
        "rank": rank,
        "statistics": {
            "total_sessions": total_sessions,
            "total_decisions": total_decisions,
            "approvals": approval_count,
            "rejections": rejection_count,
            "approval_rate": round(approval_count / max(total_decisions, 1) * 100, 1),
        },
        "brand_keywords": keywords,
        "chronicle": chronicle,
        "last_updated": evo_log.get("last_updated"),
        # ▼ 業界ベンチマーク（MARKET_RESEARCH_POLICY.md 準拠）
        "industry_benchmarks": {
            "source": "MARKET_RESEARCH_POLICY.md + Web Research 2026-04",
            "tv_standards": {
                "subtitle_chars_per_second": 4,
                "subtitle_max_per_line": 16,
                "subtitle_lead_frames": 3,
                "subtitle_trail_frames": 5,
                "reference": "NHK字幕規格 + 民放連ガイドライン",
            },
            "top_youtuber_benchmarks": {
                "ctr_average_percent": 3.5,
                "ctr_top_tier_percent": 6.0,
                "retention_average_percent": 40,
                "retention_top_tier_percent": 55,
                "hook_window_seconds": 5,
                "dopamine_interval_seconds": 10,
                "reengagement_mark_seconds": 180,
                "reference": "MrBeast Production System + YouTube Algorithm 2026",
            },
            "color_grading": {
                "trend": "自然な肌色 + シネマティック深度 + ライブラリ全体の一貫性",
                "tech_benchmark": "HDR10+ / Dolby Vision",
                "reference": "2026 YouTube Production Standards Research",
            },
            "typography": {
                "trend": "キネティックタイポグラフィ + サイレントファーストデザイン",
                "silent_first": "音声なし視聴を前提としたキャプション品質が必須",
                "reference": "YouTube Silent-First Design 2026",
            },
        },
    }


@router.get("/philosophy")
async def get_philosophy():
    """演出哲学の一覧を取得"""
    evo_log = _load_json(EVOLUTION_LOG_PATH)
    philosophies = evo_log.get("philosophies", [])

    return {
        "philosophies": philosophies,
        "count": len(philosophies),
        "latest": philosophies[-1] if philosophies else None,
    }


@router.get("/chronicle")
async def get_chronicle(limit: int = 20):
    """成長クロニクルを取得"""
    evo_log = _load_json(EVOLUTION_LOG_PATH)
    entries = evo_log.get("entries", [])
    if not isinstance(entries, list):
        entries = []

    chronicle = []
    for entry in entries[-limit:]:
        if isinstance(entry, dict):
            chronicle.append({
                "summary": entry.get("summary", ""),
                "insight": entry.get("insight", ""),
                "timestamp": entry.get("timestamp"),
                "stat_changes": entry.get("stat_changes", []) if isinstance(entry.get("stat_changes"), list) else [],
            })

    return {
        "chronicle": chronicle,
        "total": len(entries),
    }


@router.post("/record")
async def record_soul_event(event: Dict[str, Any]):
    """
    Soul Passport にイベントを記録

    パイプライン完了時に自動呼び出しされる。
    """
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="Invalid event format. Expected a JSON object.")

    # 既存データの読み込みと破損防止の検証
    try:
        evo_log = _safe_load_for_writing(EVOLUTION_LOG_PATH)
    except HTTPException as he:
        return {"status": "error", "error": he.detail}

    summary = event.get("summary")
    insight = event.get("insight")
    stat_changes = event.get("stat_changes")
    philosophy_evolved = event.get("philosophy_evolved")

    # 型の正規化とバリデーション
    if summary is not None and not isinstance(summary, str):
        summary = str(summary)
    else:
        summary = summary or "イベント記録"

    if insight is not None and not isinstance(insight, str):
        insight = str(insight)
    else:
        insight = insight or ""

    if stat_changes is not None and not isinstance(stat_changes, list):
        stat_changes = [stat_changes]
    else:
        stat_changes = stat_changes or []
    stat_changes = [str(x) for x in stat_changes]

    philosophy_evolved = bool(philosophy_evolved)

    entry = {
        "summary": summary,
        "insight": insight,
        "timestamp": datetime.now().timestamp(),
        "stat_changes": stat_changes,
        "philosophy_evolved": philosophy_evolved,
    }

    evo_log.setdefault("entries", []).append(entry)
    evo_log["last_updated"] = datetime.now().isoformat()

    try:
        with open(EVOLUTION_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(evo_log, f, ensure_ascii=False, indent=2)
        logger.info(f"✅ Soul event recorded: {entry['summary']}")
        return {"status": "recorded", "entry": entry}
    except HTTPException:
        raise
    except (TypeError, OSError) as e:
        logger.error(f"Soul event recording failed: {e}")
        return {"status": "error", "error": str(e)}
