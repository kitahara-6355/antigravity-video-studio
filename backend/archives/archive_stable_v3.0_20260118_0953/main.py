import os
import sys
import json
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, UploadFile, File, WebSocket, WebSocketDisconnect, Body
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

# .envファイルのロード
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(ENV_PATH)
import base64
from pydantic import BaseModel
from branding.history_manager import history_manager, EventType

# アプリ憲法に基づき、パスの解決を明確に行う
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
DATA_PATH = os.path.join(SRC_DIR, "segments_a_plus_plus.json")
SCENES_PATH = os.path.join(SRC_DIR, "scenes_data.json")
VIDEO_PATH = os.path.join(SRC_DIR, "sample_raw.mp4")

# ... existing code ...
from pydantic import BaseModel, Field
import uuid
import os
import logging
from pathlib import Path

# Logging 設定
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / 'backend.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
import sys
# [NEW] Import Director Brain
from director_engine import brain, task_manager
from list_models import list_gemini_models
from project_archiver import project_archiver
# Phase 23: Manager Monitoring
from manager_monitoring import router as manager_router
# Phase 24: Subtitle Engine
from subtitle_engine import WhisperTranscriber, SubtitleFormatter
# Phase 25: Thumbnail Engine
from thumbnail_engine import generator as thumbnail_generator
# Phase 3: WebSocket Progress (システム改善計画)
from websocket_handler import progress_manager, broadcaster, handle_progress_websocket

# Phase 9: Router分割 (推奨タスク実装)
from routers import dashboard_router, approval_router, philosophy_router

# Phase 10: 追加ルーター (最終推奨タスク)
from log_manager import router as log_router
from error_reporter import router as support_router

# Phase 11: 動画処理統合エンジン
from video_processor import video_processor, MOOD_SETTINGS

# Phase 12: Quality Gate Agent (憲法準拠)
from quality_gate_agent import quality_gate

# Phase 13: Draft Manager (Progressive Quality Pipeline)
from draft_manager import draft_manager

# Phase 14: Cleanup Manager (ストレージ最適化)
from cleanup_manager import cleanup_manager

# Phase 15: Decision Logger (意思決定記録・Soul Narrative統合)
from decision_logger import decision_logger

# Phase 30: Antigravity 3.0 API (統合パイプライン)
from antigravity_api import router as antigravity_router

# ... existing code ...

class RenderRequest(BaseModel):
    mode: str
    style: str = "default"

class FeedbackRequest(BaseModel):
    suggestion_id: str
    action: str  # approve, reject, tweak
    role: str    # admin, owner
    comment: str = ""

class JournalRequest(BaseModel):
    author: str
    content: str

# [NEW] Request Models for Director
class ChatRequest(BaseModel):
    history: list = [] # list of {role, parts}
    message: str

class ImageGenRequest(BaseModel):
    prompt: str

app = FastAPI(title="Antigravity Video Studio Backend")

# Antigravity 3.0 Router
app.include_router(antigravity_router)

# ... existing code (middleware, root, segments endpoints) ...
from branding_manager import branding_manager

@app.get("/api/status")
async def get_trinity_status():
    """Returns the full User Model including Ranks and Analytics."""
    return branding_manager.user_model

@app.post("/api/analytics/sync")
async def sync_analytics():
    """Triggers the Real-World Link: Analytics -> Biz Rank update."""
    result = branding_manager.process_analytics_update()
    return result

@app.post("/api/analytics/simulate")
async def simulate_analytics(views: int = 1000):
    """Debug: Simulates obtaining views."""
    from branding.analytics_manager import analytics_manager
    result = analytics_manager.sim_add_views(views)
    # Auto-sync after simulation
    sync_result = branding_manager.process_analytics_update()
    return {
        "simulation": result,
        "sync": sync_result
    }

@app.get("/api/models")
async def get_models():
    """Returns available Gemini models."""
    try:
        # Assuming list_gemini_models is available globally or from director_engine
        # If it's part of director_engine, it should be imported like:
        # from director_engine import brain, task_manager, list_gemini_models
        # For now, assuming it's a global function or needs to be defined elsewhere.
        models = list_gemini_models() 
        return {"models": models}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/director/chat")
