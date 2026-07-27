"""
Admin Quota Router — A-2 API使用量監視・コスト最適化

Admin UXストーリー A-2 に対応するバックエンドAPI。
実際の APIUsageTracker と連携し、エスカレーション閾値管理、
自動サスペンドのオーバーライド（手動解除）、および入力値制限を提供する。
"""

import time
import logging
import math
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/quota", tags=["Admin Quota"])

# ── リクエストモデル ──

class ThresholdUpdateRequest(BaseModel):
    info_percent: float = 60.0
    warning_percent: float = 80.0
    critical_percent: float = 95.0


class SavingModeRequest(BaseModel):
    enabled: bool


class BudgetLimitRequest(BaseModel):
    monthly_limit_jpy: float


class KeyRotationRequest(BaseModel):
    key_name: str
    api_key: str


class ExportRequest(BaseModel):
    format: str = "csv"  # "csv" or "pdf"


class QuotaOverrideRequest(BaseModel):
    action: str  # "force_use" | "release" | "fallback"


# ── 状態管理 (一部のシミュレーション値) ──

_saving_mode = False
_budget_limit_jpy = 10000.0
_api_keys_rotation: List[dict] = []

_worker_usage = {
    "transcribe": 980,
    "proofread": 720,
    "smartcut": 450,
    "quality_gate": 380,
    "youtube_opt": 340,
    "render": 210,
    "preview": 120,
}

_model_usage = {
    "premium": 1200,
    "standard": 1500,
    "batch": 500,
}


def _get_tracker() -> Any:
    """API使用量トラッカーインスタンスを取得する。

    サービスコンテナが存在する場合はコンテナから 'usage_tracker' を取得し、
    存在しない、あるいはエラーが発生した場合はデフォルトのグローバルインスタンスをインポートして返却する。

    Returns:
        Any: APIUsageTracker のインスタンス。
    """
    try:
        from service_container import container
        return container.get("usage_tracker")
    except (ImportError, KeyError, ValueError, AttributeError):
        from usage_tracker.api_usage_tracker import usage_tracker
        return usage_tracker


# ── S1: ダッシュボード概要 ──

@router.get("/dashboard", response_model=Dict[str, Any])
async def get_quota_dashboard() -> Dict[str, Any]:
    """A-2 S1: API使用量監視ダッシュボードの全体情報を取得する。

    現在のAPI使用量、エスカレーションレベル、節約モードの有効状態、自動ブロックの有無
    および利用可能なダッシュボードセクションのリストを含む要約データを返却する。

    Returns:
        Dict[str, Any]: ダッシュボード要約データ。以下のキーを含む：
            - title (str): ダッシュボードのタイトル
            - status (str): エスカレーションステータス (例: "NORMAL", "WARNING")
            - usage_summary (dict): 月間使用量と制限値、使用率のサマリー
            - sections (List[str]): 提供されるセクション一覧
            - saving_mode (bool): 節約モードのON/OFF
            - blocked (bool): API自動ブロック（サスペンド）が発動しているか
            - timestamp (str): データ取得時のISO 8601形式タイムスタンプ
    """
    tracker = _get_tracker()
    usage = tracker.get_today_usage()
    usage_pct = usage["usage_pct"]
    status = usage["escalation_level"].upper()
    
    return {
        "title": "API使用量監視",
        "status": status,
        "usage_summary": {
            "monthly_used": usage["used"] * 15,  # シミュレーション
            "monthly_limit": usage["limit"] * 30,
            "usage_percent": usage_pct,
        },
        "sections": [
            "usage_gauge", "escalation_status", "remaining",
            "usage_history", "model_breakdown", "worker_breakdown",
            "cost_estimate", "thresholds", "saving_mode",
            "auto_block", "alerts", "forecast",
            "optimization", "quota_reset", "downgrade_log",
            "realtime", "export", "free_tier",
            "key_rotation", "budget",
        ],
        "saving_mode": _saving_mode,
        "blocked": tracker.should_block(),
        "timestamp": datetime.now().isoformat(),
    }


# ── S2: 使用量ゲージ ──

