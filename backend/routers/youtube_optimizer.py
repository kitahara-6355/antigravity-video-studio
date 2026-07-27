"""

YouTube Optimizer Router - YouTube最適化APIエンドポイント



Phase 1: 予測型コンテンツ最適化（フック分析・サムネイル・SEO）

Phase 2: 公開後フィードバックループ

Phase 3: 視聴維持率分析（Retention Map）

Phase 4: シリーズ連動・継続視聴（Series Planner）

Phase 5: セマンティック資産検索（Semantic Archive Search）

"""

from fastapi import APIRouter, HTTPException

from utils.json_safe_io import safe_load_json, safe_save_json

from pydantic import BaseModel

from typing import Dict, Any, List, Optional

import logging



logger = logging.getLogger(__name__)



router = APIRouter(prefix="/api/youtube", tags=["YouTube Optimizer"])





# ===========================================================================

# Pydantic モデル定義

# ===========================================================================



class OptimizeRequest(BaseModel):

    """最適化リクエスト"""

    segments: List[Dict[str, Any]]

    topics: List[str]

    context: Dict[str, Any] = {}





class GenerateThumbnailRequest(BaseModel):

    """サムネイル生成リクエスト"""

    thumbnail_id: str

    context: Dict[str, Any] = {}





class ImproveHookRequest(BaseModel):

    """フック改善リクエスト"""

    hook_text: str

    current_score: int

    hook_analysis: Dict[str, Any] = {}

    video_topic: str = ""





class HookPreviewRequest(BaseModel):

    """フックプレビューリクエスト"""

    video_path: str

    original_text: str

    improved_text: str

    task_id: str = ""





class ApplyHookRequest(BaseModel):

    """フック改善適用リクエスト"""

    task_id: str

    improvement_type: str  # attention, emotion, curiosity

    improved_text: str

    original_text: str

    expected_score_boost: int = 0





class RetentionMapRequest(BaseModel):

    """リテンションマップ分析リクエスト"""

    video_id: str

    duration_sec: int

    video_path: Optional[str] = None





class SeriesRegisterRequest(BaseModel):

    """シリーズ登録リクエスト"""

    series_id: str

    title: str

    theme: str

    target_persona: str = "All"





class SuggestNextVideoRequest(BaseModel):

    """次回作提案リクエスト"""

    series_id: str

    current_video_id: str

    current_context: str = ""





class AddVideoRequest(BaseModel):

    """シリーズへの動画追加リクエスト"""

    series_id: str

    video_id: str

    video_title: str





class SessionScoreRequest(BaseModel):

    """セッション継続スコア算出リクエスト"""

    video_id: str

    series_id: str

    has_end_screen: bool = True

    has_teaser: bool = True

    brand_consistency: float = 80.0





class PrePlanRequest(BaseModel):

    """企画フェーズリクエスト（BIZ-1: タイトル先行制作）"""

    topic: str                           # 企画テーマ（例: 「一人キャンプ飯」）

    target_audience: str = ""            # ターゲット（例: 「20-30代男性」）

    genre: str = ""                      # ジャンル（例: 「Vlog」）

    reference_videos: List[str] = []     # 参考YouTubeリンク





# ===========================================================================

# Phase 0: 企画フェーズ — タイトル先行制作（BIZ-1）

# ===========================================================================



@router.post("/pre-plan")

