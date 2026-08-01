"""
SmartCut Router - スマートカットAPIエンドポイント

実装計画準拠:
- /api/smartcut/init: 初期化
- /api/smartcut/recommend: 尺に応じた推奨取得
- /api/smartcut/lock: シーンを固定
- /api/smartcut/unlock: 固定解除
- /api/smartcut/all-candidates: 全候補取得
- /api/smartcut/finalize: 最終構成確定
"""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/smartcut", tags=["SmartCut"])


class SegmentInput(BaseModel):
    """セグメント入力情報"""
    id: Optional[str] = None
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    text: str = ""
    score: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_times(self) -> "SegmentInput":
        if self.start >= self.end:
            raise ValueError("start must be less than end")
        return self


class InitRequest(BaseModel):
    """初期化リクエスト"""
    segments: List[SegmentInput]
    opening_duration: float = Field(default=10.0, ge=0.0)
    ending_duration: float = Field(default=20.0, ge=0.0)


class RecommendRequest(BaseModel):
    """推奨取得リクエスト"""
    target_duration_minutes: int  # 15, 30, 45, 60


class LockRequest(BaseModel):
    """固定リクエスト"""
    segment_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    start_time: float = Field(ge=0.0)
    end_time: float = Field(ge=0.0)
    reason: str = ""

    @model_validator(mode="after")
    def validate_times(self) -> "LockRequest":
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be less than end_time")
        return self


class UnlockRequest(BaseModel):
    """固定解除リクエスト"""
    segment_id: str


# グローバルインスタンス
_smart_cut_instance = None


async def _safe_sqlite_query(db_path: str, query: str, params: tuple = (), is_select: bool = False, retries: int = 3) -> Any:
    import sqlite3
    import asyncio
    last_err = None
    for attempt in range(retries):
        conn = None
        try:
            conn = sqlite3.connect(db_path, timeout=10.0)
            cursor = conn.execute(query, params)
            if is_select:
                row = cursor.fetchone()
                return row
            else:
                conn.commit()
                return True
        except sqlite3.OperationalError as e:
            last_err = e
            await asyncio.sleep(0.1 * (attempt + 1))
        except sqlite3.Error as e:
            raise e
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception as close_err:
                    logger.warning(f"Failed to close SQLite connection: {close_err}")
    if last_err:
        raise last_err


def _get_smart_cut():
    global _smart_cut_instance
    if _smart_cut_instance is None:
        from plugins.smart_cut_plugin import SmartCutPlugin
        _smart_cut_instance = SmartCutPlugin()
    return _smart_cut_instance


