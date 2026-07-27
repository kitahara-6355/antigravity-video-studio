"""
正規パイプラインによる字幕生成（Phase 18 Architecture）
WhisperTranscriber.transcribe_with_proofreading() を直接呼び出し
"""
import sys
import asyncio
import json
from pathlib import Path

# バックエンドモジュールのパスを追加
sys.path.insert(0, r"C:\Users\PC_User\Desktop\script\video-automation\backend")

from subtitle_engine.whisper_transcriber import WhisperTranscriber

# 設定
RAW_DIR = Path(r"C:\Users\PC_User\Desktop\script\video-automation\raw_videos\AI Studio アップロード用動画")
OUTPUT_DIR = RAW_DIR  # 同じディレクトリに出力

# 処理対象
VIDEOS = [
    ("シーン01_前編.mp4", "シーン01_前編_official.srt"),
    ("シーン03_後編01.mp4", "シーン03_後編01_official.srt"),
    ("シーン04_後編02.mp4", "シーン04_後編02_official.srt"),
]

def segments_to_srt(segments, output_path):
    """セグメントリストをSRTファイルに保存"""
    with open(output_path, 'w', encoding='utf-8') as f:
        for i, seg in enumerate(segments, 1):
            start = seg['start']
            end = seg['end']
            text = seg['text'].strip()
            
            # SRT形式のタイムスタンプ
            start_ts = f"{int(start//3600):02}:{int((start%3600)//60):02}:{start%60:06.3f}".replace(".", ",")
            end_ts = f"{int(end//3600):02}:{int((end%3600)//60):02}:{end%60:06.3f}".replace(".", ",")
            
            f.write(f"{i}\n")
            f.write(f"{start_ts} --> {end_ts}\n")
            f.write(f"{text}\n\n")

async def process_video(video_name, output_name):
    """単一動画を処理"""
    video_path = RAW_DIR / video_name
    output_path = OUTPUT_DIR / output_name
    
    if not video_path.exists():
        print(f"SKIP: {video_name} not found")
        return False
    
    print(f"\n{'='*60}")
    print(f"Processing: {video_name}")
    print(f"{'='*60}")
    
    # 進捗コールバック
    def progress_callback(status, message, progress):
        print(f"  [{status}] {progress}% - {message}")
    
    # Phase 18: WhisperTranscriber + AI Proofreader
    transcriber = WhisperTranscriber(model_size="medium")
    
    # 正規パイプライン実行
    segments = await transcriber.transcribe_with_proofreading(
        video_path=str(video_path),
        language="ja",
        beam_size=1,
        progress_callback=progress_callback
    )
    
    print(f"  Generated {len(segments)} segments")
    
    # SRT保存
    segments_to_srt(segments, output_path)
    print(f"  Saved: {output_path}")
    
    # JSON保存（バックアップ）
    json_path = output_path.with_suffix('.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)
    
    return True

async def main():
    print("=" * 60)
    print("Phase 18 Architecture: 正規パイプライン字幕生成")
    print("WhisperTranscriber.transcribe_with_proofreading()")
    print("=" * 60)
    
    for video_name, output_name in VIDEOS:
        await process_video(video_name, output_name)
    
    print(f"\n{'='*60}")
    print("All done!")
    print(f"{'='*60}")

if __name__ == "__main__":
    asyncio.run(main())
