import json
import re
import os

# [WORKAROUND] Patch PIL for MoviePy 1.0.3 + Pillow 10+ compatibility
try:
    import PIL.Image
    if not hasattr(PIL.Image, 'ANTIALIAS'):
        PIL.Image.ANTIALIAS = PIL.Image.LANCZOS
except ImportError:
    pass

# [CRITICAL] Setup ImageMagick BEFORE any moviepy imports
IM_PATH = r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"
os.environ["IMAGEMAGICK_BINARY"] = IM_PATH

# MoviePy Imports (Use Editor for complete initialization)
try:
    from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip, ImageClip, AudioFileClip, CompositeAudioClip, concatenate_audioclips
    import moviepy.video.fx.all as vfx
    import moviepy.audio.fx.all as afx
    
    # Map for consistency
    MultiplyVolume = afx.volumex
    resize = vfx.resize
    
except ImportError:
    # Manual Submodule Fallback (v2 or restricted environments)
    try:
        from moviepy.video.io.VideoFileClip import VideoFileClip
        from moviepy.video.VideoClip import TextClip, ImageClip
        from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
        from moviepy.audio.io.AudioFileClip import AudioFileClip
        from moviepy.audio.AudioClip import CompositeAudioClip, concatenate_audioclips
        from moviepy.video.fx.resize import resize
        from moviepy.audio.fx.volumex import volumex as MultiplyVolume
    except ImportError as e:
        print(f"CRITICAL: Failed to import MoviePy: {e}")
        raise e

# Setup ImageMagick configuration if available
try:
    from moviepy.config import change_settings
    change_settings({"IMAGEMAGICK_BINARY": IM_PATH})
except:
    pass

