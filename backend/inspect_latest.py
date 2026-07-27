"""Inspect the latest final output video."""
import subprocess
import json
import glob
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
final_dir = os.path.join(BASE_DIR, "vault-outputs", "final")
preview_dir = os.path.join(BASE_DIR, "vault-outputs", "preview")

def safe_float(val, default=0.0):
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def safe_int(val, default=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default

def probe(path):
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path],
        capture_output=True, text=True, encoding="utf-8", timeout=30, check=True
    )
    return json.loads(r.stdout)

def find_latest_file(directory, pattern_prefix):
    """Find the latest matching file in directory by sorted order."""
    files = sorted(glob.glob(os.path.join(directory, f"{pattern_prefix}_*.mp4")))
    return files

def probe_video_safely(path, label):
    """Run probe and handle standard execution errors."""
    try:
        return probe(path)
    except FileNotFoundError as e:
        print(f"ffprobe command not found for {label}: {e}")
        raise
    except subprocess.CalledProcessError as e:
        print(f"Subprocess error probing {label}: {e}")
        if e.stderr:
            print(f"ffprobe stderr: {e.stderr.strip()}", file=sys.stderr)
        raise
    except subprocess.TimeoutExpired as e:
        print(f"Subprocess timeout probing {label} (timeout={e.timeout}s): {e}")
        raise
    except subprocess.SubprocessError as e:
        print(f"Subprocess error probing {label}: {e}")
        raise
    except json.JSONDecodeError as e:
        doc_preview = e.doc[:100] + "..." if len(e.doc) > 100 else e.doc
        print(f"Failed to parse probe JSON for {label}: {e} (content preview: {doc_preview!r})")
        raise
    except (OSError, ValueError, RuntimeError) as e:
        print(f"Unexpected error probing {label}: {e}")
        raise

def print_stream_info(data):
    """Print video and audio stream information."""
    for s in data.get("streams", []):
        ct = s.get("codec_type")
        if ct == "video":
            codec_name = s.get("codec_name", "unknown")
            width = s.get("width", "unknown")
            height = s.get("height", "unknown")
            r_frame_rate = s.get("r_frame_rate", "unknown")
            print(f"  Video: {codec_name} {width}x{height} @ {r_frame_rate}")
        elif ct == "audio":
            codec_name = s.get("codec_name", "unknown")
            sample_rate = s.get("sample_rate", "unknown")
            channels = s.get("channels", "unknown")
            print(f"  Audio: {codec_name} {sample_rate}Hz {channels}ch")

def print_verdict(duration):
    """Check target duration range and print verdict."""
    print(f"\n{'='*50}")
    print("VERDICT")
    print(f"{'='*50}")
    if duration > 1800:
        print(f"❌ STILL TOO LONG: {duration/60:.1f}min (target 20min)")
    elif duration < 600:
        print(f"⚠️ TOO SHORT: {duration/60:.1f}min (target 20min)")
    else:
        print(f"✅ DURATION OK: {duration/60:.1f}min (target 20min)")

def main():
    # Find latest final
    finals = find_latest_file(final_dir, "final")
    if not finals:
        print("No final files found.")
        return 1
    
    print("All final files:")
    for f in finals:
        try:
            print(f"  {os.path.basename(f)}: {os.path.getsize(f)/1024/1024:.1f}MB")
        except OSError:
            print(f"  {os.path.basename(f)}: unknown size")

    latest_final = finals[-1]
    try:
        data = probe_video_safely(latest_final, "final")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError, RuntimeError) as e:
        print(f"Error: Failed to probe final video: {e}", file=sys.stderr)
        return 1
        
    fmt = data.get("format", {})
    dur = safe_float(fmt.get("duration", 0))
    size = safe_int(fmt.get("size", 0)) / 1024 / 1024

    print(f"\nLATEST FINAL: {os.path.basename(latest_final)}")
    print(f"  Duration: {dur:.1f}s = {dur/60:.1f}min")
    print(f"  Size: {size:.1f}MB")

    print_stream_info(data)

    # Latest preview
    previews = find_latest_file(preview_dir, "preview")
    if not previews:
        print("No preview files found.")
        return 1
        
    latest_preview = previews[-1]
    try:
        d2 = probe_video_safely(latest_preview, "preview")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError, RuntimeError) as e:
        print(f"Error: Failed to probe preview video: {e}", file=sys.stderr)
        return 1
        
    f2 = d2.get("format", {})
    dur_p = safe_float(f2.get("duration", 0))
    print(f"\nLATEST PREVIEW: {os.path.basename(latest_preview)}")
    print(f"  Duration: {dur_p:.1f}s = {dur_p/60:.1f}min")
    print(f"  Size: {safe_int(f2.get('size', 0))/1024/1024:.1f}MB")

    print_verdict(dur)
    return 0

if __name__ == "__main__":
    sys.exit(main())
