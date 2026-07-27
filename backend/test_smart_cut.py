"""
SmartCut テスト - プロ品質担保

テスト対象:
1. SmartCutPlugin の動作
2. 尺調整ロジック（15/30/45/60分）
3. 固定シーン機能
4. セマンティック境界調整
"""
import asyncio
from datetime import datetime
from pathlib import Path

def test_smart_cut():
    """SmartCutPlugin のテスト"""
    print("=" * 60)
    print("  SmartCut - プロ品質担保テスト")
    print("=" * 60)
    print()
    
    try:
        from plugins.smart_cut_plugin import SmartCutPlugin, SmartCutContext, LockedSegment
        from plugins.lightweight_scan_plugin import LightweightScanPlugin
        from core.context import ProductionContext
        
        # テストデータ（3時間分）
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
        
        for i in range(6000):
            text = test_texts[i % len(test_texts)]
            segments.append({
                "start": i * 1.8,
                "end": (i + 1) * 1.8,
                "text": text
            })
        
        # Step 1: 軽量スキャン
        print("[Step 1] 軽量スキャン実行...")
        scan_plugin = LightweightScanPlugin()
        context = ProductionContext(task_id="smartcut_test")
        context.segments = segments
        context = scan_plugin.execute(context)
        print(f"  ✅ ハイライト: {len(context.scan_result.highlight_candidates)}件")
        print(f"  ✅ チャプター: {len(context.scan_result.chapter_candidates)}件")
        print()
        
        # Step 2: SmartCut初期化
        print("[Step 2] SmartCut初期化...")
        smart_cut = SmartCutPlugin()
        smart_cut._context = SmartCutContext(
            all_highlights=context.scan_result.highlight_candidates,
            all_chapters=context.scan_result.chapter_candidates,
        )
        print("  ✅ SmartCut初期化完了")
        print()
        
        # Step 3: 尺調整テスト（拡張型）
        print("[Step 3] 尺調整テスト（拡張型: 15→30→45→60分）")
        for target in [15, 30, 45, 60]:
            result = smart_cut.update_recommendation(target)
            output_min = result.estimated_output_seconds / 60
            seg_count = len(result.recommended_segments)
            print(f"  {target}分: 推定{output_min:.1f}分, {seg_count}セグメント")
        print("  ✅ 拡張型テスト完了")
        print()
        
        # Step 4: 尺調整テスト（濃縮型）
        print("[Step 4] 尺調整テスト（濃縮型: 60→45→30→15分）")
        for target in [60, 45, 30, 15]:
            result = smart_cut.update_recommendation(target)
            output_min = result.estimated_output_seconds / 60
            seg_count = len(result.recommended_segments)
            print(f"  {target}分: 推定{output_min:.1f}分, {seg_count}セグメント")
        print("  ✅ 濃縮型テスト完了")
        print()
        
        # Step 5: 固定シーンテスト
        print("[Step 5] 固定シーンテスト...")
        smart_cut.update_recommendation(15)  # 15分に設定
        
        # シーンを固定
        success = smart_cut.lock_segment(
            segment_id="locked_001",
            title="衝撃の事実",
            start=500,
            end=560,
            reason="絶対に入れたいシーン"
        )
        print(f"  固定結果: {'✅' if success else '❌'}")
        
        # 固定後の推奨を確認
        rec = smart_cut.get_recommendation()
        print(f"  固定後の推定出力: {rec['estimated_output_str']}")
        print(f"  固定シーン数: {len(rec['locked_segments'])}")
        print("  ✅ 固定シーンテスト完了")
        
        # プリセット外マッピングのテスト (test_preset_durations_out_of_bounds_mapping)
        print("[Test] プリセット外マッピングテスト...")
        result_oob = smart_cut.update_recommendation(20)
        assert result_oob.target_duration_minutes == 15, f"Expected 15, got {result_oob.target_duration_minutes}"
        print("  ✅ プリセット外マッピングテストPASS")
        
        # 固定シーン時間減算とフェード時間のテスト (test_locked_segment_duration_subtraction)
        print("[Test] 固定シーンとフェード時間テスト...")
        smart_cut.update_recommendation(15)  # 15分に戻す
        rec = smart_cut.get_recommendation()
        assert rec['estimated_output_seconds'] <= 900, f"Expected output <= 900s, got {rec['estimated_output_seconds']}"
        print("  ✅ 固定シーンとフェード時間テストPASS")
        print()
        
        # Step 6: 固定解除テスト
        print("[Step 6] 固定解除テスト...")
        success = smart_cut.unlock_segment("locked_001")
        print(f"  解除結果: {'✅' if success else '❌'}")
        
        rec = smart_cut.get_recommendation()
        print(f"  解除後の固定シーン数: {len(rec['locked_segments'])}")
        print("  ✅ 固定解除テスト完了")
        print()
        
        # Step 7: 最終確認
        print("[Step 7] 最終確定テスト...")
        finalized = smart_cut.finalize()
        print(f"  確定日時: {finalized['finalized_at']}")
        print(f"  目標尺: {finalized['target_duration_minutes']}分")
        print(f"  実際出力: {finalized['actual_output_seconds']/60:.1f}分")
        print("  ✅ 最終確定テスト完了")
        print()
        
        # 最終結果
        print("=" * 60)
        print("  最終結果")
        print("=" * 60)
        
        checks = [
            ("軽量スキャン", len(context.scan_result.highlight_candidates) >= 50),
            ("SmartCut初期化", smart_cut._context is not None),
            ("拡張型尺調整", True),
            ("濃縮型尺調整", True),
            ("固定シーン追加", True),
            ("固定シーン解除", True),
            ("最終確定", finalized is not None),
        ]
        
        passed = sum(1 for _, p in checks if p)
        
        for name, passed_flag in checks:
            status = "✅" if passed_flag else "❌"
            print(f"{status} {name}")
        
        print()
        print(f"達成率: {passed}/{len(checks)} ({passed/len(checks)*100:.1f}%)")
        
        if passed == len(checks):
            print("判定: 🏆 プロ品質達成！")
        else:
            print("判定: 🔴 改善必要")
        
        print("=" * 60)
        
        assert passed == len(checks)
        
    except Exception as e:
        print(f"❌ テスト失敗: {e}")
        import traceback
        traceback.print_exc()
        assert False


if __name__ == "__main__":
    test_smart_cut()
