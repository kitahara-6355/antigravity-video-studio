try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

import asyncio
import json
import logging
import re
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, ValidationError
from model_registry import get_model
from gemini_client_factory import get_gemini_client
from google.api_core.exceptions import GoogleAPIError

logger = logging.getLogger(__name__)

class SoulFeedbackParams(BaseModel):
    """
    演出哲学パラメータのPydanticモデル (入力ガードレール)
    """
    tempo_multiplier: float = Field(
        default=1.0, 
        ge=0.5, 
        le=2.0, 
        description="動画のテンポ倍率 (0.5〜2.0)"
    )
    telop_color: str = Field(
        default="#FFFFFF", 
        description="テロップ色 (RGB 16進数表記, 例: #FF0000)"
    )
    subtitle_font_size: int = Field(
        default=24, 
        ge=10, 
        le=100, 
        description="字幕フォントサイズ (10〜100)"
    )
    volume_multiplier: float = Field(
        default=1.0, 
        ge=0.0, 
        le=2.0, 
        description="音量倍率 (0.0〜2.0)"
    )

    @field_validator("telop_color")
    @classmethod
    def validate_color(cls, v: str) -> str:
        if not re.match(r"^#[0-9A-Fa-f]{6}$", v):
            raise ValueError("Invalid hex color format. Must be #RRGGBB")
        return v.upper()

class SoulFeedbackProcessor:
    """
    SoulFeedback (演出哲学還流) プロセッサ
    
    定性指示テキストから定量パラメータへの LLM 変換、
    異常値自動修正、および入力ガードレールを管理。
    """
    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or get_model("philosophy")
        
    async def parse_qualitative_feedback(self, text: str) -> SoulFeedbackParams:
        """
        定性演出指示テキストを解析し、Pydanticパラメータモデルへ変換する。
        
        LLMエラーや異常値の検出時は安全なデフォルト値へフォールバックする。
        """
        prompt = self._build_prompt(text)
        
        try:
            async with asyncio.timeout(30):
                content = await self._call_llm(prompt)
                
            if not content:
                logger.warning("[SoulFeedback] Empty response from LLM. Fallback to default.")
                return SoulFeedbackParams()
                
            json_str = self._extract_json(content)
            data = json.loads(json_str)
            if not isinstance(data, dict):
                logger.warning(f"[SoulFeedback] LLM response is not a JSON object: {data}. Fallback to default.")
                return SoulFeedbackParams()
            
            return self.apply_guardrails(data)
            
        except (TimeoutError, asyncio.TimeoutError):
            logger.warning("[SoulFeedback] LLM timeout (30s). Fallback to default.")
            return SoulFeedbackParams()
        except json.JSONDecodeError as e:
            logger.error(f"[SoulFeedback] Parsing failed due to JSONDecodeError: {e}. Fallback to default.")
            return SoulFeedbackParams()
        except (TypeError, ValueError, AttributeError, KeyError, RuntimeError, GoogleAPIError) as e:
            logger.error(f"[SoulFeedback] Unexpected error: {e}. Fallback to default.", exc_info=True)
            return SoulFeedbackParams()
            
    def apply_guardrails(self, params: Dict[str, Any]) -> SoulFeedbackParams:
        """
        定量パラメータの異常値（範囲外など）を検出し、安全な範囲内にクリップする。
        型が間違っている、あるいはパースできない項目はデフォルト値にフォールバック。
        """
        safe_params = {}
        
        try:
            val = float(params.get("tempo_multiplier", 1.0))
            safe_params["tempo_multiplier"] = max(0.5, min(2.0, val))
        except (ValueError, TypeError):
            safe_params["tempo_multiplier"] = 1.0
            
        color = str(params.get("telop_color", "#FFFFFF"))
        if not re.match(r"^#[0-9A-Fa-f]{6}$", color):
            logger.warning(f"[SoulFeedback] Invalid color: {color}. Fallback to #FFFFFF.")
            safe_params["telop_color"] = "#FFFFFF"
        else:
            safe_params["telop_color"] = color.upper()
            
        try:
            val = int(params.get("subtitle_font_size", 24))
            safe_params["subtitle_font_size"] = max(10, min(100, val))
        except (ValueError, TypeError):
            safe_params["subtitle_font_size"] = 24
            
        try:
            val = float(params.get("volume_multiplier", 1.0))
            safe_params["volume_multiplier"] = max(0.0, min(2.0, val))
        except (ValueError, TypeError):
            safe_params["volume_multiplier"] = 1.0
            
        try:
            return SoulFeedbackParams(**safe_params)
        except ValidationError as e:
            logger.error(f"[SoulFeedback] Unexpected ValidationError: {e}. Fallback to default.", exc_info=True)
            return SoulFeedbackParams()
            
    def _build_prompt(self, text: str) -> str:
        return f"""定性的な演出指示テキストを解析し、以下のパラメータを抽出してJSON形式で返してください。

演出指示: "{text}"

出力するJSONキー:
- tempo_multiplier (数値: 0.5 〜 2.0 の範囲。指示がない場合は 1.0)
- telop_color (文字列: #RRGGBB 形式。指示がない場合は #FFFFFF)
- subtitle_font_size (数値: 10 〜 100 の範囲。指示がない場合は 24)
- volume_multiplier (数値: 0.0 〜 2.0 の範囲。指示がない場合は 1.0)

※ JSON以外の説明文やマークダウンブロックは出力せず、純粋なJSON文字列のみを返却してください。
"""

    async def _call_llm(self, prompt: str) -> Optional[str]:
        client = get_gemini_client()
        if not client:
            logger.warning("[SoulFeedback] Gemini client is not configured.")
            return None
            
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=self.model_name,
            contents=prompt,
        )
        
        try:
            return response.text.strip()
        except (AttributeError, TypeError):
            logger.warning("[SoulFeedback] Failed to parse LLM response.")
            return None
            
    def _extract_json(self, text: str) -> str:
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            return match.group(1)
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        if match:
            return match.group(1)
        return text