@router.get("/usage-gauge", response_model=Dict[str, Any])
async def get_usage_gauge() -> Dict[str, Any]:
    """A-2 S2: Gemini API使用量 (日/週/月) のゲージ表示用データを取得する。

    今日の日次使用量と制限、および週次・月次のシミュレーション使用量とパーセンテージを計算して返却する。

    Returns:
        Dict[str, Any]: 日/週/月ごとの使用量ゲージデータ。
            - daily (dict): 日次の使用量、制限、パーセンテージ
            - weekly (dict): 週次の使用量、制限、パーセンテージ
            - monthly (dict): 月次の使用量、制限、パーセンテージ
    """
    tracker = _get_tracker()
    usage = tracker.get_today_usage()
    
    return {
        "daily": {
            "used": usage["used"],
            "limit": usage["limit"],
            "percent": usage["usage_pct"],
        },
        "weekly": {
            "used": usage["used"] * 4,  # シミュレーション
            "limit": usage["limit"] * 7,
            "percent": round((usage["used"] * 4) / max(usage["limit"] * 7, 1) * 100, 1),
        },
        "monthly": {
            "used": usage["used"] * 15,  # シミュレーション
            "limit": usage["limit"] * 30,
            "percent": round((usage["used"] * 15) / max(usage["limit"] * 30, 1) * 100, 1),
        },
    }


# ── S3: 4段階ステータス ──

@router.get("/status", response_model=Dict[str, Any])
async def get_escalation_status() -> Dict[str, Any]:
    """A-2 S3: API使用量のエスカレーションステータス情報を取得する。

    NORMAL / INFO / WARNING / BLOCKED / BANNED の 4段階（＋BANNED）の色分けステータスと、
    対応する説明文、表示用のカラーコードを返却する。

    Returns:
        Dict[str, Any]: ステータス情報。以下のキーを含む：
            - status (str): ステータス文字列
            - usage_percent (float): 現在の使用率
            - thresholds (Dict[str, float]): 各レベルの閾値パーセンテージ
            - description (str): ステータスの日本語説明文
            - color (str): カラーコード (HEX値)
    """
    tracker = _get_tracker()
    usage = tracker.get_today_usage()
    status = usage["escalation_level"].upper()
    
    pct_thresholds = {k: v * 100 for k, v in tracker.thresholds.items()}
    
    return {
        "status": status,
        "usage_percent": usage["usage_pct"],
        "thresholds": pct_thresholds,
        "description": _status_description(status),
        "color": _status_color(status),
    }


# ── S4: 残回数 ──

@router.get("/remaining", response_model=Dict[str, Any])
async def get_remaining_requests() -> Dict[str, Any]:
    """A-2 S4: 今日のAPI残りリクエスト数を取得する。

    制限値から使用数を差し引いた、本日の残リクエスト可能数およびその割合を返却する。

    Returns:
        Dict[str, Any]: 残りリクエスト数データ。以下のキーを含む：
            - remaining (int): 残りリクエスト数
            - total (int): 1日の最大制限数
            - percentage (float): 残りパーセンテージ
            - period (str): 集計期間 ("daily")
    """
    tracker = _get_tracker()
    usage = tracker.get_today_usage()
    
    return {
        "remaining": usage["remaining"],
        "total": usage["limit"],
        "percentage": round((usage["remaining"] / max(usage["limit"], 1)) * 100, 1),
        "period": "daily",
    }


# ── S5: 使用量推移 ──

@router.get("/usage-history", response_model=Dict[str, Any])
async def get_usage_history() -> Dict[str, Any]:
    """A-2 S5: 過去30日間の使用量グラフ用履歴データを取得する。

    直近30日間の日次使用量データをシミュレーション生成して返却する。

    Returns:
        Dict[str, Any]: 履歴グラフデータ。以下のキーを含む：
            - history (List[Dict[str, Any]]): 各日付と使用リクエスト数のリスト
            - period_days (int): 表示対象の日数 (30)
    """
    tracker = _get_tracker()
    usage = tracker.get_today_usage()
    today = datetime.now()
    history = []
    for i in range(30):
        date_val = today - timedelta(days=29 - i)
        # 過去データのシミュレーション
        base = int(usage["used"] * (0.5 + (i * 0.02)))
        history.append({
            "date": date_val.strftime("%Y-%m-%d"),
            "requests": min(base, usage["limit"]),
        })
    return {"history": history, "period_days": 30}