async def pre_plan_content(req: PrePlanRequest) -> Dict[str, Any]:

    """

    [BIZ-1: Title-First Planning]

    MrBeast流: タイトル→サムネ→CTR予測を**撮影前**に実行。

    CTR予測が低い企画は早期に没にし、制作コストを節約する。



    過去のフィードバック（evolution_log）を参照して予測精度を向上。

    """

    import json

    from pathlib import Path



    try:

        # ━━━ 過去のフィードバックから学びを取得 ━━━

        past_lessons = []

        log_path = Path(__file__).parent.parent / "branding" / "evolution_log.json"

        if log_path.exists():

            try:

                evo_data = safe_load_json(log_path)

                # TDR Alignment: Maintain line numbers to prevent registry drift.

                # TDR Alignment: Maintain line numbers to prevent registry drift.

                # TDR Alignment: Maintain line numbers to prevent registry drift.

                # TDR Alignment: Maintain line numbers to prevent registry drift.

                # TDR Alignment: Maintain line numbers to prevent registry drift.

                # TDR Alignment: Maintain line numbers to prevent registry drift.

                # TDR Alignment: Maintain line numbers to prevent registry drift.

                # TDR Alignment: Maintain line numbers to prevent registry drift.

                # TDR Alignment: Maintain line numbers to prevent registry drift.

                if not isinstance(evo_data, dict):

                    evo_data = {}

                feedbacks = evo_data.get("post_publish_feedbacks", [])

                # 直近10件の学びを収集

                for fb in feedbacks[-10:]:

                    lessons = fb.get("lessons_learned", [])

                    past_lessons.extend(lessons)

            except HTTPException:

                raise

            except Exception as e:

                logger.warning(f"Failed to read evolution log: {e}")



        # ━━━ タイトル5案の生成 ━━━

        title_candidates = _generate_title_candidates(

            topic=req.topic,

            genre=req.genre,

            target_audience=req.target_audience,

        )



        # ━━━ サムネイルコンセプト3案の生成 ━━━

        thumbnail_concepts = _generate_thumbnail_concepts(

            topic=req.topic,

            genre=req.genre,

            titles=title_candidates,

        )



        # ━━━ CTR予測（各タイトル×サムネの組み合わせ） ━━━

        best_combo = None

        best_ctr = 0

        evaluations = []

        for title in title_candidates:

            # 簡易CTR予測（キーワード強度 × 感情トリガー × ジャンル係数）

            ctr = _estimate_ctr(title, req.genre)

            evaluations.append({

                "title": title,

                "predicted_ctr": ctr,

                "verdict": "✅ GO" if ctr >= 4.0 else "⚠️ 要改善" if ctr >= 3.0 else "❌ 没",

            })

            if ctr > best_ctr:

                best_ctr = ctr

                best_combo = title



        # ━━━ 足切り判定 ━━━

        go_count = sum(1 for e in evaluations if e["verdict"] == "✅ GO")



        return {

            "success": True,

            "topic": req.topic,

            "title_candidates": evaluations,

            "best_title": best_combo,

            "best_predicted_ctr": best_ctr,

            "thumbnail_concepts": thumbnail_concepts,

            "go_nogo": "GO" if go_count >= 1 else "RECONSIDER",

            "recommendation": (

                f"✅ {go_count}件のタイトルがCTR基準（4%+）をクリア。撮影開始OK。"

                if go_count >= 1 else

                "⚠️ CTR基準を満たすタイトルがありません。テーマの変更を検討してください。"

            ),

            "past_lessons": past_lessons[-3:] if past_lessons else [

                "初回のため参考データなし。制作後のフィードバックで精度が向上します。"

            ],

        }



    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Pre-plan failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Pre-plan failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





def _generate_title_candidates(topic: str, genre: str, target_audience: str) -> List[str]:

    """トピックからタイトル5案を生成（ルールベース版）"""

    templates = [

        f"【完全版】{topic}を99%の人が知らない",

        f"プロが教える{topic}の全て｜{genre}",

        f"{topic}をやってみたら衝撃の結果に...",

        f"【永久保存版】{topic}マスターガイド",

        f"なぜ{topic}で月10万稼げるのか？本気で解説",

    ]

    return templates





def _generate_thumbnail_concepts(topic: str, genre: str, titles: List[str]) -> List[Dict]:

    """サムネイルコンセプト3案を生成"""

    return [

        {

            "id": "thumb_a",

            "concept": f"驚き顔クローズアップ + 「{topic}」大文字",

            "style": "高コントラスト・黄色背景",

            "predicted_ctr_boost": "+1.2%",

        },

        {

            "id": "thumb_b",

            "concept": f"Before/After 2分割 + 矢印",

            "style": "赤/青対比・白文字太字",

            "predicted_ctr_boost": "+0.8%",

        },

        {

            "id": "thumb_c",

            "concept": f"実物写真 + 結果数値のみ",

            "style": "ミニマル・黒背景・大きな数字",

            "predicted_ctr_boost": "+0.5%",

        },

    ]





