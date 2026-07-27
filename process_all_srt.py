"""
全シーンSRT修正スクリプト
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

def process_srt(input_path: Path, output_path: Path) -> dict:
    """SRTファイルを処理"""
    print(f'処理中: {input_path.name}')
    
    segments = parse_srt(input_path)
    print(f'  セグメント数: {len(segments)}')
    
    total_corrections = 0
    corrected_segments = []
    correction_details = []
    
    for seg in segments:
        corrected_text, corrections = apply_dictionary(seg['text'])
        
        if corrections:
            total_corrections += len(corrections)
            for c in corrections:
                correction_details.append({
                    'seg_id': seg['id'],
                    'original': c['original'],
                    'corrected': c['corrected']
                })
        
        corrected_segments.append({
            **seg,
            'text': corrected_text
        })
    
    # 出力
    output_path.parent.mkdir(parents=True, exist_ok=True)
    SRTExporter.export(corrected_segments, output_path)
    
    print(f'  修正数: {total_corrections}件')
    print(f'  出力: {output_path}')
    
    return {
        'input': str(input_path),
        'output': str(output_path),
        'segments': len(segments),
        'corrections': total_corrections,
        'details': correction_details
    }

def main():
    print('=== 全シーンSRT修正 ===')
    print()
    
    # 入力ディレクトリ
    input_dir = Path('raw_videos/AI Studio アップロード用動画')
    output_dir = Path('output/subtitles')
    
    # 処理対象のSRTファイル（officialまたはproofread）
    srt_files = list(input_dir.glob('*_official.srt'))
    
    print(f'対象ファイル: {len(srt_files)}件')
    print()
    
    results = []
    total_corrections = 0
    
    for srt_path in srt_files:
        # 出力ファイル名
        output_name = srt_path.stem.replace('_official', '_corrected') + '.srt'
        output_path = output_dir / output_name
        
        result = process_srt(srt_path, output_path)
        results.append(result)
        total_corrections += result['corrections']
        print()
    
    # サマリー
    print('=' * 50)
    print('処理完了サマリー')
    print('=' * 50)
    print(f'処理ファイル数: {len(results)}')
    print(f'総修正数: {total_corrections}件')
    print()
    
    print('修正内容:')
    for r in results:
        if r['details']:
            print(f"  {Path(r['input']).name}:")
            for d in r['details'][:5]:  # 最初の5件のみ表示
                print(f"    - {d['original']} -> {d['corrected']}")
            if len(r['details']) > 5:
                print(f"    ... 他 {len(r['details']) - 5}件")

if __name__ == '__main__':
    main()
