import logging
from pathlib import Path
from typing import Dict, Any

from plugins.retention_map_plugin import RetentionMapReport
from safe_io import VAULT_OUTPUTS_DIR
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

# リスクスコア（0〜100）に対する色のマッピングを事前にキャッシュ
_RISK_COLOR_CACHE = {}
for i in range(101):
    if i > 70:
        _RISK_COLOR_CACHE[i] = "#ef4444" # 赤
    elif i > 40:
        _RISK_COLOR_CACHE[i] = "#eab308" # 黄
    else:
        _RISK_COLOR_CACHE[i] = "#22c55e" # 緑


class PreviewReportGenerator:
    """
    [Phase 3.4: Retention Map Visual Report]
    Retention Mapの解析結果を受け取り、可視化されたHTML（またはJSON用）レポートを出力する。
    """
    def __init__(self):
        self.output_dir = VAULT_OUTPUTS_DIR / "reports"
        self._ensure_dir()
        
    def _ensure_dir(self):
        if not self.output_dir.exists():
            self.output_dir.mkdir(parents=True, exist_ok=True)
            
    def generate_html_report(self, report: RetentionMapReport) -> str:
        """
        セグメント情報を元にヒートマップ風のHTMLレポートを生成する
        """
        html_path = self.output_dir / f"retention_report_{report.video_id}.html"
        
        # 文字列結合の高速化用リスト
        html_parts = []
        
        # 簡易的なHTML生成（実際はJinja2等のテンプレートエンジン推奨）
        html_parts.append(f"""
        <!DOCTYPE html>
        <html lang="ja">
        <head>
            <meta charset="UTF-8">
            <title>リテンションマップ分析 - {report.video_id}</title>
            <style>
                body {{ font-family: sans-serif; padding: 20px; background: #f5f5f5; }}
                .container {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                .heatmap-container {{ display: flex; width: 100%; height: 50px; margin-top: 20px; border: 1px solid #ccc; }}
                .segment {{ flex-grow: 1; height: 100%; transition: opacity 0.2s; }}
                .segment:hover {{ opacity: 0.7; }}
                .suggestions {{ margin-top: 30px; }}
                .suggestion-card {{ border-left: 4px solid #ef4444; padding: 10px; margin: 10px 0; background: #fff1f2; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>📊 視聴維持率予測ヒートマップ: {report.video_id}</h2>
                <p>総合評価: <strong>{report.overall_risk_assessment}</strong></p>
                <div class="heatmap-container">
        """)
        
        # 中間辞書リストを作らず、直接パーツリストに結合して高速化
        get_color = self._get_risk_color
        for s in report.segments:
            color = get_color(s.risk_score)
            hit_marker = "⭐" if s.dopamine_hit else ""
            time_range = f"{s.start_time}s - {s.end_time}s"
            html_parts.append(f'<div class="segment" style="background-color: {color};" title="{time_range} - リスク: {s.risk_score} {hit_marker}"></div>\n')
            
        html_parts.append("""
                </div>
                <div class="suggestions">
                    <h3>💡 リエンゲージメント提案</h3>
        """)
        
        if not report.suggestions:
            html_parts.append("<p>現在、追加の演出提案はありません。</p>")
        else:
            for sug in report.suggestions:
                html_parts.append(f"""
                    <div class="suggestion-card">
                        <strong>⏱️ {sug.timestamp_sec}秒付近</strong><br>
                        提案: {sug.suggestion_type}<br>
                        理由: {sug.reason}
                    </div>
                """)
                
        html_parts.append("""
                </div>
            </div>
        </body>
        </html>
        """)
        
        html_content = "".join(html_parts)
        
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
            
        # Prevention 2/3: Log explicitly and in Japanese
        logger.info(f"📄 [Report Generator] HTMLレポートを生成しました: {html_path}")
        return str(html_path)
        
    def _get_risk_color(self, risk_score: int) -> str:
        """リスクスコアに応じた色（緑→黄→赤）を返す。
        型が不正な場合や例外時は安全なデフォルト値（緑: #22c55e）にフォールバックする。"""
        try:
            score = int(risk_score)
            score = max(0, min(100, score))
            return _RISK_COLOR_CACHE.get(score, "#22c55e")
        except (ValueError, TypeError):
            return "#22c55e"

    def generate_thumbnail(self, output_path: Path, width: int = 1280, height: int = 720, text: str = "Preview") -> Path:
        """Pillowを使用して、指定された解像度とテキストで高品質なサムネイル画像を生成する"""
        from PIL import Image, ImageDraw, ImageFont
        import uuid
        import os
        
        # 1. パラメータの厳格な検証 (エラーハンドリングの強化)
        try:
            width = int(width)
            height = int(height)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Width and height must be integers: {e}")
            
        if width <= 0 or height <= 0:
            raise ValueError(f"Width and height must be positive integers. Got {width}x{height}")
            
        if text is None:
            text = ""
        elif not isinstance(text, str):
            text = str(text)
            
        output_path = Path(output_path)
        if output_path.is_dir():
            raise ValueError(f"Output path cannot be a directory: {output_path}")
            
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 2. 原子的な書き込み (Atomic Write) の実装
        temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        
        try:
            # 3. 高品質なグラデーション背景の生成 (Lanczos リサイズによる滑らかな補間)
            grad_small = Image.new("RGB", (16, 16))
            # 高級感あふれるディープナイトブルーからリッチなパープルへのグラデーション
            color1 = (20, 24, 45)      # 深いダークブルー
            color2 = (75, 30, 90)      # 洗練されたロイヤルパープル
            for y in range(16):
                for x in range(16):
                    factor = (x + y) / 30.0
                    r = int(color1[0] + (color2[0] - color1[0]) * factor)
                    g = int(color1[1] + (color2[1] - color1[1]) * factor)
                    b = int(color1[2] + (color2[2] - color1[2]) * factor)
                    grad_small.putpixel((x, y), (r, g, b))
            
            img = grad_small.resize((width, height), Image.Resampling.LANCZOS)
            d = ImageDraw.Draw(img)
            
            # 4. 複数OSに対応した高品質フォントの探索
            font_paths = [
                # Windows用フォント
                r"C:\Windows\Fonts\msjh.ttc",     # Microsoft JhengHei (台湾語/日本語向け太字)
                r"C:\Windows\Fonts\msgothic.ttc",  # MS Gothic
                r"C:\Windows\Fonts\meiryo.ttc",     # Meiryo
                # Linux/Docker環境用フォント
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
                "/usr/share/fonts/fonts-japanese-gothic.ttf",
                # macOS用フォント
                "/System/Library/Fonts/Helvetica.ttc",
                "/System/Library/Fonts/Hiragino Sans GB.ttc",
                # 標準英字フォント
                r"C:\Windows\Fonts\arialbd.ttf",    # Arial Bold
                r"C:\Windows\Fonts\arial.ttf",      # Arial
            ]
            
            font_size = max(24, int(height * 0.08))
            font = None
            
            # 初期フォントのロード
            for fp in font_paths:
                if os.path.exists(fp):
                    try:
                        font = ImageFont.truetype(fp, font_size)
                        break
                    except (OSError, IOError):
                        continue
            
            if font is None:
                font = ImageFont.load_default()
                
            # 5. テキスト幅に応じた動的なフォントスケーリング (はみ出し・文字切れ防止)
            max_text_width = int(width * 0.85)  # 左右の余白を考慮して85%幅を最大とする
            for _ in range(10):  # 最大10回縮小を試みる
                try:
                    bbox = d.textbbox((0, 0), text, font=font)
                    text_w = bbox[2] - bbox[0]
                    text_h = bbox[3] - bbox[1]
                except AttributeError:
                    # Pillow 旧バージョン互換
                    if hasattr(font, "getsize"):
                        text_w, text_h = font.getsize(text)
                    else:
                        text_w = len(text) * (font_size * 0.6)
                        text_h = font_size
                
                if text_w <= max_text_width or font_size <= 12:
                    break
                    
                # フォントサイズを20%縮小して再ロード
                font_size = max(12, int(font_size * 0.8))
                loaded_new_font = False
                for fp in font_paths:
                    if os.path.exists(fp):
                        try:
                            font = ImageFont.truetype(fp, font_size)
                            loaded_new_font = True
                            break
                        except (OSError, IOError):
                            continue
                if not loaded_new_font:
                    break  # デフォルトフォントの場合はサイズ変更不可のため抜ける
            
            text_x = (width - text_w) // 2
            text_y = (height - text_h) // 2
            
            # ドロップシャドウのオフセット
            shadow_offset = max(2, int(font_size * 0.05))
            d.text((text_x + shadow_offset, text_y + shadow_offset), text, font=font, fill=(10, 10, 20))
            
            # プレミアムゴールド＆アンチエイリアスの利いた輪郭線(stroke)付きでメインテキストを描画
            stroke_w = max(1, int(font_size * 0.04))
            d.text((text_x, text_y), text, font=font, fill=(255, 220, 90), stroke_width=stroke_w, stroke_fill=(15, 15, 30))
            
            # 保存
            img.save(temp_path, "PNG")
            
            # 正常保存後に置換
            if output_path.exists():
                output_path.unlink()
            temp_path.rename(output_path)
            
        except (OSError, IOError) as e:
            logger.error(f"Failed to generate thumbnail atomically: {e}")
            raise
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except (OSError, IOError) as e:
                    logger.warning(f"Could not clean up temporary file {temp_path}: {e}")
            
        return output_path

    def validate_thumbnail(self, file_path: Path) -> dict:
        """
        サムネイル画像の品質要件を検証する。
        - 1280x720 以上であること
        - アスペクト比が 16:9 であること（許容誤差 1e-3）
        - 4MB 未満であること
        - 正常にロード・破損していないこと
        """
        from PIL import UnidentifiedImageError
        
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Thumbnail file not found: {file_path}")

        size_bytes = file_path.stat().st_size
        if size_bytes >= 4 * 1024 * 1024:
            raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")

        # 1. verify() による基本破損チェック
        try:
            with Image.open(file_path) as img:
                img.verify()
        except (OSError, SyntaxError, UnidentifiedImageError, ValueError, TypeError) as e:
            raise ValueError(f"Image verification failed (Image is corrupted): {e}")

        # 2. ピクセルデータの明示的なロードによる完全な破損チェック (エラーハンドリングの強化)
        try:
            with Image.open(file_path) as img:
                img.load()  # デコードエラーやデータ破損を検出するためロードを実行
                width, height = img.size
        except (OSError, ValueError, TypeError, UnidentifiedImageError) as e:
            raise ValueError(f"Failed to load image for resolution check (Image is corrupted or invalid format): {e}")

        if width < 1280 or height < 720:
            raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")

        aspect_ratio = width / height
        target_ratio = 16.0 / 9.0
        # 16:9に対する許容誤差チェック (1e-3)
        if abs(aspect_ratio - target_ratio) > 1e-3:
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
        output_path = self.output_dir / f"thumbnail_{task_id}.png"
        self.generate_thumbnail(output_path, text=f"Report Preview {task_id}")
        result_info = self.validate_thumbnail(output_path)
        return json.dumps(result_info)

# Singleton
preview_report_generator = PreviewReportGenerator()
