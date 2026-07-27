"""
PreviewWorker — プレビュー生成ステージ

SmartCut選定済みセグメントから動画プレビューを生成。
"""

import logging
import time
from pathlib import Path
from datetime import datetime

from agents.pipeline_types import PipelineStageWorker, PipelineContext, StageResult

logger = logging.getLogger(__name__)


class PreviewWorker(PipelineStageWorker):
    def __init__(self):
        super().__init__("プレビュー生成", "🎬", 3)

    def get_definition_of_done(self) -> str:
        return "プレビューファイルが生成され、サイズが1KB以上であること"

    async def execute(self, ctx: PipelineContext) -> StageResult:
        """プレビュー動画を生成

        入力契約:
            ctx.selected_segments: list[dict] — 必須。SmartCut選定済みセグメント
            ctx.video_path: str — 必須。元動画ファイルパス
        出力契約:
            ctx.preview_path: str — 生成されたプレビューファイルパス
        """
        start = time.time()

        # 1. ctx 型/存在チェック
        if ctx is None:
            return StageResult(
                stage_name=self.name, success=False,
                detail="PipelineContext が None です",
                duration_seconds=round(time.time() - start, 1),
            )

        # 2. video_path の存在と妥当性チェック
        if not hasattr(ctx, "video_path") or not ctx.video_path:
            return StageResult(
                stage_name=self.name, success=False,
                detail="video_path が指定されていません",
                duration_seconds=round(time.time() - start, 1),
            )
        if not isinstance(ctx.video_path, (str, Path)):
            return StageResult(
                stage_name=self.name, success=False,
                detail=f"video_path の型が不正です: {type(ctx.video_path)}",
                duration_seconds=round(time.time() - start, 1),
            )

        video_path_obj = Path(ctx.video_path)
        if not video_path_obj.exists() or not video_path_obj.is_file():
            return StageResult(
                stage_name=self.name, success=False,
                detail=f"元動画ファイルが存在しません: {ctx.video_path}",
                duration_seconds=round(time.time() - start, 1),
            )

        # 3. selected_segments および segments の型・整合性チェック
        if not hasattr(ctx, "selected_segments"):
            ctx.selected_segments = None
        if not hasattr(ctx, "segments"):
            ctx.segments = None

        # T-020: selected_segments 空時のフォールバック
        if not ctx.selected_segments:
            if ctx.segments:
                logger.warning("⚠️ [T-020] selected_segments 空 — 全segments でフォールバック")
                ctx.selected_segments = ctx.segments
            else:
                return StageResult(
                    stage_name=self.name, success=False,
                    detail="セグメントなし — プレビュー生成不可",
                    duration_seconds=round(time.time() - start, 1),
                )

        if not isinstance(ctx.selected_segments, list):
            return StageResult(
                stage_name=self.name, success=False,
                detail=f"selected_segments の型が不正です: {type(ctx.selected_segments)}",
                duration_seconds=round(time.time() - start, 1),
            )



        # セグメントデータ構造 of dict の簡易妥当性検証
        for idx, seg in enumerate(ctx.selected_segments):
            if not isinstance(seg, dict):
                return StageResult(
                    stage_name=self.name, success=False,
                    detail=f"セグメントインデックス {idx} が辞書ではありません: {type(seg)}",
                    duration_seconds=round(time.time() - start, 1),
                )

        try:
            from smart_cut_engine import render_smart_cut
            from safe_io import VAULT_OUTPUTS_DIR

            preview_dir = VAULT_OUTPUTS_DIR / "preview"
            preview_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            preview_path = str(preview_dir / f"preview_{ts}.mp4")

            success = render_smart_cut(ctx.selected_segments, ctx.video_path, preview_path)
            if success and Path(preview_path).exists() and Path(preview_path).stat().st_size >= 1024:
                size_mb = Path(preview_path).stat().st_size / 1024 / 1024
                ctx.preview_path = preview_path
                return StageResult(
                    stage_name=self.name, success=True,
                    detail=f"プレビュー生成完了 ({size_mb:.1f}MB)",
                    data={"path": preview_path, "size_mb": round(size_mb, 1)},
                    duration_seconds=round(time.time() - start, 1),
                )
        except ImportError as e:
            logger.error(f"❌ プレビュー生成インポートエラー (smart_cut_engine): {e}", exc_info=True)
            return StageResult(
                stage_name=self.name, success=False,
                detail=f"インポートエラー: {e}", duration_seconds=round(time.time() - start, 1),
            )
        except OSError as e:
            logger.error(f"❌ プレビュー生成システム/ファイルI/Oエラー: {e}", exc_info=True)
            return StageResult(
                stage_name=self.name, success=False,
                detail=f"システムエラー: {e}", duration_seconds=round(time.time() - start, 1),
            )
        except Exception as e:
            logger.error(f"❌ プレビュー生成例外: {e}", exc_info=True)
            return StageResult(
                stage_name=self.name, success=False,
                detail=str(e), duration_seconds=round(time.time() - start, 1),
            )

        return StageResult(
            stage_name=self.name, success=False,
            detail="プレビュー生成失敗", duration_seconds=round(time.time() - start, 1),
        )

    def verify(self, result: StageResult) -> bool:
        path = result.data.get("path")
        return result.success and path and Path(path).exists()

    def generate_thumbnail(
        self,
        output_path,
        width: int = 1280,
        height: int = 720,
        text: str = "Thumbnail",
        draw_arrow: bool = False,
        draw_circle: bool = False,
        use_banner: bool = True
    ):
        """PillowとNumPyを使用して、指定された解像度とテキストで高品質サムネイル画像を生成する"""
        import os
        import uuid
        import shutil
        import time
        import numpy as np
        from PIL import Image, ImageDraw, ImageFont

        if not output_path:
            raise ValueError("Output path must not be empty or None")

        output_path = Path(output_path)
        if output_path.is_dir():
            raise ValueError(f"Output path must be a file path, not a directory: {output_path}")

        # 対応拡張子の検証を早期に行う
        ext = output_path.suffix.lower()
        if ext not in [".png", ".jpg", ".jpeg"]:
            raise ValueError(f"Unsupported file format: {ext}. Only PNG, JPG, and JPEG are supported.")

        try:
            width = int(width)
            height = int(height)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Width and height must be integers or numeric types convertible to integer: {e}")
            
        if width <= 0 or height <= 0:
            raise ValueError(f"Width and height must be positive integers. Got width={width}, height={height}")
            
        if width < 1280 or height < 720:
            raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")

        # 8K解像度(7680x4320)を超える極端なサイズを制限（OutOfMemory防止）
        if width > 7680 or height > 4320:
            raise ValueError(f"Resolution exceeds maximum limit of 8K (7680x4320). Got {width}x{height}")
            
        aspect_ratio = width / height
        target_ratio = 16.0 / 9.0
        if abs(aspect_ratio - target_ratio) > 0.01:
            raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")
            
        # 親ディレクトリの存在と書き込み権限の事前チェック
        parent_dir = output_path.parent
        try:
            parent_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create directory for thumbnail: {parent_dir}. Error: {e}")
            raise IOError(f"Cannot write thumbnail to {output_path}. Cannot create parent directory: {parent_dir}. Error: {e}")

        if not parent_dir.exists():
            raise IOError(f"Parent directory does not exist after creation attempt: {parent_dir}")

        if not os.access(str(parent_dir), os.W_OK):
            raise PermissionError(f"Parent directory is not writeable: {parent_dir}")
        
        # スーパサンプリング係数（巨大な解像度でのメモリ爆発とハングを防ぐため、1080pを超える場合は1に制限）
        scale = 2
        if width > 1920 or height > 1080:
            scale = 1
        ss_width = width * scale
        ss_height = height * scale

        # 原子的な書き込み (Atomic Write) の実装
        temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        img = None
        resized_img = None
        try:
            # NumPyを使用してスーパサンプリング解像度で滑らかなグラデーション背景を高速生成
            y_grid, x_grid = np.ogrid[:ss_height, :ss_width]
            factor = (x_grid / (ss_width - 1.0) + y_grid / (ss_height - 1.0)) / 2.0
            
            # 色の遷移（グラデーション）を滑らかにするため smoothstep 補間を適用
            factor = factor * factor * (3.0 - 2.0 * factor)
            
            # 中央からの距離を計算（放射状のグロー効果を追加）
            center_y, center_x = ss_height / 2.0, ss_width / 2.0
            dist_from_center = np.sqrt((x_grid - center_x)**2 + (y_grid - center_y)**2)
            max_dist = np.sqrt(center_x**2 + center_y**2)
            
            # 放射状グローも smoothstep 補間を用いてよりソフトなエッジに改善
            dist_ratio = np.clip(dist_from_center / max_dist, 0, 1)
            glow = 1.0 - (dist_ratio * dist_ratio * (3.0 - 2.0 * dist_ratio))
            
            # ガンマ 2.2 によるリニア空間への事前変換（混色時の濁りを防止し高品質化）
            color1 = np.array([25, 20, 50], dtype=np.float32)      # より深い紫 (プレミアムダーク)
            color2 = np.array([10, 55, 85], dtype=np.float32)      # より洗練されたダークブルー
            color3 = np.array([70, 35, 80], dtype=np.float32)      # アクセントのマゼンタ・パープル
            
            color1_lin = (color1 / 255.0) ** 2.2
            color2_lin = (color2 / 255.0) ** 2.2
            color3_lin = (color3 / 255.0) ** 2.2
            
            # 3色リニアブレンド
            mask = factor < 0.5
            t = np.where(mask, factor * 2.0, (factor - 0.5) * 2.0)
            
            # 各要素ごとにリニアブレンド
            r_lin = np.where(mask, color1_lin[0] + (color2_lin[0] - color1_lin[0]) * t, color2_lin[0] + (color3_lin[0] - color2_lin[0]) * t)
            g_lin = np.where(mask, color1_lin[1] + (color2_lin[1] - color1_lin[1]) * t, color2_lin[1] + (color3_lin[1] - color2_lin[1]) * t)
            b_lin = np.where(mask, color1_lin[2] + (color2_lin[2] - color1_lin[2]) * t, color2_lin[2] + (color3_lin[2] - color2_lin[2]) * t)
            
            # ゴールドの放射状グロー効果をリニア空間でブレンド
            glow_color = np.array([218, 165, 32], dtype=np.float32)
            glow_color_lin = (glow_color / 255.0) ** 2.2
            glow_strength = 0.25
            
            r_lin = r_lin + glow * glow_color_lin[0] * glow_strength
            g_lin = g_lin + glow * glow_color_lin[1] * glow_strength
            b_lin = b_lin + glow * glow_color_lin[2] * glow_strength
            
            # 品質向上(2): シネマティックビネット効果（四隅を暗くして中央を引き立てる）
            dist_sq = (x_grid - center_x) ** 2 + (y_grid - center_y) ** 2
            vignette = 1.0 - 0.35 * (dist_sq / (center_x**2 + center_y**2))
            vignette = np.clip(vignette, 0.45, 1.0)
            
            # sRGB空間（ガンマ 1/2.2）へ逆変換してビネットを乗せる
            r = (np.clip(r_lin, 0, 1) ** (1.0 / 2.2)) * 255.0 * vignette
            g = (np.clip(g_lin, 0, 1) ** (1.0 / 2.2)) * 255.0 * vignette
            b = (np.clip(b_lin, 0, 1) ** (1.0 / 2.2)) * 255.0 * vignette
            
            # バンディング低減のためのディザリング（ノイズ付与）
            dither_intensity = 0.45 if width <= 1920 else 0.25
            dither = np.random.uniform(-dither_intensity, dither_intensity, (ss_height, ss_width, 3))
            rgb = np.clip(np.stack([r, g, b], axis=-1) + dither, 0, 255).astype(np.uint8)
            img = Image.fromarray(rgb)
            
            # メモリ解放
            del y_grid, x_grid, factor, dist_ratio, glow, color1, color2, color3, color1_lin, color2_lin, color3_lin, mask, t
            del r_lin, g_lin, b_lin, glow_color, glow_color_lin, r, g, b, dither, rgb, dist_sq, vignette
            import gc
            gc.collect()
            
            # OSに依存しない強固なフォント検索・フォールバック
            font_paths = [
                # Windows
                r"C:\Windows\Fonts\msjh.ttc",    # Microsoft JhengHei
                r"C:\Windows\Fonts\msgothic.ttc", # MS Gothic
                r"C:\Windows\Fonts\meiryo.ttc",   # Meiryo
                r"C:\Windows\Fonts\yugothm.ttc",  # Yu Gothic Medium
                r"C:\Windows\Fonts\arial.ttf",    # Arial
                # macOS
                "/System/Library/Fonts/PingFang.ttc",
                "/System/Library/Fonts/Hiragino Sans GB.ttc",
                "/Library/Fonts/Arial.ttf",
                # Linux
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
                "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
                "/usr/share/fonts/fonts-japanese-gothic.ttf",
            ]
            
            font_size = max(24, int(ss_height * 0.08))
            border_margin = max(10, int(min(ss_width, ss_height) * 0.02))
            max_text_width = ss_width - (border_margin * 4)
            
            font = None
            text_w, text_h = 0, 0
            d_temp_img = Image.new("RGB", (1, 1))
            d_temp = ImageDraw.Draw(d_temp_img)
            
            # テキストの自動改行とフォーマット
            lines = text.split("\n")
            line_spacing = int(font_size * 0.15)
            
            # テキストサイズに応じた動的フォントサイズ調整（オートスケール）
            while font_size > 12:
                current_font = None
                for fp in font_paths:
                    if os.path.exists(fp):
                        try:
                            current_font = ImageFont.truetype(fp, font_size)
                            break
                        except OSError:
                            continue
                if current_font is None:
                    try:
                        current_font = ImageFont.load_default(size=font_size)
                    except TypeError:
                        current_font = ImageFont.load_default()
                
                max_w = 0
                line_heights = []
                for line in lines:
                    try:
                        bbox = d_temp.textbbox((0, 0), line, font=current_font)
                        w = bbox[2] - bbox[0]
                        h = bbox[3] - bbox[1]
                    except AttributeError:
                        if hasattr(current_font, "getsize"):
                            w, h = current_font.getsize(line)
                        else:
                            w = len(line) * (font_size * 0.6)
                            h = font_size
                    max_w = max(max_w, w)
                    line_heights.append(h)
                
                total_h = sum(line_heights) + line_spacing * (len(lines) - 1)
                
                if (max_w <= max_text_width and total_h <= ss_height * 0.6) or font_size <= 16:
                    font = current_font
                    text_w, text_h = max_w, total_h
                    break
                font_size -= 4
                line_spacing = int(font_size * 0.15)
            else:
                try:
                    font = ImageFont.load_default(size=12)
                except TypeError:
                    font = ImageFont.load_default()
                text_w = max(len(l) * 8 for l in lines)
                text_h = len(lines) * 14
                
            d_temp_img.close()
            d = ImageDraw.Draw(img)
            
            # 品質向上(3): エッジの二重線枠飾り ＋ コーナーのL字装飾（ゴールド）
            border_width = max(1, int(min(ss_width, ss_height) * 0.003))
            # 外枠
            d.rectangle(
                [border_margin, border_margin, ss_width - border_margin, ss_height - border_margin],
                outline=(255, 255, 255),
                width=border_width
            )
            # 内枠（ゴールド）
            inner_margin = border_margin + border_width + 4
            d.rectangle(
                [inner_margin, inner_margin, ss_width - inner_margin, ss_height - inner_margin],
                outline=(218, 165, 32),
                width=max(1, int(scale * 0.8))
            )
            
            # コーナー装飾（ゴールド）
            corner_len = max(10, int(min(ss_width, ss_height) * 0.04))
            d.line([(inner_margin, inner_margin), (inner_margin + corner_len, inner_margin)], fill=(218, 165, 32), width=max(2, scale))
            d.line([(inner_margin, inner_margin), (inner_margin, inner_margin + corner_len)], fill=(218, 165, 32), width=max(2, scale))
            d.line([(ss_width - inner_margin, inner_margin), (ss_width - inner_margin - corner_len, inner_margin)], fill=(218, 165, 32), width=max(2, scale))
            d.line([(ss_width - inner_margin, inner_margin), (ss_width - inner_margin, inner_margin + corner_len)], fill=(218, 165, 32), width=max(2, scale))
            d.line([(inner_margin, ss_height - inner_margin), (inner_margin + corner_len, ss_height - inner_margin)], fill=(218, 165, 32), width=max(2, scale))
            d.line([(inner_margin, ss_height - inner_margin), (inner_margin, ss_height - inner_margin - corner_len)], fill=(218, 165, 32), width=max(2, scale))
            d.line([(ss_width - inner_margin, ss_height - inner_margin), (ss_width - inner_margin - corner_len, ss_height - inner_margin)], fill=(218, 165, 32), width=max(2, scale))
            d.line([(ss_width - inner_margin, ss_height - inner_margin), (ss_width - inner_margin, ss_height - inner_margin - corner_len)], fill=(218, 165, 32), width=max(2, scale))
            
            text_x = (ss_width - text_w) // 2
            text_y = (ss_height - text_h) // 2
            
            # Glassmorphism風ダークバナー（半透明背景）の描画
            if use_banner and text:
                banner_height = int(text_h * 1.3)
                banner_y1 = text_y - (banner_height - text_h) // 2
                banner_y2 = banner_y1 + banner_height
                
                banner_box = [inner_margin + 2, banner_y1, ss_width - inner_margin - 2, banner_y2]
                radius = max(8, int(banner_height * 0.15))
                
                # 1. ぼかし背景の作成 (真のGlassmorphism効果)
                from PIL import ImageFilter
                blur_radius = 15 * scale
                rgba_img = img.convert("RGBA")
                blurred = rgba_img.filter(ImageFilter.GaussianBlur(radius=blur_radius))
                
                mask = Image.new("L", img.size, 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.rounded_rectangle(banner_box, radius=radius, fill=255)
                
                glass_bg = Image.composite(blurred, rgba_img, mask)
                blurred.close()
                rgba_img.close()
                mask.close()
                
                # 2. 半透明のダークオーバレイとゴールドの枠線を重ねる
                overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
                overlay_draw = ImageDraw.Draw(overlay)
                
                # プレミアム感を出すためグラデーション風塗りつぶしとハイライト
                overlay_draw.rounded_rectangle(
                    banner_box,
                    radius=radius,
                    fill=(8, 8, 12, 140), # やや濃い目のネイビーダークで可読性を担保
                    outline=(218, 165, 32, 200),
                    width=max(2, int(scale * 1.5))
                )
                
                # 上部境界に極細のホワイトハイライト線を乗せ、Glassらしさを強調
                highlight_box = [banner_box[0] + 2, banner_box[1] + 1, banner_box[2] - 2, banner_box[1] + max(2, int(scale * 0.8))]
                overlay_draw.rounded_rectangle(highlight_box, radius=radius-1, fill=(255, 255, 255, 50))
                
                img = Image.alpha_composite(glass_bg, overlay)
                glass_bg.close()
                overlay.close()
                
                d = ImageDraw.Draw(img)

            # 注目を集める矢印の描画
            if draw_arrow:
                from PIL import ImageFilter
                arrow_scale = 2
                arrow_w = ss_width * arrow_scale
                arrow_h = ss_height * arrow_scale
                
                pts = [
                    (int(arrow_w * 0.80), int(arrow_h * 0.20)),
                    (int(arrow_w * 0.72), int(arrow_h * 0.28)),
                    (int(arrow_w * 0.74), int(arrow_h * 0.26)),
                    (int(arrow_w * 0.66), int(arrow_h * 0.34)),
                    (int(arrow_w * 0.72), int(arrow_h * 0.32)),
                    (int(arrow_w * 0.70), int(arrow_h * 0.30)),
                ]
                
                with Image.new("RGBA", (arrow_w, arrow_h), (0, 0, 0, 0)) as arrow_shadow_layer:
                    shadow_draw = ImageDraw.Draw(arrow_shadow_layer)
                    shadow_pts = [(x + int(12 * arrow_scale), y + int(12 * arrow_scale)) for x, y in pts]
                    shadow_draw.polygon(shadow_pts, fill=(0, 0, 0, 120))
                    arrow_shadow_layer_blurred = arrow_shadow_layer.filter(ImageFilter.GaussianBlur(radius=8 * arrow_scale))
                    
                    with Image.new("RGBA", (arrow_w, arrow_h), (0, 0, 0, 0)) as arrow_layer:
                        arrow_draw = ImageDraw.Draw(arrow_layer)
                        arrow_draw.polygon(
                            pts,
                            fill=(230, 30, 30, 230),
                            outline=(255, 255, 255, 255),
                            width=max(4, 4 * arrow_scale)
                        )
                        
                        combined_arrow = Image.alpha_composite(arrow_shadow_layer_blurred, arrow_layer)
                        with combined_arrow.resize((ss_width, ss_height), Image.Resampling.LANCZOS) as resized_arrow:
                            old_img = img
                            img = Image.alpha_composite(img.convert("RGBA"), resized_arrow)
                            old_img.close()
                    arrow_shadow_layer_blurred.close()
                d = ImageDraw.Draw(img)

            # 強調サークルの描画
            if draw_circle:
                from PIL import ImageFilter
                circle_scale = 2
                circle_w = ss_width * circle_scale
                circle_h = ss_height * circle_scale
                
                cx = int(circle_w * 0.25)
                cy = int(circle_h * 0.5)
                rx = int(circle_w * 0.12)
                ry = int(circle_h * 0.22)
                
                with Image.new("RGBA", (circle_w, circle_h), (0, 0, 0, 0)) as circle_shadow_layer:
                    shadow_draw = ImageDraw.Draw(circle_shadow_layer)
                    offset_x, offset_y = int(8 * circle_scale), int(8 * circle_scale)
                    shadow_draw.ellipse(
                        [cx - rx + offset_x, cy - ry + offset_y, cx + rx + offset_x, cy + ry + offset_y],
                        outline=(0, 0, 0, 110),
                        width=max(4, int(min(circle_w, circle_h) * 0.008))
                    )
                    circle_shadow_layer_blurred = circle_shadow_layer.filter(ImageFilter.GaussianBlur(radius=6 * circle_scale))
                    
                    with Image.new("RGBA", (circle_w, circle_h), (0, 0, 0, 0)) as circle_layer:
                        circle_draw = ImageDraw.Draw(circle_layer)
                        circle_draw.ellipse(
                            [cx - rx, cy - ry, cx + rx, cy + ry],
                            outline=(255, 215, 0, 220), # ゴールドイエロー
                            width=max(4, int(min(circle_w, circle_h) * 0.008))
                        )
                        
                        combined_circle = Image.alpha_composite(circle_shadow_layer_blurred, circle_layer)
                        with combined_circle.resize((ss_width, ss_height), Image.Resampling.LANCZOS) as resized_circle:
                            old_img = img
                            img = Image.alpha_composite(img.convert("RGBA"), resized_circle)
                            old_img.close()
                    circle_shadow_layer_blurred.close()
                d = ImageDraw.Draw(img)

            # テキスト描画 (複数行対応、アウトライン & ドロップシャドウ)
            current_y = text_y
            shadow_offset = max(2, int(font_size * 0.04))
            stroke_width = max(2, int(font_size * 0.05)) if hasattr(font, "size") else 2
            
            for line in lines:
                try:
                    bbox = d.textbbox((0, 0), line, font=font)
                    line_w = bbox[2] - bbox[0]
                    line_h = bbox[3] - bbox[1]
                except AttributeError:
                    if hasattr(font, "getsize"):
                        line_w, line_h = font.getsize(line)
                    else:
                        line_w = len(line) * (font_size * 0.6)
                        line_h = font_size
                
                line_x = (ss_width - line_w) // 2
                
                # 品質向上(4): テキストシャドウ効果（オフセットずらし描画で柔らかい影を作る）
                for dx, dy, alpha in [
                    (shadow_offset, shadow_offset, 60),
                    (shadow_offset - 1, shadow_offset, 40),
                    (shadow_offset, shadow_offset - 1, 40),
                    (shadow_offset + 1, shadow_offset + 1, 20),
                ]:
                    d.text((line_x + dx, current_y + dy), line, font=font, fill=(0, 0, 0, alpha))
                
                try:
                    d.text((line_x, current_y), line, font=font, fill=(255, 250, 220),
                           stroke_width=stroke_width, stroke_fill=(15, 10, 25))
                except TypeError:
                    for dx in [-stroke_width, 0, stroke_width]:
                        for dy in [-stroke_width, 0, stroke_width]:
                            if dx != 0 or dy != 0:
                                d.text((line_x + dx, current_y + dy), line, font=font, fill=(15, 10, 25))
                    d.text((line_x, current_y), line, font=font, fill=(255, 250, 220))
                
                current_y += line_h + line_spacing
            
            if img.mode != "RGB":
                old_img = img
                img = img.convert("RGB")
                old_img.close()
            
            resized_img = img.resize((width, height), Image.Resampling.LANCZOS)
            img.close()
            img = None
            
            # エラーハンドリング・リトライ(5): 4MB未満を保証するための段階的圧縮
            max_size = 4 * 1024 * 1024
            
            if ext in [".jpg", ".jpeg"]:
                quality = 95
                while quality >= 30:
                    if temp_path.exists():
                        try:
                            temp_path.unlink()
                        except OSError:
                            pass
                    resized_img.save(temp_path, "JPEG", optimize=True, quality=quality, subsampling=0)
                    if temp_path.stat().st_size < max_size:
                        break
                    quality -= 5
                else:
                    raise ValueError("Failed to compress JPEG below 4MB even at quality 30")
            else:
                # PNGとして保存
                resized_img.save(temp_path, "PNG", optimize=True, compress_level=9)
                if temp_path.stat().st_size >= max_size:
                    logger.warning("PNG size exceeds 4MB. Retrying with quantization...")
                    if temp_path.exists():
                        try:
                            temp_path.unlink()
                        except OSError:
                            pass
                    with resized_img.quantize(colors=256) as quantized:
                        quantized.save(temp_path, "PNG", optimize=True)
                    
                    if temp_path.stat().st_size >= max_size:
                        logger.warning("Quantized PNG still exceeds 4MB. Falling back to JPEG format...")
                        if temp_path.exists():
                            try:
                                temp_path.unlink()
                            except OSError:
                                pass
                        resized_img.save(temp_path, "JPEG", optimize=True, quality=75, subsampling=0)
                        if temp_path.stat().st_size >= max_size:
                            raise ValueError(f"Failed to compress PNG below 4MB: JPEG fallback size is {temp_path.stat().st_size} bytes")
            
            resized_img.close()
            resized_img = None
            
            # 正常に保存されたらアトミックにリネーム
            success = False
            for attempt in range(5):
                try:
                    if output_path.exists():
                        output_path.unlink()
                    temp_path.rename(output_path)
                    success = True
                    break
                except OSError as e:
                    logger.warning(f"Rename attempt {attempt + 1} failed ({e}). Retrying with shutil.move...")
                    try:
                        shutil.move(str(temp_path), str(output_path))
                        success = True
                        break
                    except Exception as ex:
                        logger.error(f"shutil.move fallback failed: {ex}")
                    time.sleep(0.1)
            
            if not success:
                raise IOError(f"Failed to move temporary file {temp_path} to final destination {output_path}")

            # 生成したファイルの自己検証
            self.validate_thumbnail(output_path)

        except Exception as e:
            if img is not None:
                try:
                    img.close()
                except Exception:
                    pass
                img = None
            if resized_img is not None:
                try:
                    resized_img.close()
                except Exception:
                    pass
                resized_img = None
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            logger.error(f"Failed to generate thumbnail atomically: {e}", exc_info=True)
            raise
        finally:
            if img is not None:
                try:
                    img.close()
                except Exception:
                    pass
            if resized_img is not None:
                try:
                    resized_img.close()
                except Exception:
                    pass
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            
        return output_path

    def validate_thumbnail(self, file_path) -> dict:
        """
        サムネイル画像の品質要件を検証する
        """
        from PIL import Image, UnidentifiedImageError
        
        if not file_path:
            raise ValueError("File path must not be empty or None")
            
        file_path = Path(file_path)
        
        # サポートする画像形式（拡張子）の検証
        suffix = file_path.suffix.lower()
        if suffix not in [".png", ".jpg", ".jpeg"]:
            raise ValueError(f"Unsupported file format: {suffix}. Only PNG, JPG, and JPEG are supported.")
            
        if not file_path.exists():
            raise FileNotFoundError(f"Thumbnail file not found: {file_path}")
            
        size_bytes = file_path.stat().st_size
        if size_bytes == 0:
            raise ValueError(f"Thumbnail file is empty: {file_path}")
            
        max_size = 4 * 1024 * 1024 # 4MB
        if size_bytes >= max_size:
            raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")
            
        # ファイルヘッダー（マジックナンバー）の検証による拡張子偽装のチェック
        try:
            with open(file_path, "rb") as f_head:
                header_bytes = f_head.read(8)
            is_png_header = header_bytes.startswith(b"\x89PNG\r\n\x1a\n")
            is_jpeg_header = header_bytes.startswith(b"\xff\xd8")
            
            if suffix == ".png" and not is_png_header:
                raise ValueError("Image is corrupted or invalid format: File extension is .png but header is not PNG")
            if suffix in [".jpg", ".jpeg"] and not is_jpeg_header:
                raise ValueError("Image is corrupted or invalid format: File extension is JPEG/JPG but header is not JPEG")
        except ValueError:
            raise
        except OSError as e:
            raise ValueError(f"Failed to verify file magic number: {e}")
            
        # 1. 簡易的なverify
        try:
            with Image.open(file_path) as img:
                img.verify()
        except (SyntaxError, OSError, ValueError, UnidentifiedImageError) as e:
            raise ValueError(f"Image is corrupted or invalid format: {e}")
            
        # 2. 完全なピクセルデータのロードによる破損検知
        try:
            with Image.open(file_path) as img:
                img.load()  # ピクセルデータのロードを強制
                width, height = img.size
                img.tobytes() # ピクセルデータの読み取り整合性検証
        except (SyntaxError, OSError, ValueError, UnidentifiedImageError) as e:
            raise ValueError(f"Image is corrupted or invalid format: {e}")
            
        if width < 1280 or height < 720:
            raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
            
        if width > 7680 or height > 4320:
            raise ValueError(f"Resolution exceeds maximum limit of 8K (7680x4320). Got {width}x{height}")
            
        aspect_ratio = width / height
        target_ratio = 16.0 / 9.0
        if abs(aspect_ratio - target_ratio) > 0.01:
            raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")
            
        return {
            "path": str(file_path),
            "width": width,
            "height": height,
            "size_bytes": size_bytes
        }

    async def resolve_thumbnail_task(self, task_id: str) -> str:
        """
        StageBoundAgent の process_func として動作する非同期タスク処理。
        """
        import json
        output_dir = Path(getattr(self, "output_dir", None) or "backend/temp_thumbnails")
        output_path = output_dir / f"{task_id}.png"
        
        width = getattr(self, "width", 1280)
        height = getattr(self, "height", 720)
        text = getattr(self, "text", "Thumbnail")
        
        self.generate_thumbnail(output_path, width=width, height=height, text=text)
        result_info = self.validate_thumbnail(output_path)
        return json.dumps(result_info)
