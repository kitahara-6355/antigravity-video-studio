"""
Whisper Transcription - Sync Wrapper
既存のasync実装を同期的に実行するラッパー
"""

import asyncio
import sys
import json
from pathlib import Path

# 既存のWhisperTranscriberを使用
_parent = Path(__file__).parent
sys.path.insert(0, str(_parent))
if (_parent / "backend").exists():
    sys.path.insert(0, str(_parent / "backend"))
from subtitle_engine.whisper_transcriber import WhisperTranscriber


def _run_transcribe_loop(transcriber: WhisperTranscriber, video_path: str) -> list:
    """
    新しいイベントループを作成し、文字起こし処理を同期的に実行する。
    呼び出し元のイベントループに影響を与えないよう、元のループを退避・復元する。
    """
    import warnings
    try:
        old_loop = asyncio.get_running_loop()
    except RuntimeError:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            try:
                old_loop = asyncio.get_event_loop()
            except RuntimeError:
                old_loop = None

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(
            transcriber.transcribe(
                video_path=video_path,
                language="ja",
                beam_size=5  # 高精度モード
            )
        )
    finally:
        try:
            loop.close()
        finally:
            asyncio.set_event_loop(old_loop)


def _save_transcription_result(video_path: str, model_size: str, segments: list) -> Path:
    """
    文字起こし結果のセグメントをJSONファイルに保存する
    """
    output_path = Path(video_path).parent / f"{Path(video_path).stem}_whisper.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "video": str(video_path),
            "model": model_size,
            "segments": segments
        }, f, ensure_ascii=False, indent=2)
    return output_path


def transcribe_video_sync(video_path: str, model_size: str = "medium") -> list:
    """
    同期的に動画を文字起こし
    
    Args:
        video_path: 動画パス
        model_size: モデルサイズ
    
    Returns:
        字幕セグメントのリスト
    """
    print(f"\n🎬 Whisper文字起こし開始")
    print(f"   動画: {Path(video_path).name}")
    print(f"   モデル: {model_size}")
    
    # Whisperインスタンス作成
    transcriber = WhisperTranscriber(model_size=model_size)
    
    # 非同期関数を同期的に実行
    segments = _run_transcribe_loop(transcriber, video_path)
    
    # JSON保存
    output_path = _save_transcription_result(video_path, model_size, segments)
    
    print(f"\n✅ 完了: {len(segments)} セグメント")
    print(f"💾 保存: {output_path}")
    
    return segments


def main():
    if len(sys.argv) < 2:
        print("使用方法: python transcribe_sync.py <video_path> [model_size]")
        sys.exit(1)
    
    video_path = sys.argv[1]
    model_size = sys.argv[2] if len(sys.argv) > 2 else "medium"
    
    transcribe_video_sync(video_path, model_size)


if __name__ == "__main__":
    main()
