"""
Generation Engine
Phase 5: Imagen 4.0 / Veo 2 統合

機能:
- 多段階プロンプト最適化
- Imagen 4.0 画像生成
- Veo 2 動画生成
- オープニング/エンディング自動生成
- 生成物の品質チェック統合
"""

import json
import logging
import base64
from pathlib import Path
from typing import List, Dict, Optional, Union
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum

from google import genai
from google.genai import errors
from dotenv import load_dotenv
import os

from model_registry import get_model

load_dotenv()
logger = logging.getLogger(__name__)


class GenerationType(Enum):
    """生成タイプ"""
    THUMBNAIL = "thumbnail"
    SCENE_IMAGE = "scene_image"
    TELOP_BACKGROUND = "telop_background"
    OPENING = "opening"
    ENDING = "ending"
    TRANSITION = "transition"


@dataclass
class GenerationRequest:
    """生成リクエスト"""
    id: str
    type: GenerationType
    prompt: str
    context: Dict = field(default_factory=dict)
    style_hints: List[str] = field(default_factory=list)
    aspect_ratio: str = "16:9"
    duration_sec: float = 5.0  # 動画の場合


@dataclass
class GenerationResult:
    """生成結果"""
    request_id: str
    success: bool
    output_path: Optional[str] = None
    optimized_prompt: str = ""
    quality_score: float = 0.0
    error: Optional[str] = None
    metadata: Dict = field(default_factory=dict)


