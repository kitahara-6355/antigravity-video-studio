import json
import re

def clean_and_split():
    with open("src/segments.json", "r", encoding="utf-8") as f:
        segments = json.load(f)

    # 1. Filler word removal (Keba-tori)
    fillers = ["えーと", "えー", "あのー", "あのー、", "まぁ", "ちょっと", "そのー", "なんか", "そうそうそう"]
    
    cleaned = []
    for s in segments:
        text = s["text"]
        for f in fillers:
            text = text.replace(f, "")
        
        text = text.strip()
        if not text: continue
        
        s["text"] = text
        
        # 2. Split logic if > 18 chars
        MAX_CHARS = 18
        if len(text) > MAX_CHARS:
            # Simple split by middle space or just half
            mid = len(text) // 2
            # Try to find a good break point around the middle
            break_pt = text.find(" ", mid-5, mid+5)
            if break_pt == -1: break_pt = mid
            
            part1 = text[:break_pt].strip()
            part2 = text[break_pt:].strip()
            
            duration = s["end"] - s["start"]
            ratio = len(part1) / len(text)
            mid_time = s["start"] + (duration * ratio)
            
            cleaned.append({
                "start": s["start"],
                "end": mid_time,
                "text": part1
            })
            cleaned.append({
                "start": mid_time,
                "end": s["end"],
                "text": part2
            })
        else:
            cleaned.append({
                "start": s["start"],
                "end": s["end"],
                "text": text
            })

    with open("src/segments_clean.json", "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)
    print("Cleaned segments saved to src/segments_clean.json")

if __name__ == "__main__":
    clean_and_split()
