"""
Antigravity Video Studio — Main Application Entry Point

Phase C リファクタリング: ルーター登録パターンを1種類に統一
全エンドポイントを routers/ 配下のモジュールに移行済み。
このファイルの責務は:
1. FastAPI アプリケーション初期化
2. CORS ミドルウェア設定
3. ルーター登録（統一パターン: from routers import + app.include_router）
4. サーバー起動
"""

import os
import logging
import asyncio
import sqlite3
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# .envファイルのロード
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(ENV_PATH)


class StructuredJSONFormatter(logging.Formatter):
    """テレビ局放送技術部要件: 5分以内の障害原因特定を支援する構造化ログ"""

    def format(self, record):
        import json as _json
        log_entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id
        return _json.dumps(log_entry, ensure_ascii=False)


def setup_logging():
    """ロギング設定の初期化。StructuredJSONFormatter と標準出力ハンドラを設定。"""
    # すでにルートロガーにハンドラが設定されている場合は、多重登録を防ぎResourceWarningを回避する
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # ファイルハンドラ: JSON構造化ログ（障害解析用）
    file_handler = logging.FileHandler(log_dir / 'backend.log')
    file_handler.setFormatter(StructuredJSONFormatter())

    # コンソールハンドラ: 従来の人間可読フォーマット
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))

    logging.basicConfig(
        level=logging.INFO,
        handlers=[file_handler, console_handler]
    )


# ログセットアップを実行
setup_logging()
logger = logging.getLogger(__name__)


