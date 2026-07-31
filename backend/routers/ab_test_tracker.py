"""
A/Bテスト追跡ルーター - サムネイル選択履歴とCTRフィードバック

PROJECT_CONSTITUTION §5.2 Soul Narrative準拠:
- 選択履歴をevolution_logに記録
- 実CTRフィードバックで予測精度向上
"""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/thumbnail", tags=["A/B Test Tracking"])

# データ保存パス
DATA_DIR = Path(__file__).parent.parent / "data"
SELECTION_HISTORY_PATH = _writable_path("backend/data/thumbnail_selection_history.json")
CTR_FEEDBACK_PATH = DATA_DIR / "ctr_feedback_history.json"


class SelectThumbnailRequest(BaseModel):
    """サムネイル選択リクエスト"""
    video_id: str
    selected_index: int  # 0, 1, 2
    thumbnail_concepts: list[str]  # 3案のコンセプト
    predicted_ctrs: list[float]  # 予測CTR
    reason: str = ""  # 選択理由（Soul Narrative用）


class CTRFeedbackRequest(BaseModel):
    """実CTRフィードバックリクエスト"""
    video_id: str
    actual_ctr: float  # 実際のCTR（%）
    impressions: int  # インプレッション数
    clicks: int  # クリック数


class SelectionRecord(BaseModel):
    """選択履歴レコード"""
    video_id: str
    selected_at: str
    selected_index: int
    selected_concept: str
    predicted_ctr: float
    all_predicted_ctrs: list[float]
    reason: str
    actual_ctr: float | None = None
    feedback_at: str | None = None


def _load_json(path: Path) -> list[dict]:
    """JSONファイルを読み込み"""
    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []
    return []


def _save_json(path: Path, data: list[dict]):
    """JSONファイルに保存"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@router.post("/select")
async def select_thumbnail(req: SelectThumbnailRequest) -> dict[str, Any]:
    """
    サムネイル選択を記録
    
    §6 議長権限: ユーザーの選択を記録
    §5.2 Soul Narrative: 選択理由を保存
    """
    try:
        # 選択履歴を読み込み
        history = _load_json(SELECTION_HISTORY_PATH)
        
        # 新しい選択を記録
        record = {
            "video_id": req.video_id,
            "selected_at": datetime.now().isoformat(),
            "selected_index": req.selected_index,
            "selected_concept": req.thumbnail_concepts[req.selected_index] if 0 <= req.selected_index < len(req.thumbnail_concepts) else "",
            "predicted_ctr": req.predicted_ctrs[req.selected_index] if 0 <= req.selected_index < len(req.predicted_ctrs) else 0.0,
            "all_predicted_ctrs": req.predicted_ctrs,
            "all_concepts": req.thumbnail_concepts,
            "reason": req.reason,
            "actual_ctr": None,
            "feedback_at": None
        }
        
        history.append(record)
        _save_json(SELECTION_HISTORY_PATH, history)
        
        logger.info(f"Thumbnail selection recorded: video_id={req.video_id}, index={req.selected_index}")
        
        return {
            "success": True,
            "record": record,
            "message": "サムネイル選択を記録しました"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Thumbnail selection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/feedback")
async def record_ctr_feedback(req: CTRFeedbackRequest) -> dict[str, Any]:
    """
    実CTRフィードバックを記録
    
    予測精度向上に活用
    """
    try:
        # 選択履歴から該当動画を検索
        history = _load_json(SELECTION_HISTORY_PATH)
        
        updated = False
        for record in history:
            if record["video_id"] == req.video_id and record.get("actual_ctr") is None:
                record["actual_ctr"] = req.actual_ctr
                record["impressions"] = req.impressions
                record["clicks"] = req.clicks
                record["feedback_at"] = datetime.now().isoformat()
                
                # 予測誤差を計算
                predicted = record.get("predicted_ctr", 0)
                record["prediction_error"] = abs(req.actual_ctr - predicted)
                
                updated = True
                break
        
        if updated:
            _save_json(SELECTION_HISTORY_PATH, history)
            
            # 予測精度分析
            accuracy = _analyze_prediction_accuracy(history)
            
            logger.info(f"CTR feedback recorded: video_id={req.video_id}, actual_ctr={req.actual_ctr}%")
            
            return {
                "success": True,
                "message": "CTRフィードバックを記録しました",
                "prediction_accuracy": accuracy
            }
        else:
            return {
                "success": False,
                "message": "該当する動画が見つかりませんでした"
            }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"CTR feedback failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def get_selection_history(limit: int = 20) -> dict[str, Any]:
    """選択履歴を取得"""
    try:
        history = _load_json(SELECTION_HISTORY_PATH)
        
        # 最新順でソート
        history.sort(key=lambda x: x.get("selected_at", ""), reverse=True)
        
        return {
            "success": True,
            "total": len(history),
            "history": history[:limit]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get history failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/accuracy")
async def get_prediction_accuracy() -> dict[str, Any]:
    """予測精度を取得"""
    try:
        history = _load_json(SELECTION_HISTORY_PATH)
        accuracy = _analyze_prediction_accuracy(history)
        
        return {
            "success": True,
            "accuracy": accuracy
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get accuracy failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _analyze_prediction_accuracy(history: list[dict]) -> dict[str, Any]:
    """予測精度を分析"""
    # フィードバック済みのレコードのみ抽出
    with_feedback = [r for r in history if r.get("actual_ctr") is not None]
    
    if not with_feedback:
        return {
            "sample_size": 0,
            "message": "フィードバックデータがまだありません"
        }
    
    # 予測誤差の統計
    errors = [abs(r["actual_ctr"] - r["predicted_ctr"]) for r in with_feedback if "predicted_ctr" in r]
    
    if not errors:
        return {
            "sample_size": len(with_feedback),
            "message": "予測CTRデータがありません"
        }
    
    avg_error = sum(errors) / len(errors)
    max_error = max(errors)
    min_error = min(errors)
    
    # 選択されたサムネイルが最高CTRだった割合
    correct_predictions = 0
    valid_samples = 0
    for r in with_feedback:
        ctrs = r.get("all_predicted_ctrs")
        if isinstance(ctrs, list) and ctrs and r.get("selected_index") is not None:
            if all(isinstance(x, (int, float)) for x in ctrs):
                predicted_best = ctrs.index(max(ctrs))
                valid_samples += 1
                if predicted_best == r["selected_index"]:
                    correct_predictions += 1
    
    return {
        "sample_size": len(with_feedback),
        "average_error": round(avg_error, 2),
        "max_error": round(max_error, 2),
        "min_error": round(min_error, 2),
        "correct_prediction_rate": round(correct_predictions / valid_samples * 100, 1) if valid_samples else 0
    }


@router.get("/health")
async def health_check() -> dict[str, str]:
    """ヘルスチェック"""
    return {"status": "ok", "service": "ab_test_tracker"}
