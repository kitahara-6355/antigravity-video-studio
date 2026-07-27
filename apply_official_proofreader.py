"""
既存Whisper字幕にAI Proofreaderを正規適用
Phase 18 Architecture準拠
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, r"C:\Users\PC_User\Desktop\script\video-automation\backend")

from subtitle_engine.ai_proofreader import proofread_segments

# 設定
RAW_DIR = Path(r"C:\Users\PC_User\Desktop\script\video-automation\raw_videos\AI Studio アップロード用動画")

# 既存のWhisper字幕ファイル（_regenerated.srt）
FILES = [
    ("シーン01_前編_regenerated.srt", "シーン01_前編_official.srt"),
    ("シーン03_後編01_regenerated.srt", "シーン03_後編01_official.srt"),
    ("シーン04_後編02_regenerated.srt", "シーン04_後編02_official.srt"),
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
            try:
                idx = int(lines[0])
                times = lines[1]
                text = '\n'.join(lines[2:])
                start_str, end_str = times.split(' --> ')
                
                # タイムスタンプを秒に変換
                def ts_to_sec(ts):
                    parts = ts.replace(',', '.').split(':')
                    return float(parts[0])*3600 + float(parts[1])*60 + float(parts[2])
                
                segments.append({
                    'index': idx,
                    'start': ts_to_sec(start_str),
                    'end': ts_to_sec(end_str),
                    'start_str': start_str,
                    'end_str': end_str,
                    'text': text
                })
            except:
                pass
    return segments

def save_srt(segments, filepath):
    """セグメントリストをSRTファイルに保存"""
    with open(filepath, 'w', encoding='utf-8') as f:
        for i, seg in enumerate(segments, 1):
            f.write(f"{i}\n")
            f.write(f"{seg['start_str']} --> {seg['end_str']}\n")
            f.write(f"{seg['text']}\n\n")

def main():
    print("=" * 60)
    print("Phase 18: AI Proofreader 正規適用")
    print("既存Whisper字幕 → Gemini校閲 → 公式字幕")
    print("=" * 60)
    
    for input_name, output_name in FILES:
        input_path = RAW_DIR / input_name
        output_path = RAW_DIR / output_name
        
        if not input_path.exists():
            print(f"\nSKIP: {input_name} not found")
            continue
        
        print(f"\n{'='*60}")
        print(f"Processing: {input_name}")
        print(f"{'='*60}")
        
        # SRT読み込み
        segments = parse_srt(input_path)
        print(f"Loaded {len(segments)} segments")
        
        # 進捗コールバック
        def progress_callback(status, message, progress):
            print(f"  [{status}] {message}")
        
        # AI Proofreader適用（正規パイプライン）
        print("Applying AI Proofreader (Gemini 3.0)...")
        corrected = proofread_segments(segments, update_callback=progress_callback)
        
        # 保存
        save_srt(corrected, output_path)
        print(f"Saved: {output_path}")
        
        # JSON保存（バックアップ）
        json_path = output_path.with_suffix('.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(corrected, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*60}")
    print("All done!")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