# --- サムネイル画像処理・品質検証・StageBoundAgent連携ロジック ---
import uuid
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

try:
    from usage_tracker.alert_system import emit_warning, emit_critical
except ImportError:
    def emit_warning(domain, message):
        logger.warning(f"[{domain}] {message}")
    def emit_critical(domain, message):
        logger.error(f"[{domain}] CRITICAL: {message}")


def create_subtitle_sample(output_path=None):
    """字幕サンプル画像を生成 (アトミック書き込みで最適化)"""
    if output_path is None:
        output_path = Path(__file__).parent.parent / "subtitle_sample.png"
    else:
        output_path = Path(output_path)
    
    # 親ディレクトリが存在しない場合は作成
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    
    try:
        # 1920x1080の画像を作成
        img = Image.new('RGB', (1920, 1080), (40, 40, 40))
        draw = ImageDraw.Draw(img)
        
        try:
            font_title = ImageFont.truetype("C:/Windows/Fonts/Yu Gothic UI.ttf", 32)
            font_subtitle = ImageFont.truetype("C:/Windows/Fonts/Yu Gothic UI.ttf", 18)
        except (OSError, IOError, ValueError):
            font_title = ImageFont.load_default()
            font_subtitle = ImageFont.load_default()
        
        content_text = "[ 動画コンテンツエリア ]"
        bbox = draw.textbbox((0, 0), content_text, font=font_title)
        text_width = bbox[2] - bbox[0]
        x = (1920 - text_width) // 2
        draw.text((x, 500), content_text, fill=(150, 150, 150), font=font_title)
        
        subtitle_y = 1080 - 120
        subtitle_line1 = "先生がこれから今からやってみたいとか、"
        subtitle_line2 = "というようなことは何かあるんでしょうか?"
        
        def draw_text_outline(text, x, y):
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx != 0 or dy != 0:
                        draw.text((x+dx, y+dy), text, fill=(0, 0, 0), font=font_subtitle)
            draw.text((x, y), text, fill=(255, 255, 255), font=font_subtitle)
        
        bbox1 = draw.textbbox((0, 0), subtitle_line1, font=font_subtitle)
        width1 = bbox1[2] - bbox1[0]
        x1 = (1920 - width1) // 2
        draw_text_outline(subtitle_line1, x1, subtitle_y)
        
        bbox2 = draw.textbbox((0, 0), subtitle_line2, font=font_subtitle)
        width2 = bbox2[2] - bbox2[0]
        x2 = (1920 - width2) // 2
        draw_text_outline(subtitle_line2, x2, subtitle_y + 30)
        
        # 保存 (アトミック)
        img.save(temp_path, "PNG")
        if output_path.exists():
            output_path.unlink()
        temp_path.rename(output_path)
        logger.info(f"✅ Subtitle sample: {output_path}")
    except (OSError, IOError, ValueError, RuntimeError) as e:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except (OSError, IOError):
                pass
        raise e
        
    return str(output_path)


