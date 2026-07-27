"""
Routers Package — FastAPIルーターの集約 (Phase C 統一パターン)

全ルーターをここから一括エクスポート。
main.py は `from routers import XXX_router` のみ使用。
"""

# ============================================
# v4.0 コアルーター
# ============================================
from .trinity import router as trinity_router
from .director import router as director_router
from .segments import router as segments_router
from .render import router as render_router
from .quality import router as quality_router
from .collaboration import router as collaboration_router
from .websocket import router as websocket_router
from .preview import router as preview_router

# ============================================
# Phase 50: 無料枠最適化
# ============================================
from .usage_router import router as usage_router

# ============================================
# Phase 51: YouTube最適化 & SmartCut
# ============================================
from .youtube_optimizer import router as youtube_optimizer_router
from .smartcut import router as smartcut_router
from .ab_test_tracker import router as ab_test_tracker_router
from .shorts import router as shorts_router
from .youtube_upload import router as youtube_upload_router

# ============================================
# Phase 30: Antigravity 3.0 API
# ============================================
from antigravity_api import router as antigravity_router

# ============================================
# Phase 23: Manager Monitoring
# ============================================
from manager_monitoring import router as manager_router

# ============================================
# Phase 9以前: 既存ルーター
# ============================================
from .soul_router import router as soul_router
from .dashboard_router import router as dashboard_router
from .approval_router import router as approval_router
from .philosophy_router import router as philosophy_router

# ============================================
# DS-12: テーマルーター
# ============================================
from .themes_router import router as themes_router

# ============================================
# Phase 6前: Legacy ルーター（ユニークエンドポイント残存分）
# ============================================
from .legacy_director_router import router as legacy_director_router
from .legacy_council_router import router as legacy_council_router
from .legacy_production_router import router as legacy_production_router
from .legacy_management_router import router as legacy_management_router

# WebSocket: Live API
from .legacy_live_websocket import router as live_ws_router

# ============================================
# Phase D/G1: ProductionPipeline
# ============================================
from .pipeline_router import router as pipeline_router

# ============================================
# 実稼働準備: ヘルスチェック
# ============================================
from .health import router as health_router
from .pipeline_report import router as pipeline_report_router

# ============================================
# Phase 3: Admin保証 (M3.3)
# ============================================
from .admin_setup_router import router as admin_setup_router
from .admin_setup_router import perf_router as admin_performance_router
from .admin_quota_router import router as admin_quota_router
from .admin_analytics_router import router as admin_analytics_router
from .admin_quality_router import router as admin_quality_router
from .admin_incident_router import router as admin_incident_router
from .admin_integration_router import router as admin_integration_router
from .admin_channel_router import router as admin_channel_router

# ============================================
# ログ & エラーレポート
# ============================================
from log_manager import router as log_router
from error_reporter import router as error_router

__all__ = [
    # v4.0 コア
    "trinity_router", "director_router", "segments_router",
    "render_router", "quality_router", "collaboration_router",
    "websocket_router", "preview_router",
    # Phase 50
    "usage_router",
    # Phase 51
    "youtube_optimizer_router", "smartcut_router", "ab_test_tracker_router",
    "shorts_router", "youtube_upload_router",
    # Phase 30/23
    "antigravity_router", "manager_router",
    # Phase 9以前
    "soul_router", "dashboard_router", "approval_router", "philosophy_router",
    # DS-12: テーマ
    "themes_router",
    # Legacy
    "legacy_director_router", "legacy_council_router",
    "legacy_production_router", "legacy_management_router",
    "live_ws_router",
    # ログ
    "log_router", "error_router",
    # Pipeline
    "pipeline_router",
    # Health
    "health_router",
    # Pipeline Report
    "pipeline_report_router",
    # Admin (M3.3)
    "admin_setup_router",
    "admin_quota_router",
    "admin_analytics_router",
    "admin_quality_router",
    "admin_incident_router",
    "admin_integration_router",
    "admin_channel_router",
    "admin_performance_router",
    "soul_router",
]
