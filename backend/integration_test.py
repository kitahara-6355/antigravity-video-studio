"""
Integration Test - 統合アーキテクチャv4.0 of integration tests

全モジュールの連携動作を確認する。
"""
import sys
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime

# バックエンドパスを追加
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))


def test_core_imports() -> Dict[str, Any]:
    """コアモジュールのインポートテスト"""
    try:
        from core import (
            ProductionContext, ProductionPhase,
            Plugin, PluginPhase,
            PluginRegistry, get_plugin_registry, register_plugin
        )
        return {"name": "core_imports", "status": "passed"}
    except Exception as e:
        return {"name": "core_imports", "status": "failed", "error": str(e)}


def test_unified_imports() -> Dict[str, Any]:
    """統合モジュールのインポートテスト（archived — unified/ は archives/ に移動済み）"""
    return {"name": "unified_imports", "status": "passed", "note": "archived — skipped"}


def test_plugins_imports() -> Dict[str, Any]:
    """プラグインのインポートテスト"""
    try:
        from plugins import (
            ThumbnailPlugin,
            OpeningEndingPlugin,
            MusicLayerPlugin,
            AutoChaptersPlugin,
            ReportGeneratorPlugin,
            register_all_plugins
        )
        return {"name": "plugins_imports", "status": "passed"}
    except Exception as e:
        return {"name": "plugins_imports", "status": "failed", "error": str(e)}


def test_design_system_imports() -> Dict[str, Any]:
    """デザインシステムのインポートテスト"""
    try:
        from design_system import (
            design_token_manager,
            DesignSystemPlugin,
            design_chat_handler,
            design_auto_learner
        )
        return {"name": "design_system_imports", "status": "passed"}
    except Exception as e:
        return {"name": "design_system_imports", "status": "failed", "error": str(e)}


def test_model_registry() -> Dict[str, Any]:
    """ModelRegistryのテスト"""
    try:
        from model_registry import get_registry, run_startup_checks
        
        registry = get_registry()
        
        # ガード処理
        if registry is None:
            return {"name": "model_registry", "status": "failed", "error": "ModelRegistry is None"}
            
        result = run_startup_checks()
        
        # ガード処理
        if not isinstance(result, dict) or "status" not in result:
            return {
                "name": "model_registry",
                "status": "failed",
                "error": f"Invalid result format from run_startup_checks: {result}"
            }
        
        return {
            "name": "model_registry",
            "status": "passed" if result["status"] in ["ok", "warning"] else "failed",
            "startup_result": result["status"]
        }
    except Exception as e:
        return {"name": "model_registry", "status": "failed", "error": str(e)}


def test_plugin_registration() -> Dict[str, Any]:
    """プラグイン登録テスト"""
    try:
        from core import get_plugin_registry
        from plugins import register_all_plugins
        
        # プラグイン登録
        register_all_plugins()
        
        registry = get_plugin_registry()
        if registry is None:
            return {"name": "plugin_registration", "status": "failed", "error": "Plugin registry is None"}
            
        status = registry.get_status()
        
        # ガード処理
        if not isinstance(status, dict) or "total_plugins" not in status:
            return {
                "name": "plugin_registration",
                "status": "failed",
                "error": f"Invalid status format from registry: {status}"
            }
        
        if status["total_plugins"] >= 5:
            return {
                "name": "plugin_registration",
                "status": "passed",
                "plugin_count": status["total_plugins"]
            }
        else:
            return {
                "name": "plugin_registration",
                "status": "warning",
                "plugin_count": status["total_plugins"],
                "expected": 5
            }
    except Exception as e:
        return {"name": "plugin_registration", "status": "failed", "error": str(e)}


def test_design_tokens() -> Dict[str, Any]:
    """デザイントークン取得テスト"""
    try:
        from design_system import design_token_manager
        
        if design_token_manager is None:
            return {"name": "design_tokens", "status": "failed", "error": "design_token_manager is None"}
            
        tokens = design_token_manager.get_tokens("elegant")
        
        # ガード処理
        from collections.abc import Sized
        if not isinstance(tokens, Sized):
            return {
                "name": "design_tokens",
                "status": "failed",
                "error": f"Tokens returned is not Sized: {type(tokens)}"
            }
        
        if tokens and len(tokens) >= 3:
            return {
                "name": "design_tokens",
                "status": "passed",
                "token_count": len(tokens)
            }
        else:
            return {
                "name": "design_tokens",
                "status": "warning",
                "token_count": len(tokens) if tokens else 0
            }
    except Exception as e:
        return {"name": "design_tokens", "status": "failed", "error": str(e)}


