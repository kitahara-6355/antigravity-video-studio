import logging
from typing import Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

class PredictionValidator:
    """
    [Phase 2.2: Prediction vs Reality Report]
    Phase 1における「事前のCTR/パフォーマンス予測」と、
    Phase 2.1で収集された「実際の結果」を比較し、予測精度のレポートを生成する。
    """
    
    def __init__(self):
        pass
        
    async def validate_prediction(self, wagamama_id: str, actual_metrics: Dict[str, Any], wagamama_manager=None) -> Dict[str, Any]:
        """
        台帳（Wagamama Ledger）の予測値と、実際の数値を比較検証する。
        """
        if not wagamama_manager:
            return {"status": "error", "message": "Manager not provided"}
            
        record = wagamama_manager.get_record(wagamama_id)
        if not record:
            return {"status": "error", "message": "No record found for validation"}
            
        exp_lane = record.get("lanes", {}).get("experience", {})
        
        # Phase 1.3 で記録された予測CTRを取得
        predicted_ctr = exp_lane.get("predicted_ctr")
        if predicted_ctr is None:
            return {"status": "skipped", "message": "No predicted CTR available for comparison"}
            
        actual_metrics_dict = actual_metrics or {}
        metrics = actual_metrics_dict.get("metrics") or {}
        actual_ctr = metrics.get("click_through_rate", 0.0)
        
        # 差異の計算 (+ なら実績が予測を超えた)
        diff_pct = actual_ctr - predicted_ctr
        
        # 予測誤差率 (絶対値で、予測値に対する割合)
        error_margin = abs(diff_pct) / predicted_ctr if predicted_ctr > 0 else 0
        
        report = {
            "wagamama_id": wagamama_id,
            "validated_at": datetime.now().isoformat(),
            "prediction": {
                "ctr": predicted_ctr,
            },
            "actual": {
                "ctr": actual_ctr,
                "elapsed_hours": actual_metrics_dict.get("elapsed_hours", 24)
            },
            "analysis": {
                "predicted": predicted_ctr,
                "actual": actual_ctr,
                "difference": round(diff_pct, 2),
                "error_margin_pct": round(error_margin * 100, 2),
                "significant_deviation": error_margin > 0.3 # 30%以上ズレている場合は重要フラグ
            }
        }
        
        # 結果を台帳のfeedbackレーンに保存
        feedback_lane = record.setdefault("lanes", {}).setdefault("feedback", {})
        feedback_lane["validation_report"] = report
        wagamama_manager._save()
        
        dev_msg = "🚨 Significant deviation!" if report["analysis"]["significant_deviation"] else "✅ Within normal variance."
        logger.info(f"🎯 [Prediction Validator] {wagamama_id}: Predicted {predicted_ctr}% vs Actual {actual_ctr}%. {dev_msg}")
        
        return report

# Singleton
prediction_validator = PredictionValidator()
