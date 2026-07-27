"""
Thumbnail Plugin - サムネイル生成プラグイン（統合版）

PROJECT_CONSTITUTION §16 準拠:
- 共通Pluginインターフェース
- YouTubeOptimizerPluginへの委譲（重複解消）

NOTE: このプラグインはyoutube_optimizer_pluginへのラッパーです。
      サムネイル生成の実装はyoutube_optimizer_plugin.pyに統合されています。
"""
from core import Plugin, PluginPhase, ProductionContext
from typing import Dict, Any, Optional, List
import logging
import uuid
import json
import sqlite3
import asyncio
import time
from pathlib import Path

# Model Registry (SSoT: model_config.json)
try:
    from model_registry import get_model
except ImportError:
    def get_model(task): return "gemini-2.5-flash"

logger = logging.getLogger(__name__)


class ThumbnailPluginError(Exception):
    """サムネイルプラグインで発生したエラー"""
    pass


def validate_and_correct_thumbnail(file_path: str) -> str:
    """
    サムネイル画像の品質要件を検証し、満たさない場合は自動補正（リサイズ・トリミング・再圧縮）を行う。
    品質向上として、彩度、シャープネス、コントラスト、明るさの微調整を行う。
    それでも満たさない場合は ValueError を発生させる。
    """
    from PIL import Image, ImageEnhance, UnidentifiedImageError
    import os
    
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Thumbnail file not found: {file_path}")
        
    # 正常に Pillow でロード可能かチェック
    try:
        with Image.open(file_path) as img:
            img.verify()
    except UnidentifiedImageError as e:
        raise ValueError(f"Image file is not a recognized image format: {e}")
    except (OSError, ValueError, TypeError, SyntaxError) as e:
        raise ValueError(f"Image is corrupted or invalid format: {e}")
        
    try:
        with Image.open(file_path) as img:
            img.load()
            width, height = img.size
            
            # 1. アスペクト比の検証と補正 (16:9)
            aspect_ratio = width / height
            target_ratio = 16.0 / 9.0
            ratio_diff = abs(aspect_ratio - target_ratio)
            
            needs_save = False
            
            if ratio_diff > 0.01:
                # 16:9 にトリミングする
                if aspect_ratio > target_ratio:
                    new_width = int(height * target_ratio)
                    left = (width - new_width) // 2
                    img = img.crop((left, 0, left + new_width, height))
                else:
                    new_height = int(width / target_ratio)
                    top = (height - new_height) // 2
                    img = img.crop((0, top, width, top + new_height))
                
                # クロップ後のサイズをアスペクト比 16:9 に微調整
                w_crop, h_crop = img.size
                if abs((w_crop / h_crop) - target_ratio) > 0.001:
                    exact_width = int(h_crop * target_ratio)
                    if exact_width != w_crop:
                        img = img.crop((0, 0, exact_width, h_crop))
                        
                width, height = img.size
                needs_save = True
                
            # 2. 解像度の検証と補正 (1280x720以上)
            if width < 1280 or height < 720:
                img = img.resize((1280, 720), Image.Resampling.LANCZOS)
                width, height = img.size
                needs_save = True

            # 3. 品質向上処理 (シャープネス10%向上、彩度3%向上、コントラスト5%向上、明るさ2%向上)
            try:
                enhancer_sharp = ImageEnhance.Sharpness(img)
                img = enhancer_sharp.enhance(1.1)
                enhancer_color = ImageEnhance.Color(img)
                img = enhancer_color.enhance(1.03)
                enhancer_contrast = ImageEnhance.Contrast(img)
                img = enhancer_contrast.enhance(1.05)
                enhancer_brightness = ImageEnhance.Brightness(img)
                img = enhancer_brightness.enhance(1.02)
                needs_save = True
            except (ValueError, TypeError, OSError) as enh_e:
                logger.warning(f"Failed to enhance image quality: {enh_e}")
                
            # 4. 変更があった場合は上書き保存
            if needs_save:
                fmt = img.format or "PNG"
                img.save(file_path, format=fmt)
                
    except (OSError, ValueError, TypeError, AttributeError, RuntimeError) as e:
        raise ValueError(f"Failed to process and correct image metadata: {e}")
        
    # 5. ファイルサイズの検証と補正 (4MB 未満)
    size_bytes = file_path.stat().st_size
    if size_bytes >= 4 * 1024 * 1024:
        temp_files_to_clean = []
        try:
            with Image.open(file_path) as img:
                fmt = img.format or "PNG"
                success = False
                
                # PNG形式なら、まずは画質が劣化しない可逆圧縮の最適化を試す
                if fmt == "PNG":
                    temp_png = file_path.with_suffix(".opt.png")
                    temp_files_to_clean.append(temp_png)
                    img.save(temp_png, "PNG", optimize=True, compress_level=9)
                    if temp_png.stat().st_size < 4 * 1024 * 1024:
                        if file_path.exists():
                            file_path.unlink()
                        temp_png.rename(file_path)
                        temp_files_to_clean.remove(temp_png)
                        success = True
                
                if not success:
                    temp_jpg = file_path.with_suffix(".jpg")
                    temp_files_to_clean.append(temp_jpg)
                    
                    # 透過背景の合成処理
                    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                        background = Image.new("RGB", img.size, (255, 255, 255))
                        alpha = img.convert("RGBA").split()[3]
                        background.paste(img, mask=alpha)
                        img_rgb = background
                    else:
                        img_rgb = img.convert("RGB")
                        
                    img_rgb.save(temp_jpg, "JPEG", quality=85)
                    
                    if temp_jpg.stat().st_size < 4 * 1024 * 1024:
                        if file_path.exists():
                            file_path.unlink()
                        temp_jpg.rename(file_path)
                        temp_files_to_clean.remove(temp_jpg)
                        success = True
                    else:
                        img_rgb.save(temp_jpg, "JPEG", quality=60)
                        if temp_jpg.stat().st_size < 4 * 1024 * 1024:
                            if file_path.exists():
                                file_path.unlink()
                            temp_jpg.rename(file_path)
                            temp_files_to_clean.remove(temp_jpg)
                            success = True
                        else:
                            # 最後の手段: 1280x720にダウンスケールして quality=60 で圧縮
                            if img_rgb.width > 1280 or img_rgb.height > 720:
                                temp_opt_jpg = file_path.with_suffix(".opt.jpg")
                                temp_files_to_clean.append(temp_opt_jpg)
                                try:
                                    img_resized = img_rgb.resize((1280, 720), Image.Resampling.LANCZOS)
                                    img_resized.save(temp_opt_jpg, "JPEG", quality=60)
                                    if temp_opt_jpg.stat().st_size < 4 * 1024 * 1024:
                                        if file_path.exists():
                                            file_path.unlink()
                                        temp_opt_jpg.rename(file_path)
                                        temp_files_to_clean.remove(temp_opt_jpg)
                                        success = True
                                except (OSError, ValueError, TypeError) as e_resize:
                                    logger.warning(f"Failed to downscale image during size correction: {e_resize}")
                                
                if not success:
                    raise ValueError(f"File size exceeds 4MB limit and compression failed: {size_bytes} bytes")
        except (OSError, ValueError, TypeError, AttributeError, RuntimeError) as e:
            raise ValueError(f"Failed to compress large thumbnail: {e}")
        finally:
            for temp_f in temp_files_to_clean:
                if temp_f.exists():
                    try:
                        temp_f.unlink()
                    except OSError as ce:
                        logger.warning(f"Failed to delete temp file during cleanup: {ce}")
            
    return str(file_path)