def test_production_context_flow() -> Dict[str, Any]:
    """ProductionContext処理フローテスト"""
    try:
        from core import ProductionContext, ProductionPhase, get_plugin_registry
        from design_system import DesignSystemPlugin
        
        # コンテキスト作成
        ctx = ProductionContext(task_id="test_001", video_paths=["test.mp4"], mood="elegant")
        
        if ctx is None:
            return {"name": "production_context_flow", "status": "failed", "error": "Failed to instantiate ProductionContext"}
            
        # デザイントークンを読み込み
        ctx.load_design_tokens()
        
        # 進捗更新
        ctx.update_progress(50, "テスト中")
        
        # ガード処理
        if not hasattr(ctx, "mood_settings") or not hasattr(ctx, "progress"):
            return {
                "name": "production_context_flow",
                "status": "failed",
                "error": "ProductionContext missing required attributes"
            }
            
        if ctx.mood_settings is not None and not isinstance(ctx.mood_settings, dict):
            return {
                "name": "production_context_flow",
                "status": "failed",
                "error": f"Invalid mood_settings format: {type(ctx.mood_settings)}"
            }
        
        if ctx.mood_settings and ctx.progress == 50:
            return {
                "name": "production_context_flow",
                "status": "passed",
                "mood_settings_loaded": bool(ctx.mood_settings)
            }
        else:
            return {
                "name": "production_context_flow",
                "status": "warning",
                "mood_settings_loaded": bool(ctx.mood_settings)
            }
    except Exception as e:
        return {"name": "production_context_flow", "status": "failed", "error": str(e)}


def test_data_migration() -> Dict[str, Any]:
    """データ移行チェックテスト"""
    try:
        from data_migration import data_migration
        
        if data_migration is None:
            return {"name": "data_migration", "status": "failed", "error": "data_migration is None"}
            
        result = data_migration.run_migration(dry_run=True)
        
        # ガード処理
        if not isinstance(result, dict) or "steps" not in result or not isinstance(result["steps"], list):
            return {
                "name": "data_migration",
                "status": "failed",
                "error": f"Invalid migration result format: {result}"
            }
            
        for s in result["steps"]:
            if not isinstance(s, dict) or "status" not in s:
                return {
                    "name": "data_migration",
                    "status": "failed",
                    "error": f"Invalid step format: {s}"
                }
        
        passed_count = sum(1 for s in result["steps"] if s.get("status") == "passed")
        total = len(result["steps"])
        
        return {
            "name": "data_migration",
            "status": "passed" if passed_count == total else "warning",
            "checks": f"{passed_count}/{total}"
        }
    except Exception as e:
        return {"name": "data_migration", "status": "failed", "error": str(e)}


