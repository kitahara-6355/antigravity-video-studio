"""
Antigravity 3.0 厳格な品質監査
全モジュールの詳細テストと改善提案
"""
import sys
sys.path.insert(0, 'backend')

import json
from pathlib import Path
from datetime import datetime

def run_strict_audit():
    print('=' * 70)
    print('Antigravity 3.0 厳格な品質監査')
    print('=' * 70)
    print()
    
    results = {
        'passed': [],
        'failed': [],
        'warnings': [],
        'improvements': [],
        'critical': []
    }
    
    # 1. コアモジュール完全性テスト
    print('1. コアモジュール完全性テスト')
    print('-' * 60)
    core_modules = {
        'proper_noun_dict': ['ProperNounDictionary', 'apply_dictionary', 'proper_noun_dict'],
        'subtitle_normalizer': ['SubtitleNormalizer', 'SRTExporter'],
        'semantic_store': ['SemanticSubtitleStoreV2', 'create_semantic_store'],
        'telop_proposal_engine': ['TelopProposalEngine', 'extract_telops', 'propose_scenes'],
        'asset_library': ['CreativeAssetLibrary', 'asset_library', 'scan_assets'],
        'generation_engine': ['GenerationEngine', 'generate_thumbnail', 'PromptOptimizer'],
        'self_review_engine': ['SelfReviewEngine', 'review_and_improve'],
        'learning_loop': ['LearningLoop', 'record_approval', 'record_rejection'],
        'antigravity_pipeline': ['AntigravityPipeline'],
        'model_registry': ['get_model', 'MODEL_CONFIG']
    }
    
    for mod_name, required_items in core_modules.items():
        try:
            mod = __import__(mod_name)
            missing = [item for item in required_items if not hasattr(mod, item)]
            if missing:
                print(f'  ⚠️ {mod_name}: 不足 {missing}')
                results['warnings'].append(f'{mod_name}: {missing} が不足')
            else:
                print(f'  ✅ {mod_name}: 完全')
                results['passed'].append(f'モジュール完全性: {mod_name}')
        except Exception as e:
            print(f'  ❌ {mod_name}: {e}')
            results['failed'].append(f'{mod_name}: {e}')
    print()
    
    # 2. 固有名詞辞書の品質テスト
    print('2. 固有名詞辞書の品質テスト')
    print('-' * 60)
    try:
        from proper_noun_dict import proper_noun_dict
        entries = proper_noun_dict.get_all_entries()
        print(f'  エントリ数: {len(entries)}')
        
        # 品質基準
        if len(entries) < 10:
            results['warnings'].append('固有名詞辞書: 10件未満（推奨: 20件以上）')
            print(f'  ⚠️ エントリ数不足（推奨: 20件以上）')
        elif len(entries) < 20:
            print(f'  ⚠️ エントリ数やや少ない（推奨: 20件以上）')
            results['improvements'].append('固有名詞辞書: さらにエントリを追加推奨')
        else:
            print(f'  ✅ エントリ数十分')
            results['passed'].append(f'固有名詞辞書: {len(entries)}エントリ')
        
        # 確認済みエントリの割合
        confirmed = sum(1 for e in entries if e.confirmed)
        confirm_rate = confirmed / len(entries) * 100 if entries else 0
        print(f'  確認済み: {confirmed}/{len(entries)} ({confirm_rate:.0f}%)')
        if confirm_rate < 80:
            results['warnings'].append(f'固有名詞辞書: 未確認エントリが多い（{100-confirm_rate:.0f}%）')
        
    except Exception as e:
        print(f'  ❌ エラー: {e}')
        results['failed'].append(f'固有名詞辞書テスト: {e}')
    print()
    
    # 3. Asset Library品質テスト
    print('3. Asset Library品質テスト')
    print('-' * 60)
    try:
        from asset_library import asset_library
        asset_library.scan()
        report = asset_library.get_sufficiency_report()
        
        print(f'  総アセット数: {report["total_assets"]}')
        
        # カテゴリ別チェック
        categories = {
            'channel_owner': 3,  # 最低3件
            'guests': 1,         # 最低1件
            'templates': 2,      # 最低2件
            'brand': 1           # 最低1件
        }
        
        for cat, min_count in categories.items():
            cat_assets = [a for a in asset_library.assets if cat in str(a.path)]
            count = len(cat_assets)
            if count < min_count:
                print(f'  ⚠️ {cat}: {count}件（最低{min_count}件必要）')
                results['improvements'].append(f'素材追加推奨: {cat}（現在{count}件、最低{min_count}件）')
            else:
                print(f'  ✅ {cat}: {count}件')
                results['passed'].append(f'アセット: {cat}')
        
    except Exception as e:
        print(f'  ❌ エラー: {e}')
        results['failed'].append(f'Asset Libraryテスト: {e}')
    print()
    
    # 4. Generation Engine品質テスト
    print('4. Generation Engine品質テスト')
    print('-' * 60)
    try:
        from generation_engine import GenerationEngine, PromptOptimizer
        
        engine = GenerationEngine()
        print(f'  Imagenモデル: {engine.imagen.model}')
        print(f'  Veoモデル: {engine.veo.model}')
        
        # プロンプト最適化テスト
        optimizer = PromptOptimizer()
        if optimizer.constitution:
            print(f'  憲法読み込み: ✅')
            results['passed'].append('Generation Engine: 憲法連携')
        else:
            print(f'  ⚠️ 憲法読み込み失敗')
            results['warnings'].append('Generation Engine: 憲法連携なし')
        
        # Self-Review統合チェック
        if engine.reviewer:
            print(f'  Self-Review統合: ✅')
            results['passed'].append('Generation Engine: Self-Review統合')
        else:
            print(f'  ⚠️ Self-Review未統合')
            results['warnings'].append('Generation Engine: Self-Review未統合')
        
    except Exception as e:
        print(f'  ❌ エラー: {e}')
        results['failed'].append(f'Generation Engineテスト: {e}')
    print()
    
    # 5. 憲法整合性テスト
    print('5. 憲法整合性テスト')
    print('-' * 60)
    try:
        const_path = Path('backend/branding/constitution.json')
        md_path = Path('backend/branding/PROJECT_CONSTITUTION.md')
        
        if const_path.exists():
            with open(const_path, 'r', encoding='utf-8') as f:
                constitution = json.load(f)
            
            required = ['brand_personality', 'content_policy', 'visual_identity']
            for key in required:
                if key in constitution:
                    print(f'  ✅ {key}')
                    results['passed'].append(f'憲法: {key}')
                else:
                    print(f'  ⚠️ {key} 不足')
                    results['warnings'].append(f'憲法: {key}が不足')
        
        if md_path.exists():
            print(f'  ✅ PROJECT_CONSTITUTION.md 存在')
            results['passed'].append('憲法: PROJECT_CONSTITUTION.md')
        else:
            print(f'  ❌ PROJECT_CONSTITUTION.md 不在')
            results['failed'].append('憲法: PROJECT_CONSTITUTION.md 不在')
            
    except Exception as e:
        print(f'  ❌ エラー: {e}')
        results['failed'].append(f'憲法テスト: {e}')
    print()
    
    # 6. 統合パイプライン品質テスト
    print('6. 統合パイプライン品質テスト')
    print('-' * 60)
    try:
        from antigravity_pipeline import AntigravityPipeline
        
        pipeline = AntigravityPipeline()
        status = pipeline.get_pipeline_status()
        
        print(f'  固有名詞エントリ: {status["proper_noun_entries"]}')
        print(f'  保留中確認: {status["pending_confirmations"]}')
        print(f'  アセット数: {status["available_assets"]}')
        print(f'  未来議会議題: {status["pending_proposals"]}')
        
        # 統合テスト
        if status['proper_noun_entries'] > 0:
            results['passed'].append('統合: 固有名詞辞書連携')
        else:
            results['warnings'].append('統合: 固有名詞辞書が空')
        
        if status['available_assets'] > 0:
            results['passed'].append('統合: アセット連携')
        else:
            results['warnings'].append('統合: アセットなし')
            
    except Exception as e:
        print(f'  ❌ エラー: {e}')
        results['failed'].append(f'統合パイプラインテスト: {e}')
    print()
    
    # 7. エラーハンドリングテスト
    print('7. エラーハンドリングテスト')
    print('-' * 60)
    try:
        from proper_noun_dict import apply_dictionary
        from semantic_store import SemanticSubtitleStoreV2
        
        # 空入力テスト
        result, corrections = apply_dictionary('')
        if result == '':
            print(f'  ✅ 空文字列ハンドリング')
            results['passed'].append('エラーハンドリング: 空文字列')
        
        # 大量入力テスト（軽量）
        long_text = 'テスト' * 100
        result, _ = apply_dictionary(long_text)
        if result:
            print(f'  ✅ 長文ハンドリング')
            results['passed'].append('エラーハンドリング: 長文')
            
    except Exception as e:
        print(f'  ⚠️ エラーハンドリング改善必要: {e}')
        results['warnings'].append(f'エラーハンドリング: {e}')
    print()
    
    # サマリー
    print('=' * 70)
    print('品質監査結果サマリー')
    print('=' * 70)
    
    score = calculate_score(results)
    
    print(f'  ✅ 合格: {len(results["passed"])}件')
    print(f'  ❌ 失敗: {len(results["failed"])}件')
    print(f'  ⚠️ 警告: {len(results["warnings"])}件')
    print(f'  📝 改善提案: {len(results["improvements"])}件')
    print()
    print(f'  📊 総合スコア: {score}/10.0')
    print()
    
    # 改善提案まとめ
    print('改善提案:')
    for i in results['improvements']:
        print(f'  📝 {i}')
    for w in results['warnings']:
        print(f'  ⚠️ {w}')
    
    # 結果保存
    results['timestamp'] = datetime.now().isoformat()
    results['score'] = score
    results['summary'] = {
        'passed': len(results['passed']),
        'failed': len(results['failed']),
        'warnings': len(results['warnings']),
        'improvements': len(results['improvements'])
    }
    
    with open('quality_audit_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print()
    print(f'結果保存: quality_audit_results.json')
    
    return results

def calculate_score(results):
    """スコア計算"""
    base = 10.0
    
    # 失敗は大きな減点
    base -= len(results['failed']) * 1.0
    
    # 警告は中程度の減点
    base -= len(results['warnings']) * 0.3
    
    # 改善提案は軽微な減点
    base -= len(results['improvements']) * 0.1
    
    # 合格項目でボーナス（最大1.0）
    bonus = min(len(results['passed']) * 0.05, 1.0)
    base += bonus
    
    return max(0, min(10.0, round(base, 1)))

if __name__ == '__main__':
    run_strict_audit()
