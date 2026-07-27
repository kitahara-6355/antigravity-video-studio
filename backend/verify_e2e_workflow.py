import requests
import time
import os
import sys
from pathlib import Path

# Config
def get_base_url():
    return os.environ.get("BASE_URL", "http://localhost:8000")

def get_video_path():
    return os.environ.get("VIDEO_PATH", r"C:\Users\PC_User\Desktop\script\video-automation\raw_videos\AI Studio アップロード用動画\シーン01_前編.mp4")

def step_1_upload():
    video_path = get_video_path()
    base_url = get_base_url()
    print(f"--> Uploading {video_path}...")
    if not os.path.exists(video_path):
        print("Error: Video file not found.")
        sys.exit(1)
        
    with open(video_path, 'rb') as f:
        files = {'file': (Path(video_path).name, f, 'video/mp4')}
        try:
            res = requests.post(f"{base_url}/api/settings/video", files=files, timeout=30)
            if res.status_code == 200:
                try:
                    print("Upload Success:", res.json())
                except Exception:
                    print("Upload Success (JSON parse failed):", res.text)
            else:
                print("Upload Failed:", res.text)
                sys.exit(1)
        except Exception as e:
            print(f"Upload Exception: {e}")
            sys.exit(1)

def step_2_transcribe():
    base_url = get_base_url()
    print("--> Triggering Transcription...")
    try:
        res = requests.post(f"{base_url}/api/transcribe", timeout=30)
        if res.status_code == 200:
            try:
                print("Trigger Success:", res.json())
            except Exception:
                print("Trigger Success (JSON parse failed):", res.text)
        else:
            print("Trigger Failed:", res.text)
            sys.exit(1)
    except Exception as e:
        print(f"Trigger Exception: {e}")
        sys.exit(1)

MAX_POLL_ATTEMPTS = 60

def step_3_poll():
    base_url = get_base_url()
    print("--> Polling Status...")
    attempts = 0
    while True:
        attempts += 1
        if attempts > MAX_POLL_ATTEMPTS:
            print(f"Error: Polling timed out after {MAX_POLL_ATTEMPTS} attempts.")
            sys.exit(1)
        try:
            res = requests.get(f"{base_url}/api/transcribe/status", timeout=10)
            if res.status_code == 200:
                try:
                    status = res.json()
                except Exception:
                    print("Poll Success (JSON parse failed):", res.text)
                    status = {}
                s = status.get("status")
                msg = status.get("message")
                prog = status.get("progress", 0)
                
                print(f"Status: {s} | Progress: {prog}% | Message: {msg}")
                
                if s == "completed":
                    print("--> Transcription COMPLETED!")
                    break
                elif s == "failed":
                    print("--> Transcription FAILED!")
                    sys.exit(1)
            else:
                print("Poll Failed:", res.status_code)
                
        except Exception as e:
            print(f"Poll Exception: {e}")
            
        time.sleep(5)

if __name__ == "__main__":
    step_1_upload()
    step_2_transcribe()
    step_3_poll()
