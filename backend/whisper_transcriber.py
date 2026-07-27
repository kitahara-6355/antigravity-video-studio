"""
Whisper Transcription Module
Phase 30 - Week 1 Implementation

最高精度の字幕生成のため、Whisper を使用して動画の音声を文字起こし。
日本語に最適化され、タイムスタンプ付きで出力。
"""

import json
from pathlib import Path
from typing import List, Dict, Optional
from datetime import timedelta

try:
    from faster_whisper import WhisperModel
except ImportError:
    print("⚠️ faster-whisper がインストールされていません")
    print("インストールコマンド: pip install faster-whisper")
    WhisperModel = None


class WhisperTranscriptionError(RuntimeError):
    """Whisper文字起こし処理に関する例外"""
    pass


class WhisperTranscriber:
    """
    Whisper による高精度音声認識
    
    Features:
    - 日本語最適化
    - タイムスタンプ付き
    - 話者推定（基本版）
    - JSON/SRT 出力
    """
    
    def __init__(
        self,
        model_size: str = "large-v3",
        device: Optional[str] = None,
        compute_type: Optional[str] = None
    ):
        """
        Args:
            model_size: Whisperモデルサイズ（large-v3推奨）
            device: 使用するデバイス ('cuda', 'cpu' など。Noneなら自動検出)
            compute_type: 演算精度 ('float16', 'int8' など。Noneなら自動選択)
        """
        if WhisperModel is None:
            raise ImportError("faster-whisper が必要です")
        
        # GPUの自動検出
        if device is None:
            try:
                import ctranslate2
                has_cuda = ctranslate2.get_cuda_device_count() > 0
            except ImportError:
                has_cuda = False
            device = "cuda" if has_cuda else "cpu"
        
        # 演算精度の自動選択
        if compute_type is None:
            compute_type = "float16" if device == "cuda" else "int8"
        
        print(f"🎤 Whisper モデルをロード中: {model_size} (device: {device}, compute_type: {compute_type})")
        try:
            self.model = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type
            )
        except (ValueError, RuntimeError, OSError) as e:
            raise WhisperTranscriptionError(f"Whisperモデルのロードに失敗しました (サイズ: {model_size}): {e}") from e
        print("✅ Whisper 準備完了")
    
    def transcribe_video(
        self,
        video_path: str,
        language: str = "ja",
        output_format: str = "json"
    ) -> Dict:
        """
        動画の音声を文字起こし
        
        Args:
            video_path: 動画ファイルパス
            language: 言語コード（ja=日本語）
            output_format: 出力形式（json/srt/both）
        
        Returns:
            文字起こし結果
        """
        video_path = Path(video_path)
        
        if not video_path.exists():
            raise FileNotFoundError(f"動画が見つかりません: {video_path}")
        
        print(f"\n🎬 文字起こし開始: {video_path.name}")
        print(f"   言語: {language}")
        
        # 1. 音声の文字起こし実行
        segments, info = self._execute_transcription(video_path, language)
        
        # 2. セグメントの収集と整形
        results = self._collect_segments(segments)
        
        output_data = {
            "video": str(video_path),
            "language": info.language,
            "duration": info.duration,
            "segments": results
        }
        
        # 3. JSON保存
        output_json = video_path.parent / f"{video_path.stem}_whisper.json"
        self._save_json_result(output_json, output_data)
        
        # 4. SRT保存（オプション）
        if output_format in ("srt", "both"):
            output_srt = video_path.parent / f"{video_path.stem}_whisper.srt"
            try:
                self._save_srt(results, output_srt)
                print(f"💾 SRT保存: {output_srt}")
            except (OSError, KeyError, ValueError) as e:
                raise WhisperTranscriptionError(f"SRTファイルの保存に失敗しました ({output_srt}): {e}") from e
        
        return output_data

    def _execute_transcription(self, video_path: Path, language: str):
        """WhisperModelによる音声文字起こしの実行"""
        try:
            segments, info = self.model.transcribe(
                str(video_path),
                language=language,
                beam_size=5,  # 精度向上
                vad_filter=True,  # 無音部分を自動検出
                vad_parameters=dict(
                    min_silence_duration_ms=500  # 500ms以上の無音を検出
                )
            )
            print(f"   検出言語: {info.language} (確信度: {info.language_probability:.2%})")
            return segments, info
        except (ValueError, RuntimeError, OSError) as e:
            raise WhisperTranscriptionError(f"音声の文字起こし処理中にエラーが発生しました: {e}") from e

    def _collect_segments(self, segments) -> List[Dict]:
        """セグメントデータをパースして整形リストを構築"""
        results = []
        try:
            for i, segment in enumerate(segments, 1):
                results.append({
                    "id": i,
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text.strip(),
                    "confidence": segment.avg_logprob
                })
                
                # 進捗表示
                if i % 10 == 0:
                    print(f"   処理中: {i} セグメント...")
        except (ValueError, RuntimeError, OSError) as e:
            raise WhisperTranscriptionError(f"セグメント処理中にエラーが発生しました: {e}") from e
        
        print(f"✅ 完了: {len(results)} セグメント")
        return results

    def _save_json_result(self, output_path: Path, data: Dict):
        """結果データをJSONファイルに書き出し"""
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"💾 JSON保存: {output_path}")
        except (OSError, TypeError) as e:
            raise WhisperTranscriptionError(f"JSONファイルの保存に失敗しました ({output_path}): {e}") from e
    
    def _save_srt(self, segments: List[Dict], output_path: Path):
        """SRT形式で保存"""
        with open(output_path, "w", encoding="utf-8") as f:
            for seg in segments:
                # 必要なキーの検証
                if not isinstance(seg, dict) or not all(k in seg for k in ("id", "start", "end", "text")):
                    raise ValueError(f"無効なセグメントデータ形式です: {seg}")
                # SRT形式
                f.write(f"{seg['id']}\n")
                f.write(f"{self._format_timestamp(seg['start'])} --> {self._format_timestamp(seg['end'])}\n")
                f.write(f"{seg['text']}\n\n")
    
    @staticmethod
    def _format_timestamp(seconds: Optional[float]) -> str:
        """秒数をSRTタイムスタンプ形式に変換"""
        if seconds is None:
            return "00:00:00,000"
        try:
            seconds = float(seconds)
        except (ValueError, TypeError):
            return "00:00:00,000"
        if seconds < 0:
            seconds = 0.0
            
        td = timedelta(seconds=seconds)
        hours = int(td.total_seconds() // 3600)
        minutes = int((td.total_seconds() % 3600) // 60)
        secs = int(td.total_seconds() % 60)
        millis = int((td.total_seconds() % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
    
    def estimate_speakers(self, segments: List[Dict], gap_threshold: float = 2.0) -> List[Dict]:
        """
        話者推定（簡易版）
        
        発話間の時間ギャップが gap_threshold 秒以上のときに話者が切り替わると推測し、
        交互に "話者_1", "話者_2" のラベルを割り当てる。
        
        Args:
            segments: 音声セグメントのリスト
            gap_threshold: 話者の交代を推測する無音時間（秒）の閾値
            
        Returns:
            speakerキーが追加されたセグメントのリスト
        """
        if not segments:
            return segments
            
        current_speaker = "話者_1"
        prev_end = None
        
        for seg in segments:
            # 必要なキーがない、または None の場合は交代判定をスキップして直前と同じにする
            start = seg.get("start")
            end = seg.get("end")
            
            if start is not None and prev_end is not None:
                gap = start - prev_end
                if gap >= gap_threshold:
                    # 話者を交代させる
                    current_speaker = "話者_2" if current_speaker == "話者_1" else "話者_1"
                    
            seg["speaker"] = current_speaker
            
            if end is not None:
                prev_end = end
                
        return segments


def transcribe_video_simple(video_path: str, model_size: str = "large-v3") -> str:
    """
    シンプルな文字起こし関数
    
    Args:
        video_path: 動画パス
        model_size: モデルサイズ
    
    Returns:
        出力JSONパス
    """
    transcriber = WhisperTranscriber(model_size=model_size)
    result = transcriber.transcribe_video(video_path, output_format="both")
    
    return str(Path(video_path).parent / f"{Path(video_path).stem}_whisper.json")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("使用方法: python whisper_transcriber.py <video_path>")
        sys.exit(1)
    
    video_path = sys.argv[1]
    try:
        output_path = transcribe_video_simple(video_path)
        print(f"\n✅ 完了: {output_path}")
    except FileNotFoundError as e:
        print(f"❌ エラー: 動画ファイルが見つかりません: {e}", file=sys.stderr)
        sys.exit(1)
    except WhisperTranscriptionError as e:
        print(f"❌ 文字起こしエラーが発生しました: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ 予期しないエラーが発生しました: {e}", file=sys.stderr)
        sys.exit(1)
