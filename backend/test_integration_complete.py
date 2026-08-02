"""
統合完成テスト - 全機能動作確認

テスト対象:
1. main.pyルーター登録確認
2. SmartCut evolution_log保存
3. A/Bテスト追跡機能
"""
import asyncio
import json
from pathlib import Path
from datetime import datetime


def test_router_imports():
    """main.pyのルーターインポート確認"""
    print("=" * 60)
    print("  Test 1: ルーターインポート確認")
    print("=" * 60)
    
    try:
        from routers import youtube_optimizer as youtube_optimizer_router
        from routers import smartcut as smartcut_router
        from routers import ab_test_tracker as ab_test_tracker_router
        
        checks = [
            ("youtube_optimizer", hasattr(youtube_optimizer_router, 'router')),
            ("smartcut", hasattr(smartcut_router, 'router')),
            ("ab_test_tracker", hasattr(ab_test_tracker_router, 'router')),
        ]
        
        all_passed = True
        for name, result in checks:
            status = "✅" if result else "❌"
            print(f"{status} {name} router: {'OK' if result else 'MISSING'}")
            if not result:
                all_passed = False
        
        return all_passed
        
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return False


def test_smartcut_evolution_log():
    """SmartCutのevolution_log保存テスト"""
    print()
    print("=" * 60)
    print("  Test 2: SmartCut evolution_log保存")
    print("=" * 60)
    
    try:
        from plugins.smart_cut_plugin import SmartCutPlugin, SmartCutContext
        
        # テスト用コンテキスト作成
        smart_cut = SmartCutPlugin()
        smart_cut._context = SmartCutContext(
            all_highlights=[{"timestamp": 0, "score": 10, "type": "test"}],
            all_chapters=[{"timestamp": 0, "title": "test"}],
        )
        
        # 固定シーンを追加（evolution_logに保存される）
        success = smart_cut.lock_segment(
            segment_id="test_lock_001",
            title="テスト固定シーン",
            start=100.0,
            end=130.0,
            reason="統合テストのための固定"
        )
        
        print(f"✅ lock_segment: {'成功' if success else '失敗'}")
        
        # evolution_logを確認。実装と同じ経路で解決する
        # （直書きだと Git 追跡下の本番ファイルを読みに行ってしまう）。
        from path_resolver import writable_path
        evolution_path = writable_path("backend/branding/evolution_log.json")
        if evolution_path.exists():
            with open(evolution_path, 'r', encoding='utf-8') as f:
                log = json.load(f)
            
            has_locked = "locked_segments" in log and len(log["locked_segments"]) > 0
            print(f"✅ evolution_log保存: {'OK' if has_locked else 'EMPTY'}")
            
            if has_locked:
                latest = log["locked_segments"][-1]
                print(f"   最新エントリ: {latest.get('title', 'N/A')}")
            
            return has_locked
        else:
            print("❌ evolution_log.json が見つかりません")
            return False
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_ab_test_tracker():
    """A/Bテスト追跡機能テスト"""
    print()
    print("=" * 60)
    print("  Test 3: A/Bテスト追跡機能")
    print("=" * 60)
    
    try:
        from routers.ab_test_tracker import (
            _load_json,
            _save_json,
            _analyze_prediction_accuracy,
            SELECTION_HISTORY_PATH
        )
        
        # テストデータ
        test_record = {
            "video_id": "test_video_001",
            "selected_at": datetime.now().isoformat(),
            "selected_index": 0,
            "selected_concept": "テストコンセプト",
            "predicted_ctr": 4.5,
            "all_predicted_ctrs": [4.5, 4.0, 3.8],
            "reason": "テスト選択",
        }
        
        # 保存テスト
        history = _load_json(SELECTION_HISTORY_PATH)
        history.append(test_record)
        _save_json(SELECTION_HISTORY_PATH, history)
        
        # 読み込み確認
        loaded = _load_json(SELECTION_HISTORY_PATH)
        has_record = any(r.get("video_id") == "test_video_001" for r in loaded)
        
        print(f"✅ 選択履歴保存: {'OK' if has_record else 'FAILED'}")
        print(f"   保存件数: {len(loaded)}")
        
        # 精度分析テスト
        accuracy = _analyze_prediction_accuracy(loaded)
        print(f"✅ 精度分析: サンプル数 {accuracy.get('sample_size', 0)}")
        
        return has_record
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all_tests():
    """全テストを実行"""
    print()
    print("=" * 60)
    print("  統合完成テスト - 全機能動作確認")
    print("=" * 60)
    print()
    
    results = []
    
    # Test 1
    results.append(("ルーターインポート", test_router_imports()))
    
    # Test 2
    results.append(("evolution_log保存", test_smartcut_evolution_log()))
    
    # Test 3
    results.append(("A/Bテスト追跡", test_ab_test_tracker()))
    
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
        print("判定: 🏆 統合完成！")
    else:
        print("判定: 🔴 改善必要")
    
    print("=" * 60)
    
    return passed == total


if __name__ == "__main__":
    run_all_tests()
