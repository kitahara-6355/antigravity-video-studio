"""
実動画テスト: 固有名詞辞書の適用
"""
import sys
sys.path.insert(0, 'backend')

from proper_noun_dict import apply_dictionary
from subtitle_normalizer import SRTExporter
from pathlib import Path
import re

def parse_srt(srt_path: Path) -> list:
    """SRTファイルをパース"""
    with open(srt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    segments = []
    blocks = content.strip().split('\n\n')
    
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            try:
                index = int(lines[0])
                timestamp = lines[1]
                text = '\n'.join(lines[2:])
                
                # タイムスタンプをパース
                match = re.match(r'(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})', timestamp)
                if match:
                    h1, m1, s1, ms1, h2, m2, s2, ms2 = match.groups()
                    start = int(h1)*3600 + int(m1)*60 + int(s1) + int(ms1)/1000
                    end = int(h2)*3600 + int(m2)*60 + int(s2) + int(ms2)/1000
                    
                    segments.append({
                        'id': f'seg_{index:03d}',
                        'start': start,
                        'end': end,
                        'text': text
                    })
            except:
                pass
    
    return segments

def main():
    print('=== 実動画テスト: 固有名詞辞書の適用 ===')
    print()
    
    # SRTファイルを読み込み
    srt_path = Path('raw_videos/AI Studio アップロード用動画/シーン01_前編_official.srt')
    print(f'入力ファイル: {srt_path}')
    
    segments = parse_srt(srt_path)
    print(f'セグメント数: {len(segments)}')
    print()
    
    # 固有名詞辞書を適用
    print('固有名詞辞書を適用中...')
    print('-' * 50)
    
    total_corrections = 0
    corrected_segments = []
    
    for seg in segments:
        corrected_text, corrections = apply_dictionary(seg['text'])
        
        if corrections:
            total_corrections += len(corrections)
            print(f"[{seg['id']}] 修正あり:")
            print(f"  元: {seg['text'][:50]}...")
            print(f"  後: {corrected_text[:50]}...")
            for c in corrections:
                print(f"    ✓ {c['original']} → {c['corrected']}")
            print()
        
        corrected_segments.append({
            **seg,
            'text': corrected_text,
            'corrections': corrections
        })
    
    print('-' * 50)
    print(f'総修正数: {total_corrections}件')
    print()
    
    # 修正済みSRTを出力
    output_path = Path('output/subtitles/シーン01_前編_corrected.srt')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    SRTExporter.export(corrected_segments, output_path)
    print(f'修正済みSRT出力: {output_path}')
    
    # 最初の10セグメントを表示
    print()
    print('=== 修正後の最初の10セグメント ===')
    for seg in corrected_segments[:10]:
        print(f"[{seg['start']:.1f}s] {seg['text']}")

if __name__ == '__main__':
    main()