@router.post("/init")
async def init_smartcut(req: InitRequest) -> Dict[str, Any]:
    """
    スマートカット初期化
    
    Stage 1のスキャン結果を受け取り、SmartCutContextを作成
    """
    try:
        from plugins.lightweight_scan_plugin import LightweightScanPlugin
        from core.context import ProductionContext
        
        # スキャン実行
        scan_plugin = LightweightScanPlugin()
        context = ProductionContext(task_id="smartcut_init")
        
        segments_data = []
        for i, s in enumerate(req.segments):
            dump = s.model_dump()
            if not dump.get("id"):
                dump["id"] = f"seg_auto_{i}_{int(dump['start'])}_{int(dump['end'])}"
            segments_data.append(dump)
            
        context.segments = segments_data
        context = scan_plugin.execute(context)
        
        if not hasattr(context, "scan_result") or context.scan_result is None:
            raise HTTPException(status_code=500, detail="Scan plugin failed to generate results")
        
        # スマートカット初期化
        smart_cut = _get_smart_cut()
        smart_cut._context = None  # リセット
        
        from plugins.smart_cut_plugin import SmartCutContext
        smart_cut._context = SmartCutContext(
            all_highlights=context.scan_result.highlight_candidates,
            all_chapters=context.scan_result.chapter_candidates,
            opening_duration=req.opening_duration,
            ending_duration=req.ending_duration,
        )
        
        # デフォルト15分で推奨生成
        smart_cut.update_recommendation(15)
        
        return {
            "success": True,
            "scan_result": {
                "total_segments": context.scan_result.total_segments,
                "highlight_count": len(context.scan_result.highlight_candidates),
                "chapter_count": len(context.scan_result.chapter_candidates),
                "estimated_cut_rate": context.scan_result.estimated_cut_rate,
            },
            "recommendation": smart_cut.get_recommendation()
        }
        
    except ImportError as e:
        logger.exception("Plugin load failure during init")
        raise HTTPException(status_code=500, detail=f"Failed to load required plugins: {str(e)}")
    except TypeError as e:
        logger.exception("Type error during init")
        raise HTTPException(status_code=400, detail=f"Invalid parameter types: {str(e)}")
    except KeyError as e:
        logger.exception("Missing key during init")
        raise HTTPException(status_code=400, detail=f"Missing expected key: {str(e)}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("SmartCut init failed")
        err_msg = str(e) or "Unknown internal error occurred during SmartCut initialization"
        raise HTTPException(status_code=500, detail=err_msg)


@router.post("/recommend")
async def get_recommendation(req: RecommendRequest) -> Dict[str, Any]:
    """
    尺に応じた推奨構成を取得
    
    15分 → 30分 → 45分 → 60分（拡張型）
    60分 → 45分 → 30分 → 15分（濃縮型）
    """
    try:
        smart_cut = _get_smart_cut()
        
        if smart_cut._context is None:
            raise HTTPException(status_code=400, detail="SmartCut not initialized. Call /init first.")
        
        smart_cut.update_recommendation(req.target_duration_minutes)
        
        return {
            "success": True,
            "recommendation": smart_cut.get_recommendation()
        }
        
    except ImportError as e:
        logger.exception("Plugin load failure during recommendation")
        raise HTTPException(status_code=500, detail=f"Failed to load required plugins: {str(e)}")
    except TypeError as e:
        logger.exception("Type error during recommendation")
        raise HTTPException(status_code=400, detail=f"Invalid parameter types: {str(e)}")
    except KeyError as e:
        logger.exception("Missing key during recommendation")
        raise HTTPException(status_code=400, detail=f"Missing expected key: {str(e)}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Recommendation failed")
        err_msg = str(e) or "Unknown internal error occurred during recommendation"
        raise HTTPException(status_code=500, detail=err_msg)


@router.post("/lock")
async def lock_segment(req: LockRequest) -> Dict[str, Any]:
    """
    シーンを固定
    
    §6 議長権限: ユーザーが「絶対に入れたい」シーンを指定
    """
    try:
        smart_cut = _get_smart_cut()
        
        if smart_cut._context is None:
            raise HTTPException(status_code=400, detail="SmartCut not initialized")
        
        success = smart_cut.lock_segment(
            segment_id=req.segment_id,
            title=req.title,
            start=req.start_time,
            end=req.end_time,
            reason=req.reason
        )
        
        if not success:
            raise HTTPException(status_code=400, detail="Segment already locked or lock failed")
        
        return {
            "success": True,
            "locked_segments": smart_cut.get_locked_segments(),
            "recommendation": smart_cut.get_recommendation()
        }
        
    except ImportError as e:
        logger.exception("Plugin load failure during lock")
        raise HTTPException(status_code=500, detail=f"Failed to load required plugins: {str(e)}")
    except TypeError as e:
        logger.exception("Type error during lock")
        raise HTTPException(status_code=400, detail=f"Invalid parameter types: {str(e)}")
    except KeyError as e:
        logger.exception("Missing key during lock")
        raise HTTPException(status_code=400, detail=f"Missing expected key: {str(e)}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Lock failed")
        err_msg = str(e) or "Unknown internal error occurred during segment locking"
        raise HTTPException(status_code=500, detail=err_msg)


@router.post("/unlock")
async def unlock_segment(req: UnlockRequest) -> Dict[str, Any]:
    """固定解除"""
    try:
        smart_cut = _get_smart_cut()
        
        if smart_cut._context is None:
            raise HTTPException(status_code=400, detail="SmartCut not initialized")
        
        success = smart_cut.unlock_segment(req.segment_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Locked segment not found")
        
        return {
            "success": True,
            "locked_segments": smart_cut.get_locked_segments(),
            "recommendation": smart_cut.get_recommendation()
        }
        
    except ImportError as e:
        logger.exception("Plugin load failure during unlock")
        raise HTTPException(status_code=500, detail=f"Failed to load required plugins: {str(e)}")
    except TypeError as e:
        logger.exception("Type error during unlock")
        raise HTTPException(status_code=400, detail=f"Invalid parameter types: {str(e)}")
    except KeyError as e:
        logger.exception("Missing key during unlock")
        raise HTTPException(status_code=400, detail=f"Missing expected key: {str(e)}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unlock failed")
        err_msg = str(e) or "Unknown internal error occurred during segment unlocking"
        raise HTTPException(status_code=500, detail=err_msg)


@router.get("/all-candidates")
async def get_all_candidates() -> Dict[str, Any]:
    """全候補（ハイライト50件/チャプター30件）を取得"""
    try:
        smart_cut = _get_smart_cut()
        
        if smart_cut._context is None:
            raise HTTPException(status_code=400, detail="SmartCut not initialized")
        
        return {
            "success": True,
            "candidates": smart_cut.get_all_candidates()
        }
        
    except ImportError as e:
        logger.exception("Plugin load failure during get candidates")
        raise HTTPException(status_code=500, detail=f"Failed to load required plugins: {str(e)}")
    except TypeError as e:
        logger.exception("Type error during get candidates")
        raise HTTPException(status_code=400, detail=f"Invalid parameter types: {str(e)}")
    except KeyError as e:
        logger.exception("Missing key during get candidates")
        raise HTTPException(status_code=400, detail=f"Missing expected key: {str(e)}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Get candidates failed")
        err_msg = str(e) or "Unknown internal error occurred during fetching candidates"
        raise HTTPException(status_code=500, detail=err_msg)


@router.post("/finalize")
async def finalize() -> Dict[str, Any]:
    """
    最終構成を確定
    
    Soul Narrativeに記録するためのデータを返す
    """
    try:
        smart_cut = _get_smart_cut()
        
        if smart_cut._context is None:
            raise HTTPException(status_code=400, detail="SmartCut not initialized")
        
        result = smart_cut.finalize()
        
        return {
            "success": True,
            "finalized": result
        }
        
    except ImportError as e:
        logger.exception("Plugin load failure during finalize")
        raise HTTPException(status_code=500, detail=f"Failed to load required plugins: {str(e)}")
    except TypeError as e:
        logger.exception("Type error during finalize")
        raise HTTPException(status_code=400, detail=f"Invalid parameter types: {str(e)}")
    except KeyError as e:
        logger.exception("Missing key during finalize")
        raise HTTPException(status_code=400, detail=f"Missing expected key: {str(e)}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Finalize failed")
        err_msg = str(e) or "Unknown internal error occurred during finalization"
        raise HTTPException(status_code=500, detail=err_msg)


class SmartCutThumbnailRequest(BaseModel):
    """スマートカット用サムネイル生成リクエスト"""
    session_id: str
    task_id: str = "smartcut_thumb_task"
    width: int = Field(default=1280, ge=1280)
    height: int = Field(default=720, ge=720)
    text: str = Field(default="SmartCut Session Thumbnail")

    @model_validator(mode="after")
    def validate_resolution_and_aspect(self) -> "SmartCutThumbnailRequest":
        if self.width < 1280 or self.height < 720:
            raise ValueError("Resolution must be at least 1280x720")
        if self.width * 9 != self.height * 16:
            raise ValueError("Aspect ratio must be 16:9")
        return self


@router.post("/thumbnail")
async def generate_smartcut_thumbnail(req: SmartCutThumbnailRequest) -> Dict[str, Any]:
    """
    SmartCutセッション用のサムネイル生成とStageBoundAgent連携のエンドポイント
    
    品質自動化規約（1280x720以上, 16:9, <4MB, Pillow正常ロード）を検証します。
    """
    try:
        from services.smartcut_strategy_service import SmartCutStrategyService
        from agents.stage_bound_agent import StageBoundAgent
        import os
        import json
        import asyncio
        import sqlite3
        
        # データベースと出力ディレクトリの設定
        db_path = "backend/temp/smartcut_stage.db" if os.path.exists("backend") else "temp/smartcut_stage.db"
        output_dir = str(_writable_path("backend/temp_thumbnails"))
        
        try:
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            os.makedirs(output_dir, exist_ok=True)
        except OSError as e:
            logger.exception("Failed to create temporary directories")
            raise HTTPException(status_code=500, detail=f"Failed to initialize directory structure: {str(e)}")
        
        # サービスの設定
        service = SmartCutStrategyService()
        service.output_dir = output_dir
        service.width = req.width
        service.height = req.height
        service.text = req.text
        
        # エージェントの初期化
        agent = StageBoundAgent(stage_name="thumbnail", db_path=db_path)
        
        try:
            # 既存タスクがあれば削除して冪等性を確保
            try:
                await _safe_sqlite_query(db_path, "DELETE FROM tasks WHERE id = ?", (req.task_id,), is_select=False)
            except sqlite3.Error as e:
                logger.warning(f"Failed to delete existing task {req.task_id} from SQLite ({db_path}): {e}")
                
            await agent.register_task(task_id=req.task_id, initial_status="READY", max_retries=2)
            await agent.start(service.resolve_session_thumbnail_task)
            
            # 完了を待つ (最大10秒)
            for _ in range(200):
                status = await agent.get_task_status(req.task_id)
                if status in ("COMPLETED", "FAILED"):
                    break
                await asyncio.sleep(0.05)
                
            final_status = await agent.get_task_status(req.task_id)
            
            # 保存されていた結果を取得
            row = None
            db_error = None
            try:
                row = await _safe_sqlite_query(db_path, "SELECT result FROM tasks WHERE id = ?", (req.task_id,), is_select=True)
            except sqlite3.Error as e:
                logger.error(f"Failed to fetch task result for {req.task_id} from SQLite ({db_path}): {e}")
                db_error = e
            
            if db_error is not None:
                raise HTTPException(status_code=500, detail=f"Database error while fetching result: {str(db_error)}")
            
            if final_status == "COMPLETED" and row and row[0] is not None:
                try:
                    result_data = json.loads(row[0])
                except (json.JSONDecodeError, TypeError):
                    result_data = row[0]
                return {
                    "success": True,
                    "status": final_status,
                    "thumbnail": result_data
                }
            else:
                err_detail = None
                if row:
                    try:
                        err_detail_json = json.loads(row[0]) if row[0] is not None else None
                        if isinstance(err_detail_json, dict) and "error" in err_detail_json:
                            err_detail = err_detail_json["error"]
                        elif isinstance(err_detail_json, str):
                            err_detail = err_detail_json
                        else:
                            err_detail = str(err_detail_json) if err_detail_json is not None else None
                    except (json.JSONDecodeError, TypeError):
                        err_detail = str(row[0]) if row[0] is not None else None
                
                if final_status == "COMPLETED":
                    msg = "Thumbnail task completed but no result found"
                else:
                    msg = f"Thumbnail task failed with status {final_status}"
                if err_detail:
                    msg = f"Thumbnail task failed: {err_detail}"
                raise HTTPException(status_code=500, detail=msg)
        finally:
            await agent.stop()
            
    except sqlite3.Error as e:
        logger.exception("SQLite database error during thumbnail generation")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except ImportError as e:
        logger.exception("Dependency import failure during thumbnail generation")
        raise HTTPException(status_code=500, detail=f"Required module not found: {str(e)}")
    except TypeError as e:
        logger.exception("Type error during thumbnail generation")
        raise HTTPException(status_code=400, detail=f"Type error: {str(e)}")
    except KeyError as e:
        logger.exception("Missing key during thumbnail generation")
        raise HTTPException(status_code=400, detail=f"Missing key: {str(e)}")
    except OSError as e:
        logger.exception("OS error during thumbnail generation")
        raise HTTPException(status_code=500, detail=f"OS error: {str(e)}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("SmartCut thumbnail generation failed")
        err_msg = str(e) or "Unknown internal error occurred during thumbnail generation"
        raise HTTPException(status_code=500, detail=err_msg)


@router.get("/health")
async def health_check() -> Dict[str, str]:
    """ヘルスチェック"""
    return {"status": "ok", "service": "smartcut"}