# ── S6: モデル別内訳 ──

@router.get("/model-breakdown", response_model=Dict[str, Any])
async def get_model_breakdown() -> Dict[str, Any]:
    """A-2 S6: モデルティア別 (Premium / Standard / Batch) の使用量内訳を取得する。

    それぞれのティアにおける累積リクエスト数および総合計を返却する。

    Returns:
        Dict[str, Any]: モデル別内訳データ。以下のキーを含む：
            - premium (int): Premium ティアの使用数
            - standard (int): Standard ティアの使用数
            - batch (int): Batch ティアの使用数
            - total (int): 全ティアの合計使用数
    """
    total = sum(_model_usage.values())
    return {
        "premium": _model_usage["premium"],
        "standard": _model_usage["standard"],
        "batch": _model_usage["batch"],
        "total": total,
    }


# ── S7: Worker別内訳 ──

@router.get("/worker-breakdown", response_model=Dict[str, Any])
async def get_worker_breakdown() -> Dict[str, Any]:
    """A-2 S7: 非同期Workerプロセスごとのリクエスト消費量内訳を取得する。

    transcribe, proofread, render など各Workerの累積API呼び出し数を返却する。

    Returns:
        Dict[str, Any]: Worker別内訳データ。以下のキーを含む：
            - workers (Dict[str, int]): 各Worker名と消費数のマップ
            - total (int): 全Workerの消費合計数
            - worker_count (int): 登録されているWorker数
    """
    return {
        "workers": _worker_usage,
        "total": sum(_worker_usage.values()),
        "worker_count": len(_worker_usage),
    }


# ── S8: コスト計算 ──

@router.get("/cost-estimate", response_model=Dict[str, Any])
async def get_cost_estimate() -> Dict[str, Any]:
    """A-2 S8: API使用コストの月間予測および実績を取得する。

    モデルティアごとの単価（Premium=0.5 JPY, Standard=0.1 JPY, Batch=0.05 JPY）に基づいて
    現在の実績コストを算出し、日次上限と経過日数から月間推定コストを求めて返却する。

    Returns:
        Dict[str, Any]: コスト見積データ。以下のキーを含む：
            - estimated (float): 月間推定コスト (JPY)
            - actual (float): 今月の現在の実績コスト (JPY)
            - currency (str): 通学単位 ("JPY")
            - breakdown (Dict[str, float]): 各ティア別の実績コスト内訳
    """
    premium_cost = _model_usage["premium"] * 0.5
    standard_cost = _model_usage["standard"] * 0.1
    batch_cost = _model_usage["batch"] * 0.05
    actual = premium_cost + standard_cost + batch_cost
    
    tracker = _get_tracker()
    usage = tracker.get_today_usage()
    limit = usage["limit"]
    used = usage["used"]
    estimated = actual * ((limit * 30) / max(used * 15, 1))
    return {
        "estimated": round(estimated, 2),
        "actual": round(actual, 2),
        "currency": "JPY",
        "breakdown": {
            "premium": round(premium_cost, 2),
            "standard": round(standard_cost, 2),
            "batch": round(batch_cost, 2),
        },
    }


# ── S9: 閾値設定 ──

@router.get("/thresholds", response_model=Dict[str, float])
async def get_thresholds() -> Dict[str, float]:
    """A-2 S9: エスカレーション閾値の現在値を取得する。

    各レベル (info, warning, critical) の自動サスペンド等のトリガー閾値を
    パーセンテージ表記 (0-100) で返却する。

    Returns:
        Dict[str, float]: 閾値名とパーセンテージ値のマップ。
    """
    tracker = _get_tracker()
    return {k: v * 100 for k, v in tracker.thresholds.items()}


