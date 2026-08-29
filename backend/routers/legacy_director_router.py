"""
Legacy Director Router — ユニークエンドポイントのみ残存 (Phase C)

v4.0 director.py と重複していたエンドポイントは削除済み。

残存ユニークエンドポイント:
- GET  /api/director/tasks/{task_id}  — 非同期タスク状態確認
- GET  /api/director/state            — Director State 取得
- POST /api/director/state            — Director State 保存
- POST /api/director/verify-quality   — 最終品質チェック
- GET  /api/director/evolution        — 成長ナラティブログ
- GET  /api/director/profile          — 監督プロファイル

削除済み（v4.0 routers/director.py に移行済み）:
  chat, generate-image, generate-image-async, analyze-script,
  quality-score, analyze-resources, generate-report,
  plan-storyboard, batch-generate
"""

import os
import json
import asyncio

from fastapi import APIRouter, HTTPException, Request

from director_engine import brain, task_manager
from branding_manager import branding_manager

router = APIRouter(tags=["Director Legacy"])

# --- Path setup ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(BASE_DIR, "src")
SCENES_PATH = os.path.join(SRC_DIR, "scenes_data.json")


# --- ユニークエンドポイントのみ残存 ---

def _write_scenes_state(data: dict) -> None:
    """シーン状態データを JSON ファイルに書き込むヘルパー関数"""
    with open(SCENES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _execute_quality_verification(data: dict) -> dict:
    """品質検証処理を実行し、結果を JSON デコードするヘルパー関数"""
    result_json = brain.verify_production_quality(
        data.get("full_text", ""),
        data.get("scenes", []),
        data.get("segments", [])
    )
    return json.loads(result_json)


@router.get("/api/director/tasks/{task_id}")
def get_director_task_status(task_id: str):
    """タスクの状態確認（ユニーク）"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


# --- Director State Persistence ---

@router.get("/api/director/state")
def get_director_state():
    """Returns the saved Director State (scenes, audio)."""
    default_state = {"scenes": [], "audioConfig": None}
    if not os.path.exists(SCENES_PATH):
        return default_state
    try:
        with open(SCENES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default_state


@router.post("/api/director/state")
async def save_director_state(request: Request):
    """Saves the Director State."""
    try:
        data = await request.json()
    except json.JSONDecodeError as je:
        raise HTTPException(status_code=400, detail=f"Malformed JSON: {je}")

    try:
        from project_archiver import project_archiver
        project_archiver.save_snapshot(label="auto_before_save")
        await asyncio.to_thread(_write_scenes_state, data)
        return {"status": "success"}
    except (OSError, ValueError, RuntimeError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/director/verify-quality")
async def verify_quality(request: Request):
    """Performs final quality check before render."""
    try:
        data = await request.json()
    except json.JSONDecodeError as je:
        raise HTTPException(status_code=400, detail=f"Malformed JSON: {je}")

    try:
        return await asyncio.to_thread(_execute_quality_verification, data)
    except (json.JSONDecodeError, ValueError, TypeError, RuntimeError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/director/evolution")
def get_evolution():
    """Returns the qualitative growth narrative log.

    **`GET /api/evolution` と同じ読み口を使う**（R1.5-C4・6周目 指摘1）。
    `post_publish_feedbacks` に焼き付いた作り物の「実績」への印は
    `branding_manager.get_evolution_log_for_display()` に1箇所だけ置いてある。
    """
    return branding_manager.get_evolution_log_for_display()


@router.get("/api/director/profile")
def get_director_profile():
    """監督プロファイルを取得"""
    from decision_logger import decision_logger
    return decision_logger.get_director_preferences()