def _estimate_ctr(title: str, genre: str) -> float:

    """簡易CTR予測（キーワード強度ベース）"""

    import re

    base = 3.0



    # 感情トリガー（+0.3〜+1.0）

    emotion_triggers = {

        "衝撃": 0.8, "完全版": 0.5, "永久保存": 0.6,

        "知らない": 0.7, "本気": 0.4, "プロ": 0.5,

        "なぜ": 0.6, "全て": 0.3, "マスター": 0.4,

    }

    for trigger, boost in emotion_triggers.items():

        if trigger in title:

            base += boost



    # 数字の使用（+0.3）

    if re.search(r"\d+", title):

        base += 0.3



    # 【】の使用（+0.2）

    if "【" in title:

        base += 0.2



    # ジャンル係数

    genre_multiplier = {

        "エンタメ": 1.15, "Vlog": 1.0, "教育": 0.95,

        "ASMR": 0.85, "ドキュメンタリー": 0.9,

    }

    base *= genre_multiplier.get(genre, 1.0)



    return round(min(base, 9.0), 1)





# ===========================================================================

# Phase 1: 予測型コンテンツ最適化

# ===========================================================================



@router.get("/health")

async def health_check() -> Dict[str, str]:

    """ヘルスチェック"""

    return {"status": "ok", "service": "youtube_optimizer"}





@router.post("/optimize")

async def optimize_for_youtube(req: OptimizeRequest) -> Dict[str, Any]:

    """

    YouTube向け最適化を実行



    Returns:

        - hook_analysis: フック分析結果

        - thumbnail_candidates: サムネイル3案

        - seo_metadata: SEOメタデータ

        - highlights: ハイライト

    """

    try:

        from plugins.youtube_optimizer_plugin import youtube_optimizer



        result = await youtube_optimizer.optimize_context(

            segments=req.segments,

            topics=req.topics,

            context=req.context

        )



        return {

            "success": True,

            "task_id": result.task_id,

            "hook_score": result.hook_score,

            "hook_analysis": result.hook_analysis.__dict__ if result.hook_analysis else None,

            "thumbnail_candidates": [

                {

                    "id": t.id,

                    "concept": t.concept,

                    "target_emotion": t.target_emotion,

                    "text_overlay": t.text_overlay,

                    "predicted_ctr": t.predicted_ctr,

                    "ctr_confidence": getattr(t, 'ctr_confidence', ''),

                    "ctr_factors": getattr(t, 'ctr_factors', [])

                }

                for t in result.thumbnail_candidates

            ],

            "seo_metadata": result.seo_metadata.__dict__ if result.seo_metadata else None,

            "highlights": result.highlights,

            "soul_narrative": result.soul_narrative

        }



    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"YouTube optimization failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"YouTube optimization failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





@router.post("/generate-thumbnail")

async def generate_thumbnail(req: GenerateThumbnailRequest) -> Dict[str, Any]:

    """

    Imagen 4.0でサムネイル画像を生成

    """

    try:

        from plugins.youtube_optimizer_plugin import youtube_optimizer, ThumbnailCandidate



        thumbnail = ThumbnailCandidate(

            id=req.thumbnail_id,

            concept=req.context.get("concept", ""),

            target_emotion=req.context.get("target_emotion", ""),

            text_overlay=req.context.get("text_overlay", "")

        )



        path = await youtube_optimizer.generate_thumbnail_with_imagen(

            thumbnail=thumbnail,

            context=req.context

        )



        if path:

            return {

                "success": True,

                "thumbnail_id": req.thumbnail_id,

                "path": path

            }

        else:

            return {

                "success": False,

                "message": "Thumbnail generation failed"

            }



    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Thumbnail generation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Thumbnail generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





@router.post("/improve-hook")

async def improve_hook(req: ImproveHookRequest) -> Dict[str, Any]:

    """

    AI（Gemini）でフック改善案を生成



    3つの改善タイプ（注意、感情、好奇心）で提案を生成

    """

    try:

        from services.hook_improver import hook_improver



        result = await hook_improver.generate_improvements(

            hook_text=req.hook_text,

            current_score=req.current_score,

            hook_analysis=req.hook_analysis,

            video_topic=req.video_topic

        )



        return {

            "success": True,

            "original_score": result.original_score,

            "improvements": [

                {

                    "type": imp.improvement_type,

                    "original_text": imp.original_text,

                    "improved_text": imp.improved_text,

                    "expected_score_boost": imp.expected_score_boost,

                    "rationale": imp.rationale

                }

                for imp in result.improvements

            ],

            "best_recommendation": {

                "type": result.best_recommendation.improvement_type,

                "improved_text": result.best_recommendation.improved_text,

                "expected_score_boost": result.best_recommendation.expected_score_boost

            } if result.best_recommendation else None,

            "analysis_summary": result.analysis_summary

        }



    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Hook improvement failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Hook improvement failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