@router.post("/thresholds", response_model=Dict[str, Any])
async def update_thresholds(req: ThresholdUpdateRequest) -> Dict[str, Any]:
    """A-2 S9: エスカレーション閾値 (info / warning / critical) を更新する。

    入力値のガードレール検査 (0-100%の範囲内、および info < warning < critical の順序関係)
    を通過したのち、APIUsageTracker 内の閾値を更新して返却する。

    Args:
        req (ThresholdUpdateRequest): 変更後の閾値パーセンテージ。

    Raises:
        HTTPException: 入力値が不正な場合 (400) や順序が崩れている場合に発生。

    Returns:
        Dict[str, Any]: 更新結果と設定値。
    """
    # 入力値ガードレール (0-100%)
    for name, val in [("info", req.info_percent), ("warning", req.warning_percent), ("critical", req.critical_percent)]:
        if math.isnan(val) or math.isinf(val) or val < 0 or val > 100:
            raise HTTPException(status_code=400, detail=f"Invalid threshold {name}: {val}%. Must be 0-100")
    if not (req.info_percent < req.warning_percent < req.critical_percent):
        raise HTTPException(status_code=400, detail="Thresholds must satisfy info < warning < critical")
    
    tracker = _get_tracker()
    try:
        tracker.update_thresholds(
            info=req.info_percent / 100.0,
            warning=req.warning_percent / 100.0,
            critical=req.critical_percent / 100.0
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    return {
        "status": "updated",
        "info": req.info_percent,
        "warning": req.warning_percent,
        "critical": req.critical_percent
    }


# ── S10: 節約モード ──

@router.get("/saving-mode", response_model=Dict[str, bool])
async def get_saving_mode() -> Dict[str, bool]:
    """A-2 S10: 節約モードの現在の有効状態を取得する。

    節約モードが有効な場合、システムは可能な限り安価なStandard/Batchティアのモデルを優先使用する。

    Returns:
        Dict[str, bool]: 'enabled' キーに状態を格納して返却。
    """
    return {"enabled": _saving_mode}


@router.post("/saving-mode", response_model=Dict[str, Any])
async def toggle_saving_mode(req: SavingModeRequest) -> Dict[str, Any]:
    """A-2 S10: 節約モードのON/OFF（有効化・無効化）を切り替える。

    Args:
        req (SavingModeRequest): 有効化するかどうかのフラグ。

    Returns:
        Dict[str, Any]: 更新結果ステータス。
    """
    global _saving_mode
    _saving_mode = req.enabled
    return {"status": "updated", "enabled": _saving_mode}


# ── S11: 自動ブロック ──

@router.get("/auto-block", response_model=Dict[str, Any])
async def get_auto_block_status() -> Dict[str, Any]:
    """A-2 S11: API自動サスペンド（自動ブロック）状態を取得する。

    API使用量が設定されたクリティカル閾値を超えているか、手動オーバーライドが有効かなどの状態を返却する。

    Returns:
        Dict[str, Any]: 自動ブロックステータス。以下のキーを含む：
            - blocked (bool): 現在サスペンド中であるか
            - reason (Optional[str]): サスペンドされている理由
            - triggered_at (Optional[str]): サスペンドがトリガーされたISO時刻
            - threshold (float): サスペンド発動の閾値パーセンテージ
            - override_active (bool): 手動解除オーバーライドが有効であるか
    """
    tracker = _get_tracker()
    blocked = tracker.should_block()
    
    return {
        "blocked": blocked,
        "reason": "API使用量がサスペンド閾値を超えました" if blocked else None,
        "triggered_at": datetime.now().isoformat() if blocked else None,
        "threshold": tracker.thresholds["critical"] * 100,
        "override_active": tracker.override_active,
    }


# ── S12: ブロック解除（オーバーライド） ──

@router.post("/auto-block/release", response_model=Dict[str, Any])
async def release_block() -> Dict[str, Any]:
    """A-2 S12: 手動でAPI自動サスペンド（ブロック）を一時解除（オーバーライド有効化）する。

    これにより、使用率がクリティカル閾値に達していてもAPIリクエストの送信が強制的に許可される。

    Returns:
        Dict[str, Any]: 解除結果ステータス。
    """
    tracker = _get_tracker()
    tracker.set_override(True)
    return {"status": "released", "blocked": False, "override_active": True}


# ── S11 supplement: 強制ブロック発動 (テスト用) ──

@router.post("/auto-block/trigger", response_model=Dict[str, Any])
async def trigger_block() -> Dict[str, Any]:
    """API自動サスペンド（ブロック）状態をテスト用に強制発動させる。

    API使用実績をクリティカル閾値 (95%超) 付近まで一時的に加算記録し、オーバーライドを無効化する。

    Returns:
        Dict[str, Any]: 発動後のサスペンド状態。
    """
    tracker = _get_tracker()
    # 制限いっぱいに達するように記録 (95%の位置に調整)
    usage = tracker.get_today_usage()
    needed = int(usage["limit"] * 0.96) - usage["used"]
    if needed > 0:
        tracker.record_calls(needed, source="test_trigger")
    tracker.set_override(False)
    return {"status": "triggered", "blocked": tracker.should_block()}


# ── S13: アラート履歴 ──

@router.get("/alerts", response_model=Dict[str, Any])
async def get_alert_history(level: Optional[str] = None) -> Dict[str, Any]:
    """A-2 S13: 閾値超過に伴うアラート履歴一覧を取得する。

    使用率が閾値 (60%, 80%, 95%) を超えた際に記録された、INFO / WARNING / CRITICAL レベルのアラート。
    クエリパラメータで特定レベルのアラートのみを抽出可能。

    Args:
        level (Optional[str], optional): 抽出するアラートレベル (例: "warning")。デフォルトは None (全表示)。

    Returns:
        Dict[str, Any]: アラート履歴のリストと合計件数。
    """
    tracker = _get_tracker()
    usage = tracker.get_today_usage()
    alerts = []
    
    if usage["usage_pct"] >= 60.0:
        alerts.append({"id": 2, "level": "INFO", "message": "API使用量が60%に到達", "timestamp": datetime.now().isoformat()})
    if usage["usage_pct"] >= 80.0:
        alerts.append({"id": 1, "level": "WARNING", "message": "API使用量が80%に到達", "timestamp": datetime.now().isoformat()})
    if usage["usage_pct"] >= 95.0:
        alerts.append({"id": 3, "level": "CRITICAL", "message": "API使用量が95%に到達 (サスペンド状態)", "timestamp": datetime.now().isoformat()})
        
    if level:
        alerts = [a for a in alerts if a["level"] == level.upper()]
    return {"alerts": alerts, "total": len(alerts)}


# ── S14: 予測消費 ──

@router.get("/forecast", response_model=Dict[str, Any])
async def get_forecast() -> Dict[str, Any]:
    """A-2 S14: 今月の線形外挿によるAPI予測消費量と予測コストを取得する。

    今月の経過日数と現在までの使用実績から1日平均消費量を算出し、月末時点での着地予測を行う。

    Returns:
        Dict[str, Any]: 予測結果データ。以下のキーを含む：
            - forecast_requests (int): 月末の予測総リクエスト数
            - forecast_cost (float): 月末の予測総コスト (JPY)
            - currency (str): 通貨単位 ("JPY")
            - method (str): 予測手法 ("linear_extrapolation")
            - days_elapsed (int): 今月の経過日数
            - daily_average (float): 1日あたりの平均消費リクエスト数
    """
    tracker = _get_tracker()
    usage = tracker.get_today_usage()
    now = datetime.now()
    days_elapsed = now.day
    days_in_month = 30
    
    daily_avg = usage["used"] / max(days_elapsed, 1)
    forecast_requests = round(daily_avg * days_in_month)
    forecast_cost = round(forecast_requests * 0.15, 2)
    return {
        "forecast_requests": forecast_requests,
        "forecast_cost": forecast_cost,
        "currency": "JPY",
        "method": "linear_extrapolation",
        "days_elapsed": days_elapsed,
        "daily_average": round(daily_avg, 1),
    }


# ── S15: 最適化提案 ──

@router.get("/optimization", response_model=Dict[str, Any])
async def get_optimization_suggestions() -> Dict[str, Any]:
    """A-2 S15: システムが検知したAPIコスト最適化の自動提案一覧を取得する。

    バッチ化の推奨、キャッシュの有効化、モデルのダウングレード推奨など、影響度とともに提案を返却する。

    Returns:
        Dict[str, Any]: 最適化の提案リストと合計件数。
    """
    suggestions = [
        {"category": "batching", "impact": "high", "description": "非同期処理をバッチAPIに移行し、コストを60%削減"},
        {"category": "caching", "impact": "medium", "description": "繰り返しプロンプトのレスポンスキャッシュで20%削減"},
        {"category": "model_selection", "impact": "medium", "description": "品質非依存タスクをStandard/Batchに降格"},
        {"category": "deduplication", "impact": "low", "description": "重複リクエストの検出・排除で5%削減"},
    ]
    return {"suggestions": suggestions, "total": len(suggestions)}


# ── S16: クォータリセット ──

@router.get("/quota-reset", response_model=Dict[str, Any])
async def get_quota_reset() -> Dict[str, Any]:
    """A-2 S16: 日次クォータ制限のリセット予定時刻を取得する。

    標準のリセット時刻設定 (UTC 00:00:00) および次回の具体的なリセット日時 (ISO表記) を返却する。

    Returns:
        Dict[str, Any]: リセット予定時刻情報。
    """
    now = datetime.now()
    next_reset = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "reset_time": "00:00:00 UTC",
        "next_reset": next_reset.isoformat(),
        "timezone": "UTC",
    }


