"""
Hook Preview Generator Service - フック改善プレビュー生成サービス

PROJECT_CONSTITUTION §23 YouTube最適化規約準拠:
- Before/After比較画像生成
- 5秒動画プレビュー生成
- 改善案の視覚的効果確認
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from pathlib import Path
import logging
import subprocess
import tempfile
import base64
import os

logger = logging.getLogger(__name__)


@dataclass
class HookPreviewResult:
    """フックプレビュー結果"""
    before_image: Optional[str] = None  # Base64画像
    after_image: Optional[str] = None   # Base64画像
    before_video_path: Optional[str] = None
    after_video_path: Optional[str] = None
    comparison_image: Optional[str] = None  # Before/After比較画像
    success: bool = False
    message: str = ""


class HookPreviewGenerator:
    """
    フック改善プレビュー生成サービス
    
    改善案を視覚的に確認するためのプレビューを生成する。
    - スクリーンショット比較
    - 5秒動画プレビュー
    """
    
    PREVIEW_WIDTH = 1280
    PREVIEW_HEIGHT = 720
    FONT_SIZE = 48
    FONT_COLOR = "white"
    FONT_BORDER_COLOR = "black"
    
    def __init__(self, output_dir: str = "output/hook_previews"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    async def generate_screenshot_preview(
        self,
        video_path: str,
        original_text: str,
        improved_text: str,
        timestamp: float = 2.5
    ) -> HookPreviewResult:
        """
        Before/Afterスクリーンショットを生成
        
        Args:
            video_path: 元動画のパス
            original_text: 元のフックテキスト
            improved_text: 改善後のフックテキスト
            timestamp: スクリーンショットのタイムスタンプ（秒）
        
        Returns:
            HookPreviewResult: プレビュー結果
        """
        logger.info(f"Generating screenshot preview at {timestamp}s")
        
        # 入力バリデーションとクランプ
        original_text = str(original_text) if original_text is not None else ""
        improved_text = str(improved_text) if improved_text is not None else ""
        if timestamp < 0.0:
            timestamp = 0.0
            
        try:
            # 動画が存在しない場合はダミー画像を生成
            if not Path(video_path).exists():
                return await self._generate_dummy_preview(original_text, improved_text)
            
            # 一時ディレクトリを作成
            with tempfile.TemporaryDirectory() as tmpdir:
                before_path = Path(tmpdir) / "before.png"
                after_path = Path(tmpdir) / "after.png"
                comparison_path = Path(tmpdir) / "comparison.png"
                
                # Beforeスクリーンショット（元テキスト付き）
                await self._extract_frame_with_text(
                    video_path, timestamp, original_text, str(before_path), label="BEFORE"
                )
                
                # Afterスクリーンショット（改善テキスト付き）
                await self._extract_frame_with_text(
                    video_path, timestamp, improved_text, str(after_path), label="AFTER"
                )
                
                # Before/After比較画像を生成
                await self._create_comparison_image(
                    str(before_path), str(after_path), str(comparison_path)
                )
                
                # Base64エンコード
                before_b64 = self._encode_image(before_path)
                after_b64 = self._encode_image(after_path)
                comparison_b64 = self._encode_image(comparison_path)
                
                return HookPreviewResult(
                    before_image=before_b64,
                    after_image=after_b64,
                    comparison_image=comparison_b64,
                    success=True,
                    message="プレビュー生成完了"
                )
                
        except Exception as e:
            logger.error(f"Screenshot preview generation failed: {e}")
            return HookPreviewResult(
                success=False,
                message=f"プレビュー生成エラー: {str(e)}"
            )
    
    async def generate_video_preview(
        self,
        video_path: str,
        original_text: str,
        improved_text: str,
        task_id: str = ""
    ) -> HookPreviewResult:
        """
        Before/After 5秒動画プレビューを生成
        
        Args:
            video_path: 元動画のパス
            original_text: 元のフックテキスト
            improved_text: 改善後のフックテキスト
            task_id: タスクID
        
        Returns:
            HookPreviewResult: プレビュー結果
        """
        logger.info("Generating video preview")
        
        # 入力バリデーション
        original_text = str(original_text) if original_text is not None else ""
        improved_text = str(improved_text) if improved_text is not None else ""
        
        try:
            # 出力ディレクトリ
            task_dir = self.output_dir / (task_id or "default")
            task_dir.mkdir(parents=True, exist_ok=True)
            
            before_video = task_dir / "hook_before.mp4"
            after_video = task_dir / "hook_after.mp4"
            
            # 動画が存在しない場合
            if not Path(video_path).exists():
                return HookPreviewResult(
                    success=False,
                    message="元動画が見つかりません"
                )
            
            # Before動画（元テキスト付き）
            await self._create_video_with_text(
                video_path, original_text, str(before_video), duration=5, label="BEFORE"
            )
            
            # After動画（改善テキスト付き）
            await self._create_video_with_text(
                video_path, improved_text, str(after_video), duration=5, label="AFTER"
            )
            
            return HookPreviewResult(
                before_video_path=str(before_video),
                after_video_path=str(after_video),
                success=True,
                message="動画プレビュー生成完了"
            )
            
        except Exception as e:
            logger.error(f"Video preview generation failed: {e}")
            return HookPreviewResult(
                success=False,
                message=f"動画プレビュー生成エラー: {str(e)}"
            )
    
    def _wrap_text(self, text: str, max_width: int = 35) -> str:
        """
        テキストを一定の幅（全角換算）で折り返します。
        全角文字・絵文字は2、半角文字は1としてカウントします。
        """
        if not text:
            return ""
        lines = []
        for line in text.splitlines():
            current_line = []
            current_len = 0
            for char in line:
                char_len = 2 if ord(char) > 127 else 1
                if current_len + char_len > max_width:
                    lines.append("".join(current_line))
                    current_line = [char]
                    current_len = char_len
                else:
                    current_line.append(char)
                    current_len += char_len
            if current_line:
                lines.append("".join(current_line))
        return "\n".join(lines)

    async def _extract_frame_with_text(
        self,
        video_path: str,
        timestamp: float,
        text: str,
        output_path: str,
        label: str = ""
    ) -> None:
        """動画からフレームを抽出し、テキストを重ねる"""
        wrapped_text = self._wrap_text(text)
        
        filters = [f"scale={self.PREVIEW_WIDTH}:{self.PREVIEW_HEIGHT}"]
        
        if label:
            label_color = "0xff3333@0.8" if "BEFORE" in label.upper() else "0x33cc33@0.8"
            label_filter = (
                f"drawtext=text='{label}':"
                f"fontsize=24:"
                f"fontcolor=white:"
                f"box=1:boxcolor={label_color}:boxborderw=8:"
                f"x=30:y=30"
            )
            filters.append(label_filter)
            
        drawtext_filter = (
            f"drawtext=text='{self._escape_ffmpeg_text(wrapped_text)}':"
            f"fontsize={self.FONT_SIZE}:"
            f"fontcolor={self.FONT_COLOR}:"
            f"borderw=3:bordercolor={self.FONT_BORDER_COLOR}:"
            f"box=1:boxcolor=black@0.5:boxborderw=12:"
            f"x=(w-text_w)/2:y=h-th-80"
        )
        filters.append(drawtext_filter)
        
        filter_complex = ",".join(filters)
        
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(timestamp),
            "-i", video_path,
            "-vframes", "1",
            "-vf", filter_complex,
            output_path
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                logger.warning(
                    f"FFmpeg extract frame failed (code {result.returncode}). "
                    f"Stderr: {result.stderr[:500]}"
                )
                await self._create_placeholder_image(text, output_path, label)
        except (subprocess.SubprocessError, subprocess.TimeoutExpired) as e:
            logger.error(f"FFmpeg execution failed or timed out: {e}")
            await self._create_placeholder_image(text, output_path, label)
    
    async def _create_video_with_text(
        self,
        video_path: str,
        text: str,
        output_path: str,
        duration: float = 5,
        label: str = ""
    ) -> None:
        """動画の冒頭にテキストを重ねた短いクリップを作成"""
        wrapped_text = self._wrap_text(text)
        
        filters = [f"scale={self.PREVIEW_WIDTH}:{self.PREVIEW_HEIGHT}"]
        
        if label:
            label_color = "0xff3333@0.8" if "BEFORE" in label.upper() else "0x33cc33@0.8"
            label_filter = (
                f"drawtext=text='{label}':"
                f"fontsize=24:"
                f"fontcolor=white:"
                f"box=1:boxcolor={label_color}:boxborderw=8:"
                f"x=30:y=30"
            )
            filters.append(label_filter)
            
        drawtext_filter = (
            f"drawtext=text='{self._escape_ffmpeg_text(wrapped_text)}':"
            f"fontsize={self.FONT_SIZE}:"
            f"fontcolor={self.FONT_COLOR}:"
            f"borderw=3:bordercolor={self.FONT_BORDER_COLOR}:"
            f"box=1:boxcolor=black@0.5:boxborderw=12:"
            f"x=(w-text_w)/2:y=h-th-80"
        )
        filters.append(drawtext_filter)
        
        filter_complex = ",".join(filters)
        
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-t", str(duration),
            "-vf", filter_complex,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "28",
            "-c:a", "aac",
            "-b:a", "128k",
            output_path
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                logger.warning(
                    f"FFmpeg video creation failed (code {result.returncode}). "
                    f"Stderr: {result.stderr[:500]}"
                )
        except (subprocess.SubprocessError, subprocess.TimeoutExpired) as e:
            logger.error(f"FFmpeg video creation failed or timed out: {e}")
    
    async def _create_comparison_image(
        self,
        before_path: str,
        after_path: str,
        output_path: str
    ) -> None:
        '''Before/After比較画像を作成 (Pillowを使用して確実に16:9 1280x720にする)'''
        from PIL import Image, ImageDraw
        try:
            with Image.open(before_path) as img_before, Image.open(after_path) as img_after:
                with Image.new("RGB", (1280, 720), (255, 255, 255)) as canvas:
                    
                    def resize_and_crop(img, target_w, target_h):
                        img_ratio = img.width / img.height
                        target_ratio = target_w / target_h
                        if img_ratio > target_ratio:
                            new_h = target_h
                            new_w = int(target_h * img_ratio)
                        else:
                            new_w = target_w
                            new_h = int(target_w / img_ratio)
                        
                        try:
                            resample_filter = Image.Resampling.LANCZOS
                        except AttributeError:
                            resample_filter = Image.ANTIALIAS
                            
                        resized = img.resize((new_w, new_h), resample_filter)
                        left = (new_w - target_w) // 2
                        top = (new_h - target_h) // 2
                        cropped = resized.crop((left, top, left + target_w, top + target_h))
                        return cropped
                    
                    before_cropped = resize_and_crop(img_before, 635, 720)
                    after_cropped = resize_and_crop(img_after, 635, 720)
                    
                    try:
                        canvas.paste(before_cropped, (0, 0))
                        canvas.paste(after_cropped, (645, 0))
                        
                        # 中央の境界線を描画して美しく仕切る
                        with ImageDraw.Draw(canvas) as draw:
                            draw.rectangle([635, 0, 645, 720], fill=(20, 20, 20))
                        
                        canvas.save(output_path, "PNG", optimize=True)
                    finally:
                        before_cropped.close()
                        after_cropped.close()
        except Exception as e:
            logger.error(f"Failed to create comparison image with Pillow: {e}")
            self._fallback_comparison(before_path, output_path)

    def _fallback_comparison(self, before_path: str, output_path: str) -> None:
        '''比較画像生成失敗時のコピーフォールバック (必ず16:9 1280x720のフォーマットを満たすよう再生成)'''
        from PIL import Image
        try:
            with Image.open(before_path) as img:
                try:
                    resample_filter = Image.Resampling.LANCZOS
                except AttributeError:
                    resample_filter = Image.ANTIALIAS
                # 確実に 1280x720 16:9 にリサイズする
                with img.resize((1280, 720), resample_filter) as out_img:
                    out_img.save(output_path, "PNG", optimize=True)
        except Exception as e:
            logger.error(f"Failed to fallback comparison with Pillow resizing: {e}")
            # 最後の手段としてそのままコピー
            import shutil
            shutil.copy(before_path, output_path)
    
    async def _generate_dummy_preview(
        self,
        original_text: str,
        improved_text: str
    ) -> HookPreviewResult:
        '''ダミープレビューを生成（動画がない場合）'''
        with tempfile.TemporaryDirectory() as tmpdir:
            before_path = Path(tmpdir) / "before.png"
            after_path = Path(tmpdir) / "after.png"
            comparison_path = Path(tmpdir) / "comparison.png"
            
            self._generate_image_pillow(original_text, str(before_path), label="BEFORE")
            self._generate_image_pillow(improved_text, str(after_path), label="AFTER")
            
            await self._create_comparison_image(
                str(before_path), str(after_path), str(comparison_path)
            )
            
            before_b64 = self._encode_image(before_path)
            after_b64 = self._encode_image(after_path)
            comparison_b64 = self._encode_image(comparison_path)
            
            return HookPreviewResult(
                before_image=before_b64,
                after_image=after_b64,
                comparison_image=comparison_b64,
                success=True,
                message="プレビュー生成完了（デモモード）"
            )
    
    async def _create_placeholder_image(self, text: str, output_path: str, label: str = "") -> None:
        '''プレースホルダー画像を作成'''
        self._generate_image_pillow(text, output_path, label)
    
    def _generate_image_pillow(self, text: str, output_path: str, label: str = "") -> None:
        '''Pillowを使用して高品質な画像ファイルを生成する (フォントサイズ自動調整とリッチなグラデーション)'''
        from PIL import Image, ImageDraw, ImageFont
        import os
        
        width = self.PREVIEW_WIDTH
        height = self.PREVIEW_HEIGHT
        
        # 1. リッチな色調設定 (BEFORE: 深みのあるワイン/パープル, AFTER: 深みのあるエメラルド/フォレスト)
        if "BEFORE" in label.upper():
            color1 = (50, 20, 20)
            color2 = (20, 10, 10)
        else:
            color1 = (20, 50, 20)
            color2 = (10, 20, 10)
            
        # 2. 角度付きの滑らかな2次元グラデーションを生成して高級感を演出 (8x8対角グラデーションからの拡大)
        grad_small = Image.new("RGB", (8, 8))
        for y in range(8):
            for x in range(8):
                # 対角線方向の比率
                t = (x + y) / 14.0
                r = int(color1[0] * (1 - t) + color2[0] * t)
                g = int(color1[1] * (1 - t) + color2[1] * t)
                b = int(color1[2] * (1 - t) + color2[2] * t)
                grad_small.putpixel((x, y), (r, g, b))
        
        try:
            resample_filter = Image.Resampling.LANCZOS
        except AttributeError:
            resample_filter = Image.ANTIALIAS
            
        with grad_small.resize((width, height), resample_filter) as img:
            draw = ImageDraw.Draw(img)
            
            # フォント候補リスト (美麗フォントを優先)
            font_paths = [
                r"C:\Windows\Fonts\meiryo.ttc",           # メイリオ (Windows)
                r"C:\Windows\Fonts\yugothm.ttc",          # 游ゴシック (Windows)
                r"C:\Windows\Fonts\msjh.ttc",             # Microsoft JhengHei
                r"C:\Windows\Fonts\msyh.ttc",             # Microsoft YaHei
                r"C:\Windows\Fonts\msgothic.ttc",         # MS ゴシック (Windows)
                r"C:\Windows\Fonts\arial.ttf",            # Arial (Windows)
                "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc", # ヒラギノ (Mac)
                "/System/Library/Fonts/PingFang.ttc",      # PingFang (Mac)
                "/Library/Fonts/Arial.ttf",               # Arial (Mac)
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", # Noto CJK (Linux)
                "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf", # Debian/Ubuntu
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
            
            # テキストの折り返し
            wrapped_text = self._wrap_text(text)
            lines = wrapped_text.splitlines()
            
            # 3. フォントサイズの自動調整 (長いテキストでもはみ出さないようにスケーリング)
            font = None
            current_font_size = self.FONT_SIZE
            
            while current_font_size >= 16:
                # フォントをロード
                for fp in font_paths:
                    if os.path.exists(fp):
                        try:
                            font = ImageFont.truetype(fp, current_font_size)
                            break
                        except OSError:
                            continue
                if font is None:
                    try:
                        font = ImageFont.load_default(size=current_font_size)
                    except TypeError:
                        font = ImageFont.load_default()
                
                # テキストの描画領域サイズを測定してチェック
                max_line_w = 0
                total_h = 0
                for line in lines:
                    try:
                        bbox = draw.textbbox((0, 0), line, font=font)
                        line_w = bbox[2] - bbox[0]
                        line_h = bbox[3] - bbox[1]
                    except AttributeError:
                        line_w = len(line) * (current_font_size * 0.6)
                        line_h = current_font_size
                    max_line_w = max(max_line_w, line_w)
                    total_h += line_h + 10
                    
                # 画面内に収まるか判定 (幅制限 1100, 高さ制限 500)
                if max_line_w <= 1100 and total_h <= 500:
                    break
                # 収まらない場合はフォントサイズを縮小して再試行
                current_font_size -= 4
                
            # 4. BEFORE / AFTER のバッジ描画 (モダンUI・ドロップシャドウ付き)
            if label:
                is_before = "BEFORE" in label.upper()
                label_color = (239, 68, 68) if is_before else (16, 185, 129)  # Tailwind赤/緑
                
                # ラベル用フォント
                label_font = None
                for fp in font_paths:
                    if os.path.exists(fp):
                        try:
                            label_font = ImageFont.truetype(fp, 22)
                            break
                        except OSError:
                            continue
                if label_font is None:
                    try:
                        label_font = ImageFont.load_default(size=22)
                    except Exception:
                        label_font = font
                
                try:
                    l_bbox = draw.textbbox((0, 0), label, font=label_font)
                    l_w = l_bbox[2] - l_bbox[0]
                    l_h = l_bbox[3] - l_bbox[1]
                except AttributeError:
                    l_w = len(label) * 14
                    l_h = 22
                
                badge_w = l_w + 36
                badge_h = l_h + 20
                bx1, by1 = 30, 30
                bx2, by2 = bx1 + badge_w, by1 + badge_h
                
                # バッジのソフトシャドウ
                try:
                    draw.rounded_rectangle([bx1 + 3, by1 + 3, bx2 + 3, by2 + 3], radius=10, fill=(10, 10, 10))
                except AttributeError:
                    draw.rectangle([bx1 + 3, by1 + 3, bx2 + 3, by2 + 3], fill=(10, 10, 10))
                    
                # バッジ本体
                try:
                    draw.rounded_rectangle([bx1, by1, bx2, by2], radius=10, fill=label_color, outline="white", width=2)
                except AttributeError:
                    draw.rectangle([bx1, by1, bx2, by2], fill=label_color, outline="white", width=2)
                    
                tx = bx1 + (badge_w - l_w) // 2
                ty = by1 + (badge_h - l_h) // 2 - 2
                draw.text((tx, ty), label, fill="white", font=label_font)
                
            # 5. テキスト描画 (シャドウとアウトラインによる高コントラスト視認性向上)
            y_offset = height // 2 - total_h // 2
            for line in lines:
                try:
                    bbox = draw.textbbox((0, 0), line, font=font)
                    line_w = bbox[2] - bbox[0]
                    line_h = bbox[3] - bbox[1]
                except AttributeError:
                    line_w = len(line) * (current_font_size * 0.6)
                    line_h = current_font_size
                    
                x_pos = (width - line_w) // 2
                
                # 美麗なアウトラインの描画 (stroke_widthパラメータを優先使用)
                try:
                    # ドロップシャドウ
                    draw.text((x_pos + 4, y_offset + 4), line, fill=(10, 10, 10), font=font, stroke_width=2, stroke_fill=(10, 10, 10))
                    # メインテキスト (美麗アウトライン付き白文字)
                    draw.text((x_pos, y_offset), line, fill="white", font=font, stroke_width=3, stroke_fill=(0, 0, 0))
                except TypeError:
                    # 古いPillow向けフォールバック
                    draw.text((x_pos + 4, y_offset + 4), line, fill=(10, 10, 10), font=font)
                    for dx, dy in [(-2, -2), (2, -2), (-2, 2), (2, 2), (-2, 0), (2, 0), (0, -2), (0, 2)]:
                        draw.text((x_pos + dx, y_offset + dy), line, fill=(0, 0, 0), font=font)
                    draw.text((x_pos, y_offset), line, fill="white", font=font)
                    
                y_offset += line_h + 15
                
            out_path = Path(output_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(out_path, "PNG", optimize=True)

    def validate_preview_image(self, file_path: str) -> dict:
        '''
        生成されたプレビュー画像の品質要件を検証する
        '''
        from PIL import Image
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Preview image file not found: {file_path}")
            
        size_bytes = path.stat().st_size
        if size_bytes >= 4 * 1024 * 1024:
            raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")
            
        try:
            with Image.open(path) as img:
                img.verify()
        except Exception as e:
            raise ValueError(f"Image verify failed: {e}")
            
        try:
            with Image.open(path) as img:
                img.load()
                width, height = img.size
        except Exception as e:
            raise ValueError(f"Image load failed: {e}")
            
        if width < 1280 or height < 720:
            raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
            
        aspect_ratio = width / height
        target_ratio = 16.0 / 9.0
        if abs(aspect_ratio - target_ratio) > 0.01:
            raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")
            
        return {
            "path": str(path),
            "width": width,
            "height": height,
            "size_bytes": size_bytes
        }

    async def resolve_hook_preview_task(self, task_id: str, db_path: str = ":memory:") -> str:
        '''
        StageBoundAgent の process_func として動作する non-member 非同期タスク処理
        
        DBの `tasks` テーブルからパラメータを読み込み、プレビューを生成し、
        品質要件の検証を行って結果を保存する。
        '''
        import sqlite3
        import json
        
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("PRAGMA table_info(tasks)")
            columns = [row[1] for row in cursor.fetchall()]
            if "params" not in columns:
                conn.execute("ALTER TABLE tasks ADD COLUMN params TEXT")
                conn.commit()
                
            cursor = conn.execute("SELECT params FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            params_str = row[0] if row else None
            
            params = {}
            if params_str:
                try:
                    params = json.loads(params_str)
                except Exception as e:
                    logger.warning(f"Failed to parse task params: {e}")
            
            video_path = params.get("video_path", "dummy.mp4")
            original_text = params.get("original_text", "Original Hook Text")
            improved_text = params.get("improved_text", "Improved Hook Text")
            preview_type = params.get("preview_type", "screenshot")
            timestamp = params.get("timestamp", 2.5)
            
            if preview_type == "screenshot":
                result = await self.generate_screenshot_preview(
                    video_path=video_path,
                    original_text=original_text,
                    improved_text=improved_text,
                    timestamp=timestamp
                )
            else:
                result = await self.generate_video_preview(
                    video_path=video_path,
                    original_text=original_text,
                    improved_text=improved_text,
                    task_id=task_id
                )
                
            if not result.success:
                raise RuntimeError(f"Preview generation failed: {result.message}")
                
            result_data = {
                "success": result.success,
                "message": result.message,
                "preview_type": preview_type,
            }
            
            if preview_type == "screenshot":
                output_path = self.output_dir / f"comparison_{task_id}.png"
                if result.comparison_image:
                    img_data = base64.b64decode(result.comparison_image)
                    output_path.write_bytes(img_data)
                    val_result = self.validate_preview_image(str(output_path))
                    result_data.update(val_result)
            else:
                result_data.update({
                    "before_video_path": result.before_video_path,
                    "after_video_path": result.after_video_path
                })
                
            return json.dumps(result_data)
            
        except Exception as e:
            logger.error(f"Failed in resolve_hook_preview_task for task {task_id}: {e}")
            raise e
        finally:
            conn.close()

    def _escape_ffmpeg_text(self, text: str) -> str:
        '''FFmpeg用にテキストをエスケープ'''
        text = text.replace("\\", "\\\\")
        text = text.replace("'", "\\'")
        text = text.replace(":", "\\:")
        text = text.replace("%", "%%")
        return text
    
    def _encode_image(self, image_path: Path) -> Optional[str]:
        '''画像をBase64エンコード'''
        try:
            if image_path.exists():
                with open(image_path, "rb") as f:
                    return base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            logger.error(f"Failed to encode image {image_path}: {e}")
        return None


# シングルトンインスタンス
hook_preview_generator = HookPreviewGenerator()
