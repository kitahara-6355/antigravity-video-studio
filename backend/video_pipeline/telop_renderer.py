"""
telop_renderer.py — S6: テロップ画像生成

テキストからテロップ画像（PNG）を生成するパイプラインステージ。
Pillow (PIL) でテキスト画像を描画する。Pillow未インストール時は
最小限の空PNGを生成するフォールバックを行う。

design_tokens.json からフォント・色を取得し、
standard / emphasis / subtitle の3スタイルに対応する。

subprocess.Popenモック安全規約:
  - poll() は return_value=0 で即座に終了コードを返すこと
  - readline() は空文字列 "" を返すこと
  - conftest.py の safe_popen_mock fixture を使用すること
"""

import logging
import os
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 定数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DEFAULT_DESIGN_TOKENS: dict = {
    "standard": {
        "font_size": 48,
        "color": "#FFFFFF",
        "bg_color": "#000000CC",
        "font_name": "arial.ttf",
    },
    "emphasis": {
        "font_size": 64,
        "color": "#FFD700",
        "bg_color": "#CC0000DD",
        "font_name": "arial.ttf",
    },
    "subtitle": {
        "font_size": 36,
        "color": "#FFFFFF",
        "bg_color": "#00000099",
        "font_name": "arial.ttf",
    },
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# データクラス定義
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class TelopResult:
    """テロップ画像生成結果。

    Attributes:
        success: 生成成功フラグ
        image_path: 生成された画像ファイルのパス
        text: テロップテキスト
        width: 画像幅（ピクセル）
        height: 画像高さ（ピクセル）
        style: 適用されたスタイル名
    """

    success: bool = False
    image_path: str = ""
    text: str = ""
    width: int = 0
    height: int = 0
    style: str = ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TelopRenderer クラス
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TelopRenderer:
    """S6: テロップ画像生成ステージ。

    テキストからテロップ画像を生成する。
    Pillow (PIL) を使用してテキスト画像を描画し、PNG形式で保存する。
    Pillow未インストール時は空のPNGを生成するフォールバックを行う。

    3スタイル対応:
      - standard: 白テキスト + 半透明黒背景
      - emphasis: 金テキスト + 半透明赤背景
      - subtitle: 白テキスト + 薄い半透明黒背景

    Args:
        design_tokens: スタイル定義の辞書（省略時はデフォルト値を使用）
        output_dir: テロップ画像の出力ディレクトリ（省略時はカレントディレクトリ）
    """

    def __init__(
        self,
        design_tokens: Optional[dict] = None,
        output_dir: Optional[str] = None,
    ) -> None:
        """TelopRendererを初期化する。

        Args:
            design_tokens: スタイル定義の辞書
            output_dir: テロップ画像の出力ディレクトリ
        """
        self.design_tokens: dict = design_tokens or DEFAULT_DESIGN_TOKENS
        self.output_dir: str = output_dir or os.getcwd()
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    def render_telop(
        self, text: str, style: str = "standard"
    ) -> TelopResult:
        """テロップ画像を1枚生成する。

        Args:
            text: テロップテキスト
            style: スタイル名 ("standard", "emphasis", "subtitle")

        Returns:
            TelopResult: テロップ画像生成結果
        """
        if text is None or not str(text).strip():
            logger.warning("空のテロップテキストが指定されました。画像生成をスキップします。")
            return TelopResult(
                success=False,
                image_path="",
                text=text if text is not None else "",
                style=style,
            )

        if style not in self.design_tokens:
            logger.warning(
                "未知のスタイル '%s' が指定されました。'standard' を使用します", style
            )
            style = "standard"

        tokens = self.design_tokens[style]
        font_size = tokens.get("font_size", 48)
        color = tokens.get("color", "#FFFFFF")
        bg_color = tokens.get("bg_color", "#000000CC")

        # ファイル名をテキストのハッシュから生成
        text_hash = abs(hash(text)) % (10**8)
        filename = f"telop_{style}_{text_hash:08d}.png"
        output_path = os.path.join(self.output_dir, filename)

        logger.info("テロップ生成: style=%s, text='%s'", style, text[:20])

        try:
            image_path = self._create_text_image(
                text, font_size, color, bg_color
            )
            # _create_text_image が一時パスに生成するので最終パスに移動
            if image_path != output_path:
                os.replace(image_path, output_path)

            # 画像サイズを推定（Pillow使用時は正確、フォールバック時は概算）
            width = max(len(text) * font_size, 200)
            height = font_size + 40

            return TelopResult(
                success=True,
                image_path=output_path,
                text=text,
                width=width,
                height=height,
                style=style,
            )

        except (OSError, ValueError) as e:
            logger.exception("テロップ画像生成中にエラーが発生: %s", e)
            return TelopResult(
                success=False,
                image_path="",
                text=text,
                style=style,
            )

    def render_batch(
        self, texts: list[str], style: str = "standard"
    ) -> list[TelopResult]:
        """テロップ画像を一括生成する。

        Args:
            texts: テロップテキストのリスト
            style: スタイル名 ("standard", "emphasis", "subtitle")

        Returns:
            テロップ画像生成結果のリスト
        """
        logger.info("テロップ一括生成開始: %d 件 (style=%s)", len(texts), style)
        results: list[TelopResult] = []

        for text in texts:
            result = self.render_telop(text, style)
            results.append(result)

        success_count = sum(1 for r in results if r.success)
        logger.info(
            "テロップ一括生成完了: %d/%d 成功", success_count, len(results)
        )
        return results

    def _create_text_image(
        self, text: str, font_size: int, color: str, bg_color: str
    ) -> str:
        """テキスト画像をPNG形式で生成する。

        Pillow (PIL) が利用可能な場合はそれを使用し、
        利用不可の場合は最小限の空PNGを生成する。

        Args:
            text: 描画するテキスト
            font_size: フォントサイズ（ピクセル）
            color: テキスト色 (例: "#FFFFFF")
            bg_color: 背景色 (例: "#000000CC")

        Returns:
            生成されたPNGファイルのパス
        """
        text_hash = abs(hash(text)) % (10**8)
        tmp_path = os.path.join(self.output_dir, f"_tmp_{text_hash:08d}.png")

        if self._is_pillow_available():
            return self._create_with_pillow(
                text, font_size, color, bg_color, tmp_path
            )
        else:
            logger.warning(
                "Pillowが利用不可のためフォールバック空PNGを生成"
            )
            return self._create_empty_png(tmp_path)

    def _create_with_pillow(
        self,
        text: str,
        font_size: int,
        color: str,
        bg_color: str,
        output_path: str,
    ) -> str:
        """Pillowでテキスト画像を生成する。

        Args:
            text: 描画するテキスト
            font_size: フォントサイズ
            color: テキスト色
            bg_color: 背景色
            output_path: 出力パス

        Returns:
            生成されたPNGファイルのパス
        """
        from PIL import Image, ImageDraw, ImageFont  # type: ignore[import-untyped]

        # 画像サイズを計算
        padding = 20
        width = max(len(text) * font_size + padding * 2, 200)
        height = font_size + padding * 2

        # 背景色をパース（RGBA対応）
        bg_rgba = self._parse_color(bg_color)
        img = Image.new("RGBA", (width, height), bg_rgba)
        draw = ImageDraw.Draw(img)

        # フォント読み込み（失敗時はデフォルト）
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except (OSError, IOError):
            font = ImageFont.load_default()

        text_color = self._parse_color(color)
        draw.text((padding, padding // 2), text, fill=text_color, font=font)
        img.save(output_path, "PNG")

        return output_path

    def _create_empty_png(self, output_path: str) -> str:
        """最小限の空PNGファイルを生成する（Pillowフォールバック用）。

        1x1ピクセルの透明PNGを生成する。

        Args:
            output_path: 出力パス

        Returns:
            生成されたPNGファイルのパス
        """
        # 1x1 透明 PNG を手動で構築
        def _make_chunk(chunk_type: bytes, data: bytes) -> bytes:
            chunk = chunk_type + data
            crc = struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)
            return struct.pack(">I", len(data)) + chunk + crc

        signature = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
        ihdr = _make_chunk(b"IHDR", ihdr_data)
        raw_data = zlib.compress(b"\x00\x00\x00\x00\x00")
        idat = _make_chunk(b"IDAT", raw_data)
        iend = _make_chunk(b"IEND", b"")

        with open(output_path, "wb") as f:
            f.write(signature + ihdr + idat + iend)

        return output_path

    @staticmethod
    def _parse_color(color_str: str) -> tuple:
        """色文字列をRGBAタプルに変換する。

        Args:
            color_str: 色文字列 (例: "#FFFFFF", "#000000CC")

        Returns:
            RGBAタプル (例: (255, 255, 255, 255))
        """
        color_str = color_str.lstrip("#")
        if len(color_str) == 6:
            r, g, b = int(color_str[0:2], 16), int(color_str[2:4], 16), int(color_str[4:6], 16)
            return (r, g, b, 255)
        elif len(color_str) == 8:
            r, g, b = int(color_str[0:2], 16), int(color_str[2:4], 16), int(color_str[4:6], 16)
            a = int(color_str[6:8], 16)
            return (r, g, b, a)
        else:
            return (255, 255, 255, 255)

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


if __name__ == "__main__":
    # 動作確認用のサンプルコード
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    renderer = TelopRenderer(output_dir="./telop_output")

    # 単体生成
    result = renderer.render_telop("テスト テロップ", style="standard")
    print(f"テロップ生成結果: success={result.success}, path={result.image_path}")

    # 一括生成
    texts = ["こんにちは", "重要なポイント", "まとめ"]
    results = renderer.render_batch(texts, style="emphasis")
    for r in results:
        print(f"  text='{r.text}', success={r.success}")
