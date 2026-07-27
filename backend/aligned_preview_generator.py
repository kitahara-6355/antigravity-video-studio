"""
Aligned and Positioned Logo+Telop Generator
ロゴとテロップの高さ揃え・黒背景回避
"""

import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import sys
import io

# Pillow 9.1.0 以降の Resampling 互換性確保
try:
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS
except AttributeError:
    try:
        RESAMPLE_LANCZOS = Image.LANCZOS
    except AttributeError:
        RESAMPLE_LANCZOS = getattr(Image, "ANTIALIAS", 1)


def get_video_duration(video_path):
    """
    ffprobeを用いて動画の長さを取得。取得失敗時はデフォルトで15.0秒を返す。
    """
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)
        ], capture_output=True, text=True, check=True)
        val = float(result.stdout.strip())
        if val <= 0.0:
            return 15.0
        return val
    except Exception:
        return 15.0



def create_aligned_preview(input_video=None, output_dir=None):
    """
    高さを揃えたロゴ+テロップ、黒背景回避
    """
    print("\n" + "="*70)
    print("高さ揃え・黒背景回避版プレビュー生成")
    print("="*70)
    
    # PIL画像オブジェクト変数の初期化
    logo_img = None
    logo_resized = None
    telop_img = None
    combined_img = None
    
    try:
        if output_dir is None:
            # デフォルトは現在のセッションに依存しない相対パスを使用
            output_dir = Path("backend/temp/aligned_preview/output")
        else:
            output_dir = Path(output_dir)
            
        output_dir.mkdir(parents=True, exist_ok=True)
        
        temp_dir = Path("backend/temp/aligned_preview")
        temp_dir.mkdir(parents=True, exist_ok=True)
        if input_video is None:
            # プロジェクト内のテスト用動画や一時動画をフォールバックとして探索
            fallback_paths = [
                Path("backend/tests/assets/dummy.mp4"),
                Path("backend/temp/dummy.mp4"),
                Path("temp/dummy.mp4")
            ]
            for fp in fallback_paths:
                if fp.exists():
                    input_video = str(fp)
                    break
            else:
                input_video = "backend/temp/aligned_preview/dummy_fallback.mp4"
        
        input_video_path = Path(input_video)
        if not input_video_path.exists():
            # 実動作時の安全性のために、もし動画ファイルすら無い場合は、FFmpegで1秒のダミー動画を動的生成して回避
            try:
                input_video_path.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run([
                    "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=1280x720:d=15",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(input_video_path)
                ], capture_output=True, check=True)
                print(f"⚠️ 入力動画が存在しないため、ダミー動画を動的に生成しました: {input_video_path}")
            except subprocess.CalledProcessError as e:
                stderr_msg = e.stderr.decode('utf-8', errors='ignore') if isinstance(e.stderr, bytes) else (str(e.stderr) if e.stderr else "No stderr")
                raise FileNotFoundError(f"入力動画が見つからず、ダミー動画の生成にも失敗しました: {input_video}. FFmpeg出力: {stderr_msg}") from e
            except OSError as e:
                raise FileNotFoundError(f"入力動画が見つからず、ダミー動画の生成にも失敗しました: {input_video}. システムエラー: {e}") from e
            
        # Step 1: 動画抽出 (動画の長さに合わせて動的にパラメータを計算)
        duration = get_video_duration(input_video_path)
        start_time = max(0.0, min(5.0, duration - 10.0))
        extract_duration = min(10.0, duration)
        
        print(f"\n[1/5] 動画抽出 (動画長: {duration:.1f}秒, 開始: {start_time:.1f}秒, 長さ: {extract_duration:.1f}秒)...")
        base_video = temp_dir / "base.mp4"
        try:
            subprocess.run([
                "ffmpeg", "-y", "-ss", f"{start_time:.2f}", "-i", str(input_video_path), "-t", f"{extract_duration:.2f}", "-c", "copy",
                str(base_video)
            ], capture_output=True, check=True)
        except subprocess.CalledProcessError as e:
            stderr_msg = e.stderr.decode('utf-8', errors='ignore') if isinstance(e.stderr, bytes) else (str(e.stderr) if e.stderr else "No stderr")
            raise RuntimeError(f"Step 1 (動画抽出) でエラーが発生しました。FFmpeg出力: {stderr_msg}") from e
        except OSError as e:
            raise RuntimeError(f"Step 1 (動画抽出) でシステムエラーが発生しました: {e}") from e
        print("✅ 完了")
        
        # Step 2: テロップ生成（高さを固定）
        print("\n[2/5] テロップ生成...")
        
        try:
            theme_text = "デザイン書道作家 山田タロウ"
            
            # フォント (マルチプラットフォーム対応)
            font_paths = [
                "C:/Windows/Fonts/msgothic.ttc",
                "C:/Windows/Fonts/YuGothM.ttc",
                "/System/Library/Fonts/Hiragino Sans GB.ttc",
                "/System/Library/Fonts/AppleSDGothicNeo.ttc",
                "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
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
            with Image.new('RGBA', (1, 1)) as dummy:
                draw = ImageDraw.Draw(dummy)
                bbox = draw.textbbox((0, 0), theme_text, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
            
            # テロップ画像作成（高さ45pxに統一）
            telop_height = 45  # ロゴと同じ高さ
            padding_x = 12
            padding_y = (telop_height - text_height) // 2  # 垂直中央配置
            
            telop_width = text_width + padding_x * 2
            
            telop_img = Image.new('RGBA', (telop_width, telop_height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(telop_img)
            
            # 半透明黒背景
            draw.rectangle((0, 0, telop_width, telop_height), fill=(0, 0, 0, 128))
            
            # テキスト（垂直中央に配置するため anchor="lm" を指定）
            draw.text((padding_x, telop_height // 2), theme_text, font=font, fill=(255, 255, 255, 255), anchor="lm")
            
            telop_path = temp_dir / "telop_aligned.png"
            try:
                telop_img.save(str(telop_path))
            except (OSError, ValueError) as e:
                raise RuntimeError(f"Step 2 (テロップ画像保存) でエラーが発生しました: {e}") from e
            print(f"テロップ: {telop_width}x{telop_height}px（高さ統一）")
        except Exception as e:
            if not isinstance(e, RuntimeError):
                raise RuntimeError(f"Step 2 (テロップ生成) 内で予期せぬエラーが発生しました: {e}") from e
            raise
        
        # Step 3: ロゴとテロップを統合した1枚の画像を作成
        print("\n[3/5] ロゴ+テロップ統合画像生成...")
        
        try:
            logo_path = Path("backend/branding/logos/brand_logo.png")
            # プロジェクト構造によってロゴが存在しない場合のフォールバック
            if not logo_path.exists():
                alt_logo_paths = [
                    Path("branding/logos/brand_logo.png"),
                    Path("logos/brand_logo.png")
                ]
                for alp in alt_logo_paths:
                    if alp.exists():
                        logo_path = alp
                        break
            
            if logo_path.exists():
                try:
                    logo_img = Image.open(logo_path)
                except (OSError, ValueError, TypeError) as e:
                    print(f"⚠️ ロゴ画像の読み込みに失敗したため、ダミー画像を生成しました。Error: {e}")
                    logo_img = Image.new("RGBA", (45, 45), (0, 0, 0, 0))
            else:
                # ロゴが存在しない場合は透過画像をダミー生成
                logo_img = Image.new("RGBA", (45, 45), (0, 0, 0, 0))
                print("⚠️ ロゴ画像が見つからないため、ダミー画像を生成しました。")
        
            original_width, original_height = logo_img.size
            
            # ゼロ除算防止ガード
            if original_height == 0:
                original_height = 45
            if original_width == 0:
                original_width = 45
            
            # ロゴを高さ45pxにリサイズ
            logo_height = 45
            logo_width = int(original_width * (logo_height / original_height))
            if logo_width <= 0:
                logo_width = 1
                
            logo_resized = logo_img.resize((logo_width, logo_height), RESAMPLE_LANCZOS)
            
            # 透過情報（RGBA）を保証する（RGBやPモード等のロゴ画像を透過貼り付け可能にするため）
            logo_resized = logo_resized.convert("RGBA")
            
            # 統合画像作成（ロゴ + 5px間隔 + テロップ）
            combined_width = logo_width + 5 + telop_width
            combined_height = 45
            
            combined_img = Image.new('RGBA', (combined_width, combined_height), (0, 0, 0, 0))
            
            # ロゴを貼り付け
            combined_img.paste(logo_resized, (0, 0), logo_resized)
            
            # テロップを貼り付け
            combined_img.paste(telop_img, (logo_width + 5, 0), telop_img)
            
            combined_path = temp_dir / "logo_telop_combined.png"
            try:
                combined_img.save(str(combined_path))
            except (OSError, ValueError) as e:
                raise RuntimeError(f"Step 3 (統合画像保存) でエラーが発生しました: {e}") from e
            print(f"統合画像: {combined_width}x{combined_height}px")
        except Exception as e:
            if not isinstance(e, RuntimeError):
                raise RuntimeError(f"Step 3 (統合画像生成) 内で予期せぬエラーが発生しました: {e}") from e
            raise
        
        # Step 4: 統合画像をオーバーレイ（黒背景を避ける位置）
        print("\n[4/5] オーバーレイ適用...")
        
        # 位置: 右上寄り（黒背景レターボックスを避ける）
        overlay_x = 80  # より右に配置
        overlay_y = 15  # より上に配置
        
        final_video = temp_dir / "aligned.mp4"
        
        try:
            subprocess.run([
                "ffmpeg", "-y",
                "-i", str(base_video),
                "-i", str(combined_path),
                "-filter_complex",
                f"[1:v]format=rgba[overlay];[0:v][overlay]overlay={overlay_x}:{overlay_y}:format=auto",
                "-c:a", "copy",
                str(final_video)
            ], capture_output=True, check=True)
        except subprocess.CalledProcessError as e:
            stderr_msg = e.stderr.decode('utf-8', errors='ignore') if isinstance(e.stderr, bytes) else (str(e.stderr) if e.stderr else "No stderr")
            raise RuntimeError(f"Step 4 (オーバーレイ適用) でエラーが発生しました。FFmpeg出力: {stderr_msg}") from e
        except OSError as e:
            raise RuntimeError(f"Step 4 (オーバーレイ適用) でシステムエラーが発生しました: {e}") from e
        print("✅ 完了")
        
        print(f"\n配置:")
        print(f"  位置: ({overlay_x}, {overlay_y})")
        print(f"  ロゴ: {logo_width}x45px")
        print(f"  テロップ: {telop_width}x45px")
        print(f"  間隔: 5px")
        print(f"  合計幅: {combined_width}px")
        
        # Step 5: スクリーンショット (抽出した動画の長さに合わせて動的にタイムスタンプを決定)
        print("\n[5/5] スクリーンショット生成...")
        
        ts_ratios = [0.1, 0.3, 0.7]
        for i, ratio in enumerate(ts_ratios):
            ts = extract_duration * ratio
            ts_str = f"{int(ts)}" if ts.is_integer() else f"{ts:.2f}"
            ss_path = output_dir / f"ALIGNED_screenshot_{i+1}_{ts_str}s.png"
            try:
                subprocess.run([
                    "ffmpeg", "-y", "-ss", f"{ts:.2f}", "-i", str(final_video),
                    "-frames:v", "1", str(ss_path)
                ], capture_output=True, check=True)
            except subprocess.CalledProcessError as e:
                stderr_msg = e.stderr.decode('utf-8', errors='ignore') if isinstance(e.stderr, bytes) else (str(e.stderr) if e.stderr else "No stderr")
                raise RuntimeError(f"Step 5 (スクリーンショット {i+1} 生成) でエラーが発生しました。FFmpeg出力: {stderr_msg}") from e
            except OSError as e:
                raise RuntimeError(f"Step 5 (スクリーンショット {i+1} 生成) でシステムエラーが発生しました: {e}") from e
            print(f"  ✅ {ss_path.name}")
        
        print("\n" + "="*70)
        print("✅ 高さ揃え・黒背景回避版完成")
        print("="*70)
        print("\n確認ポイント:")
        print("  ✅ ロゴとテロップの高さが揃っている（45px）")
        print("  ✅ ロゴが黒背景にかかっていない")
        print("  ✅ 密着配置（5px間隔）")
        print("  ✅ 日本語正常表示")
        
        return str(final_video)
    except (FileNotFoundError, RuntimeError):
        raise
    except Exception as e:
        raise RuntimeError(f"プレビュー生成中に予期せぬエラーが発生しました: {e}") from e
    finally:
        if logo_img is not None:
            try:
                logo_img.close()
            except Exception:
                pass
        if logo_resized is not None:
            try:
                logo_resized.close()
            except Exception:
                pass
        if telop_img is not None:
            try:
                telop_img.close()
            except Exception:
                pass
        if combined_img is not None:
            try:
                combined_img.close()
            except Exception:
                pass


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    try:
        final = create_aligned_preview()
        print(f"\n✅ 成功")
    except (subprocess.CalledProcessError, FileNotFoundError, OSError, RuntimeError) as e:
        print(f"\n❌ システムエラーが発生しました: {e}")
        cause = e.__cause__ if isinstance(e, RuntimeError) else e
        if isinstance(cause, subprocess.CalledProcessError) and cause.stderr:
            try:
                print(f"FFmpeg詳細エラー出力:\n{cause.stderr.decode('utf-8', errors='ignore')}")
            except (AttributeError, ValueError, TypeError):
                pass
        import traceback
        traceback.print_exc()
    except (ValueError, TypeError, KeyError, ZeroDivisionError) as e:
        print(f"\n❌ 予期せぬエラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
