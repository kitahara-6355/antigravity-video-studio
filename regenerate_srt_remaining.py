"""
字幕再生成スクリプト - 残り3シーンをWhisperで処理
"""
from faster_whisper import WhisperModel
import os

# モデルロード
print("Loading Whisper model (CPU mode)...")
model = WhisperModel("large-v3", device="cpu", compute_type="int8")

# 動画ディレクトリ
video_dir = r"C:\Users\PC_User\Desktop\script\video-automation\raw_videos\AI Studio アップロード用動画"

# 処理対象（シーン01は完了済みなのでスキップ）
videos = [
    "シーン02_ゲスト書道.mp4",
    "シーン03_後編01.mp4",
    "シーン04_後編02.mp4"
]

for video_name in videos:
    video_path = os.path.join(video_dir, video_name)
    output_path = os.path.join(video_dir, video_name.replace(".mp4", "_regenerated.srt"))
    
    if not os.path.exists(video_path):
        print(f"SKIP: {video_name} not found")
        continue
    
    if os.path.exists(output_path):
        print(f"SKIP: {video_name} already processed")
        continue
    
    print(f"\n=== Processing: {video_name} ===")
    
    # 書き起こし
    segments, info = model.transcribe(video_path, language="ja", vad_filter=True)
    
    # SRT出力
    with open(output_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            start = seg.start
            end = seg.end
            text = seg.text.strip()
            
            # SRT形式のタイムスタンプ
            start_ts = f"{int(start//3600):02}:{int((start%3600)//60):02}:{start%60:06.3f}".replace(".", ",")
            end_ts = f"{int(end//3600):02}:{int((end%3600)//60):02}:{end%60:06.3f}".replace(".", ",")
            
            f.write(f"{i}\n")
            f.write(f"{start_ts} --> {end_ts}\n")
            f.write(f"{text}\n\n")
            
            if i <= 5 or i % 20 == 0:
                print(f"  {i}: {text[:40]}...")
    
    print(f"  Saved: {output_path}")

print("\n=== All done! ===")
