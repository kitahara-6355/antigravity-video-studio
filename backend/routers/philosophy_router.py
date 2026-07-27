"""
Philosophy Router - 哲学/Soul Narrative APIルーター

推奨タスク3: main.pyルーター分割
Soul Narrative関連のエンドポイントを独立モジュール化
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import logging
import sys
import os

# パス追加（backendディレクトリをモジュールパスに追加）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from branding_manager import branding_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/philosophy", tags=["Philosophy"])


class PhilosophyEntry(BaseModel):
    content: str
    source: str = "user"


def _format_philosophy_entry(index: int, raw_entry: any) -> dict:
    """
    個々の演出哲学エントリーをAPIレスポンス用にフォーマットする。

    Args:
        index (int): 演出哲学エントリーのインデックス
        raw_entry (any): 演出哲学エントリーデータ（dict型またはその他）

    Returns:
        dict: フォーマット済みの演出哲学データ
    """
    if isinstance(raw_entry, dict):
        return {
            "id": f"phil_{index}",
            "content": raw_entry.get("content", str(raw_entry)),
            "extractedAt": raw_entry.get("extracted_at", "不明"),
            "session": raw_entry.get("session", index + 1)
        }
    return {
        "id": f"phil_{index}",
        "content": str(raw_entry),
        "extractedAt": "不明",
        "session": index + 1
    }


@router.get("/list")
async def list_philosophies():
    """
    登録されている演出哲学（Soul Narrative）の一覧を取得する。

    Returns:
        dict: 演出哲学エントリーのリストを含む辞書

    Raises:
        HTTPException: HTTP例外が発生した場合にそのまま再スローされる
    """
    try:
        evolution_log = branding_manager.get_evolution_log()
        philosophies = evolution_log.get("philosophies", [])
        
        formatted_entries = [
            _format_philosophy_entry(i, raw_entry)
            for i, raw_entry in enumerate(philosophies)
        ]
        
        return {"philosophies": formatted_entries}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Philosophy list error: {e}")
        return {"philosophies": [], "error": str(e)}


@router.post("/add")
async def add_philosophy(entry: PhilosophyEntry):
    """
    新しい演出哲学エントリーを追加する。

    Args:
        entry (PhilosophyEntry): 追加する演出哲学エントリーの情報

    Returns:
        dict: 追加ステータスと追加されたエントリー情報

    Raises:
        HTTPException: HTTP例外が発生した場合にそのまま再スローされる
        HTTPException(500): データベースやファイル保存中に一般例外が発生した場合
    """
    try:
        new_philosophy_entry = {
            "content": entry.content,
            "source": entry.source,
            "extracted_at": datetime.now().isoformat()
        }
        
        # evolution_logに追加
        evolution_log = branding_manager.get_evolution_log()
        if "philosophies" not in evolution_log:
            evolution_log["philosophies"] = []
        evolution_log["philosophies"].append(new_philosophy_entry)
        branding_manager.save_evolution_log(evolution_log)
        
        return {"status": "added", "philosophy": new_philosophy_entry}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Philosophy add error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_philosophy_summary():
    """
    蓄積された演出哲学のサマリー情報（総件数、最新のエントリーなど）を取得する。

    Returns:
        dict: サマリー情報（total_count, latest, summary）を含む辞書

    Raises:
        HTTPException: HTTP例外が発生した場合にそのまま再スローされる
    """
    try:
        evolution_log = branding_manager.get_evolution_log()
        philosophies = evolution_log.get("philosophies", [])
        
        return {
            "total_count": len(philosophies),
            "latest": philosophies[-1] if philosophies else None,
            "summary": f"{len(philosophies)}件の演出哲学が蓄積されています。"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Philosophy summary error: {e}")
        return {"error": str(e)}

