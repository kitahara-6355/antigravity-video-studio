"""
API バージョニング — /api/v1/ プレフィクス化（U-19）

設計方針:
- 既存の全ルーターを /api/v1/ 配下にマウント
- 旧 /api/ エンドポイントは下位互換のためそのまま残す
- 将来 v2 追加時は v2_router.py を作成して app に追加するだけ

使い方:
    # main.py
    from api_versioning import v1_router
    app.include_router(v1_router)
"""

import logging
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

# themes_router.py が template_config から template_constants の定数をインポートしようとする
# インポートエラーを回避するための動的注入
try:
    import template_config
    import template_constants
    if not hasattr(template_config, "PRODUCTION_TEMPLATES"):
        template_config.PRODUCTION_TEMPLATES = template_constants.PRODUCTION_TEMPLATES
    if not hasattr(template_config, "MOOD_THEMES"):
        template_config.MOOD_THEMES = template_constants.MOOD_THEMES
    if not hasattr(template_config, "RECOMMENDED_COMBOS"):
        template_config.RECOMMENDED_COMBOS = template_constants.RECOMMENDED_COMBOS
except Exception as inject_err:
    logger.error(f"Failed to inject template constants to template_config: {inject_err}")


# ============================================================
# v1 ルーター — 全エンドポイントを /api/v1/ にマウント
# ============================================================
v1_router = APIRouter(prefix="/api/v1", tags=["v1"])


def register_v1_routes(v1: APIRouter):
    """
    既存ルーターを v1 プレフィクス配下に再マウント

    各ルーターの既存 prefix をそのまま保持しつつ、
    /api/v1/quality/... のように階層化される。
    """
    try:
        from routers import (
            quality_router,
            collaboration_router,
            preview_router,
            usage_router,
            youtube_optimizer_router,
            smartcut_router,
            shorts_router,
            youtube_upload_router,
            pipeline_router,
        )
        from routers.themes_router import router as themes_router
        from routers.soul_router import router as soul_router
        from mcp_server import create_mcp_router

        # コア API
        v1.include_router(quality_router)
        v1.include_router(collaboration_router)
        v1.include_router(preview_router)

        # 使用量管理
        v1.include_router(usage_router)

        # YouTube / SmartCut
        v1.include_router(youtube_optimizer_router)
        v1.include_router(smartcut_router)
        v1.include_router(shorts_router)
        v1.include_router(youtube_upload_router)

        # パイプライン
        v1.include_router(pipeline_router)

        # バッチ5 新規
        v1.include_router(themes_router)      # U-13: テーマ選択
        v1.include_router(soul_router)        # U-09: Soul Passport
        v1.include_router(create_mcp_router())  # U-12: MCP Server
    except HTTPException:
        raise
    except Exception as e:
        # 新規 except Exception に対する TDR 自動登録
        try:
            from agents.memory.technical_debt import TechnicalDebtStore
            store = TechnicalDebtStore()
            store.register_debt(
                category="CRITICAL_ROUTER",
                file_path="api_versioning.py",
                line_number=87,  # except Exception as e: の行番号
                pattern="except Exception as e:",
                cause_pattern="DP-01",
                fix_pattern="except HTTPException: raise を前行に配置",
                registered_by="bug_hunter_t_batch_9d1432",
                notes=f"Auto-registered: API v1 router mounting crashed. Error: {str(e)}",
                tags=["api_versioning", "mounting_failure"]
            )
        except Exception as tdr_err:
            logger.error(f"Failed to register technical debt for mounting error: {tdr_err}")
        logger.error(f"Failed to register v1 routes: {e}")
        raise e


register_v1_routes(v1_router)


def _get_version_metadata():
    """内部用のバージョンメタデータ取得関数（テストでの例外シミュレーション用）"""
    return {
        "api_version": "v1",
        "app_version": "5.0.0",
        "codename": "Trinity",
        "supported_versions": ["v1"],
        "deprecations": [],
    }


# ============================================================
# バージョン情報エンドポイント
# ============================================================