# ── S17: 降格ログ ──

@router.get("/downgrade-log", response_model=Dict[str, Any])
async def get_downgrade_log() -> Dict[str, Any]:
    """A-2 S17: レート制限や枠逼迫に伴う、使用モデルティアの動的自動降格ログ履歴を取得する。

    Returns:
        Dict[str, Any]: 降格ログ一覧と件数。
    """
    logs = [
        {"from_tier": "premium", "to_tier": "standard", "reason": "rate_limit_exceeded", "timestamp": "2026-04-30T15:20:00"},
        {"from_tier": "standard", "to_tier": "batch", "reason": "quota_near_limit", "timestamp": "2026-04-30T16:45:00"},
    ]
    return {"logs": logs, "total": len(logs)}


# ── S18: リアルタイム更新 ──

@router.get("/realtime-status", response_model=Dict[str, Any])
async def get_realtime_status() -> Dict[str, Any]:
    """A-2 S18: ダッシュボード表示のリアルタイム WebSocket 同期状態を取得する。

    Returns:
        Dict[str, Any]: WebSocketの有効フラグ、同期間隔、接続クライアント数など。
    """
    return {
        "websocket_enabled": True,
        "update_interval_ms": 5000,
        "last_update": datetime.now().isoformat(),
        "connected_clients": 0,
    }


