import re
from pathlib import Path
from datetime import timedelta
import sys

# シーンごとの字幕統合設定
SCENE_CONFIGS = [
    {
        "name": "シーン01",
        "file_name": "シーン01_前編_whisper_semantic.srt",
        "shift_seconds": 0,
        "shift_display": ""
    },
    {
        "name": "シーン02",
        "file_name": None,
        "shift_seconds": 0,
        "skip_reason": "字幕不要（スキップ）",
        "shift_display": ""
    },
    {
        "name": "シーン03",
        "file_name": "シーン03_後編01_whisper_semantic.srt",
        "shift_seconds": 1854,
        "shift_display": "（+30:54シフト）"
    },
    {
        "name": "シーン04",
        "file_name": "シーン04_後編02_whisper_semantic.srt",
        "shift_seconds": 2274,
        "shift_display": "（+37:54シフト）"
    }
]

def parse_srt_time(time_str):
    """Parse SRT time format (HH:MM:SS,mmm) to timedelta"""
    try:
        hours, minutes, sec_and_ms = time_str.split(':')
        seconds, ms = sec_and_ms.split(',')
        
        # Normalize millisecond part to exactly 3 digits
        if len(ms) < 3:
            ms = ms.ljust(3, '0')
        else:
            ms = ms[:3]
            
        return timedelta(hours=int(hours), minutes=int(minutes), seconds=int(seconds), milliseconds=int(ms))
    except (ValueError, IndexError) as e:
        raise ValueError(f"Invalid SRT time format: '{time_str}'. Expected 'HH:MM:SS,mmm'") from e

def format_srt_time(time_delta):
    """Format timedelta to SRT time format"""
    if time_delta.total_seconds() < 0:
        raise ValueError(f"SRT time cannot be negative: {time_delta}")
    total_seconds = int(time_delta.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    ms = time_delta.microseconds // 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"

def _parse_and_shift_block(block_text, offset_seconds):
    """Parse a single SRT block and shift its start/end times by offset_seconds.
    
    Returns a tuple of (start_time, end_time, subtitle_text) or None if parsing fails.
    """
    lines = block_text.strip().split('\n')
    if len(lines) < 3:
        sys.stderr.write(f"Warning: Invalid SRT block (less than 3 lines): {repr(block_text)}\n")
        return None
        
    time_match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})', lines[1])
    if not time_match:
        sys.stderr.write(f"Warning: Invalid SRT time format in line 1: {repr(lines[1])}\n")
        return None
        
    try:
        start_time = parse_srt_time(time_match.group(1)) + timedelta(seconds=offset_seconds)
        end_time = parse_srt_time(time_match.group(2)) + timedelta(seconds=offset_seconds)
        
        if start_time.total_seconds() < 0 or end_time.total_seconds() < 0:
            sys.stderr.write(f"Warning: Shifting by {offset_seconds}s resulted in negative time: {time_match.group(0)}\n")
            if start_time.total_seconds() < 0:
                start_time = timedelta(0)
            if end_time.total_seconds() < 0:
                end_time = timedelta(0)
    except ValueError as e:
        sys.stderr.write(f"Warning: Failed to parse or shift time: {e}\n")
        return None
        
    subtitle_text = '\n'.join(lines[2:])
    return start_time, end_time, subtitle_text

def shift_srt(input_path, offset_seconds):
    """Read SRT file and shift all timestamps by offset_seconds"""
    content = Path(input_path).read_text(encoding='utf-8-sig')
    normalized_content = content.replace('\r\n', '\n')
    
    blocks = re.split(r'\n\n+', normalized_content.strip())
    
    entries = []
    for block in blocks:
        entry = _parse_and_shift_block(block, offset_seconds)
        if entry:
            entries.append(entry)
            
    return entries

def write_combined_srt(srt_entries, output_path):
    """Write combined SRT file"""
    # Sort by start time
    srt_entries.sort(key=lambda x: x[0])
    
    out_path = Path(output_path)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        sys.stderr.write(f"Warning: Failed to create directory {out_path.parent}: {e}\n")
        raise
        
    with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
        for i, (start, end, text) in enumerate(srt_entries, 1):
            f.write(f"{i}\n")
            f.write(f"{format_srt_time(start)} --> {format_srt_time(end)}\n")
            f.write(f"{text}\n\n")

def main():
    base_dir = Path(r"C:\Users\PC_User\Desktop\script\video-automation\raw_videos\AI Studio アップロード用動画")
    output_path = Path(r"C:\Users\PC_User\Desktop\script\video-automation\soul_narrative_combined.srt")
    
    all_entries = []
    
    try:
        for config in SCENE_CONFIGS:
            name = config["name"]
            file_name = config.get("file_name")
            shift_seconds = config["shift_seconds"]
            shift_display = config.get("shift_display", "")
            
            if not file_name:
                skip_reason = config.get("skip_reason", "字幕不要（スキップ）")
                print(f"{name}: {skip_reason}")
                continue
                
            srt_file = base_dir / file_name
            if srt_file.exists():
                try:
                    entries = shift_srt(srt_file, shift_seconds)
                    all_entries.extend(entries)
                    print(f"{name}: {len(entries)} エントリー追加{shift_display}")
                except (OSError, ValueError) as e:
                    sys.stderr.write(f"Error: Failed to process SRT file {srt_file}: {e}\n")
                    raise
            else:
                sys.stderr.write(f"Warning: SRT file does not exist: {srt_file}\n")
                
        write_combined_srt(all_entries, output_path)
        print(f"\n✅ 統合SRT作成完了: {output_path}")
        print(f"   合計 {len(all_entries)} エントリー")
        
    except (OSError, ValueError) as e:
        sys.stderr.write(f"\n❌ Error during SRT combining process: {e}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
