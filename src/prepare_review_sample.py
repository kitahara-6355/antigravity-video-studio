import json
import os
import re
from workflow_utils import export_to_text

def clean_and_split_regex(segments):
    fillers = ["えーと", "えー", "あのー", "あのー、", "まぁ", "ちょっと", "そのー", "なんか", "そうそうそう"]
    MAX_CHARS = 18
    # Regex to find Japanese particles or punctuation that are good split points
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
            
        parts = split_pattern.findall(text)
        if not parts:
            mid = len(text) // 2
            parts = [text[:mid], text[mid:]]
        
        chunks = []
        current_chunk = ""
        for p in parts:
            if len(current_chunk + p) <= MAX_CHARS:
                current_chunk += p
            else:
                if current_chunk: chunks.append(current_chunk)
                current_chunk = p
        if current_chunk: chunks.append(current_chunk)

        if len(chunks) > 1:
            total_chars = sum(len(c) for c in chunks)
            duration = s["end"] - s["start"]
            current_start = s["start"]
            for c in chunks:
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

def main():
    json_in = "src/segments.json"
    json_out = "src/segments_a_plus_plus.json"
    text_out = "SUBTITLE_REVIEW.txt"
    
    with open(json_in, "r", encoding="utf-8") as f:
        raw = json.load(f)
    
    processed = clean_and_split_regex(raw)
    
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(processed, f, ensure_ascii=False, indent=2)
        
    export_to_text(json_out, text_out)
    print(f"Review sheet generated: {os.path.abspath(text_out)}")

if __name__ == "__main__":
    main()