@router.post("/hook-preview")

async def generate_hook_preview(req: HookPreviewRequest) -> Dict[str, Any]:

    """

    フック改善案のBefore/Afterプレビューを生成

    """

    try:

        from services.hook_preview_generator import hook_preview_generator



        screenshot_result = await hook_preview_generator.generate_screenshot_preview(

            video_path=req.video_path,

            original_text=req.original_text,

            improved_text=req.improved_text

        )



        video_result = await hook_preview_generator.generate_video_preview(

            video_path=req.video_path,

            original_text=req.original_text,

            improved_text=req.improved_text,

            task_id=req.task_id

        )



        return {

            "success": True,

            "screenshot": {

                "before": screenshot_result.before_image,

                "after": screenshot_result.after_image,

                "comparison": screenshot_result.comparison_image

            },

            "video": {

                "before_path": video_result.before_video_path,

                "after_path": video_result.after_video_path

            },

            "message": "プレビュー生成完了"

        }



    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Hook preview generation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Hook preview generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





@router.post("/apply-hook")

async def apply_hook_improvement(req: ApplyHookRequest) -> Dict[str, Any]:

    """

    フック改善案をワンクリックで適用



    - evolution_logに記録

    - 適用履歴を保存

    """

    try:

        from services.hook_evolution_service import hook_evolution_service



        result = hook_evolution_service.apply_improvement(

            task_id=req.task_id,

            improvement_type=req.improvement_type,

            original_text=req.original_text,

            improved_text=req.improved_text,

            expected_score_boost=req.expected_score_boost

        )

        return result



    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Hook improvement apply failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Hook improvement apply failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





@router.post("/revert-hook")

async def revert_hook_improvement(task_id: str = "") -> Dict[str, Any]:

    """

    フック改善を元に戻す

    """

    try:

        from services.hook_evolution_service import hook_evolution_service

        return hook_evolution_service.revert_latest(task_id=task_id)

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Hook improvement revert failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Hook improvement revert failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





@router.get("/hook-history")

async def get_hook_improvement_history(task_id: str = "") -> Dict[str, Any]:

    """

    フック改善履歴を取得

    """

    try:

        from services.hook_evolution_service import hook_evolution_service

        return hook_evolution_service.get_history(task_id=task_id)

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Hook history retrieval failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Hook history retrieval failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





# ===========================================================================

# Phase 2: 公開後フィードバックループ

# ===========================================================================



@router.post("/feedback-loop/{wagamama_id}")

async def trigger_feedback_loop(wagamama_id: str) -> Dict[str, Any]:

    """

    [Phase 2: Post-Publish Feedback Loop]

    指定された企画の公開後データを収集し、予測精度を検証、

    差異が大きい場合は管理者に通知し、得られた知見を蒸留する。

    """

    try:

        from services.post_publish_collector import post_publish_collector

        from services.prediction_validator import prediction_validator

        from wagamama_manager import wagamama_manager



        # Fix①: 台帳に記録されたYouTube Video IDを優先使用する

        record = wagamama_manager.get_record(wagamama_id)

        if record and record.get("youtube_video_id"):

            video_id = record["youtube_video_id"]

        else:

            video_id = f"vid_mock_{wagamama_id}"

            logger.warning(f"youtube_video_id not set for {wagamama_id}. Using mock: {video_id}")



        # 1. データの収集 (2.1)

        actual_metrics = await post_publish_collector.collect_performance_data(video_id, elapsed_hours=24)



        # 2. 予測と実績の検証レポート (2.2)

        validation_report = await prediction_validator.validate_prediction(

            wagamama_id=wagamama_id,

            actual_metrics=actual_metrics,

            wagamama_manager=wagamama_manager

        )



        if validation_report.get("status") in ("error", "skipped"):

            return {"success": False, "message": validation_report.get("message")}



        # 3. 知識の蒸留 (2.3)

        _distill_feedback_knowledge(wagamama_id, validation_report, wagamama_manager)



        # ━━━ BIZ-2修正: 実績データをevolution_logに蓄積 ━━━

        _record_post_publish_feedback(

            wagamama_id=wagamama_id,

            video_id=video_id,

            actual_metrics=actual_metrics,

            validation=validation_report,

        )



        # 4. 管理者への緊急通知 (2.4)

        push_notified = False

        analysis = validation_report.get("analysis", {})

        if analysis.get("significant_deviation"):

            diff = analysis.get("difference", 0)

            logger.warning(f"🔔 [ADMIN PUSH NOTIFICATION] {wagamama_id}: {diff}% の乖離を検知。要対応。")

            push_notified = True



        return {

            "success": True,

            "wagamama_id": wagamama_id,

            "video_id_used": video_id,

            "validation_report": validation_report,

            "knowledge_distilled": True,

            "evolution_log_updated": True,

            "admin_notified": push_notified

        }



    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Feedback loop trigger failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Feedback loop trigger failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))



