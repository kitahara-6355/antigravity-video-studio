"""
Gemini Semantic Chunking Module
Phase 30 - Week 2 Implementation

Whisperの出力を意味単位で区切り、読みやすい字幕に整形
"""

from google import genai
import json
import os
import logging
from typing import List, Dict
from pathlib import Path

logger = logging.getLogger(__name__)

# Import Model Registry
try:
    from model_registry import get_model
    DEFAULT_MODEL = get_model("semantic_chunker")
except (ImportError, AttributeError) as e:
    logger.info("model_registry not available or missing get_model (using fallback): %s", e)
    DEFAULT_MODEL = "gemini-2.0-flash"

# Gemini API初期化 (グローバルまたはクラス内で行う)
from gemini_client_factory import get_gemini_client
client = None  # 後方互換性のための定義


class GeminiSemanticChunker:
    """
    Gemini による意味単位分割
    
    Features:
    - Whisper出力を意味のある単位に再構成
    - 文の途中で切れないように調整
    - 話者ラベル付与（可能な場合）
    """
    
    def __init__(self, model_name: str = None, client = None):
        # Use Model Registry if no model specified
        self.model_name = model_name or DEFAULT_MODEL
        self.client = client or get_gemini_client()

    
    def chunk_segments(self, whisper_segments: List[Dict], video_theme: str = "") -> List[Dict]:
        """
        Whisperの出力を意味単位で再構成
        
        Args:
            whisper_segments: Whisper of output segments
            video_theme: Theme of video
        
        Returns:
            Meaningful chunked segments
        """
        if not isinstance(whisper_segments, list):
            logger.error("whisper_segments がリストではありません: %s", type(whisper_segments))
            return []
            
        if not whisper_segments:
            print("   入力セグメントが空です")
            return []

        print(f"\n🧠 Gemini意味単位分割開始")
        print(f"   入力セグメント数: {len(whisper_segments)}")
        
        # セグメントを結合してテキスト化
        full_text = self._segments_to_text(whisper_segments)
        
        # Gemini に意味単位分割を依頼
        prompt = f"""
以下は動画の音声認識結果です。以下の要件に従って、意味のある単位に整形してください。

【動画のテーマ】
{video_theme if video_theme else "対談動画"}

【要件】
1. 文の途中で切れないように調整
2. 1セグメントは2-3行程度
3. 意味のまとまりで区切る
4. 話者が変わるタイミングは必ず区切る
5. 「あの」「えっと」などのフィラーは削除
6. 誤字・表記ゆれを修正

【音声認識結果】
{full_text[:5000]}  # 最初の5000文字のみ（API制限対策）

【出力形式】
JSONリストで返してください。各要素は以下の形式：
{{
  "text": "整形されたテキスト",
  "start": 開始時刻（秒）,
  "end": 終了時刻（秒）,
  "speaker": "話者名（不明な場合は空文字）"
}}
"""
        
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            
            # JSON抽出
            result_text = response.text
            # JSONブロックを抽出（```json ... ```の中身）
            if "```json" in result_text:
                json_str = result_text.split("```json")[1].split("```")[0].strip()
            else:
                json_str = result_text
            
            chunked_segments = json.loads(json_str)
            
            # バリデーションと型安全の確保
            if not isinstance(chunked_segments, list):
                raise ValueError("Gemini response is not a JSON list")
                
            validated_segments = []
            for seg in chunked_segments:
                if not isinstance(seg, dict):
                    raise ValueError("Segment item is not a dictionary")
                
                text = seg.get("text")
                start = seg.get("start")
                end = seg.get("end")
                speaker = seg.get("speaker", "")
                
                if text is None or start is None or end is None:
                    raise ValueError("Missing required keys in segment")
                
                try:
                    start_val = float(start)
                    end_val = float(end)
                except (ValueError, TypeError):
                    raise ValueError("Start or End time is not a valid number")
                
                validated_segments.append({
                    "text": str(text),
                    "start": start_val,
                    "end": end_val,
                    "speaker": str(speaker)
                })
            
            print(f"✅ 完了: {len(validated_segments)} セグメント")
            return validated_segments
            
        except (genai.errors.APIError, json.JSONDecodeError, ValueError) as e:
            logger.exception("⚠️ Gemini処理エラー（想定内）: %s", e)
            print("   元のWhisper出力を返します")
            return whisper_segments
        except (TypeError, AttributeError, KeyError) as e:
            logger.error("⚠️ プログラミングエラーまたはレスポンス解析エラー: %s", e, exc_info=True)
            print("   元のWhisper出力を返します")
            return whisper_segments
        except (RuntimeError, OSError) as e:
            logger.exception("⚠️ Gemini処理エラー（想定外）: %s", e)
            print("   元のWhisper出力を返します")
            return whisper_segments
    
    def _segments_to_text(self, segments: List[Dict]) -> str:
        """セグメントをタイムスタンプ付きテキストに変換"""
        pass
        lines = []
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            start = seg.get("start", 0.0)
            text = seg.get("text", "")
            try:
                start_val = float(start)
            except (ValueError, TypeError):
                start_val = 0.0
            timestamp = f"[{start_val:.2f}s]"
            lines.append(f"{timestamp} {text}")
        return "\n".join(lines)
    
    def save_as_srt(self, segments: List[Dict], output_path: str):
        """
        SRT形式で保存（白色・映画風スタイル）
        
        Args:
            segments: 字幕セグメント
            output_path: 出力ファイルパス
        """
        output_path = Path(output_path)
        
        with open(output_path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments, 1):
                if not isinstance(seg, dict):
                    continue
                start = seg.get("start", 0.0)
                end = seg.get("end", 0.0)
                text = seg.get("text", "")
                speaker = seg.get("speaker", "")
                
                try:
                    start_val = float(start)
                except (ValueError, TypeError):
                    start_val = 0.0
                try:
                    end_val = float(end)
                except (ValueError, TypeError):
                    end_val = 0.0
                
                # SRT形式
                f.write(f"{i}\n")
                f.write(f"{self._format_timestamp(start_val)} --> {self._format_timestamp(end_val)}\n")
                
                # テキスト（話者ラベル付き）
                if speaker:
                    f.write(f"{speaker}: {text}\n\n")
                else:
                    f.write(f"{text}\n\n")
        
        print(f"💾 SRT保存: {output_path}")
    
    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """秒数をSRTタイムスタンプ形式に変換"""
        try:
            seconds_val = max(0.0, float(seconds))
        except (ValueError, TypeError):
            seconds_val = 0.0
        hours = int(seconds_val // 3600)
        minutes = int((seconds_val % 3600) // 60)
        secs = int(seconds_val % 60)
        millis = int((seconds_val % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def process_whisper_to_semantic_srt(
    whisper_json_path: str,
    video_theme: str = "",
    output_srt_path: str = None,
    client = None
) -> str:
    """
    Whisper JSON → Gemini意味単位分割 → SRT
    
    Args:
        whisper_json_path: Whisper of output JSON path
        video_theme: Theme of video
        output_srt_path: Output SRT path
    
    Returns:
        Output SRT path
    """
    # Whisper JSON読み込み
    try:
        with open(whisper_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as e:
        logger.error("Whisper JSON file not found: %s", whisper_json_path)
        raise ValueError(f"Whisper JSON file not found: {whisper_json_path}") from e
    except json.JSONDecodeError as e:
        logger.error("Failed to decode Whisper JSON: %s. Error: %s", whisper_json_path, e)
        raise ValueError(f"Failed to decode Whisper JSON: {whisper_json_path}") from e
    except OSError as e:
        logger.error("OS error occurred while reading Whisper JSON: %s. Error: %s", whisper_json_path, e)
        raise ValueError(f"Error reading Whisper JSON: {whisper_json_path}") from e
    
    whisper_segments = data.get("segments", []) if isinstance(data, dict) else []
    
    # Gemini処理
    chunker = GeminiSemanticChunker(client=client)
    semantic_segments = chunker.chunk_segments(whisper_segments, video_theme)
    
    # SRT保存
    if output_srt_path is None:
        output_srt_path = Path(whisper_json_path).parent / f"{Path(whisper_json_path).stem}_semantic.srt"
    
    chunker.save_as_srt(semantic_segments, output_srt_path)
    
    return str(output_srt_path)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("使用方法: python gemini_semantic_chunker.py <whisper_json_path> [video_theme]")
        sys.exit(1)
    
    whisper_json = sys.argv[1]
    theme = sys.argv[2] if len(sys.argv) > 2 else ""
    
    output_srt = process_whisper_to_semantic_srt(whisper_json, theme)
    print(f"\n✅ 完了: {output_srt}")
