"""日本語フォントの解決を一箇所に集約する。

## なぜ必要か

2026-07-25 時点で、日本語フォントのパスが 24 ファイルに個別ハードコードされて
いた。多くは `C:\\Windows\\Fonts\\YuGothB.ttc` のような Windows 決め打ちで、
フォールバックを持つものも Fedora/RHEL 系のパスしか知らなかった。

その結果、CI(Ubuntu) で `OSError: cannot open resource` /
`OSError: Failed to load any premium fonts` が 12 件発生していた。
ローカル(Windows) では常に成功するため、CI を回すまで露見しなかった。

新しくフォントを使うコードは、パスを直書きせずこのモジュールを使うこと。

## 使い方

    from font_resolver import load_japanese_font

    font = load_japanese_font(20)          # 見つからなければ OSError
    font = load_japanese_font(20, bold=True)
    font = load_japanese_font(20, fallback_to_default=True)  # 最終手段で既定フォント
"""

from __future__ import annotations

import platform
from pathlib import Path

from PIL import ImageFont

# 優先度順。先頭ほど品質が高い想定。
# 既存テストが Windows のフォールバック順（YuGothB → meiryob → msgothic）を
# 検証しているため、Windows 分は3つまとめて先頭に置くこと。
_BOLD_CANDIDATES: tuple[str, ...] = (
    # Windows
    r"C:\Windows\Fonts\YuGothB.ttc",
    r"C:\Windows\Fonts\meiryob.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    # Linux — Debian/Ubuntu の fonts-noto-cjk（GitHub Actions はここ）
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    # Linux — Fedora/RHEL
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    # Linux — fonts-ipafont 等
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
)

_REGULAR_CANDIDATES: tuple[str, ...] = (
    # Windows
    r"C:\Windows\Fonts\msgothic.ttc",
    r"C:\Windows\Fonts\YuGothR.ttc",
    r"C:\Windows\Fonts\meiryo.ttc",
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    # Linux
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    # 日本語非対応だがラテン文字は描画できる最終手段
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def candidate_paths(bold: bool = False) -> tuple[str, ...]:
    """探索するフォントパスの一覧を返す（テストや診断用）。"""
    return _BOLD_CANDIDATES + _REGULAR_CANDIDATES if bold else _REGULAR_CANDIDATES


def find_japanese_font_path(bold: bool = False) -> str | None:
    """実在する日本語フォントのパスを1つ返す。見つからなければ None。"""
    for path in candidate_paths(bold):
        try:
            if Path(path).is_file():
                return path
        except OSError:
            continue
    return None


def load_japanese_font(
    size: int,
    *,
    bold: bool = False,
    fallback_to_default: bool = False,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """日本語フォントを読み込む。

    Args:
        size: フォントサイズ（px）
        bold: 太字を優先する
        fallback_to_default: 全滅時に PIL の既定フォントを返す。
            既定フォントはサイズ指定が効かず日本語も出ないため、
            描画結果の品質が要件でない場面でのみ使うこと。

    Raises:
        OSError: フォントが1つも見つからず fallback_to_default が False のとき
    """
    for path in candidate_paths(bold):
        try:
            if Path(path).is_file():
                return ImageFont.truetype(path, size)
        except (OSError, ValueError):
            # 実在しても壊れている・非対応形式のことがあるので次を試す
            continue

    if fallback_to_default:
        return ImageFont.load_default()

    raise OSError(
        f"日本語フォントが見つかりません (platform={platform.system()}, bold={bold})。"
        f"探索したパス: {', '.join(candidate_paths(bold))}"
    )