async def director_chat(req: ChatRequest):
    """Nano Banana Pro (Gemini) とのチャット"""
    try:
        response_text = brain.chat_session(req.history, req.message)
        return {"text": response_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/director/generate-image")
async def director_generate_image(req: ImageGenRequest):
    """Imagen 3 による画像生成（同期）"""
    try:
        # Returns list of bytes. We need to convert to base64 string for JSON.
        images_bytes = brain.generate_image(req.prompt)
        
        # Convert bytes to base64 string
        images_b64_str = [base64.b64encode(img).decode('utf-8') for img in images_bytes]
        
        return {"images": images_b64_str}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/director/generate-image-async")
async def director_generate_image_async(req: ImageGenRequest, background_tasks: BackgroundTasks):
    """Imagen 3 による非同期画像生成"""
    try:
        task_id = task_manager.create_task()
        background_tasks.add_task(brain.process_image_task, task_id, req.prompt)
        return {"task_id": task_id, "status": "pending"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/director/tasks/{task_id}")
async def get_task_status(task_id: str):
    """タスクの状態確認"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

class ScriptAnalysisRequest(BaseModel):
    full_text: str

class BatchGenRequest(BaseModel):
    scenes: list
    style_prompt: str

@app.post("/api/director/analyze-script")
async def analyze_script(req: ScriptAnalysisRequest):
    """脚本全体を分析し、最適なスタイル案を提示する"""
    try:
        json_str = brain.analyze_script(req.full_text)
        return json.loads(json_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class QualityScoreRequest(BaseModel):
    storyboard_plan: list
    biz_rank: str = "Novice"

@app.post("/api/director/quality-score")
async def quality_score(req: QualityScoreRequest):
    """演出プランの品質スコアを算出する"""
    try:
        json_str = brain.calculate_quality_score(req.storyboard_plan, req.biz_rank)
        return json.loads(json_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/director/analyze-resources")
async def analyze_resources(req: ScriptAnalysisRequest):
    """脚本から必要な素材を洗い出す"""
    try:
        json_str = brain.analyze_resource_needs(req.full_text)
        return json.loads(json_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ReportRequest(BaseModel):
    storyboard_plan: list
    quality_score: dict
    biz_rank: str = "Novice"

@app.post("/api/director/generate-report")
async def generate_report(req: ReportRequest):
    """セッション終了時にレポートを作成し、経験値を付与する"""
    try:
        # 1. Generate Report
        report_json = brain.generate_production_report(
            req.storyboard_plan, 
            req.quality_score, 
            req.biz_rank
        )
        report_data = json.loads(report_json)
        
        # 2. Ingest to Branding (Grant XP)
        ingest_result = branding_manager.ingest_report(report_data)
        
        # Merge results
        result = {
            "report": report_data,
            "ingest": ingest_result
        }
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class StoryboardPlanRequest(BaseModel):
    full_text: str
    scenes: list
    selected_style: dict

@app.post("/api/director/plan-storyboard")
async def plan_storyboard(req: StoryboardPlanRequest):
    """スタイル決定後、シーンごとの詳細演出プラン（AI or 素材）を作成する"""
    try:
        json_str = brain.generate_storyboard_plan(req.full_text, req.scenes, req.selected_style)
        return json.loads(json_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/director/batch-generate")
async def batch_generate(req: BatchGenRequest, background_tasks: BackgroundTasks):
    """全シーンの画像をバックグラウンドで一括生成する"""
    try:
        task_id = task_manager.create_task()
        background_tasks.add_task(brain.process_batch_image_task, task_id, req.scenes, req.style_prompt)
        return {"task_id": task_id, "status": "pending"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ... existing code (render endpoint, etc) ...




# React(Vite)からのアクセスを許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"status": "Constitution Active", "app": "Antigravity Video Studio"}

@app.get("/api/segments")
def get_segments():
    """現在の字幕データを取得する。
    AIからの解説: これは編集画面の右側に表示される各行のデータ元です。"""
    if not os.path.exists(DATA_PATH):
        raise HTTPException(status_code=404, detail="字幕データが見つかりません。")
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

@app.post("/api/segments")
async def save_segments(request: Request):
    """編集された字幕データを保存する。
    AIからの解説: ユーザーがフォームで修正した内容を、マスターデータとしてJSONに反映します。"""
    try:
        segments = await request.json()
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(segments, f, ensure_ascii=False, indent=2)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/video")
def get_video():
    """プレビュー用動画をストリーミングする。
    AIからの解説: 左側のプレビュー画面で再生される、素材動画です。"""
    if not os.path.exists(VIDEO_PATH):
        raise HTTPException(status_code=404, detail="動画ファイルが見つかりません。")
    return FileResponse(VIDEO_PATH, media_type="video/mp4")

# [NEW] Director Persistence
@app.get("/api/director/state")
def get_director_state():
    """Returns the saved Director State (scenes, audio)."""
    if not os.path.exists(SCENES_PATH):
        # Return empty state if no file exists
        return {"scenes": [], "audioConfig": None}
    try:
        with open(SCENES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # If file is corrupted, return empty
        return {"scenes": [], "audioConfig": None}

@app.post("/api/director/state")
async def save_director_state(request: Request):
    """Saves the Director State."""
    try:
        data = await request.json()
        
        # [NEW] Auto-backup before overwrite
        project_archiver.save_snapshot(label="auto_before_save")
        
        # Structure: { scenes: [...], audioConfig: {...} }
        with open(SCENES_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/archives/snapshots")
def list_snapshots():
    """Returns a list of all project snapshots."""
    return project_archiver.list_snapshots()

@app.post("/api/archives/restore/{snapshot_id}")
def restore_snapshot(snapshot_id: str):
    """Restores a specific snapshot."""
    try:
        project_archiver.restore_snapshot(snapshot_id)
        return {"status": "success", "message": f"Snapshot {snapshot_id} restored."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/director/verify-quality")
async def verify_quality(request: Request):
    """Performs final quality check before render."""
    try:
        data = await request.json()
        full_text = data.get("full_text", "")
        scenes = data.get("scenes", [])
        segments = data.get("segments", [])
        
        result_json = brain.verify_production_quality(full_text, scenes, segments)
        return json.loads(result_json)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/director/evolution")
def get_evolution():
    """Returns the qualitative growth narrative log."""
    return branding_manager.get_evolution_log()

@app.post("/api/collaboration/feedback")
async def process_feedback(feedback: FeedbackRequest):
    """
    Processes feedback from Admin or Owner on an AI suggestion.
    AIからの解説: 管理者やチャンネル主からのフィードバックを記録し、AIの成長に反映させます。
    """
    try:
        # 1. Log the feedback
        history_manager.log_event(EventType.USER_INTERACTION, {
            "type": "COLLABORATIVE_FEEDBACK",
            "suggestion_id": feedback.suggestion_id,
            "action": feedback.action,
            "role": feedback.role,
            "comment": feedback.comment
        })
        
        # 2. Grant small XP if it's an approval or constructive tweak
        xp_amount = 10 if feedback.action == "approve" else 5
        rank_type = "tech_rank" if feedback.role == "admin" else "biz_rank"
        branding_manager.update_user_rank(rank_type, amount=xp_amount)
        
        # 3. Add to Qualitative Evolution Log
        feedback_note = f"Owner {feedback.action}ed with comment: {feedback.comment}" if feedback.role == "owner" else f"Admin {feedback.action}ed: {feedback.comment}"
        branding_manager.log_evolution({
            "event": "COLLABORATIVE_DECISION",
            "feedback": feedback_note,
            "agenda_proposal": "Review collaborative synergy."
        })
        
        return {"status": "success", "message": f"Feedback from {feedback.role} registered."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/collaboration/journal")
def get_journal():
    """Returns the collaborative notes history."""
    notes = branding_manager.user_model.get("interaction_history", {}).get("collaborative_notes", "No notes yet.")
    return {"notes": notes}

@app.post("/api/collaboration/journal")
async def add_journal_entry(req: JournalRequest):
    """
    Adds a collaborative note/decision to the user model.
    AIからの解説: 管理者とチャンネル主の間で交わされた合意やメモを、AIの記憶に刻みます。
    """
    try:
        import time
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        new_note = f"[{timestamp}] {req.author.upper()}: {req.content}"
        
        # Append to collaborative notes
        current_history = branding_manager.user_model.get("interaction_history", {})
        current_notes = current_history.get("collaborative_notes", "")
        updated_notes = current_notes + "\n" + new_note if current_notes else new_note
        
        if "interaction_history" not in branding_manager.user_model:
            branding_manager.user_model["interaction_history"] = {}
        
        branding_manager.user_model["interaction_history"]["collaborative_notes"] = updated_notes
        branding_manager.update_user_model() # This saves it
        
        # Also log as evolution
        branding_manager.log_evolution({
            "event": "COLLABORATIVE_NOTE",
            "author": req.author,
            "content": req.content,
            "agenda_proposal": "Align with new collaborative note."
        })
        
        return {"status": "success", "notes": updated_notes}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/render")
def trigger_render(req: RenderRequest = RenderRequest(mode="normal")):
    """高品質レンダリングを実行する。
    AIからの解説: 編集した結果をMoviePyで動画ファイル（MP4）として書き出します。"""
    try:
        # [NEW] Auto-backup before render
        project_archiver.save_snapshot(label="pre_render")
        
        # workflow_utilsを動的にインポートして実行
        sys.path.append(SRC_DIR)
        
        # Load segments to pass to engine
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            segments = json.load(f)

        success = False
        output_filename = ""

        # Ensure output directory exists
        processed_output_dir = os.path.join(BASE_DIR, "processed_output")
        os.makedirs(processed_output_dir, exist_ok=True)

        if req.mode == "cut":
            from smart_cut_engine import render_smart_cut
            output_filename = "GUI_SMART_CUT_OUTPUT.mp4"
            output_path = os.path.join(processed_output_dir, output_filename)
            success = render_smart_cut(
                segments, 
                VIDEO_PATH, 
                output_path
            )
        else:
            # Normal Premium Render
            # Load Scenes Data (for BGM)
            bgm_path = None
            if os.path.exists(SCENES_PATH):
                try:
                    with open(SCENES_PATH, "r", encoding="utf-8") as f:
                        director_state = json.load(f)
                        if director_state.get("audioConfig"):
                            # Logic: If audioConfig exists, use sample_audio.wav
                            # Future: Map director_state["audioConfig"]["name"] to specific files
                            check_bgm_path = os.path.join(SRC_DIR, "sample_audio.wav")
                            if os.path.exists(check_bgm_path):
                                bgm_path = check_bgm_path
                except Exception as e:
                    print(f"BGM Loading Error: {e}")

            from workflow_utils import render_subtitles
            output_filename = "GUI_FINAL_OUTPUT.mp4"
            output_path = os.path.join(processed_output_dir, output_filename)
            logo_path = os.path.join(BASE_DIR, "raw_videos", "スライド用素材", "特選", "常時_ロゴマーク.JPG")
            
            render_subtitles(
                VIDEO_PATH, 
                segments, 
                output_path,
                logo_path,
                style_name=req.style,
                bgm_path=bgm_path
            )
            success = True # Assuming render_subtitles completes without error

        if success:
             return {"status": "success", "path": os.path.abspath(output_path)}
        else:
             raise HTTPException(status_code=500, detail="Render failed")
             
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# --- AI Rhythm Engine ---

class RhythmRequest(BaseModel):
    text: str
    target_chars: int = 13

@app.post("/api/rhythm/split")
async def rhythm_split(req: RhythmRequest):
    """Semantic Split for AI Rhythm Master"""
    try:
        from ai_rhythm import semantic_split
        parts = semantic_split(req.text, req.target_chars)
        return {"parts": parts}
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))

# --- Council of Minds Endpoints ---

@app.post("/api/council/session")
def trigger_council_session(query: str = "現在のチャンネル成長についての戦略的分析をお願いします。"):
    """
    Triggers a Council Debate via LangGraph (Phase 20).
    """
    from agents.graph import council_graph
    from agents.council_logger import council_logger
    from langchain_core.messages import HumanMessage
    import uuid
    import json
    
    session_id = str(uuid.uuid4())
    
    # LangGraph 実行
    initial_state = {
        "messages": [HumanMessage(content=query)],
        "findings": {},
        "query": query,
        "next_agent": "",
        "synthesis": ""
    }
    
    # 実行結果の収集
    final_state = council_graph.invoke(initial_state)
    
    # 既存の UI との互換性のためのデータ変換
    council_responses = []
    print(f"DEBUG: Processing {len(final_state['messages'])} messages from council_graph")
    for msg in final_state['messages']:
        # メッセージ名を取得（LangChain のバージョンによる差異を吸収）
        msg_name = getattr(msg, 'name', None) or msg.additional_kwargs.get('name')
        print(f"DEBUG: Message from '{msg_name}' Type: {type(msg)}")
        
        if msg_name in ["Analyst", "Strategist", "Director"]:
            try:
                content_data = json.loads(msg.content)
                council_responses.append(content_data)
                print(f"DEBUG: Successfully added response from {msg_name}")
            except Exception as e:
                print(f"DEBUG: Failed to parse message content from {msg_name}: {e}")
                pass
                
    synthesis = final_state.get("synthesis", "知見を統合できませんでした。")
    
    # 4. Log
    council_logger.log_session(session_id, query, council_responses, synthesis)
    
    # Phase 26: Resolution（議案）の自動作成
    from agents.resolution_tracker import resolution_tracker, ResolutionStatus
    
    # 議論の結果から提案内容を抽出
    resolution_title = f"セッション {session_id[:8]} の知見"
    resolution_desc = synthesis.get("proposal", "議論の統合提案") if isinstance(synthesis, dict) else synthesis
    proposed_changes = {
        "type": "council_synthesis",
        "insights": council_responses,
        "synthesis": synthesis
    }
    
    resolution = resolution_tracker.create_resolution(
        title=resolution_title,
        description=resolution_desc,
        proposed_changes=proposed_changes,
        session_id=session_id
    )
    
    # 議論中ステータスに更新
    resolution_tracker.update_status(resolution.id, ResolutionStatus.DEBATE)
    
    return {
        "session_id": session_id,
        "query": query,
        "debate_flow": council_responses,
        "synthesis": synthesis,
        "resolution_id": resolution.id  # 議案IDを返す
    }

@app.post("/api/council/decision")
def council_decision(decision_data: dict):
    """
    Evolution Endpoint: Feedback Loop from Chairman to Agents.
    data: { "session_id": "...", "outcome": "APPROVE" | "REJECT", "agents_involved": [...] }
    """
    from agents.analyst import Analyst
    from agents.strategist import Strategist
    from agents.director import Director
    
    # 1. Parse Data
    session_id = decision_data.get("session_id")
    outcome = decision_data.get("outcome") # APPROVE / REJECT
    flow = decision_data.get("debate_flow", [])
    
    print(f"⚖️ Chairman Decision: {outcome} for Session {session_id}")
    
    # 2. Trigger Learning for each involved agent
    agents_map = {
        "Analyst": Analyst(),
        "Strategist": Strategist(),
        "Director": Director()
    }
    
    learned_log = []
    
    for entry in flow:
        agent_name = entry.get("agent")
        stance = entry.get("stance")
        
        if agent_name in agents_map:
            agent = agents_map[agent_name]
            # TEACH THE SOUL
            agent.learn(session_id, stance, outcome)
            learned_log.append(f"{agent_name} learned.")
            
    return {"status": "success", "learned": learned_log}

# --- Settings & Control Center Endpoints (Phase 9) ---

@app.get("/api/settings")
async def get_settings():
    """Returns all system settings for the Control Center."""
    from settings_manager import settings_manager
    return settings_manager.get_all_settings()

class IdentityUpdate(BaseModel):
    channel_name: str
    target_audience: str

@app.post("/api/settings/identity")
async def update_identity(req: IdentityUpdate):
    """Updates Channel Name and Target Audience."""
    from settings_manager import settings_manager
    return settings_manager.update_identity(req.channel_name, req.target_audience)

@app.post("/api/settings/video")
async def upload_video_source(file: UploadFile = File(...)):
    """Replaces sample_raw.mp4 with uploaded file."""
    from settings_manager import settings_manager
    import shutil
    
    # Save uploaded file temporarily
    temp_path = f"temp_{file.filename}"
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Delegate to SettingsManager
    result = settings_manager.update_video_source(temp_path, original_filename=file.filename)
    
    # User might want to remove temp file, SettingsManager moved it so no need to delete if move was successful across filesystem,
    # but shutil.move usually deletes source. If on same filesystem safe. If different, might need cleanup.
    # SettingsManager uses shutil.move.
    
    return result

@app.post("/api/settings/reset")
async def reset_workspace():
    """Resets the workspace (Video & Segments)."""
    from settings_manager import settings_manager
    return settings_manager.reset_workspace()

class TranscribeRequest(BaseModel):
    """字幕生成リクエスト（両憲法準拠プラン）"""
    video_path: Optional[str] = None  # ローカルパス指定（大容量対応）
    language: str = "ja"
    with_proofreading: bool = True


@app.post("/api/transcribe")
async def trigger_transcription(
    background_tasks: BackgroundTasks,
    req: TranscribeRequest = TranscribeRequest()
):
    """
    字幕生成API（両憲法準拠プラン）
    
    技術憲法準拠:
    - 9.3 承認フロー: タスクID即時返却
    - 10.1 記録の義務: task_store で状態永続化
    - 5.2 魂の継承: evolution_log 自動記録
    
    人の憲法準拠:
    - Entry 4: 「作業は裏でやっておく」 (BackgroundTasks)
    """
    from settings_manager import settings_manager
    from task_store import task_store, create_progress_callback, TaskPhase
    
    # video_path 判定（指定があればローカルパス、なければ設定から）
    if req.video_path and os.path.exists(req.video_path):
        video_path = req.video_path
    else:
        video_path = settings_manager.get_video_source()
    
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Video source not found")
    
    # タスク作成（即時返却）
    task = task_store.create_task(video_path=video_path)
    task_id = task.task_id
    
    output_path = os.path.join(SRC_DIR, f"segments_{task_id[:8]}.json")
    
    # バックグラウンド処理
    def process_task():
        try:
            # 進捗コールバック（StateStore + WebSocket 二重化）
            progress_callback = create_progress_callback(task_id)
            
            # Phase 18: faster-whisper + Gemini Proofreading
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            task_store.update_progress(
                task_id, TaskPhase.MODEL_LOADING, 5, "Whisperモデルをロード中..."
            )
            
            transcriber = WhisperTranscriber(model_size="medium")
            segments = loop.run_until_complete(
                transcriber.transcribe_with_proofreading(
                    video_path=video_path,
                    language=req.language,
                    beam_size=1,
                    progress_callback=progress_callback
                )
            )
            
            # 結果保存
            task_store.update_progress(
                task_id, TaskPhase.SAVING, 95, "結果を保存中..."
            )
            
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(segments, f, ensure_ascii=False, indent=2)
            
            # 完了（evolution_log 自動記録）
            task_store.complete_task(task_id, result_path=output_path)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            task_store.fail_task(task_id, str(e))
    
    background_tasks.add_task(process_task)
    
    return {
        "status": "started",
        "task_id": task_id,
        "message": "字幕生成を開始しました。タスクIDで進捗を確認できます。"
    }



@app.get("/api/transcribe/status")
def get_transcription_status():
    """Checks the status file written by transcribe.py (後方互換)"""
    status_file = os.path.join(SRC_DIR, "transcription_status.json")
    if os.path.exists(status_file):
        try:
            with open(status_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {"status": "unknown", "message": "Reading status file failed"}
    return {"status": "idle", "message": "No active transcription"}


@app.get("/api/task/{task_id}")
def get_task_status(task_id: str):
    """
    タスク状態取得API（両憲法準拠プラン）
    
    技術憲法 10.1 準拠: 全タスク状態を永続化・参照可能
    """
    from task_store import task_store
    
    task = task_store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return task.to_dict()


@app.get("/api/tasks")
def list_tasks(status: str = None):
    """
    タスク一覧取得API
    
    Query params:
        status: pending, running, completed, failed, cancelled
    """
    from task_store import task_store, TaskStatus
    
    status_filter = None
    if status:
        try:
            status_filter = TaskStatus(status)
        except ValueError:
            pass
    
    return {"tasks": task_store.list_tasks(status=status_filter)}



@app.websocket("/ws/live")
async def websocket_live_endpoint(websocket: WebSocket):
    from live_api_handler import LiveAPIHandler
    from director_engine import DirectorBrain
    import asyncio
    
    await websocket.accept()
    
    # 1. Identity Injection: Get Director's Soul
    brain = DirectorBrain()
    system_instruction = brain._get_system_instruction(mode="director") # Use Director persona for Live
    
    handler = LiveAPIHandler()
    send_queue = asyncio.Queue()
    
    # AI 側の受信コールバック
    async def ai_callback(message):
        payload = {}
        # ServerContent を解析
        try:
            if hasattr(message, 'server_content') and message.server_content:
                content = message.server_content
                if content.model_turn:
                    for part in content.model_turn.parts:
                        if part.text:
                            payload["text"] = part.text
                        if part.inline_data:
                            payload["audio"] = base64.b64encode(part.inline_data.data).decode('utf-8')
            
            if payload:
                await websocket.send_json(payload)
        except Exception as e:
            print(f"⚠️ Error in ai_callback: {e}")

    # クライアントからのデータ受信ループ
    async def receive_from_client():
        try:
            while True:
                data = await websocket.receive_json()
                if "text" in data:
                    await send_queue.put(data["text"])
                if "audio" in data:
                    # audio: base64 string
                    await send_queue.put({"data": data["audio"], "mime_type": "audio/pcm;rate=16000"})
                if "media" in data:
                    for chunk in data["media"]:
                        await send_queue.put(chunk)
        except WebSocketDisconnect:
            print("📡 WebSocket client disconnected")
        except Exception as e:
            print(f"❌ Receive from client error: {e}")
        finally:
            await send_queue.put(None) # Signal handler to stop

    try:
        # Live API セッションの実行 (Director's Soul 注入)
        handler_task = asyncio.create_task(handler.run(send_queue, ai_callback, system_instruction=system_instruction))
        receive_task = asyncio.create_task(receive_from_client())
        
        # 片方が終わるまで待機
        done, pending = await asyncio.wait(
            [handler_task, receive_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        for task in pending:
            task.cancel()
            
    except Exception as e:
        print(f"❌ WebSocket Bridge Error: {e}")
    finally:
        print("🧹 Cleaning up WebSocket Bridge...")
        try:
            await websocket.close()
        except:
            pass
        print("✅ Cleanup complete.")

# Phase 24: Subtitle API Endpoints
@app.post("/api/subtitle/transcribe")
async def transcribe_video(file: UploadFile):
    """
    動画をアップロードして字幕を生成
    
    Returns:
        {
            "subtitles": [{"start": 0.0, "end": 2.5, "text": "こんにちは"}, ...],
            "duration": 60.0,
            "segments_count": 12
        }
    """
    import tempfile
    import pathlib
    
    try:
        # 一時ファイルに保存
        with tempfile.NamedTemporaryFile(delete=False, suffix=pathlib.Path(file.filename).suffix) as video_file:
            content = await file.read()
            video_file.write(content)
            video_path = video_file.name
        
        try:
            # Phase 18 Architecture: faster-whisper + Gemini Proofreading
            transcriber = WhisperTranscriber(model_size="medium")
            subtitles = await transcriber.transcribe_with_proofreading(
                video_path=video_path,
                language="ja",
                beam_size=1
            )
            
            # 動画の長さを取得
            from moviepy.editor import VideoFileClip
            clip = VideoFileClip(video_path)
            duration = clip.duration
            clip.close()
            
            return {
                "subtitles": subtitles,
                "duration": duration,
                "segments_count": len(subtitles)
            }
        finally:
            # 一時ファイルクリーンアップ
            if os.path.exists(video_path):
                os.remove(video_path)
                
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")


@app.post("/api/subtitle/export/{format}")
async def export_subtitles(format: str, subtitles: list = Body(...)):
    """
    字幕を指定形式でエクスポート
    
    Args:
        format: "vtt" or "srt"
        subtitles: 字幕データのリスト
    
    Returns:
        字幕ファイル（テキスト）
    """
    try:
        if format.lower() == "vtt":
            content = SubtitleFormatter.to_vtt(subtitles)
            media_type = "text/vtt"
            filename = "subtitles.vtt"
        elif format.lower() == "srt":
            content = SubtitleFormatter.to_srt(subtitles)
            media_type = "text/plain"
            filename = "subtitles.srt"
        else:
            raise HTTPException(status_code=400, detail="Format must be 'vtt' or 'srt'")
        
        return StreamingResponse(
            iter([content]),
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")

# ============================================================================
# Phase 25: Thumbnail Generation
# ============================================================================

@app.post("/api/thumbnail/generate")
async def generate_thumbnail(request: Request):
    """
    サムネイル生成エンドポイント（Phase 25）
    
    Request Body:
    {
        "video_title": "動画タイトル",
        "video_description": "動画の説明（任意）",
        "num_variants": 3
    }
    
    Response:
    {
        "status": "success",
        "thumbnails": [
            {
                "id": "thumbnail_0",
                "concept_name": "コンセプト名",
                "description": "説明",
                "image_base64": "...",
                "ctr_score": 7.5
            },
            ...
        ]
    }
    """
    try:
        data = await request.json()
        video_title = data.get("video_title", "")
        video_description = data.get("video_description", "")
        num_variants = data.get("num_variants", 3)
        
        if not video_title:
            raise HTTPException(status_code=400, detail="video_title is required")
        
        # サムネイル生成
        thumbnails = await thumbnail_generator.generate(
            video_title=video_title,
            video_description=video_description,
            num_variants=num_variants
        )
        
        if not thumbnails:
            raise HTTPException(status_code=500, detail="Failed to generate thumbnails")
        
        return JSONResponse({
            "status": "success",
            "thumbnails": thumbnails,
            "count": len(thumbnails)
        })
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Thumbnail generation error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Thumbnail generation failed: {str(e)}")

@app.post("/api/soul/vision")
async def set_vision(request: Request):
    """
    ユーザーの動画に対する「想い・こだわり」をセットする。
    """
    try:
        data = await request.json()
        vision = data.get("vision", "")
        branding_manager.current_vision = vision
        return {"status": "success", "vision": vision}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/soul/evolve")
async def trigger_evolution(request: Request):
    """
    手動または自動で性格進化をトリガーする。
    """
    try:
        data = await request.json()
        success_event = data.get("event", {})
        branding_manager.evolve_constitution(success_event)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/council/resolutions")
async def list_resolutions(status: str = None):
    """
    議案一覧を取得（みらい議会スタイル）
    """
    from agents.resolution_tracker import resolution_tracker, ResolutionStatus
    try:
        status_filter = ResolutionStatus(status) if status else None
        resolutions = resolution_tracker.list_resolutions(status=status_filter)
        return {"status": "success", "resolutions": resolutions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/council/resolutions/{resolution_id}/vote")
async def vote_resolution(resolution_id: str, request: Request):
    """
    エージェントの投票を記録
    """
    from agents.resolution_tracker import resolution_tracker
    try:
        data = await request.json()
        agent_name = data.get("agent_name")
        vote = data.get("vote")  # "APPROVE" | "REJECT"
        resolution_tracker.record_vote(resolution_id, agent_name, vote)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/council/resolutions/{resolution_id}/gavel")
async def apply_gavel(resolution_id: str, request: Request):
    """
    議長決済（Gavel Ceremony）
    """
    from agents.resolution_tracker import resolution_tracker
    try:
        data = await request.json()
        decision = data.get("decision")  # "APPROVE" | "REJECT"
        
        success = resolution_tracker.apply_gavel(resolution_id, decision)
        
        if success and decision == "APPROVE":
            # 承認された場合、憲法を更新
            resolution = resolution_tracker.get_resolution(resolution_id)
            if resolution:
                branding_manager.evolve_constitution({
                    "type": "council_resolution",
                    "resolution_id": resolution_id,
                    "value": resolution.title,
                    "changes": resolution.proposed_changes
                })
        
        return {"status": "success", "decision": decision}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Preview Engine Endpoints (Phase 27) ---

from preview_engine import preview_engine
from fastapi.responses import FileResponse
from pathlib import Path

from pydantic import BaseModel
from typing import List, Optional
import asyncio
import os

# セキュリティ設定
MAX_VIDEO_SIZE_MB = 500
ALLOWED_VIDEO_DIR = Path("C:/Users/PC_User/Desktop/script/video-automation").resolve()
ALLOWED_EXTENSIONS = [".mp4", ".mov", ".avi", ".mkv", ".mp3", ".wav"]

# 同時実行制限
preview_semaphore = asyncio.Semaphore(2)  # 最大2プロセス同時実行

class SubtitleItem(BaseModel):
    text: str
    start: float
    end: float

class PreviewRequest(BaseModel):
    source_video: str
    bgm_path: Optional[str] = None
    duration: Optional[int] = None
    subtitles: Optional[List[SubtitleItem]] = None
    color_preset: Optional[str] = None

def validate_video_path(path: str, allow_none: bool = False) -> Path:
    """
    動画パスの検証（セキュリティ強化）
    
    Args:
        path: 検証するファイルパス
        allow_none: None を許可するか
    
    Returns:
        検証済みの Path オブジェクト
    
    Raises:
        ValueError: パスが不正な場合
        FileNotFoundError: ファイルが存在しない場合
    """
    if allow_none and not path:
        return None
    
    if not path:
        raise ValueError("File path is required")
    
    try:
        video_path = Path(path).resolve()
    except Exception as e:
        raise ValueError(f"Invalid path format: {path}")
    
    # 1. 許可されたディレクトリ内か確認（パストラバーサル対策）
    try:
        video_path.relative_to(ALLOWED_VIDEO_DIR)
    except ValueError:
        raise ValueError(f"Access denied: Path outside allowed directory")
    
    # 2. ファイル存在確認
    if not video_path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    
    # 3. サイズ制限（DoS 対策）
    size_mb = video_path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_VIDEO_SIZE_MB:
        raise ValueError(f"File too large: {size_mb:.1f}MB (max: {MAX_VIDEO_SIZE_MB}MB)")
    
    # 4. 拡張子チェック
    if video_path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {video_path.suffix}")
    
    return video_path

@app.get("/api/preview/sessions")
async def list_preview_sessions():
    """全プレビューセッション一覧"""
    return {
        "sessions": list(_preview_sessions.keys()),
        "count": len(_preview_sessions)
    }

@app.post("/api/preview/generate")
async def generate_preview(req: PreviewRequest):
    """
    Generate an enhanced preview (480p proxy) of the source video.
    Supports optional background music, animated subtitles, and color grading presets (Phase 28).
    
    Security: Input validation, file size limits, path traversal protection
    Performance: Concurrency control (max 2 simultaneous processes)
    """
    # 同時実行制限（CPU 使い切り防止）
    async with preview_semaphore:
        try:
            # 入力検証（セキュリティ強化）
            video_path = validate_video_path(req.source_video, allow_none=False)
            bgm_path = validate_video_path(req.bgm_path, allow_none=True) if req.bgm_path else None
            
            logger.info(f"Validated input: source_video={video_path}")
            if bgm_path:
                logger.info(f"Validated BGM: bgm_path={bgm_path}")
            
            # Pydantic モデルを辞書のリストに変換
            subs_list = [s.dict() for s in req.subtitles] if req.subtitles else None
            
            if subs_list or req.color_preset:
                # 高度なプレビューモード（一括処理）
                preview_id = preview_engine.generate_preview_with_subtitles(
                    str(video_path), subs_list or [], str(bgm_path) if bgm_path else None, req.duration, req.color_preset
                )
            else:
                # 標準プレビューモード
                preview_id = preview_engine.generate_preview(str(video_path), str(bgm_path) if bgm_path else None, req.duration)
                
            return {
                "preview_id": preview_id,
                "status": "ready",
                "message": "Enhanced preview generated successfully"
            }
        except (ValueError, FileNotFoundError) as e:
            # 入力検証エラー（ユーザー側の問題）
            error_detail = str(e)
            user_friendly_message = "Invalid input. Please check your file path and try again."
            
            # より詳細なガイダンスを提供
            if "Path outside allowed directory" in error_detail:
                user_friendly_message = "ファイルが許可されたディレクトリ外にあります。プロジェクトフォルダ内のファイルを選択してください。"
            elif "File not found" in error_detail:
                user_friendly_message = "指定されたファイルが見つかりません。ファイルパスを確認してください。"
            elif "File too large" in error_detail:
                user_friendly_message = "ファイルサイズが大きすぎます（最大500MB）。動画を圧縮してから再試行してください。"
            elif "Unsupported file type" in error_detail:
                user_friendly_message = "サポートされていないファイル形式です。対応形式: .mp4, .mov, .avi, .mkv"
            
            logger.warning(f"Validation error: {error_detail}")
            raise HTTPException(
                status_code=400,
                detail=user_friendly_message
            )
        except Exception as e:
            # 内部エラー（サーバー側の問題）
            logger.error(f"Preview generation failed", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail="Preview generation failed. Please try again later."
            )

@app.get("/api/preview/{preview_id}")
def get_preview(preview_id: str):
    """
    Get the generated preview video.
    """
    try:
        video_path = preview_engine.get_preview_path(preview_id)
        return FileResponse(str(video_path), media_type="video/mp4")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Preview not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/preview/cleanup")
def cleanup_old_previews(days: int = 7):
    """
    Clean up preview files older than specified days.
    """
    try:
        preview_engine.cleanup_old_previews(days)
        return {"message": f"Cleaned up previews older than {days} days"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Audio & Video Enhancement Endpoints (Phase 28) ---

from audio_master import audio_master
from color_grading import color_grading

@app.post("/api/audio/master")
def master_audio(
    audio_path: str,
    normalize: bool = True,
    denoise: bool = True,
    target_lufs: float = -16.0,
    noise_reduction: float = 0.5
):
    """
    Audio mastering with normalization and noise removal.
    """
    try:
        mastered_audio = audio_master.master_audio(
            audio_path, 
            normalize, 
            denoise,
            target_lufs,
            noise_reduction
        )
        return {
            "mastered_audio": mastered_audio,
            "status": "success",
            "applied": {
                "normalize": normalize,
                "denoise": denoise
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/video/color-grade")
def apply_color_grading(
    video_path: str,
    preset: str = "cinematic"
):
    """
    Apply color grading preset to video.
    
    Available presets: cinematic, warm, cool, vintage, vibrant, none
    """
    try:
        graded_video = color_grading.apply_preset(video_path, preset)
        return {
            "graded_video": graded_video,
            "preset": preset,
            "status": "success"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/video/color-presets")
def get_color_presets():
    """
    Get available color grading presets.
    """
    return {
        "presets": list(color_grading.PRESETS.keys()),
        "default": "cinematic"
    }


# Phase 30.5: Progressive Preview System
from progressive_preview import ProgressivePreview
from preview_report_generator import PreviewReportGenerator

# 進行中のプレビューセッション管理
_preview_sessions: dict[str, ProgressivePreview] = {}

class PreviewSessionRequest(BaseModel):
    session_id: Optional[str] = None

class StepSnapshotRequest(BaseModel):
    session_id: str
    step_name: str
    before_video: str
    after_video: str
    num_samples: int = 3
    srt_path: Optional[str] = None

class PreviewDecisionRequest(BaseModel):
    session_id: str
    decision: str  # "approve" or "reject"
    feedback: str = ""

@app.post("/api/preview/session")
async def create_preview_session(req: PreviewSessionRequest):
    """新規プレビューセッションを作成"""
    preview = ProgressivePreview(session_id=req.session_id)
    _preview_sessions[preview.session_id] = preview
    return {
        "session_id": preview.session_id,
        "output_dir": str(preview.output_dir),
        "status": "created"
    }

@app.post("/api/preview/step")
async def capture_step_snapshot(req: StepSnapshotRequest):
    """処理ステップ完了時のスナップショットをキャプチャ"""
    if req.session_id not in _preview_sessions:
        # 自動作成
        _preview_sessions[req.session_id] = ProgressivePreview(session_id=req.session_id)
    
    preview = _preview_sessions[req.session_id]
    
    try:
        result = preview.snapshot_step(
            step_name=req.step_name,
            before_video=req.before_video,
            after_video=req.after_video,
            num_samples=req.num_samples
        )
        return {
            "status": "success",
            "step_name": req.step_name,
            "comparisons": len(result.get("comparisons", [])),
            "output_dir": str(preview.output_dir)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/preview/report/{session_id}")
async def get_preview_report(session_id: str):
    """セッションのHTMLレポートを生成・取得"""
    if session_id not in _preview_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    preview = _preview_sessions[session_id]
    generator = PreviewReportGenerator()
    
    try:
        report_path = generator.generate_from_session_dir(str(preview.output_dir))
        return FileResponse(report_path, media_type="text/html")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/preview/decision")
async def submit_preview_decision(req: PreviewDecisionRequest):
    """プレビューの承認/却下判定を記録"""
    decision_log = Path("backend/temp/previews") / "decisions.json"
    decision_log.parent.mkdir(parents=True, exist_ok=True)
    
    # 既存ログを読み込み
    decisions = []
    if decision_log.exists():
        try:
            with open(decision_log, 'r', encoding='utf-8') as f:
                decisions = json.load(f)
        except:
            pass
    
    # 新規判定を追加
    decisions.append({
        "session_id": req.session_id,
        "decision": req.decision,
        "feedback": req.feedback,
        "timestamp": datetime.now().isoformat()
    })
    
    with open(decision_log, 'w', encoding='utf-8') as f:
        json.dump(decisions, f, ensure_ascii=False, indent=2)
    
    return {
        "status": "recorded",
        "decision": req.decision,
        "session_id": req.session_id
    }



# Phase 23: Register Manager Monitoring router
app.include_router(manager_router)

# Phase 9: Register modular routers (推奨タスク実装)
app.include_router(dashboard_router)
app.include_router(approval_router)
app.include_router(philosophy_router)

# Phase 10: Register additional routers (最終推奨タスク)
app.include_router(log_router)
app.include_router(support_router)

# ============================================
# Phase 2: 統合ダッシュボードAPI (システム改善計画)
# ============================================

class ApprovalRequest(BaseModel):
    approved: bool
    feedback: str = ""
    timestamp: str = ""

class ProcessStartRequest(BaseModel):
    video_path: str = ""

# 処理状態を管理するグローバル変数（本番ではRedis等を使用推奨）
_dashboard_state = {
    "phase": "idle",
    "progress": 0,
    "current_step": "待機中",
    "preview_url": None
}

# 動画処理タスク管理（早期定義でダッシュボードAPIから参照可能に）
_video_tasks = {}

@app.get("/api/dashboard/status")
async def get_dashboard_status():
    """統合ダッシュボードの現在の状態を取得（video_tasks同期版）"""
    # _video_tasksから最新のアクティブタスクを取得
    active_task = None
    active_task_id = None
    latest_time = 0
    
    logger.info(f"Dashboard status check: {len(_video_tasks)} tasks in memory, id={id(_video_tasks)}")
    
    for task_id, task in _video_tasks.items():
        created_at = task.get("created_at", 0)
        logger.info(f"  Task {task_id}: created_at={created_at}")
        if created_at > latest_time:
            latest_time = created_at
            active_task = task
            active_task_id = task_id
    
    # アクティブタスクがあれば返す（completeでも返す）
    if active_task:
        current_status = active_task.get("status", "idle")
        logger.info(f"Active task found: {active_task_id}, status={current_status}, progress={active_task.get('progress', 0)}")
        return {
            "phase": current_status,
            "progress": active_task.get("progress", 0),
            "current_step": active_task.get("current_step", "待機中"),
            "preview_url": active_task.get("preview_url"),
            "task_id": active_task_id
        }
    
    logger.info("No active task found, returning idle state")
    return _dashboard_state

# ===== Quality Gate API (PROJECT_CONSTITUTION 8.2 品質ゲート) =====
class QualityCheckRequest(BaseModel):
    """品質チェックリクエスト"""
    full_text: str = ""  # 脚本テキスト
    scenes: list = []    # シーン構成
    segments: list = []  # 字幕データ

@app.post("/api/quality/check")
async def run_quality_check(req: QualityCheckRequest):
    """
    品質ゲートを実行
    
    PROJECT_CONSTITUTION 8.2 に基づく品質チェック:
    - 誤字脱字チェック
    - ブランド整合性チェック
    - 字幕リズムチェック
    - シーン演出の論理性チェック
    
    スコア80点以上で合格、60点未満でブロック
    """
    try:
        content = {
            "full_text": req.full_text,
            "scenes": req.scenes,
            "segments": req.segments
        }
        
        report = quality_gate.run_gate(content)
        
        return {
            "success": True,
            "report": report.to_dict()
        }
    except Exception as e:
        logger.error(f"Quality gate error: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@app.get("/api/quality/threshold")
async def get_quality_threshold():
    """品質閾値を取得"""
    return {
        "pass_threshold": quality_gate.THRESHOLD_PASS,
        "warning_threshold": quality_gate.THRESHOLD_WARNING
    }

# ===== Draft Manager API (Progressive Quality Pipeline) =====
class DraftCreateRequest(BaseModel):
    """ドラフト生成リクエスト"""
    input_path: str
    quality: str = "medium"  # low/medium/high
    output_name: str = None

class PrefinalCreateRequest(BaseModel):
    """投稿前確認動画生成リクエスト"""
    draft_paths: list
    output_name: str = None

class FinalCreateRequest(BaseModel):
    """最終出力リクエスト"""
    prefinal_path: str
    output_name: str = None
    srt_path: str = None

@app.post("/api/draft/create")
async def create_draft(req: DraftCreateRequest):
    """
    低容量ドラフト動画を生成
    
    容量削減のため、720p/1Mbpsで変換
    編集テスト用の一時ファイル
    """
    try:
        result = draft_manager.create_draft(
            req.input_path, 
            req.quality, 
            req.output_name
        )
        
        if result:
            return {"success": True, "path": result}
        else:
            return {"success": False, "error": "Draft creation failed"}
    except Exception as e:
        logger.error(f"Draft creation error: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/prefinal/create")
async def create_prefinal(req: PrefinalCreateRequest):
    """
    複数のドラフトを結合して投稿前確認動画を生成
    
    通し視聴用の低容量動画
    """
    try:
        result = draft_manager.create_prefinal(
            req.draft_paths,
            req.output_name
        )
        
        if result:
            return {"success": True, "path": result}
        else:
            return {"success": False, "error": "Prefinal creation failed"}
    except Exception as e:
        logger.error(f"Prefinal creation error: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/final/create")
async def create_final(req: FinalCreateRequest):
    """
    最終出力（高画質MP4 + SRT）を生成
    
    YouTube投稿用の高品質動画
    """
    try:
        mp4_path, srt_path = draft_manager.create_final(
            req.prefinal_path,
            req.output_name,
            req.srt_path
        )
        
        if mp4_path:
            return {
                "success": True, 
                "mp4_path": mp4_path,
                "srt_path": srt_path
            }
        else:
            return {"success": False, "error": "Final output failed"}
    except Exception as e:
        logger.error(f"Final output error: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/draft/stats")
async def get_draft_stats():
    """ドラフトストレージ使用状況を取得"""
    return draft_manager.get_stats()

# ===== Cleanup Manager API (ストレージ最適化) =====
class CleanupRequest(BaseModel):
    """クリーンアップリクエスト"""
    category: str = None  # None = 全カテゴリ
    dry_run: bool = False  # True = 削除せずにプレビュー

@app.post("/api/cleanup/run")
async def run_cleanup(req: CleanupRequest = None):
    """
    一時ファイルをクリーンアップ
    
    保持期間と最大件数に基づいて古いファイルを削除
    RAW動画と最終出力は絶対に削除しない（protected）
    """
    try:
        category = req.category if req else None
        dry_run = req.dry_run if req else False
        
        result = cleanup_manager.cleanup(category, dry_run)
        
        return {
            "success": True,
            "deleted_count": len(result["deleted"]),
            "protected_count": len(result["protected"]),
            "freed_mb": round(result["freed_bytes"] / (1024 * 1024), 2),
            "dry_run": result["dry_run"],
            "details": result
        }
    except Exception as e:
        logger.error(f"Cleanup error: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/cleanup/preview")
async def preview_cleanup():
    """
    クリーンアップのプレビュー
    
    実際には削除せず、削除予定のファイルをリスト表示
    """
    return cleanup_manager.preview_cleanup()

@app.get("/api/storage/stats")
async def get_storage_stats():
    """
    ストレージ使用状況を取得
    
    カテゴリ別のファイル数、容量、保護状態を返す
    """
    return cleanup_manager.get_storage_stats()

# ===== Decision Logger API (意思決定記録・Soul Narrative統合) =====
class DecisionRequest(BaseModel):
    """意思決定記録リクエスト"""
    target_type: str  # screenshot/draft/prefinal
    target_path: str
    target_description: str
    decision: str  # approve/reject/modify
    reason: str
    scene_info: dict = None
    mood_settings: dict = None
    tags: list = None

@app.post("/api/decision/record")
async def record_decision(req: DecisionRequest):
    """
    意思決定を記録
    
    スクショやドラフトに対するユーザーの判断を記録し、
    AIが次回の提案に活用できるようにする
    """
    try:
        decision_id = decision_logger.record_decision(
            target_type=req.target_type,
            target_path=req.target_path,
            target_description=req.target_description,
            decision=req.decision,
            reason=req.reason,
            scene_info=req.scene_info,
            mood_settings=req.mood_settings,
            tags=req.tags
        )
        
        return {"success": True, "decision_id": decision_id}
    except Exception as e:
        logger.error(f"Decision record error: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/decision/context")
async def get_decision_context(target_type: str = None):
    """
    AIに渡すコンテキストを取得
    
    過去の意思決定を要約して、AIプロンプトに追加
    同じ質問の繰り返しを防止
    """
    return {
        "context": decision_logger.get_ai_context(target_type),
        "preferences": decision_logger.get_director_preferences()
    }

@app.get("/api/decision/stats")
async def get_decision_stats():
    """意思決定統計を取得"""
    return decision_logger.get_stats()

@app.post("/api/decision/sync")
async def sync_decisions():
    """
    意思決定をSoul Narrativeに同期
    
    却下理由を「こだわり」として哲学に昇華
    承認パターンを「好み」として記録
    """
    try:
        result = decision_logger.sync_to_soul_narrative()
        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Decision sync error: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/director/profile")
async def get_director_profile():
    """
    監督プロファイルを取得
    
    AIが提案する際に参照する「監督の好み・こだわり」
    """
    return decision_logger.get_director_preferences()

# ===== Auto Evolution API (自動進化システム) =====
@app.post("/api/evolution/sync")
async def sync_evolution():
    """
    全ての自動進化処理を実行
    
    1. 意思決定 → constitution.json
    2. decision_logger → evolution_log
    3. 哲学の統合チェック
    """
    try:
        from branding_manager import branding_manager
        result = branding_manager.auto_evolve_all()
        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Evolution sync error: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/evolution/status")
async def get_evolution_status():
    """
    自動進化システムのステータスを取得
    """
    try:
        from branding_manager import branding_manager
        
        evo_log = branding_manager.get_evolution_log()
        decision_stats = decision_logger.get_stats() if decision_logger else {}
        
        return {
            "constitution_version": branding_manager.constitution.get("evolution_vision", "")[:100],
            "philosophies_count": len(evo_log.get("philosophies", [])),
            "integrated_philosophy": evo_log.get("integrated_philosophy"),
            "decision_stats": decision_stats,
            "keywords_count": len(branding_manager.constitution.get("brand_personality", {}).get("keywords", [])),
            "policies_count": len(branding_manager.constitution.get("content_policy", []))
        }
    except Exception as e:
        logger.error(f"Evolution status error: {e}")
        return {"error": str(e)}

@app.post("/api/process/start")
async def start_processing(background_tasks: BackgroundTasks, req: ProcessStartRequest = None):
    """ワンクリック動画処理開始"""
    global _dashboard_state
    
    try:
        _dashboard_state = {
            "phase": "preflight",
            "progress": 0,
            "current_step": "プリフライトチェック中...",
            "preview_url": None
        }
        
        # バックグラウンドで処理を実行
        def process_task():
            global _dashboard_state
            import time
            
            # Phase 1: Preflight
            _dashboard_state["progress"] = 10
            time.sleep(1)
            
            # Phase 2: Processing
            _dashboard_state["phase"] = "processing"
            _dashboard_state["current_step"] = "動画を処理中..."
            for i in range(10, 80, 10):
                _dashboard_state["progress"] = i
                time.sleep(0.5)
            
            # Phase 3: Preview Generation
            _dashboard_state["phase"] = "preview"
            _dashboard_state["current_step"] = "プレビュー生成完了"
            _dashboard_state["progress"] = 100
            _dashboard_state["preview_url"] = "/api/video"
        
        background_tasks.add_task(process_task)
        
        return {"status": "started", "message": "処理を開始しました"}
    except Exception as e:
        _dashboard_state["phase"] = "error"
        _dashboard_state["current_step"] = f"エラー: {str(e)}"
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/approval")
async def process_approval(req: ApprovalRequest):
    """承認/却下処理"""
    global _dashboard_state
    
    try:
        if req.approved:
            _dashboard_state["phase"] = "complete"
            _dashboard_state["current_step"] = "処理完了"
            
            # 承認ログを記録
            history_manager.log_event(EventType.USER_INTERACTION, {
                "type": "DASHBOARD_APPROVAL",
                "approved": True,
                "timestamp": req.timestamp
            })
            
            return {"status": "approved", "message": "承認されました。処理を完了します。"}
        else:
            _dashboard_state["phase"] = "preview"
            _dashboard_state["current_step"] = "フィードバックを反映して再生成中..."
            
            # 却下ログを記録
            history_manager.log_event(EventType.USER_INTERACTION, {
                "type": "DASHBOARD_REJECTION",
                "approved": False,
                "feedback": req.feedback,
                "timestamp": req.timestamp
            })
            
            return {"status": "rejected", "message": "却下されました。修正を適用します。", "feedback": req.feedback}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/philosophy/list")
async def list_philosophies():
    """哲学一覧を取得"""
    try:
        evolution_log = branding_manager.get_evolution_log()
        philosophies = evolution_log.get("philosophies", [])
        
        # フォーマット変換
        formatted = []
        for i, phil in enumerate(philosophies):
            formatted.append({
                "id": f"phil_{i}",
                "content": phil.get("content", phil) if isinstance(phil, dict) else phil,
                "extractedAt": phil.get("extracted_at", "不明") if isinstance(phil, dict) else "不明",
                "session": phil.get("session", i + 1) if isinstance(phil, dict) else i + 1
            })
        
        return {"philosophies": formatted}
    except Exception as e:
        return {"philosophies": [], "error": str(e)}

# ============================================
# Phase 3: WebSocket進捗通知 (システム改善計画)
# ============================================

@app.websocket("/ws/progress")
async def websocket_progress_endpoint(websocket: WebSocket):
    """リアルタイム進捗通知WebSocket"""
    await handle_progress_websocket(websocket)

# ============================================
# Phase 11: 本番動画処理API (AI UI統合)
# ============================================

class VideoProcessRequest(BaseModel):
    """動画処理リクエスト"""
    video_paths: list = []
    mood: str = "elegant"  # elegant, dynamic, dramatic
    guest_assets: list = []
    output_name: str = "output"

@app.post("/api/video/process/start")
async def start_video_processing(background_tasks: BackgroundTasks, req: VideoProcessRequest):
    """本番動画処理を開始（video_processor統合版）"""
    import uuid
    import time
    from pathlib import Path
    
    task_id = str(uuid.uuid4())
    
    # video_processorでタスクを作成
    task = video_processor.create_task(
        task_id=task_id,
        video_paths=req.video_paths,
        mood=req.mood,
        guest_assets=req.guest_assets,
        output_name=req.output_name
    )
    
    # 互換性のため_video_tasksにも登録
    _video_tasks[task_id] = {
        "status": "starting",
        "progress": 0,
        "current_step": "初期化中...",
        "mood": req.mood,
        "video_paths": req.video_paths,
        "output_path": None,
        "preview_url": None,
        "error": None,
        "created_at": time.time()
    }
    
    def process_video_task():
        """バックグラウンドで動画処理を実行（video_processor使用）"""
        try:
            # 進捗更新コールバック
            def update_progress(t):
                _video_tasks[task_id]["status"] = t.phase.value
                _video_tasks[task_id]["progress"] = t.progress
                _video_tasks[task_id]["current_step"] = t.current_step
                _video_tasks[task_id]["output_path"] = t.output_path
                _video_tasks[task_id]["preview_url"] = t.preview_url
                _video_tasks[task_id]["error"] = t.error
                
                # WebSocket通知
                try:
                    import asyncio
                    asyncio.get_event_loop().create_task(
                        broadcaster.broadcast({
                            "type": "video_progress",
                            "task_id": task_id,
                            "phase": t.phase.value,
                            "progress": t.progress,
                            "current_step": t.current_step
                        })
                    )
                except:
                    pass
            
            video_processor.set_progress_callback(update_progress)
            
            # 動画処理実行
            success = video_processor.process_video(task_id)
            
            if success:
                logger.info(f"Video processing completed: {task_id}")
            else:
                logger.error(f"Video processing failed: {task_id}")
                
        except Exception as e:
            _video_tasks[task_id]["status"] = "error"
            _video_tasks[task_id]["error"] = str(e)
            _video_tasks[task_id]["current_step"] = f"エラー: {str(e)}"
            logger.error(f"Video processing error: {e}")
    
    background_tasks.add_task(process_video_task)
    
    # ムード設定情報を取得
    mood_settings = MOOD_SETTINGS.get(req.mood.lower(), MOOD_SETTINGS["elegant"])
    
    return {
        "task_id": task_id,
        "status": "started",
        "message": f"ムード '{mood_settings.name}' で動画処理を開始しました",
        "mood_settings": {
            "name": mood_settings.name,
            "transition": mood_settings.transition,
            "telop_style": mood_settings.telop_style
        }
    }

@app.get("/api/video/process/status/{task_id}")
async def get_video_process_status(task_id: str):
    """動画処理の進捗状況を取得"""
    if task_id not in _video_tasks:
        raise HTTPException(status_code=404, detail="タスクが見つかりません")
    return _video_tasks[task_id]

@app.get("/api/debug/video-tasks")
async def debug_video_tasks():
    """デバッグ用：_video_tasksの状態を確認"""
    return {
        "task_count": len(_video_tasks),
        "task_ids": list(_video_tasks.keys()),
        "video_tasks_id": id(_video_tasks),
        "tasks": {k: {"status": v.get("status"), "progress": v.get("progress")} for k, v in _video_tasks.items()}
    }

@app.get("/api/video/preview/{task_id}")
async def get_video_preview(task_id: str):
    """処理中/完了動画のプレビューを取得"""
    from fastapi.responses import FileResponse
    
    if task_id not in _video_tasks:
        raise HTTPException(status_code=404, detail="タスクが見つかりません")
    
    task = _video_tasks[task_id]
    
    # デモ用：既存の動画をプレビューとして返す
    demo_video = Path("raw_videos/AI Studio アップロード用動画/シーン01_前編.mp4")
    if demo_video.exists():
        return FileResponse(str(demo_video), media_type="video/mp4")
    
    return {"message": "プレビュー準備中", "progress": task.get("progress", 0)}

@app.get("/api/video/download/{task_id}")
async def download_processed_video(task_id: str):
    """処理完了動画をダウンロード"""
    from fastapi.responses import FileResponse
    
    if task_id not in _video_tasks:
        raise HTTPException(status_code=404, detail="タスクが見つかりません")
    
    task = _video_tasks[task_id]
    
    if task["status"] != "complete":
        raise HTTPException(status_code=400, detail="処理がまだ完了していません")
    
    output_path = task.get("output_path")
    if output_path and Path(output_path).exists():
        return FileResponse(output_path, media_type="video/mp4", filename=Path(output_path).name)
    
    # デモ用：既存の処理済み動画を返す
    demo_output = Path("backend/temp/fixed_unified/scene01_final.mp4")
    if demo_output.exists():
        return FileResponse(str(demo_output), media_type="video/mp4", filename="processed_video.mp4")
    
    raise HTTPException(status_code=404, detail="出力ファイルが見つかりません")

# ============================================
# Phase 12: リアルタイムプレビュー API
# ============================================

class RealtimePreviewRequest(BaseModel):
    video_path: str = ""
    mood: str = "elegant"
    duration: int = 30  # プレビュー秒数

@app.post("/api/video/realtime-preview")
async def generate_realtime_preview(background_tasks: BackgroundTasks, req: RealtimePreviewRequest):
    """リアルタイムプレビューを生成"""
    import uuid
    from preview_engine import preview_engine
    
    preview_id = str(uuid.uuid4())[:8]
    
    # 動画パスを決定
    video_path = req.video_path
    if not video_path or not Path(video_path).exists():
        # デフォルトでシーン01を使用
        demo_dir = Path("raw_videos/AI Studio アップロード用動画")
        if demo_dir.exists():
            videos = list(demo_dir.glob("*.mp4"))
            if videos:
                video_path = str(videos[0])
    
    if not video_path or not Path(video_path).exists():
        raise HTTPException(status_code=400, detail="動画ファイルが見つかりません")
    
    def generate_preview_task():
        try:
            logger.info(f"Generating realtime preview: {preview_id}")
            result = preview_engine.generate_preview(
                source_video=video_path,
                duration=req.duration
            )
            logger.info(f"Preview generated: {result}")
        except Exception as e:
            logger.error(f"Preview generation failed: {e}")
    
    background_tasks.add_task(generate_preview_task)
    
    return {
        "preview_id": preview_id,
        "status": "generating",
        "message": f"プレビュー生成中（{req.duration}秒）",
        "source": Path(video_path).name,
        "preview_url": f"/api/video/preview/{preview_id}"
    }

@app.get("/api/video/list")
async def list_available_videos():
    """処理可能な動画一覧を取得"""
    videos = []
    
    # RAW動画ディレクトリをスキャン（絶対パス使用）
    raw_dirs = [
        Path("raw_videos/AI Studio アップロード用動画"),
        Path(r"C:\Users\PC_User\Desktop\script\video-automation\raw_videos\AI Studio アップロード用動画"),
        Path("../raw_videos/AI Studio アップロード用動画"),
    ]
    
    for raw_dir in raw_dirs:
        if raw_dir.exists():
            for video in raw_dir.glob("*.mp4"):
                size_mb = video.stat().st_size / 1024 / 1024
                videos.append({
                    "name": video.name,
                    "path": str(video.absolute()),
                    "size_mb": round(size_mb, 1)
                })
            if videos:
                break
    
    return {"videos": videos, "count": len(videos)}

if __name__ == "__main__":
    import uvicorn
    print("DEBUG: Routes registered:", [route.path for route in app.routes])
    # Reverting to app object to fix path issues. Reload disabled for stability.
    # Reverting to app object to fix path issues. Reload disabled for stability.
    uvicorn.run(app, host="0.0.0.0", port=8000)