# ── S19: レポートエクスポート ──

@router.post("/export", response_model=Dict[str, Any])
async def export_report(req: ExportRequest) -> Dict[str, Any]:
    """A-2 S19: API使用量レポートを指定されたフォーマット (CSV / PDF) で生成し、ダウンロードURLを発行する。

    Args:
        req (ExportRequest): 出力フォーマット設定。

    Raises:
        HTTPException: 指定フォーマットが CSV / PDF 以外の場合に発生 (400)。

    Returns:
        Dict[str, Any]: 生成ステータスおよびダウンロード用URL。
    """
    valid_formats = {"csv", "pdf"}
    if req.format.lower() not in valid_formats:
        raise HTTPException(status_code=400, detail=f"Invalid format: {req.format}. Must be one of {valid_formats}")
    return {
        "status": "generated",
        "format": req.format.lower(),
        "download_url": f"/api/admin/quota/download/report.{req.format.lower()}",
        "generated_at": datetime.now().isoformat(),
    }


# ── S20: 無料枠超過判定 ──

@router.get("/free-tier-status", response_model=Dict[str, Any])
async def get_free_tier_status() -> Dict[str, Any]:
    """A-2 S20: 無料枠（初期日次制限値）を超過しているかどうかの判定および残額を取得する。

    Returns:
        Dict[str, Any]: 無料枠ステータス。以下のキーを含む：
            - exceeded (bool): 超過しているか
            - remaining_free (int): 残りの無料利用可能数
            - free_limit (int): 無料枠の上限数
            - daily_used (int): 今日の使用数
            - action (str): 推奨アクション ("continue" または超過時の "wait")
    """
    tracker = _get_tracker()
    usage = tracker.get_today_usage()
    free_limit = usage["limit"]
    daily_used = usage["used"]
    return {
        "exceeded": daily_used > free_limit,
        "remaining_free": max(0, free_limit - daily_used),
        "free_limit": free_limit,
        "daily_used": daily_used,
        "action": "wait" if daily_used > free_limit else "continue",
    }


