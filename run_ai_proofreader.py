"""
AI Proofreaderを使用して全字幕ファイルを自動修正
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

import json
import logging
from path_resolver import raw_videos_dir
from subtitle_engine.ai_proofreader import proofread_segments

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 字幕ファイル
SRT_DIR = raw_videos_dir() / "AI Studio アップロード用動画"
FILES = [
    "シーン01_前編_regenerated.srt",
    "シーン03_後編01_regenerated.srt",
    "シーン04_後編02_regenerated.srt"
]

def parse_srt(filepath):
    """SRTファイルをセグメントリストに変換"""
    segments = []
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    blocks = content.strip().split('\n\n')
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            idx = int(lines[0])
            times = lines[1]
            text = '\n'.join(lines[2:])
            start_str, end_str = times.split(' --> ')
            segments.append({
                'index': idx,
                'start_str': start_str,
                'end_str': end_str,
                'text': text
            })
    return segments

def save_srt(segments, filepath):
    """セグメントリストをSRTファイルに保存"""
    with open(filepath, 'w', encoding='utf-8') as f:
        for i, seg in enumerate(segments, 1):
            f.write(f"{i}\n")
            f.write(f"{seg['start_str']} --> {seg['end_str']}\n")
            f.write(f"{seg['text']}\n\n")

def main():
    for filename in FILES:
        filepath = SRT_DIR / filename
        if not filepath.exists():
            print(f"SKIP: {filename} not found")
            continue
        
        print(f"\n{'='*60}")
        print(f"Processing: {filename}")
        print(f"{'='*60}")
        
        # SRT読み込み
        segments = parse_srt(filepath)
        print(f"Loaded {len(segments)} segments")
        
        # AI校閲実行
        corrected = proofread_segments(segments)
        
        # 保存
        output_path = SRT_DIR / filename.replace("_regenerated.srt", "_proofread.srt")
        save_srt(corrected, output_path)
        print(f"Saved: {output_path}")
    
    print(f"\n{'='*60}")
    print("All done!")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
