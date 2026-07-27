import requests
import json
import traceback

def debug_transcribe():
    url = "http://localhost:8000/api/transcribe"
    try:
        response = requests.post(url)
        print(f"Status Code: {response.status_code}")
        try:
            print("Response JSON:", response.json())
        except:
            print("Response Text:", response.text)
    except Exception:
        traceback.print_exc()

if __name__ == "__main__":
    debug_transcribe()
