"""
サムネイル分析強化サービス（BIZ-5 + IMP-007）

視聴者心理に基づくサムネイル品質分析:
- 顔クローズアップ比率チェック
- テキスト可読性チェック（モバイル60%小画面対応）
- カラーコントラスト分析（YouTube白背景での視認性）
- IMP-007: Gemini Vision APIによる実画像分析（テキストマッチのフォールバック付き）
"""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

import logging
import base64
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

# Model Registry (SSoT: model_config.json)
try:
    from model_registry import get_model
except ImportError:
    def get_model(task): return "gemini-2.5-flash"

logger = logging.getLogger(__name__)


class ThumbnailAnalyzer:
    """サムネイル品質分析"""

    # YouTube推奨: 1280x720
    THUMB_WIDTH = 1280
    THUMB_HEIGHT = 720
    MOBILE_SCALE = 0.3  # モバイルでの表示サイズ比

    # ━━━ IMP-007: Gemini Vision APIプロンプト ━━━
    VISION_PROMPT = """あなたはYouTubeサムネイルの品質分析エキスパートです。
以下の画像をYouTubeサムネイルとして分析し、JSON形式で回答してください。

評価項目:
1. face_score (0-100): 顔のクローズアップ比率。顔が画面の30%以上で高得点。
2. text_score (0-100): テキストの可読性。モバイル（384x216px）で読めるか。文字数が少なく大きいほど高得点。
3. contrast_score (0-100): YouTube白背景での視認性。高コントラストで高得点。
4. composition_score (0-100): 構図の効果性。Before/After、矢印、数字等の定番パターン使用で高得点。
5. overall_impression: 一言コメント（日本語、20文字以内）
6. top_improvement: 最も効果的な改善提案（日本語、40文字以内）

回答は以下のJSON形式のみ。説明文は不要:
{"face_score":85,"text_score":70,"contrast_score":90,"composition_score":75,"overall_impression":"...","top_improvement":"..."}"""

    def analyze(self, thumbnail_concept: Dict[str, Any]) -> Dict[str, Any]:
        """サムネイルコンセプトの品質分析（テキストマッチ版）"""
        checks = []
        total_score = 0

        # 1. 顔クローズアップチェック
        face_check = self._check_face_closeup(thumbnail_concept)
        checks.append(face_check)
        total_score += face_check["score"]

        # 2. テキスト可読性チェック
        text_check = self._check_text_readability(thumbnail_concept)
        checks.append(text_check)
        total_score += text_check["score"]

        # 3. カラーコントラストチェック
        color_check = self._check_color_contrast(thumbnail_concept)
        checks.append(color_check)
        total_score += color_check["score"]

        # 4. 構図チェック
        comp_check = self._check_composition(thumbnail_concept)
        checks.append(comp_check)
        total_score += comp_check["score"]

        avg_score = round(total_score / len(checks), 1)

        return {
            "overall_score": avg_score,
            "verdict": "✅ 高品質" if avg_score >= 80 else "⚠️ 改善推奨" if avg_score >= 60 else "❌ 要修正",
            "checks": checks,
            "predicted_ctr_impact": self._estimate_ctr_impact(avg_score),
            "top_improvement": min(checks, key=lambda c: c["score"])["suggestion"],
            "analysis_mode": "text_match",
        }

    def analyze_image(self, image_path: str) -> Dict[str, Any]:
        """IMP-007: Gemini Vision APIによる実画像分析

        Args:
            image_path: サムネイル画像の絶対パス

        Returns:
            分析結果。API未設定時はテキスト分析にフォールバック。
        """
        path = Path(image_path)
        if not path.exists():
            logger.warning(f"サムネイル画像が見つかりません: {image_path}")
            return self.analyze({"concept": path.stem})

        try:
            from gemini_client_factory import get_gemini_client
            client = get_gemini_client()
            if client is None:
                logger.info("Gemini API未設定 — テキスト分析にフォールバック")
                return self.analyze({"concept": path.stem})

            # 画像をBase64エンコード
            image_bytes = path.read_bytes()
            mime_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"

            response = client.models.generate_content(
                model=get_model("quality_gate"),
                contents=[
                    {
                        "role": "user",
                        "parts": [
                            {"text": self.VISION_PROMPT},
                            {
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": base64.b64encode(image_bytes).decode("utf-8"),
                                }
                            },
                        ],
                    }
                ],
            )

            # JSON抽出
            result = self._parse_vision_api_response(response.text)

            face_score = result.get("face_score", 50)
            text_score = result.get("text_score", 50)
            contrast_score = result.get("contrast_score", 50)
            composition_score = result.get("composition_score", 50)

            min_score = min(face_score, text_score, contrast_score, composition_score)

            # 各項目の suggestion 決定ロジック
            if face_score == min_score:
                face_sugg = result.get("top_improvement", "改善提案なし")
            else:
                face_sugg = "顔が画面の30%以上を占めるようにする" if face_score >= 70 else "驚き顔・リアクション顔を追加するとCTR +1.5%の可能性"

            if text_score == min_score:
                text_sugg = result.get("top_improvement", "改善提案なし")
            else:
                if text_score >= 80:
                    text_sugg = "現状のまま保持"
                elif text_score >= 40:
                    text_sugg = "10文字以内に削減すると可読性向上"
                else:
                    text_sugg = "10文字以内に大胆に削減すること"

            if contrast_score == min_score:
                contrast_sugg = result.get("top_improvement", "改善提案なし")
            else:
                if contrast_score >= 80:
                    contrast_sugg = "現状のスタイルを維持"
                elif contrast_score >= 50:
                    contrast_sugg = "黒背景+白/黄文字の組み合わせが最も安全"
                else:
                    contrast_sugg = "暗い背景色 or ビビッドカラーに変更してコントラストを確保"

            if composition_score == min_score:
                composition_sugg = result.get("top_improvement", "改善提案なし")
            else:
                composition_sugg = "視線誘導の矢印やフレームを追加するとさらに効果的" if composition_score >= 70 else "Before/After比較、大きな数字、矢印のいずれかを追加"

            # 統一フォーマットに変換
            checks = [
                {
                    "name": "顔クローズアップ",
                    "score": face_score,
                    "status": self._get_status_icon(face_score),
                    "detail": f"Vision API分析: {face_score}点",
                    "suggestion": face_sugg,
                },
                {
                    "name": "テキスト可読性",
                    "score": text_score,
                    "status": self._get_status_icon(text_score),
                    "detail": f"Vision API分析: {text_score}点",
                    "suggestion": text_sugg,
                },
                {
                    "name": "カラーコントラスト",
                    "score": contrast_score,
                    "status": self._get_status_icon(contrast_score),
                    "detail": f"Vision API分析: {contrast_score}点",
                    "suggestion": contrast_sugg,
                },
                {
                    "name": "構図パターン",
                    "score": composition_score,
                    "status": self._get_status_icon(composition_score),
                    "detail": f"Vision API分析: {composition_score}点",
                    "suggestion": composition_sugg,
                },
            ]

            scores = [c["score"] for c in checks]
            avg_score = round(sum(scores) / len(scores), 1)

            return {
                "overall_score": avg_score,
                "verdict": "✅ 高品質" if avg_score >= 80 else "⚠️ 改善推奨" if avg_score >= 60 else "❌ 要修正",
                "checks": checks,
                "predicted_ctr_impact": self._estimate_ctr_impact(avg_score),
                "top_improvement": result.get("top_improvement", "改善提案なし"),
                "overall_impression": result.get("overall_impression", ""),
                "analysis_mode": "gemini_vision",
            }

        except json.JSONDecodeError as jde:
            logger.error(f"Gemini Vision分析応答パースエラー — テキスト分析にフォールバック: {jde}")
            logger.debug(f"Failed to parse text: {response.text if 'response' in locals() else 'None'}", exc_info=True)
            return self.analyze({"concept": path.stem})
        except Exception as e:
            logger.error(f"Gemini Vision分析エラー — テキスト分析にフォールバック: {e}")
            # TDRへの登録等がない場合でも、例外トレースが確実にログに出るようにする
            logger.debug("Gemini Vision API fallback stack trace:", exc_info=True)
            return self.analyze({"concept": path.stem})

    def _check_face_closeup(self, concept: Dict) -> Dict:
        """顔のクローズアップ比率（CTRに最も影響する要因）"""
        desc = concept.get("concept", "").lower()
        has_face = any(w in desc for w in ["顔", "クローズアップ", "表情", "驚き", "笑顔", "リアクション"])

        if has_face:
            return {
                "name": "顔クローズアップ",
                "score": 90,
                "status": "✅",
                "detail": "顔のクローズアップを含む — CTR向上に最も効果的",
                "suggestion": "顔が画面の30%以上を占めるようにする",
            }
        return {
            "name": "顔クローズアップ",
            "score": 40,
            "status": "⚠️",
            "detail": "顔のクローズアップが検出されない",
            "suggestion": "驚き顔・リアクション顔を追加するとCTR +1.5%の可能性",
        }

    def _check_text_readability(self, concept: Dict) -> Dict:
        """モバイル画面でのテキスト可読性"""
        text = concept.get("text_overlay", concept.get("concept", ""))
        text_len = len(text)

        # モバイル（384x216px相当）で読める文字数は約10-15文字
        if text_len <= 10:
            return {
                "name": "テキスト可読性",
                "score": 95,
                "status": "✅",
                "detail": f"テキスト{text_len}文字 — モバイルで大きく表示可能",
                "suggestion": "現状のまま保持",
            }
        elif text_len <= 20:
            return {
                "name": "テキスト可読性",
                "score": 70,
                "status": "⚠️",
                "detail": f"テキスト{text_len}文字 — モバイルでギリギリ読める",
                "suggestion": f"10文字以内に削減すると可読性向上（現在{text_len}文字）",
            }
        return {
            "name": "テキスト可読性",
            "score": 35,
            "status": "❌",
            "detail": f"テキスト{text_len}文字 — モバイルで読めない可能性が高い",
            "suggestion": f"10文字以内に大胆に削減すること（現在{text_len}文字）",
        }

    def _check_color_contrast(self, concept: Dict) -> Dict:
        """YouTube白背景での視認性"""
        style = concept.get("style", "").lower()

        high_contrast_keywords = ["黒背景", "ダーク", "高コントラスト", "赤", "黄色", "ビビッド"]
        low_contrast_keywords = ["白", "パステル", "淡い", "ライト"]

        is_high = any(k in style for k in high_contrast_keywords)
        is_low = any(k in style for k in low_contrast_keywords)

        if is_high:
            return {
                "name": "カラーコントラスト",
                "score": 90,
                "status": "✅",
                "detail": "高コントラスト — YouTube白背景で際立つ",
                "suggestion": "現状のスタイルを維持",
            }
        elif is_low:
            return {
                "name": "カラーコントラスト",
                "score": 35,
                "status": "❌",
                "detail": "低コントラスト — YouTube白背景に埋もれるリスク",
                "suggestion": "暗い背景色 or ビビッドカラーに変更してコントラストを確保",
            }
        return {
            "name": "カラーコントラスト",
            "score": 65,
            "status": "⚠️",
            "detail": "コントラスト情報不足",
            "suggestion": "黒背景+白/黄文字の組み合わせが最も安全",
        }

    def _check_composition(self, concept: Dict) -> Dict:
        """構図チェック（Before/After, 矢印等）"""
        desc = concept.get("concept", "").lower()
        strong_patterns = ["before/after", "比較", "矢印", "2分割", "数字"]

        matches = [p for p in strong_patterns if p in desc]
        if matches:
            return {
                "name": "構図パターン",
                "score": 85,
                "status": "✅",
                "detail": f"効果的パターン検出: {', '.join(matches)}",
                "suggestion": "視線誘導の矢印やフレームを追加するとさらに効果的",
            }
        return {
            "name": "構図パターン",
            "score": 55,
            "status": "⚠️",
            "detail": "定番構図パターンが検出されない",
            "suggestion": "Before/After比較、大きな数字、矢印のいずれかを追加",
        }

    def _estimate_ctr_impact(self, score: float) -> str:
        """スコアからCTR影響を推定"""
        if score >= 85:
            return "+1.5-2.0% CTRブースト見込み"
        elif score >= 70:
            return "+0.5-1.0% CTRブースト見込み"
        elif score >= 50:
            return "±0% CTR影響は中立"
        return "-1.0% CTR低下リスクあり"

    def _get_status_icon(self, score: int) -> str:
        """スコアに応じたステータスアイコンを取得"""
        if score >= 70:
            return "✅"
        if score >= 40:
            return "⚠️"
        return "❌"

    def _parse_vision_api_response(self, text: str) -> Dict[str, Any]:
        """Gemini Vision APIの応答テキストからJSONをパースする"""
        import json
        import re
        text = text.strip()
        # ```json や ``` で囲まれた部分を正規表現で頑健に抽出
        # 大文字小文字や余分なスペースにも対応
        match = re.search(r"```\s*(?:json\s+)?(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
        if match:
            text = match.group(1).strip()
        return json.loads(text)

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
        """PillowとNumPyを使用して指定された解像度とテキストで高品質サムネイル画像を生成する"""
        import os
        import uuid
        import shutil
        import time
        import numpy as np
        from PIL import Image, ImageDraw, ImageFont
        from pathlib import Path

        # None値に対するフォールバック
        if width is None:
            width = 1280
        if height is None:
            height = 720
        if text is None:
            text = ""
        else:
            text = str(text)  # 文字列型への強制キャストで安全性を確保
            # 自動折り返し処理 (1行あたり全角18文字/半角36文字目安)
            max_chars_per_line = 18
            wrapped_lines = []
            for paragraph in text.split("\n"):
                if not paragraph:
                    wrapped_lines.append("")
                    continue
                current_line = []
                current_len = 0
                for char in paragraph:
                    char_len = 2 if ord(char) > 127 else 1
                    if current_len + char_len > max_chars_per_line * 2:
                        wrapped_lines.append("".join(current_line))
                        current_line = [char]
                        current_len = char_len
                    else:
                        current_line.append(char)
                        current_len += char_len
                if current_line:
                    wrapped_lines.append("".join(current_line))
            text = "\n".join(wrapped_lines)

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
            raise ValueError(f"Width and height must be integers or numeric types convertible to integer: {e}") from e
            
        if width <= 0 or height <= 0:
            raise ValueError(f"Width and height must be positive integers. Got {width}x{height}")

        # 8K解像度(7680x4320)を超える極端なサイズを制限（OutOfMemory防止）
        if width > 7680 or height > 4320:
            raise ValueError(f"Resolution exceeds maximum limit of 8K (7680x4320). Got {width}x{height}")
            
        if width < 1280 or height < 720:
            raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
            
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
            raise IOError(f"Cannot write thumbnail to {output_path}. Cannot create parent directory: {parent_dir}. Error: {e}") from e

        if not os.path.exists(parent_dir):
            raise IOError(f"Parent directory does not exist after creation attempt: {parent_dir}")

        if not os.access(str(parent_dir), os.W_OK):
            raise PermissionError(f"Parent directory is not writeable: {parent_dir}")
        
        # スーパサンプリング係数（巨大な解像度でのメモリ爆発とハングを防ぐため、1080pを超える場合は1に制限）
        scale = 2
        if width > 1920 or height > 1080:
            scale = 1
        ss_width = width * scale
        ss_height = height * scale

        # 巨大解像度でのメモリ爆発とハングを防ぐため、NumPyで行う背景生成のサイズは最大 1920x1080 に制限する
        bg_width = ss_width
        bg_height = ss_height
        if bg_width > 1920 or bg_height > 1080:
            bg_width = 1920
            bg_height = 1080

        # 原子的な書き込み (Atomic Write) の実装
        temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        img = None
        resized_img = None
        try:
            # NumPyを使用してスーパサンプリング解像度で滑らかなグラデーション背景を高速生成
            y_grid, x_grid = np.ogrid[:bg_height, :bg_width]
            factor = (x_grid / (bg_width - 1.0) + y_grid / (bg_height - 1.0)) / 2.0
            
            # 色の遷移（グラデーション）を滑らかにするため smoothstep 補間を適用
            factor = factor * factor * (3.0 - 2.0 * factor)
            
            # 中央からの距離を計算（放射状のグロー効果を追加）
            center_y, center_x = bg_height / 2.0, bg_width / 2.0
            dist_from_center = np.sqrt((x_grid - center_x)**2 + (y_grid - center_y)**2)
            max_dist = np.sqrt(center_x**2 + center_y**2)
            
            # 放射状グローも smoothstep 補間を用いてよりソフトなエッジに改善
            dist_ratio = np.clip(dist_from_center / max_dist, 0, 1)
            glow = 1.0 - (dist_ratio * dist_ratio * (3.0 - 2.0 * dist_ratio))
            
            # ガンマ 2.2 によるリニア空間への事前変換（混色時の濁りを防止し高品質化）
            color1 = np.array([35, 30, 60], dtype=np.float32)
            color2 = np.array([15, 65, 95], dtype=np.float32)
            color3 = np.array([80, 45, 90], dtype=np.float32)
            
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
            
            # ゴールド/オレンジ（240, 180, 80）の放射状グロー効果をリニア空間でブレンド
            glow_color = np.array([240, 180, 80], dtype=np.float32)
            glow_color_lin = (glow_color / 255.0) ** 2.2
            glow_strength = 0.35
            
            r_lin = r_lin + glow * glow_color_lin[0] * glow_strength
            g_lin = g_lin + glow * glow_color_lin[1] * glow_strength
            b_lin = b_lin + glow * glow_color_lin[2] * glow_strength
            
            # sRGB空間（ガンマ 1/2.2）へ逆変換
            r = (np.clip(r_lin, 0, 1) ** (1.0 / 2.2)) * 255.0
            g = (np.clip(g_lin, 0, 1) ** (1.0 / 2.2)) * 255.0
            b = (np.clip(b_lin, 0, 1) ** (1.0 / 2.2)) * 255.0
            
            # 全ての解像度で適切にバンディング低減のためのディザリングを適用
            # normal よりも高速な uniform 分布でディザリングを行い、超高解像度での処理時間とメモリ消費を大幅に抑制
            dither_intensity = 0.45 if bg_width <= 1920 else 0.25
            dither = np.random.uniform(-dither_intensity, dither_intensity, (bg_height, bg_width, 3))
            rgb = np.clip(np.stack([r, g, b], axis=-1) + dither, 0, 255).astype(np.uint8)
            img = Image.fromarray(rgb)

            # 生成した背景をスーパサンプリング解像度へリサイズ（拡大）
            if ss_width != bg_width or ss_height != bg_height:
                img_resized = img.resize((ss_width, ss_height), Image.Resampling.LANCZOS)
                img.close()
                img = img_resized
            
            # 中間 NumPy 巨大配列を明示的かつ即座に解放し、GCを促す
            del y_grid, x_grid, factor, dist_from_center, dist_ratio, glow
            del color1, color2, color3, color1_lin, color2_lin, color3_lin, mask, t
            del r_lin, g_lin, b_lin, glow_color, glow_color_lin, r, g, b, dither, rgb
            import gc
            gc.collect()
            
            # OSに依存しない強固なフォント検索・フォールバック
            font_paths = [
                # Windows
                r"C:\Windows\Fonts\msjh.ttc",      # Microsoft JhengHei
                r"C:\Windows\Fonts\meiryo.ttc",     # Meiryo
                r"C:\Windows\Fonts\YuGothM.ttc",    # Yu Gothic
                r"C:\Windows\Fonts\msgothic.ttc",   # MS Gothic
                r"C:\Windows\Fonts\msmincho.ttc",   # MS Mincho
                r"C:\Windows\Fonts\arial.ttf",      # Arial
                # macOS
                "/System/Library/Fonts/PingFang.ttc",
                "/System/Library/Fonts/Hiragino Sans GB.ttc",
                "/System/Library/Fonts/STHeiti Light.ttc",
                "/System/Library/Fonts/Helvetica.ttc",
                "/Library/Fonts/Arial.ttf",
                # Linux
                "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttf",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttf",
                "/usr/share/fonts/truetype/noto/NotoSansJP-Regular.ttf",
                "/usr/share/fonts/opentype/noto/NotoSansJP-Regular.otf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
                "/usr/share/fonts/fonts-japanese-gothic.ttf",
                "/.fonts/NotoSansJP-Regular.ttf"
            ]
            
            # スーパサンプリングサイズに応じたフォントサイズ調整
            font_size = max(48, int(ss_height * 0.08))
            border_margin = max(20, int(min(ss_width, ss_height) * 0.02))
            max_text_width = ss_width - (border_margin * 4)
            
            font = None
            text_w, text_h = 0, 0
            d_temp_img = Image.new("RGB", (1, 1))
            d_temp = ImageDraw.Draw(d_temp_img)
            
            lines = text.split("\n")
            line_spacing = int(font_size * 0.15)
            
            # テキストサイズに応じた動的フォントサイズ調整（オートスケール、複数行対応）
            while font_size >= 12:
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
                
                if (max_w <= max_text_width and total_h <= ss_height * 0.6) or font_size <= 12:
                    font = current_font
                    text_w, text_h = max_w, total_h
                    break
                font_size -= 4
                line_spacing = int(font_size * 0.15)
            else:
                for fp in font_paths:
                    if os.path.exists(fp):
                        try:
                            font = ImageFont.truetype(fp, 12)
                            break
                        except OSError:
                            continue
                if font is None:
                    try:
                        font = ImageFont.load_default(size=12)
                    except TypeError:
                        font = ImageFont.load_default()
                text_w = max(len(l) * 8 for l in lines)
                text_h = len(lines) * 14 + 2 * (len(lines) - 1)
            
            d_temp_img.close()
                
            d = ImageDraw.Draw(img)
            
            # エッジの二重線枠飾り（プレミアム感の向上、スーパサンプリング対応）
            border_width = max(2, int(min(ss_width, ss_height) * 0.003))
            d.rectangle(
                [border_margin, border_margin, ss_width - border_margin, ss_height - border_margin],
                outline=(255, 255, 255),
                width=border_width
            )
            inner_margin = border_margin + border_width + 4
            d.rectangle(
                [inner_margin, inner_margin, ss_width - inner_margin, ss_height - inner_margin],
                outline=(218, 165, 32), # ゴールド
                width=2
            )
            
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

            # 注目を集める矢印の描画 (立体的なソフトドロップシャドウとアンチエイリアスの適用)
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
                
                # 影レイヤーの生成
                with Image.new("RGBA", (arrow_w, arrow_h), (0, 0, 0, 0)) as arrow_shadow_layer:
                    shadow_draw = ImageDraw.Draw(arrow_shadow_layer)
                    # オフセットした位置に黒い影を描画
                    shadow_pts = [(x + int(12 * arrow_scale), y + int(12 * arrow_scale)) for x, y in pts]
                    shadow_draw.polygon(shadow_pts, fill=(0, 0, 0, 120))
                    # 影をソフトにぼかす
                    arrow_shadow_layer_blurred = arrow_shadow_layer.filter(ImageFilter.GaussianBlur(radius=8 * arrow_scale))
                    
                    with Image.new("RGBA", (arrow_w, arrow_h), (0, 0, 0, 0)) as arrow_layer:
                        arrow_draw = ImageDraw.Draw(arrow_layer)
                        arrow_draw.polygon(
                            pts,
                            fill=(230, 30, 30, 230),
                            outline=(255, 255, 255, 255),
                            width=max(4, 4 * arrow_scale)
                        )
                        
                        # 影と矢印本体の結合
                        combined_arrow = Image.alpha_composite(arrow_shadow_layer_blurred, arrow_layer)
                        with combined_arrow.resize((ss_width, ss_height), Image.Resampling.LANCZOS) as resized_arrow:
                            old_img = img
                            img = Image.alpha_composite(img.convert("RGBA"), resized_arrow)
                            old_img.close()
                    arrow_shadow_layer_blurred.close()
                d = ImageDraw.Draw(img)

            # 強調サークルの描画 (立体的なソフトドロップシャドウとアンチエイリアスの適用)
            if draw_circle:
                from PIL import ImageFilter
                circle_scale = 2
                circle_w = ss_width * circle_scale
                circle_h = ss_height * circle_scale
                
                cx = int(circle_w * 0.25)
                cy = int(circle_h * 0.5)
                rx = int(circle_w * 0.12)
                ry = int(circle_h * 0.22)
                
                # 影レイヤーの生成
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

            # ドロップシャドウとアウトライン付きテキストを複数行対応で描画
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
                
                # 複数方向・アルファ値を変えて多重描画することで、ソフトシャドウ（ぼかし影）効果を再現
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

            # ファイルサイズ4MB未満を保証する堅牢な保存ループ
            max_size = 4 * 1024 * 1024
            
            if ext in [".jpg", ".jpeg"]:
                # JPEG保存: 高画質 95 から開始して細かく調整
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
                    raise ValueError(f"Failed to compress JPEG below 4MB even at quality 30")
            else:
                # PNG保存
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
            
            import shutil
            import time
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
                    except (shutil.Error, OSError) as ex:
                        logger.error(f"shutil.move fallback failed: {ex}")
                    time.sleep(0.1)
            if not success:
                raise IOError(f"Failed to move temporary file {temp_path} to final destination {output_path}")
            
            try:
                self.validate_thumbnail(output_path)
            except Exception as ve:
                logger.error(f"Generated thumbnail failed validation: {ve}")
                if output_path.exists():
                    try:
                        output_path.unlink()
                    except OSError:
                        pass
                raise ValueError(f"Generated thumbnail quality validation failed: {ve}")
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
                except OSError as ue:
                    logger.warning(f"Failed to delete temp file {temp_path}: {ue}")
            logger.error(f"Failed to generate thumbnail atomically: {e}")
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
            # 正常終了時、あるいは例外発生時に関わらず、一時ファイルが残っていれば確実にクリーンアップ
            if 'temp_path' in locals() and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError as ue:
                    logger.warning(f"Failed to clean up temporary file {temp_path} in finally block: {ue}")
            
        return output_path

    def validate_thumbnail(self, file_path) -> dict:
        """
        サムネイル画像の品質要件を検証する。検証エラー時は ValueError を投げる。
        """
        from PIL import Image, UnidentifiedImageError
        from PIL.Image import DecompressionBombError
        from pathlib import Path
        from usage_tracker.alert_system import emit_warning

        if not file_path:
            raise ValueError("File path must not be empty or None")

        file_path = Path(file_path)
        
        # サポートする画像形式（拡張子）の検証
        suffix = file_path.suffix.lower()
        if suffix not in [".png", ".jpg", ".jpeg"]:
            message = f"Unsupported file format: {suffix}. Only PNG, JPG, and JPEG are supported."
            emit_warning("thumbnail", message)
            raise ValueError(message)
        if not file_path.exists():
            message = f"Thumbnail file not found: {file_path}"
            emit_warning("thumbnail", message)
            raise FileNotFoundError(message)
            
        size_bytes = file_path.stat().st_size
        if size_bytes == 0:
            message = f"Thumbnail file is empty: {file_path}"
            emit_warning("thumbnail", message)
            raise ValueError(message)

        max_size = 4 * 1024 * 1024 # 4MB
        if size_bytes >= max_size:
            message = f"File size exceeds 4MB limit: {size_bytes} bytes"
            emit_warning("thumbnail", message)
            raise ValueError(message)
            
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
        except ValueError as ve:
            emit_warning("thumbnail", str(ve))
            raise
        except OSError as e:
            message = f"Failed to verify file magic number: {e}"
            emit_warning("thumbnail", message)
            raise ValueError(message) from e
            
        # 1. 簡易的なverify
        try:
            with Image.open(file_path) as img:
                img.verify()
        except (SyntaxError, OSError, ValueError, UnidentifiedImageError) as e:
            message = f"Image is corrupted or invalid format (invalid syntax or verify failed): {e}"
            emit_warning("thumbnail", message)
            raise ValueError(message)
        except Exception as e:
            message = f"Unexpected error during image verification: {e}"
            emit_warning("thumbnail", message)
            raise ValueError(message)
            
        # 2. 完全なピクセルデータのロードによる破損検知
        try:
            with Image.open(file_path) as img:
                img.load()  # ピクセルデータのロードを強制
                try:
                    width, height = img.size
                except Exception:
                    width, height = 1280, 720
                
                # ゼロ除算及び無効な解像度の安全ガード
                if width <= 0 or height <= 0:
                    raise ValueError(f"Invalid image dimensions: {width}x{height}")
                
                # ピクセルデータの切り捨てなどを検出するため、ダミーで一部バイトデータを取得
                img.tobytes()
        except UnidentifiedImageError as e:
            message = f"Failed to open image during loading (unidentified image): {e}"
            emit_warning("thumbnail", message)
            raise ValueError(message)
        except ValueError as e:
            if "tile cannot extend outside image" in str(e):
                message = f"Invalid image dimensions: {e}"
            else:
                message = f"Invalid value encountered during pixel load: {e}"
            emit_warning("thumbnail", message)
            raise ValueError(message)
        except (SyntaxError, OSError) as e:
            message = f"Failed to load image pixels (corrupted pixel stream): {e}"
            emit_warning("thumbnail", message)
            raise ValueError(message)
        except DecompressionBombError as e:
            message = f"Failed to load image pixels (Decompression Bomb): {e}"
            emit_warning("thumbnail", message)
            raise ValueError(message)
        except Exception as e:
            message = f"Unexpected error during image loading: {e}"
            emit_warning("thumbnail", message)
            raise ValueError(message)
            
        if width < 1280 or height < 720:
            message = f"Resolution must be at least 1280x720. Got {width}x{height}"
            emit_warning("thumbnail", message)
            raise ValueError(message)
            
        if width > 7680 or height > 4320:
            message = f"Resolution exceeds maximum limit of 8K (7680x4320). Got {width}x{height}"
            emit_warning("thumbnail", message)
            raise ValueError(message)
            
        aspect_ratio = width / height
        target_ratio = 16.0 / 9.0
        if abs(aspect_ratio - target_ratio) > 0.01:
            message = f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}"
            emit_warning("thumbnail", message)
            raise ValueError(message)
            
        return {
            "path": str(file_path),
            "width": width,
            "height": height,
            "size_bytes": size_bytes
        }

    async def resolve_thumbnail_task(self, agent_or_id, task_id: str = None, db_path: str = None, output_dir=None) -> str:
        """
        StageBoundAgent の process_func として動作する非同期タスク処理。
        実行時に例外が発生した場合はアラートシステムに重要（CRITICAL）を発行する。
        """
        import json
        import sqlite3
        import time
        import asyncio
        from pathlib import Path
        from usage_tracker.alert_system import emit_critical

        # StageBoundAgentインスタンスかどうかの判定
        is_agent = False
        if type(agent_or_id).__name__ == "StageBoundAgent" or hasattr(agent_or_id, "stage_name"):
            is_agent = True

        if is_agent:
            agent = agent_or_id
            actual_task_id = task_id or getattr(agent, "current_task_id", "task_unknown")
            actual_db_path = db_path or getattr(agent, "db_path", ":memory:")
            actual_output_dir = output_dir or getattr(agent, "output_dir", None)
            width = getattr(self, "width", getattr(agent, "width", 1280))
            height = getattr(self, "height", getattr(agent, "height", 720))
            text = getattr(self, "text", getattr(agent, "text", f"Thumbnail {actual_task_id}"))
        else:
            actual_task_id = agent_or_id
            actual_db_path = db_path or ":memory:"
            actual_output_dir = output_dir
            width = getattr(self, "width", 1280)
            height = getattr(self, "height", 720)
            text = getattr(self, "text", f"Thumbnail {actual_task_id}")

        try:
            out_dir = Path(actual_output_dir or _writable_path("backend/temp_thumbnails"))
            out_dir.mkdir(parents=True, exist_ok=True)
            output_path = out_dir / f"{actual_task_id}.png"
            
            self.generate_thumbnail(output_path, width=width, height=height, text=text)
            result_info = self.validate_thumbnail(output_path)
            
            # DBマイグレーション & 結果保存
            db_retries = 5
            for attempt in range(db_retries):
                try:
                    conn = sqlite3.connect(actual_db_path, timeout=30.0)
                    try:
                        # インメモリDBでWALモードへの変更時にエラーになるのを防ぐ
                        if actual_db_path != ":memory:":
                            conn.execute("PRAGMA journal_mode=WAL")
                        
                        conn.execute("""
                            CREATE TABLE IF NOT EXISTS thumbnail_results (
                                task_id TEXT PRIMARY KEY,
                                path TEXT,
                                width INTEGER,
                                height INTEGER,
                                size_bytes INTEGER,
                                verified_at REAL
                            )
                        """)
                        conn.execute(
                            "INSERT OR REPLACE INTO thumbnail_results VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                actual_task_id,
                                str(output_path),
                                result_info["width"],
                                result_info["height"],
                                result_info["size_bytes"],
                                time.time()
                            )
                        )
                        conn.commit()
                        break
                    except sqlite3.Error as de:
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                        raise de
                    finally:
                        conn.close()
                except sqlite3.OperationalError as oe:
                    if "locked" in str(oe).lower() and attempt < db_retries - 1:
                        import random
                        sleep_time = (2 ** attempt) * 0.5 + random.random()
                        logger.warning(
                            f"Database locked in ThumbnailAnalyzer.resolve_thumbnail_task (Attempt {attempt + 1}/{db_retries}). "
                            f"Retrying in {sleep_time:.2f} seconds..."
                        )
                        await asyncio.sleep(sleep_time)
                    else:
                        raise

            # StageBoundAgent が期待する "valid": True を付加
            result_info["valid"] = True
            return json.dumps(result_info)
        except Exception as e:
            emit_critical("thumbnail", f"Thumbnail task failed for task {actual_task_id}: {e}")
            raise


thumbnail_analyzer = ThumbnailAnalyzer()


# 旧 ThumbnailResolver 互換のためのクラス
class ThumbnailResolver(ThumbnailAnalyzer):
    """
    ThumbnailAnalyzer の生成・検証ロジックを継承した互換用クラス。
    """
    def __init__(self, project_root=None, output_dir=None):
        super().__init__()
        from pathlib import Path
        self.project_root = project_root or Path(__file__).resolve().parents[2]
        self.output_dir = output_dir or _writable_path("temp_thumbnails")
        
    async def resolve_thumbnail_task(self, task_id):
        # 親クラスの resolve_thumbnail_task を呼び出す
        return await super().resolve_thumbnail_task(task_id, output_dir=str(self.output_dir))
