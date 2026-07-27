"""
Phase A: テーマテロップの動的切り替え + 字幕SRT作成
"""
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import re
from datetime import timedelta

# --- 共有定数定義 ---
# テーマテキストとタイミング（カット後の時間に調整）
THEMES = [
    {"text": "デザイン書道作家 山田タロウ", "start": 0, "end": 600},
    {"text": "伝統の筆づくり 存続の危機", "start": 600, "end": 1200},
    {"text": "企業ロゴを筆で書く デザイン書道", "start": 1200, "end": 1845},
    {"text": "山田氏のゲスト書道パフォーマンス", "start": 1845, "end": 1899},
    {"text": "山田流：有名ブランドの書を手がける", "start": 1899, "end": 2100},
    {"text": "ユニクロ×書道 未来を繋ぐ挑戦", "start": 2100, "end": 2240},
    {"text": "鬼滅の刃×書道 山田の筆技", "start": 2240, "end": 2400},
    {"text": "有名人も注目！山田の書道教室", "start": 2400, "end": 2584}
]


def escape_ffmpeg_path(path_str):
    """FFmpeg フィルタ構文用にパスの特殊文字をエスケープ"""
    p = str(path_str).replace('\\', '/')
    p = p.replace(':', '\\:')
    p = p.replace("'", "'\\\\''")
    return p


def create_theme_telop(text, output_path, width=303, height=45):
    """テーマテロップ画像を生成"""
    img = Image.new('RGBA', (width, height), (0, 0, 0, 128))
    draw = ImageDraw.Draw(img)
    
    font = _load_font()
    
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    x = (width - text_width) // 2
    y = (height - text_height) // 2
    
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))
    img.save(output_path)
    return output_path


def _load_font():
    """標準あるいは指定の日本語フォントをロード"""
    try:
        return ImageFont.truetype(r"C:\Windows\Fonts\msgothic.ttc", 18)
    except OSError:
        return ImageFont.load_default()


def _generate_theme_telops(telop_dir, themes):
    """テロップ画像を一括生成"""
    print("="*70)
    print("Generating Theme Telops")
    print("="*70)
    for i, theme in enumerate(themes):
        telop_path = telop_dir / f"theme_{i+1}.png"
        create_theme_telop(theme["text"], telop_path)
        print(f"✅ Theme {i+1}: {theme['text']}")


def _build_ffmpeg_filter(logo_path, telop_dir, themes):
    """FFmpegフィルタ（動的切り替え）の構築"""
    filter_parts = []
    
    # ロゴを読み込み
    filter_parts.append(f"movie='{escape_ffmpeg_path(logo_path)}' [logo]")
    
    # 各テロップを読み込み、時間制御付きでオーバーレイ
    for i, theme in enumerate(themes):
        telop_path = telop_dir / f"theme_{i+1}.png"
        filter_parts.append(
            f"movie='{escape_ffmpeg_path(telop_path)}':loop=0,setpts=N/(FRAME_RATE*TB) [t{i+1}]"
        )
    
    # ベース動画にロゴを追加
    filter_parts.append("[0:v][logo] overlay=15:15 [v1]")
    
    # テロップを順次追加
    prev_label = "v1"
    for i in range(len(themes)):
        next_label = f"v{i+2}"
        enable_condition = f"between(t,{themes[i]['start']},{themes[i]['end']})"
        filter_parts.append(
            f"[{prev_label}][t{i+1}] overlay=53:32:enable='{enable_condition}' [{next_label}]"
        )
        prev_label = next_label
        
    return "; ".join(filter_parts), prev_label


def _run_ffmpeg_command(cmd, output_video, last_label):
    """FFmpegコマンドを実行して完了状況を判定"""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
    except FileNotFoundError as e:
        print(f"\n❌ Failed to add telops: ffmpeg command not found ({e})")
        return None
    except OSError as e:
        _register_ffmpeg_tdr_debt(e)
        print(f"\n❌ Unexpected error running ffmpeg: {e}")
        return None
    
    if result.returncode == 0 and output_video.exists():
        size_mb = output_video.stat().st_size / 1024 / 1024
        print(f"\n✅ Video with telops complete: {size_mb:.1f} MB")
        return str(output_video)
    else:
        print(f"\n❌ Failed to add telops")
        print(result.stderr[-1000:] if result.stderr else "")
        return None


def _register_ffmpeg_tdr_debt(exception):
    """FFmpegの予期せぬエラー時に技術負債を登録"""
    try:
        from agents.memory.technical_debt import technical_debt_store
        technical_debt_store.register_debt(
            category="MINOR_INFRA",
            file_path="backend/phase_a_telops_srt.py",
            line_number=116,
            pattern="except_Exception_as_e",
            cause_pattern="DP-01",
            fix_pattern="Logged and returned None",
            registered_by="T-batch_1112a9-bug_hunter-000",
            notes=f"Subprocess call unexpected failure: {exception}",
        )
    except (ImportError, AttributeError, ValueError) as tdr_err:
        print(f"⚠️ Warning: Failed to register Technical Debt: {tdr_err}")


def add_dynamic_telops():
    """テーマテロップを動的に切り替えながら動画に追加"""
    base = Path(r"C:\Users\PC_User\Desktop\script\video-automation")
    input_video = base / "soul_narrative_FINAL_EDITED.mp4"
    output_video = base / "soul_narrative_WITH_TELOPS.mp4"
    
    telop_dir = base / "backend" / "branding" / "theme_telops"
    telop_dir.mkdir(parents=True, exist_ok=True)
    
    logo_path = base / "backend" / "branding" / "logos" / "brand_logo.png"
    
    # テーマテロップの画像生成
    try:
        _generate_theme_telops(telop_dir, THEMES)
    except OSError as e:
        print(f"\n❌ Failed to generate theme telops: {e}")
        return None
    
    # FFmpegフィルタ構築
    filter_complex, last_label = _build_ffmpeg_filter(logo_path, telop_dir, THEMES)
    
    print("\n" + "="*70)
    print("Adding Dynamic Telops to Video")
    print("="*70)
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_video),
        "-filter_complex", filter_complex,
        "-map", f"[{last_label}]",
        "-map", "0:a",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_video)
    ]
    
    return _run_ffmpeg_command(cmd, output_video, last_label)