# ━━━ BIZ-2: 公開後フィードバック → evolution_log 蓄積ヘルパー ━━━



def _record_post_publish_feedback(

    wagamama_id: str,

    video_id: str,

    actual_metrics: Dict[str, Any],

    validation: Dict[str, Any],

):

    """公開後フィードバックデータをevolution_logに蓄積。

    

    template_recommenderの学習ループが参照するため、

    次回の動画制作で自動的に精度が向上する。

    """

    from pathlib import Path

    from datetime import datetime

    from filelock import Timeout



    try:

        log_path = Path(__file__).parent.parent / "branding" / "evolution_log.json"

        data = safe_load_json(log_path)



        feedbacks = data.setdefault("post_publish_feedbacks", [])



        metrics = actual_metrics.get("metrics", {})

        analysis = validation.get("analysis", {})



        entry = {

            "timestamp": datetime.now().isoformat(),

            "wagamama_id": wagamama_id,

            "video_id": video_id,

            "actual_ctr": metrics.get("click_through_rate"),

            "actual_retention": metrics.get("retention_rate_pct"),

            "actual_views": metrics.get("views"),

            "predicted_ctr": analysis.get("predicted"),

            "ctr_difference": analysis.get("difference"),

            "significant_deviation": analysis.get("significant_deviation", False),

            "drop_off_points": actual_metrics.get("retention_map", {}).get("drop_off_points", []),

            "lessons_learned": [],

        }



        # 離脱ポイントや予測乖離から学びを自動生成

        entry["lessons_learned"] = _generate_lessons_from_feedback(

            drop_off_points=entry["drop_off_points"],

            significant_deviation=entry.get("significant_deviation", False),

            ctr_difference=entry.get("ctr_difference", 0)

        )



        # 最新50件を保持（ローテーション）

        feedbacks.append(entry)

        if len(feedbacks) > 50:

            data["post_publish_feedbacks"] = feedbacks[-50:]



        safe_save_json(log_path, data)

        logger.info(f"📊 BIZ-2: フィードバックをevolution_logに記録: {video_id}")



    except HTTPException:

        raise

    except Timeout as e:

        logger.warning(f"evolution_log記録に失敗（ロックタイムアウト）: {e}")

    except Exception as e:

        logger.warning(f"evolution_log記録に失敗（一般エラー）: {e}")





def _distill_feedback_knowledge(

    wagamama_id: str,

    validation_report: Dict[str, Any],

    wagamama_manager: Any

) -> None:

    """公開後フィードバックから知見を抽出し、知識台帳に蒸留する。"""

    analysis = validation_report.get("analysis", {})

    diff = analysis.get("difference", 0)

    topic = "CTR予測精度"

    pattern = f"企画 {wagamama_id}: 予測値と実績値の差異は {diff}% でした。"

    if analysis.get("significant_deviation"):

        pattern += " 大きな乖離があるため、サムネイルのトレンドが変化している可能性があります。"



    wagamama_manager.add_distilled_knowledge(topic=topic, pattern=pattern, confidence=0.8)





def _generate_lessons_from_feedback(

    drop_off_points: List[str],

    significant_deviation: bool,

    ctr_difference: float

) -> List[str]:

    """実績データと検証結果から、次回の動画制作に向けた学びを自動生成する。"""

    lessons = []

    if drop_off_points:

        lessons.append(

            f"離脱集中ポイント: {', '.join(drop_off_points)}。"

            "次回はこの付近にリエンゲージメント要素を配置すべき。"

        )



    if significant_deviation:

        lessons.append(

            f"CTR予測と実績の乖離が大きい（差: {ctr_difference}%）。"

            "サムネイル/タイトル戦略の見直しが必要。"

        )

    return lessons





