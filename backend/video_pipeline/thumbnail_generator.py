"""
thumbnail_generator.py — S9: サムネイル生成

動画からサムネイル画像を生成するパイプラインステージ。
FFmpegで複数フレームを抽出し、構図・品質スコアリング（明るさ・コントラスト・エントロピー）により
最適候補を自動選択する。また、Pillow (PIL) でテキストオーバーレイを行う。
Pillow未インストール時はフレーム画像のみを返却するフォールバック設計。

FFmpeg呼び出しは _run_ffmpeg() メソッドに分離し、テスト時にモック可能な設計。

subprocess.Popenモック安全規約:
  - poll() は return_value=0 で即座に終了コードを返すこと
  - readline() は空文字列 "" を返すこと
  - conftest.py の safe_popen_mock fixture を使用すること
"""

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 定数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# デフォルトのフレーム抽出位置（動画長に対する割合）
DEFAULT_FRAME_POSITION = 0.3


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# データクラス定義
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class ThumbnailCandidate:
    """サムネイル候補。

    Attributes:
        image_path: 候補画像のパス
        source_frame_time: フレーム抽出時刻（秒）
        resolution: サムネイル解像度 (例: "1280x720")
        file_size: ファイルサイズ（バイト）
        score: スコア (0-100)
        score_details: スコア内訳辞書
    """

    image_path: str = ""
    source_frame_time: float = 0.0
    resolution: str = ""
    file_size: int = 0
    score: float = 0.0
    score_details: dict = field(default_factory=dict)