@v1_router.get("/version")
async def get_api_version():
    """API バージョンとメタ情報を返す"""
    try:
        return _get_version_metadata()
    except HTTPException:
        raise
    except Exception as e:
        # 新規 except Exception に対する TDR 自動登録
        try:
            from agents.memory.technical_debt import TechnicalDebtStore
            store = TechnicalDebtStore()
            store.register_debt(
                category="CRITICAL_ROUTER",
                file_path="api_versioning.py",
                line_number=134,  # except Exception as e: の行番号
                pattern="except Exception as e:",
                cause_pattern="DP-01",
                fix_pattern="except HTTPException: raise を前行に配置",
                registered_by="bug_hunter_t_batch_9d1432",
                notes=f"Auto-registered: Version endpoint failed. Error: {str(e)}",
                tags=["api_versioning", "version_endpoint"]
            )
        except Exception as tdr_err:
            logger.error(f"Failed to register technical debt for version endpoint error: {tdr_err}")
        logger.error(f"Error in get_api_version: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# サムネイル生成・品質検証ロジック (Phase 27)
# ============================================================

def _create_thumbnail_image(width: int, height: int, text: str):
    """PillowのImageオブジェクトを生成する（入力バリデーションを含む）"""
    from PIL import Image, ImageDraw

    if not isinstance(text, str):
        raise TypeError("Text must be a string")
    if not text.strip():
        raise ValueError("Text must not be empty or whitespace only")
    if len(text) > 100:
        raise ValueError("Text length must not exceed 100 characters")

    try:
        width = int(width)
        height = int(height)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Width and height must be integers: {e}")
        
    if width <= 0 or height <= 0:
        raise ValueError(f"Width and height must be positive integers. Got {width}x{height}")

    img = Image.new("RGB", (width, height), color=(73, 109, 137))
    d = ImageDraw.Draw(img)
    d.text((10, 10), text, fill=(255, 255, 0))
    return img


def _save_image_atomically(img, output_path):
    """画像を一時ファイルに保存後、アトミックにrenameして保存する"""
    import uuid
    from pathlib import Path

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        img.save(temp_path, "PNG")
        
        if output_path.exists():
            output_path.unlink()
        temp_path.rename(output_path)
    except OSError as e:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        logger.error(f"Failed to generate thumbnail atomically: {e}")
        raise
        
    return output_path


def generate_api_thumbnail(
    output_path,
    width: int = 1280,
    height: int = 720,
    text: str = "ApiVersioning Thumbnail"
):
    """Pillowを使用して、指定された解像度とテキストでサムネイル画像を生成する (原子的な書き込み)"""
    img = _create_thumbnail_image(width, height, text)
    return _save_image_atomically(img, output_path)


def _validate_thumbnail_file_attributes(file_path):
    """ファイルが存在し、サイズ制限（4MB）を満たしているか検証する"""
    from pathlib import Path
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Thumbnail file not found: {file_path}")
        
    size_bytes = file_path.stat().st_size
    if size_bytes >= 4 * 1024 * 1024:
        raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")
    return size_bytes


def _verify_and_load_image(file_path):
    """Pillowで画像を開き、破損していないことをロード確認する"""
    from PIL import Image
    try:
        with Image.open(file_path) as img:
            img.verify()
    except (IOError, SyntaxError) as e:
        raise ValueError(f"Image is corrupted or invalid format: {e}")
        
    try:
        with Image.open(file_path) as img:
            img.load()  # ピクセルデータのロードを強制
            width, height = img.size
            return width, height
    except (IOError, SyntaxError) as e:
        raise ValueError(f"Image is corrupted or invalid format: {e}")


def _validate_image_dimensions(width: int, height: int):
    """解像度が1280x720以上かつアスペクト比が16:9であるか検証する"""
    if width < 1280 or height < 720:
        raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
        
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 0.01:
        raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")


def validate_api_thumbnail(file_path) -> dict:
    """
    サムネイル画像の品質要件を検証する
    """
    size_bytes = _validate_thumbnail_file_attributes(file_path)
    width, height = _verify_and_load_image(file_path)
    _validate_image_dimensions(width, height)
        
    return {
        "path": str(file_path),
        "width": width,
        "height": height,
        "size_bytes": size_bytes
    }


async def resolve_api_thumbnail_task(task_id: str) -> str:
    """
    StageBoundAgent の process_func として動作する非同期タスク処理
    """
    import json
    from pathlib import Path
    output_dir = Path("backend/temp_thumbnails")
    output_path = output_dir / f"api_versioning_{task_id}.png"
    
    generate_api_thumbnail(output_path, width=1280, height=720, text=f"ApiVersioning {task_id}")
    result_info = validate_api_thumbnail(output_path)
    return json.dumps(result_info)


from pydantic import BaseModel

class ThumbnailGenerateRequest(BaseModel):
    task_id: str
    text: str = "ApiVersioning Thumbnail"
    width: int = 1280
    height: int = 720


@v1_router.post("/thumbnail/generate")
async def generate_v1_thumbnail(req: ThumbnailGenerateRequest):
    """
    サムネイル画像を生成・検証し、結果を返す
    """
    from fastapi import HTTPException
    from pathlib import Path
    try:
        output_dir = Path("backend/temp_thumbnails")
        output_path = output_dir / f"api_versioning_{req.task_id}.png"
        generate_api_thumbnail(
            output_path,
            width=req.width,
            height=req.height,
            text=req.text
        )
        result_info = validate_api_thumbnail(output_path)
        return {"status": "success", "result": result_info}
    except HTTPException:
        raise
    except Exception as e:
        # 新規 except Exception に対する TDR 自動登録
        try:
            from agents.memory.technical_debt import TechnicalDebtStore
            store = TechnicalDebtStore()
            store.register_debt(
                category="CRITICAL_ROUTER",
                file_path="api_versioning.py",
                line_number=325,
                pattern="except Exception as e:",
                cause_pattern="DP-01",
                fix_pattern="except HTTPException: raise を前行に配置",
                registered_by="bug_hunter_t_batch_9d1432",
                notes=f"Auto-registered: Thumbnail endpoint failed. Error: {str(e)}",
                tags=["api_versioning", "thumbnail_endpoint"]
            )
        except Exception as tdr_err:
            logger.error(f"Failed to register technical debt for thumbnail endpoint error: {tdr_err}")
        logger.error(f"Error in generate_v1_thumbnail: {e}")
        raise HTTPException(status_code=500, detail=str(e))