def create_integrated_sample(output_path=None):
    """B案ロゴ+テロップ+字幕の統合サンプル画像 (アトミック書き込みで最適化)"""
    if output_path is None:
        output_path = Path(__file__).parent.parent / "B_plan_with_subtitle.png"
    else:
        output_path = Path(output_path)
        
    # 親ディレクトリが存在しない場合は作成
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    
    try:
        img = Image.new('RGB', (1920, 1080), (40, 40, 40))
        draw = ImageDraw.Draw(img)
        
        try:
            font_content = ImageFont.truetype("C:/Windows/Fonts/Yu Gothic UI.ttf", 32)
            font_telop = ImageFont.truetype("C:/Windows/Fonts/Yu Gothic UI.ttf", 16)
            font_subtitle = ImageFont.truetype("C:/Windows/Fonts/Yu Gothic UI.ttf", 18)
        except (OSError, IOError, ValueError):
            font_content = font_telop = font_subtitle = ImageFont.load_default()
        
        logo_area = "[ ロゴ 45px ]"
        draw.text((10, 10), logo_area, fill=(200, 200, 200), font=font_telop)
        
        telop_bg = Image.new('RGBA', (200, 28), (0, 0, 0, 51))
        telop_draw = ImageDraw.Draw(telop_bg)
        telop_draw.text((8, 8), "筆の話", fill=(255, 255, 255, 217), font=font_telop)
        
        img_rgba = img.convert('RGBA')
        img_rgba.paste(telop_bg, (150, 15), telop_bg)
        img = img_rgba.convert('RGB')
        draw = ImageDraw.Draw(img)
        
        content_text = "[ 動画コンテンツエリア ]"
        bbox = draw.textbbox((0, 0), content_text, font=font_content)
        text_width = bbox[2] - bbox[0]
        x = (1920 - text_width) // 2
        draw.text((x, 500), content_text, fill=(150, 150, 150), font=font_content)
        
        subtitle_y = 1080 - 120
        
        def draw_text_outline(text, x, y):
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx != 0 or dy != 0:
                        draw.text((x+dx, y+dy), text, fill=(0, 0, 0), font=font_subtitle)
            draw.text((x, y), text, fill=(255, 255, 255), font=font_subtitle)
        
        subtitle_line1 = "先生がこれから今からやってみたいとか、"
        subtitle_line2 = "というようなことは何かあるんでしょうか?"
        
        bbox1 = draw.textbbox((0, 0), subtitle_line1, font=font_subtitle)
        width1 = bbox1[2] - bbox1[0]
        x1 = (1920 - width1) // 2
        draw_text_outline(subtitle_line1, x1, subtitle_y)
        
        bbox2 = draw.textbbox((0, 0), subtitle_line2, font=font_subtitle)
        width2 = bbox2[2] - bbox2[0]
        x2 = (1920 - width2) // 2
        draw_text_outline(subtitle_line2, x2, subtitle_y + 30)
        
        # 保存 (アトミック)
        img.save(temp_path, "PNG")
        if output_path.exists():
            output_path.unlink()
        temp_path.rename(output_path)
        logger.info(f"✅ Integrated sample: {output_path}")
    except (OSError, IOError, ValueError, RuntimeError) as e:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except (OSError, IOError):
                pass
        raise e
        
    return str(output_path)


class SubtitleThumbnailVerifier:
    @staticmethod
    def validate(file_path) -> dict:
        """字幕サンプル画像の品質基準を検証する"""
        path = Path(file_path)
        if not path.exists():
            msg = f"Subtitle sample file not found: {path}"
            emit_warning("thumbnail", msg)
            raise FileNotFoundError(msg)

        size_bytes = path.stat().st_size
        if size_bytes >= 4 * 1024 * 1024:
            msg = f"File size exceeds 4MB limit: {size_bytes} bytes"
            emit_warning("thumbnail", msg)
            raise ValueError(msg)

        # 簡易検証 (verify)
        try:
            with Image.open(path) as img:
                img.verify()
        except (OSError, IOError, ValueError) as e:
            msg = f"Image verify failed: {e}"
            emit_warning("thumbnail", msg)
            raise ValueError(msg)

        # ピクセルデータロードによる完全な破損チェックとサイズ取得
        try:
            with Image.open(path) as img:
                img.load()
                width, height = img.size
        except (OSError, IOError, ValueError) as e:
            msg = f"Image load failed (corrupted): {e}"
            emit_warning("thumbnail", msg)
            raise ValueError(msg)

        # 解像度 1280x720 以上
        if width < 1280 or height < 720:
            msg = f"Resolution must be at least 1280x720. Got {width}x{height}"
            emit_warning("thumbnail", msg)
            raise ValueError(msg)

        # アスペクト比 16:9 (許容誤差 0.01)
        aspect_ratio = width / height
        target_ratio = 16.0 / 9.0
        if abs(aspect_ratio - target_ratio) > 0.01:
            msg = f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}"
            emit_warning("thumbnail", msg)
            raise ValueError(msg)

        return {
            "path": str(path),
            "width": width,
            "height": height,
            "size_bytes": size_bytes
        }


async def resolve_subtitle_thumbnail_task(agent, task_id: str) -> str:
    """StageBoundAgent の process_func として動作する非同期タスク処理"""
    try:
        output_dir = Path(getattr(agent, "output_dir", None) or _writable_path("backend/temp_thumbnails"))
        output_path = output_dir / f"{task_id}.png"
        
        # 画像生成
        create_subtitle_sample(output_path)
        
        # 品質検証
        result_info = SubtitleThumbnailVerifier.validate(output_path)
        return json.dumps(result_info)
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, AttributeError) as e:
        emit_critical("thumbnail", f"Subtitle thumbnail task failed for task {task_id}: {e}")
        logger.error(f"[SoulFeedback] Subtitle thumbnail task failed for task {task_id}: {e}", exc_info=True)
        raise

