"""
stable_ts_wrapper.py — stable-ts (stable-whisper) 字幕同期エンジンラッパー

WyattBlue/stable-ts を呼び出し、精度の高い文字起こしおよびタイムスタンプ調整 (refine) を行う。
遅延インポートとフォールバック処理を備え、モジュール未存在時でも安全に動く設計。
"""

import logging
import os
from typing import Optional, List

from backend.video_pipeline.transcription_service import TranscriptSegment

logger = logging.getLogger(__name__)


class StableTsWrapper:
    """stable-ts (stable-whisper) 字幕同期ラッパークラス。

    Attributes:
        model_name: 使用するWhisperモデル名 (例: "base", "small")
        language: 対象言語コード (例: "ja")
    """

    def __init__(self, model_name: str = "base", language: str = "ja") -> None:
        """StableTsWrapperを初期化する。

        Args:
            model_name: Whisperモデル名
            language: 言語コード
        """
        self.model_name: str = model_name
        self.language: str = language

    @staticmethod
    def is_available() -> bool:
        """stable_whisperが利用可能かどうかをチェックする。

        Returns:
            bool: インポート可能であれば True
        """
        try:
            import stable_whisper  # noqa: F401
            return True
        except ImportError:
            return False

    def transcribe(self, audio_path: str) -> List[TranscriptSegment]:
        """audio_path から文字起こしを行い、TranscriptSegmentのリストを返す。

        Args:
            audio_path: 音声ファイルパス

        Returns:
            List[TranscriptSegment]: 文字起こしセグメントのリスト
        """
        if not self.is_available():
            logger.warning("stable_whisper がインストールされていないため transcribe をスキップします")
            return []

        if not os.path.exists(audio_path):
            logger.error(f"音声ファイルが存在しません: {audio_path}")
            return []

        try:
            import stable_whisper

            logger.info(f"stable-ts で文字起こし中 (model={self.model_name}, lang={self.language}): {audio_path}")
            model = stable_whisper.load_model(self.model_name)
            result = model.transcribe(audio_path, language=self.language)

            segments: List[TranscriptSegment] = []
            raw_segments = getattr(result, "segments", [])
            if not raw_segments and isinstance(result, list):
                raw_segments = result

            for seg in raw_segments:
                start = getattr(seg, "start", 0.0)
                end = getattr(seg, "end", 0.0)
                text = getattr(seg, "text", "").strip()
                
                # confidence の取得（MagicMock対策を含む）
                confidence = 0.0
                if hasattr(seg, "confidence") and not callable(getattr(seg, "confidence")):
                    val = getattr(seg, "confidence")
                    if isinstance(val, (int, float)):
                        confidence = float(val)
                if confidence == 0.0 and hasattr(seg, "avg_logprob") and not callable(getattr(seg, "avg_logprob")):
                    val = getattr(seg, "avg_logprob")
                    if isinstance(val, (int, float)):
                        confidence = float(val)

                segments.append(
                    TranscriptSegment(
                        start=float(start),
                        end=float(end),
                        text=str(text),
                        confidence=confidence,
                    )
                )

            return segments

        except Exception as e:
            logger.exception(f"stable-ts 文字起こし中にエラーが発生しました: {e}")
            return []

    def refine_timestamps(
        self, audio_path: str, segments: List[TranscriptSegment]
    ) -> List[TranscriptSegment]:
        """タイムスタンプを精密化 (refine) する。

        Args:
            audio_path: 音声ファイルパス
            segments: 既存の TranscriptSegment リスト

        Returns:
            List[TranscriptSegment]: 調整後の TranscriptSegment リスト（失敗時は元のリスト）
        """
        if not segments:
            return []

        if not self.is_available():
            logger.warning("stable_whisper が利用不可のため refine_timestamps をスキップします")
            return segments

        if not os.path.exists(audio_path):
            logger.error(f"音声ファイルが存在しません: {audio_path}")
            return segments

        try:
            import stable_whisper

            logger.info(f"stable-ts でタイムスタンプ調整中: {audio_path}")
            model = stable_whisper.load_model(self.model_name)
            
            # refine 機能の実行（Dict / WhisperResult オブジェクト変換）
            dict_segments = [
                {"start": seg.start, "end": seg.end, "text": seg.text}
                for seg in segments
            ]
            refined_result = model.refine(audio_path, dict_segments)
            
            refined_segments: List[TranscriptSegment] = []
            raw_segments = getattr(refined_result, "segments", [])
            if not raw_segments and isinstance(refined_result, list):
                raw_segments = refined_result

            for i, seg in enumerate(raw_segments):
                orig_seg = segments[i] if i < len(segments) else None
                start = getattr(seg, "start", seg.get("start", orig_seg.start if orig_seg else 0.0) if isinstance(seg, dict) else 0.0)
                end = getattr(seg, "end", seg.get("end", orig_seg.end if orig_seg else 0.0) if isinstance(seg, dict) else 0.0)
                text = getattr(seg, "text", seg.get("text", orig_seg.text if orig_seg else "") if isinstance(seg, dict) else "").strip()
                confidence = orig_seg.confidence if orig_seg else 0.0

                refined_segments.append(
                    TranscriptSegment(
                        start=float(start),
                        end=float(end),
                        text=text,
                        confidence=float(confidence),
                    )
                )

            return refined_segments if refined_segments else segments

        except Exception as e:
            logger.warning(f"stable-ts refine 処理失敗、オリジナルのセグメントを返します: {e}")
            return segments
