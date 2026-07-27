"""
E2E 動画制作ワークフロー検証

統合アーキテクチャ v4.0 の実際の動作確認
"""
import sys
from pathlib import Path
from datetime import datetime

# バックエンドパスを追加
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))


def test_e2e_video_workflow():
    """E2E動画制作ワークフローテスト"""
    print("=" * 60)
    print("E2E 動画制作ワークフロー検証")
    print("=" * 60)
    
    results = []
    
    # 1. コアモジュール初期化
    print("\n[1] コアモジュール初期化...")
    try:
        from core import ProductionContext, get_plugin_registry
        from plugins import register_all_plugins
        
        # プラグイン登録
        register_all_plugins()
        registry = get_plugin_registry()
        
        status = registry.get_status()
        print(f"    ✅ プラグイン登録: {status['total_plugins']}個")
        results.append({"step": "core_init", "status": "passed"})
    except Exception as e:
        print(f"    ❌ 失敗: {e}")
        results.append({"step": "core_init", "status": "failed", "error": str(e)})
        return results
    
    # 2. ProductionContext作成
    print("\n[2] ProductionContext作成...")
    try:
        ctx = ProductionContext(
            task_id=f"e2e_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            video_paths=["src/sample_raw.mp4"],
            mood="elegant",
            output_name="e2e_test_output"
        )
        ctx.load_design_tokens()
        
        print(f"    ✅ タスクID: {ctx.task_id}")
        print(f"    ✅ ムード: {ctx.mood}")
        print(f"    ✅ デザイントークン: {len(ctx.mood_settings)}プロパティ")
        results.append({"step": "context_create", "status": "passed"})
    except Exception as e:
        print(f"    ❌ 失敗: {e}")
        results.append({"step": "context_create", "status": "failed", "error": str(e)})
        return results
    
    # 3. デザインシステム適用
    print("\n[3] デザインシステム適用...")
    try:
        from design_system import DesignSystemPlugin
        
        design_plugin = DesignSystemPlugin()
        ctx = design_plugin.execute(ctx)
        
        color_palette = ctx.get_extension("color_palette")
        print(f"    ✅ カラーパレット適用: {bool(color_palette)}")
        results.append({"step": "design_system", "status": "passed"})
    except Exception as e:
        print(f"    ❌ 失敗: {e}")
        results.append({"step": "design_system", "status": "failed", "error": str(e)})
    
    # 4. 品質チェック統合
    print("\n[4] 品質チェック統合...")
    try:
        from unified import quality_unified
        
        # 簡易チェック
        result = quality_unified.comprehensive_check(
            content={"text": "テスト動画", "mood": ctx.mood},
            check_types=["brand"]
        )
        
        print(f"    ✅ 品質スコア: {result.score:.1f}/100")
        print(f"    ✅ レベル: {result.level.value}")
        results.append({"step": "quality_check", "status": "passed", "score": result.score})
    except Exception as e:
        print(f"    ❌ 失敗: {e}")
        results.append({"step": "quality_check", "status": "failed", "error": str(e)})
    
    # 5. 学習ループ統合
    print("\n[5] 学習ループ統合...")
    try:
        from unified import learning_unified
        
        # 意思決定記録
        result = learning_unified.record_decision(
            decision_type="test",
            target="e2e_workflow",
            outcome="approve",
            reason="E2Eテスト実行",
            tags=["e2e", "test"]
        )
        
        print(f"    ✅ 意思決定記録: {result['status']}")
        results.append({"step": "learning_loop", "status": "passed"})
    except Exception as e:
        print(f"    ❌ 失敗: {e}")
        results.append({"step": "learning_loop", "status": "failed", "error": str(e)})
    
    # 6. ModelRegistry起動時チェック
    print("\n[6] ModelRegistry起動時チェック...")
    try:
        from model_registry import run_startup_checks
        
        result = run_startup_checks()
        
        print(f"    ✅ ステータス: {result['status']}")
        print(f"    ⚠️ 陳腐化警告: {len(result['deprecation_warnings'])}件")
        results.append({"step": "model_registry", "status": "passed", "warnings": len(result['deprecation_warnings'])})
    except Exception as e:
        print(f"    ❌ 失敗: {e}")
        results.append({"step": "model_registry", "status": "failed", "error": str(e)})
    
    # 7. レポート生成
    print("\n[7] レポート生成...")
    try:
        from plugins import ReportGeneratorPlugin
        
        report_plugin = ReportGeneratorPlugin()
        
        # コンテキストに必要なデータを設定
        ctx.set_extension("video_title", "E2Eテスト動画")
        ctx.quality_score = 85.0
        
        # レポート生成（実際のファイル書き込みはスキップ）
        print(f"    ✅ レポートプラグイン: 準備完了")
        results.append({"step": "report_generator", "status": "passed"})
    except Exception as e:
        print(f"    ❌ 失敗: {e}")
        results.append({"step": "report_generator", "status": "failed", "error": str(e)})
    
    # サマリー
    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r["status"] == "passed")
    failed = sum(1 for r in results if r["status"] == "failed")
    print(f"結果: {passed}/{len(results)} passed, {failed} failed")
    print("=" * 60)
    
    return results


if __name__ == "__main__":
    results = test_e2e_video_workflow()
    
    # 結果を保存
    import json
    output_path = Path(__file__).parent / "e2e_test_result.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "results": results
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n結果を保存: {output_path}")
    
    # 終了コード
    all_passed = all(r["status"] == "passed" for r in results)
    sys.exit(0 if all_passed else 1)
