"""
subtitle_generator.py — S4: 字幕生成

文字起こし結果（TranscriptResult）からSRT字幕ファイルを生成するパイプラインステージ。
1行あたりの最大文字数を制限し、句読点・助詞の後で自動改行する。

subprocess.Popenモック安全規約:
  - poll() は return_value=0 で即座に終了コードを返すこと
  - readline() は空文字列 "" を返すこと
  - conftest.py の safe_popen_mock fixture を使用すること
"""

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from backend.video_pipeline.transcription_service import TranscriptResult

logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 定数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 句読点・助詞など、改行の候補位置
BREAK_AFTER_CHARS = set("、。！？!?）」』】")
BREAK_AFTER_PARTICLES = ("は", "が", "を", "に", "で", "と", "の", "も", "へ")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# データクラス定義
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class SubtitleResult:
    """字幕生成結果。

    Attributes:
        success: 生成成功フラグ
        output_path: 生成されたSRTファイルのパス
        entry_count: 字幕エントリ数
        issues: 生成中に検出された問題のリスト
    """

    success: bool = False
    output_path: str = ""
    entry_count: int = 0
    issues: list[str] = field(default_factory=list)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SubtitleGenerator クラス
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class SubtitleGenerator:
    """S4: 字幕生成ステージ。

    TranscriptResult を受け取り、SRT形式の字幕ファイルを出力する。
    1行あたりの文字数制限を適用し、句読点・助詞の後で自動改行する。

    Args:
        max_chars_per_line: 1行あたりの最大文字数（デフォルト: 13）
    """

    def __init__(self, max_chars_per_line: int = 13) -> None:
        """SubtitleGeneratorを初期化する。

        Args:
            max_chars_per_line: 1行あたりの最大文字数
        """
        if max_chars_per_line < 1:
            raise ValueError("max_chars_per_line must be at least 1")
        self.max_chars_per_line: int = max_chars_per_line

    def generate_srt(
        self, transcript: TranscriptResult, output_path: str
    ) -> SubtitleResult:
        """TranscriptResultからSRTファイルを生成する。

        Args:
            transcript: 文字起こし結果
            output_path: 出力SRTファイルのパス

        Returns:
            SubtitleResult: 字幕生成結果
        """
        if transcript is None:
            raise ValueError("transcript cannot be None")

        issues: list[str] = []

        if not transcript.success:
            logger.warning("文字起こし結果が失敗状態のため字幕生成をスキップ")
            return SubtitleResult(
                success=False,
                output_path=output_path,
                issues=["文字起こし結果が失敗状態です"],
            )

        if not transcript.segments:
            logger.warning("文字起こしセグメントが空のため字幕生成をスキップ")
            return SubtitleResult(
                success=False,
                output_path=output_path,
                issues=["文字起こしセグメントが空です"],
            )

        try:
            # 出力ディレクトリを作成
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            srt_entries: list[str] = []
            entry_idx = 1
            for segment in transcript.segments:
                # 空テキストはスキップ
                if not segment.text or not segment.text.strip():
                    logger.info("空のセグメントをスキップします: start=%s, end=%s", segment.start, segment.end)
                    continue

                start_tc = self._format_timecode(segment.start)
                end_tc = self._format_timecode(segment.end)

                # タイムコードフォーマット検証
                if not self.validate_timecode_format(start_tc) or not self.validate_timecode_format(end_tc):
                    raise ValueError(f"タイムコードの形式が不正です: start={start_tc}, end={end_tc}")

                # テキストを自動改行
                lines = self._split_text(segment.text)
                text_block = "\n".join(lines)

                # 文字数超過の警告
                for line in lines:
                    if len(line) > self.max_chars_per_line:
                        msg = (
                            f"エントリ{entry_idx}: 行が{len(line)}文字 "
                            f"(上限{self.max_chars_per_line}文字)"
                        )
                        issues.append(msg)
                        logger.warning(msg)

                srt_entries.append(
                    f"{entry_idx}\n{start_tc} --> {end_tc}\n{text_block}\n"
                )
                entry_idx += 1

            srt_content = "\n".join(srt_entries)

            with open(output_path, "w", encoding="utf-8") as f:
                f.write(srt_content)

            entry_count = len(srt_entries)
            logger.info("SRTファイル生成完了: %s (%d エントリ)",
                         output_path, entry_count)

            return SubtitleResult(
                success=True,
                output_path=output_path,
                entry_count=entry_count,
                issues=issues,
            )

        except OSError as e:
            logger.error("SRTファイルの書き込みに失敗: %s", e)
            return SubtitleResult(
                success=False,
                output_path=output_path,
                issues=[f"ファイル書き込みエラー: {e}"],
            )
        except Exception:  # TDR登録済み: DP-02
            logger.exception("字幕生成中に予期しないエラーが発生")
            return SubtitleResult(
                success=False,
                output_path=output_path,
                issues=["予期しないエラーが発生しました"],
            )
    def validate_timecode_format(self, timecode: str) -> bool:
        """タイムコード形式 (HH:MM:SS,mmm) を検証する。

        Args:
            timecode: 検証対象のタイムコード文字列

        Returns:
            形式が正しい場合は True、それ以外は False
        """
        pattern = r"^\d{2}:\d{2}:\d{2},\d{3}$"
        return bool(re.match(pattern, timecode))

    def _format_timecode(self, seconds: float) -> str:
        """秒数をSRTタイムコード形式に変換する。

        Args:
            seconds: 秒数

        Returns:
            SRTタイムコード文字列 (例: "00:01:23,456")
        """
        if seconds < 0:
            seconds = 0.0

        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)

        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def _split_text(self, text: str) -> list[str]:
        """テキストをmax_chars_per_lineに従って自動改行する。

        句読点（、。！？）や助詞（は、が、を等）の後で優先的に分割する。

        Args:
            text: 分割対象のテキスト

        Returns:
            分割された行のリスト
        """
        if not text:
            return [""]

        if len(text) <= self.max_chars_per_line:
            return [text]

        lines: list[str] = []
        remaining = text

        while remaining:
            if len(remaining) <= self.max_chars_per_line:
                lines.append(remaining)
                break

            # max_chars_per_line以内で最適な分割位置を探す
            best_split = self.max_chars_per_line
            search_range = remaining[: self.max_chars_per_line]

            # 句読点での分割を優先
            for i in range(len(search_range) - 1, 0, -1):
                if search_range[i] in BREAK_AFTER_CHARS:
                    best_split = i + 1
                    break
            else:
                # 助詞での分割を試みる
                for i in range(len(search_range) - 1, 0, -1):
                    if search_range[i] in BREAK_AFTER_PARTICLES:
                        best_split = i + 1
                        break

            lines.append(remaining[:best_split])
            remaining = remaining[best_split:]

        return lines


if __name__ == "__main__":
    # 動作確認用のサンプルコード
    import sys

    from backend.video_pipeline.transcription_service import (
        TranscriptResult,
        TranscriptSegment,
    )

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # テスト用の文字起こし結果を作成
    sample_transcript = TranscriptResult(
        success=True,
        segments=[
            TranscriptSegment(start=0.0, end=3.0, text="こんにちは、今日はPythonの紹介です。"),
            TranscriptSegment(start=3.0, end=6.0, text="とても便利な言語です。"),
        ],
        language="ja",
        model_used="test",
        duration_seconds=1.0,
    )

    generator = SubtitleGenerator(max_chars_per_line=13)
    output = "./test_output.srt"
    result = generator.generate_srt(sample_transcript, output)
    print(f"字幕生成結果: success={result.success}, entries={result.entry_count}")
    if result.issues:
        print(f"問題: {result.issues}")