class ThumbnailPlugin(Plugin):
    """
    サムネイル生成プラグイン（統合版）
    
    Imagen 4を使用して複数のサムネイル候補を生成する。
    実装はYouTubeOptimizerPluginに委譲し、重複を解消。
    """
    
    name = "thumbnail"
    phase = PluginPhase.GENERATION
    priority = 10
    
    # モデル要件（PROJECT_CONSTITUTION §16.3）
    model_requirements = {
        "task": "thumbnail",
        "model": get_model("thumbnail"),
        "fallback": get_model("thumbnail_preview"),
        "api_type": "imagen"
    }
    
    def __init__(self, num_candidates: int = 3):
        # 堅牢化: num_candidates の型検証とクランプ
        try:
            val = int(num_candidates)
        except (ValueError, TypeError):
            val = 3
        
        if val <= 0:
            val = 1
        elif val > 10:
            val = 10
        self.num_candidates = val
    
    def execute(self, context: ProductionContext) -> ProductionContext:
        """
        サムネイル候補を生成し、StageBoundAgent連携による品質検証とリトライを行う。
        """
        if context is None:
            return context

        self.log(f"Generating {self.num_candidates} thumbnail candidates (delegating to YouTubeOptimizer)")
        
        try:
            import sys
            # sys.modules でインポート不可と明示されている場合は、DIコンテナからの取得ではなくインポート不可として扱う
            if 'plugins.youtube_optimizer_plugin' in sys.modules and sys.modules['plugins.youtube_optimizer_plugin'] is None:
                raise ImportError("plugins.youtube_optimizer_plugin is disabled in sys.modules (simulated ImportError)")

            from service_container import container, setup_services
            setup_services()

            yt_opt_mod = sys.modules.get('plugins.youtube_optimizer_plugin')
            if yt_opt_mod is not None and getattr(yt_opt_mod, 'youtube_optimizer', None) is None:
                youtube_optimizer = None
            else:
                if container.has("youtube_optimizer"):
                    youtube_optimizer = container.get("youtube_optimizer")
                else:
                    from plugins.youtube_optimizer_plugin import youtube_optimizer

            if youtube_optimizer is None:
                raise AttributeError("youtube_optimizer is None")
            
            # タイトルと説明を取得
            title = context.get_extension("video_title", "") if hasattr(context, "get_extension") else ""
            description = context.get_extension("video_description", "") if hasattr(context, "get_extension") else ""
            
            # YouTubeOptimizerを使用してサムネイル候補を生成
            # segments形式に変換
            segments = getattr(context, 'segments', None) or []
            topics = [title] if title else []
            
            # 同期的にサムネイル候補を取得
            async def get_thumbnails():
                result = await youtube_optimizer.optimize_context(
                    segments=segments,
                    topics=topics,
                    context={"topic": title, "description": description}
                )
                if result is None:
                    return []
                return getattr(result, "thumbnail_candidates", []) or []
            
            # イベントループで実行
            try:
                loop = asyncio.get_running_loop()
                # 既存ループ内では別スレッドで実行
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, get_thumbnails())
                    candidates = future.result()
            except RuntimeError:
                candidates = asyncio.run(get_thumbnails())
            
            # 堅牢化: candidates がリストでない場合のガード
            if not isinstance(candidates, list):
                candidates = []

            # StageBoundAgent と連携した検証・補正処理の構築
            from agents.stage_bound_agent import StageBoundAgent
            db_path = getattr(context, "db_path", "backend/thumbnails.db") or "backend/thumbnails.db"
            agent = StageBoundAgent(stage_name="thumbnail", db_path=db_path)
            
            task_mapping = {}
            validated_candidates = []

            async def process_thumbnail_task(task_id: str) -> str:
                task_info = task_mapping.get(task_id)
                if not task_info:
                    raise ValueError(f"Task info not found for task_id: {task_id}")
                
                c = task_info["candidate"]
                path_str = getattr(c, 'path', None)
                
                # もし path が None であるか、ファイルが存在しない場合、実際に生成を試みる
                if not path_str or not Path(path_str).exists():
                    try:
                        async def generate():
                            return await youtube_optimizer.generate_thumbnail_with_imagen(c, {"topic": title})
                        generated_path = await generate()
                        if generated_path:
                            path_str = generated_path
                    except (AttributeError, ValueError, RuntimeError) as e:
                        logger.warning(f"Failed to generate thumbnail via Imagen in agent: {e}")
                
                if not path_str or not Path(path_str).exists():
                    raise ValueError(f"Thumbnail image file missing or failed to generate for candidate {getattr(c, 'id', 'unknown')}")
                
                # 品質検証と補正を行う
                corrected_path = validate_and_correct_thumbnail(path_str)
                
                # 最終的な検証情報の取得
                from PIL import Image
                with Image.open(corrected_path) as img:
                    img.load()
                    width, height = img.size
                size_bytes = Path(corrected_path).stat().st_size
                
                # 品質基準の検証
                if width < 1280 or height < 720:
                    raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
                if abs((width / height) - (16.0 / 9.0)) > 0.05:
                    raise ValueError(f"Aspect ratio must be 16:9. Got {width/height:.2f}")
                if size_bytes >= 4 * 1024 * 1024:
                    raise ValueError(f"File size exceeds 4MB: {size_bytes} bytes")
                
                result_info = {
                    "id": getattr(c, "id", "unknown"),
                    "path": corrected_path,
                    "width": width,
                    "height": height,
                    "size_bytes": size_bytes
                }
                return json.dumps(result_info)

            async def run_agent_tasks():
                # タスク登録
                for idx, c in enumerate(candidates[:self.num_candidates]):
                    task_id = f"thumb_plugin_{getattr(c, 'id', 'unknown')}_{uuid.uuid4().hex[:8]}"
                    task_mapping[task_id] = {
                        "candidate": c,
                        "index": idx
                    }
                    await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
                
                # エージェント起動
                await agent.start(process_thumbnail_task)
                
                # 完了待機
                start_time = time.time()
                timeout = 30.0
                try:
                    while time.time() - start_time < timeout:
                        all_done = True
                        for task_id in task_mapping.keys():
                            status = await agent.get_task_status(task_id)
                            if status not in ("COMPLETED", "FAILED"):
                                all_done = False
                                break
                        if all_done:
                            break
                        await asyncio.sleep(0.05)
                finally:
                    await agent.stop()

            # 同期的にエージェントタスクを実行
            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, run_agent_tasks())
                    future.result()
            except RuntimeError:
                asyncio.run(run_agent_tasks())

            # DBから結果をロードして context に反映
            conn = sqlite3.connect(db_path)
            try:
                for task_id, info in task_mapping.items():
                    cursor = conn.execute("SELECT status, result, error FROM tasks WHERE id = ?", (task_id,))
                    row = cursor.fetchone()
                    if row:
                        status, result, error = row
                        if status == "COMPLETED" and result:
                            res_data = json.loads(result)
                            c = info["candidate"]
                            setattr(c, 'path', Path(res_data["path"]))
                            validated_candidates.append(c)
                        else:
                            raise ValueError(f"Thumbnail validation/correction failed: {error}")
            finally:
                conn.close()

            # コンテキストに設定
            context.thumbnail_candidates = [
                {
                    "id": getattr(c, "id", "unknown_id"),
                    "concept": getattr(c, "concept", ""),
                    "target_emotion": getattr(c, "target_emotion", ""),
                    "text_overlay": getattr(c, "text_overlay", ""),
                    "predicted_ctr": getattr(c, "predicted_ctr", 0.0),
                    "path": getattr(c, 'path', None)
                }
                for c in validated_candidates
            ]
            if hasattr(context, "set_extension"):
                context.set_extension("thumbnail_count", len(context.thumbnail_candidates))
            
            self.log(f"Generated {len(context.thumbnail_candidates)} thumbnail candidates via YouTubeOptimizer")
            
        except ImportError as e:
            logger.error(f"YouTubeOptimizerPlugin import failed: {e}", exc_info=True)
            raise ThumbnailPluginError(f"Import failed: {e}") from e
        except sqlite3.Error as e:
            logger.error(f"Database error during thumbnail generation: {e}", exc_info=True)
            raise ThumbnailPluginError(f"Database failure: {e}") from e
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error in task result: {e}", exc_info=True)
            raise ThumbnailPluginError(f"JSON format failure: {e}") from e
        except ValueError as e:
            logger.error(f"Validation or value error during thumbnail generation: {e}", exc_info=True)
            raise ThumbnailPluginError(f"Validation failure: {e}") from e
        except AttributeError as e:
            logger.error(f"Attribute error during thumbnail generation: {e}", exc_info=True)
            raise ThumbnailPluginError(f"Attribute failure: {e}") from e
        except OSError as e:
            logger.error(f"File or system I/O error during thumbnail generation: {e}", exc_info=True)
            raise ThumbnailPluginError(f"I/O failure: {e}") from e
        except RuntimeError as e:
            logger.error(f"Runtime state error during thumbnail generation: {e}", exc_info=True)
            raise ThumbnailPluginError(f"Runtime failure: {e}") from e
        except (TypeError, KeyError, IndexError) as e:
            logger.error(f"Data structure access error during thumbnail generation: {e}", exc_info=True)
            raise ThumbnailPluginError(f"Data structure failure: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected uncaught error during thumbnail generation: {e}", exc_info=True)
            raise ThumbnailPluginError(f"Unexpected failure: {e}") from e
        
        return context
    
    def can_execute(self, context: ProductionContext) -> bool:
        """タイトルがある場合のみ実行"""
        if context is None or not hasattr(context, "get_extension"):
            return False
        return context.get_extension("video_title") is not None
