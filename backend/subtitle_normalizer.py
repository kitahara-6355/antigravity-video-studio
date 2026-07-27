"""
字幕正規化パイプライン
Phase 1: Foundation

機能:
- Whisper出力の正規化
- 固有名詞辞書の適用
- 不確実語句の自動抽出
- SRTエクスポート
"""

import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass

from dotenv import load_dotenv
from gemini_client_factory import get_gemini_client
from google.genai.errors import APIError

# Model Registry使用
from model_registry import get_model
from proper_noun_dict import proper_noun_dict, apply_dictionary

load_dotenv()
logger = logging.getLogger(__name__)


@dataclass
class NormalizedSegment:
    """正規化されたセグメント"""
    id: str
    start: float
    end: float
    original_text: str
    normalized_text: str
    corrections: List[Dict]
    speaker: Optional[str] = None
    confidence: float = 1.0


@dataclass
class UncertainItem:
    """不確実語句"""
    original: str
    candidates: List[str]
    context: str
    segment_id: str
    confidence: float


class SubtitleNormalizer:
    """字幕正規化クラス"""

    NORMALIZE_PROMPT = """
以下の音声認識結果を正しい日本語に修正してください。

## 修正対象
- 誤字脱字
- 文法エラー
- フィラー（えー、あのー等）の除去
- 句読点の適正化

## 固有名詞について
以下の固有名詞は正確に表記してください：
{proper_nouns}

## 不確実な語句
自信がない箇所は uncertain_items として出力してください。

## 入力
{segments}

## 出力形式（JSON）
{{
  "normalized_segments": [
    {{"id": "seg_001", "text": "修正後テキスト"}},
    ...
  ],
  "uncertain_items": [
    {{"original": "認識テキスト", "candidates": ["候補1", "候補2"], "context": "前後文脈", "segment_id": "seg_001", "confidence": 0.6}},
    ...
  ]
}}
"""

    def __init__(self):
        self._client = None
        self._model = None

    @property
    def client(self):
        if self._client is None:
            self._client = get_gemini_client()
        return self._client

    @property
    def model(self):
        if self._model is None:
            self._model = get_model("subtitle_split")
        return self._model

    def normalize(self, whisper_segments: List[Dict], apply_dict: bool = True) -> Dict:
        """
        Whisperセグメントを正規化

        Args:
            whisper_segments: Whisper出力 of segments
            apply_dict: 固有名詞辞書を適用するか

        Returns:
            {
                "normalized_segments": [...],
                "uncertain_items": [...],
                "stats": {...}
            }
        """
        proper_nouns = proper_noun_dict.get_all_entries()
        prompt = self._build_normalize_prompt(whisper_segments, proper_nouns)

        result = self._execute_ai_normalization(prompt, whisper_segments)

        # 辞書適用
        if apply_dict:
            result = self._apply_dictionary(result, whisper_segments)

        # 統計情報
        result["stats"] = self._calculate_stats(whisper_segments, result)

        logger.info(f"字幕正規化完了: {result['stats']}")
        return result

    def _build_normalize_prompt(self, whisper_segments: List[Dict], proper_nouns: List[Dict]) -> str:
        """正規化のためのAIプロンプトを構築"""
        proper_nouns_text = "\n".join([
            f"- {entry['incorrect']} → {entry['correct']}" for entry in proper_nouns
        ])

        segments_text = "\n".join([
            f"[{segment.get('id', f'seg_{index:03d}')}] {segment.get('text', '')}"
            for index, segment in enumerate(whisper_segments)
        ])

        return self.NORMALIZE_PROMPT.format(
            proper_nouns=proper_nouns_text or "（なし）",
            segments=segments_text
        )

    def _execute_ai_normalization(self, prompt: str, whisper_segments: List[Dict]) -> Dict:
        """AIモデルを実行し、結果をパースする。エラー時はフォールバックする。"""
        if self.client is None:
            logger.warning("Geminiクライアントが未設定のため、フォールバック正規化を実行します")
            return self._fallback_normalize(whisper_segments)
            
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt
            )
            return self._parse_response(response.text)
        except APIError as e:
            logger.error(f"Gemini APIエラー: {e}")
            return self._fallback_normalize(whisper_segments)
        except ValueError as e:
            logger.error(f"API引数エラー: {e}")
            return self._fallback_normalize(whisper_segments)

    def _calculate_stats(self, whisper_segments: List[Dict], result: Dict) -> Dict:
        """統計情報を計算"""
        normalized_segments = result.get("normalized_segments") or []
        uncertain_items = result.get("uncertain_items") or []

        corrections_made = sum(
            len(segment.get("corrections") or []) for segment in normalized_segments
        )

        return {
            "total_segments": len(whisper_segments),
            "normalized_segments": len(normalized_segments),
            "uncertain_items": len(uncertain_items),
            "corrections_made": corrections_made
        }

    def _parse_response(self, text: str) -> Dict:
        """AIレスポンスをパース。パース失敗時は ValueError を発生させてフォールバックを促す。"""
        # JSON抽出
        json_match = re.search(r'\{[\s\S]*\}', text)
        if not json_match:
            raise ValueError("AI response does not contain a valid JSON block")
            
        try:
            data = json.loads(json_match.group())
            if not isinstance(data, dict) or "normalized_segments" not in data:
                raise ValueError("AI response JSON is missing 'normalized_segments' key")
            return data
        except json.JSONDecodeError as e:
            raise ValueError(f"AI response JSON is corrupt: {e}")

    def _fallback_normalize(self, segments: List[Dict]) -> Dict:
        """フォールバック正規化（辞書適用のみ）"""
        normalized = []
        for index, segment in enumerate(segments):
            segment_id = segment.get("id", f"seg_{index:03d}")
            text = segment.get("text", "")
            corrected, corrections = apply_dictionary(text)
            normalized.append({
                "id": segment_id,
                "text": corrected,
                "original_text": text,
                "corrections": corrections
            })
        return {"normalized_segments": normalized, "uncertain_items": []}

    def _apply_dictionary(self, result: Dict, original_segments: List[Dict]) -> Dict:
        """辞書を適用"""
        for segment in result.get("normalized_segments") or []:
            text = segment.get("text") or ""
            corrected, corrections = apply_dictionary(text)
            segment["text"] = corrected
            segment["corrections"] = (segment.get("corrections") or []) + corrections
        return result