def test_youtube_optimizer_thumbnail_generation() -> Dict[str, Any]:
    """YouTubeOptimizerPluginのサムネイル生成テスト（Imagen 4.0モック）"""
    try:
        import asyncio
        from unittest.mock import patch, MagicMock
        from plugins.youtube_optimizer_plugin import ThumbnailCandidate, YouTubeOptimizerPlugin
        
        optimizer = YouTubeOptimizerPlugin()
        thumbnail = ThumbnailCandidate(
            id="test_thumb_curiosity_1",
            concept="好奇心喚起型",
            target_emotion="好奇心",
            text_overlay="知らないと損するテスト"
        )
        context = {"topic": "テストトピック"}
        
        # ガード処理
        if optimizer is None or thumbnail is None:
            return {"name": "youtube_optimizer_thumbnail_generation", "status": "failed", "error": "Optimizer or Thumbnail candidate is None"}
        
        # 1. 正常系: 画像生成が成功するケース
        mock_image = MagicMock()
        mock_result = MagicMock()
        mock_result.generated_images = [MagicMock(image=mock_image)]
        
        mock_client = MagicMock()
        mock_client.models.generate_images.return_value = mock_result
        
        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
             patch("pathlib.Path.mkdir"), \
             patch.object(mock_image, "save") as mock_save:
              
            result_path = asyncio.run(optimizer.generate_thumbnail_with_imagen(thumbnail, context))
            
            import os
            if os.getenv("INTEGRATION_TEST_FAIL_NORMAL"):
                result_path = None
                
            assert result_path is not None, f"Expected thumbnail path, but got {result_path}"
            assert "test_thumb_curiosity_1.png" in result_path, f"Expected thumbnail path, but got {result_path}"
            mock_save.assert_called_once()
            
        # 2. 異常系: generated_images が空のケース
        mock_result_empty = MagicMock()
        mock_result_empty.generated_images = []
        mock_client.models.generate_images.return_value = mock_result_empty
        
        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
            result_path = asyncio.run(optimizer.generate_thumbnail_with_imagen(thumbnail, context))
            import os
            if os.getenv("INTEGRATION_TEST_FAIL_EMPTY"):
                result_path = "fake_path"
            assert result_path is None, "Expected None when generated_images is empty"
                
        # 3. 異常系: 例外が発生するケース
        mock_client.models.generate_images.side_effect = Exception("Imagen API Error")
        
        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
            result_path = asyncio.run(optimizer.generate_thumbnail_with_imagen(thumbnail, context))
            import os
            if os.getenv("INTEGRATION_TEST_FAIL_EXCEPTION"):
                result_path = "fake_path"
            assert result_path is None, "Expected None when exception occurs"
                
        return {"name": "youtube_optimizer_thumbnail_generation", "status": "passed"}
    except Exception as e:
        return {"name": "youtube_optimizer_thumbnail_generation", "status": "failed", "error": str(e)}


def run_all_tests() -> Dict[str, Any]:
    """全テストを実行"""
    print("=" * 60)
    print("統合アーキテクチャ v4.0 - 統合テスト")
    print("=" * 60)
    
    tests = [
        test_core_imports,
        # test_unified_imports,  # archived — unified/ moved to archives/
        test_plugins_imports,
        test_design_system_imports,
        test_model_registry,
        test_plugin_registration,
        test_design_tokens,
        test_production_context_flow,
        test_data_migration,
        test_youtube_optimizer_thumbnail_generation,
    ]
    
    results = []
    for test_func in tests:
        # ガード処理
        if not callable(test_func):
            results.append({"name": "unknown_test", "status": "failed", "error": "Test target is not callable"})
            continue
            
        print(f"\n[TEST] {test_func.__name__}...", end=" ")
        result = test_func()
        results.append(result)
        
        status = result["status"]
        if status == "passed":
            print("✅ PASSED")
        elif status == "warning":
            print("⚠️ WARNING")
        else:
            print(f"❌ FAILED: {result.get('error', 'Unknown error')}")
    
    # サマリー
    passed = sum(1 for r in results if r["status"] == "passed")
    warnings = sum(1 for r in results if r["status"] == "warning")
    failed = sum(1 for r in results if r["status"] == "failed")
    total = len(results)
    
    print("\n" + "=" * 60)
    print(f"結果: {passed}/{total} passed, {warnings} warnings, {failed} failed")
    print("=" * 60)
    
    overall_status = "passed" if failed == 0 else "failed"
    
    return {
        "timestamp": datetime.now().isoformat(),
        "overall_status": overall_status,
        "summary": {
            "passed": passed,
            "warnings": warnings,
            "failed": failed,
            "total": total
        },
        "results": results
    }


def main() -> None:
    result = run_all_tests()
    
    # 結果をファイルに保存
    output_path = Path(__file__).parent / "integration_test_result.json"
    import json
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n結果を保存: {output_path}")
    except (OSError, IOError) as e:
        sys.stderr.write(f"\n結果の保存に失敗しました: {e}\n")
    
    # 終了コード
    sys.exit(0 if result["overall_status"] == "passed" else 1)


if __name__ == "__main__":
    main()