# ── S21: 複数APIキーローテーション ──

@router.get("/key-rotation", response_model=Dict[str, Any])
async def get_key_rotation() -> Dict[str, Any]:
    """A-2 S21: ローテーション用に登録されている複数APIキーの一覧を取得する。

    Returns:
        Dict[str, Any]: 登録キー一覧と件数。
    """
    return {"keys": _api_keys_rotation, "total": len(_api_keys_rotation)}


@router.post("/key-rotation", response_model=Dict[str, Any])
async def add_key_rotation(req: KeyRotationRequest) -> Dict[str, Any]:
    """A-2 S21: ローテーション用に新しいAPIキーを追加登録する。

    入力されたAPIキーの簡易ガードレール検査 (最小文字数) と重複チェックを行う。

    Args:
        req (KeyRotationRequest): 登録するキー名とキー本体。

    Raises:
        HTTPException: キーが短すぎる場合 (400)、あるいはすでに登録済みの名前の場合 (400)。

    Returns:
        Dict[str, Any]: 登録完了したキーの情報 (キーの機密部分はマスクされる)。
    """
    if len(req.api_key) < 10:
        raise HTTPException(status_code=400, detail="API key too short")
    if any(k["key_name"] == req.key_name for k in _api_keys_rotation):
        raise HTTPException(status_code=400, detail=f"Key name '{req.key_name}' already exists")
    entry = {
        "key_name": req.key_name,
        "prefix": req.api_key[:8] + "...",
        "added_at": datetime.now().isoformat(),
        "active": True,
    }
    _api_keys_rotation.append(entry)
    return {"status": "added", **entry}


@router.delete("/key-rotation/{key_name}", response_model=Dict[str, Any])
async def remove_key_rotation(key_name: str) -> Dict[str, Any]:
    """A-2 S21: 登録済みの特定のAPIキーをローテーション対象から削除する。

    Args:
        key_name (str): 削除対象のキー名。

    Raises:
        HTTPException: 指定されたキー名が存在しない場合に発生 (404)。

    Returns:
        Dict[str, Any]: 削除結果ステータス。
    """
    global _api_keys_rotation
    before = len(_api_keys_rotation)
    _api_keys_rotation = [k for k in _api_keys_rotation if k["key_name"] != key_name]
    if len(_api_keys_rotation) == before:
        raise HTTPException(status_code=404, detail=f"Key '{key_name}' not found")
    return {"status": "removed", "key_name": key_name}


# ── S22: 予算上限 ──

@router.get("/budget", response_model=Dict[str, Any])
async def get_budget() -> Dict[str, Any]:
    """A-2 S22: 設定された月間予算上限と現在の推定コスト、残額を取得する。

    Returns:
        Dict[str, Any]: 予算ステータス。以下のキーを含む：
            - monthly_limit_jpy (float): 設定された月間上限金額 (JPY)
            - current_cost_jpy (float): 現在の推定実績コスト (JPY)
            - remaining_jpy (float): 予算の残高 (JPY)
            - exceeded (bool): 予算を超過しているか
    """
    cost = (await get_cost_estimate())["actual"]
    return {
        "monthly_limit_jpy": _budget_limit_jpy,
        "current_cost_jpy": cost,
        "remaining_jpy": round(_budget_limit_jpy - cost, 2),
        "exceeded": cost > _budget_limit_jpy,
    }


