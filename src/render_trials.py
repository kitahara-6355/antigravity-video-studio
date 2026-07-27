import json
import os
from moviepy import VideoFileClip, TextClip, CompositeVideoClip, ImageClip, ColorClip
import moviepy.video.fx as vfx

def create_trial_pack():
    segments_path = "src/segments.json"
    video_path = "src/sample_raw.mp4"
    logo_path = "raw_videos/スライド用素材/特選/常時_ロゴマーク.JPG"
    
    with open(segments_path, "r", encoding="utf-8") as f:
        segments = json.load(f)
    
    base_video = VideoFileClip(video_path)
    w, h = map(int, base_video.size)
    
    # Common Logo
    logo = ImageClip(logo_path).with_duration(base_video.duration).resized(height=80).with_position(("right", "bottom"))

    # Style A: Full Subtitles (Mobile focus)
    full_subs = []
    for s in segments:
        txt = s["text"]
        if len(txt) > 20: txt = txt[:20] + "\n" + txt[20:]
            
        t_clip = TextClip(text=txt, font_size=60, color='white', font=r'C:\Windows\Fonts\msgothic.ttc', 
                         bg_color='rgba(0,0,0,128)', size=(int(w*0.8), None))
        t_clip = t_clip.with_start(s["start"]).with_end(s["end"]).with_position(("center", h-150))
        full_subs.append(t_clip)
    
    # result_a = CompositeVideoClip([base_video] + full_subs + [logo])
    # result_a.write_videofile("processed_output/trial_full_subtitles.mp4", fps=24, codec="libx264")

    # Style B: Keyword Highlight (Atmosphere first)
    keyword_subs = []
    for s in segments:
        if len(s["text"]) < 10: continue
        
        txt = s["text"]
        t_clip = TextClip(text=txt, font_size=80, color='yellow', font=r'C:\Windows\Fonts\msgothic.ttc', 
                         stroke_color='black', stroke_width=2, size=(int(w*0.7), None))
        t_clip = t_clip.with_start(s["start"]).with_duration(2).with_position("center")
        keyword_subs.append(t_clip)
        
    # result_b = CompositeVideoClip([base_video] + keyword_subs + [logo])
    # result_b.write_videofile("processed_output/trial_keyword_highlight.mp4", fps=24, codec="libx264")

    # Style C: Dynamic Digest (High Engagement)
    result_c = CompositeVideoClip([base_video.with_effects([vfx.MirrorX()])] + keyword_subs + [logo])
    result_c.write_videofile("processed_output/trial_dynamic_digest.mp4", fps=24, codec="libx264")

if __name__ == "__main__":
    os.environ["IMAGEMAGICK_BINARY"] = r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"
    create_trial_pack()