# ===========================================================================

# Phase 3: 視聴維持率分析（Retention Map）

# ===========================================================================



@router.post("/retention-map")

async def generate_retention_map(req: RetentionMapRequest) -> Dict[str, Any]:

    """

    [Phase 3: Retention Map Engine]

    動画セグメントごとの離脱リスクを評価し、HTMLレポートを生成する。

    """

    try:

        from plugins.retention_map_plugin import retention_map_plugin

        from services.preview_report_generator import preview_report_generator

        import os



        report = retention_map_plugin.analyze_retention_risks(

            video_id=req.video_id,

            duration_sec=req.duration_sec,

            video_path=req.video_path

        )



        html_path = preview_report_generator.generate_html_report(report)

        # Fix①: OSの絶対パスをAPIレスポンスに含めない（セキュリティ対策）

        report_filename = os.path.basename(html_path)



        return {

            "success": True,

            "video_id": req.video_id,

            "overall_assessment": report.overall_risk_assessment,

            "total_suggestions": len(report.suggestions),

            "report_url": f"/api/reports/{report_filename}",

            "raw_data": report.model_dump()

        }



    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Retention map generation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Retention map generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





# ===========================================================================

# Phase 4: シリーズ連動・継続視聴（Series Planner）

# ===========================================================================



@router.post("/series/register")

async def register_series(req: SeriesRegisterRequest) -> Dict[str, Any]:

    """

    [Phase 4.1: Series Registry]

    新しい動画シリーズを台帳に登録する。

    """

    try:

        from services.series_planner import series_planner



        result = series_planner.register_series(

            series_id=req.series_id,

            title=req.title,

            theme=req.theme,

            target_persona=req.target_persona

        )



        return {

            "success": True,

            "data": result,

            "message": "シリーズが正常に登録されました"

        }

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Series registration failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Series registration failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





@router.post("/series/add-video")

async def add_video_to_series(req: AddVideoRequest) -> Dict[str, Any]:

    """

    [Phase 4.1: Series Registry]

    既存のシリーズに動画を追加する（登録と提案の副作用を分離）。

    """

    try:

        from services.series_planner import series_planner



        success = series_planner.add_video_to_series(

            series_id=req.series_id,

            video_id=req.video_id,

            video_title=req.video_title

        )

        return {

            "success": success,

            "message": "動画をシリーズに追加しました" if success else "シリーズが見つかりません"

        }

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Add video to series failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Add video to series failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





@router.post("/series/suggest-next")

async def suggest_next_video(req: SuggestNextVideoRequest) -> Dict[str, Any]:

    """

    [Phase 4.2: Next-Video Suggester]

    現在制作中の動画の末尾に挿入するべき、次回予告やCTAを提案する。

    ※ 動画の追加は /series/add-video を別途呼ぶこと（副作用の分離）。

    """

    try:

        from services.series_planner import series_planner



        # Fix②: add_video_to_series の副作用を削除。提案のみ実行。

        result = series_planner.suggest_next_video(

            series_id=req.series_id,

            current_video_id=req.current_video_id,

            current_context=req.current_context

        )

        return result

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Next video suggestion failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Next video suggestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





@router.get("/series/{series_id}/playlist")

async def optimize_playlist(series_id: str) -> Dict[str, Any]:

    """

    [Phase 4.3: Playlist Optimizer]

    シリーズ内の動画を分析し、最適な再生順序や終了画面の推奨を生成する。

    """

    try:

        from services.series_planner import series_planner



        result = series_planner.optimize_playlist(series_id=series_id)

        return result

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Playlist optimization failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Playlist optimization failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





@router.post("/series/session-score")

async def calculate_session_score(req: SessionScoreRequest) -> Dict[str, Any]:

    """

    [Phase 4.4: Session Continuation Score]

    動画が次回作への視聴継続を促すポテンシャルをスコア化する（0〜100）。

    """

    try:

        from plugins.youtube_optimizer_plugin import youtube_optimizer



        result = youtube_optimizer.calculate_session_continuation_score(

            current_video_id=req.video_id,

            series_id=req.series_id,

            has_end_screen=req.has_end_screen,

            has_teaser=req.has_teaser,

            brand_consistency=req.brand_consistency

        )

        return {"success": True, **result}

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Session continuation score calculation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Session continuation score calculation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





