"""
Antigravity 3.0 品質チェックスクリプト
"""
import sys
sys.path.insert(0, 'backend')

def run_quality_check():
    print('=== Antigravity 3.0 品質チェック ===')
    print()
    
    results = {
        'passed': [],
        'failed': [],
        'improvements': []
    }
    
    # 1. モジュールインポートテスト
    print('1. モジュールインポートテスト')
    print('-' * 40)
    modules = [
        'proper_noun_dict',
        'subtitle_normalizer', 
        'semantic_store',
        'asset_library',
        'self_review_engine',
        'learning_loop'
    ]
    
    for m in modules:
        try:
            __import__(m)
            print(f'  {m}: OK')
            results['passed'].append(f'Import: {m}')
        except Exception as e:
            print(f'  {m}: FAILED - {e}')
            results['failed'].append(f'Import: {m} - {e}')
    
    print()
    
    # 2. 固有名詞辞書テスト
    print('2. 固有名詞辞書テスト')
    print('-' * 40)
    try:
        from proper_noun_dict import proper_noun_dict, apply_dictionary
        
        entries = proper_noun_dict.get_all_entries()
        print(f'  辞書エントリ数: {len(entries)}')
        results['passed'].append(f'辞書読み込み: {len(entries)}エントリ')
        
        test = '久北博信先生との対談'
        corrected, corrections = apply_dictionary(test)
        print(f'  テスト入力: {test}')
        print(f'  修正数: {len(corrections)}件')
        if corrections:
            for c in corrections:
                print(f'    {c["original"]} -> {c["corrected"]}')
        results['passed'].append(f'辞書適用: {len(corrections)}件修正')
    except Exception as e:
        print(f'  FAILED: {e}')
        results['failed'].append(f'辞書テスト: {e}')
    
    print()
    
    # 3. SRTエクスポートテスト
    print('3. SRTエクスポートテスト')
    print('-' * 40)
    try:
        from subtitle_normalizer import SRTExporter
        from pathlib import Path
        
        segments = [
            {'start': 0, 'end': 5.2, 'text': 'こんにちは、書家の北原美麗です。'},
            {'start': 5.2, 'end': 12.5, 'text': '本日は山田太郎先生をお招きしています。'}
        ]
        output = SRTExporter.export(segments, Path('test_quality_check.srt'))
        print(f'  出力ファイル: {output}')
        print(f'  ファイル存在: {output.exists()}')
        
        with open(output, 'r', encoding='utf-8') as f:
            content = f.read()
        srt_valid = '-->' in content
        print(f'  SRT形式確認: {srt_valid}')
        
        if srt_valid:
            results['passed'].append('SRTエクスポート: OK')
        else:
            results['failed'].append('SRTエクスポート: 形式不正')
    except Exception as e:
        print(f'  FAILED: {e}')
        results['failed'].append(f'SRTエクスポート: {e}')
    
    print()
    
    # 4. Asset Libraryテスト
    print('4. Asset Libraryテスト')
    print('-' * 40)
    try:
        from asset_library import asset_library
        report = asset_library.get_sufficiency_report()
        print(f'  総アセット数: {report["total_assets"]}')
        print(f'  推奨事項: {len(report["recommendations"])}件')
        results['passed'].append(f'Asset Library: {report["total_assets"]}アセット')
        
        if report['recommendations']:
            for rec in report['recommendations'][:2]:
                results['improvements'].append(f'素材追加推奨: {rec.get("category", "")}')
    except Exception as e:
        print(f'  FAILED: {e}')
        results['failed'].append(f'Asset Library: {e}')
    
    print()
    
    # 5. Learning Loopテスト
    print('5. Learning Loopテスト')
    print('-' * 40)
    try:
        from learning_loop import learning_loop, record_approval
        
        dec = record_approval({'type': 'test', 'text': 'テスト承認'}, tags=['test'], permanent=False)
        print(f'  意思決定記録: {dec.id}')
        print(f'  承認タイプ: {dec.approval_type}')
        results['passed'].append(f'Learning Loop: 意思決定記録OK')
        
        agenda = learning_loop.get_pending_proposals()
        print(f'  未来議会議題: {len(agenda)}件')
    except Exception as e:
        print(f'  FAILED: {e}')
        results['failed'].append(f'Learning Loop: {e}')
    
    print()
    print('=' * 40)
    print(f'合格: {len(results["passed"])}件')
    print(f'失敗: {len(results["failed"])}件')
    print(f'改善提案: {len(results["improvements"])}件')
    print()
    
    if results['failed']:
        print('失敗項目:')
        for f in results['failed']:
            print(f'  - {f}')
    
    if results['improvements']:
        print('改善タスクストック:')
        for i in results['improvements']:
            print(f'  - {i}')
    
    return results

if __name__ == '__main__':
    run_quality_check()
