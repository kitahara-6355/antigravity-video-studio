import json
import os
import re
from moviepy import VideoFileClip, TextClip, CompositeVideoClip, ImageClip

def clean_and_split_regex(segments):
    fillers = ["えーと", "えー", "あのー", "あのー、", "まぁ", "ちょっと", "そのー", "なんか", "そうそうそう"]
    MAX_CHARS = 18
    # Regex to find Japanese particles or punctuation that are good split points
    # (は|が|を|に|の|で|と|、|。|？|！|です|ます)
    split_pattern = re.compile(r"(.+?[はがをにのでと、。？！]|.+?です|.+?ます)")

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
            
        # Try to find split points using our regex
        parts = split_pattern.findall(text)
        if not parts:
            # Fallback to hard split if no markers found
            mid = len(text) // 2
            parts = [text[:mid], text[mid:]]
        
        # Combine parts into chunks of appropriate length
        chunks = []
        current_chunk = ""
        for p in parts:
            if len(current_chunk + p) <= MAX_CHARS:
                current_chunk += p
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = p
        if current_chunk:
            chunks.append(current_chunk)

        # Distribute time across chunks
        if len(chunks) > 1:
            total_chars = sum(len(c) for c in chunks)
            duration = s["end"] - s["start"]
            current_start = s["start"]
            for i, c in enumerate(chunks):
                chunk_duration = (len(c) / total_chars) * duration
                cleaned.append({
                    "start": current_start,
                    "end": current_start + chunk_duration,
                    "text": c.strip()
                })
                current_start += chunk_duration
        else:
            cleaned.append({"start": s["start"], "end": s["end"], "text": chunks[0].strip()})
            
    return cleaned

def create_final_a_plus_plus():
    segments_path = "src/segments.json"
    video_path = "src/sample_raw.mp4"
    logo_path = "raw_videos/スライド用素材/特選/常時_ロゴマーク.JPG"
    font_path = r'C:\Windows\Fonts\YuGothB.ttc'
    os.environ["IMAGEMAGICK_BINARY"] = r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"

    with open(segments_path, "r", encoding="utf-8") as f:
        raw_segments = json.load(f)
    
    segments = clean_and_split_regex(raw_segments)
    base_video = VideoFileClip(video_path)
    w, h = map(int, base_video.size)
    
    logo = ImageClip(logo_path).with_duration(base_video.duration).resized(height=50).with_position(("right", 40))

    subs = []
    for s in segments:
        txt = s["text"]
        
        # Auto-scaling logic (Base size 60 per request)
        current_font = 60
        max_w = int(w * 0.88) # Margin

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
        # Prevent clipping
        while temp_clip.size[0] > max_w and current_font > 25:
            current_font -= 4
            temp_clip = get_clip(current_font)
            
        t_clip = temp_clip.with_start(s["start"]).with_end(s["end"]).with_position(("center", int(h*0.88)))
        subs.append(t_clip)
    
    final = CompositeVideoClip([base_video] + subs + [logo])
    output_name = "processed_output/trial_A_plus_plus_final.mp4"
    print(f"Exporting A++ final sample to {output_name}...")
    final.write_videofile(output_name, fps=24, codec="libx264")
    print("Export Complete.")

if __name__ == "__main__":
    create_final_a_plus_plus()