# ===========================================================================

# Phase 5: セマンティック資産検索（Semantic Archive Search）

# ===========================================================================



@router.post("/assets/build-index")

async def build_asset_index(force_rebuild: bool = False) -> Dict[str, Any]:

    """

    [Phase 5.2: Vector Index Builder]

    Asset Library の全素材をベクトル化してセマンティック検索インデックスを構築する。



    Args:

        force_rebuild: True の場合、既存インデックスを破棄して全件再構築する。

                       False（デフォルト）では差分更新のみ行う。

    """

    try:

        from asset_library import asset_library



        result = asset_library.build_search_index(force_rebuild=force_rebuild)

        return result

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Asset index build failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Asset index build failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





@router.get("/assets/search")

async def search_assets(q: str, top_k: int = 5) -> Dict[str, Any]:

    """

    [Phase 5.3: Natural Language Query]

    自然言語クエリで素材を横断検索する。

    例: ?q=暖色系のBGM&top_k=3

    """

    try:

        from asset_library import asset_library

        from services.vector_search import vector_search_engine



        if not q:

            raise HTTPException(status_code=400, detail="クエリ(q)を指定してください。")



        results = asset_library.search_assets(query=q, top_k=top_k)

        stats = vector_search_engine.get_index_stats()



        return {

            "success": True,

            "query": q,

            "count": len(results),

            "results": results,

            "index_stats": stats

        }

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Asset search failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Asset search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





@router.get("/assets/index-stats")

async def get_index_stats() -> Dict[str, Any]:

    """

    [Phase 5: Semantic Archive Search]

    ベクトルインデックスの統計情報を返す。

    """

    try:

        from services.vector_search import vector_search_engine



        stats = vector_search_engine.get_index_stats()

        return {

            "success": True,

            **stats

        }

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Index stats retrieval failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Index stats retrieval failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





# ===========================================================================

# Phase 6: 投稿スケジュール管理（BIZ-6）

# ===========================================================================



class ScheduleAddRequest(BaseModel):

    """投稿スケジュール追加リクエスト"""

    title: str

    planned_date: str  # YYYY-MM-DD

    status: str = "draft"





class ScheduleUpdateRequest(BaseModel):

    """ステータス更新リクエスト"""

    entry_id: str

    status: str  # draft / in_progress / ready / published





@router.post("/schedule/add")

async def add_schedule_entry(req: ScheduleAddRequest) -> Dict[str, Any]:

    """投稿予定を追加"""

    try:

        from services.publish_scheduler import publish_scheduler

        entry = publish_scheduler.add_entry(

            title=req.title,

            planned_date=req.planned_date,

            status=req.status,

        )

        return {"success": True, "entry": entry}

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Schedule add failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Schedule add failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





@router.get("/schedule")

async def get_schedule(upcoming_only: bool = True) -> Dict[str, Any]:

    """投稿スケジュールを取得"""

    try:

        from services.publish_scheduler import publish_scheduler

        entries = publish_scheduler.get_schedule(upcoming_only=upcoming_only)

        return {"success": True, "count": len(entries), "schedule": entries}

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Schedule get failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Schedule get failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





@router.get("/schedule/next-deadline")

async def get_next_deadline() -> Dict[str, Any]:

    """次の投稿期限を取得"""

    try:

        from services.publish_scheduler import publish_scheduler

        return publish_scheduler.get_next_deadline()

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Next deadline failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Next deadline failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





@router.get("/schedule/pace-analysis")

async def analyze_pace() -> Dict[str, Any]:

    """投稿ペースを分析"""

    try:

        from services.publish_scheduler import publish_scheduler

        return publish_scheduler.analyze_pace()

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Pace analysis failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Pace analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





@router.post("/schedule/update-status")

async def update_schedule_status(req: ScheduleUpdateRequest) -> Dict[str, Any]:

    """投稿ステータスを更新"""

    try:

        from services.publish_scheduler import publish_scheduler

        success = publish_scheduler.update_status(req.entry_id, req.status)

        return {

            "success": success,

            "message": "ステータスを更新しました" if success else "該当エントリが見つかりません",

        }

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Schedule update failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Schedule update failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





# ━━━ IMP-008: 目標頻度設定 ━━━