class SRTExporter:
    """SRTファイルエクスポーター"""

    @classmethod
    def _get_value(cls, segment: Any, key: str, default: Any = None) -> Any:
        """セグメントから辞書・オブジェクト両対応で値を取得"""
        if isinstance(segment, dict):
            return segment.get(key, default)
        return getattr(segment, key, default)

    @staticmethod
    def format_timestamp(seconds: float) -> str:
        """秒をSRT形式のタイムスタンプに変換"""
        if seconds is None or seconds < 0:
            seconds = 0.0
        total_millis = int(round(seconds * 1000))
        hours = total_millis // 3600000
        minutes = (total_millis % 3600000) // 60000
        secs = (total_millis % 60000) // 1000
        millis = total_millis % 1000
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    @classmethod
    def _format_cue_timestamps(cls, segment: Any, is_vtt: bool = False) -> Tuple[str, str]:
        """セグメントから開始時間・終了時間のタイムスタンプ文字列を取得"""
        start_seconds = cls._get_value(segment, "start", 0.0)
        end_seconds = cls._get_value(segment, "end", 0.0)

        if start_seconds is None:
            start_seconds = 0.0
        if end_seconds is None:
            end_seconds = 0.0

        start_ts = cls.format_timestamp(start_seconds)
        end_ts = cls.format_timestamp(end_seconds)

        if is_vtt:
            start_ts = start_ts.replace(",", ".")
            end_ts = end_ts.replace(",", ".")

        return start_ts, end_ts

    @classmethod
    def _extract_cue_text(cls, segment: Any) -> str:
        """セグメントから字幕テキストを取得"""
        text = cls._get_value(segment, "text")
        if text is None:
            text = cls._get_value(segment, "normalized_text")
        if text is None:
            text = ""
        return text

    @classmethod
    def _generate_cue_lines(cls, segment: Any, index: int, is_vtt: bool = False) -> List[str]:
        """セグメントからSRT/VTT of キュー（インデックス、時間範囲、テキスト）を表す行リストを生成"""
        start_ts, end_ts = cls._format_cue_timestamps(segment, is_vtt=is_vtt)
        text = cls._extract_cue_text(segment)

        return [
            str(index),
            f"{start_ts} --> {end_ts}",
            text,
            ""
        ]

    @classmethod
    def _write_file_content(cls, lines: List[str], output_path: Path) -> None:
        """行リストを指定されたファイルに書き込む"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    @classmethod
    def export(cls, segments: List[Dict], output_path: Path) -> Path:
        """
        セグメントをSRTファイルにエクスポート

        Args:
            segments: 正規化されたセグメントリスト
            output_path: 出力ファイルパス

        Returns:
            出力ファイルパス
        """
        lines = []
        for index, segment in enumerate(segments, 1):
            lines.extend(cls._generate_cue_lines(segment, index, is_vtt=False))

        cls._write_file_content(lines, output_path)
        logger.info(f"SRTエクスポート完了: {output_path}")
        return output_path

    @classmethod
    def export_vtt(cls, segments: List[Dict], output_path: Path) -> Path:
        """WebVTT形式でエクスポート"""
        lines = ["WEBVTT", ""]
        for index, segment in enumerate(segments, 1):
            lines.extend(cls._generate_cue_lines(segment, index, is_vtt=True))

        cls._write_file_content(lines, output_path)
        logger.info(f"VTTエクスポート完了: {output_path}")
        return output_path


# シングルトンインスタンス
subtitle_normalizer = SubtitleNormalizer()
srt_exporter = SRTExporter()


def normalize_subtitles(whisper_segments: List[Dict]) -> Dict:
    """字幕を正規化（簡易関数）"""
    return subtitle_normalizer.normalize(whisper_segments)


def export_srt(segments: List[Dict], output_path: Path) -> Path:
    """SRTエクスポート（簡易関数）"""
    return srt_exporter.export(segments, output_path)

