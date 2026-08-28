"""
Admin Channel Router — A-7 チャンネル主ダッシュボード管理

Admin UXストーリー A-7 に対応するバックエンドAPI。
22シーンのダッシュボード機能(チャンネル一覧/チャンネル詳細/効果サマリー/制作効率/
品質向上度/CTR改善率/維持率改善/ROI計算/チャンネル比較/最適化推奨/テンプレ推奨/
投稿スケジュール/ペース分析/コメント分析/競合ベンチ/成長予測/アラート設定/
レポート生成/Owner向けビュー/権限管理/連携設定)を提供する。

設計書: design_admin_a1_a7_full.md.resolved (推移表転記済み/)
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/channel", tags=["Admin Channel"])

# ── リクエストモデル ──

class PostScheduleItem(BaseModel):
    day: str
    time: str
    channel_id: Optional[str] = None
    type: Optional[str] = None


class ScheduleUpdateRequest(BaseModel):
    channel_id: str
    schedule: List[PostScheduleItem]


class TemplateRecommendRequest(BaseModel):
    channel_id: str
    genre: str = "tech"


class AlertSettingRequest(BaseModel):
    channel_id: str
    metric: str = "subscribers"
    threshold: float = 0.0
    condition: str = "below"


class ReportGenerateRequest(BaseModel):
    channel_id: str
    format: str = "pdf"
    period: str = "monthly"


# ── 状態管理 (インメモリ) ──

# **これは実在のチャンネルの数字ではない**（R1.5-C4・2026-08-27）。
# `subscribers` も `total_views` も `watch_time_hours: 15200` も固定値で、
# YouTube Analytics には一度も接続していない。**収益化の到達度をこの数字で
# 判断すると嘘になる**ので、返すときは `DATA_SOURCE` を必ず添える。
# 台帳: `backend/config/feature_gaps.json` の `channel_stats`
DATA_SOURCE = {
    "data_source": "sample",
    "is_real": False,
    "note": "**実在のチャンネルの数字ではありません。**YouTube Analytics には"
            "接続していません（未実装）。収益化の判断には使えません",
}

# **`connected` は `/youtube-connection` と揃える**（R1.5-C4）。
# 2026-08-28 まで、ここだけ `True` のままで、同じ router の
# `/youtube-connection` が `False` を返すという食い違いがあった。
_channels = [
    {"id": "ch-001", "name": "Antigravity Tech", "status": "active", "genre": "tech",
     "youtube_channel_id": "UC_xxxxx1", "subscribers": 12500, "total_views": 850000,
     "connected": False},
    {"id": "ch-002", "name": "AI Creative Studio", "status": "active", "genre": "creative",
     "youtube_channel_id": "UC_xxxxx2", "subscribers": 8200, "total_views": 420000,
     "connected": False},
    {"id": "ch-003", "name": "Dev Digest", "status": "paused", "genre": "education",
     "youtube_channel_id": "UC_xxxxx3", "subscribers": 3100, "total_views": 180000,
     "connected": False},
]

_permissions = {
    "roles": [
        {"name": "owner", "permissions": ["read", "write", "admin"]},
        {"name": "editor", "permissions": ["read", "write"]},
        {"name": "viewer", "permissions": ["read"]},
    ],
    "users": [
        {"user_id": "user-001", "channel_id": "ch-001", "role": "owner"},
        {"user_id": "user-002", "channel_id": "ch-001", "role": "editor"},
        {"user_id": "user-003", "channel_id": "ch-002", "role": "owner"},
    ],
}


# ── S1: ダッシュボード概要 ──

@router.get("/dashboard")
async def get_channel_dashboard():
    """A-7 S1: チャンネル管理ダッシュボードの全体情報"""
    active = [c for c in _channels if c["status"] == "active"]
    return {
        **DATA_SOURCE,
        "title": "チャンネル主ダッシュボード管理",
        "status": "healthy" if len(active) == len(_channels) else "partial",
        "summary": {
            "total_channels": len(_channels),
            "active_channels": len(active),
            "total_subscribers": sum(c["subscribers"] for c in _channels),
            "total_views": sum(c["total_views"] for c in _channels),
        },
        "sections": [
            "channels", "channel_detail", "effect_summary",
            "production_efficiency", "quality_improvement", "ctr_improvement",
            "retention_improvement", "roi", "channel_comparison",
            "optimization_recommendations", "template_recommendations",
            "post_schedule", "posting_pace", "comment_analysis",
            "competitor_benchmark", "growth_prediction",
            "alert_settings", "report", "owner_view",
            "permissions", "youtube_connection",
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── S2: チャンネル一覧 ──

@router.get("/channels")
async def get_channels():
    """A-7 S2: 管理対象チャンネルの一覧"""
    return {**DATA_SOURCE, "channels": _channels, "total": len(_channels)}


# ── S3: チャンネル詳細 ──

@router.get("/channels/{channel_id}")
async def get_channel_detail(channel_id: str):
    """A-7 S3: チャンネルのKPI/設定/実績"""
    ch = next((c for c in _channels if c["id"] == channel_id), None)
    if ch is None:
        raise HTTPException(status_code=404, detail=f"Channel {channel_id} not found")
    return {
        **DATA_SOURCE,
        **ch,
        "kpi": {
            "subscribers": ch["subscribers"],
            "views": ch["total_views"],
            # **固定値。** 実測ではない（R1.5-C4）
            "watch_time_hours": 15200,
            "avg_view_duration_seconds": 420,
            "engagement_rate": 4.8,
        },
        "settings": {
            "auto_optimize": True,
            "quality_gate_enabled": True,
            "smartcut_enabled": True,
        },
        "performance": {
            "videos_published": 45,
            "avg_views_per_video": 18888,
            "top_video_views": 125000,
        },
    }


# ── S4: 効果サマリー ──

@router.get("/effect-summary")
async def get_effect_summary():
    """A-7 S4: Antigravity導入前後の効果比較"""
    return {
        **DATA_SOURCE,
        "before": {"production_time_hours": 8.0, "quality_score": 72, "ctr_pct": 4.2, "retention_pct": 35},
        "after": {"production_time_hours": 2.5, "quality_score": 92, "ctr_pct": 6.8, "retention_pct": 52},
        "improvement_pct": {
            "production_time": 68.75,
            "quality": 27.78,
            "ctr": 61.90,
            "retention": 48.57,
        },
    }


# ── S5: 制作効率 ──

@router.get("/production-efficiency")
async def get_production_efficiency():
    """A-7 S5: 制作時間の短縮率"""
    return {
        **DATA_SOURCE,
        "reduction_pct": 68.75,
        "before_hours": 8.0,
        "after_hours": 2.5,
        "breakdown": {
            "transcription": {"before": 2.0, "after": 0.3, "reduction_pct": 85.0},
            "editing": {"before": 3.0, "after": 1.0, "reduction_pct": 66.7},
            "optimization": {"before": 2.0, "after": 0.5, "reduction_pct": 75.0},
            "review": {"before": 1.0, "after": 0.7, "reduction_pct": 30.0},
        },
    }


# ── S6: 品質向上度 ──

@router.get("/quality-improvement")
async def get_quality_improvement():
    """A-7 S6: 品質スコアの平均向上率"""
    return {
        **DATA_SOURCE,
        "average_improvement": 27.78,
        "trend": [
            {"month": "2026-02", "score": 72},
            {"month": "2026-03", "score": 80},
            {"month": "2026-04", "score": 88},
            {"month": "2026-05", "score": 92},
        ],
        "details": {
            "transcription_accuracy": {"before": 85, "after": 97},
            "audio_quality": {"before": 70, "after": 90},
            "metadata_quality": {"before": 60, "after": 88},
        },
    }


# ── S7: CTR改善率 ──

@router.get("/ctr-improvement")
async def get_ctr_improvement():
    """A-7 S7: AI最適化によるCTR改善率"""
    return {
        **DATA_SOURCE,
        "improvement_pct": 61.90,
        "before": 4.2,
        "after": 6.8,
        "factors": [
            {"name": "サムネイル最適化", "contribution_pct": 35},
            {"name": "タイトル最適化", "contribution_pct": 40},
            {"name": "説明文最適化", "contribution_pct": 25},
        ],
    }


# ── S8: 維持率改善 ──

@router.get("/retention-improvement")
async def get_retention_improvement():
    """A-7 S8: SmartCut/品質ゲートによる維持率改善"""
    return {
        **DATA_SOURCE,
        "improvement_pct": 48.57,
        "before": 35,
        "after": 52,
        "smartcut_impact": 65,
        "quality_gate_impact": 35,
        "avg_watch_time_increase_pct": 42.0,
    }


# ── S9: ROI計算 ──

@router.get("/roi")
async def get_roi():
    """A-7 S9: API費用 vs 効果のROI計算"""
    return {
        **DATA_SOURCE,
        "roi_ratio": 5.2,
        "cost": {"api_monthly_usd": 45, "compute_monthly_usd": 30, "total_monthly_usd": 75},
        "benefit": {"time_saved_hours": 22, "time_value_usd": 330, "additional_revenue_usd": 60},
        "payback_period_months": 0.19,
    }


# ── S10: チャンネル比較 ──

@router.get("/channel-comparison")
async def get_channel_comparison():
    """A-7 S10: 複数チャンネル間のパフォーマンス比較"""
    return {
        **DATA_SOURCE,
        "comparisons": [
            {"channel_id": "ch-001", "name": "Antigravity Tech", "subscribers": 12500, "ctr": 6.8, "retention": 52, "quality_score": 92},
            {"channel_id": "ch-002", "name": "AI Creative Studio", "subscribers": 8200, "ctr": 5.9, "retention": 48, "quality_score": 88},
            {"channel_id": "ch-003", "name": "Dev Digest", "subscribers": 3100, "ctr": 4.5, "retention": 40, "quality_score": 85},
        ],
        "metrics": ["subscribers", "ctr", "retention", "quality_score"],
        "best_performer": "ch-001",
    }


# ── S11: 最適化推奨 ──

@router.get("/optimization-recommendations")
async def get_optimization_recommendations():
    """A-7 S11: チャンネル固有の最適化推奨"""
    return {
        **DATA_SOURCE,
        "recommendations": [
            {"id": 1, "priority": "high", "title": "投稿頻度の増加(週2→週3)", "channel_id": "ch-002", "expected_impact": "登録者+15%"},
            {"id": 2, "priority": "medium", "title": "サムネイルA/Bテストの導入", "channel_id": "ch-001", "expected_impact": "CTR+8%"},
            {"id": 3, "priority": "low", "title": "コミュニティタブの活用", "channel_id": "ch-003", "expected_impact": "エンゲージメント+20%"},
        ],
        "prioritized_count": 3,
    }


# ── S12: テンプレ推奨 ──

@router.get("/template-recommendations")
async def get_template_recommendations():
    """A-7 S12: テンプレート推奨一覧"""
    return {
        **DATA_SOURCE,
        "templates": [
            {"id": "tpl-001", "name": "Tech Tutorial", "genre_match": 95, "usage_count": 12},
            {"id": "tpl-002", "name": "Product Review", "genre_match": 88, "usage_count": 8},
            {"id": "tpl-003", "name": "News Digest", "genre_match": 75, "usage_count": 5},
        ],
        "genre_match": "tech",
    }


@router.post("/template-recommend")
async def recommend_template(req: TemplateRecommendRequest):
    """A-7 S12: ジャンル別テンプレ推奨"""
    return {
        **DATA_SOURCE,
        "status": "recommended",
        "channel_id": req.channel_id,
        "genre": req.genre,
        "recommended_template": "tpl-001",
        "match_score": 95,
    }


# ── S13: 投稿スケジュール ──

@router.get("/post-schedule")
async def get_post_schedule():
    """A-7 S13: 投稿スケジュールの一覧"""
    return {
        **DATA_SOURCE,
        "schedule": [
            {"day": "Monday", "time": "18:00", "channel_id": "ch-001", "type": "tutorial"},
            {"day": "Thursday", "time": "18:00", "channel_id": "ch-001", "type": "review"},
            {"day": "Wednesday", "time": "12:00", "channel_id": "ch-002", "type": "creative"},
            {"day": "Saturday", "time": "10:00", "channel_id": "ch-002", "type": "shorts"},
        ],
        "next_post": {"channel_id": "ch-001", "scheduled_at": "2026-05-05T18:00:00", "type": "tutorial"},
    }


@router.post("/post-schedule")
async def update_post_schedule(req: ScheduleUpdateRequest):
    """A-7 S13: 投稿スケジュールの更新"""
    return {**DATA_SOURCE, "status": "updated", "channel_id": req.channel_id,
            "schedule": req.schedule}


# ── S14: ペース分析 ──

@router.get("/posting-pace")
async def get_posting_pace():
    """A-7 S14: 投稿ペースの達成度"""
    return {
        **DATA_SOURCE,
        "target": {"posts_per_week": 2},
        "actual": {"posts_per_week": 1.8, "posts_this_month": 7},
        "achievement_pct": 90.0,
        "streak_days": 14,
    }


# ── S15: コメント分析 ──

@router.get("/comment-analysis")
async def get_comment_analysis():
    """A-7 S15: コメントのセンチメント/リクエスト分析"""
    return {
        **DATA_SOURCE,
        "sentiment": {"positive": 72, "neutral": 20, "negative": 8},
        "requests": [
            {"topic": "チュートリアルの続編", "count": 15},
            {"topic": "字幕の改善", "count": 8},
            {"topic": "ショート動画", "count": 12},
        ],
        "top_topics": ["AI", "自動化", "品質", "効率化"],
        "total_comments_analyzed": 450,
    }


# ── S16: 競合ベンチ ──

@router.get("/competitor-benchmark")
async def get_competitor_benchmark():
    """A-7 S16: 同ジャンル競合チャンネルとのベンチマーク"""
    return {
        **DATA_SOURCE,
        "channel_id": "ch-001",
        "genre": "tech",
        "benchmarks": [
            {"name": "Competitor A", "subscribers": 25000, "avg_views": 35000, "ctr": 5.5},
            {"name": "Competitor B", "subscribers": 18000, "avg_views": 22000, "ctr": 4.8},
            {"name": "Your Channel", "subscribers": 12500, "avg_views": 18888, "ctr": 6.8},
        ],
        "ranking": {"subscribers": 3, "ctr": 1, "avg_views": 3},
    }


# ── S17: 成長予測 ──

@router.get("/growth-prediction")
async def get_growth_prediction():
    """A-7 S17: チャンネル成長予測"""
    return {
        **DATA_SOURCE,
        "channel_id": "ch-001",
        "predictions": {
            "subscribers_3m": 15000,
            "subscribers_6m": 20000,
            "subscribers_12m": 35000,
            "views_monthly_3m": 95000,
            "views_monthly_6m": 140000,
        },
        # **存在しない推論を自称しない**（R1.5-C4）。`linear_regression_v2`
        # という模型はどこにも無く、上の数字は固定値
        "confidence": None,
        "model": None,
        "method": "fixed_sample",
    }


# ── S18: アラート設定 ──

@router.get("/alert-settings")
async def get_alert_settings():
    """A-7 S18: アラート閾値の一覧"""
    return {
        **DATA_SOURCE,
        "alerts": [
            {"channel_id": "ch-001", "metric": "ctr", "threshold": 3.0, "condition": "below"},
            {"channel_id": "ch-001", "metric": "quality_score", "threshold": 80, "condition": "below"},
        ],
        "total": 2,
    }


@router.post("/alert-settings")
async def update_alert_settings(req: AlertSettingRequest):
    """A-7 S18: アラート閾値の設定"""
    return {
        **DATA_SOURCE,
        "status": "configured",
        "channel_id": req.channel_id,
        "metric": req.metric,
        "threshold": req.threshold,
        "condition": req.condition,
    }


# ── S19: レポート生成 ──

@router.post("/generate-report")
async def generate_report(req: ReportGenerateRequest):
    """A-7 S19: チャンネル別月次レポートの生成"""
    return {
        **DATA_SOURCE,
        "status": "generated",
        "channel_id": req.channel_id,
        "format": req.format,
        "period": req.period,
        "download_url": f"/api/admin/channel/download/report_{req.channel_id}.{req.format}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── S20: Owner向けビュー ──

@router.get("/owner-view")
async def get_owner_view():
    """A-7 S20: チャンネル主向け簡易ダッシュボード設定"""
    return {
        **DATA_SOURCE,
        "enabled": True,
        "visible_sections": ["kpi", "posting_pace", "quality_score", "next_post"],
        "theme": "light",
        "customizable": True,
    }


# ── S21: 権限管理 ──

@router.get("/permissions")
async def get_permissions():
    """A-7 S21: チャンネル主ごとの権限設定"""
    return {**DATA_SOURCE, **_permissions}


# ── S22: YouTube API連携 ──

@router.get("/youtube-connection")
async def get_youtube_connection():
    """A-7 S22: YouTube API接続/チャンネルID連携

    **接続していないので `connected: false` を返す**（R1.5-C4）。
    2026-08-28 まで `connected: true` と**現在時刻の `last_sync`** を
    返していた。同じファイルの `DATA_SOURCE` が「接続していません」と
    書いているのに、この 1 本だけ逆のことを言っていた。
    現在時刻を返すのが特に悪く、**いま同期したように見える。**
    """
    return {
        **DATA_SOURCE,
        "connected": False,
        "channel_id": None,
        "api_key": None,
        "scopes": ["youtube.readonly", "youtube.upload"],
        "last_sync": None,
        "quota_used_today": 0,
        "quota_limit": 10000,
    }