def format_timestamp(seconds):
    td = (seconds)
    mins = int(td // 60)
    secs = int(td % 60)
    millis = int((td % 1) * 10)
    return f"{mins:02}:{secs:02}.{millis}"

def parse_timestamp(ts_str):
    mins, rest = ts_str.split(":")
    secs, millis = rest.split(".")
    return int(mins) * 60 + int(secs) + float(f"0.{millis}")

def export_to_text(json_path, text_path):
    with open(json_path, "r", encoding="utf-8") as f:
        segments = json.load(f)
    
    with open(text_path, "w", encoding="utf-8") as f:
        f.write("# --- 字幕修正シート (SUBTITLE REVIEW SHEET) ---\n")
        f.write("# 【基本ルール】\n")
        f.write("# 1. 誤字修正: 後のテキストを直接書き換えてください。\n")
        f.write("# 2. 字幕の分割: 1行が長い場合、Enterで改行し、新しい [] と時間を設定してください。\n")
        f.write("# 3. テキストの追加: 既存の行をコピー＆ペーストして、時間と文字を調整してください。\n")
        f.write("# 4. タイミングの一括ズレ修正: 行の先頭に [+1.5] や [-0.5] と書くと、その行以降の全字幕がスライドします。\n")
        f.write("# ※ [] の記号や -> は消さないでください。\n\n")
        for s in segments:
            start = format_timestamp(s["start"])
            end = format_timestamp(s["end"])
            f.write(f"[{start} -> {end}] {s['text']}\n")

def import_from_text(text_path):
    segments = []
    # Match standard [00:00.0 -> 00:00.0] or relative [+1.0]
    line_pattern = re.compile(r"\[(\d{2}:\d{2}\.\d) -> (\d{2}:\d{2}\.\d)\] (.*)")
    shift_pattern = re.compile(r"\[([+-]\d+\.?\d*)\] (.*)")
    
    if not os.path.exists(text_path):
        return []

    with open(text_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    current_offset = 0.0
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        # Check for global shift comment: # SHIFT: +1.5
        if line.startswith("# SHIFT:"):
            try:
                current_offset += float(line.split(":")[1].strip())
            except: pass
            continue
            
        if line.startswith("#"): continue
            
        # 1. Match standard timestamp
        match = line_pattern.match(line)
        if match:
            start = parse_timestamp(match.group(1)) + current_offset
            end = parse_timestamp(match.group(2)) + current_offset
            text = match.group(3).strip()
            if text:
                segments.append({"start": start, "end": end, "text": text})
            continue

        # 2. Match relative shift [ripple edit]
        s_match = shift_pattern.match(line)
        if s_match:
            nudge = float(s_match.group(1))
            current_offset += nudge
            text = s_match.group(2).strip()
            continue
            
        # 3. Fallback: append to last segment
        if segments:
            segments[-1]["text"] += " " + line
                
    return segments

def render_subtitles(video_path, segments, output_path, logo_path=None, style_name="default", bgm_path=None):
    print("DEBUG: LOADED NEW WORKFLOW UTILS v2 [Checked with_duration usage]")
    # ImageMagick configured globally
    font_path = r'C:\Windows\Fonts\YuGothB.ttc'
    
    base_video = VideoFileClip(video_path)
    w, h = map(int, base_video.size)
    
    logo = None
    if logo_path and os.path.exists(logo_path):
        # v1.0.3: set_duration, resize, set_position
        logo = ImageClip(logo_path).set_duration(base_video.duration)
        if resize:
            logo = logo.fx(resize, height=50)
        logo = logo.set_position(("right", 40))

    # Style Definitions
    styles = {
        "default": {"color": "white", "stroke_color": "black", "stroke_width": 2, "font_scale": 1.0, "position": ("center", int(h*0.88))},
        "youtuber": {"color": "#FFD700", "stroke_color": "black", "stroke_width": 6, "font_scale": 1.3, "position": ("center", int(h*0.82))},
        "cinematic": {"color": "#F0F0F0", "stroke_color": "black", "stroke_width": 1, "font_scale": 0.8, "position": ("center", int(h*0.90)), "kerning": 2}, 
        "cute": {"color": "#FF69B4", "stroke_color": "white", "stroke_width": 5, "font_scale": 1.1, "position": ("center", int(h*0.88))}
    }
    
    current_style = styles.get(style_name, styles["default"])

    subs = []
    for s in segments:
        txt = s["text"]
        base_size = 60
        current_font = int(base_size * current_style["font_scale"])
        max_w = int(w * 0.9)

        def get_clip(fsize):
            args = {
                "txt": txt,
                "fontsize": fsize,
                "color": current_style["color"],
                "font": font_path,
                "print_cmd": True
            }
            if current_style.get("stroke_color"):
                args["stroke_color"] = current_style["stroke_color"]
                args["stroke_width"] = current_style["stroke_width"]
            if "kerning" in current_style:
                args["kerning"] = current_style["kerning"]
            
            print(f"DEBUG: Creating TextClip with txt='{txt[:10]}...', fontsize={fsize}, color={args['color']}")
            return TextClip(**args)
        
        try:
            temp_clip = get_clip(current_font)
        except Exception as e:
             print(f"DEBUG: get_clip failed: {e}")
             # Fallback to simple v1 style
             temp_clip = TextClip(txt, font=font_path, fontsize=current_font, color=current_style["color"])

        # v2: resize check?
        # temp_clip.size might work
        
        t_clip = temp_clip.set_start(s["start"]).set_end(s["end"]).set_position(current_style["position"])
        subs.append(t_clip)
    
    # --- BGM Handling ---
    final_audio = base_video.audio
    
    if bgm_path and os.path.exists(bgm_path):
        try:
            bgm_clip = AudioFileClip(bgm_path)
            # Manual loop
            n_loops = int(base_video.duration / bgm_clip.duration) + 1
            bgm_looped = concatenate_audioclips([bgm_clip] * n_loops).set_duration(base_video.duration)
            
            # Volume control
            bgm_final = bgm_looped
            if MultiplyVolume:
                try:
                    # Try v1 style (function)
                    bgm_final = MultiplyVolume(bgm_looped, 0.2)
                except:
                    # Fallback or v2 style (if somehow it's mixed)
                    try:
                        bgm_final = bgm_looped.volumex(0.2)
                    except:
                        pass
            else:
                print("Warning: MultiplyVolume not available")

            # Mix
            if final_audio:
                 final_audio = CompositeAudioClip([final_audio, bgm_final])
            else:
                 final_audio = bgm_final
        except Exception as e:
            print(f"Warning: Failed to load/mix BGM: {e}")
            import traceback
            traceback.print_exc()

    clips = [base_video] + subs
    if logo: clips.append(logo)
    
    final = CompositeVideoClip(clips)
    
    # v2: setter for audio?
    final.audio = final_audio
    
    final.write_videofile(output_path, fps=24, codec="libx264")
    
    base_video.close()
    if bgm_path and os.path.exists(bgm_path):
         try:
             bgm_clip.close()
         except: pass
    final.close()
