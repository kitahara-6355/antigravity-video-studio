"""
themes_router.py — テンプレート × テーマ 2階層システム（U-13）

設計思想:
  テンプレート（Template）= 業界水準の制作フォーマット
    → 字幕ルール、エンゲージメント基準、品質パラメータを定義
    → NHKドキュメンタリー風、MrBeastエンタメ風 など

  テーマ（Theme）= テンプレート内の雰囲気調整
    → カラーパレット、タイポグラフィ、モーション
    → warm, cool, energetic, calm

  チャンネル主のフロー:
    ① テンプレートを選ぶ（業界プロの制作ルールを採用）
    ② テーマで雰囲気を微調整（自分好みの色味・フォント）

PROJECT_CONSTITUTION §17 準拠 + MARKET_RESEARCH_POLICY.md 準拠
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import logging

try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/themes", tags=["themes"])


# ============================================================
# データモデル
# ============================================================

class TemplateApplyRequest(BaseModel):
    template_id: str
    theme_id: str = "warm"
    reason: Optional[str] = "チャンネル主がUI から適用"


# ============================================================
# レイヤー1: テンプレート（業界基準の制作フォーマット）
# ============================================================

from template_constants import PRODUCTION_TEMPLATES, MOOD_THEMES, RECOMMENDED_COMBOS


# ============================================================
# エンドポイント
# ============================================================

@router.get("/health")
async def health_check():
    """テーマシステムヘルスチェック"""
    return {
        "status": "ok",
        "service": "themes",
        "templates_count": len(PRODUCTION_TEMPLATES),
        "themes_count": len(MOOD_THEMES),
    }


@router.get("/templates")
async def list_templates():
    """レイヤー1: 利用可能なテンプレート（業界基準フォーマット）一覧"""
    templates = []
    for tid, t in PRODUCTION_TEMPLATES.items():
        templates.append({
            "id": t["id"],
            "name": t["name"],
            "label": t["label"],
            "description": t["description"],
            "reference": t["reference"],
            "target_genre": t["target_genre"],
            "recommended_themes": RECOMMENDED_COMBOS.get(tid, list(MOOD_THEMES.keys())),
        })

    return {
        "templates": templates,
        "count": len(templates),
    }


@router.get("/templates/{template_id}")
async def get_template(template_id: str):
    """テンプレートの詳細（品質基準含む）を取得"""
    if template_id not in PRODUCTION_TEMPLATES:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    tmpl = PRODUCTION_TEMPLATES[template_id]
    return {
        "template": tmpl,
        "recommended_themes": RECOMMENDED_COMBOS.get(template_id, []),
        "available_themes": list(MOOD_THEMES.keys()),
    }


@router.get("")
async def list_themes():
    """レイヤー2: 利用可能なテーマ（雰囲気調整）一覧"""
    themes = []
    for tid, t in MOOD_THEMES.items():
        themes.append({
            "id": t["id"],
            "label": t["label"],
            "description": t["description"],
            "color_palette": t["design_tokens"]["color_palette"],
        })

    return {
        "themes": themes,
        "count": len(themes),
    }


# ============================================================
# UX-5修正: 管理者向けテンプレート選択統計
# ============================================================

@router.get("/stats")
async def get_template_stats():
    """
    テンプレート選択統計（管理者向け）。

    evolution_log の template_selections を集計。
    """
    import json
    from pathlib import Path
    from collections import Counter

    try:
        log_path = _writable_path("backend/branding/evolution_log.json")
        if not log_path.exists():
            return {"stats": {}, "total_selections": 0}

        try:
            content = log_path.read_text(encoding="utf-8")
            if not content.strip():
                return {"stats": {}, "total_selections": 0}
            data = json.loads(content)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to read or parse evolution_log.json: {e}")
            return {"stats": {}, "total_selections": 0}

        if not isinstance(data, dict):
            return {"stats": {}, "total_selections": 0}

        selections = data.get("template_selections", [])
        if not isinstance(selections, list):
            selections = []

        # テンプレート別集計
        template_counts = Counter()
        theme_counts = Counter()
        sat_by_template = {}

        for s in selections:
            if not isinstance(s, dict):
                continue
            tid = s.get("template_id", "")
            if not isinstance(tid, str) or not tid:
                continue

            theme_id = s.get("theme_id", "")
            if not isinstance(theme_id, str):
                theme_id = ""

            template_counts[tid] += 1
            if theme_id:
                theme_counts[theme_id] += 1

            sat = s.get("satisfaction")
            if tid not in sat_by_template:
                sat_by_template[tid] = []
            if isinstance(sat, (int, float)):
                sat_by_template[tid].append(sat)

        avg_satisfaction = {}
        for tid, sats in sat_by_template.items():
            if sats:
                avg_satisfaction[tid] = round(sum(sats) / len(sats), 1)
            else:
                avg_satisfaction[tid] = 3.0

        return {
            "total_selections": sum(template_counts.values()),
            "by_template": dict(template_counts),
            "by_theme": dict(theme_counts),
            "avg_satisfaction": avg_satisfaction,
            "recent": [s for s in selections if isinstance(s, dict)][-5:],
        }
    except HTTPException:
        raise
    except (TypeError, ValueError, KeyError, AttributeError, OSError, RuntimeError) as e:
        logger.error(f"Failed to get template stats: {e}")
        _register_router_technical_debt(
            line_number=193,
            notes=f"Get template stats exception: {str(e)}",
            pattern="except (TypeError, ValueError, KeyError, AttributeError, OSError, RuntimeError) as e:",
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{theme_id}")
async def get_theme(theme_id: str):
    """テーマの詳細を取得"""
    if theme_id not in MOOD_THEMES:
        raise HTTPException(status_code=404, detail=f"Theme '{theme_id}' not found")

    return {"theme": MOOD_THEMES[theme_id]}


@router.post("/apply")
async def apply_template_and_theme(req: TemplateApplyRequest):
    """
    テンプレート × テーマ を一括適用

    ① template_config にテンプレートを設定（パイプライン接続: C-1修正）
    ② テーマのデザイントークンを適用
    ③ evolution_log に選択を記録（学習ループ: C-4修正）
    """
    # テンプレート検証
    if not isinstance(req.template_id, str) or req.template_id not in PRODUCTION_TEMPLATES:
        raise HTTPException(status_code=400, detail=f"Template '{req.template_id}' not found")

    # テーマ検証
    if not isinstance(req.theme_id, str) or req.theme_id not in MOOD_THEMES:
        raise HTTPException(status_code=400, detail=f"Theme '{req.theme_id}' not found")

    tmpl = PRODUCTION_TEMPLATES[req.template_id]
    theme = MOOD_THEMES[req.theme_id]

    if not isinstance(theme, dict) or "mood" not in theme or "design_tokens" not in theme:
        return {"error": "Invalid theme structure"}

    mood = theme["mood"]
    tokens = theme["design_tokens"]

    try:
        # ━━━ C-1修正: template_config にテンプレートを設定 ━━━
        # これにより品質ゲート・カラーグレーディング・2パスloudnormが有効化される
        try:
            from template_config import template_config
            if template_config is not None:
                template_config.set_active_template(
                    template_id=req.template_id,
                    template_data=tmpl,
                    theme_id=req.theme_id,
                )
                logger.info(
                    f"🔗 テンプレート→パイプライン接続: {req.template_id}"
                )
        except ImportError:
            logger.warning("template_config not available")
        except HTTPException:
            raise
        except (AttributeError, ValueError, TypeError, RuntimeError) as e:
            logger.error(f"Failed to set active template in template_config: {e}")

        # デザイントークンを適用
        try:
            from design_system.design_token_manager import design_token_manager
            result = design_token_manager.update_tokens(
                mood=mood,
                updates=tokens,
                source="template_theme_selector",
                reason=req.reason or f"テンプレート '{tmpl.get('label', '')}' + テーマ '{theme.get('label', '')}' を適用",
            )
        except ImportError:
            logger.error("design_token_manager not available")
            _register_router_technical_debt(
                line_number=268,
                notes="design_token_manager not available",
                pattern="except ImportError:",
            )
            raise HTTPException(status_code=500, detail="design_token_manager not available")

        # ━━━ C-4修正: evolution_log に選択を記録 ━━━
        try:
            _record_template_selection(req.template_id, req.theme_id)
        except HTTPException:
            raise
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as e:
            logger.error(f"Failed to record template selection: {e}")

        logger.info(
            f"✅ 適用完了: {tmpl.get('label', '')} × {theme.get('label', '')} (mood={mood})"
        )

        return {
            "status": "applied",
            "template": {
                "id": tmpl.get("id"),
                "label": tmpl.get("label"),
                "reference": tmpl.get("reference"),
            },
            "theme": {
                "id": theme.get("id"),
                "label": theme.get("label"),
                "mood": mood,
            },
            "quality_standards": {
                "subtitle_rules": tmpl.get("subtitle_rules"),
                "engagement_rules": tmpl.get("engagement_rules"),
                "quality_benchmarks": tmpl.get("quality_benchmarks"),
                "source": tmpl.get("reference"),
            },
            "pipeline_connected": True,
            "design_tokens_updated": list(tokens.keys()) if isinstance(tokens, dict) else [],
            "detail": result,
        }

    except HTTPException:
        raise
    except (TypeError, ValueError, KeyError, AttributeError, OSError, ImportError, RuntimeError) as e:
        logger.error(f"テンプレート×テーマ適用失敗: {e}")
        _register_router_technical_debt(
            line_number=313,
            notes=f"Apply template/theme exception: {str(e)}",
            pattern="except (TypeError, ValueError, KeyError, AttributeError, OSError, ImportError, RuntimeError) as e:",
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/current/active")
async def get_current_config():
    """現在適用中のテンプレート×テーマを取得"""
    try:
        try:
            from design_system.design_token_manager import design_token_manager
            history = design_token_manager.get_change_history(limit=1)
        except ImportError:
            logger.error("design_token_manager not available in current config")
            _register_router_technical_debt(
                line_number=330,
                notes="design_token_manager not available in current config",
                pattern="except ImportError:",
            )
            raise HTTPException(status_code=500, detail="design_token_manager not available")

        if history and isinstance(history, list) and isinstance(history[-1], dict):
            last = history[-1]
            reason = last.get("reason")
            if not isinstance(reason, str):
                reason = ""

            # テンプレート逆引き
            current_tmpl = None
            for tid, t in PRODUCTION_TEMPLATES.items():
                label = t.get("label", "")
                if label and label in reason:
                    current_tmpl = {"id": tid, "label": label}
                    break

            # テーマ逆引き
            current_theme = None
            last_mood = last.get("mood")
            for tid, t in MOOD_THEMES.items():
                if t.get("mood") == last_mood:
                    current_theme = {"id": tid, "label": t.get("label", tid)}
                    break

            return {
                "template": current_tmpl,
                "theme": current_theme,
                "applied_at": last.get("timestamp"),
            }

        return {"template": None, "theme": None, "label": "未設定"}

    except HTTPException:
        raise
    except (ImportError, AttributeError, TypeError, ValueError, KeyError, IndexError, RuntimeError) as e:
        logger.error(f"Failed to get current config: {e}")
        _register_router_technical_debt(
            line_number=370,
            notes=f"Get current config exception: {str(e)}",
            pattern="except (ImportError, AttributeError, TypeError, ValueError, KeyError, IndexError, RuntimeError) as e:",
        )
        raise HTTPException(status_code=500, detail=str(e))





# ============================================================
# C-3修正: テンプレート自動推奨エンドポイント
# ============================================================

class RecommendRequest(BaseModel):
    segments: List[Dict[str, Any]] = []
    total_duration_seconds: float = 0


@router.post("/recommend")
async def recommend_template(req: RecommendRequest):
    """
    素材分析に基づくテンプレート自動推奨（初心者「おまかせ」ボタン用）。

    憲法§15.1: 「AIが最適解を提示し、カスタマイズは任意」
    """
    # バリデーション (Pydanticによりsegmentsがlistであること、要素がdictであることは保証済み)
    for idx, seg in enumerate(req.segments):
        if "start" not in seg or "end" not in seg:
            raise HTTPException(status_code=400, detail=f"segment at index {idx} must contain 'start' and 'end' keys")
        if not isinstance(seg["start"], (int, float)) or not isinstance(seg["end"], (int, float)):
            raise HTTPException(status_code=400, detail=f"segment at index {idx} 'start' and 'end' must be numbers")
        if seg["start"] < 0 or seg["end"] < 0:
            raise HTTPException(status_code=400, detail=f"segment at index {idx} 'start' and 'end' must be non-negative")
        if seg["start"] > seg["end"]:
            raise HTTPException(status_code=400, detail=f"segment at index {idx} 'start' cannot be greater than 'end'")

    if req.total_duration_seconds < 0:
        raise HTTPException(status_code=400, detail="total_duration_seconds must be a non-negative number")

    try:
        try:
            from template_recommender import template_recommender
        except ImportError:
            logger.error("template_recommender not available")
            _register_router_technical_debt(
                line_number=416,
                notes="template_recommender not available",
                pattern="except ImportError:",
            )
            raise HTTPException(status_code=500, detail="template_recommender not available")

        rec_res = template_recommender.recommend(
            req.segments, req.total_duration_seconds
        )
        if not isinstance(rec_res, tuple) or len(rec_res) < 2:
            return {"error": "Invalid recommendation result"}

        best_id, detail = rec_res
        if not isinstance(detail, dict):
            detail = {}

        alternatives = template_recommender.recommend_with_alternatives(
            req.segments, req.total_duration_seconds
        )
        if not isinstance(alternatives, list):
            alternatives = []

        tmpl = PRODUCTION_TEMPLATES.get(best_id, {})
        return {
            "recommended": {
                "template_id": best_id,
                "label": tmpl.get("label", best_id),
                "score": detail.get("score", 0.0),
                "reasons": detail.get("reasons", []),
                "recommended_themes": RECOMMENDED_COMBOS.get(best_id, []),
            },
            "alternatives": alternatives,
            "profile": detail.get("profile", {}),
        }
    except HTTPException:
        raise
    except (ImportError, TypeError, ValueError, KeyError, AttributeError, RuntimeError) as e:
        logger.error(f"Error in recommend_template: {e}")
        _register_router_technical_debt(
            line_number=454,
            notes=f"Recommend template exception: {str(e)}",
            pattern="except (ImportError, TypeError, ValueError, KeyError, AttributeError, RuntimeError) as e:",
        )
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# M-2修正: テンプレートオーバーライドエンドポイント
# ============================================================

class OverrideRequest(BaseModel):
    overrides: Dict[str, Any] = {}


@router.post("/override")
async def apply_template_overrides(req: OverrideRequest):
    """
    テンプレート基準の個別オーバーライド（上級者カスタマイズ用）。

    例: {"subtitle_rules": {"font_size_min_px": 48}}
    """
    # Pydanticによりoverridesがdictであることは保証済み
    try:
        try:
            from template_config import template_config
        except ImportError:
            logger.error("template_config not available")
            _register_router_technical_debt(
                line_number=483,
                notes="template_config not available in overrides",
                pattern="except ImportError:",
            )
            raise HTTPException(status_code=500, detail="template_config not available")

        if not template_config.is_active:
            raise HTTPException(status_code=400, detail="テンプレートが未選択です。先に /themes/apply でテンプレートを適用してください。")

        try:
            template_config.set_overrides(req.overrides)
        except HTTPException:
            raise
        except (AttributeError, ValueError, TypeError) as e:
            logger.error(f"Failed to set overrides: {e}")
            _register_router_technical_debt(
                line_number=498,
                notes=f"Apply overrides exception: {str(e)}",
                pattern="except (AttributeError, ValueError, TypeError) as e:",
            )
            return {"error": f"Failed to apply overrides: {str(e)}"}

        return {
            "status": "overridden",
            "template_id": template_config.template_id,
            "overrides_applied": list(req.overrides.keys()),
        }
    except HTTPException:
        raise
    except (ImportError, AttributeError, ValueError, TypeError, KeyError, RuntimeError) as e:
        logger.error(f"Unexpected error in override endpoint: {e}")
        _register_router_technical_debt(
            line_number=514,
            notes=f"Unexpected override exception: {str(e)}",
            pattern="except (ImportError, AttributeError, ValueError, TypeError, KeyError, RuntimeError) as e:",
        )
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# H-1修正: テーマ名 → FFmpegカラーフィルタ名 マッピング
# ============================================================

# themes_router の MOOD_THEMES と video_processor._get_color_filter の名前統一
THEME_TO_FFmpeg_MOOD = {
    "warm": "warm",
    "cool": "cinematic",      # cool → cinematic（寒色系の映画的トーン）
    "energetic": "vibrant",   # energetic → vibrant（高彩度・高コントラスト）
    "calm": "cinematic",      # calm → cinematic（落ち着いたトーン）
}


# ============================================================
# C-4修正: evolution_log へのテンプレート選択記録
# ============================================================

def _record_template_selection(template_id: str, theme_id: str):
    """
    テンプレート選択を evolution_log.json に記録。
    テンプレート推奨エンジンの学習ループ用データソース。

    憲法§5.2「哲学の深化」+ §10「意思決定の記録と学習」
    """
    import json
    from datetime import datetime
    from pathlib import Path
    import tempfile
    import os

    try:
        log_path = _writable_path("backend/branding/evolution_log.json")

        log_path.parent.mkdir(parents=True, exist_ok=True)

        data = {}
        if log_path.exists():
            try:
                content = log_path.read_text(encoding="utf-8")
                if content.strip():
                    data = json.loads(content)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to read/parse evolution_log.json: {e}. Rewriting...")

        if not isinstance(data, dict):
            data = {}

        if "template_selections" not in data:
            data["template_selections"] = []

        if not isinstance(data["template_selections"], list):
            data["template_selections"] = []

        data["template_selections"].append({
            "template_id": template_id,
            "theme_id": theme_id,
            "timestamp": datetime.now().isoformat(),
            "satisfaction": 3,  # デフォルト中立。後から更新可能。
        })

        # 最新100件のみ保持
        data["template_selections"] = data["template_selections"][-100:]

        # アトミックな書き込み
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(log_path.parent), suffix=".tmp", prefix="evolution_"
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, str(log_path))
        except HTTPException:
            raise
        except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError):
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

        logger.info(f"📝 テンプレート選択記録: {template_id} × {theme_id}")
    except HTTPException:
        raise
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as e:
        logger.debug(f"Template selection recording skipped: {e}")



def _register_router_technical_debt(line_number: int, notes: str, pattern: str):
    """
    ルーター層の予期せぬ例外に対する技術負債を TDR (TechnicalDebtStore) に登録する。
    """
    try:
        try:
            from backend.agents.memory.technical_debt import TechnicalDebtStore
        except ImportError:
            from agents.memory.technical_debt import TechnicalDebtStore
        store = TechnicalDebtStore()
        store.register_debt(
            category="CRITICAL_ROUTER",
            file_path="backend/routers/themes_router.py",
            line_number=line_number,
            pattern=pattern,
            cause_pattern="DP-01",
            fix_pattern="HTTPExceptionへの適切な変換",
            registered_by="phase27_themes_router",
            notes=notes,
        )
    except HTTPException:
        raise
    except (ImportError, AttributeError, TypeError, ValueError, OSError, RuntimeError) as tdr_err:
        logger.error(f"Failed to register technical debt for line {line_number}: {tdr_err}")


# ============================================================
# テーマプレビューサムネイル生成エンドポイント
# ============================================================

from pydantic import BaseModel
from PIL import Image, ImageDraw
from pathlib import Path
import os

class ThemeThumbnailRequest(BaseModel):
    theme_id: str = "warm"
    text: str = "Theme Thumbnail"
    output_path: Optional[str] = None

@router.post("/thumbnail")
async def generate_theme_thumbnail(req: ThemeThumbnailRequest):
    """
    指定されたテーマのデザイントークン（配色など）を反映したサムネイル画像を生成し、品質検証を行う。
    """
    if req.theme_id not in MOOD_THEMES:
        raise HTTPException(status_code=400, detail=f"Theme '{req.theme_id}' not found")
    
    theme = MOOD_THEMES[req.theme_id]
    
    if not req.output_path:
        temp_dir = _writable_path("backend/temp_thumbnails")
        temp_dir.mkdir(parents=True, exist_ok=True)
        req.output_path = str(temp_dir / f"theme_{req.theme_id}_preview.png")
    
    output_path = Path(req.output_path)
    
    tokens = theme.get("design_tokens", {})
    palette = tokens.get("color_palette", {})
    bg_color = palette.get("background", "#ffffff")
    text_color = palette.get("text", "#333333")
    
    try:
        # Pillowによる 1280x720 (16:9) 画像の生成
        img = Image.new("RGB", (1280, 720), color=bg_color)
        draw = ImageDraw.Draw(img)
        
        # 簡易的なレイアウトと枠線の描画
        draw.rectangle([(20, 20), (1260, 700)], outline=text_color, width=5)
        draw.text((100, 300), req.text, fill=text_color)
        
        # アトミックな書き込みによるファイル破損防止
        tmp_path = str(output_path) + ".tmp"
        img.save(tmp_path, "PNG")
        if os.path.exists(output_path):
            os.remove(output_path)
        os.rename(tmp_path, output_path)
        
        # 品質検証の実行 (解像度 1280x720 以上、16:9、4MB未満)
        from combined_overlay import CombinedOverlay
        overlay = CombinedOverlay()
        result_info = overlay.validate_thumbnail(str(output_path))
        
        return {
            "status": "success",
            "theme_id": req.theme_id,
            "path": str(output_path),
            "validation": result_info
        }
        
    except HTTPException:
        raise
    except (ImportError, AttributeError, TypeError, ValueError, OSError, RuntimeError) as e:
        logger.error(f"Failed to generate theme thumbnail: {e}")
        _register_router_technical_debt(
            line_number=702,
            notes=f"Generate theme thumbnail exception: {str(e)}",
            pattern="except (ImportError, AttributeError, TypeError, ValueError, OSError, RuntimeError) as e:",
        )
        raise HTTPException(status_code=500, detail=str(e))