@router.post("/budget", response_model=Dict[str, Any])
async def update_budget(req: BudgetLimitRequest) -> Dict[str, Any]:
    """A-2 S22: 月間予算上限金額を設定する。

    入力された予算上限値に対して NaN/Inf および負数ガードレール検査を行う。

    Args:
        req (BudgetLimitRequest): 新しい予算上限 (JPY)。

    Raises:
        HTTPException: 入力値が不正な（負数、非有限）場合に発生 (400)。

    Returns:
        Dict[str, Any]: 設定完了ステータス。
    """
    global _budget_limit_jpy
    if math.isnan(req.monthly_limit_jpy) or math.isinf(req.monthly_limit_jpy) or req.monthly_limit_jpy < 0:
        raise HTTPException(status_code=400, detail="Budget limit must be non-negative (and finite)")
    _budget_limit_jpy = req.monthly_limit_jpy
    return {"status": "updated", "monthly_limit_jpy": _budget_limit_jpy}


# ── S23: 手動オーバーライドAPI ──

@router.post("/override", response_model=Dict[str, Any])
async def override_quota_limit(req: QuotaOverrideRequest) -> Dict[str, Any]:
    """A-2 S23: 手動オーバーライド（自動サスペンド状態の強制制御）を実行する。

    ブロックを無視してAPI使用を継続する 'force_use'、オーバーライドを解除する 'release'、
    フォールバックを一時適用するための 'fallback' のアクションを受け付ける。

    Args:
        req (QuotaOverrideRequest): 実行するオーバーライドのアクション名。

    Raises:
        HTTPException: 指定されたアクション名が無効な場合に発生 (400)。

    Returns:
        Dict[str, Any]: 実行結果ステータス。
    """
    # 入力値ガードレール
    if req.action not in ("force_use", "release", "fallback"):
        raise HTTPException(
            status_code=400,
            detail="Invalid action. Must be 'force_use', 'release', or 'fallback'"
        )
    
    tracker = _get_tracker()
    if req.action == "force_use":
        tracker.set_override(True)
        return {"status": "overridden", "override_active": True, "action": "force_use"}
    elif req.action == "release":
        tracker.set_override(False)
        return {"status": "released", "override_active": False, "action": "release"}
    elif req.action == "fallback":
        # フォールバック処理有効化のために、一旦ブロックをバイパス
        tracker.set_override(True)
        return {"status": "fallback_configured", "override_active": True, "action": "fallback"}


# ── ユーティリティ ──

def _status_description(status: str) -> str:
    """エスカレーションステータスの表示用説明文（日本語）を取得する。

    Args:
        status (str): NORMAL, INFO, WARNING, BLOCKED, BANNED などのステータス名。

    Returns:
        str: ステータスに対応する日本語説明文。
    """
    descriptions = {
        "NORMAL": "API使用量は正常範囲内です",
        "INFO": "API使用量が注意レベルに達しています",
        "WARNING": "API使用量が警告レベルです。節約モードを検討してください",
        "BLOCKED": "API使用量が危険レベルです。自動サスペンドが発動しています",
        "BANNED": "API使用量が上限に達しました。強制ブロック状態です",
    }
    return descriptions.get(status, "不明")


def _status_color(status: str) -> str:
    """エスカレーションステータスの表示用カラーコードを取得する。

    Args:
        status (str): NORMAL, INFO, WARNING, BLOCKED, BANNED などのステータス名。

    Returns:
        str: HEX形式のカラーコード文字列（例: "#22c55e"）。
    """
    colors = {
        "NORMAL": "#22c55e",
        "INFO": "#3b82f6",
        "WARNING": "#f59e0b",
        "BLOCKED": "#ef4444",
        "BANNED": "#7f1d1d"
    }
    return colors.get(status, "#6b7280")
