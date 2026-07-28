"""
Professional Quality Check with Real Video Preview
実際の動画を使用したYouTube品質基準でのプレビュー生成
"""

import subprocess
from pathlib import Path
import logging
import json
from PIL import Image, ImageFilter, UnidentifiedImageError

from path_resolver import raw_videos_dir


logger = logging.getLogger(__name__)



def get_video_duration(video_path: str) -> float:
    """ffprobe を使用して動画の長さを取得。失敗した場合はデフォルトで 10.0 秒とする。"""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    try:
        import subprocess
        res = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=10)
        return float(res.stdout.strip())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, FileNotFoundError, OSError) as e:
        logger.warning(f"ffprobeによる動画長取得に失敗しました。デフォルトの10.0秒を使用します: {e}")
        return 10.0


def create_production_preview(
    input_video: str,
    subtitle_file: str,
    theme_text: str,
    output_dir: str = "backend/temp/production_preview",
    speaker1: str = "北原美麗",
    speaker2: str = "山田タロウ"
):
    """
    本番品質のプレビューを生成
    
    手順:
    1. 実際の動画から10秒抽出
    2. CombinedOverlay を用いたロゴ+テーマテロップ適用
    3. 字幕焼き込み（実際のSRT）
    4. 複数フレームのスクリーンショット生成と 1280x720 (16:9) 高品質リサイズ
    """
    input_video_path = Path(input_video)
    subtitle_path = Path(subtitle_file)
    
    # 入力検証
    if not input_video_path.exists():
        raise FileNotFoundError(f"Input video not found: {input_video}")
    if not subtitle_path.exists():
        raise FileNotFoundError(f"Subtitle file not found: {subtitle_file}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"\n{'='*60}")
    logger.info(f"本番品質プレビュー生成")
    logger.info(f"{'='*60}")
    logger.info(f"動画: {input_video_path.name}")
    logger.info(f"テーマ: {theme_text}")
    
    # 一時ファイルのリスト（クリーンアップ用）
    temp_files = []
    
    try:
        # Step 1: 10秒抽出（代表的なシーン：5秒開始地点から）
        base_video = output_dir / "base_10s.mp4"
        temp_files.append(base_video)
        logger.info("\n[1/4] 動画抽出中...")
        
        duration = get_video_duration(str(input_video_path))
        start_time = "5" if duration >= 15.0 else "0"
        extract_len = "10" if duration >= 10.0 else f"{duration:.2f}"
        logger.info(f"動画長: {duration}s -> 開始位置: {start_time}s, 抽出長: {extract_len}s")

        extract_cmd = [
            "ffmpeg",
            "-ss", start_time,
            "-i", str(input_video_path),
            "-t", extract_len,
            "-c:v", "libx264",
            "-c:a", "copy",
            "-y",
            str(base_video)
        ]
        try:
            subprocess.run(extract_cmd, check=True, capture_output=True, timeout=60)
            logger.info("✅ 10秒抽出完了")
        except subprocess.TimeoutExpired as e:
            logger.error(f"動画抽出タイムアウト: {e}")
            raise
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
            logger.error(f"動画抽出失敗: {err_msg}")
            raise

        # Step 2: ロゴ+テーマテロップ適用 (CombinedOverlayを使用)
        logger.info("\n[2/4] ロゴ+テロップ適用中...")
        from combined_overlay import CombinedOverlay
        overlay = CombinedOverlay()
        
        logo_video = output_dir / "with_logo.mp4"
        temp_files.append(logo_video)
        
        try:
            overlay.apply_brand_overlay(
                input_video=str(base_video),
                output_path=str(logo_video),
                speaker1=speaker1,
                speaker2=speaker2,
                theme=theme_text,
                logo_position=(10, 10),
                logo_height=45,  # B案サイズ
                logo_opacity=0.8,
                telop_opacity=0.85
            )
            logger.info("✅ ロゴ+テロップ適用完了")
        except (FileNotFoundError, OSError, subprocess.SubprocessError) as e:
            logger.error(f"ロゴ+テロップ適用失敗: {e}")
            raise

        # Step 3: 字幕焼き込み（subtitlesフィルタ使用）
        logger.info("\n[3/4] 字幕焼き込み中...")
        final_video = output_dir / "final_preview.mp4"
        
        # 字幕スタイル（YouTube推奨）
        subtitle_style = (
            "FontName=Arial,"
            "FontSize=20,"
            "PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,"
            "BorderStyle=1,"
            "Outline=2,"
            "Shadow=1,"
            "Alignment=2,"
            "MarginV=40"
        )
        
        # WindowsにおけるFFmpegのsubtitlesフィルタのパスエスケープ対策
        sub_file_escaped = str(subtitle_path.absolute()).replace("\\", "/")
        sub_file_escaped = sub_file_escaped.replace(":", "\\:")
        
        subtitle_cmd = [
            "ffmpeg",
            "-i", str(logo_video),
            "-vf", f"subtitles='{sub_file_escaped}':force_style='{subtitle_style}'",
            "-c:a", "copy",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-y",
            str(final_video)
        ]
        
        try:
            subprocess.run(subtitle_cmd, check=True, capture_output=True, timeout=120)
            logger.info("✅ 字幕焼き込み完了")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            err_msg = e.stderr.decode('utf-8', errors='ignore') if hasattr(e, 'stderr') and e.stderr else str(e)
            logger.warning(f"字幕焼き込み失敗 (FFmpeg実行エラー): {err_msg}", exc_info=True)
            logger.info("→ ロゴ+テロップのみで続行")
            import shutil
            shutil.copy(str(logo_video), str(final_video))
        except OSError as e:
            logger.warning(f"字幕焼き込み失敗 (I/Oエラー): {e}", exc_info=True)
            logger.info("→ ロゴ+テロップのみで続行")
            import shutil
            shutil.copy(str(logo_video), str(final_video))

        # Step 4: スクリーンショット生成（複数フレーム）および高品質リサイズ
        logger.info("\n[4/4] スクリーンショット生成中...")
        
        screenshots = []
        final_video_duration = get_video_duration(str(final_video))
        if final_video_duration >= 10.0:
            timestamps = [0.5, 3.0, 7.0]
        else:
            timestamps = [final_video_duration * 0.1, final_video_duration * 0.5, final_video_duration * 0.9]
        logger.info(f"スクリーンショット抽出位置: {[f'{t:.2f}s' for t in timestamps]}")
        
        for i, ts in enumerate(timestamps):
            screenshot_path = output_dir / f"screenshot_{i+1}_{int(ts)}s.png"
            
            # エラーハンドリング強化：FFmpeg抽出失敗時のリトライ（異なるタイムスタンプ）
            success = False
            err_msg = ""
            # 元のタイムスタンプと、そこからのオフセット候補（±0.5秒、±1.0秒）
            ts_attempts = [ts, ts + 0.5, ts - 0.5, ts + 1.0]
            
            for attempt_ts in ts_attempts:
                if attempt_ts < 0:
                    continue
                screenshot_cmd = [
                    "ffmpeg",
                    "-ss", f"{attempt_ts:.2f}",
                    "-i", str(final_video),
                    "-frames:v", "1",
                    "-y",
                    str(screenshot_path)
                ]
                try:
                    subprocess.run(screenshot_cmd, check=True, capture_output=True, timeout=30)
                    if screenshot_path.exists() and screenshot_path.stat().st_size > 0:
                        # 正常に抽出でき、かつ壊れていないことをPillowで簡単にチェック
                        with Image.open(screenshot_path) as test_img:
                            test_img.verify()
                        success = True
                        ts = attempt_ts  # 実際に成功したタイムスタンプを記録
                        break
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired, UnidentifiedImageError, OSError, SyntaxError, ValueError) as e:
                    err_msg = e.stderr.decode('utf-8', errors='ignore') if hasattr(e, 'stderr') and e.stderr else str(e)
                    logger.warning(f"スクリーンショット {attempt_ts}秒 での抽出失敗（リトライします）: {err_msg}")
                    if screenshot_path.exists():
                        try:
                            screenshot_path.unlink()
                        except OSError:
                            pass
            
            if not success:
                logger.error(f"スクリーンショット {ts}秒 の抽出に完全に失敗しました。最後のエラー: {err_msg}")
                raise RuntimeError(f"Failed to capture screenshot at {ts}s: {err_msg}")
            
            # Pillow を使って高品質にリサイズ (YouTube推奨: 1280x720, 16:9)
            if screenshot_path.exists():
                try:
                    with Image.open(screenshot_path) as img:
                        target_width = 1280
                        target_height = 720
                        
                        img_aspect = img.width / img.height
                        target_aspect = target_width / target_height
                        
                        if img_aspect > target_aspect:
                            new_width = target_width
                            new_height = int(target_width / img_aspect)
                        else:
                            new_height = target_height
                            new_width = int(target_height * img_aspect)
                            
                        # リサイズ
                        resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                        
                        # カラープロファイル (ICC プロファイル) の保持
                        icc = img.info.get("icc_profile")
                        
                        # 品質向上: 単純な黒塗りキャンバスではなく、背景に元の映像を拡大・ぼかしたものを配置
                        # アスペクト比がピッタリ一致しない場合のみぼかし背景を使用し、一致する場合はそのままリサイズ
                        if abs(img_aspect - target_aspect) > 0.01:
                            blur_bg = img.resize((target_width, target_height), Image.Resampling.BILINEAR)
                            blur_bg = blur_bg.filter(ImageFilter.GaussianBlur(radius=20))
                            canvas = blur_bg.convert("RGBA")
                        else:
                            canvas = Image.new("RGBA", (target_width, target_height), (0, 0, 0, 255))
                            
                        offset_x = (target_width - new_width) // 2
                        offset_y = (target_height - new_height) // 2
                        canvas.paste(resized_img, (offset_x, offset_y))
                        
                        rgb_canvas = canvas.convert("RGB")
                        
                        # まずは高品質な PNG で保存 (ICCプロファイル、最適化指定)
                        save_kwargs = {"optimize": True}
                        if icc:
                            save_kwargs["icc_profile"] = icc
                        rgb_canvas.save(screenshot_path, "PNG", **save_kwargs)
                        
                        # ファイルサイズが 4MB 未満かチェック
                        size_bytes = screenshot_path.stat().st_size
                        if size_bytes >= 4 * 1024 * 1024:
                            logger.warning(f"PNG size ({size_bytes} bytes) exceeds 4MB. Falling back to JPEG with optimization.")
                            screenshot_path_jpg = screenshot_path.with_suffix(".jpg")
                            
                            # JPEG の品質を調整しながら 4MB 未満に収める
                            for quality in [95, 90, 80, 70]:
                                save_kwargs_jpg = {"quality": quality, "optimize": True, "progressive": True}
                                if icc:
                                    save_kwargs_jpg["icc_profile"] = icc
                                rgb_canvas.save(screenshot_path_jpg, "JPEG", **save_kwargs_jpg)
                                size_bytes_jpg = screenshot_path_jpg.stat().st_size
                                if size_bytes_jpg < 4 * 1024 * 1024:
                                    break
                            
                            if screenshot_path.exists():
                                screenshot_path.unlink()
                            screenshot_path = screenshot_path_jpg
                            
                    # 品質要件の検証
                    validation_result = validate_preview_image(screenshot_path)
                    screenshots.append(str(screenshot_path))
                    logger.info(f"  ✅ スクリーンショット{i+1}: {ts}秒 (解像度: {validation_result['width']}x{validation_result['height']}, サイズ: {validation_result['size_bytes']} bytes)")
                except (UnidentifiedImageError, OSError, ValueError, FileNotFoundError, KeyError) as e:
                    logger.error(f"スクリーンショット {screenshot_path.name} の画像処理または品質検証失敗: {e}")
                    raise
            else:
                raise FileNotFoundError(f"Screenshot file not found: {screenshot_path}")

        logger.info(f"\n{'='*60}")
        logger.info("🎉 本番品質プレビュー完成！")
        logger.info(f"{'='*60}")
        logger.info(f"プレビュー動画: {final_video}")
        logger.info(f"スクリーンショット: {len(screenshots)}枚")
        
        return {
            "video": str(final_video),
            "screenshots": screenshots
        }

    finally:
        # 一時ファイルのクリーンアップ
        for temp_file in temp_files:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                    logger.info(f"一時ファイルを削除しました: {temp_file.name}")
                except OSError as e:
                    logger.warning(f"一時ファイル {temp_file.name} の削除失敗: {e}")