@dataclass
class ThumbnailResult:
    """サムネイル生成結果。

    Attributes:
        success: 生成成功フラグ
        image_path: 生成されたサムネイル画像のパス
        source_frame_time: フレーム抽出時刻（秒）
        resolution: サムネイル解像度 (例: "1280x720")
        file_size: ファイルサイズ（バイト）
        score: 最高スコア (0-100)
        score_details: 最高スコア候補のスコア詳細
        candidates: 生成された全候補のリスト
    """

    success: bool = False
    image_path: str = ""
    source_frame_time: float = 0.0
    resolution: str = ""
    file_size: int = 0
    score: float = 0.0
    score_details: dict = field(default_factory=dict)
    candidates: list = field(default_factory=list)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ThumbnailGenerator クラス
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class ThumbnailGenerator:
    """S9: サムネイル生成ステージ。

    動画からフレームを抽出し、タイトルテキストを重ね合わせて
    サムネイル画像を生成する。

    複数箇所のフレームから品質（明るさ・コントラスト・エントロピー）を評価し、
    最適候補を自動選択する。

    フレーム抽出にはFFmpegを使用し、テキスト描画にはPillowを使用する。
    Pillow未インストール時はフレーム画像のみを返却する。

    FFmpeg呼び出しは _run_ffmpeg() メソッドに分離し、
    テスト時に safe_popen_mock でモック可能。

    Args:
        output_dir: サムネイル画像の出力ディレクトリ（省略時はカレントディレクトリ）
        design_tokens: デザイントークン辞書（フォント・色設定）
    """

    def __init__(
        self,
        output_dir: Optional[str] = None,
        design_tokens: Optional[dict] = None,
    ) -> None:
        """ThumbnailGeneratorを初期化する。

        Args:
            output_dir: サムネイル画像の出力ディレクトリ
            design_tokens: デザイントークン辞書
        """
        self.output_dir: str = output_dir or os.getcwd()
        self.design_tokens: dict = design_tokens or {
            "font_size": 72,
            "color": "#FFFFFF",
            "stroke_color": "#000000",
            "stroke_width": 3,
            "font_name": "arial.ttf",
        }
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    def generate_candidates(
        self, video_path: str, num_candidates: int = 5
    ) -> list[ThumbnailCandidate]:
        """動画から複数箇所のフレーム候補を抽出し、スコアリングして返却する。

        位置: 先頭/末尾を避けた割合（10%, 25%, 40%, 55%, 70%）

        Args:
            video_path: 動画ファイルのパス
            num_candidates: 抽出する候補数（デフォルト: 5）

        Returns:
            list[ThumbnailCandidate]: スコア降順でソートされたサムネイル候補リスト
        """
        if not os.path.exists(video_path):
            logger.error("動画ファイルが見つかりません: %s", video_path)
            return []

        try:
            duration = self._get_video_duration(video_path)
            positions = [0.10, 0.25, 0.40, 0.55, 0.70]
            if num_candidates != 5:
                if num_candidates <= 1:
                    positions = [DEFAULT_FRAME_POSITION]
                else:
                    start_p, end_p = 0.10, 0.70
                    step = (end_p - start_p) / (num_candidates - 1)
                    positions = [start_p + i * step for i in range(num_candidates)]

            candidates: list[ThumbnailCandidate] = []
            for idx, pos in enumerate(positions[:num_candidates]):
                timestamp = duration * pos
                suffix = f"_cand_{idx + 1}"
                frame_path = self._extract_frame(
                    video_path, timestamp, output_suffix=suffix
                )
                if not frame_path or not os.path.exists(frame_path):
                    continue

                score, score_details = self._score_frame(frame_path)
                file_size = os.path.getsize(frame_path)
                resolution = self._get_image_resolution(frame_path)

                candidate = ThumbnailCandidate(
                    image_path=frame_path,
                    source_frame_time=timestamp,
                    resolution=resolution,
                    file_size=file_size,
                    score=score,
                    score_details=score_details,
                )
                candidates.append(candidate)

            # スコア降順ソート
            candidates.sort(key=lambda c: c.score, reverse=True)
            return candidates

        except Exception:  # TDR登録済み: DP-02
            logger.exception("サムネイル候補生成中にエラーが発生")
            return []

    def generate(
        self, video_path: str, title: str = ""
    ) -> ThumbnailResult:
        """動画からサムネイル画像を生成する。

        複数候補の抽出・スコアリングを行い、最高スコアの候補を自動選択する。
        失敗時は従来の30%位置フレームにフォールバックする。

        Args:
            video_path: 動画ファイルのパス
            title: サムネイルに表示するタイトル（省略時はテキストなし）

        Returns:
            ThumbnailResult: サムネイル生成結果
        """
        logger.info("サムネイル生成開始: %s", video_path)

        try:
            if not os.path.exists(video_path):
                raise FileNotFoundError(f"Video file not found: {video_path}")

            candidates = self.generate_candidates(video_path, num_candidates=5)

            if candidates:
                best_candidate = candidates[0]
                output_path = best_candidate.image_path

                if title:
                    overlay_path = self._add_text_overlay(
                        best_candidate.image_path, title
                    )
                    if overlay_path:
                        output_path = overlay_path

                file_size = (
                    os.path.getsize(output_path)
                    if os.path.exists(output_path)
                    else best_candidate.file_size
                )
                resolution = (
                    self._get_image_resolution(output_path)
                    or best_candidate.resolution
                )

                logger.info(
                    "サムネイル生成完了 (最高スコア候補選択): %s (スコア: %.1f, %.1f秒地点, %s)",
                    output_path,
                    best_candidate.score,
                    best_candidate.source_frame_time,
                    resolution,
                )

                return ThumbnailResult(
                    success=True,
                    image_path=output_path,
                    source_frame_time=best_candidate.source_frame_time,
                    resolution=resolution,
                    file_size=file_size,
                    score=best_candidate.score,
                    score_details=best_candidate.score_details,
                    candidates=candidates,
                )

            # フォールバック: generate_candidates 失敗時または候補 0 件時は従来処理 (30%地点)
            logger.warning("候補生成なし、従来の30%%位置へフォールバック")
            duration = self._get_video_duration(video_path)
            timestamp = duration * DEFAULT_FRAME_POSITION

            frame_path = self._extract_frame(video_path, timestamp)
            if not frame_path or not os.path.exists(frame_path):
                logger.error("フレーム抽出に失敗: %s", video_path)
                return ThumbnailResult(
                    success=False,
                    source_frame_time=timestamp,
                )

            output_path = frame_path
            if title:
                overlay_path = self._add_text_overlay(frame_path, title)
                if overlay_path:
                    output_path = overlay_path

            file_size = (
                os.path.getsize(output_path) if os.path.exists(output_path) else 0
            )
            resolution = self._get_image_resolution(output_path)
            score, score_details = self._score_frame(output_path)

            logger.info(
                "サムネイル生成完了 (フォールバック): %s (%.1f秒地点, %s)",
                output_path,
                timestamp,
                resolution,
            )

            return ThumbnailResult(
                success=True,
                image_path=output_path,
                source_frame_time=timestamp,
                resolution=resolution,
                file_size=file_size,
                score=score,
                score_details=score_details,
            )

        except FileNotFoundError:
            logger.error("動画ファイルが見つかりません: %s", video_path)
            return ThumbnailResult(success=False)
        except Exception:  # TDR登録済み: DP-02
            logger.exception("サムネイル生成中に予期しないエラーが発生")
            return ThumbnailResult(success=False)

    def _score_frame(self, image_path: str) -> tuple[float, dict]:
        """画像の明るさ・コントラスト・エントロピーをスコアリングする。

        Pillow利用可能な場合は3指標で評価（各0-100、合計平均）
        - 明るさスコア (brightness): 理想輝度125 (50-200範囲内が高スコア)
        - コントラストスコア (contrast): 標準偏差が高いほど高スコア
        - 情報量スコア (entropy): エントロピーが高いほど高スコア

        Pillow未利用時またはエラー時はスコア50.0を返却する。

        Args:
            image_path: 画像ファイルのパス

        Returns:
            tuple[float, dict]: (総合スコア, スコア内訳)
        """
        default_score = 50.0
        default_details = {
            "brightness": 50.0,
            "contrast": 50.0,
            "entropy": 50.0,
        }

        if not self._is_pillow_available() or not os.path.exists(image_path):
            return default_score, default_details

        try:
            from PIL import Image  # type: ignore[import-untyped]

            with Image.open(image_path) as img:
                gray = img.convert("L")
                pixels = list(gray.getdata())
                if not pixels:
                    return default_score, default_details

                n = len(pixels)
                mean_val = sum(pixels) / n

                # a. 明るさスコア (brightness): 50-200 の範囲内が高スコア
                if 50 <= mean_val <= 200:
                    b_score = max(0.0, 100.0 - abs(mean_val - 125.0) * 0.45)
                elif mean_val < 50:
                    b_score = max(0.0, (mean_val / 50.0) * 60.0)
                else:  # mean_val > 200
                    b_score = max(0.0, ((255.0 - mean_val) / 55.0) * 60.0)

                # b. コントラストスコア (contrast): 標準偏差
                variance = sum((p - mean_val) ** 2 for p in pixels) / n
                std_dev = variance ** 0.5
                c_score = min(100.0, (std_dev / 64.0) * 100.0)

                # c. 情報量スコア (entropy): PILのentropy() (0.0 - 8.0)
                entropy_val = gray.entropy()
                e_score = min(100.0, (entropy_val / 7.0) * 100.0)

                total_score = round((b_score + c_score + e_score) / 3.0, 2)
                details = {
                    "brightness": round(b_score, 2),
                    "contrast": round(c_score, 2),
                    "entropy": round(e_score, 2),
                }
                return total_score, details

        except Exception:  # TDR登録済み: DP-02
            logger.exception("フレームスコアリング中にエラーが発生")
            return default_score, default_details

    def _extract_frame(
        self, video_path: str, timestamp: float, output_suffix: str = ""
    ) -> str:
        """FFmpegで動画から1フレームを抽出する。

        Args:
            video_path: 動画ファイルのパス
            timestamp: 抽出するフレームの時刻（秒）
            output_suffix: 出力ファイル名の接尾辞 (例: "_cand_1")

        Returns:
            抽出されたフレーム画像のパス。失敗時は空文字列
        """
        video_name = Path(video_path).stem
        output_path = os.path.join(
            self.output_dir, f"thumb_{video_name}{output_suffix}.jpg"
        )

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(timestamp),
            "-i", video_path,
            "-vframes", "1",
            "-q:v", "2",
            output_path,
        ]

        try:
            self._run_ffmpeg(cmd)
            if os.path.exists(output_path):
                return output_path
            return ""
        except subprocess.CalledProcessError:
            logger.error("フレーム抽出コマンドが失敗: %s", video_path)
            return ""

    def _add_text_overlay(self, image_path: str, text: str) -> str:
        """Pillowで画像にテキストオーバーレイを追加する。

        Pillow未インストール時はフレーム画像のパスをそのまま返却する。

        Args:
            image_path: ベース画像のパス
            text: オーバーレイするテキスト

        Returns:
            テキスト追加後の画像パス。Pillow未使用時はimage_path
        """
        if not self._is_pillow_available():
            logger.warning(
                "Pillowが利用不可のためテキストオーバーレイをスキップ"
            )
            return image_path

        try:
            from PIL import Image, ImageDraw, ImageFont  # type: ignore[import-untyped]

            img = Image.open(image_path)
            draw = ImageDraw.Draw(img)

            font_size = self.design_tokens.get("font_size", 72)
            color = self.design_tokens.get("color", "#FFFFFF")
            stroke_color = self.design_tokens.get("stroke_color", "#000000")
            stroke_width = self.design_tokens.get("stroke_width", 3)

            # フォント読み込み（失敗時はデフォルト）
            try:
                font = ImageFont.truetype(
                    self.design_tokens.get("font_name", "arial.ttf"),
                    font_size,
                )
            except (OSError, IOError):
                font = ImageFont.load_default()

            # テキスト位置: 画像中央下部
            img_w, img_h = img.size
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            x = (img_w - text_w) // 2
            y = img_h - text_h - 40

            # ストローク付きテキスト描画
            draw.text(
                (x, y), text, fill=color, font=font,
                stroke_width=stroke_width, stroke_fill=stroke_color,
            )

            # 上書き保存
            output_path = image_path.replace(".jpg", "_titled.jpg")
            img.save(output_path, "JPEG", quality=95)
            return output_path

        except Exception:  # TDR登録済み: DP-02
            logger.exception("テキストオーバーレイ中にエラーが発生")
            return image_path

    def _get_video_duration(self, video_path: str) -> float:
        """ffprobeで動画の長さ（秒）を取得する。

        Args:
            video_path: 動画ファイルのパス

        Returns:
            動画の長さ（秒）。取得失敗時は 10.0（安全なデフォルト値）
        """
        cmd = [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "json",
            video_path,
        ]
        try:
            result = self._run_ffmpeg(cmd)
            data = json.loads(result.stdout)
            return float(data.get("format", {}).get("duration", 10.0))
        except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError):
            logger.warning("ffprobeによる動画長取得に失敗: %s (デフォルト10秒)", video_path)
            return 10.0

    def _get_image_resolution(self, image_path: str) -> str:
        """画像の解像度を取得する。

        Pillow利用可能な場合はPillowで取得し、不可の場合は空文字列を返す。

        Args:
            image_path: 画像ファイルのパス

        Returns:
            解像度文字列 (例: "1920x1080")。取得失敗時は空文字列
        """
        if not self._is_pillow_available():
            return ""

        try:
            from PIL import Image  # type: ignore[import-untyped]
            with Image.open(image_path) as img:
                return f"{img.width}x{img.height}"
        except Exception:  # TDR登録済み: DP-02
            return ""

    @staticmethod
    def _is_pillow_available() -> bool:
        """Pillow (PIL) が利用可能かどうかを動的にチェックする。

        Returns:
            Pillowがインポート可能であれば True
        """
        try:
            from PIL import Image  # type: ignore[import-untyped] # noqa: F401
            return True
        except ImportError:
            return False

    def _run_ffmpeg(self, cmd: list[str]) -> subprocess.CompletedProcess:
        """FFmpeg/ffprobeコマンドを実行する。

        テスト時は safe_popen_mock でこのメソッドをモックすることで、
        実際のFFmpeg実行を回避できる。

        subprocess.Popenモック安全規約:
          - poll() は return_value=0 で即座に終了コードを返すこと
          - readline() は空文字列 "" を返すこと

        Args:
            cmd: 実行するコマンドのリスト

        Returns:
            subprocess.CompletedProcess: 実行結果

        Raises:
            subprocess.CalledProcessError: コマンドが非ゼロ終了した場合
        """
        logger.info("FFmpegコマンド実行: %s", " ".join(cmd))
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        logger.info("FFmpegコマンド完了 (returncode=%d)", result.returncode)
        return result


if __name__ == "__main__":
    # 動作確認用のサンプルコード
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) < 2:
        print("使用方法: python thumbnail_generator.py <動画ファイルパス> [タイトル]")
        sys.exit(1)

    video_file = sys.argv[1]
    title_text = sys.argv[2] if len(sys.argv) >= 3 else ""

    generator = ThumbnailGenerator(output_dir="./thumbnail_output")
    result = generator.generate(video_file, title=title_text)
    print(f"サムネイル生成結果: success={result.success}, "
          f"path={result.image_path}, score={result.score}, "
          f"resolution={result.resolution}")
