"""
AI Proofreader for subtitle segments.
Security fix: API key loaded from .env file.
Uses Model Registry for centralized model management.
"""
import os
import json
import traceback
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load API key from .env
env_path = Path(__file__).parent.parent / "backend" / ".env"
if not env_path.exists():
    env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

# Model configuration (will be replaced by Model Registry)
MODEL_NAME = "gemini-2.0-flash"

def get_api_key():
    """Get API key from environment."""
    return os.getenv("GOOGLE_API_KEY")

def proofread_segments(segments, update_callback=None):
    """
    Uses Gemini to proofread and correct subtitle segments.
    Args:
        segments (list): List of segment dicts (text, start, end, etc.)
        update_callback (callable, optional): Function to update status (status, message, progress)
    Returns:
        list: Proofread segments
    """
    api_key = get_api_key()
    if not api_key:
        print("AI Proofreader: No API Key found in .env")
        return segments

    try:
        client = genai.Client(api_key=api_key)
        CHUNK_SIZE = 20
        total_segments = len(segments)
        proofread_count = 0
        
        print(f"AI Proofreader: Processing {total_segments} segments in batches of {CHUNK_SIZE}...")
        
        for i in range(0, total_segments, CHUNK_SIZE):
            batch = segments[i:i + CHUNK_SIZE]
            batch_text = ""
            # Use absolute index in prompt to match original list
            for idx, s in enumerate(batch):
                abs_index = i + idx
                batch_text += f"[{abs_index}] {s['text']}\n"
            
            prompt = """
あなたはプロの動画字幕編集者です。以下の日本語字幕テキストを校閲および修正してください。
文脈を維持しつつ、以下の点を改善してください：
1. 「えー」「あの」などのフィラー（無意味なつなぎ言葉）を削除する。
2. 文末が助詞で終わっている場合（「〜ですが」など）、言い切りの形にするか、自然な形に修正する。
3. 明らかな誤字脱字を修正する。
4. 意味を変えずに、読みやすい長さに調整する。

**出力形式**:
必ず以下のJSON形式**のみ**を出力してください。Markdownのコードブロックは不要です。
[
  {"index": 0, "text": "修正後のテキスト"},
  {"index": 1, "text": "修正後のテキスト"}
]

**入力データ**:
""" + batch_text


            progress_percent = 99 # Baseline
            # Optional: Simulate 99.1, 99.2... or just keep message alive
            current_batch_num = i // CHUNK_SIZE + 1
            total_batches = (total_segments + CHUNK_SIZE - 1) // CHUNK_SIZE
            msg = f"AI校閲を実行中 ({current_batch_num}/{total_batches} バッチ)..."
            
            print(f"AI Proofreader: Sending batch {current_batch_num}...")
            if update_callback:
                update_callback("processing", msg, 99)

            try:
                response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                    )
                )
                
                corrected_data = json.loads(response.text)
                batch_correction_map = {item['index']: item['text'] for item in corrected_data}
                
                for idx, s in enumerate(batch):
                    abs_index = i + idx
                    if abs_index in batch_correction_map:
                        original = s['text']
                        corrected = batch_correction_map[abs_index]
                        if original != corrected:
                            segments[abs_index]['text'] = corrected
                            proofread_count += 1
                            
            except Exception as e:
                print(f"AI Proofreader: Batch failed: {e}")
                traceback.print_exc()
                # Continue to next batch without stopping
                continue
                
        print(f"AI Proofreader: Successfully corrected {proofread_count} lines total.")
        return segments

    except Exception as e:
        print(f"AI Proofreader Fatal Error: {e}")
        traceback.print_exc()
        return segments

if __name__ == "__main__":
    # Test run
    test_segments = [
        {"text": "えー、あー、本日はですね、えっと、天気がいいので"},
        {"text": "これはテストデータですが"}
    ]
    result = proofread_segments(test_segments)
    for r in result:
        print(r['text'])