def validate_preview_image(file_path) -> dict:
    """
    プレビュー（サムネイル）画像の品質要件を検証する
    - 生成画像の解像度が 1280x720 以上であること
    - アスペクト比が 16:9 であること
    - ファイルサイズが 4MB 未満であること
    - 出力ファイルが正常に存在し、破損していない（Pillow等で正常にロード可能である）こと
    """
    from PIL import Image, UnidentifiedImageError
    from pathlib import Path
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Preview file not found: {file_path}")
        
    size_bytes = file_path.stat().st_size
    if size_bytes == 0:
        raise ValueError(f"File size is 0 bytes: {file_path}")
    if size_bytes >= 4 * 1024 * 1024:
        raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")
        
    # 簡易検証
    try:
        with Image.open(file_path) as img:
            img.verify()
    except UnidentifiedImageError as e:
        raise ValueError(f"File is not a recognized image format: {e}")
    except (OSError, SyntaxError, ValueError) as e:
        raise ValueError(f"Image structure is corrupted (verify failed): {e}")
        
    # 完全なピクセルデータのロードによる破損検知
    try:
        with Image.open(file_path) as img:
            img.load()  # ピクセルデータのロードを強制
            width, height = img.size
    except UnidentifiedImageError as e:
        raise ValueError(f"File is not a recognized image format during load: {e}")
    except (OSError, SyntaxError, ValueError) as e:
        raise ValueError(f"Image is corrupted and cannot be loaded: {e}")
        
    if width < 1280 or height < 720:
        raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
        
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 0.05:
        raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f} (width: {width}, height: {height})")
        
    return {
        "path": str(file_path),
        "width": width,
        "height": height,
        "size_bytes": size_bytes
    }


