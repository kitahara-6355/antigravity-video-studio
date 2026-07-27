"""
Generation Engine テスト
"""
import sys
sys.path.insert(0, 'backend')

import logging
logging.basicConfig(level=logging.INFO)

from generation_engine import (
    GenerationEngine, 
    GenerationType, 
    GenerationRequest,
    PromptOptimizer,
    generate_thumbnail
)

def test_generation_engine():
    print('=' * 60)
    print('Generation Engine テスト')
    print('=' * 60)
    print()
    
    results = []
    
    # 1. プロンプト最適化テスト
    print('1. プロンプト最適化テスト')
    print('-' * 50)
    try:
        optimizer = PromptOptimizer()
        
        request = GenerationRequest(
            id="test_001",
            type=GenerationType.THUMBNAIL,
            prompt="書道の対談動画のサムネイル",
            context={"guest": "山田太郎", "topic": "デザイン書道"},
            style_hints=["和風", "上品", "プロフェッショナル"]
        )
        
        optimized = optimizer.optimize(request)
        print(f'  元のプロンプト: {request.prompt}')
        print(f'  最適化後: {optimized[:100]}...')
        print(f'  ✅ プロンプト最適化: OK')
        results.append(('プロンプト最適化', True, None))
    except Exception as e:
        print(f'  ❌ エラー: {e}')
        results.append(('プロンプト最適化', False, str(e)))
    print()
    
    # 2. Generation Engineインスタンス化テスト
    print('2. Generation Engineインスタンス化テスト')
    print('-' * 50)
    try:
        engine = GenerationEngine()
        print(f'  出力ディレクトリ: {engine.output_dir}')
        print(f'  Imagenモデル: {engine.imagen.model}')
        print(f'  Veoモデル: {engine.veo.model}')
        print(f'  ✅ インスタンス化: OK')
        results.append(('インスタンス化', True, None))
    except Exception as e:
        print(f'  ❌ エラー: {e}')
        results.append(('インスタンス化', False, str(e)))
    print()
    
    # 3. サムネイル生成テスト（実際のAPI呼び出し）
    print('3. サムネイル生成テスト')
    print('-' * 50)
    try:
        result = generate_thumbnail(
            title="書家・北原美麗の対談 〜山田太郎先生〜",
            context={
                "channel": "美麗書院",
                "guest": "山田太郎",
                "episode": 1
            }
        )
        
        if result['success']:
            print(f'  ✅ 生成成功')
            print(f'  出力パス: {result["output_path"]}')
            print(f'  品質スコア: {result["quality_score"]}')
            results.append(('サムネイル生成', True, result['output_path']))
        else:
            print(f'  ⚠️ 生成失敗: {result["error"]}')
            # Imagen APIがまだ利用できない場合はwarningとして扱う
            if 'not supported' in str(result['error']).lower() or 'not available' in str(result['error']).lower():
                print(f'  （注: Imagen APIがまだ利用可能になっていない可能性があります）')
                results.append(('サムネイル生成', 'warning', result['error']))
            else:
                results.append(('サムネイル生成', False, result['error']))
    except Exception as e:
        print(f'  ❌ エラー: {e}')
        results.append(('サムネイル生成', False, str(e)))
    print()
    
    # サマリー
    print('=' * 60)
    print('テスト結果サマリー')
    print('=' * 60)
    
    passed = sum(1 for r in results if r[1] == True)
    failed = sum(1 for r in results if r[1] == False)
    warnings = sum(1 for r in results if r[1] == 'warning')
    
    print(f'  ✅ 成功: {passed}件')
    print(f'  ❌ 失敗: {failed}件')
    print(f'  ⚠️ 警告: {warnings}件')
    print()
    
    for name, status, detail in results:
        if status == True:
            print(f'  ✅ {name}')
        elif status == False:
            print(f'  ❌ {name}: {detail}')
        else:
            print(f'  ⚠️ {name}: {detail}')
    
    return results

if __name__ == '__main__':
    test_generation_engine()
