"""
Director Router - AI Director endpoints
"""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

from fastapi import APIRouter, BackgroundTasks, Request, HTTPException
from pydantic import BaseModel, Field
import json

router = APIRouter(prefix="/api/director", tags=["director"])


def _register_router_debt(line_number: int, pattern: str, error_msg: str):
    try:
        from pathlib import Path
        from agents.memory.technical_debt import TechnicalDebtStore
        # director.py is in backend/routers/director.py, so parent.parent is backend
        store = TechnicalDebtStore(Path(__file__).parent.parent / "agents/memory")
        store.register_debt(
            category="CRITICAL_ROUTER",
            file_path="routers/director.py",
            line_number=line_number,
            pattern=pattern,
            cause_pattern="DP-01",
            fix_pattern="HTTPException translation",
            registered_by="T-batch_27b234-docker-002",
            notes=f"Runtime exception in director router: {error_msg}",
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to register TDR debt: {e}")


class ChatRequest(BaseModel):
    history: list = []
    message: str


class ImageGenRequest(BaseModel):
    prompt: str


class ScriptAnalysisRequest(BaseModel):
    full_text: str


class BatchGenRequest(BaseModel):
    scenes: list
    style_prompt: str


class QualityScoreRequest(BaseModel):
    storyboard_plan: list
    biz_rank: str = "Novice"


class StoryboardPlanRequest(BaseModel):
    full_text: str
    scenes: list
    selected_style: dict


class ReportRequest(BaseModel):
    storyboard_plan: list
    quality_score: dict
    biz_rank: str = "Novice"


@router.post("/chat")
async def director_chat(req: ChatRequest):
    """AI Chat via Nexus 2.0 semantic dispatch"""
    if len(req.message) > 2000:
        raise HTTPException(status_code=400, detail="Message exceeds maximum limit of 2000 characters")
    try:
        from director_engine import brain
        return brain.route_to_agents(req.message, req.history)
    except HTTPException:
        raise
    except Exception as e:
        _register_router_debt(77, "except Exception as e", str(e))
        raise HTTPException(status_code=500, detail=f"Director chat failed: {str(e)}")


@router.post("/generate-image")
async def director_generate_image(req: ImageGenRequest):
    """Generate image using Imagen 3 (sync)"""
    if len(req.prompt) > 1000:
        raise HTTPException(status_code=400, detail="Prompt exceeds maximum limit of 1000 characters")
    try:
        from director_engine import brain
        result = brain.generate_image(req.prompt)
        return result
    except HTTPException:
        raise
    except Exception as e:
        _register_router_debt(93, "except Exception as e", str(e))
        raise HTTPException(status_code=500, detail=f"Image generation failed: {str(e)}")


@router.post("/generate-image-async")
async def director_generate_image_async(req: ImageGenRequest, background_tasks: BackgroundTasks):
    """Generate image using Imagen 3 (async)"""
    if len(req.prompt) > 1000:
        raise HTTPException(status_code=400, detail="Prompt exceeds maximum limit of 1000 characters")
    try:
        from director_engine import brain, task_manager
        task_id = task_manager.create_task()
        background_tasks.add_task(brain.process_image_task, task_id, req.prompt)
        return {"task_id": task_id, "status": "processing"}
    except HTTPException:
        raise
    except Exception as e:
        _register_router_debt(110, "except Exception as e", str(e))
        raise HTTPException(status_code=500, detail=f"Async image generation failed: {str(e)}")


@router.get("/task/{task_id}")
async def get_task_status(task_id: str):
    """Get status of background task"""
    try:
        from director_engine import task_manager
        return task_manager.get_task(task_id)
    except HTTPException:
        raise
    except Exception as e:
        _register_router_debt(123, "except Exception as e", str(e))
        raise HTTPException(status_code=500, detail=f"Get task status failed: {str(e)}")


@router.post("/analyze-script")
async def analyze_script(req: ScriptAnalysisRequest):
    """Analyze script and propose optimal themes/styles"""
    if len(req.full_text) > 50000:
        raise HTTPException(status_code=400, detail="Script text exceeds maximum limit of 50000 characters")
    try:
        from director_engine import brain
        res_raw = brain.analyze_script(req.full_text)
        if isinstance(res_raw, str):
            try:
                return json.loads(res_raw)
            except (json.JSONDecodeError, TypeError, ValueError):
                return {"result": res_raw}
        return res_raw
    except HTTPException:
        raise
    except Exception as e:
        _register_router_debt(144, "except Exception as e", str(e))
        raise HTTPException(status_code=500, detail=f"Script analysis failed: {str(e)}")


@router.post("/quality-score")
async def quality_score(req: QualityScoreRequest):
    """Calculate quality score for storyboard plan"""
    if len(req.storyboard_plan) > 50:
        raise HTTPException(status_code=400, detail="Storyboard plan exceeds maximum limit of 50 scenes")
    try:
        from director_engine import brain
        res_raw = brain.calculate_quality_score(req.storyboard_plan, req.biz_rank)
        if isinstance(res_raw, str):
            try:
                return json.loads(res_raw)
            except (json.JSONDecodeError, TypeError, ValueError):
                return {"result": res_raw}
        return res_raw
    except HTTPException:
        raise
    except Exception as e:
        _register_router_debt(165, "except Exception as e", str(e))
        raise HTTPException(status_code=500, detail=f"Quality scoring failed: {str(e)}")


@router.post("/analyze-resources")
async def analyze_resources(req: ScriptAnalysisRequest):
    """Extract required video resources from script"""
    if len(req.full_text) > 50000:
        raise HTTPException(status_code=400, detail="Script text exceeds maximum limit of 50000 characters")
    try:
        from director_engine import brain
        res_raw = brain.analyze_resource_needs(req.full_text)
        if isinstance(res_raw, str):
            try:
                return json.loads(res_raw)
            except (json.JSONDecodeError, TypeError, ValueError):
                return {"result": res_raw}
        return res_raw
    except HTTPException:
        raise
    except Exception as e:
        _register_router_debt(186, "except Exception as e", str(e))
        raise HTTPException(status_code=500, detail=f"Resource analysis failed: {str(e)}")


@router.post("/generate-report")
async def generate_report(req: ReportRequest):
    """Generate session report and apply XP to branding"""
    if len(req.storyboard_plan) > 50:
        raise HTTPException(status_code=400, detail="Storyboard plan exceeds maximum limit of 50 scenes")
    try:
        from director_engine import brain
        from branding_manager import branding_manager
        
        report_raw = brain.generate_production_report(req.storyboard_plan, req.quality_score, req.biz_rank)
        if isinstance(report_raw, str):
            try:
                report = json.loads(report_raw)
            except (json.JSONDecodeError, TypeError, ValueError):
                report = {"summary": report_raw}
        else:
            report = report_raw
        
        xp = report.get("xp_grant", report.get("xp_earned", 0))
        if xp > 0:
            try:
                branding_manager.update_user_rank("tech_rank", amount=xp)
            except HTTPException:
                raise
            except Exception as xp_err:
                import logging
                logging.getLogger(__name__).error(f"Failed to apply XP in Docker environment: {xp_err}")
                _register_router_debt(215, "except Exception as xp_err", str(xp_err))
        
        return report
    except HTTPException:
        raise
    except Exception as e:
        _register_router_debt(223, "except Exception as e", str(e))
        raise HTTPException(status_code=500, detail=f"Report generation failed: {str(e)}")


@router.post("/plan-storyboard")
async def plan_storyboard(req: StoryboardPlanRequest):
    """Generate scene-by-scene storyboard plan"""
    if len(req.full_text) > 50000:
        raise HTTPException(status_code=400, detail="Script text exceeds maximum limit of 50000 characters")
    if len(req.scenes) > 50:
        raise HTTPException(status_code=400, detail="Scenes list exceeds maximum limit of 50 elements")
    try:
        from director_engine import brain
        res_raw = brain.generate_storyboard_plan(req.full_text, req.scenes, req.selected_style)
        if isinstance(res_raw, str):
            try:
                return json.loads(res_raw)
            except (json.JSONDecodeError, TypeError, ValueError):
                return {"result": res_raw}
        return res_raw
    except HTTPException:
        raise
    except Exception as e:
        _register_router_debt(246, "except Exception as e", str(e))
        raise HTTPException(status_code=500, detail=f"Storyboard planning failed: {str(e)}")


@router.post("/batch-generate")
async def batch_generate(req: BatchGenRequest, background_tasks: BackgroundTasks):
    """Batch generate images for all scenes asynchronously"""
    if len(req.scenes) > 20:
        raise HTTPException(status_code=400, detail="Batch size exceeds maximum limit of 20 scenes to prevent Docker container OOM")
    if len(req.style_prompt) > 1000:
        raise HTTPException(status_code=400, detail="Style prompt exceeds maximum limit of 1000 characters")
    try:
        from director_engine import brain, task_manager
        task_id = task_manager.create_task()
        background_tasks.add_task(brain.process_batch_image_task, task_id, req.scenes, req.style_prompt)
        return {"task_id": task_id, "status": "processing"}
    except HTTPException:
        raise
    except Exception as e:
        _register_router_debt(265, "except Exception as e", str(e))
        raise HTTPException(status_code=500, detail=f"Batch generation failed: {str(e)}")


# --- Thumbnail Generation & Quality Validation for Phase 27 ---
from pathlib import Path
from PIL import Image, ImageDraw

THUMBNAIL_OUTPUT_DIR = _writable_path("backend/temp_thumbnails")

def generate_director_thumbnail(output_path, width=1280, height=720, text="Director Thumbnail"):
    """Pillowを使用して、指定された解像度とテキストでサムネイル画像を生成する"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (width, height), color=(50, 50, 50))
    d = ImageDraw.Draw(img)
    d.text((10, 10), text, fill=(255, 255, 255))
    img.save(output_path, "PNG")
    return output_path

def validate_director_thumbnail(file_path) -> dict:
    """サムネイル画像の品質要件（解像度、アスペクト比、ファイルサイズ、破損）を検証する"""
    from PIL import Image
    from pathlib import Path
    file_path = Path(file_path)
    
    if not file_path.exists():
        raise FileNotFoundError(f"Thumbnail file not found: {file_path}")
        
    size_bytes = file_path.stat().st_size
    if size_bytes >= 4 * 1024 * 1024:
        raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")
        
    try:
        with Image.open(file_path) as img:
            img.verify()
            img.close()
    except Exception as e:
        raise ValueError(f"Image is corrupted or invalid format: {e}")
        
    try:
        with Image.open(file_path) as img:
            img.load()
            width, height = img.size
            img.close()
    except Exception as e:
        raise ValueError(f"Failed to load image for resolution check: {e}")
        
    if width < 1280 or height < 720:
        raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
        
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 1e-3:
        raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")
        
    return {
        "path": str(file_path),
        "width": width,
        "height": height,
        "size_bytes": size_bytes
    }

async def resolve_director_thumbnail_task(task_id: str) -> str:
    """StageBoundAgent の process_func として動作する非同期タスク処理"""
    import json
    output_path = THUMBNAIL_OUTPUT_DIR / f"{task_id}.png"
    generate_director_thumbnail(output_path)
    result_info = validate_director_thumbnail(output_path)
    return json.dumps(result_info)


