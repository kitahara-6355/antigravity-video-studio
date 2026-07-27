import json
import os
import fugashi

import ipadic

def get_split_points(text):
    tagger = fugashi.Tagger(f'-d "{ipadic.get_dicdir()}"')
    words = []
    for word in tagger(text):
        words.append({
            "surface": word.surface,
            "pos": word.feature.pos1, # Particle, Noun, etc.
            "length": len(word.surface)
        })
    return words

def filter_filler(segments):
    fillers = ["えーと", "えー", "あのー", "あのー、", "まぁ", "ちょっと", "そのー", "なんか", "そうそうそう"]
    for s in segments:
        text = s["text"]
        for f in fillers:
            text = text.replace(f, "")
        s["text"] = text.strip()
    return [s for s in segments if s["text"]]

def split_linguistically(segments):
    MAX_CHARS = 18
    new_segments = []
    
    for s in segments:
        text = s["text"]
        if len(text) <= MAX_CHARS:
            new_segments.append(s)
            continue
            
        # Analyze linguistic structure
        tokens = get_split_points(text)
        
        # Strategy: Find a split point near the middle, but after a particle or punctuation
        best_split_idx = -1
        midpoint = len(text) / 2
        min_dist = float('inf')
        
        current_char_count = 0
        for i, t in enumerate(tokens):
            current_char_count += t["length"]
            # Particles (助詞) or Punctuation (補助記号) are good split points
            if t["pos"] in ["助詞", "補助記号"] or i == len(tokens) - 1:
                dist = abs(current_char_count - midpoint)
                if dist < min_dist:
                    min_dist = dist
                    best_split_idx = current_char_count
        
        if best_split_idx == -1 or best_split_idx == len(text):
            # Fallback to hard split if no linguistic boundary found (rare in JP)
            best_split_idx = len(text) // 2

        part1 = text[:best_split_idx].strip()
        part2 = text[best_split_idx:].strip()
        
        duration = s["end"] - s["start"]
        ratio = len(part1) / len(text)
        mid_time = s["start"] + (duration * ratio)
        
        new_segments.append({"start": s["start"], "end": mid_time, "text": part1})
        new_segments.append({"start": mid_time, "end": s["end"], "text": part2})
        
    return new_segments

def main():
    with open("src/segments.json", "r", encoding="utf-8") as f:
        segments = json.load(f)
        
    segments = filter_filler(segments)
    segments = split_linguistically(segments)
    
    with open("src/segments_a_plus_plus.json", "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)
    print("A++ segments saved to src/segments_a_plus_plus.json")

if __name__ == "__main__":
    main()
