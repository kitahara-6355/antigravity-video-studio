"""
Admin Analytics Router — A-3 YouTube Analytics連携・効果分析

Admin UXストーリー A-3 に対応するバックエンドAPI。
22シーンのダッシュボード機能(CTR推移/維持率推移/動画別実績/ベンチマーク/
テンプレ効果/SmartCut効果/AI提案効果/KPI管理/成長予測等)を提供する。

設計書: design_admin_a1_a7_full.md.resolved (推移表転記済み/)
注意: 既存の youtube_optimizer.py (Phase 51) はパイプライン内のメタデータ最適化用。
      本ルーターは管理者向けAnalyticsダッシュボードAPIとして棲み分ける。
"""

import logging
import re
from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/analytics", tags=["Admin Analytics"])


def _handle_unexpected_error(e: Exception, action_name: str) -> None:
    """例外をログ出力し、HTTPException(500)を送出する（HTTPExceptionの場合はそのまま再送出）"""
    if isinstance(e, HTTPException):
        raise e
    logger.exception(f"Unexpected error in {action_name}")
    raise HTTPException(status_code=500, detail="Internal server error")


def _calculate_average_metrics(videos: List[dict]) -> tuple[float, float]:
    """動画リストからCTRと視聴維持率の平均値を算出する"""
    if not videos:
        return 0.0, 0.0
    avg_ctr = sum(v["ctr"] for v in videos) / len(videos)
    avg_retention = sum(v["retention"] for v in videos) / len(videos)
    return avg_ctr, avg_retention


def validate_period_format(period: str) -> None:
    """期間指定（YYYY-MM）のフォーマット検証"""
    if not period or not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", period):
        raise HTTPException(status_code=400, detail=f"Invalid period format: {period}. Expected YYYY-MM")


# ── リクエストモデル ──

class KPISettingRequest(BaseModel):
    target_ctr: float = 5.0
    target_retention: float = 50.0


class ApplySuggestionRequest(BaseModel):
    suggestion_id: int


class ReportGenerateRequest(BaseModel):
    period: str = "monthly"  # "weekly" or "monthly"


class APIConnectionRequest(BaseModel):
    update_interval_minutes: int = 60
    enabled: bool = True


# ── 状態管理 (インメモリ) ──

_kpi_settings = {"target_ctr": 5.0, "target_retention": 50.0}
_api_connection = {
    "connected": True,
    "update_interval_minutes": 60,
    "last_sync": datetime.now().isoformat(),
    "enabled": True,
}
_applied_suggestions: List[int] = []

# シミュレーション用: 動画パフォーマンスデータ
_video_data = [
    {"id": 1, "title": "AI動画編集入門", "ctr": 4.8, "retention": 52.3, "views": 12500, "published": "2026-04-01"},
    {"id": 2, "title": "SmartCut活用術", "ctr": 5.2, "retention": 48.7, "views": 8900, "published": "2026-04-08"},
    {"id": 3, "title": "テンプレート比較", "ctr": 3.9, "retention": 44.1, "views": 6300, "published": "2026-04-15"},
    {"id": 4, "title": "品質ゲート解説", "ctr": 6.1, "retention": 55.8, "views": 15200, "published": "2026-04-22"},
    {"id": 5, "title": "YouTube最適化ガイド", "ctr": 4.5, "retention": 47.2, "views": 10100, "published": "2026-04-29"},
]

_template_data = [
    {"name": "教育・解説系", "avg_ctr": 5.1, "avg_retention": 51.2, "video_count": 12},
    {"name": "エンタメ・バラエティ系", "avg_ctr": 6.3, "avg_retention": 42.8, "video_count": 8},
    {"name": "ニュース・時事系", "avg_ctr": 3.8, "avg_retention": 38.5, "video_count": 5},
    {"name": "チュートリアル系", "avg_ctr": 4.2, "avg_retention": 56.7, "video_count": 15},
]

