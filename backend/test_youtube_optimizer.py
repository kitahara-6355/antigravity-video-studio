"""
YouTube Optimizer Plugin テスト（プロ基準達成確認版）
youtube_expert_review.md + youtube_uiux_expert_review.md 提言反映度を検証
"""
import asyncio
from plugins.youtube_optimizer_plugin import youtube_optimizer, YouTubeOptimizedContext

async def test_youtube_optimizer():
    # テストデータ（より現実的なデータ）
    segments = [
        {'start': 0, 'end': 2, 'text': 'みなさんこんにちは！'},
        {'start': 2, 'end': 5, 'text': '今日は驚きの事実を3つお伝えします！'},
        {'start': 5, 'end': 10, 'text': '知っていますか？実はこの方法で10倍の成果が出ました'},
        {'start': 10, 'end': 30, 'text': 'まず最初に、基本的なポイントを解説していきます'},
        {'start': 30, 'end': 60, 'text': '次に、しかし重要なのはここからです'},
        {'start': 60, 'end': 90, 'text': 'つまり、これが結論です！まとめると3つのポイントがあります'},
        {'start': 90, 'end': 120, 'text': '最後に、今すぐ実践できる方法をお伝えします'},
    ]
    topics = ['生産性向上', 'ライフハック', '時短術', '効率化', '仕事術']
    context = {'topic': '生産性向上', 'task_id': 'test_pro_001'}
    
    # 全機能テスト
    result = await youtube_optimizer.optimize_context(segments, topics, context)
    
    print('=' * 60)
    print('  YouTube Optimizer - プロ基準達成確認テスト')
    print('=' * 60)
    print()
    
    # プロ基準チェックリスト
    checks = []
    
    # 1. フック分析（10種類対応）
    hook_pass = result.hook_score >= 0 and result.hook_analysis is not None
    checks.append(('フック分析', hook_pass, f'スコア: {result.hook_score}, タイプ: {result.hook_analysis.attention_grabber if result.hook_analysis else "N/A"}'))
    
    # 2. サムネイル3案
    thumb_pass = len(result.thumbnail_candidates) >= 3
    checks.append(('サムネイル3案', thumb_pass, f'{len(result.thumbnail_candidates)}案生成'))
    
    # 3. CTR信頼区間付き
    ctr_pass = hasattr(result.thumbnail_candidates[0], 'ctr_confidence') if result.thumbnail_candidates else False
    ctr_info = result.thumbnail_candidates[0].ctr_confidence if ctr_pass else 'N/A'
    checks.append(('CTR信頼区間', ctr_pass, ctr_info))
    
    # 4. CTR計算根拠
    factors_pass = hasattr(result.thumbnail_candidates[0], 'ctr_factors') if result.thumbnail_candidates else False
    factors_count = len(result.thumbnail_candidates[0].ctr_factors) if factors_pass else 0
    checks.append(('CTR計算根拠', factors_pass, f'{factors_count}件の計算根拠'))
    
    # 5. タグ15個以上
    tags_pass = result.seo_metadata and len(result.seo_metadata.tags) >= 15
    tag_count = len(result.seo_metadata.tags) if result.seo_metadata else 0
    checks.append(('タグ15個以上', tags_pass, f'{tag_count}個'))
    
    # 6. チャプター5個以上
    chapters_pass = result.seo_metadata and len(result.seo_metadata.chapters) >= 5
    chapter_count = len(result.seo_metadata.chapters) if result.seo_metadata else 0
    checks.append(('チャプター5個以上', chapters_pass, f'{chapter_count}個'))
    
    # 7. ハイライト検出
    highlight_pass = len(result.highlights) >= 3
    checks.append(('ハイライト3件以上', highlight_pass, f'{len(result.highlights)}件検出'))
    
    # 8. CTR現実的範囲（2-7%）
    ctr_realistic = all(2.0 <= t.predicted_ctr <= 7.0 for t in result.thumbnail_candidates) if result.thumbnail_candidates else False
    ctr_values = [t.predicted_ctr for t in result.thumbnail_candidates]
    checks.append(('CTR現実的範囲', ctr_realistic, f'{ctr_values}'))
    
    # 結果表示
    passed = sum(1 for _, p, _ in checks if p)
    total = len(checks)
    
    for name, passed_flag, detail in checks:
        status = '✅' if passed_flag else '❌'
        print(f'{status} {name}: {detail}')
    
    print()
    print('=' * 60)
    
    # 達成率計算
    achievement = (passed / total) * 100
    print(f'  プロ基準達成率: {achievement:.1f}% ({passed}/{total})')
    
    if achievement >= 100:
        print('  判定: 🏆 プロ品質達成！')
    elif achievement >= 80:
        print('  判定: 🟡 ほぼ達成（微調整必要）')
    else:
        print('  判定: 🔴 改善必要')
    
    print('=' * 60)
    
    return result, achievement

if __name__ == '__main__':
    result, achievement = asyncio.run(test_youtube_optimizer())
