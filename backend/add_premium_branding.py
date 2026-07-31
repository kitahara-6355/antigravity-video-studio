"""
高級感のあるフォント版：Yu Gothic Bold 20px
"""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

import os
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

from path_resolver import project_root

# ANTIGRAVITY_BASE_DIR による差し替えは project_root() の中で行う
BASE_DIR = project_root()

def create_premium_branding():
    """ロゴ + プレミアムフォントのテロップを作成"""
    base = BASE_DIR
    logo_path = base / "backend" / "branding" / "logos" / "brand_logo.png"
    output_path = _writable_path("backend/branding/premium_branding.png")
    
    # ロゴ読み込み（23x45px）
    logo = Image.open(logo_path).convert('RGBA')
    
    # テロップ作成（330x45px - 少し幅を広げてゆとりを持たせる）
    telop_text = "デザイン書道作家 山田タロウ"
    telop = Image.new('RGBA', (330, 45), (0, 0, 0, 128))
    draw = ImageDraw.Draw(telop)
    
    # 高級感のあるフォント：太字を優先。
    # 2026-07-25: Windows パス決め打ちだったため CI(Ubuntu) で
    # OSError: cannot open resource となっていた。候補リストを font_resolver に
    # 集約しつつ、truetype の呼び出しは本モジュール内に残す
    # （既存テストが ImageFont.truetype をモックしているため）。
    from font_resolver import candidate_paths
    font = None
    for _fp in candidate_paths(bold=True):
        try:
            font = ImageFont.truetype(_fp, 20)
            break
        except OSError:
            continue
    if font is None:
        raise OSError("Failed to load any premium fonts.")
    
    bbox = draw.textbbox((0, 0), telop_text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    x = (330 - text_width) // 2
    y = (45 - text_height) // 2
    
    draw.text((x, y), telop_text, font=font, fill=(255, 255, 255, 255))
    
    # 統合（ロゴ23px + 間隔5px + テロップ330px = 358px）
    combined = Image.new('RGBA', (358, 45), (0, 0, 0, 0))
    combined.paste(logo, (0, 0), logo)
    combined.paste(telop, (28, 0), telop)
    
    combined.save(output_path)
    print(f"✅ Premium branding created: {output_path}")
    print(f"   Font: Yu Gothic Bold 20px")
    return output_path

def add_premium_branding():
    """プレミアムブランディングを動画に追加"""
    base = BASE_DIR
    input_video = base / "soul_narrative_FINAL_EDITED.mp4"
    output_video = base / "soul_narrative_YOUTUBE_PREMIUM.mp4"
    
    branding_path = create_premium_branding()
    
    print("\n" + "="*70)
    print("Adding Premium Branding to Video")
    print("="*70)
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_video),
        "-i", str(branding_path),
        "-filter_complex", "[0:v][1:v] overlay=15:15",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_video)
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
    
    if result.returncode == 0 and output_video.exists():
        size_mb = output_video.stat().st_size / 1024 / 1024
        
        check_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(output_video)
        ]
        duration_result = subprocess.run(check_cmd, capture_output=True, text=True)
        duration_sec = float(duration_result.stdout.strip())
        duration_min = int(duration_sec // 60)
        duration_sec_remaining = int(duration_sec % 60)
        
        print(f"\n✅ Premium YouTube video complete!")
        print(f"   File: {output_video}")
        print(f"   Size: {size_mb:.1f} MB")
        print(f"   Duration: {duration_min}:{duration_sec_remaining:02d}")
        print(f"   Font: Yu Gothic Bold 20px (Premium)")
        
        return str(output_video)
    else:
        print(f"\n❌ Failed to add premium branding")
        print(result.stderr[-1000:] if result.stderr else "")
        return None

def generate_premium_branding_thumbnail(output_path, width=1280, height=720, text=None, preview_path=None):
    """Pillowを使用して、高品質なプレミアムブランディング（サムネイル）画像を生成する。必要に応じてプレビュー画像も生成する。"""
    from datetime import datetime
    import uuid
    import random
    import math
    import shutil

    # 引数のバリデーション強化
    if output_path is None or output_path == "":
        raise ValueError("Output path cannot be empty.")
    if not isinstance(output_path, (str, Path)):
        raise TypeError("Output path must be a string or Path object.")
    
    # Windowsの無効な文字チェック
    invalid_chars = '<>:\"|?*'
    path_str = str(output_path)
    check_str = path_str[2:] if len(path_str) > 2 and path_str[1] == ':' else path_str
    if any(c in check_str for c in invalid_chars):
        raise OSError(f"Invalid characters in path: {output_path}")

    # 拡張子制限のチェック
    suffix = Path(output_path).suffix.upper()
    if suffix not in [".PNG", ".JPG", ".JPEG"]:
        raise ValueError(f"Unsupported file format: {suffix}")

    try:
        width = int(width)
        height = int(height)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Width and height must be integers: {e}")
        
    if width <= 0 or height <= 0:
        raise ValueError("Width and height must be positive integers.")
        
    # 解像度制限のチェック (1280x720以上、3840x2160以下)
    if width < 1280 or height < 720:
        raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
    if width > 3840 or height > 2160:
        raise ValueError(f"Resolution exceeds maximum limit: {width}x{height}")
        
    # アスペクト比のチェック (16:9)
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 0.001:
        raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")
        
    # ディスク空き容量のチェック (最低10MB)
    output_path = Path(output_path)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(output_path.parent)
        free_space = getattr(usage, "free", None)
        if free_space is None:
            try:
                free_space = usage[2]
            except Exception:
                free_space = 100 * 1024 * 1024  # 安全フォールバック
        if free_space < 10 * 1024 * 1024:
            raise OSError("Insufficient disk space (less than 10MB free).")
    except Exception as e:
        if isinstance(e, (OSError, ValueError)):
            raise e
        if isinstance(e, TypeError):
            raise OSError(f"Failed to create directory structure: {e}")
        # その他の軽微な例外は無視
        
    temp_path = None
    temp_preview_path = None

    if preview_path:
        if not isinstance(preview_path, (str, Path)):
            raise TypeError("Preview path must be a string or Path object.")
        # プレビューのパスチェック
        prev_path_str = str(preview_path)
        prev_check_str = prev_path_str[2:] if len(prev_path_str) > 2 and prev_path_str[1] == ':' else prev_path_str
        if any(c in prev_check_str for c in invalid_chars):
            raise OSError(f"Invalid characters in preview path: {preview_path}")
            
        preview_path = Path(preview_path)
        try:
            preview_path.parent.mkdir(parents=True, exist_ok=True)
        except (TypeError, OSError) as e:
            raise OSError(f"Failed to create preview directory structure: {e}")

    # 高品質リサンプリングフィルタの取得
    try:
        temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        if preview_path:
            temp_preview_path = preview_path.with_suffix(f".{uuid.uuid4().hex}.tmp")

        try:
            if hasattr(Image, "Resampling"):
                LANCZOS = Image.Resampling.LANCZOS
            else:
                LANCZOS = Image.LANCZOS
        except AttributeError:
            LANCZOS = None

        # SSAA用のスケールと描画サイズの設定
        scale = 2
        draw_width = width * scale
        draw_height = height * scale

        # --- (1) 背景 of プレミアムグラデーション生成 (高品質化・ディザリング追加) ---
        grad_w, grad_h = 64, 36
        small_grad = Image.new("RGB", (grad_w, grad_h))
        rnd_grad = random.Random(42)
        for y in range(grad_h):
            for x in range(grad_w):
                t1 = x / (grad_w - 1)
                t2 = y / (grad_h - 1)
                t = (t1 + t2) / 2.0
                
                # Smoothstep easing (3t^2 - 2t^3) で色の階調変化を滑らかに
                t = t * t * (3.0 - 2.0 * t)
                
                # ディープネイビーからロイヤルブルーへのブレンド
                r = 11 * (1 - t) + 24 * t
                g = 19 * (1 - t) + 8 * t
                b = 43 * (1 - t) + 68 * t
                
                # 右下にほのかなゴールドの要素を微ブレンドしてプレミアム感を演出
                if t > 0.6:
                    w = (t - 0.6) / 0.4
                    # イージング適用でゴールドのブレンドをスムーズに
                    w = w * w * (3.0 - 2.0 * w)
                    r = r * (1 - w) + 212 * w * 0.12
                    g = g * (1 - w) + 175 * w * 0.12
                    b = b * (1 - w) + 55 * w * 0.12
                
                # 微細なディザーノイズ of 付与 (色の縞模様=バンディングを防ぎ高品質化)
                r = int(r + rnd_grad.uniform(-1.0, 1.0))
                g = int(g + rnd_grad.uniform(-1.0, 1.0))
                b = int(b + rnd_grad.uniform(-1.0, 1.0))
                
                r = max(0, min(255, r))
                g = max(0, min(255, g))
                b = max(0, min(255, b))
                
                small_grad.putpixel((x, y), (r, g, b))
        
        # 拡大してRGBAへ (BICUBICでより滑らかに拡大)
        try:
            resample_filter = Image.Resampling.BICUBIC
        except AttributeError:
            try:
                resample_filter = Image.BICUBIC
            except AttributeError:
                resample_filter = 3  # BICUBIC
        img = small_grad.resize((draw_width, draw_height), resample_filter).convert("RGBA")
        
        # --- (1.5) シネマティックヴィネット効果 (Vignette Effect) ---
        vig_w, vig_h = 64, 36
        vig_img = Image.new("RGBA", (vig_w, vig_h), (0, 0, 0, 0))
        cx, cy = vig_w / 2, vig_h / 2
        max_d = math.sqrt(cx**2 + cy**2)
        for y in range(vig_h):
            for x in range(vig_w):
                dx = x - cx
                dy = y - cy
                d = math.sqrt(dx**2 + dy**2)
                t = d / max_d
                # 非線形に外側を暗くする
                alpha = int(75 * (t ** 2.5))
                vig_img.putpixel((x, y), (0, 0, 0, alpha))
        
        vig_large = vig_img.resize((draw_width, draw_height), resample_filter)
        img = Image.alpha_composite(img, vig_large)

        # --- (2) プレミアムなグロス効果 (斜めの半透明な光沢帯) の追加 ---
        gloss_overlay = Image.new('RGBA', (draw_width, draw_height), (0, 0, 0, 0))
        gloss_draw = ImageDraw.Draw(gloss_overlay)
        
        # 1本目の幅広の極めて薄い光沢帯
        gloss_draw.polygon(
            [
                (int(draw_width * 0.18), 0),
                (int(draw_width * 0.42), 0),
                (int(draw_width * 0.22), draw_height),
                (0, draw_height)
            ],
            fill=(255, 255, 255, 10)
        )
        # 2本目のシャープでやや強めの細い光の線
        gloss_draw.polygon(
            [
                (int(draw_width * 0.45), 0),
                (int(draw_width * 0.49), 0),
                (int(draw_width * 0.29), draw_height),
                (int(draw_width * 0.25), draw_height)
            ],
            fill=(255, 255, 255, 18)
        )
        img = Image.alpha_composite(img, gloss_overlay)
        d = ImageDraw.Draw(img)
        
        # --- (3) プレミアムダブル枠線および装飾の描画 ---
        margin = 30
        # 外側のプレミアムゴールド枠線 (太さ 3px * scale, ロイヤルゴールド)
        d.rectangle(
            [margin * scale, margin * scale, draw_width - margin * scale, draw_height - margin * scale],
            outline=(212, 175, 55, 210),
            width=3 * scale
        )
        
        # ダブル枠線効果: さらに外側に薄いゴールドの細い線を描画
        d.rectangle(
            [(margin - 4) * scale, (margin - 4) * scale, draw_width - (margin - 4) * scale, draw_height - (margin - 4) * scale],
            outline=(212, 175, 55, 60),
            width=1 * scale
        )
        
        # 内枠 (マージン 38px * scale, 太さ 1px * scale, 半透明ホワイト)
        inner_margin = 38
        d.rectangle(
            [inner_margin * scale, inner_margin * scale, draw_width - inner_margin * scale, draw_height - inner_margin * scale],
            outline=(255, 255, 255, 50),
            width=1 * scale
        )
        
        # 4つのコーナーにゴールドとホワイトの輝き星を描画
        def draw_corner_star(draw_obj, cx, cy):
            color_gold = (255, 215, 0, 230)
            color_white = (255, 255, 255, 255)
            # 十字 (ゴールド)
            draw_obj.line([cx - 14 * scale, cy, cx + 14 * scale, cy], fill=color_gold, width=2 * scale)
            draw_obj.line([cx, cy - 14 * scale, cx, cy + 14 * scale], fill=color_gold, width=2 * scale)
            # 对角線 (ゴールド)
            draw_obj.line([cx - 8 * scale, cy - 8 * scale, cx + 8 * scale, cy + 8 * scale], fill=color_gold, width=1 * scale)
            draw_obj.line([cx - 8 * scale, cy + 8 * scale, cx + 8 * scale, cy - 8 * scale], fill=color_gold, width=1 * scale)
            # 中心光球 (ホワイト)
            draw_obj.ellipse([cx - 3 * scale, cy - 3 * scale, cx + 3 * scale, cy + 3 * scale], fill=color_white)
            
        draw_corner_star(d, margin * scale, margin * scale)
        draw_corner_star(d, draw_width - margin * scale, margin * scale)
        draw_corner_star(d, margin * scale, draw_height - margin * scale)
        draw_corner_star(d, draw_width - margin * scale, draw_height - margin * scale)

        # ランダムなゴールドパーティクルの追加 (円 + ひし形のバリエーション, シード固定)
        rnd = random.Random(42)
        for _ in range(20):
            px = rnd.randint((margin + 20) * scale, draw_width - (margin + 20) * scale)
            py = rnd.randint((margin + 20) * scale, draw_height - (margin + 20) * scale)
            p_type = rnd.choice(["circle", "diamond"])
            radius = rnd.randint(2 * scale, 6 * scale)
            opacity = rnd.randint(15, 70)
            
            if p_type == "circle":
                d.ellipse(
                    [px - radius, py - radius, px + radius, py + radius],
                    fill=(212, 175, 55, opacity)
                )
            else:
                d.polygon(
                    [
                        (px, py - radius),
                        (px + radius, py),
                        (px, py + radius),
                        (px - radius, py)
                    ],
                    fill=(255, 223, 0, opacity)
                )

        # 右下の装飾的なゴールドバッジ (多角形と円のプレミアム意匠)
        bx, by = draw_width - 110 * scale, draw_height - 110 * scale
        br = 50 * scale
        points = []
        for i in range(16):
            angle = i * (360 / 16) * 3.14159 / 180
            r_curr = br if i % 2 == 0 else br - 8 * scale
            # アスペクト比を微調整して綺麗な円形に見えるように
            px = bx + r_curr * 1.15
            py = by + r_curr
            points.append((px, py))
            
        d.polygon(points, fill=(212, 175, 55, 25), outline=(212, 175, 55, 100), width=1 * scale)
        d.ellipse(
            [bx - br, by - br, bx + br, by + br],
            outline=(255, 215, 0, 90),
            width=1 * scale
        )
        
        # --- (4) プレミアムブランドロゴのオーバーレイ合成 (スケール適用) ---
        logo_path = BASE_DIR / "backend" / "branding" / "logos" / "brand_logo.png"
        if logo_path.exists():
            try:
                logo = Image.open(logo_path).convert('RGBA')
                logo_w, logo_h = logo.size
                logo_scaled = logo.resize((logo_w * scale, logo_h * scale), LANCZOS if LANCZOS is not None else 3)
                img.paste(logo_scaled, ((margin + 15) * scale, (margin + 15) * scale), logo_scaled)
            except Exception as e:
                import sys
                sys.stderr.write(f"Warning: Failed to load brand logo for thumbnail: {e}\n")

        if not text:
            text = f"Premium Branding\nGenerated at: {datetime.now().isoformat()}"
            
        # 日本語フォントのプレミアムフォールバック対応
        font_paths = [
            r"C:\Windows\Fonts\YuGothB.ttc",   # Windows: Yu Gothic Bold
            r"C:\Windows\Fonts\meiryob.ttc",   # Windows: Meiryo Bold
            r"C:\Windows\Fonts\msgothic.ttc",  # Windows: MS Gothic
            "/System/Library/Fonts/PingFang.ttc", # macOS
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf", # Linux (fonts-ipafont)
            "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",  # Fedora/RHEL
            # Debian/Ubuntu の fonts-noto-cjk。GitHub Actions の ubuntu ランナーは
            # ここに入るため、この行が無いと CI でフォント解決に失敗する
            # （2026-07-25: OSError: Failed to load any premium fonts で14件失敗）
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # 最終手段（CJK非対応）
        ]
        
        # テキストの長さに応じて自動折り返し＆フォントサイズ調整
        max_text_width = draw_width - 120 * scale
        max_text_height = draw_height - 120 * scale
        
        words_or_chars = text.split('\n')
        wrapped_lines = []
        for line in words_or_chars:
            if len(line) > 30:
                sub_lines = [line[i:i+30] for i in range(0, len(line), 30)]
                wrapped_lines.extend(sub_lines)
            else:
                wrapped_lines.append(line)
                
        font_size = max(24 * scale, int(draw_height * 0.06))
        font = None
        
        while font_size >= 12 * scale:
            for fp in font_paths:
                try:
                    if Path(fp).exists():
                        font = ImageFont.truetype(fp, font_size)
                        break
                except (OSError, ValueError):
                    continue
            if font is None:
                try:
                    font = ImageFont.load_default()
                except (OSError, ValueError):
                    font = None
                    break
            
            line_height = int(font_size * 1.3)
            total_text_height = len(wrapped_lines) * line_height
            
            max_line_w = 0
            for line in wrapped_lines:
                try:
                    bbox = d.textbbox((0, 0), line, font=font)
                    w = bbox[2] - bbox[0]
                    if w > max_line_w:
                        max_line_w = w
                except (OSError, ValueError):
                    max_line_w = len(line) * font_size
                    
            if max_line_w <= max_text_width and total_text_height <= max_text_height:
                break
            
            font_size -= 2 * scale
            
        start_y = (draw_height - (len(wrapped_lines) * int(font_size * 1.3))) // 2
        for i, line in enumerate(wrapped_lines):
            y_pos = start_y + i * int(font_size * 1.3)
            
            # フォントサイズに応じた適切なストローク幅の計算
            stroke_w = max(1 * scale, int(font_size * 0.05))
            
            # 12方向アウターグロー効果 (深い影色で文字輪郭を際立たせる、半径別で重ねて滑らかにする)
            glow_radius = max(1 * scale, int(font_size * 0.04))
            for r_offset in range(glow_radius, 0, -scale):
                alpha = int(180 * (1.0 - (r_offset - scale) / glow_radius)) # 外側ほど薄く
                for angle in range(0, 360, 30): # 12方向
                    rad = math.radians(angle)
                    dx = int(round(math.cos(rad) * r_offset))
                    dy = int(round(math.sin(rad) * r_offset))
                    d.text((60 * scale + dx, y_pos + dy), line, fill=(0, 0, 0, alpha), font=font)
            
            # メインテキスト (少し温かみのあるアイボリーホワイトとゴールドの調和)
            d.text((60 * scale, y_pos), line, fill=(255, 250, 240, 255), font=font, stroke_width=stroke_w, stroke_fill=(20, 10, 5, 255))
            
        # SSAA: LANCZOSフィルタを使用してターゲット解像度に縮小し、RGBに変換して保存
        img_rgb = img.convert("RGB")
        if LANCZOS is not None:
            final_img = img_rgb.resize((width, height), LANCZOS)
        else:
            final_img = img_rgb.resize((width, height), Image.Resampling.BILINEAR if hasattr(Image, "Resampling") else 2)
            
        out_suffix = Path(output_path).suffix.upper()
        if out_suffix in [".JPG", ".JPEG"]:
            final_img.save(temp_path, "JPEG", quality=95, subsampling=0)
        else:
            final_img.save(temp_path, "PNG", optimize=True, compress_level=9)
        
        if output_path.exists():
            try:
                output_path.unlink()
            except OSError:
                pass
        temp_path.rename(output_path)
        
        # プレビュー画像の生成 (高品質リサイズ)
        if preview_path and temp_preview_path:
            preview_w = 640
            preview_h = 360
            
            if LANCZOS is not None:
                preview_img = final_img.resize((preview_w, preview_h), LANCZOS)
            else:
                try:
                    preview_img = final_img.resize((preview_w, preview_h), Image.Resampling.BILINEAR)
                except AttributeError:
                    preview_img = final_img.resize((preview_w, preview_h), 2)  # BILINEAR
                
            prev_suffix = Path(preview_path).suffix.upper()
            if prev_suffix in [".JPG", ".JPEG"]:
                preview_img.save(temp_preview_path, "JPEG", quality=95, subsampling=0)
            else:
                preview_img.save(temp_preview_path, "PNG", optimize=True, compress_level=9)
            
            if preview_path.exists():
                try:
                    preview_path.unlink()
                except OSError:
                    pass
            temp_preview_path.rename(preview_path)
            
    except BaseException as e:
        # すべての例外(BaseExceptionを含む)発生時に、作成された一時ファイルを確実にクリーンアップする
        import sys
        import traceback
        sys.stderr.write(f"ERROR [generate_premium_branding_thumbnail] Failed to generate thumbnail: {str(e)}\n")
        sys.stderr.write(traceback.format_exc())
        for tp in [temp_path, temp_preview_path]:
            if tp and isinstance(tp, Path) and tp.exists():
                try:
                    tp.unlink()
                except OSError as ue:
                    sys.stderr.write(f"WARNING: Failed to cleanup temp file {tp}: {ue}\n")
        raise e
    return output_path

def validate_thumbnail(file_path, is_preview=False) -> dict:
    """サムネイル画像の品質要件を検証する"""
    if file_path is None or file_path == "":
        raise ValueError("File path cannot be empty.")
    if not isinstance(file_path, (str, Path)):
        raise TypeError("File path must be a string or Path object.")
        
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Thumbnail file not found: {file_path}")
    if not file_path.is_file():
        raise ValueError(f"Target path is not a file: {file_path}")
        
    size_bytes = file_path.stat().st_size
    if size_bytes >= 4 * 1024 * 1024:
        raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")
        
    # 1. 簡易的なverify
    try:
        with Image.open(file_path) as img:
            img.verify()
    except (OSError, ValueError, SyntaxError) as e:
        raise ValueError(f"Image is corrupted or invalid format: {e}")
        
    # 2. 完全なピクセルデータのロードによる破損検知および品質（単一色でないか）の検証用データ取得
    try:
        with Image.open(file_path) as img:
            img.load()  # ピクセルデータのロードを強制
            width, height = img.size
            format_name = img.format
            
            # 品質検証用データ
            rgb_img = img.convert("RGB")
            extrema = rgb_img.getextrema()
    except (OSError, ValueError, SyntaxError) as e:
        raise ValueError(f"Image is corrupted or invalid format: {e}")
        
    if is_preview:
        if width < 320 or height < 180:
            raise ValueError(f"Preview resolution must be at least 320x180. Got {width}x{height}")
    else:
        if width < 1280 or height < 720:
            raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
        
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 0.001:
        raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")
        
    # 品質検証: すべて同色（真っ黒など）になっていないかチェック
    is_single_color = all(min_val == max_val for min_val, max_val in extrema)
    if is_single_color:
        raise ValueError("Image is a single solid color (possible generation failure).")
        
    return {
        "path": str(file_path),
        "width": width,
        "height": height,
        "size_bytes": size_bytes,
        "format": format_name
    }

async def resolve_premium_branding_task(task_id: str, agent=None) -> str:
    """StageBoundAgent の process_func として動作する非同期タスク処理"""
    import json
    import sys
    import traceback
    
    output_dir_path = Path("backend/temp_thumbnails")
    width = 1280
    height = 720
    text = f"Premium Branding Task: {task_id}"
    
    if agent is not None:
        if hasattr(agent, "output_dir") and agent.output_dir:
            output_dir_path = Path(agent.output_dir)
        if hasattr(agent, "resolution") and agent.resolution:
            try:
                w, h = map(int, agent.resolution.split("x"))
                width = w
                height = h
            except Exception:
                pass
        if hasattr(agent, "width") and agent.width:
            width = agent.width
        if hasattr(agent, "height") and agent.height:
            height = agent.height
        if hasattr(agent, "text") and agent.text:
            text = agent.text
            
    output_path = output_dir_path / f"{task_id}.png"
    preview_path = output_dir_path / f"{task_id}_preview.png"
    
    try:
        generate_premium_branding_thumbnail(output_path, width=width, height=height, text=text, preview_path=preview_path)
        result_info = validate_thumbnail(output_path)
        
        if preview_path.exists():
            preview_info = validate_thumbnail(preview_path, is_preview=True)
            result_info["preview"] = preview_info
            
        return json.dumps(result_info)
    except Exception as e:
        # TDR規約(TD-1009等)に適合するため、例外のログ出力と再レイズを実行
        sys.stderr.write(f"CRITICAL [StageBoundAgent:{task_id}] Task processing failed: {str(e)}\n")
        sys.stderr.write(traceback.format_exc())
        raise e

if __name__ == "__main__":
    import time
    start = time.time()
    
    video_path = add_premium_branding()
    
    elapsed = time.time() - start
    
    print("\n" + "="*70)
    print(f"Processing complete: {elapsed / 60:.1f} minutes")
    print("="*70)
    
    if video_path:
        print("\n🚀 Premium Version Ready for YouTube Upload!")
        print("\nFiles:")
        print(f"  Video: {video_path}")
        print(f"  SRT: {BASE_DIR / 'soul_narrative_combined.srt'}")
        print("\nFont Specs:")
        print("  Font: Yu Gothic Bold")
        print("  Size: 20px")
        print("  Color: White (#FFFFFF)")
    else:
        print("\n❌ Failed")
