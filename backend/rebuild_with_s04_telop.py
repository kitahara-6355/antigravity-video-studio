"""
セグメントから再結合し、シーン04のみにテロップを追加
"""
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def create_scene04_telop():
    """シーン04用のテロップを作成"""
    base = Path(__file__).resolve().parent.parent
    output_path = base / "backend" / "branding" / "scene04_telop.png"
    
    telop_text = "有名人も注目！山田の書道教室"
    
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\YuGothB.ttc", 20)
    except OSError:
        try:
            font = ImageFont.truetype(r"C:\Windows\Fonts\msgothic.ttc", 20)
        except OSError:
            font = ImageFont.load_default()
    
    dummy_img = Image.new('RGBA', (1, 1))
    draw = ImageDraw.Draw(dummy_img)
    bbox = draw.textbbox((0, 0), telop_text, font=font)
    text_width = bbox[2] - bbox[0] + 20
    text_height = bbox[3] - bbox[1] + 10
    
    telop = Image.new('RGBA', (text_width, text_height), (0, 0, 0, 180))
    draw = ImageDraw.Draw(telop)
    
    x = 10 - bbox[0]
    y = (text_height - (bbox[3] - bbox[1])) // 2 - bbox[1]
    
    draw.text((x, y), telop_text, font=font, fill=(255, 255, 255, 255))
    
    telop.save(output_path)
    print(f"✅ Scene04 telop created: {output_path}")
    return output_path

def rebuild_and_add_telop():
    """セグメントから再結合し、シーン04にテロップを追加"""
    base = Path(__file__).resolve().parent.parent
    segment_dir = base / "backend" / "temp" / "trimmed_segments"
    output_video = base / "soul_narrative_TELOP_UNIFIED.mp4"
    temp_concat = base / "soul_narrative_REBUILT.mp4"
    
    # Step 1: セグメントを再結合
    print("="*70)
    print("Step 1: Rebuilding from segments")
    print("="*70)
    
    concat_list = segment_dir / "concat.txt"
    
    cmd_concat = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        "-movflags", "+faststart",
        str(temp_concat)
    ]
    
    try:
        result = subprocess.run(cmd_concat, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=300)
        if result.returncode != 0 or not temp_concat.exists():
            print("❌ Segment concatenation failed")
            print(result.stderr[-500:] if result.stderr else "")
            return None
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        print(f"❌ Segment concatenation failed with exception: {e}")
        return None
    
    print(f"✅ Rebuilt: {temp_concat.stat().st_size / 1024 / 1024:.1f} MB")
    
    # Step 2: シーン04にテロップを追加
    print("\n" + "="*70)
    print("Step 2: Adding telop to Scene 04 only (37:36 onwards)")
    print("="*70)
    
    telop_path = create_scene04_telop()
    
    # シーン04の開始時間 = 約2256秒（37:36）
    cmd_overlay = [
        "ffmpeg", "-y",
        "-i", str(temp_concat),
        "-i", str(telop_path),
        "-filter_complex", "[0:v][1:v] overlay=15:15:enable='gte(t,2256)'",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_video)
    ]
    
    try:
        result = subprocess.run(cmd_overlay, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=600)
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        print(f"❌ Failed to add telop with exception: {e}")
        return None
    
    if result.returncode == 0 and output_video.exists():
        size_mb = output_video.stat().st_size / 1024 / 1024
        
        check_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", 
                     "-of", "default=noprint_wrappers=1:nokey=1", str(output_video)]
        try:
            duration_result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=30)
            duration_sec = float(duration_result.stdout.strip())
        except (subprocess.SubprocessError, FileNotFoundError, ValueError) as e:
            print(f"⚠️ Failed to parse video duration: {e}")
            duration_sec = 0.0
            
        duration_min = int(duration_sec // 60)
        duration_sec_remaining = int(duration_sec % 60)
        
        print(f"\n✅ Video complete!")
        print(f"   File: {output_video}")
        print(f"   Size: {size_mb:.1f} MB")
        print(f"   Duration: {duration_min}:{duration_sec_remaining:02d}")
        
        return str(output_video)
    else:
        print("❌ Failed to add telop")
        print(result.stderr[-500:] if result.stderr else "")
        return None

if __name__ == "__main__":
    import time
    start = time.time()
    
    video_path = rebuild_and_add_telop()
    
    elapsed = time.time() - start
    print(f"\nTotal time: {elapsed / 60:.1f} minutes")
    
    if video_path:
        print(f"\n🚀 {video_path}")
    else:
        print("\n❌ Failed")
