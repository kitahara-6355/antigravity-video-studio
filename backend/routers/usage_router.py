"""
Usage Router - 使用量APIエンドポイント

PROJECT_CONSTITUTION §18 準拠:
- 使用量ダッシュボード表示
- アラート状態確認
- 残り枠の可視化
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any
import os

# UX-04: get_model が未インポートで /api/usage/dashboard が 500 エラーになっていた
try:
    from model_registry import get_model
except ImportError:
    def get_model(task: str) -> str:
        """モデル名を取得するフォールバック関数

        Args:
            task (str): タスク名。

        Returns:
            str: 常に 'gemini-2.5-flash' を返す。
        """
        return "gemini-2.5-flash"

router = APIRouter(prefix="/api/usage", tags=["Usage"])


def _format_dashboard_models_and_alerts(summary: Dict[str, Any]) -> tuple[list, list]:
    """ダッシュボード用のモデル情報とアラートリストをフォーマットします。

    Args:
        summary (Dict[str, Any]): 使用量トラッカーから取得した日次サマリー情報。

    Returns:
        tuple[list, list]: フォーマットされたモデル情報のリストとアラート情報のリスト。
    """
    models = []
    alerts = []
    for model, data in summary.get("models", {}).items():
        model_info = {
            "name": model,
            "tier": _get_tier_label(model),
            "used": data["used"],
            "limit": data["limit"],
            "remaining": data["remaining"],
            "usage_percent": round(data["usage_ratio"] * 100, 1),
            "alert_level": data["alert_level"],
            "can_use": data["alert_level"] not in ["block", "critical"]
        }
        models.append(model_info)
        
        if data["alert_level"] in ["warning", "block", "critical"]:
            alerts.append({
                "model": model,
                "level": data["alert_level"],
                "message": _get_alert_message(model, data)
            })
    return models, alerts


def _generate_dashboard_recommendations(summary: Dict[str, Any]) -> list[str]:
    """ダッシュボード用の推奨事項を生成します。

    Args:
        summary (Dict[str, Any]): 使用量トラッカーから取得した日次サマリー情報。

    Returns:
        list[str]: 推奨事項を表す文字列のリスト。
    """
    recommendations = []
    for model, data in summary.get("models", {}).items():
        if data["alert_level"] == "critical":
            recommendations.append(f"{model}の日次枠を使い切りました。翌日まで待つか課金を検討してください。")
        elif data["alert_level"] == "warning":
            recommendations.append(f"{model}の残り枠が少なくなっています。節約モードの利用を推奨します。")
    if not recommendations:
        recommendations.append("すべてのモデルが正常範囲内です。")
    return recommendations


@router.get("/dashboard")
async def get_usage_dashboard() -> Dict[str, Any]:
    """使用量ダッシュボード情報を取得します。

    フロントエンドで残り枠を可視化するためのエンドポイントです。

    Returns:
        Dict[str, Any]: ダッシュボード用の日付、モデル情報、アラート、推奨事項を含む辞書。
            エラー発生時には、警告メッセージを含むデフォルトの空データ構造を返します。

    Raises:
        HTTPException: HTTP関連のエラーが発生した場合。
    """
    try:
        from usage_tracker import usage_tracker
        
        summary = usage_tracker.get_daily_summary()
        
        models, alerts = _format_dashboard_models_and_alerts(summary)
        recommendations = _generate_dashboard_recommendations(summary)
        
        return {
            "date": summary["date"],
            "models": models,
            "alerts": alerts,
            "recommendations": recommendations
        }
    except HTTPException:
        raise
    except Exception as e:
        # UX-04: エラーでも空のダッシュボードを返しフロントエンドが機能する
        import logging
        logging.getLogger(__name__).warning(f"Dashboard API error: {e}")
        return {
            "date": "",
            "models": [],
            "alerts": [{"level": "warning", "message": f"使用量データの取得に失敗: {str(e)[:100]}"}],
            "recommendations": []
        }


@router.get("/remaining/{model_name}")
async def get_remaining_requests(model_name: str) -> Dict[str, Any]:
    """特定モデルの残りリクエスト数を取得します。

    Args:
        model_name (str): 残りリクエスト数を確認するモデルの名前。

    Returns:
        Dict[str, Any]: モデル名、残りリクエスト数、利用可能フラグ、使用率パーセント、警告フラグを含む辞書。
    """
    from usage_tracker import usage_tracker
    
    remaining = usage_tracker.get_remaining_requests(model_name)
    can_use = usage_tracker.can_make_request(model_name)
    usage_ratio = usage_tracker.get_usage_ratio(model_name)
    
    return {
        "model": model_name,
        "remaining": remaining,
        "can_use": can_use,
        "usage_percent": round(usage_ratio * 100, 1),
        "warning": not can_use or usage_ratio > 0.8
    }


def _format_tier_budget(model_name: str, tier_data: Dict[str, Any], estimated_divide: int, warning_threshold: int) -> Dict[str, Any]:
    """各ティアの予算情報をフォーマットします。

    Args:
        model_name (str): モデルの名前。
        tier_data (Dict[str, Any]): ティアのメタデータ。
        estimated_divide (int): 残り枠から見積もりリトライ回数を算出するための除数。
        warning_threshold (int): 警告を表示する残りリクエスト数の閾値。

    Returns:
        Dict[str, Any]: フォーマットされた予算情報（モデル名、残りリクエスト数、見積もりリトライ回数、使用率パーセント、警告フラグ）。
    """
    remaining = tier_data.get("remaining", 0)
    return {
        "model": model_name,
        "remaining_requests": remaining,
        "estimated_retries": remaining // estimated_divide,
        "usage_percent": round(tier_data.get("usage_ratio", 0) * 100, 1),
        "warning": remaining < warning_threshold
    }


@router.get("/retry-budget")
async def get_retry_budget() -> Dict[str, Any]:
    """やり直し予算を取得します。

    ユーザーが「何回やり直しできるか」を把握するための情報です。

    Returns:
        Dict[str, Any]: プレミアムとスタンダード各ティアの見積もりやり直し予算およびアドバイスを含む辞書。
            エラー発生時には、警告アドバイスを含むデフォルトの予算情報を返します。

    Raises:
        HTTPException: HTTP関連のエラーが発生した場合。
    """
    try:
        from usage_tracker import usage_tracker
        
        summary = usage_tracker.get_daily_summary()
        
        premium_model = get_model("quality_gate")
        standard_model = get_model("proofreader")
        
        premium = summary["models"].get(premium_model, {})
        standard = summary["models"].get(standard_model, {})
        
        premium_remaining = premium.get("remaining", 0)
        standard_remaining = standard.get("remaining", 0)
        
        retry_budget = {
            "premium": _format_tier_budget(premium_model, premium, estimated_divide=2, warning_threshold=10),
            "standard": _format_tier_budget(standard_model, standard, estimated_divide=3, warning_threshold=50),
            "advice": _get_retry_advice(premium_remaining, standard_remaining)
        }
        
        return retry_budget
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Retry budget error: {e}")
        return {
            "premium": {"estimated_retries": 0, "warning": True},
            "standard": {"estimated_retries": 0, "warning": True},
            "advice": f"予算データの取得に失敗: {str(e)[:80]}"
        }


@router.get("/quality-warning")
async def get_quality_warning() -> Dict[str, Any]:
    """品質低下警告を取得します。

    高品質モデルの枠が切れている場合に警告を返します。

    Returns:
        Dict[str, Any]: 警告の有無、警告レベル、警告メッセージ、推奨アクションを含む辞書。
    """
    from usage_tracker import usage_tracker
    
    premium_can_use = usage_tracker.can_make_request(get_model("quality_gate"))
    premium_ratio = usage_tracker.get_usage_ratio(get_model("quality_gate"))
    
    if not premium_can_use:
        return {
            "warning": True,
            "level": "critical",
            "message": "⚠️ 高品質モデル(gemini-2.5-flash)の日次枠を使い切りました。品質が低下する可能性があります。",
            "suggestion": "やり直しを明日に延期するか、標準モデルでの処理を許容してください。"
        }
    elif premium_ratio > 0.8:
        return {
            "warning": True,
            "level": "warning",
            "message": f"⚠️ 高品質モデルの残り枠が{(1-premium_ratio)*100:.0f}%です。",
            "suggestion": "やり直し回数を抑えるか、重要な処理に優先的に使用してください。"
        }
    
    return {
        "warning": False,
        "level": "normal",
        "message": "高品質モデルは正常に利用可能です。"
    }


def _get_tier_label(model: str) -> str:
    """モデルのティアラベルを model_config.json から動的に取得します。

    Args:
        model (str): ラベルを取得したいモデル名。

    Returns:
        str: 取得されたティアラベル。見つからない場合は "Unknown"。

    Raises:
        HTTPException: HTTP関連のエラーが発生した場合。
    """
    try:
        import json
        from pathlib import Path
        config_path = Path(__file__).parent.parent / "model_config.json"
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        tiers = config.get("text_generation", {}).get("tiers", {})
        for tier_name, tier_info in tiers.items():
            if tier_info.get("model") == model:
                return tier_info.get("label", tier_name.capitalize())
    except HTTPException:
        raise
    except Exception:
        pass
    return "Unknown"


def _get_alert_message(model: str, data: Dict[str, Any]) -> str:
    """アラートメッセージを生成します。

    Args:
        model (str): アラートが発生しているモデルの名前。
        data (Dict[str, Any]): アラートレベルと残り枠数を含むモデルデータ。

    Returns:
        str: 生成されたアラートメッセージ。アラートレベルが normal の場合は空文字列。
    """
    level = data["alert_level"]
    remaining = data["remaining"]
    
    if level == "critical":
        return f"{model}の日次枠を使い切りました。翌日まで使用できません。"
    elif level == "block":
        return f"{model}の残り枠が{remaining}件です。処理がブロックされます。"
    elif level == "warning":
        return f"{model}の残り枠が{remaining}件です。使用を控えてください。"
    return ""





def _get_retry_advice(premium_remaining: int, standard_remaining: int) -> str:
    """やり直しアドバイスを生成します。

    Args:
        premium_remaining (int): プレミアムモデルの残りリクエスト数。
        standard_remaining (int): スタンダードモデルの残りリクエスト数。

    Returns:
        str: 残りリクエスト数に応じたアドバイス文言。
    """
    if premium_remaining < 5:
        return "⚠️ 高品質モデルの残りが少なくなっています。やり直しは慎重に行ってください。"
    elif premium_remaining < 20:
        return "高品質モデルの残りに注意しながら作業を進めてください。"
    else:
        return "十分な余裕があります。通常通り作業を続けてください。"


@router.get("/model-status")
async def get_all_models_status() -> Dict[str, Any]:
    """全モデルのステータスを取得します。

    各モデルの利用可能状況、フォールバック先を返します。

    Returns:
        Dict[str, Any]: 全モデルのステータス情報を含む辞書。
    """
    from usage_tracker import quota_manager
    
    return quota_manager.get_all_models_status()


@router.get("/switch-history")
async def get_switch_history(limit: int = 10) -> Dict[str, Any]:
    """モデル切換え履歴を取得します。

    自動切換えが発生した履歴を返します。

    Args:
        limit (int): 取得する履歴の最大件数。デフォルトは 10。

    Returns:
        Dict[str, Any]: 履歴件数と履歴リストを含む辞書。
    """
    from usage_tracker import quota_manager
    
    history = quota_manager.get_switch_history(limit)
    
    return {
        "count": len(history),
        "history": history
    }


@router.post("/get-model")
async def get_available_model(preferred_model: str, task: str = "") -> Dict[str, Any]:
    """利用可能なモデルを取得します。

    優先モデルが使用できない場合は自動でフォールバックします。
    切換えが発生した場合は通知情報も返します。

    Args:
        preferred_model (str): 優先して使用したいモデルの名前。
        task (str, optional): タスク名。デフォルトは空文字列。

    Returns:
        Dict[str, Any]: 利用可能なモデルの名前やフォールバック通知情報を含む辞書。
    """
    from usage_tracker import quota_manager
    
    result = quota_manager.get_available_model(preferred_model, task)
    
    return result


@router.get("/current-model/{task}")
async def get_current_model_for_task(task: str) -> Dict[str, Any]:
    """タスクに対する現在利用可能なモデルを取得します。

    Args:
        task (str): タスク名（quality_gate, director, subtitle, telop, batch, thumbnail）。

    Returns:
        Dict[str, Any]: タスク名、優先モデル名、および実際に利用可能なモデルの情報を含む辞書。

    Raises:
        HTTPException: HTTP関連のエラーが発生した場合。
    """
    from usage_tracker import usage_tracker, quota_manager
    
    # タスク→優先モデルマッピング（model_registry から動的取得）
    try:
        from model_registry import get_model
        preferred = get_model(task)
    except HTTPException:
        raise
    except Exception:
        preferred = "gemini-2.5-flash"
    
    result = quota_manager.get_available_model(preferred, task)
    result["task"] = task
    result["preferred_model"] = preferred
    return result


@router.get("/two-tier-status")
async def get_two_tier_status() -> Dict[str, Any]:
    """2段階モデル方式のステータスを取得します。

    Premium（最上位）とStandard（中位）の状態を返します。

    Returns:
        Dict[str, Any]: 2段階モデル方式の各ティアのステータス情報を含む辞書。
    """
    from usage_tracker import quota_manager
    
    return quota_manager.get_two_tier_status()


@router.get("/wait-options")
async def get_wait_options(tier: str = "premium") -> Dict[str, Any]:
    """待機オプションを取得します。

    モデル枠が回復するまでの時間と選択肢を返します。

    Args:
        tier (str): 対象のティア（"premium" または "standard"）。デフォルトは "premium"。

    Returns:
        Dict[str, Any]: ティア名、現在のステータス、リセット情報、推奨事項を含む辞書。
    """
    from usage_tracker import quota_manager
    
    result = quota_manager.get_model_with_wait_option(tier, allow_fallback=True)
    reset_info = quota_manager.get_time_until_reset()
    
    return {
        "tier": tier,
        "current_status": result,
        "reset_info": reset_info,
        "recommendations": _get_wait_recommendations(tier, result, reset_info)
    }


@router.post("/select-option")
async def select_model_option(
    tier: str = "premium",
    option: str = "auto"
) -> Dict[str, Any]:
    """モデルオプションを選択します。

    Args:
        tier (str): 対象のティア（"premium" または "standard"）。デフォルトは "premium"。
        option (str): 選択するオプション（"wait" | "fallback" | "force" | "auto"）。デフォルトは "auto"。

    Returns:
        Dict[str, Any]: 選択結果のアクション、メッセージ、使用するモデル名などを含む辞書。
    """
    from usage_tracker import quota_manager
    
    result = quota_manager.get_model_with_wait_option(tier, allow_fallback=(option != "wait"))
    
    if option == "wait":
        reset_info = quota_manager.get_time_until_reset()
        return {
            "action": "wait",
            "message": f"リセットまで待機してください: {reset_info['remaining_display']}",
            "reset_time": reset_info["reset_time_jst"],
            "model": None
        }
    elif option == "force":
        if result.get("available") or result.get("options", {}).get("force", {}).get("available"):
            return {
                "action": "force",
                "message": f"Premiumモデルを使用します",
                "model": quota_manager.MODEL_TIERS.get(tier, {}).get("model"),
                "warning": "温存枠を使用します。残り回数に注意してください。"
            }
        else:
            return {
                "action": "error",
                "message": "Premiumモデルの枠がありません",
                "model": None
            }
    elif option == "fallback":
        fallback = quota_manager.FALLBACK_CHAIN.get(
            quota_manager.MODEL_TIERS.get(tier, {}).get("model")
        )
        return {
            "action": "fallback",
            "message": f"Standardモデル({fallback})を使用します",
            "model": fallback,
            "quality_impact": "品質が低下する可能性があります"
        }
    else:  # auto
        return {
            "action": "auto",
            "message": "自動選択されたモデルを使用します",
            "model": result.get("model"),
            "tier": result.get("tier")
        }


def _get_wait_recommendations(tier: str, status: Dict[str, Any], reset_info: Dict[str, Any]) -> list[Dict[str, Any]]:
    """待機に関する推奨事項を生成します。

    Args:
        tier (str): 対象のティア（"premium" または "standard"）。
        status (Dict[str, Any]): 現在のモデルステータス情報。
        reset_info (Dict[str, Any]): リセットまでの時間情報。

    Returns:
        list[Dict[str, Any]]: 推奨事項を表す辞書のリスト。
    """
    recommendations = []
    
    if not status.get("available"):
        if reset_info.get("remaining_hours", 24) <= 2:
            recommendations.append({
                "type": "wait",
                "priority": "high",
                "message": f"あと{reset_info['remaining_display']}で枠がリセットされます。待機をお勧めします。"
            })
        elif reset_info.get("remaining_hours", 24) <= 6:
            recommendations.append({
                "type": "consider",
                "priority": "medium",
                "message": "数時間待てば枠がリセットされます。緊急でなければ待機を検討してください。"
            })
        else:
            recommendations.append({
                "type": "fallback",
                "priority": "medium",
                "message": "リセットまで時間があります。Standardモデルでの作業を検討してください。"
            })
    else:
        remaining = status.get("remaining", 0)
        if remaining < 10:
            recommendations.append({
                "type": "caution",
                "priority": "high",
                "message": f"残り{remaining}回です。やり直し回数を抑えてください。"
            })
    
    return recommendations


# ============================================================
# モデルガバナンス管理エンドポイント
# ============================================================

@router.get("/governance")
async def get_governance_status() -> Dict[str, Any]:
    """モデルガバナンス統合ダッシュボード（管理者向け）を取得します。

    1つの API で以下をすべて確認可能です：
    - 3グレード構成 + グレード方針 (model_config.json)
    - 各モデルの残枠・使用率・アラートレベル (usage_tracker)
    - フォールバックチェーン、deprecated 差替情報、カウンター等 (model_governance)
    - 直近のイベントログ

    Returns:
        Dict[str, Any]: グレード方針、ティア構成、使用量、フォールバックチェーン、
            各種カウンター（差替回数、エラー数等）、最近のイベントを含む辞書。
            各モジュールのインポートエラーや設定ファイル不在時は、一部のデータが
            空オブジェクト（フォールバック）として返されます。

    Raises:
        HTTPException: HTTP関連のエラーが発生した場合。
    """
    # === ガバナンス統計 ===
    try:
        from model_governance import model_governance
        gov_stats = model_governance.get_stats()
    except ImportError:
        gov_stats = {}

    # === model_config.json から構成情報 ===
    tiers = {}
    grade_policy = {}
    try:
        import json
        from pathlib import Path
        config_path = Path(__file__).parent.parent / "model_config.json"
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        text_gen = config.get("text_generation", {})
        for tier_name, tier_info in text_gen.get("tiers", {}).items():
            tiers[tier_name] = {
                "model": tier_info.get("model"),
                "label": tier_info.get("label"),
                "description": tier_info.get("description"),
            }
        grade_policy = config.get("grade_policy", {})
    except HTTPException:
        raise
    except Exception:
        pass

    # === 使用量ダッシュボード ===
    usage = {}
    try:
        from usage_tracker.tracker import usage_tracker
        summary = usage_tracker.get_daily_summary()
        usage = {
            "date": summary.get("date"),
            "models": summary.get("models", {}),
        }
    except HTTPException:
        raise
    except Exception:
        pass

    return {
        "grade_policy": grade_policy,
        "tiers": tiers,
        "usage": usage,
        "fallback_chain": gov_stats.get("fallback_chain", {}),
        "deprecation_map": gov_stats.get("deprecation_map", {}),
        "counters": {
            "deprecation_corrections": gov_stats.get("deprecation_corrections", 0),
            "fallback_activations": gov_stats.get("fallback_activations", 0),
            "total_api_errors": gov_stats.get("total_api_errors", 0),
        },
        "recent_events": gov_stats.get("recent_events", []),
    }


@router.post("/governance/reload")
async def reload_governance_config() -> Dict[str, Any]:
    """model_config.json を再読込します（管理者操作）。

    新モデルの追加やグレード変更を即座に反映するため、
    モデルガバナンスおよびモデルレジストリの設定ファイルを再読込します。

    Returns:
        Dict[str, Any]: ガバナンスおよびレジストリの再読込結果ステータスを含む辞書。
            エラー発生時には、各コンポーネントの status に "error" とエラー詳細メッセージが返されます。

    Raises:
        HTTPException: HTTP関連のエラーが発生した場合。
    """
    results = {}

    # ガバナンスエンジン再読込
    try:
        from model_governance import model_governance
        model_governance.reload()
        stats = model_governance.get_stats()
        results["governance"] = {
            "status": "reloaded",
            "fallback_chain": stats.get("fallback_chain", {}),
        }
    except HTTPException:
        raise
    except Exception as e:
        results["governance"] = {"status": "error", "message": str(e)}

    # モデルレジストリ再読込
    try:
        from model_registry import ModelRegistry
        registry = ModelRegistry()
        registry._load_config()
        results["registry"] = {"status": "reloaded"}
    except HTTPException:
        raise
    except Exception as e:
        results["registry"] = {"status": "error", "message": str(e)}

    results["status"] = "reloaded"
    return results



# ============================================================
# サムネイル生成 & 品質検証 API (legacy_management_router から移行)
# ============================================================

from pydantic import BaseModel
import sqlite3
import json
import asyncio
from typing import Optional

class LegacyThumbnailRequest(BaseModel):
    """レガシーサムネイル生成リクエストのモデル

    Attributes:
        task_id (str): タスクの一意の識別子。
        text (str): サムネイルに描画するテキスト。デフォルトは 'Thumbnail'。
        width (int): サムネイルの幅（ピクセル）。デフォルトは 1280。
        height (int): サムネイルの高さ（ピクセル）。デフォルトは 720。
        max_retries (int): 最大再試行回数。デフォルトは 0。
        db_path (Optional[str]): データベースファイルのパス。
        output_dir (Optional[str]): 出力ディレクトリのパス。
    """
    task_id: str
    text: str = "Thumbnail"
    width: int = 1280
    height: int = 720
    max_retries: int = 0
    db_path: Optional[str] = None
    output_dir: Optional[str] = None


thumbnail_router = APIRouter(tags=["Usage Thumbnail"])


def _validate_thumbnail_request(req: LegacyThumbnailRequest) -> None:
    """サムネイル生成リクエストのバリデーションを行います。

    解像度が 1280x720 以上であること、およびアスペクト比が 16:9 であることを検証します。

    Args:
        req (LegacyThumbnailRequest): サムネイル生成リクエストオブジェクト。

    Raises:
        HTTPException: 解像度が1280x720未満の場合（400 Bad Request）、
            またはアスペクト比が16:9ではない場合（400 Bad Request）。
    """
    if req.width < 1280 or req.height < 720:
        raise HTTPException(
            status_code=400,
            detail=f"Resolution must be at least 1280x720. Got {req.width}x{req.height}"
        )
        
    aspect_ratio = req.width / req.height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 0.01:
        raise HTTPException(
            status_code=400,
            detail=f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}"
        )


def _setup_thumbnail_overlay_and_agent(
    req: LegacyThumbnailRequest, db_path: str
) -> tuple["CombinedOverlay", "StageBoundAgent"]:
    """CombinedOverlay と StageBoundAgent のセットアップを行います。

    指定された解像度やテキスト情報で CombinedOverlay を初期化し、
    タスク状態を管理するための StageBoundAgent をデータベースパスを指定して生成します。

    Args:
        req (LegacyThumbnailRequest): サムネイル生成リクエストオブジェクト。
        db_path (str): タスク管理用の SQLite データベースのファイルパス。

    Returns:
        tuple[CombinedOverlay, StageBoundAgent]: 初期化された CombinedOverlay インスタンスと
            StageBoundAgent インスタンスのタプル。
    """
    from combined_overlay import CombinedOverlay
    from agents.stage_bound_agent import StageBoundAgent
    
    overlay = CombinedOverlay()
    overlay.width = req.width
    overlay.height = req.height
    overlay.text = req.text
    
    if req.output_dir:
        overlay.output_dir = req.output_dir
    else:
        overlay.output_dir = "backend/temp/legacy_thumbnails"
        os.makedirs(overlay.output_dir, exist_ok=True)
        
    agent = StageBoundAgent(stage_name="thumbnail", db_path=db_path)
    return overlay, agent


async def _wait_for_thumbnail_task(agent: Any, task_id: str) -> str:
    """サムネイルタスクの終了を待機します。

    最大 50 回（約 2.5 秒）、0.05 秒間隔でタスクのステータスを確認し、
    完了（COMPLETED）または失敗（FAILED）になるまで非同期に待機します。

    Args:
        agent (Any): タスクステータスを確認するための StageBoundAgent インスタンス。
        task_id (str): 待機対象のタスクID。

    Returns:
        str: タスクの最終ステータス（"COMPLETED" または "FAILED"）。
            タイムアウトした場合は、その時点のステータスが返されます。
    """
    import asyncio
    for _ in range(50):
        status = await agent.get_task_status(task_id)
        if status in ("COMPLETED", "FAILED"):
            break
        await asyncio.sleep(0.05)
        
    return await agent.get_task_status(task_id)


def _fetch_thumbnail_result(db_path: str, task_id: str, final_status: str) -> Dict[str, Any]:
    """タスクの結果またはエラーをデータベースから取得します。

    Args:
        db_path (str): データベースのファイルパス。
        task_id (str): 対象のタスクID。
        final_status (str): タスクの最終ステータス。

    Returns:
        Dict[str, Any]: データベースから取得した結果データ。

    Raises:
        HTTPException: タスクが失敗していた場合、または結果が取得できなかった場合。
    """
    import sqlite3
    import json
    
    if final_status == "FAILED":
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("SELECT error FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            error_msg = row[0] if row else "Unknown error"
        finally:
            conn.close()
        raise HTTPException(status_code=500, detail=f"Thumbnail task failed: {error_msg}")
        
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("SELECT result FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        result_data = json.loads(row[0]) if row and row[0] else {}
    finally:
        conn.close()
        
    return result_data


@thumbnail_router.post("/api/thumbnail/generate")
async def generate_thumbnail_api(req: LegacyThumbnailRequest) -> Dict[str, Any]:
    """サムネイル画像生成・品質検証・StageBoundAgent連携エンドポイントです。

    リクエストの検証、データベースの初期化、タスクの登録、およびバックグラウンドでの
    サムネイル生成処理の実行・待機を行い、生成結果を返します。

    Args:
        req (LegacyThumbnailRequest): サムネイル生成リクエスト。

    Returns:
        Dict[str, Any]: 生成成功フラグ（success=True）、タスクID、最終ステータス、
            および結果データを含む辞書。

    Raises:
        HTTPException: リクエストのバリデーションに失敗した場合（400）、
            またはサムネイル生成タスクの処理が失敗した場合（500）。
    """
    _validate_thumbnail_request(req)
        
    db_path = req.db_path or "backend/temp/legacy_thumbnail_agent.db"
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
        
    overlay, agent = _setup_thumbnail_overlay_and_agent(req, db_path)
    
    # タスクの登録
    await agent.register_task(task_id=req.task_id, initial_status="READY", max_retries=req.max_retries)
    
    # 実行開始
    await agent.start(overlay.resolve_thumbnail_task)
    
    # 完了または失敗まで待機
    final_status = await _wait_for_thumbnail_task(agent, req.task_id)
    await agent.stop()
    
    result_data = _fetch_thumbnail_result(db_path, req.task_id, final_status)
        
    return {
        "success": True,
        "task_id": req.task_id,
        "status": final_status,
        "result": result_data
    }
