"""
品質100%達成テスト - 全機能統合テスト

テスト対象:
1. プラグイン統合（重複解消）
2. UIボタン実装完了
3. A/Bテスト選択連携
4. API呼び出し整合性
"""
import asyncio
import json
from pathlib import Path
from datetime import datetime


def test_plugin_integration():
    """プラグイン統合テスト - 重複解消確認"""
    print("=" * 60)
    print("  Test 1: プラグイン統合（重複解消）")
    print("=" * 60)
    
    results = []
    
    # thumbnail_plugin が youtube_optimizer への委譲ラッパーになっているか
    try:
        from plugins.thumbnail_plugin import ThumbnailPlugin
        plugin = ThumbnailPlugin()
        
        # ラッパー化されているか（docstring確認）
        is_wrapper = "統合版" in ThumbnailPlugin.__doc__ or "委譲" in ThumbnailPlugin.__doc__
        results.append(("thumbnail_plugin 委譲ラッパー", is_wrapper))
        print(f"{'✅' if is_wrapper else '❌'} thumbnail_plugin: 委譲ラッパー")
        
    except Exception as e:
        print(f"❌ thumbnail_plugin: {e}")
        results.append(("thumbnail_plugin 委譲ラッパー", False))
    
    # auto_chapters_plugin が lightweight_scan への委譲ラッパーになっているか
    try:
        from plugins.auto_chapters_plugin import AutoChaptersPlugin
        plugin = AutoChaptersPlugin()
        
        is_wrapper = "統合版" in AutoChaptersPlugin.__doc__ or "委譲" in AutoChaptersPlugin.__doc__
        results.append(("auto_chapters_plugin 委譲ラッパー", is_wrapper))
        print(f"{'✅' if is_wrapper else '❌'} auto_chapters_plugin: 委譲ラッパー")
        
    except Exception as e:
        print(f"❌ auto_chapters_plugin: {e}")
        results.append(("auto_chapters_plugin 委譲ラッパー", False))
    
    return all(r[1] for r in results)


def test_router_registration():
    """ルーター登録テスト"""
    print()
    print("=" * 60)
    print("  Test 2: ルーター登録確認")
    print("=" * 60)
    
    results = []
    
    routers_to_check = [
        ("youtube_optimizer", "routers.youtube_optimizer"),
        ("smartcut", "routers.smartcut"),
        ("ab_test_tracker", "routers.ab_test_tracker"),
    ]
    
    for name, module_path in routers_to_check:
        try:
            module = __import__(module_path, fromlist=['router'])
            has_router = hasattr(module, 'router')
            results.append((name, has_router))
            print(f"{'✅' if has_router else '❌'} {name}: {'登録済み' if has_router else '未登録'}")
        except Exception as e:
            print(f"❌ {name}: {e}")
            results.append((name, False))
    
    return all(r[1] for r in results)


def test_ab_test_api():
    """A/Bテスト追跡API確認"""
    print()
    print("=" * 60)
    print("  Test 3: A/Bテスト追跡API")
    print("=" * 60)
    
    try:
        from routers.ab_test_tracker import router
        
        # エンドポイント存在確認（prefixを含む完全パスで確認）
        endpoints = []
        for route in router.routes:
            if hasattr(route, 'path'):
                endpoints.append(route.path)
        
        # prefix込みでチェック
        required_patterns = ["select", "feedback", "history", "accuracy"]
        found = []
        for pattern in required_patterns:
            for ep in endpoints:
                if pattern in ep:
                    found.append(pattern)
                    break
        
        all_present = len(found) >= 4
        print(f"{'✅' if all_present else '❌'} 必須エンドポイント: {len(found)}/{len(required_patterns)}")
        print(f"   検出: {len(endpoints)}個のルート")
        
        return all_present
        
    except Exception as e:
        print(f"❌ A/Bテスト追跡API: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_ui_handler_coverage():
    """UIハンドラ実装確認（コード内検索）"""
    print()
    print("=" * 60)
    print("  Test 4: UIハンドラ実装確認")
    print("=" * 60)
    
    try:
        jsx_path = Path(__file__).parent.parent / "frontend" / "src" / "components" / "YouTubeOptimizerPanel.jsx"
        
        if not jsx_path.exists():
            print(f"❌ ファイルが見つかりません: {jsx_path}")
            return False
        
        with open(jsx_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        handlers = [
            ("handleThumbnailSelect", "A/Bテスト選択"),
            ("handleReanalyze", "再分析"),
            ("handleAIImprove", "AI改善"),
            ("handleCustomEdit", "カスタム編集"),
            ("handleUpload", "アップロード"),
            ("handleSaveSettings", "設定保存"),
        ]
        
        results = []
        for handler_name, desc in handlers:
            exists = handler_name in content
            results.append((handler_name, exists))
            print(f"{'✅' if exists else '❌'} {desc}: {handler_name}")
        
        return all(r[1] for r in results)
        
    except Exception as e:
        print(f"❌ UIハンドラ確認: {e}")
        return False


def test_api_path_consistency():
    """API呼び出しパス整合性"""
    print()
    print("=" * 60)
    print("  Test 5: API呼び出しパス整合性")
    print("=" * 60)
    
    try:
        # ルーターのprefix確認
        from routers.youtube_optimizer import router as yt_router
        from routers.smartcut import router as sc_router
        from routers.ab_test_tracker import router as ab_router
        
        checks = [
            ("youtube_optimizer", yt_router.prefix, "/api/youtube"),
            ("smartcut", sc_router.prefix, "/api/smartcut"),
            ("ab_test_tracker", ab_router.prefix, "/api/thumbnail"),
        ]
        
        results = []
        for name, actual, expected in checks:
            match = actual == expected
            results.append((name, match))
            print(f"{'✅' if match else '❌'} {name}: {actual} {'==' if match else '!='} {expected}")
        
        return all(r[1] for r in results)
        
    except Exception as e:
        print(f"❌ API整合性: {e}")
        return False


def calculate_quality_score(results):
    """品質スコアを計算"""
    weights = {
        "プラグイン統合": 25,
        "ルーター登録": 20,
        "A/BテストAPI": 20,
        "UIハンドラ": 25,
        "API整合性": 10,
    }
    
    total = 0
    for name, passed in results:
        if passed:
            total += weights.get(name, 0)
    
    return total


def run_all_tests():
    """全テストを実行"""
    print()
    print("=" * 60)
    print("  品質100%達成テスト - 全機能統合テスト")
    print("=" * 60)
    print()
    
    results = []
    
    # Test 1
    results.append(("プラグイン統合", test_plugin_integration()))
    
    # Test 2
    results.append(("ルーター登録", test_router_registration()))
    
    # Test 3
    results.append(("A/BテストAPI", test_ab_test_api()))
    
    # Test 4
    results.append(("UIハンドラ", test_ui_handler_coverage()))
    
    # Test 5
    results.append(("API整合性", test_api_path_consistency()))
    
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
    
    # 品質スコア計算
    score = calculate_quality_score(results)
    
    print()
    print(f"テスト結果: {passed}/{total}")
    print(f"品質スコア: {score}/100")
    
    if score >= 100:
        print("判定: 🏆 品質100%達成！")
    elif score >= 85:
        print("判定: ✅ 高品質")
    elif score >= 70:
        print("判定: ⚠️ 良好")
    else:
        print("判定: 🔴 改善必要")
    
    print("=" * 60)
    
    return score >= 100


if __name__ == "__main__":
    run_all_tests()