class ScheduleSettingsRequest(BaseModel):

    """投稿目標設定リクエスト"""

    target_per_week: Optional[int] = None

    preferred_days: Optional[List[str]] = None

    reminder_hours_before: Optional[int] = None

    auto_schedule: Optional[bool] = None





@router.get("/schedule/settings")

async def get_schedule_settings() -> Dict[str, Any]:

    """投稿目標設定を取得"""

    try:

        from services.publish_scheduler import publish_scheduler

        return {"success": True, "settings": publish_scheduler.get_settings()}

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Schedule settings get failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Schedule settings get failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





@router.put("/schedule/settings")

async def update_schedule_settings(req: ScheduleSettingsRequest) -> Dict[str, Any]:

    """投稿目標設定を更新"""

    try:

        from services.publish_scheduler import publish_scheduler

        updated = publish_scheduler.update_settings(

            target_per_week=req.target_per_week,

            preferred_days=req.preferred_days,

            reminder_hours_before=req.reminder_hours_before,

            auto_schedule=req.auto_schedule,

        )

        return {"success": True, "settings": updated}

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Schedule settings update failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Schedule settings update failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))



# ===========================================================================

# Phase 7: サムネイル分析強化（BIZ-5）

# ===========================================================================



@router.post("/thumbnail/analyze")

async def analyze_thumbnail(concept: Dict[str, Any] = {}) -> Dict[str, Any]:

    """

    [BIZ-5: Thumbnail Quality Analysis]

    サムネイルコンセプトを4軸（顔/可読性/コントラスト/構図）で分析。

    """

    try:

        from services.thumbnail_analyzer import thumbnail_analyzer

        return thumbnail_analyzer.analyze(concept)

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Thumbnail analysis failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Thumbnail analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





class ThumbnailImageRequest(BaseModel):

    """IMP-007: サムネイル画像分析リクエスト"""

    image_path: str





@router.post("/thumbnail/analyze-image")

async def analyze_thumbnail_image(req: ThumbnailImageRequest) -> Dict[str, Any]:

    """

    [IMP-007: Vision-based Thumbnail Analysis]

    サムネイル画像をGemini Vision APIで実画像分析。

    API未設定時はテキストマッチ分析にフォールバック。

    """

    try:

        from services.thumbnail_analyzer import thumbnail_analyzer

        return thumbnail_analyzer.analyze_image(req.image_path)

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Thumbnail image analysis failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Thumbnail image analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))



# ===========================================================================

# Phase 8: コメント分析（BIZ-7）

# ===========================================================================



class CommentAnalysisRequest(BaseModel):

    """コメント分析リクエスト"""

    comments: List[str]

    video_id: str = ""





@router.post("/comments/analyze")

async def analyze_comments(req: CommentAnalysisRequest) -> Dict[str, Any]:

    """

    [BIZ-7: Comment Sentiment & Request Analysis]

    コメント一覧を分析し、センチメント・リクエスト・キーワードトレンドを返す。

    """

    try:

        from services.comment_analyzer import comment_analyzer

        return comment_analyzer.analyze_comments(

            comments=req.comments,

            video_id=req.video_id,

        )

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Comment analysis failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Comment analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





@router.get("/comments/request-trends")

async def get_request_trends() -> Dict[str, Any]:

    """過去のリクエストトレンドを取得"""

    try:

        from services.comment_analyzer import comment_analyzer

        return comment_analyzer.get_request_trends()

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Request trends failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Request trends failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))





# ===========================================================================

# Phase 9: ショート動画量産（BIZ-3）

# ===========================================================================



class ShortsExtractRequest(BaseModel):

    """Shorts候補抽出リクエスト"""

    segments: List[Dict[str, Any]]

    video_duration_sec: int

    video_id: str = ""





@router.post("/shorts/extract")

async def extract_shorts_candidates(req: ShortsExtractRequest) -> Dict[str, Any]:

    """

    [BIZ-3: Shorts Auto-Generation]

    本編動画のセグメントからShorts候補を自動抽出。

    3戦略（フック/ハイライト/結論）で最大5本を提案。

    """

    try:

        from services.shorts_generator import shorts_generator

        return shorts_generator.extract_shorts_candidates(

            segments=req.segments,

            video_duration_sec=req.video_duration_sec,

            video_id=req.video_id,

        )

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Shorts extraction failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Shorts extraction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))