class ProductionPreviewManager:
    """
    StageBoundAgent等と連携してプレビュー生成タスクを処理するマネージャークラス
    """
    def __init__(
        self,
        input_video: str,
        subtitle_file: str,
        theme_text: str,
        output_dir: str = "backend/temp/production_preview",
        speaker1: str = "北原美麗",
        speaker2: str = "山田タロウ"
    ):
        self.input_video = input_video
        self.subtitle_file = subtitle_file
        self.theme_text = theme_text
        self.output_dir = output_dir
        self.speaker1 = speaker1
        self.speaker2 = speaker2

    async def resolve_production_preview_task(self, task_id: str) -> str:
        """
        StageBoundAgent の process_func として動作する非同期タスク処理
        自動リトライ、結果保存、DBマイグレーションの各機能と連携して動作する
        """
        import asyncio
        import json
        
        loop = asyncio.get_running_loop()
        
        # CPUヘビーな処理をスレッドプールで非同期実行
        result = await loop.run_in_executor(
            None,
            lambda: create_production_preview(
                input_video=self.input_video,
                subtitle_file=self.subtitle_file,
                theme_text=self.theme_text,
                output_dir=self.output_dir,
                speaker1=self.speaker1,
                speaker2=self.speaker2
            )
        )
        
        # 各スクリーンショットが正常に検証に通るか再確認
        for shot in result["screenshots"]:
            validate_preview_image(shot)
            
        return json.dumps(result)


def main():
    # シーン04で実行
    input_v = str(raw_videos_dir() / "AI Studio アップロード用動画" / "シーン04_後編02.mp4")
    subtitle = str(raw_videos_dir() / "AI Studio アップロード用動画" / "シーン04_後編02_whisper_semantic.srt")
    
    # 改善されたテーマ
    theme = "コリンスキー筆の真実"
    
    if Path(input_v).exists() and Path(subtitle).exists():
        result = create_production_preview(input_v, subtitle, theme)
        
        print(f"\n✅ 完了:")
        print(f"  動画: {Path(result['video']).name}")
        print(f"  スクリーンショット: {len(result['screenshots'])}枚")
        return 0
    else:
        print("❌ ファイルが見つかりません")
        return 1


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
