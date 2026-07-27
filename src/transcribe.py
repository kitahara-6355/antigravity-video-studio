from faster_whisper import WhisperModel
import json
import os
import time
from moviepy.editor import VideoFileClip
import ai_proofreader

def run_transcription(input_path, output_path):
    """
    Transcribes the input media file using faster-whisper, then Proofreads with Gemini.
    Args:
        input_path (str): Path to input file (mp4, wav, etc.)
        output_path (str): Path to save the JSON segments.
    """
    STATUS_FILE = os.path.join(os.path.dirname(output_path), "transcription_status.json")

    def update_status(status, message=None, progress=0):
        try:
            with open(STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump({"status": status, "message": message, "progress": progress}, f)
        except:
            pass

    if not os.path.exists(input_path):
        return {"status": "error", "message": f"Input file not found: {input_path}"}

    try:
        # 1. Get Duration for Progress Calculation
        try:
            clip = VideoFileClip(input_path)
            total_duration = clip.duration
            clip.close()
            print(f"Video Duration: {total_duration:.2f}s")
        except Exception as e:
            print(f"Failed to get duration: {e}")
            total_duration = 1800 # Fallback 30min

        model_size = "medium" # good balance for CPU
        update_status("processing", f"Loading Model ({model_size})...", 0)
        print(f"Loading faster-whisper model ({model_size})...")
        
        # Run on CPU with INT8 quantization for speed
        model = WhisperModel(model_size, device="cpu", compute_type="int8")

        update_status("processing", "Transcribing...", 0)
        print(f"Transcribing {input_path}...")
        
        segments, info = model.transcribe(input_path, beam_size=1, language="ja")

        formatted_segments = []
        last_progress_update = 0

        for segment in segments:
            # Calculate Progress
            progress = int((segment.end / total_duration) * 100)
            progress = min(progress, 99) # Keep 100 for completion
            
            # Update status file occasionally to reduce IO
            if time.time() - last_progress_update > 0.5:
                update_status("processing", f"Transcribing... {progress}%", progress)
                last_progress_update = time.time()
                print(f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text} ({progress}%)")

            formatted_segments.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip(),
                "sourceStart": segment.start,
                "sourceEnd": segment.end
            })
        
        update_status("processing", "Transcribing Complete. Processing AI Proofreading...", 99)

        # --- AI PROOFREADING STEP ---
        update_status("processing", "AI校閲を実行中 (Gemini 3.0)...", 99)
        print("Starting AI Proofreading...")
        formatted_segments = ai_proofreader.proofread_segments(formatted_segments, update_callback=update_status)
        # ----------------------------

        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Save standard JSON
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(formatted_segments, f, ensure_ascii=False, indent=2)
            
        print(f"Transcription saved to {output_path}")
        update_status("completed", "Success", 100)
        return {"status": "success", "count": len(formatted_segments)}
        
    except Exception as e:
        print(f"Transcription failed: {str(e)}")
        update_status("failed", str(e), 0)
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    # Test
    # run_transcription("src/sample_raw.mp4", "src/segments_a_plus_plus.json")
    pass
