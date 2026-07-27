"""
Phase 23: Manager Monitoring
管理者がチャンネル主の状態をリアルタイムで監視するためのエンドポイント
"""
import asyncio
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# 疲労度計算およびアラートに関する定数
MAX_FATIGUE_SCORE = 100
MIN_FATIGUE_SCORE = 0
FATIGUE_ALERT_HIGH_THRESHOLD = 70
FATIGUE_ALERT_MID_THRESHOLD = 50
FATIGUE_TIRED_INCREMENT = 15
FATIGUE_NEUTRAL_INCREMENT = 5
FATIGUE_POSITIVE_DECREMENT = 10

# 簡易的な状態ストア（本番では Redis や Database を使用）
owner_status_store = {
    "last_login": None,
    "session_count": 0,
    "interaction_count": 0,
    "last_interaction_tone": "neutral",  # positive, neutral, tired
    "fatigue_score": 0,  # 0-100
}

# 状態ストア更新用の非同期ロック
owner_status_lock = asyncio.Lock()


class OwnerStatus(BaseModel):
    last_login: Optional[datetime]
    session_count: int
    interaction_count: int
    last_interaction_tone: str
    fatigue_score: int
    alert_message: Optional[str] = None


def _calculate_alert_message(fatigue_score: int) -> Optional[str]:
    """
    疲労度スコアに基づいてアラートメッセージを算出
    """
    if fatigue_score > FATIGUE_ALERT_HIGH_THRESHOLD:
        return "⚠️ お母様が疲れている可能性があります。休憩を促してください。"
    elif fatigue_score > FATIGUE_ALERT_MID_THRESHOLD:
        return "📊 集中力が低下しています。サポートの準備をしてください。"
    return None


def _calculate_new_fatigue_score(tone: str, current_fatigue: int) -> int:
    """
    入力されたトーンと現在の疲労度スコアから新しい疲労度スコアを算出
    """
    if isinstance(current_fatigue, bool) or not isinstance(current_fatigue, (int, float)):
        raise TypeError("current_fatigue must be a number")

    if not (MIN_FATIGUE_SCORE <= current_fatigue <= MAX_FATIGUE_SCORE):
        raise ValueError(f"current_fatigue must be between {MIN_FATIGUE_SCORE} and {MAX_FATIGUE_SCORE}")

    if tone == "tired":
        return min(MAX_FATIGUE_SCORE, int(current_fatigue + FATIGUE_TIRED_INCREMENT))
    elif tone == "neutral":
        return min(MAX_FATIGUE_SCORE, int(current_fatigue + FATIGUE_NEUTRAL_INCREMENT))
    elif tone == "positive":
        return max(MIN_FATIGUE_SCORE, int(current_fatigue - FATIGUE_POSITIVE_DECREMENT))
    else:
        raise ValueError(f"Invalid tone: {tone}")


@router.get("/api/manager/status", response_model=OwnerStatus)
async def get_owner_status():
    """
    チャンネル主（お母様）の現在のステータスを取得
    """
    try:
        async with owner_status_lock:
            status = owner_status_store.copy()

        # 疲労度に応じたアラート生成
        alert = _calculate_alert_message(status["fatigue_score"])

        return OwnerStatus(
            last_login=status["last_login"],
            session_count=status["session_count"],
            interaction_count=status["interaction_count"],
            last_interaction_tone=status["last_interaction_tone"],
            fatigue_score=status["fatigue_score"],
            alert_message=alert
        )
    except KeyError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Store integrity error: missing key {str(e)}"
        )
    except TypeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Store type error: {str(e)}"
        )


@router.post("/api/manager/update")
async def update_owner_status(
    tone: str = "neutral",
    increment_interaction: bool = True
):
    """
    チャンネル主の対話ごとに状態を更新
    """
    if tone not in ("tired", "neutral", "positive"):
        raise HTTPException(
            status_code=400,
            detail="Invalid tone value. Must be 'tired', 'neutral', or 'positive'."
        )

    try:
        async with owner_status_lock:
            if increment_interaction:
                owner_status_store["interaction_count"] += 1

            owner_status_store["last_interaction_tone"] = tone
            owner_status_store["last_login"] = datetime.now(timezone.utc)

            # 疲労スコア計算
            new_fatigue = _calculate_new_fatigue_score(tone, owner_status_store["fatigue_score"])
            owner_status_store["fatigue_score"] = new_fatigue
            current_fatigue = new_fatigue
    except KeyError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Store integrity error: missing key {str(e)}"
        )
    except TypeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Store type error: {str(e)}"
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid value error: {str(e)}"
        )

    return {"status": "updated", "current_fatigue": current_fatigue}

