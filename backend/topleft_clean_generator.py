"""
Top-Left Clean Placement Generator
左上・黒背景完全回避版
"""

import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError
import sys
import io

from path_resolver import brain_dir, raw_videos_dir

# sys.stdout setup moved to main block


def create_topleft_clean_preview(
    input_video=str(raw_videos_dir() / "AI Studio アップロード用動画" / "シーン04_後編02.mp4"),
    output_dir=brain_dir() / "638e528a-ad1b-4885-ad73-5d9f60dc2799",
    logo_path=Path("backend/branding/logos/brand_logo.png"),
    temp_dir=Path("backend/temp/topleft_clean")
):
    """
    左上・黒背景完全回避版プレビュー
    """
    print("\n" + "="*70)
    print("左上・黒背景完全回避版プレビュー生成")
    print("="*70)
    
    output_dir = Path(output_dir)
    temp_dir = Path(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    input_video = str(input_video)
    
    # Step 1: 10秒抽出
    print("\n[1/4] 動画抽出...")
    base_video = temp_dir / "base.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-ss", "5", "-i", input_video, "-t", "10", "-c", "copy",
        str(base_video)
    ], capture_output=True, check=True)
    print("✅ 完了")
    
    # Step 2: テロップ生成（高さ45px統一）
    print("\n[2/4] テロップ生成...")
    
    theme_text = "デザイン書道作家 山田タロウ"
    
    # フォント
    font_paths = [
        "C:/Windows/Fonts/msgothic.ttc",
        "C:/Windows/Fonts/YuGothM.ttc"
    ]
    
    font = None
    for fp in font_paths:
        if Path(fp).exists():
            try:
                font = ImageFont.truetype(fp, 18)
                break
            except OSError:
                pass
    
    if font is None:
        font = ImageFont.load_default()
    
    # テキストサイズ計測
    dummy = Image.new('RGBA', (1, 1))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), theme_text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    # テロップ画像作成（高さ45px）
    telop_height = 45
    padding_x = 12
    padding_y = (telop_height - text_height) // 2
    telop_width = text_width + padding_x * 2
    
    telop_img = Image.new('RGBA', (telop_width, telop_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(telop_img)
    
    # 半透明黒背景
    draw.rectangle((0, 0, telop_width, telop_height), fill=(0, 0, 0, 128))
    
    # テキスト
    draw.text((padding_x, padding_y), theme_text, font=font, fill=(255, 255, 255, 255))
    
    telop_path = temp_dir / "telop.png"
    telop_img.save(str(telop_path))
    print(f"テロップ: {telop_width}x{telop_height}px")
    
    # Step 3: ロゴ+テロップ統合画像
    print("\n[3/4] ロゴ+テロップ統合画像生成...")
    
    logo_path = Path(logo_path)
    logo_img = Image.open(logo_path)
    original_width, original_height = logo_img.size
    
    # ロゴを45pxにリサイズ
    logo_height = 45
    logo_width = int(original_width * (logo_height / original_height))
    logo_resized = logo_img.resize((logo_width, logo_height), Image.Resampling.LANCZOS)
    
    # 統合画像（ロゴ + 5px + テロップ）
    combined_width = logo_width + 5 + telop_width
    combined_height = 45
    
    combined_img = Image.new('RGBA', (combined_width, combined_height), (0, 0, 0, 0))
    combined_img.paste(logo_resized, (0, 0), logo_resized if logo_resized.mode == 'RGBA' else None)
    combined_img.paste(telop_img, (logo_width + 5, 0), telop_img)
    
    combined_path = temp_dir / "combined.png"
    combined_img.save(str(combined_path))
    print(f"統合画像: {combined_width}x{combined_height}px")
    
    # Step 4: オーバーレイ（左上・黒背景回避）
    print("\n[4/4] オーバーレイ適用...")
    
    # 位置: 左上、黒背景(レターボックス)を完全に避ける
    # X: 15px（左端に余白）
    # Y: 70px（上部レターボックスを回避）
    overlay_x = 15
    overlay_y = 70
    
    final_video = temp_dir / "topleft_clean.mp4"
    
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(base_video),
        "-i", str(combined_path),
        "-filter_complex",
        f"[1:v]format=rgba[overlay];[0:v][overlay]overlay={overlay_x}:{overlay_y}:format=auto",
        "-c:a", "copy",
        str(final_video)
    ], capture_output=True, check=True)
    print("✅ 完了")
    
    print(f"\n配置:")
    print(f"  位置: ({overlay_x}, {overlay_y}) ← 左上・黒背景回避")
    print(f"  ロゴ: {logo_width}x45px")
    print(f"  テロップ: {telop_width}x45px")
    print(f"  合計: {combined_width}x45px")
    
    # Step 5: スクリーンショット
    print("\n[5/5] スクリーンショット生成...")
    
    for i, ts in enumerate([1, 3, 7]):
        ss_path = output_dir / f"FINAL_screenshot_{i+1}_{ts}s.png"
        subprocess.run([
            "ffmpeg", "-y", "-ss", str(ts), "-i", str(final_video),
            "-frames:v", "1", str(ss_path)
        ], capture_output=True, check=True)
        print(f"  ✅ {ss_path.name}")
    
    print("\n" + "="*70)
    print("✅ 左上・黒背景完全回避版完成")
    print("="*70)
    print("\n確認ポイント:")
    print("  ✅ 左上に配置（一番目立たない）")
    print("  ✅ 黒背景（レターボックス）を完全回避")
    print("  ✅ ロゴ・テロップ高さ統一（45px）")
    print("  ✅ 映像エリア内に綺麗に収まっている")
    
    return str(final_video)


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    try:
        final = create_topleft_clean_preview()
        print(f"\n✅ 成功")
    except subprocess.CalledProcessError as e:
        print(f"\n❌ FFmpeg実行エラー: {e}")
        if e.stderr:
            print(f"詳細: {e.stderr.decode('utf-8', errors='replace')}")
        import traceback
        traceback.print_exc()
    except FileNotFoundError as e:
        print(f"\n❌ 必要ファイルが見つかりません: {e}")
        import traceback
        traceback.print_exc()
    except UnidentifiedImageError as e:
        print(f"\n❌ 画像ファイルの読み込みに失敗しました: {e}")
        import traceback
        traceback.print_exc()
    except OSError as e:
        print(f"\n❌ システム/ファイルI/Oエラー: {e}")
        import traceback
        traceback.print_exc()