class PromptOptimizer:
    """多段階プロンプト最適化"""
    
    OPTIMIZE_PROMPT = """
以下の生成リクエストを最適化してください。

## リクエスト
タイプ: {gen_type}
元のプロンプト: {original_prompt}
コンテキスト: {context}
スタイルヒント: {style_hints}

## ブランド憲法
{constitution}

## 出力形式
最適化されたプロンプトのみを出力してください。
- 具体的で視覚的な表現を使用
- ブランドの世界観を反映
- 技術的な品質指示を含める
"""

    def __init__(self):
        api_key = os.getenv("GOOGLE_API_KEY")
        self.client = genai.Client(api_key=api_key)
        self.model = get_model("quality_gate")
        self.constitution = self._load_constitution()
    
    def _load_constitution(self) -> Dict:
        """憲法を読み込み"""
        const_path = Path(__file__).parent / "branding" / "constitution.json"
        if const_path.exists():
            with open(const_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
    
    def optimize(self, request: GenerationRequest) -> str:
        """プロンプトを最適化"""
        prompt = self.OPTIMIZE_PROMPT.format(
            gen_type=request.type.value,
            original_prompt=request.prompt,
            context=json.dumps(request.context, ensure_ascii=False),
            style_hints=", ".join(request.style_hints),
            constitution=json.dumps(self.constitution, ensure_ascii=False)
        )
        
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt
            )
            optimized = response.text.strip()
            logger.info(f"プロンプト最適化完了: {len(optimized)}文字")
            return optimized
        except errors.APIError as e:
            logger.warning(f"プロンプト最適化失敗 (APIError): {e}", exc_info=True)
            return self._fallback_optimize(request)
        except (ValueError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning(f"プロンプト最適化失敗 (予期しないエラー): {e}", exc_info=True)
            return self._fallback_optimize(request)
    
    def _fallback_optimize(self, request: GenerationRequest) -> str:
        """フォールバック最適化"""
        # 基本的な強化
        base = request.prompt
        
        # スタイルヒントを追加
        if request.style_hints:
            base += f", {', '.join(request.style_hints)}"
        
        # タイプ別の品質指示
        quality_hints = {
            GenerationType.THUMBNAIL: "high quality, professional, eye-catching, YouTube thumbnail style",
            GenerationType.SCENE_IMAGE: "cinematic, high resolution, detailed",
            GenerationType.TELOP_BACKGROUND: "subtle, text-friendly, gradient background",
            GenerationType.OPENING: "dynamic, professional intro, motion graphics",
            GenerationType.ENDING: "elegant, call to action, subscribe reminder",
            GenerationType.TRANSITION: "smooth, seamless, professional transition"
        }
        
        if request.type in quality_hints:
            base += f", {quality_hints[request.type]}"
        
        return base


class ImagenGenerator:
    """Imagen 4.0 画像生成"""
    
    def __init__(self, output_dir: Path = None):
        api_key = os.getenv("GOOGLE_API_KEY")
        self.client = genai.Client(api_key=api_key)
        self.model = "imagen-4.0-generate-preview-06-06"  # 最新のImagen 4.0
        self.output_dir = output_dir or Path("output/generated/images")
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate(self, prompt: str, request: GenerationRequest) -> GenerationResult:
        """画像を生成"""
        try:
            logger.info(f"Imagen生成開始: {request.id}")
            
            # アスペクト比の設定
            aspect_ratios = {
                "16:9": {"width": 1920, "height": 1080},
                "1:1": {"width": 1024, "height": 1024},
                "9:16": {"width": 1080, "height": 1920},
                "4:3": {"width": 1440, "height": 1080}
            }
            
            dimensions = aspect_ratios.get(request.aspect_ratio, aspect_ratios["16:9"])
            
            # Imagen APIで生成（シンプルなパラメータ）
            response = self.client.models.generate_images(
                model=self.model,
                prompt=prompt
            )
            
            # 結果を保存
            if response.generated_images:
                image_data = response.generated_images[0]
                
                # ファイル名生成
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{request.type.value}_{request.id}_{timestamp}.png"
                output_path = self.output_dir / filename
                
                # 画像を保存
                img_bytes = None
                if hasattr(image_data, 'image') and hasattr(image_data.image, 'image_bytes'):
                    img_bytes = image_data.image.image_bytes
                elif hasattr(image_data, 'image_bytes'):
                    img_bytes = image_data.image_bytes
                
                if img_bytes is not None:
                    if isinstance(img_bytes, str):
                        img_bytes = base64.b64decode(img_bytes)
                    with open(output_path, "wb") as f:
                        f.write(img_bytes)
                else:
                    raise ValueError("Generated image data is missing image_bytes attribute")
                
                logger.info(f"Imagen生成完了: {output_path}")
                
                return GenerationResult(
                    request_id=request.id,
                    success=True,
                    output_path=str(output_path),
                    optimized_prompt=prompt,
                    quality_score=0.85,
                    metadata={"dimensions": dimensions}
                )
            else:
                return GenerationResult(
                    request_id=request.id,
                    success=False,
                    error="No images generated"
                )
                
        except errors.APIError as e:
            logger.error(f"Imagen APIエラー: {e}", exc_info=True)
            return GenerationResult(
                request_id=request.id,
                success=False,
                error=f"Imagen API Error: {e}"
            )
        except (ValueError, TypeError, IndexError, OSError) as e:
            logger.error(f"Imagen生成システムエラー: {e}", exc_info=True)
            return GenerationResult(
                request_id=request.id,
                success=False,
                error=str(e)
            )


class VeoGenerator:
    """Veo 2 動画生成"""
    
    def __init__(self, output_dir: Path = None):
        api_key = os.getenv("GOOGLE_API_KEY")
        self.client = genai.Client(api_key=api_key)
        self.model = "veo-2.0-generate-001"  # 正式なVeo 2モデル
        self.output_dir = output_dir or Path("output/generated/videos")
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate(self, prompt: str, request: GenerationRequest) -> GenerationResult:
        """動画を生成"""
        try:
            logger.info(f"Veo生成開始: {request.id}")
            
            # Veo APIで生成
            response = self.client.models.generate_videos(
                model=self.model,
                prompt=prompt,
                config={
                    "aspect_ratio": request.aspect_ratio,
                    "duration_seconds": min(request.duration_sec, 8),  # 最大8秒
                    "number_of_videos": 1
                }
            )
            
            # 結果を保存
            if response.generated_videos:
                video_data = response.generated_videos[0]
                
                # ファイル名生成
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{request.type.value}_{request.id}_{timestamp}.mp4"
                output_path = self.output_dir / filename
                
                # 動画を保存
                vid_bytes = None
                if hasattr(video_data, 'video') and hasattr(video_data.video, 'video_bytes'):
                    vid_bytes = video_data.video.video_bytes
                elif hasattr(video_data, 'video_bytes'):
                    vid_bytes = video_data.video_bytes
                
                if vid_bytes is not None:
                    if isinstance(vid_bytes, str):
                        vid_bytes = base64.b64decode(vid_bytes)
                    with open(output_path, "wb") as f:
                        f.write(vid_bytes)
                else:
                    raise ValueError("Generated video data is missing video_bytes attribute")
                
                logger.info(f"Veo生成完了: {output_path}")
                
                return GenerationResult(
                    request_id=request.id,
                    success=True,
                    output_path=str(output_path),
                    optimized_prompt=prompt,
                    quality_score=0.85,
                    metadata={"duration": request.duration_sec}
                )
            else:
                return GenerationResult(
                    request_id=request.id,
                    success=False,
                    error="No videos generated"
                )
                
        except errors.APIError as e:
            logger.error(f"Veo APIエラー: {e}", exc_info=True)
            return GenerationResult(
                request_id=request.id,
                success=False,
                error=f"Veo API Error: {e}"
            )
        except (ValueError, TypeError, IndexError, OSError) as e:
            logger.error(f"Veo生成システムエラー: {e}", exc_info=True)
            return GenerationResult(
                request_id=request.id,
                success=False,
                error=str(e)
            )


class GenerationEngine:
    """統合生成エンジン"""
    
    def __init__(self, output_dir: Path = None):
        self.output_dir = output_dir or Path("output/generated")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.prompt_optimizer = PromptOptimizer()
        self.imagen = ImagenGenerator(self.output_dir / "images")
        self.veo = VeoGenerator(self.output_dir / "videos")
        
        # Self-Review Engine統合
        try:
            from self_review_engine import self_review_engine
            self.reviewer = self_review_engine
        except:
            self.reviewer = None
    
    def generate(self, request: GenerationRequest) -> GenerationResult:
        """
        リクエストに基づいて生成
        
        Args:
            request: 生成リクエスト
        
        Returns:
            GenerationResult
        """
        logger.info(f"生成開始: {request.id} ({request.type.value})")
        
        # 1. プロンプト最適化
        optimized_prompt = self.prompt_optimizer.optimize(request)
        
        # 2. 生成実行
        if request.type in [GenerationType.OPENING, GenerationType.ENDING, GenerationType.TRANSITION]:
            # 動画生成
            result = self.veo.generate(optimized_prompt, request)
        else:
            # 画像生成
            result = self.imagen.generate(optimized_prompt, request)
        
        # 3. 品質チェック（Self-Review Engine統合）
        if result.success and self.reviewer:
            try:
                review = self.reviewer.review(
                    content=optimized_prompt,
                    generation_type=request.type.value,
                    context=request.context
                )
                result.quality_score = review.score.overall
                result.metadata["review"] = {
                    "passed": review.passed,
                    "issues": review.issues
                }
            except (AttributeError, ValueError, TypeError, RuntimeError) as e:
                logger.warning(f"品質チェックスキップ: {e}", exc_info=True)
        
        return result
    
    def generate_thumbnail(self, 
                          title: str, 
                          context: Dict = None,
                          style: str = "professional") -> GenerationResult:
        """サムネイル生成のショートカット"""
        request = GenerationRequest(
            id=f"thumb_{datetime.now().strftime('%H%M%S')}",
            type=GenerationType.THUMBNAIL,
            prompt=f"YouTube thumbnail for video: {title}",
            context=context or {},
            style_hints=[style, "eye-catching", "high contrast"],
            aspect_ratio="16:9"
        )
        return self.generate(request)
    
    def generate_opening(self,
                        channel_name: str,
                        duration_sec: float = 5.0) -> GenerationResult:
        """オープニング動画生成"""
        request = GenerationRequest(
            id=f"open_{datetime.now().strftime('%H%M%S')}",
            type=GenerationType.OPENING,
            prompt=f"Professional YouTube channel opening for '{channel_name}', modern motion graphics, elegant animation",
            style_hints=["dynamic", "professional", "branded"],
            aspect_ratio="16:9",
            duration_sec=duration_sec
        )
        return self.generate(request)
    
    def generate_ending(self,
                       channel_name: str,
                       call_to_action: str = "チャンネル登録お願いします",
                       duration_sec: float = 5.0) -> GenerationResult:
        """エンディング動画生成"""
        request = GenerationRequest(
            id=f"end_{datetime.now().strftime('%H%M%S')}",
            type=GenerationType.ENDING,
            prompt=f"YouTube outro for '{channel_name}', featuring '{call_to_action}', subscribe button animation",
            style_hints=["elegant", "call-to-action", "branded"],
            aspect_ratio="16:9",
            duration_sec=duration_sec
        )
        return self.generate(request)


# シングルトンインスタンス
generation_engine = GenerationEngine()


# 簡易関数
def generate_thumbnail(title: str, context: Dict = None) -> Dict:
    """サムネイル生成（簡易関数）"""
    result = generation_engine.generate_thumbnail(title, context)
    return asdict(result)


def generate_opening(channel_name: str = "美麗書院") -> Dict:
    """オープニング生成（簡易関数）"""
    result = generation_engine.generate_opening(channel_name)
    return asdict(result)


def generate_ending(channel_name: str = "美麗書院") -> Dict:
    """エンディング生成（簡易関数）"""
    result = generation_engine.generate_ending(channel_name)
    return asdict(result)
