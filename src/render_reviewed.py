from workflow_utils import import_from_text, render_subtitles
import os

def render_reviewed_sample():
    text_path = "SUBTITLE_REVIEW.txt"
    video_path = "src/sample_raw.mp4"
    logo_path = "raw_videos/スライド用素材/特選/常時_ロゴマーク.JPG"
    output_path = "processed_output/trial_A_plus_plus_final_reviewed.mp4"
    
    if not os.path.exists(text_path):
        print("Error: SUBTITLE_REVIEW.txt not found.")
        return
        
    print("Importing segments from SUBTITLE_REVIEW.txt...")
    segments = import_from_text(text_path)
    
    print(f"Rendering {len(segments)} segments...")
    render_subtitles(video_path, segments, output_path, logo_path)
    print(f"Success! Preview rendered to: {os.path.abspath(output_path)}")

if __name__ == "__main__":
    render_reviewed_sample()