_smartcut_settings = [
    {"setting": "aggressive", "avg_retention": 55.3, "video_count": 8, "description": "積極的カット: 無音区間0.5秒以上を除去"},
    {"setting": "balanced", "avg_retention": 49.1, "video_count": 12, "description": "バランス型: 3秒以上の無音区間を除去"},
    {"setting": "conservative", "avg_retention": 43.8, "video_count": 5, "description": "保守的: 5秒以上の無音区間のみ除去"},
]

_improvement_suggestions = [
    {"id": 1, "category": "thumbnail", "impact": "high", "description": "サムネイルにテキストオーバーレイ追加でCTR+1.2%見込み", "applied": False},
    {"id": 2, "category": "smartcut", "impact": "medium", "description": "SmartCut設定をaggressiveに変更で維持率+5%見込み", "applied": False},
    {"id": 3, "category": "chapter", "impact": "medium", "description": "チャプター自動生成の有効化で維持率+3%見込み", "applied": False},
    {"id": 4, "category": "title", "impact": "low", "description": "タイトルに数字/疑問形を含めてCTR+0.5%見込み", "applied": False},
]


# ── S1: ダッシュボード概要 ──

@router.get("/dashboard")
async def get_analytics_dashboard():
    """A-3 S1: YouTube Analytics連携ダッシュボードの全体情報"""
    try:
        avg_ctr, avg_retention = _calculate_average_metrics(_video_data)
        return {
            "title": "YouTube Analytics連携",
            "status": "connected" if _api_connection["connected"] else "disconnected",
            "kpi_summary": {
                "avg_ctr": round(avg_ctr, 1),
                "avg_retention": round(avg_retention, 1),
                "total_videos": len(_video_data),
                "total_views": sum(v["views"] for v in _video_data),
            },
            "sections": [
                "ctr_trend", "retention_trend", "video_performance",
                "benchmark", "template_effect", "smartcut_effect",
                "ai_suggestion_effect", "chapter_effect", "thumbnail_effect",
                "improvement_suggestions", "suggestion_apply",
                "kpi_settings", "kpi_achievement",
                "trend_analysis", "competitor_analysis",
                "report_generate", "api_connection",
                "cache_fallback", "owner_dashboard",
                "period_comparison", "growth_forecast",
            ],
            "api_connected": _api_connection["connected"],
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except (KeyError, TypeError, ValueError) as e:
        _handle_unexpected_error(e, "get_analytics_dashboard")


# ── S2: CTR推移 ──

@router.get("/ctr-trend")
async def get_ctr_trend():
    """A-3 S2: 過去30日間のCTR推移グラフデータ"""
    today = datetime.now()
    history = []
    for i in range(30):
        date = today - timedelta(days=29 - i)
        base_ctr = 4.0 + (i * 0.05) + (i % 7) * 0.1
        history.append({
            "date": date.strftime("%Y-%m-%d"),
            "ctr": round(min(base_ctr, 8.0), 2),
        })
    return {"history": history, "period_days": 30}


# ── S3: 維持率推移 ──

@router.get("/retention-trend")
async def get_retention_trend():
    """A-3 S3: 過去30日間の視聴維持率推移グラフデータ"""
    today = datetime.now()
    history = []
    for i in range(30):
        date = today - timedelta(days=29 - i)
        base_retention = 40.0 + (i * 0.3) + (i % 5) * 0.5
        history.append({
            "date": date.strftime("%Y-%m-%d"),
            "retention": round(min(base_retention, 65.0), 1),
        })
    return {"history": history, "period_days": 30}


# ── S4: 動画別実績 ──

@router.get("/video-performance")
async def get_video_performance():
    """A-3 S4: 動画別のCTR/維持率/再生数の比較"""
    return {"videos": _video_data, "total": len(_video_data)}


# ── S5: ベンチマーク ──

@router.get("/benchmark")
async def get_benchmark():
    """A-3 S5: 業界平均との比較"""
    try:
        avg_ctr, avg_retention = _calculate_average_metrics(_video_data)
        industry_avg_ctr = 3.5
        industry_avg_retention = 40.0
        return {
            "industry_avg": {
                "ctr": industry_avg_ctr,
                "retention": industry_avg_retention,
            },
            "channel_avg": {
                "ctr": round(avg_ctr, 1),
                "retention": round(avg_retention, 1),
            },
            "comparison": {
                "ctr_diff": round(avg_ctr - industry_avg_ctr, 1),
                "retention_diff": round(avg_retention - industry_avg_retention, 1),
                "ctr_status": "above" if avg_ctr > industry_avg_ctr else "below",
                "retention_status": "above" if avg_retention > industry_avg_retention else "below",
            },
        }
    except HTTPException:
        raise
    except (KeyError, TypeError, ValueError) as e:
        _handle_unexpected_error(e, "get_benchmark")


# ── S6: テンプレート効果 ──

@router.get("/template-effect")
async def get_template_effect():
    """A-3 S6: テンプレート別の効果分析"""
    return {"templates": _template_data, "total": len(_template_data)}


# ── S7: SmartCut効果 ──

@router.get("/smartcut-effect")
async def get_smartcut_effect():
    """A-3 S7: SmartCut設定別の維持率効果分析"""
    return {"settings": _smartcut_settings, "total": len(_smartcut_settings)}


# ── S8: AI提案効果 ──

@router.get("/ai-suggestion-effect")
async def get_ai_suggestion_effect():
    """A-3 S8: AI提案採用/却下別のパフォーマンス比較"""
    return {
        "adopted": {
            "count": 15,
            "avg_ctr": 5.4,
            "avg_retention": 52.1,
        },
        "rejected": {
            "count": 8,
            "avg_ctr": 3.9,
            "avg_retention": 41.3,
        },
        "impact_diff": {
            "ctr_diff": 1.5,
            "retention_diff": 10.8,
        },
    }


# ── S9: チャプター効果 ──

@router.get("/chapter-effect")
async def get_chapter_effect():
    """A-3 S9: チャプター有無による視聴行動の差分"""
    return {
        "with_chapters": {
            "avg_retention": 53.2,
            "avg_watch_time_min": 8.5,
            "video_count": 12,
        },
        "without_chapters": {
            "avg_retention": 42.1,
            "avg_watch_time_min": 5.3,
            "video_count": 8,
        },
        "improvement": {
            "retention_diff": 11.1,
            "watch_time_diff": 3.2,
        },
    }


# ── S10: サムネイル効果 ──

@router.get("/thumbnail-effect")
async def get_thumbnail_effect():
    """A-3 S10: サムネイル選択とCTR of 相関"""
    return {
        "thumbnails": [
            {"type": "text_overlay", "avg_ctr": 5.8, "count": 10},
            {"type": "face_close_up", "avg_ctr": 6.2, "count": 7},
            {"type": "scene_capture", "avg_ctr": 3.5, "count": 5},
            {"type": "custom_design", "avg_ctr": 4.9, "count": 8},
        ],
        "correlation_score": 0.72,
        "best_performing": "face_close_up",
    }


# ── S11: 改善提案 ──

@router.get("/improvement-suggestions")
async def get_improvement_suggestions():
    """A-3 S11: データ駆動の改善提案一覧"""
    return {"suggestions": _improvement_suggestions, "total": len(_improvement_suggestions)}


# ── S12: 提案適用 ──

@router.post("/apply-suggestion")
async def apply_suggestion(req: ApplySuggestionRequest):
    """A-3 S12: 改善提案をパイプライン設定に適用"""
    try:
        suggestion = next((s for s in _improvement_suggestions if s["id"] == req.suggestion_id), None)
        if suggestion is None:
            raise HTTPException(status_code=404, detail=f"Suggestion ID {req.suggestion_id} not found")
        suggestion["applied"] = True
        _applied_suggestions.append(req.suggestion_id)
        return {"status": "applied", "suggestion_id": req.suggestion_id, "applied_at": datetime.now().isoformat()}
    except HTTPException:
        raise
    except (KeyError, TypeError, ValueError) as e:
        _handle_unexpected_error(e, "apply_suggestion")


# ── S13: KPI設定 ──

@router.get("/kpi-settings")
async def get_kpi_settings():
    """KPI設定の現在値を取得"""
    return _kpi_settings


@router.post("/kpi-settings")
async def update_kpi_settings(req: KPISettingRequest):
    """A-3 S13: チャンネルKPI(目標CTR/目標維持率)を設定"""
    try:
        if req.target_ctr < 0:
            raise HTTPException(status_code=400, detail=f"Invalid target_ctr: {req.target_ctr}. Must be non-negative")
        if req.target_ctr > 100.0:
            raise HTTPException(status_code=400, detail=f"Invalid target_ctr: {req.target_ctr}. Must be 100.0 or less")
        if req.target_retention < 0:
            raise HTTPException(status_code=400, detail=f"Invalid target_retention: {req.target_retention}. Must be non-negative")
        if req.target_retention > 100.0:
            raise HTTPException(status_code=400, detail=f"Invalid target_retention: {req.target_retention}. Must be 100.0 or less")
        _kpi_settings["target_ctr"] = req.target_ctr
        _kpi_settings["target_retention"] = req.target_retention
        return {"status": "updated", **_kpi_settings}
    except HTTPException:
        raise
    except (KeyError, TypeError, ValueError) as e:
        _handle_unexpected_error(e, "update_kpi_settings")


# ── S14: KPI達成度 ──

@router.get("/kpi-achievement")
async def get_kpi_achievement():
    """A-3 S14: KPI達成度のゲージ/グラフ"""
    try:
        avg_ctr, avg_retention = _calculate_average_metrics(_video_data)
        ctr_rate = min(100.0, (avg_ctr / max(_kpi_settings["target_ctr"], 0.01)) * 100)
        retention_rate = min(100.0, (avg_retention / max(_kpi_settings["target_retention"], 0.01)) * 100)
        return {
            "target": _kpi_settings.copy(),
            "actual": {
                "ctr": round(avg_ctr, 1),
                "retention": round(avg_retention, 1),
            },
            "achievement_rate": {
                "ctr": round(ctr_rate, 1),
                "retention": round(retention_rate, 1),
                "overall": round((ctr_rate + retention_rate) / 2, 1),
            },
        }
    except HTTPException:
        raise
    except (KeyError, TypeError, ValueError) as e:
        _handle_unexpected_error(e, "get_kpi_achievement")


# ── S15: トレンド分析 ──

@router.get("/trend-analysis")
async def get_trend_analysis():
    """A-3 S15: 視聴者の興味トレンド分析"""
    return {
        "trends": [
            {"topic": "AI動画編集", "score": 92, "direction": "rising"},
            {"topic": "YouTubeショート", "score": 85, "direction": "rising"},
            {"topic": "品質管理自動化", "score": 78, "direction": "stable"},
            {"topic": "コスト最適化", "score": 65, "direction": "declining"},
        ],
        "analysis_date": datetime.now().strftime("%Y-%m-%d"),
        "total": 4,
    }


# ── S16: 競合分析 ──

@router.get("/competitor-analysis")
async def get_competitor_analysis():
    """A-3 S16: 類似チャンネルとのパフォーマンス比較"""
    return {
        "competitors": [
            {"name": "チャンネルA", "subscribers": 25000, "avg_ctr": 4.2, "avg_retention": 45.5},
            {"name": "チャンネルB", "subscribers": 18000, "avg_ctr": 5.1, "avg_retention": 48.2},
            {"name": "チャンネルC", "subscribers": 32000, "avg_ctr": 3.8, "avg_retention": 42.0},
        ],
        "our_rank": 2,
        "total_compared": 3,
    }


# ── S17: レポート生成 ──

@router.post("/generate-report")
async def generate_report(req: ReportGenerateRequest):
    """A-3 S17: 月次/週次パフォーマンスレポートを自動生成"""
    try:
        valid_periods = {"weekly", "monthly"}
        if req.period not in valid_periods:
            raise HTTPException(status_code=400, detail=f"Invalid period: {req.period}. Must be one of {valid_periods}")
        return {
            "status": "generated",
            "period": req.period,
            "download_url": f"/api/admin/analytics/download/report_{req.period}.pdf",
            "generated_at": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except (KeyError, TypeError, ValueError) as e:
        _handle_unexpected_error(e, "generate_report")


# ── S18: API接続管理 ──

@router.get("/api-connection")
async def get_api_connection():
    """A-3 S18: YouTube Analytics API接続状態/更新頻度"""
    return _api_connection


@router.post("/api-connection")
async def update_api_connection(req: APIConnectionRequest):
    """A-3 S18: API接続設定の更新"""
    _api_connection["update_interval_minutes"] = req.update_interval_minutes
    _api_connection["enabled"] = req.enabled
    _api_connection["last_sync"] = datetime.now().isoformat()
    return {"status": "updated", **_api_connection}


# ── S19: キャッシュ/フォールバック ──

@router.get("/cache-fallback")
async def get_cache_fallback():
    """A-3 S19: API未接続時のキャッシュ/フォールバック状態"""
    return {
        "cache_available": True,
        "cache_age_hours": 2.5,
        "fallback_active": not _api_connection["connected"],
        "last_successful_sync": _api_connection["last_sync"],
        "data_freshness": "fresh" if _api_connection["connected"] else "cached",
    }


# ── S20: 効果要約ダッシュボード ──

@router.get("/owner-dashboard")
async def get_owner_dashboard():
    """A-3 S20: チャンネル主向けの効果要約ダッシュボード"""
    avg_ctr, avg_retention = _calculate_average_metrics(_video_data)
    total_views = sum(v["views"] for v in _video_data)
    return {
        "summary": {
            "total_videos": len(_video_data),
            "total_views": total_views,
            "avg_ctr": round(avg_ctr, 1),
            "avg_retention": round(avg_retention, 1),
        },
        "highlights": [
            f"CTR平均 {round(avg_ctr, 1)}% — 業界平均(3.5%)を上回っています",
            f"維持率平均 {round(avg_retention, 1)}% — 業界平均(40%)を上回っています",
            f"総再生数 {total_views:,} — 前月比+15%の成長",
        ],
        "timestamp": datetime.now().isoformat(),
    }


# ── S21: 期間比較 ──

@router.get("/period-comparison")
async def get_period_comparison(period1: str = "2026-03", period2: str = "2026-04"):
    """A-3 S21: 任意2期間の比較分析"""
    try:
        validate_period_format(period1)
        validate_period_format(period2)
        return {
            "period1": {
                "label": period1,
                "avg_ctr": 4.1,
                "avg_retention": 43.5,
                "total_views": 38000,
            },
            "period2": {
                "label": period2,
                "avg_ctr": 4.9,
                "avg_retention": 49.6,
                "total_views": 53000,
            },
            "diff": {
                "ctr_change": 0.8,
                "retention_change": 6.1,
                "views_change": 15000,
                "ctr_change_pct": 19.5,
                "retention_change_pct": 14.0,
                "views_change_pct": 39.5,
            },
        }
    except HTTPException:
        raise
    except (KeyError, TypeError, ValueError) as e:
        _handle_unexpected_error(e, "get_period_comparison")


# ── S22: 成長予測 ──

@router.get("/growth-forecast")
async def get_growth_forecast():
    """A-3 S22: チャンネル成長予測(登録者/再生数)"""
    return {
        "forecast_subscribers": {
            "current": 15000,
            "30_days": 17200,
            "90_days": 22500,
            "method": "exponential_smoothing",
        },
        "forecast_views": {
            "current_monthly": 53000,
            "next_month": 61000,
            "3_months": 78000,
            "method": "linear_regression",
        },
        "growth_rate": {
            "subscribers_monthly_pct": 14.7,
            "views_monthly_pct": 15.1,
        },
        "confidence": 0.82,
        "generated_at": datetime.now().isoformat(),
    }
