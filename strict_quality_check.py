"""
Antigravity 3.0 厳格な品質チェック
全モジュールのテストと改善タスク抽出
"""
import sys
sys.path.insert(0, 'backend')

import json
from pathlib import Path
from datetime import datetime

def run_strict_quality_check():
    print('=' * 60)
    print('Antigravity 3.0 厳格な品質チェック')
    print('=' * 60)
    print()
    
    results = {
        'passed': [],
        'failed': [],
        'warnings': [],
        'improvements': []
    }
    
    # 1. モジュールインポートテスト
    print('1. モジュールインポートテスト')
    print('-' * 50)
    modules = [
        ('proper_noun_dict', 'ProperNounDictionary'),
        ('subtitle_normalizer', 'SubtitleNormalizer'),
        ('semantic_store', 'SemanticSubtitleStoreV2'),
        ('telop_proposal_engine', 'TelopProposalEngine'),
        ('asset_library', 'CreativeAssetLibrary'),
        ('generation_engine', 'GenerationEngine'),
        ('self_review_engine', 'SelfReviewEngine'),
        ('learning_loop', 'LearningLoop'),
        ('antigravity_pipeline', 'AntigravityPipeline'),
        ('model_registry', 'get_model')
    ]
    
    for mod_name, class_name in modules:
        try:
            mod = __import__(mod_name)
            if hasattr(mod, class_name):
                print(f'  ✅ {mod_name}.{class_name}')
                results['passed'].append(f'Import: {mod_name}.{class_name}')
            else:
                print(f'  ⚠️ {mod_name} (missing {class_name})')
                results['warnings'].append(f'{mod_name}: {class_name} not found')
        except Exception as e:
            print(f'  ❌ {mod_name}: {e}')
            results['failed'].append(f'Import: {mod_name} - {e}')
    print()
    
    # 2. 固有名詞辞書テスト
    print('2. 固有名詞辞書テスト')
    print('-' * 50)
    try:
        from proper_noun_dict import proper_noun_dict, apply_dictionary
        
        entries = proper_noun_dict.get_all_entries()
        print(f'  辞書エントリ数: {len(entries)}')
        
        if len(entries) < 5:
            results['improvements'].append('固有名詞辞書: エントリ数が少ない（5件未満）')
        
        # テスト適用
        test_cases = [
            ('久北先生', '山田先生', True),
            ('初夏の書家', '書家の書家', True),
            ('普通のテキスト', '普通のテキスト', False),
        ]
        
        for original, expected_contains, should_correct in test_cases:
            corrected, corrections = apply_dictionary(original)
            if should_correct and len(corrections) == 0:
                results['warnings'].append(f'辞書適用: "{original}" が修正されなかった')
            elif not should_correct and len(corrections) > 0:
                results['warnings'].append(f'辞書適用: "{original}" が誤修正された')
            else:
                results['passed'].append(f'辞書適用: {original}')
        
        print(f'  テストケース: {len(test_cases)}件完了')
    except Exception as e:
        print(f'  ❌ エラー: {e}')
        results['failed'].append(f'固有名詞辞書テスト: {e}')
    print()
    
    # 3. SRTエクスポートテスト
    print('3. SRTエクスポートテスト')
    print('-' * 50)
    try:
        from subtitle_normalizer import SRTExporter
        
        test_segments = [
            {'start': 0, 'end': 5.2, 'text': 'テストセグメント1'},
            {'start': 5.2, 'end': 12.5, 'text': 'テストセグメント2'},
        ]
        
        output = SRTExporter.export(test_segments, Path('test_strict_check.srt'))
        
        if output.exists():
            with open(output, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # SRT形式チェック
            checks = [
                ('-->' in content, 'タイムスタンプ形式'),
                ('1\n' in content or '1\r\n' in content, 'シーケンス番号'),
                ('テストセグメント' in content, 'テキスト内容'),
            ]
            
            for check, name in checks:
                if check:
                    print(f'  ✅ {name}')
                    results['passed'].append(f'SRT: {name}')
                else:
                    print(f'  ❌ {name}')
                    results['failed'].append(f'SRT: {name}')
            
            output.unlink()  # テストファイル削除
        else:
            results['failed'].append('SRT: ファイル生成失敗')
    except Exception as e:
        print(f'  ❌ エラー: {e}')
        results['failed'].append(f'SRTエクスポートテスト: {e}')
    print()
    
    # 4. Semantic Store v2テスト
    print('4. Semantic Store v2テスト')
    print('-' * 50)
    try:
        from semantic_store import SemanticSubtitleStoreV2, BATCH_SIZE, API_TIMEOUT, USE_CACHE
        
        print(f'  バッチサイズ: {BATCH_SIZE}')
        print(f'  タイムアウト: {API_TIMEOUT}秒')
        print(f'  キャッシュ: {USE_CACHE}')
        
        if BATCH_SIZE > 50:
            results['improvements'].append('Semantic Store: バッチサイズが大きすぎる')
        if API_TIMEOUT < 30:
            results['improvements'].append('Semantic Store: タイムアウトが短すぎる')
        
        # インスタンス作成テスト
        store = SemanticSubtitleStoreV2()
        print(f'  インスタンス作成: OK')
        results['passed'].append('Semantic Store: インスタンス作成')
        
    except Exception as e:
        print(f'  ❌ エラー: {e}')
        results['failed'].append(f'Semantic Storeテスト: {e}')
    print()
    
    # 5. テロップ提案エンジンテスト
    print('5. テロップ提案エンジンテスト')
    print('-' * 50)
    try:
        from telop_proposal_engine import telop_engine, extract_telops
        
        test_segments = [
            {'id': 'seg_001', 'start': 0, 'end': 5, 'text': 'これは大切なポイントです。'},
            {'id': 'seg_002', 'start': 5, 'end': 10, 'text': '普通のテキストです。'},
        ]
        
        candidates = extract_telops(test_segments, max_candidates=5)
        print(f'  テロップ候補抽出: {len(candidates)}件')
        
        if len(candidates) == 0:
            results['warnings'].append('テロップ提案: 候補が0件')
        else:
            results['passed'].append(f'テロップ提案: {len(candidates)}件抽出')
    except Exception as e:
        print(f'  ❌ エラー: {e}')
        results['failed'].append(f'テロップ提案テスト: {e}')
    print()
    
    # 6. Asset Libraryテスト
    print('6. Asset Libraryテスト')
    print('-' * 50)
    try:
        from asset_library import asset_library
        
        report = asset_library.get_sufficiency_report()
        print(f'  総アセット数: {report["total_assets"]}')
        print(f'  推奨事項: {len(report["recommendations"])}件')
        
        if report['total_assets'] == 0:
            results['improvements'].append('Asset Library: アセットが0件（素材追加が必要）')
        
        for rec in report['recommendations']:
            results['improvements'].append(f'素材追加推奨: {rec.get("category", "")}')
        
        results['passed'].append('Asset Library: 動作確認OK')
    except Exception as e:
        print(f'  ❌ エラー: {e}')
        results['failed'].append(f'Asset Libraryテスト: {e}')
    print()
    
    # 7. Self-Review Engineテスト
    print('7. Self-Review Engineテスト')
    print('-' * 50)
    try:
        from self_review_engine import self_review_engine, QualityScore
        
        # 閾値チェック
        thresholds = self_review_engine.THRESHOLDS
        print(f'  品質閾値:')
        for key, value in thresholds.items():
            print(f'    {key}: {value}')
        
        if thresholds.get('overall', 0) < 0.6:
            results['warnings'].append('Self-Review: 全体閾値が低すぎる')
        
        results['passed'].append('Self-Review Engine: 設定確認OK')
    except Exception as e:
        print(f'  ❌ エラー: {e}')
        results['failed'].append(f'Self-Review Engineテスト: {e}')
    print()
    
    # 8. Learning Loopテスト
    print('8. Learning Loopテスト')
    print('-' * 50)
    try:
        from learning_loop import learning_loop
        
        pending = learning_loop.get_pending_proposals()
        patterns = learning_loop.get_preferences()
        
        print(f'  未来議会議題: {len(pending)}件')
        print(f'  学習パターン: {len(patterns)}件')
        
        results['passed'].append('Learning Loop: 動作確認OK')
    except Exception as e:
        print(f'  ❌ エラー: {e}')
        results['failed'].append(f'Learning Loopテスト: {e}')
    print()
    
    # 9. 統合パイプラインテスト
    print('9. 統合パイプラインテスト')
    print('-' * 50)
    try:
        from antigravity_pipeline import AntigravityPipeline
        
        pipeline = AntigravityPipeline()
        status = pipeline.get_pipeline_status()
        
        print(f'  固有名詞エントリ: {status["proper_noun_entries"]}')
        print(f'  保留中の確認: {status["pending_confirmations"]}')
        print(f'  アセット数: {status["available_assets"]}')
        
        results['passed'].append('統合パイプライン: ステータス取得OK')
    except Exception as e:
        print(f'  ❌ エラー: {e}')
        results['failed'].append(f'統合パイプラインテスト: {e}')
    print()
    
    # 10. 憲法整合性チェック
    print('10. 憲法整合性チェック')
    print('-' * 50)
    try:
        const_path = Path('backend/branding/constitution.json')
        if const_path.exists():
            with open(const_path, 'r', encoding='utf-8') as f:
                constitution = json.load(f)
            
            required_keys = ['brand_personality', 'content_policy']
            for key in required_keys:
                if key in constitution:
                    print(f'  ✅ {key}')
                    results['passed'].append(f'憲法: {key}')
                else:
                    print(f'  ❌ {key} missing')
                    results['failed'].append(f'憲法: {key} missing')
        else:
            results['failed'].append('憲法: constitution.json not found')
    except Exception as e:
        print(f'  ❌ エラー: {e}')
        results['failed'].append(f'憲法チェック: {e}')
    print()
    
    # サマリー
    print('=' * 60)
    print('品質チェック結果サマリー')
    print('=' * 60)
    print(f'  ✅ 合格: {len(results["passed"])}件')
    print(f'  ❌ 失敗: {len(results["failed"])}件')
    print(f'  ⚠️ 警告: {len(results["warnings"])}件')
    print(f'  📝 改善タスク: {len(results["improvements"])}件')
    print()
    
    if results['failed']:
        print('失敗項目:')
        for f in results['failed']:
            print(f'  ❌ {f}')
        print()
    
    if results['warnings']:
        print('警告項目:')
        for w in results['warnings']:
            print(f'  ⚠️ {w}')
        print()
    
    print('改善タスクストック:')
    for i in results['improvements']:
        print(f'  📝 {i}')
    
    # 結果を保存
    results['timestamp'] = datetime.now().isoformat()
    results['summary'] = {
        'passed': len(results['passed']),
        'failed': len(results['failed']),
        'warnings': len(results['warnings']),
        'improvements': len(results['improvements'])
    }
    
    with open('quality_check_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print()
    print(f'結果保存: quality_check_results.json')
    
    return results

if __name__ == '__main__':
    run_strict_quality_check()
