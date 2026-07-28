"""Video inspection tool - verifies actual video properties."""
import subprocess
import json
import glob
import sys
from pathlib import Path
from PIL import Image

from path_resolver import vault_assets_dir, vault_outputs_dir

def inspect_thumbnail(path, label="Thumbnail"):
    """
    サムネイル画像の品質要件を検証する。
    - 生成画像の解像度が 1280x720 以上であること
    - アスペクト比が 16:9 であること
    - ファイルサイズが 4MB 未満であること
    - 出力ファイルが正常に存在し、破損していない（Pillow等で正常にロード可能である）こと
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Thumbnail file not found: {file_path}")
        
    size_bytes = file_path.stat().st_size
    if size_bytes >= 4 * 1024 * 1024:
        raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")
        
    try:
        with Image.open(file_path) as img:
            img.verify()
    except (OSError, SyntaxError) as e:
        raise ValueError(f"Image is corrupted or invalid format: {e}")
        
    try:
        with Image.open(file_path) as img:
            width, height = img.size
    except (OSError, ValueError) as e:
        raise ValueError(f"Failed to load image for resolution check: {e}")
        
    if height <= 0:
        raise ValueError(f"Height must be greater than zero. Got {height}")
    if width < 1280 or height < 720:
        raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
        
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 1e-3:
        raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")
        
    print(f"\n=== {label} ===")
    print(f"  Path: {file_path}")
    print(f"  Resolution: {width}x{height} (Aspect Ratio: {aspect_ratio:.2f})")
    print(f"  Size: {size_bytes / 1024 / 1024:.2f}MB")
    
    return {
        "path": str(file_path),
        "width": width,
        "height": height,
        "size_bytes": size_bytes
    }

def inspect_video(path, label):
    if path is None:
        raise TypeError("path must be a string or path-like object, not None")
    if not isinstance(path, (str, Path)):
        raise TypeError(f"path must be a string or path-like object, got {type(path).__name__}")
    if not str(path).strip():
        raise ValueError("path cannot be empty or whitespace only")
    if label is None:
        raise TypeError("label must be a string, not None")
    if not isinstance(label, str):
        raise TypeError(f"label must be a string, got {type(label).__name__}")
    if not label.strip():
        raise ValueError("label cannot be empty or whitespace only")

    import os
    if not os.path.exists(path):
        raise FileNotFoundError(f"Video file not found: {path}")
        
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json',
             '-show_format', '-show_streams', path],
            capture_output=True, text=True, encoding='utf-8', check=True
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"ffprobe command not found. Please ensure ffmpeg/ffprobe is installed: {e}")
    except subprocess.CalledProcessError as e:
        raise ValueError(f"ffprobe execution failed with exit code {e.returncode}: {e.stderr}")
        
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse ffprobe output as JSON: {e}. Output: {result.stdout!r}")

    if not isinstance(data, dict):
        raise ValueError(f"Expected ffprobe output JSON to be a dictionary, got {type(data).__name__}")

    fmt = data.get('format', {})
    if not isinstance(fmt, dict):
        fmt = {}
    
    try:
        duration = float(fmt.get('duration', 0))
    except (ValueError, TypeError):
        duration = 0.0

    try:
        size_mb = int(fmt.get('size', 0)) / 1024 / 1024
    except (ValueError, TypeError):
        size_mb = 0.0

    try:
        bitrate = int(fmt.get('bit_rate', 0)) / 1000
    except (ValueError, TypeError):
        bitrate = 0.0
    
    print(f"\n=== {label} ===")
    print(f"  Duration: {duration:.1f}s = {duration/60:.1f}min = {duration/3600:.2f}hr")
    print(f"  Size: {size_mb:.1f}MB")
    print(f"  Bitrate: {bitrate:.0f} kbps")
    
    for s in data.get('streams', []):
        ct = s.get('codec_type')
        if ct == 'video':
            w = s.get('width', '?')
            h = s.get('height', '?')
            codec = s.get('codec_name', '?')
            fps = s.get('r_frame_rate', '?')
            nb_frames = s.get('nb_frames', '?')
            print(f"  Video: {codec} {w}x{h} @ {fps} fps, frames={nb_frames}")
        elif ct == 'audio':
            codec = s.get('codec_name', '?')
            sr = s.get('sample_rate', '?')
            ch = s.get('channels', '?')
            print(f"  Audio: {codec} {sr}Hz {ch}ch")
    
    return duration

def main():
    # Final
    final = str(vault_outputs_dir() / "final" / "final_20260519_125938.mp4")
    d_final = 0.0
    try:
        d_final = inspect_video(final, "Final Output")
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"Skipping Final Output: {e}")
    
    # Preview
    preview = str(vault_outputs_dir() / "preview" / "preview_20260519_125345.mp4")
    d_preview = 0.0
    try:
        d_preview = inspect_video(preview, "Preview")
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"Skipping Preview: {e}")
    
    # Merged
    merged_files = glob.glob(str(vault_outputs_dir() / "merged" / "merged_*.mp4"))
    for mf in merged_files:
        try:
            inspect_video(mf, f"Merged: {mf.split(chr(92))[-1]}")
        except (FileNotFoundError, ValueError, RuntimeError) as e:
            print(f"Skipping Merged {mf}: {e}")
    
    # Raw files
    import os
    raw_dir = str(vault_assets_dir() / "raw_videos" / "本番RAW01 対談_山田")
    if os.path.exists(raw_dir):
        print("\n=== Raw Files ===")
        total_raw = 0
        for f in sorted(os.listdir(raw_dir)):
            if f.endswith('.mp4'):
                fp = os.path.join(raw_dir, f)
                d = inspect_video(fp, f"  RAW: {f}")
                total_raw += d
        print(f"\n  Total raw duration: {total_raw:.1f}s = {total_raw/60:.1f}min")
    
    # Key diagnosis
    print("\n" + "=" * 60)
    print("DIAGNOSIS")
    print("=" * 60)
    print(f"SmartCut reported: 602seg / 20.1min")
    print(f"Actual final:      {d_final:.1f}s = {d_final/60:.1f}min")
    print(f"Actual preview:    {d_preview:.1f}s = {d_preview/60:.1f}min")
    if d_final > 1800:  # > 30min
        print(">>> BUG CONFIRMED: SmartCut selection NOT applied to render!")

if __name__ == '__main__':
    main()
