"""
固定版 Whisper 文字起こしスクリプト
Phase 30 - 根本原因修正済み

修正内容:
1. UTF-8エンコーディングを明示的に設定
2. 出力バッファリングを解消
3. 進捗表示を改善
"""

import sys
import json
from pathlib import Path
from typing import List, Dict, Tuple, Any

# UTF-8出力を強制
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from faster_whisper import WhisperModel


def _print_start_message(video_path: Path, model_size: str) -> None:
    """文字起こし開始メッセージの出力"""
    print(f"\n{'='*60}")
    print(f"🎤 Whisper 文字起こし")
    print(f"{'='*60}")
    print(f"ファイル: {video_path.name}")
    print(f"モデル: {model_size}")
    print(f"{'='*60}")
    sys.stdout.flush()


def _load_whisper_model(model_size: str) -> WhisperModel:
    """Whisper モデルのロード"""
    print("\n⏳ モデルをロード中...")
    sys.stdout.flush()
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    print("✅ モデル準備完了")
    sys.stdout.flush()
    return model


def _collect_segments(model: WhisperModel, video_path: Path) -> Tuple[List[Dict[str, Any]], Any]:
    """文字起こしを実行し、セグメントを収集する"""
    print("\n⏳ 文字起こし中...")
    sys.stdout.flush()
    
    segments_iter, info = model.transcribe(
        str(video_path),
        language="ja",
        beam_size=1,  # 高速化
        vad_filter=True  # 無音検出
    )
    
    segments = []
    for segment in segments_iter:
        segments.append({
            "start": round(segment.start, 2),
            "end": round(segment.end, 2),
            "text": segment.text.strip()
        })
        
        # 進捗表示（10セグメントごと）
        if len(segments) % 10 == 0:
            print(f"  {len(segments)} セグメント処理済み...", flush=True)
            
    print(f"\n✅ 完了: {len(segments)} セグメント")
    sys.stdout.flush()
    return segments, info


def _save_transcription_result(
    video_path: Path,
    model_size: str,
    info: Any,
    segments: List[Dict[str, Any]],
    output_dir: str = None
) -> Path:
    """文字起こし結果を JSON ファイルに保存する"""
    if output_dir:
        output_path = Path(output_dir) / f"{video_path.stem}_whisper.json"
    else:
        output_path = video_path.parent / f"{video_path.stem}_whisper.json"
        
    with open(output_path, "w", encoding="utf-8") as output_file:
        json.dump({
            "video": video_path.name,
            "model": model_size,
            "language": info.language,
            "duration": info.duration,
            "total_segments": len(segments),
            "segments": segments
        }, output_file, ensure_ascii=False, indent=2)
        
    print(f"💾 保存完了: {output_path.name}")
    return output_path


def _print_transcription_summary(segments: List[Dict[str, Any]]) -> None:
    """文字起こし結果のサマリーを出力する"""
    if segments:
        print(f"\n📝 最初の5セグメント:")
        for segment in segments[:5]:
            print(f"  [{segment['start']:.1f}s] {segment['text'][:50]}...")
            
    print(f"\n{'='*60}")
    print(f"🎉 完了!")
    print(f"{'='*60}\n")
    sys.stdout.flush()


def transcribe_video(video_path: str, model_size: str = "medium", output_dir: str = None):
    """
    動画を文字起こし
    
    Args:
        video_path: 動画ファイルパス
        model_size: モデルサイズ (base, medium, large-v3)
        output_dir: 出力ディレクトリ（省略時は動画と同じ場所）
    
    Returns:
        出力JSONパス
    """
    video_path = Path(video_path)
    
    if not video_path.exists():
        print(f"エラー: ファイルが見つかりません: {video_path}")
        return None
        
    _print_start_message(video_path, model_size)
    
    model = _load_whisper_model(model_size)
    
    segments, info = _collect_segments(model, video_path)
    
    output_path = _save_transcription_result(
        video_path=video_path,
        model_size=model_size,
        info=info,
        segments=segments,
        output_dir=output_dir
    )
    
    _print_transcription_summary(segments)
    
    return str(output_path)


def transcribe_all_videos(video_dir: str, model_size: str = "medium"):
    """
    ディレクトリ内の全動画を文字起こし
    
    Args:
        video_dir: 動画が格納されたディレクトリ
        model_size: モデルサイズ
    
    Returns:
        処理結果のリスト
    """
    video_dir = Path(video_dir)
    results = []
    
    # 対象ファイルを列挙
    video_files = list(video_dir.glob("*.mp4"))
    print(f"\n🎬 {len(video_files)} 個の動画を検出")
    
    for i, video_path in enumerate(video_files, 1):
        print(f"\n[{i}/{len(video_files)}] 処理中: {video_path.name}")
        
        try:
            output = transcribe_video(str(video_path), model_size)
            results.append({"file": video_path.name, "status": "success", "output": output})
        except Exception as error:
            print(f"❌ エラー: {error}")
            results.append({"file": video_path.name, "status": "failed", "error": str(error)})
            
    print(f"\n{'='*60}")
    print(f"📊 全体サマリー")
    print(f"{'='*60}")
    success = sum(1 for result in results if result["status"] == "success")
    print(f"成功: {success}/{len(results)}")
    print(f"{'='*60}\n")
    
    return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用方法:")
        print("  単一ファイル: python whisper_fixed.py <video_path> [model_size]")
        print("  全ファイル:   python whisper_fixed.py --all <directory> [model_size]")
        sys.exit(1)
        
    if sys.argv[1] == "--all":
        video_dir = sys.argv[2] if len(sys.argv) > 2 else "."
        model_size = sys.argv[3] if len(sys.argv) > 3 else "medium"
        transcribe_all_videos(video_dir, model_size)
    else:
        video_path = sys.argv[1]
        model_size = sys.argv[2] if len(sys.argv) > 2 else "medium"
        transcribe_video(video_path, model_size)

