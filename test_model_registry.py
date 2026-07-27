"""
Model Registry導入後の包括的テストスクリプト
- インポートテスト
- Model Registry機能テスト
- API呼び出しテスト
- 統合テスト
"""
import os
import sys
import traceback
from pathlib import Path

# バックエンドディレクトリをパスに追加
BACKEND_DIR = Path(__file__).parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# .env読み込み
from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env")

print("=" * 60)
print("Model Registry導入後の包括的テスト")
print("=" * 60)

results = {
    "passed": [],
    "failed": [],
    "skipped": []
}

def test(name, func):
    """テスト実行ラッパー"""
    try:
        print(f"\n🧪 {name}...")
        result = func()
        if result:
            print(f"   ✅ PASSED")
            results["passed"].append(name)
        else:
            print(f"   ⚠️ SKIPPED")
            results["skipped"].append(name)
        return True
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        traceback.print_exc()
        results["failed"].append((name, str(e)))
        return False

# ============================================================
# Test 1: Model Registry Import
# ============================================================
def test_model_registry_import():
    from model_registry import ModelRegistry, get_model
    registry = ModelRegistry()
    assert registry is not None
    return True

test("Model Registry Import", test_model_registry_import)

# ============================================================
# Test 2: Model Registry Functions
# ============================================================
def test_model_registry_functions():
    from model_registry import ModelRegistry, get_model
    
    # タスク別モデル取得
    model = get_model("ai_confirmation")
    assert model == "gemini-2.0-flash", f"Expected gemini-2.0-flash, got {model}"
    
    model = get_model("quality_gate")
    assert model == "gemini-2.5-flash", f"Expected gemini-2.5-flash, got {model}"
    
    # デフォルトモデル
    registry = ModelRegistry()
    default = registry.get_default_model()
    assert default == "gemini-2.0-flash", f"Default should be gemini-2.0-flash, got {default}"
    
    return True

test("Model Registry Functions", test_model_registry_functions)

# ============================================================
# Test 3: Model Availability Check
# ============================================================
def test_model_availability():
    from model_registry import ModelRegistry
    registry = ModelRegistry()
    availability = registry.check_model_availability()
    
    print(f"   Available models: {len(availability)} checked")
    for model, available in availability.items():
        status = "✅" if available else "❌"
        print(f"     {status} {model}")
    
    return True

test("Model Availability Check (API)", test_model_availability)

# ============================================================
# Test 4: Deprecation Warnings
# ============================================================
def test_deprecation_warnings():
    from model_registry import ModelRegistry
    registry = ModelRegistry()
    warnings = registry.check_deprecation_warnings()
    
    print(f"   Deprecation warnings: {len(warnings)}")
    for w in warnings:
        print(f"     ⚠️ {w.model} → {w.replacement} (残り{w.days_remaining}日)")
    
    return True

test("Deprecation Warnings", test_deprecation_warnings)

# ============================================================
# Test 5: Interactive Preview Import
# ============================================================
def test_interactive_preview_import():
    from interactive_preview import SubtitleConfirmationChecker, TelopSuggester
    checker = SubtitleConfirmationChecker()
    suggester = TelopSuggester()
    return True

test("Interactive Preview Import", test_interactive_preview_import)

# ============================================================
# Test 6: Director Engine Import
# ============================================================
def test_director_engine_import():
    from director_engine import DirectorBrain, brain
    assert brain.chat_model is not None
    print(f"   chat_model: {brain.chat_model}")
    return True

test("Director Engine Import", test_director_engine_import)

# ============================================================
# Test 7: Quality Gate AI Import
# ============================================================
def test_quality_gate_import():
    from quality_gate_ai import AIQualityChecker, ai_quality_checker
    assert ai_quality_checker is not None
    return True

test("Quality Gate AI Import", test_quality_gate_import)

# ============================================================
# Test 8: Branding Manager Import
# ============================================================
def test_branding_manager_import():
    from branding_manager import branding_manager
    assert branding_manager is not None
    return True

test("Branding Manager Import", test_branding_manager_import)

# ============================================================
# Test 9: Gemini Chunker Import
# ============================================================
def test_gemini_chunker_import():
    from gemini_chunker_fixed import process_whisper_segments, DEFAULT_MODEL
    print(f"   DEFAULT_MODEL: {DEFAULT_MODEL}")
    return True

test("Gemini Chunker Import", test_gemini_chunker_import)

# ============================================================
# Test 10: Gemini Semantic Chunker Import
# ============================================================
def test_gemini_semantic_chunker_import():
    from gemini_semantic_chunker import GeminiSemanticChunker, DEFAULT_MODEL
    chunker = GeminiSemanticChunker()
    print(f"   model_name: {chunker.model_name}")
    return True

test("Gemini Semantic Chunker Import", test_gemini_semantic_chunker_import)

# ============================================================
# Test 11: Agent Base Import
# ============================================================
def test_agent_base_import():
    sys.path.insert(0, str(BACKEND_DIR / "agents"))
    from agent_base import Agent
    return True

test("Agent Base Import", test_agent_base_import)

# ============================================================
# Test 12: Supervisor Agent Import
# ============================================================
def test_supervisor_import():
    sys.path.insert(0, str(BACKEND_DIR / "agents"))
    from supervisor import SupervisorAgent
    sup = SupervisorAgent()
    print(f"   model_name: {sup.model_name}")
    return True

test("Supervisor Agent Import", test_supervisor_import)

# ============================================================
# Test 13: API Call - Model Registry Optimal Report
# ============================================================
def test_api_optimal_report():
    from model_registry import ModelRegistry
    registry = ModelRegistry()
    report = registry.get_optimal_model_report()
    print(f"   Report length: {len(report)} chars")
    return True

test("API Call - Optimal Report", test_api_optimal_report)

# ============================================================
# Test 14: Simple API Call
# ============================================================
def test_simple_api_call():
    from google import genai
    from model_registry import get_model
    
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("   GOOGLE_API_KEY not found, skipping")
        return False
    
    client = genai.Client(api_key=api_key)
    model = get_model("ai_confirmation")
    
    response = client.models.generate_content(
        model=model,
        contents="Say 'Hello' in Japanese. Reply with just the word."
    )
    
    print(f"   Model: {model}")
    print(f"   Response: {response.text.strip()}")
    return True

test("Simple API Call", test_simple_api_call)

# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 60)
print("テスト結果サマリー")
print("=" * 60)
print(f"✅ PASSED:  {len(results['passed'])} tests")
print(f"⚠️ SKIPPED: {len(results['skipped'])} tests")
print(f"❌ FAILED:  {len(results['failed'])} tests")

if results["failed"]:
    print("\n❌ 失敗したテスト:")
    for name, error in results["failed"]:
        print(f"   - {name}: {error}")

print("\n" + "=" * 60)
if not results["failed"]:
    print("🎉 全テスト合格！")
else:
    print("⚠️ 一部テストが失敗しました")
print("=" * 60)