# ============================================
# Claude Code KAIROS統合: TickLoop バックグラウンド起動
# ============================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan イベント。
    サーバー起動時に TickLoop（KAIROS型常駐監視）をバックグラウンドで起動し、
    サーバー停止時に安全に終了する。
    """
    tick_task = None
    tick_loop = None
    try:
        from agents.tick_loop import tick_loop as _tick_loop
        tick_loop = _tick_loop
        tick_task = asyncio.create_task(tick_loop.start())
        logger.info("🫀 TickLoop (KAIROS) バックグラウンド起動完了")
    except ImportError:
        logger.warning("⚠️ TickLoop 未インストール — バックグラウンド監視なし")
    except (TypeError, ValueError, AttributeError, RuntimeError) as e:
        logger.error(f"TickLoop 起動エラー: {e}")

    # U-11: DIコンテナ初期化
    try:
        from service_container import setup_services
        setup_services()
        logger.info("📦 ServiceContainer 初期化完了")
    except (KeyError, ValueError, TypeError, AttributeError, sqlite3.Error, OSError, RuntimeError) as e:
        logger.warning(f"ServiceContainer init skipped: {e}")

    # Harness（Anthropic推奨パターン）初期化
    harness_active = False
    try:
        from harness.hooks import hook_system
        hook_system.register_builtin_hooks()
        harness_active = True
        logger.info("🪝 Harness Hook システム初期化完了")
    except ImportError:
        logger.info("Harness 未インストール — レガシーモードで動作")
    except (KeyError, ValueError, TypeError, AttributeError, RuntimeError) as e:
        logger.warning(f"Harness init skipped: {e}")

    # ModelGovernance — ハーネス統合型モデルガバナンス
    # deprecated モデルの実行時自動差替 (PreToolUse Hook)
    try:
        from model_governance import register_governance_hook
        register_governance_hook()
    except (ValueError, TypeError, AttributeError, RuntimeError) as e:
        logger.debug(f"ModelGovernance skipped: {e}")

    yield  # アプリケーション稼働中

    # シャットダウン
    if harness_active:
        try:
            from harness.governance import governance_engine
            governance_engine.flush_traces()
            logger.info("📊 Harness トレースフラッシュ完了")
        except (ValueError, TypeError, AttributeError, RuntimeError, OSError):
            pass

    if tick_task and tick_loop:
        try:
            await tick_loop.stop()
            logger.info("🫀 TickLoop 安全停止完了")
        except (ValueError, TypeError, AttributeError, OSError, RuntimeError) as e:
            logger.error(f"TickLoop 停止エラー: {e}")


def configure_cors(app: FastAPI) -> None:
    """CORS設定（SC-01: 環境変数ベースで制御）"""
    cors_origins_raw = os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:5173,http://localhost:5174,http://localhost:5175,http://localhost:3000"
    )
    cors_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Range", "Content-Length"],
    )


def register_all_routers(app: FastAPI) -> None:
    """すべての API ルーターを FastAPI アプリケーションに登録する"""
    from routers.usage_router import thumbnail_router as usage_thumbnail_router
    from routers import (
        # --- v4.0 コアルーター ---
        trinity_router,
        director_router,
        segments_router,
        render_router,
        quality_router,
        collaboration_router,
        websocket_router,
        preview_router,
        # --- Phase 50: 無料枠最適化 ---
        usage_router,
        # --- Phase 51: YouTube最適化 & SmartCut ---
        youtube_optimizer_router,
        smartcut_router,
        ab_test_tracker_router,
        shorts_router,
        youtube_upload_router,
        # --- Phase 30/23: Antigravity 3.0 & Manager ---
        antigravity_router,
        manager_router,
        # --- Phase 9以前: 既存ルーター ---
        soul_router,
        dashboard_router,
        approval_router,
        philosophy_router,
        # --- ログ & エラーレポート ---
        log_router,
        error_router,
        # --- Legacy: ユニークエンドポイント残存 ---
        legacy_director_router,
        legacy_council_router,
        legacy_production_router,
        legacy_management_router,
        # --- WebSocket: Live API ---
        live_ws_router,
        # --- Phase D/G1: ProductionPipeline ---
        pipeline_router,
        # --- 実稼働準備: ヘルスチェック ---
        health_router,
        # --- パイプラインレポート ---
        pipeline_report_router,
        # --- Phase 3: Admin保証 (M3.3) ---
        admin_setup_router,
        admin_quota_router,
        admin_analytics_router,
        admin_quality_router,
        admin_incident_router,
        admin_integration_router,
        admin_channel_router,
        # --- Sprint 4.4.2: Performance Dashboard ---
        admin_performance_router,
        # --- DS-12: テーマ ---
        themes_router,
    )

    # v4.0 コアルーター
    app.include_router(trinity_router)
    app.include_router(director_router)
    app.include_router(segments_router)
    app.include_router(render_router)
    app.include_router(quality_router)
    app.include_router(collaboration_router)
    app.include_router(websocket_router)
    app.include_router(preview_router)

    # Phase 50/51
    app.include_router(usage_router)
    app.include_router(usage_thumbnail_router)
    app.include_router(youtube_optimizer_router)
    app.include_router(smartcut_router)
    app.include_router(ab_test_tracker_router)
    app.include_router(shorts_router)
    app.include_router(youtube_upload_router)

    # Phase 30/23
    app.include_router(antigravity_router)
    app.include_router(manager_router)

    # Phase 9以前
    app.include_router(soul_router)
    app.include_router(dashboard_router)
    app.include_router(approval_router)
    app.include_router(philosophy_router)

    # DS-12: テーマ
    app.include_router(themes_router)

    # ログ & エラーレポート
    app.include_router(log_router)
    app.include_router(error_router)

    # Legacy: ユニークエンドポイント残存分
    app.include_router(legacy_director_router)
    app.include_router(legacy_council_router)
    app.include_router(legacy_production_router)
    app.include_router(legacy_management_router)

    # WebSocket: Live API
    app.include_router(live_ws_router)

    # Phase D/G1: ProductionPipeline
    app.include_router(pipeline_router)

    # 実稼働準備: ヘルスチェック
    app.include_router(health_router)

    # パイプラインレポート
    app.include_router(pipeline_report_router)

    # Phase 3: Admin保証 (M3.3)
    app.include_router(admin_setup_router)
    app.include_router(admin_quota_router)
    app.include_router(admin_analytics_router)
    app.include_router(admin_quality_router)
    app.include_router(admin_incident_router)
    app.include_router(admin_integration_router)
    app.include_router(admin_channel_router)

    # Sprint 4.4.2: Performance Dashboard API
    app.include_router(admin_performance_router)

    # U-19: API バージョニング— /api/v1/ プレフィクス
    try:
        from api_versioning import v1_router
        app.include_router(v1_router)
        logger.info("🏷️ API v1 バージョニング有効")
    except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as e:
        logger.warning(f"API versioning skipped: {e}")


# ============================================
# FastAPI アプリケーション初期化
# ============================================
app = FastAPI(
    title="Antigravity Video Studio Backend",
    lifespan=lifespan,
)

# CORS設定適用
configure_cors(app)

# エラーハンドラ登録
try:
    from routers.error_schemas import register_error_handlers
    register_error_handlers(app)
    logger.info("🚨 統一エラーレスポンス形式を登録完了")
except (ImportError, ValueError, TypeError, AttributeError, RuntimeError) as e:
    logger.warning(f"Error handlers registration skipped: {e}")

# ルーター登録
register_all_routers(app)


# ============================================
# エントリーポイント
# ============================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
