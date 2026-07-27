import json
import os
from moviepy import VideoFileClip, TextClip, CompositeVideoClip, ImageClip

def create_premium_sample():
    segments_path = "src/segments_clean.json"
    video_path = "src/sample_raw.mp4"
    logo_path = "raw_videos/スライド用素材/特選/常時_ロゴマーク.JPG"
    font_path = r'C:\Windows\Fonts\YuGothB.ttc'
    
    # Required for MoviePy v2 on Windows
    os.environ["IMAGEMAGICK_BINARY"] = r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"

    with open(segments_path, "r", encoding="utf-8") as f:
        segments = json.load(f)
    
    base_video = VideoFileClip(video_path)
    w, h = map(int, base_video.size)
    
    # Logo (Small and unobtrusive)
    logo = ImageClip(logo_path).with_duration(base_video.duration).resized(height=60).with_position(("right", 40))

    # Premium Subtitles
    subs = []
    for s in segments:
        txt = s["text"]
        
        # Style A+ : Premium Styling
        # White text + Thick Black Stroke for readability without background box
        t_clip = TextClip(
            text=txt, 
            font_size=75, 
            color='white', 
            font=font_path,
            stroke_color='black',
            stroke_width=3,
            size=(int(w*0.9), None),
            text_align='center'
        )
        
        # Position: Bottom 10% of the screen
        t_clip = t_clip.with_start(s["start"]).with_end(s["end"]).with_position(("center", int(h*0.85)))
        subs.append(t_clip)
    
    # Final Composition
    final = CompositeVideoClip([base_video] + subs + [logo])
    
    print("Exporting Premium Sample A+...")
    final.write_videofile("processed_output/trial_A_plus_publication.mp4", fps=24, codec="libx264")
    print("Export Complete.")

if __name__ == "__main__":
    create_premium_sample()
