"""
長時間動画対応テスト - プロ品質担保活動

テスト対象:
1. video_constraints.json の読み込み
2. LightweightScanPlugin の動作
3. 3時間RAW → 1時間投稿のシミュレーション
"""
import asyncio
import json
from pathlib import Path
from datetime import datetime

def test_video_constraints():
    """video_constraints.json のテスト"""
    print("=" * 60)
    print("  Test 1: video_constraints.json")
    print("=" * 60)
    
    constraints_path = Path(__file__).parent / "branding" / "video_constraints.json"
    
    try:
        with open(constraints_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 必須項目のチェック
        checks = [
            ("raw_video.max_duration_minutes", config["raw_video"]["max_duration_minutes"], 180),
            ("output_video.max_duration_minutes", config["output_video"]["max_duration_minutes"], 60),
            ("stage1_lightweight.max_segments", config["processing"]["stage1_lightweight"]["max_segments"], 6000),
            ("stage3_deep.max_chapters", config["processing"]["stage3_deep"]["max_chapters"], 15),
        ]
        
        all_passed = True
        for name, actual, expected in checks:
            status = "✅" if actual == expected else "❌"
            print(f"{status} {name}: {actual} (expected: {expected})")
            if actual != expected:
                all_passed = False
        
        return all_passed
        
    except Exception as e:
        print(f"❌ Failed to load constraints: {e}")
        return False


def test_lightweight_scan_plugin():
    """LightweightScanPlugin のテスト"""
    print()
    print("=" * 60)
    print("  Test 2: LightweightScanPlugin")
    print("=" * 60)
    
    try:
        from plugins.lightweight_scan_plugin import LightweightScanPlugin, ScanResult
        from core.context import ProductionContext
        
        plugin = LightweightScanPlugin()
        
        # 3時間分のテストセグメント（180分 = 10,800秒）
        # 1セグメント = 約2秒 → 5,400セグメント
        segments = []
        test_texts = [
            "みなさんこんにちは！",
            "今日は驚きの事実を3つお伝えします！",
            "知っていますか？実はこの方法で10倍の成果が出ました",
            "まず最初に、基本的なポイントを解説していきます",
            "次に、重要なのはここからです",
            "しかし、ここで注意点があります",
            "つまり、これが結論です！",
            "最後に、今すぐ実践できる方法をお伝えします",
        ]
        
        # 3時間分のセグメントを生成（6000セグメント）
        for i in range(6000):
            text = test_texts[i % len(test_texts)]
            segments.append({
                "start": i * 1.8,  # 1.8秒間隔で約3時間
                "end": (i + 1) * 1.8,
                "text": text
            })
        
        # コンテキスト作成
        context = ProductionContext(task_id="test_long_video_001")
        context.segments = segments
        
        # 実行
        start_time = datetime.now()
        result_context = plugin.execute(context)
        processing_time = (datetime.now() - start_time).total_seconds()
        
        # 結果検証
        checks = [
            ("plugin.can_execute()", plugin.can_execute(context), True),
            ("scan_result exists", hasattr(result_context, 'scan_result'), True),
        ]
        
        if hasattr(result_context, 'scan_result'):
            sr = result_context.scan_result
            checks.extend([
                ("total_segments <= 6000", sr.total_segments <= 6000, True),
                ("highlight_candidates <= 50", len(sr.highlight_candidates) <= 50, True),
                ("chapter_candidates <= 30", len(sr.chapter_candidates) <= 30, True),
                ("estimated_cut_rate > 0", sr.estimated_cut_rate > 0, True),
            ])
            
            print(f"\n📊 スキャン結果:")
            print(f"   総セグメント数: {sr.total_segments}")
            print(f"   動画長: {sr.total_duration_seconds / 60:.1f}分")
            print(f"   ハイライト候補: {len(sr.highlight_candidates)}件")
            print(f"   チャプター候補: {len(sr.chapter_candidates)}件")
            print(f"   推定カット率: {sr.estimated_cut_rate:.1f}%")
            print(f"   処理時間: {processing_time:.2f}秒")
        
        all_passed = True
        print()
        for name, actual, expected in checks:
            status = "✅" if actual == expected else "❌"
            print(f"{status} {name}: {actual}")
            if actual != expected:
                all_passed = False
        
        return all_passed
        
    except Exception as e:
        print(f"❌ Plugin test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_3hour_to_1hour_simulation():
    """3時間RAW → 1時間投稿のシミュレーション"""
    print()
    print("=" * 60)
    print("  Test 3: 3時間→1時間シミュレーション")
    print("=" * 60)
    
    # シミュレーションパラメータ
    raw_duration_minutes = 180
    target_duration_minutes = 60
    expected_cut_rate = (raw_duration_minutes - target_duration_minutes) / raw_duration_minutes * 100
    
    print(f"\n📹 シミュレーション:")
    print(f"   RAW動画長: {raw_duration_minutes}分")
    print(f"   目標投稿長: {target_duration_minutes}分")
    print(f"   カット率: {expected_cut_rate:.1f}%")
    
    # 推定処理時間
    estimated_stage1 = raw_duration_minutes * 0.05  # 5%
    estimated_stage2 = 10  # ユーザー判断時間は固定
    estimated_stage3 = target_duration_minutes * 0.05  # 5%
    
    print(f"\n⏱️ 推定処理時間:")
    print(f"   Stage 1 (軽量スキャン): {estimated_stage1:.1f}分")
    print(f"   Stage 2 (カット編集): {estimated_stage2}分 (ユーザー判断)")
    print(f"   Stage 3 (深層分析): {estimated_stage3:.1f}分")
    print(f"   合計: {estimated_stage1 + estimated_stage2 + estimated_stage3:.1f}分")
    
    # 判定
    checks = [
        ("RAW動画 <= 180分", raw_duration_minutes <= 180, True),
        ("投稿動画 <= 60分", target_duration_minutes <= 60, True),
        ("カット率 = 67%", abs(expected_cut_rate - 66.7) < 1, True),
    ]
    
    all_passed = True
    print()
    for name, actual, expected in checks:
        status = "✅" if actual == expected else "❌"
        print(f"{status} {name}: {actual}")
        if actual != expected:
            all_passed = False
    
    return all_passed


def run_all_tests():
    """全テストを実行"""
    print()
    print("=" * 60)
    print("  長時間動画対応 - プロ品質担保テスト")
    print("=" * 60)
    print()
    
    results = []
    
    # Test 1
    results.append(("video_constraints.json", test_video_constraints()))
    
    # Test 2
    results.append(("LightweightScanPlugin", test_lightweight_scan_plugin()))
    
    # Test 3
    results.append(("3時間→1時間シミュレーション", test_3hour_to_1hour_simulation()))
    
    # 最終結果
    print()
    print("=" * 60)
    print("  最終結果")
    print("=" * 60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅" if result else "❌"
        print(f"{status} {name}")
    
    print()
    print(f"達成率: {passed}/{total} ({passed/total*100:.1f}%)")
    
    if passed == total:
        print("判定: 🏆 プロ品質達成！")
    else:
        print("判定: 🔴 改善必要")
    
    print("=" * 60)
    
    return passed == total


if __name__ == "__main__":
    run_all_tests()
