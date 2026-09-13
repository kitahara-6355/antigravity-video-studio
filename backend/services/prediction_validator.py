import logging
from typing import Any, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────
# 実測でない値に印を付ける（R1.5-C4・19周目）
#
# 以前ここは `actual`（＝実測）という名前の下に**既定値**を置いていた:
#
#     "ctr": metrics.get("click_through_rate", 0.0)
#     "elapsed_hours": actual_metrics_dict.get("elapsed_hours", 24)
#
# `elapsed_hours` は post_publish_collector の `_generate_mock_data()`
# （モック経路）でしか産出されない鍵で、実 API 統合（api_mode が real）は
# NotImplementedError を投げる。**実データが流れ始めた日にこそ既定値の 24 が
# 効き続ける。** CTR も同じで、届かなければ 0.0 が入り、予測 5.0% に対して
# 「誤差 100%・重大な乖離」という**計測していない判定**が出て、
# 管理者通知（trigger_feedback_loop のログ）まで飛んでいた。
#
# 問題は返り値だけではない。このレポートは末尾で台帳（Wagamama Ledger）の
# feedback レーンへ入り `_save()` で**恒久保存される。**
# 18周目に直した「作り物が台帳に焼き付く」と同型で、一度書くと後から
# 実測と区別できない。
#
# 作法は backend/user_model_marks.py に合わせる。
# **0 や 24 は「実際に取りうる値」なので印にならない** → 値そのものを None にする。
# ─────────────────────────────────────────────────────────────────────────

# 実測値が1つも届いていないときの印
_未計測の印 = {
    "is_real": False,
    "data_source": "unavailable",
    "note": "**YouTube から取得した実績ではありません。**実測値が届いていないため、"
            "予測との突き合わせを行っていません",
}

# 収集側が作り物（is_mock）だと申告しているときの印
_作り物の印 = {
    "is_real": False,
    "data_source": "sample",
    "note": "**作り物の数字です。**post_publish_collector のモック"
            "（YOUTUBE_API_MODE=mock）が組み立てた値なので、"
            "予測との突き合わせを行っていません",
}

# 実測が届いたときの印。読み手が古い行と区別できるように明示する
_実測の印 = {
    "is_real": True,
    "data_source": "measured",
}


def _実数のみ(値: Any) -> Optional[float]:
    """**fail-closed。** 数値として使える値だけ通し、それ以外は None を返す。

    bool は Python では int の一種だが CTR や経過時間としては意味を成さないので弾く。
    既定値で「実測」を埋めないための入口（R1.5-C4・19周目）。
    """
    if isinstance(値, bool):
        return None
    if isinstance(値, (int, float)):
        return 値
    return None


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

        **実測 CTR が届いていない（または作り物の）ときは `status: "skipped"` を返し、
        台帳には書かない。** 呼び出し元の trigger_feedback_loop は status が
        skipped なら success: False を返すので、計測していない結果が
        success を名乗らない（R1.5-C4・19周目）。
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

        # **既定値で「実測」を埋めない**（R1.5-C4・19周目）。届いていなければ None のまま
        actual_ctr = _実数のみ(metrics.get("click_through_rate"))
        elapsed_hours = _実数のみ(actual_metrics_dict.get("elapsed_hours"))

        # 収集時刻も、実測が無いなら None。作り物に時刻を付けると
        # 「いま計測した」に見える（user_model_marks の last_updated と同じ扱い）
        measured_at = actual_metrics_dict.get("metrics_timestamp")
        if not isinstance(measured_at, str) or not measured_at.strip():
            measured_at = None

        # 収集側は is_mock を立てている。呼び出し元が 501 で止めるので通常は来ないが、
        # **台帳へ焼き付ける側はここなので、ここでも作り物を実測として扱わない**
        作り物 = bool(actual_metrics_dict.get("is_mock"))
        計測できている = (actual_ctr is not None) and not 作り物

        if 計測できている:
            印 = dict(_実測の印)
            未計測の理由 = None
        elif 作り物:
            印 = dict(_作り物の印)
            未計測の理由 = ("post_publish_collector が作り物（is_mock）を返しています。"
                        "実測ではないので予測との突き合わせを行いません")
        else:
            印 = dict(_未計測の印)
            未計測の理由 = ("実測 CTR（click_through_rate）が届いていません。"
                        "0.0 で埋めると「CTR 0% という実績」に見えるので検証を行いません")

        actual_block = {
            "ctr": actual_ctr if 計測できている else None,
            "elapsed_hours": elapsed_hours if 計測できている else None,
            "measured_at": measured_at if 計測できている else None,
        }
        actual_block.update(印)

        if not 計測できている:
            analysis = {
                "checked": False,
                "skip_reason": 未計測の理由,
                "predicted": predicted_ctr,
                "actual": None,
                "difference": None,
                "error_margin_pct": None,
                "significant_deviation": None,
            }
        elif predicted_ctr > 0:
            # 差異の計算 (+ なら実績が予測を超えた)
            diff_pct = actual_ctr - predicted_ctr
            # 予測誤差率 (絶対値で、予測値に対する割合)
            error_margin = abs(diff_pct) / predicted_ctr
            analysis = {
                "checked": True,
                "predicted": predicted_ctr,
                "actual": actual_ctr,
                "difference": round(diff_pct, 2),
                "error_margin_pct": round(error_margin * 100, 2),
                "significant_deviation": error_margin > 0.3, # 30%以上ズレている場合は重要フラグ
            }
        else:
            # 予測 CTR が 0 以下だと誤差率を割り算できない。以前はここで
            # error_margin = 0 に落として significant_deviation を False にし、
            # ログにも「Within normal variance」と出していた。
            # **判定していないのに「予測が当たった」に見える**ので None を置く
            analysis = {
                "checked": False,
                "skip_reason": "予測 CTR が 0 以下なので誤差率を計算できません",
                "predicted": predicted_ctr,
                "actual": actual_ctr,
                "difference": round(actual_ctr - predicted_ctr, 2),
                "error_margin_pct": None,
                "significant_deviation": None,
            }

        report = {
            "wagamama_id": wagamama_id,
            "validated_at": datetime.now().isoformat(),
            "prediction": {
                "ctr": predicted_ctr,
            },
            "actual": actual_block,
            "analysis": analysis
        }

        if not 計測できている:
            # **台帳に書かない。** ここで _save() すると「検証した」体裁の行が
            # feedback レーンへ恒久保存され、過去の本物のレポートまで上書きしてしまう
            report["status"] = "skipped"
            report["message"] = 未計測の理由
            logger.warning(
                f"⏭️ [Prediction Validator] {wagamama_id}: {未計測の理由}"
                "（台帳には記録しません）"
            )
            return report

        # 結果を台帳のfeedbackレーンに保存
        # **印を落とさない。** 返り値と同じ dict をそのまま入れるので、
        # is_real / data_source は永続化された側にも残る（18周目の反例は
        # 「返り値だけ直して台帳は素のまま」だった）
        feedback_lane = record.setdefault("lanes", {}).setdefault("feedback", {})
        feedback_lane["validation_report"] = report
        wagamama_manager._save()

        if analysis["significant_deviation"] is True:
            dev_msg = "🚨 Significant deviation!"
        elif analysis["checked"]:
            dev_msg = "✅ Within normal variance."
        else:
            dev_msg = "⚠️ Deviation not evaluated."
        logger.info(f"🎯 [Prediction Validator] {wagamama_id}: Predicted {predicted_ctr}% vs Actual {actual_ctr}%. {dev_msg}")

        return report

# Singleton
prediction_validator = PredictionValidator()
