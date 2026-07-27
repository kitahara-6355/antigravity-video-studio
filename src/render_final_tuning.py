import json
import os
import fugashi
import ipadic
from moviepy import VideoFileClip, TextClip, CompositeVideoClip, ImageClip

def get_split_points(text):
    tagger = fugashi.Tagger(ipadic.MECAB_ARGS)
    words = []
    for word in tagger(text):
        words.append({
            "surface": word.surface,
            "pos": word.feature.pos1,
            "length": len(word.surface)
        })
    return words

def clean_and_split(segments):
    fillers = ["えーと", "えー", "あのー", "あのー、", "まぁ", "ちょっと", "そのー", "なんか", "そうそうそう"]
    MAX_CHARS = 20 # Slightly more lenient since we are scaling
    cleaned = []
    
    for s in segments:
        text = s["text"]
        for f in fillers:
            text = text.replace(f, "")
        text = text.strip()
        if not text: continue
        
        if len(text) <= MAX_CHARS:
            cleaned.append({"start": s["start"], "end": s["end"], "text": text})
            continue
            
        tokens = get_split_points(text)
        midpoint = len(text) / 2
        best_split_idx = -1
        min_dist = float('inf')
        
        current_char_count = 0
        for i, t in enumerate(tokens):
            current_char_count += t["length"]
            if t["pos"] in ["助詞", "補助記号"] or i == len(tokens) - 1:
                dist = abs(current_char_count - midpoint)
                if dist < min_dist:
                    min_dist = dist
                    best_split_idx = current_char_count
        
        if best_split_idx <= 0 or best_split_idx >= len(text):
            best_split_idx = len(text) // 2

        part1 = text[:best_split_idx].strip()
        part2 = text[best_split_idx:].strip()
        
        duration = s["end"] - s["start"]
        ratio = len(part1) / len(text)
        mid_time = s["start"] + (duration * ratio)
        
        cleaned.append({"start": s["start"], "end": mid_time, "text": part1})
        cleaned.append({"start": mid_time, "end": s["end"], "text": part2})
        
    return cleaned

def create_advanced_sample():
    segments_path = "src/segments.json"
    video_path = "src/sample_raw.mp4"
    logo_path = "raw_videos/スライド用素材/特選/常時_ロゴマーク.JPG"
    font_path = r'C:\Windows\Fonts\YuGothB.ttc'
    os.environ["IMAGEMAGICK_BINARY"] = r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"

    with open(segments_path, "r", encoding="utf-8") as f:
        raw_segments = json.load(f)
    
    segments = clean_and_split(raw_segments)
    base_video = VideoFileClip(video_path)
    w, h = map(int, base_video.size)
    
    logo = ImageClip(logo_path).with_duration(base_video.duration).resized(height=50).with_position(("right", 40))

    subs = []
    for s in segments:
        txt = s["text"]
        
        # Auto-scaling logic
        current_font = 60
        max_w = int(w * 0.85)

        # Iteratively reduce font size if text exceeds safe width
        def get_clip(fsize):
            return TextClip(
                text=txt, 
                font_size=fsize, 
                color='white', 
                font=font_path,
                stroke_color='black',
                stroke_width=2,
                text_align='center'
            )
        
        temp_clip = get_clip(current_font)
        while temp_clip.size[0] > max_w and current_font > 30:
            current_font -= 5
            temp_clip = get_clip(current_font)
            
        t_clip = temp_clip.with_start(s["start"]).with_end(s["end"]).with_position(("center", int(h*0.88)))
        subs.append(t_clip)
    
    final = CompositeVideoClip([base_video] + subs + [logo])
    final.write_videofile("processed_output/trial_A_plus_plus_final.mp4", fps=24, codec="libx264")

if __name__ == "__main__":
    create_advanced_sample()