# --- 字幕SRT処理ヘルパー関数 ---

def _parse_srt_time(time_str):
    """SRTの時間文字列をtimedeltaに変換"""
    try:
        hours, minutes, seconds_ms = time_str.split(':')
        seconds, ms = seconds_ms.split(',')
        return timedelta(hours=int(hours), minutes=int(minutes), seconds=int(seconds), milliseconds=int(ms))
    except (ValueError, IndexError) as e:
        raise ValueError(f"Invalid SRT time format '{time_str}': {e}") from e


def _format_srt_time(td):
    """timedeltaをSRT形式の時間文字列に変換"""
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    ms = int((td.total_seconds() - int(td.total_seconds())) * 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"


def _shift_srt(input_path, shift_seconds):
    """SRTファイルを読み込み、時間をシフトさせたエントリのリストを返す"""
    entries = []
    content = None
    try:
        content = Path(input_path).read_text(encoding='utf-8-sig')
    except (UnicodeDecodeError, OSError):
        try:
            content = Path(input_path).read_text(encoding='cp932')
        except (UnicodeDecodeError, OSError):
            content = None
            
    if content is None:
        return []
        
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    blocks = re.split(r'\n\n+', content.strip())
    
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            time_match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})', lines[1])
            if time_match:
                start = _parse_srt_time(time_match.group(1)) + timedelta(seconds=shift_seconds)
                end = _parse_srt_time(time_match.group(2)) + timedelta(seconds=shift_seconds)
                text = '\n'.join(lines[2:])
                entries.append((start, end, text))
    return entries


def _load_and_filter_srt(srt_path, shift_seconds, max_seconds=None):
    """SRTファイルをロード、シフトし、指定の最大秒数未満でフィルタリング"""
    if not srt_path.exists():
        return []
    try:
        entries = _shift_srt(srt_path, shift_seconds)
        if max_seconds is not None:
            entries = [entry for entry in entries if entry[0].total_seconds() < max_seconds]
        return entries
    except (OSError, UnicodeDecodeError, ValueError) as e:
        print(f"⚠️ Warning: Failed to load {srt_path.name} SRT: {e}")
        return []


def create_combined_srt():
    """統合字幕SRTを作成（カット後の時間に調整）"""
    base = Path(r"C:\Users\PC_User\Desktop\script\video-automation")
    raw_dir = base / "raw_videos" / "AI Studio アップロード用動画"
    output_srt = base / "soul_narrative_subtitles.srt"
    
    print("\n" + "="*70)
    print("Creating Combined SRT")
    print("="*70)
    
    all_entries = []
    
    # シーン01: 0:00 - 30:48 (shift = 0), 30:48 (1848秒) 以降は除外
    srt_01 = raw_dir / "シーン01_前編_whisper_semantic.srt"
    entries_01 = _load_and_filter_srt(srt_01, 0, max_seconds=1848)
    if srt_01.exists():
        print(f"✅ Scene01: {len(entries_01)} entries")
    all_entries.extend(entries_01)
    
    # シーン02: 30:48 - 31:42 (字幕なし)
    print("✅ Scene02: No subtitles (performance)")
    
    # シーン03: 31:42 - 38:38 (shift = 1902), 37:38 (元の時間で2258秒) より後のエントリは除外
    srt_03 = raw_dir / "シーン03_後編01_whisper_semantic.srt"
    entries_03 = _load_and_filter_srt(srt_03, 1902, max_seconds=2258)
    if srt_03.exists():
        print(f"✅ Scene03: {len(entries_03)} entries")
    all_entries.extend(entries_03)
    
    # シーン04: 38:29 - 43:04 (shift = 2309)
    srt_04 = raw_dir / "シーン04_後編02_whisper_semantic.srt"
    entries_04 = _load_and_filter_srt(srt_04, 2309)
    if srt_04.exists():
        print(f"✅ Scene04: {len(entries_04)} entries")
    all_entries.extend(entries_04)
    
    # ソートして書き出し
    all_entries.sort(key=lambda x: x[0])
    
    try:
        with open(output_srt, "w", encoding="utf-8") as f:
            for i, (start, end, text) in enumerate(all_entries, 1):
                f.write(f"{i}\n")
                f.write(f"{_format_srt_time(start)} --> {_format_srt_time(end)}\n")
                f.write(f"{text}\n\n")
    except OSError as e:
        print(f"\n❌ Failed to write combined SRT file: {e}")
        return None
    
    print(f"\n✅ Combined SRT: {len(all_entries)} total entries")
    print(f"   File: {output_srt}")
    return str(output_srt)


def main():
    import time
    start = time.time()
    
    # Step 1: テロップ追加
    video_path = add_dynamic_telops()
    
    # Step 2: 字幕SRT作成
    srt_path = create_combined_srt()
    
    elapsed = time.time() - start
    
    print("\n" + "="*70)
    print(f"Phase A Complete: {elapsed / 60:.1f} minutes")
    print("="*70)
    
    if video_path and srt_path:
        print(f"\n✅ Video: {video_path}")
        print(f"✅ SRT: {srt_path}")
        print("\n🚀 Ready for YouTube upload!")
        return True
    else:
        print("\n❌ Some steps failed")
        return False


if __name__ == "__main__":  # pragma: no cover
    main()
