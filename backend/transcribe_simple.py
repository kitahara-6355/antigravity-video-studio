"""
Simple Whisper Transcription - No moviepy
faster-whisper 直接実行版
"""

from faster_whisper import WhisperModel
import json
from pathlib import Path
import sys


SUPPORTED_MODELS = {
    "tiny", "tiny.en", "base", "base.en", "small", "small.en",
    "medium", "medium.en", "large-v1", "large-v2", "large-v3",
    "large", "large-v3-turbo", "distil-large-v2", "distil-medium.en",
    "distil-small.en", "distil-large-v3", "distil-large-v3.5", "turbo"
}


def transcribe_simple(video_path: str, model_size: str = "medium"):
    """
    シンプルなWhisper文字起こし（moviepy不使用）
    
    Args:
        video_path: 動画パス
        model_size: モデルサイズ
    
    Returns:
        セグメントリスト
    """
    if model_size not in SUPPORTED_MODELS:
        raise ValueError(f"Invalid model size: {model_size}. Supported: {SUPPORTED_MODELS}")

    if not Path(video_path).is_file():
        raise FileNotFoundError(f"Video file not found or is not a file: {video_path}")

    print(f"\n🎤 Whisper文字起こし（{model_size}）")
    print(f"📁 {Path(video_path).name}")
    
    # モデルロード
    print("⏳ モデルロード中...")
    try:
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
    except (ValueError, RuntimeError, ImportError) as e:
        raise RuntimeError(f"Failed to load Whisper model '{model_size}': {e}") from e
    print("✅ モデル準備完了")
    
    # 文字起こし
    print("⏳ 文字起こし中...")
    try:
        segments_iter, info = model.transcribe(
            video_path,
            language="ja",
            beam_size=1,  # 高速化のため1に
            vad_filter=True
        )
        
        # セグメント収集
        segments = []
        for i, seg in enumerate(segments_iter, 1):
            segments.append({
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip()
            })
            
            # 進捗表示
            if i % 50 == 0:
                print(f"  {i} セグメント処理済み...")
    except (ValueError, RuntimeError, OSError) as e:
        raise RuntimeError(f"Error during Whisper transcription: {e}") from e
    
    print(f"✅ 完了: {len(segments)} セグメント")
    
    # JSON保存
    output_path = Path(video_path).parent / f"{Path(video_path).stem}_whisper.json"
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({
                "video": str(video_path),
                "model": model_size,
                "language": info.language,
                "segments": segments
            }, f, ensure_ascii=False, indent=2)
    except OSError as e:
        raise OSError(f"Failed to save transcription JSON to {output_path}: {e}") from e
    
    print(f"💾 保存: {output_path.name}")
    
    return segments


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用方法: python transcribe_simple.py <video_path> [model_size]")
        sys.exit(1)
    
    video = sys.argv[1]
    model = sys.argv[2] if len(sys.argv) > 2 else "medium"
    
    try:
        transcribe_simple(video, model)
    except FileNotFoundError as e:
        print(f"エラー: 指定された動画ファイルが見つかりません。 {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"エラー: 無効な引数です。 {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"エラー: 処理の実行中にエラーが発生しました。 {e}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"エラー: ファイルの読み書き中にエラーが発生しました。 {e}", file=sys.stderr)
        sys.exit(1)
    print("\n🎉 完了！")
