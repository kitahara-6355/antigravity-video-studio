"""API-UI整合性チェック: governance APIレスポンスの構造がOperationsDashboard.jsxの期待と一致するか検証"""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

# template_config のインポートエラーを回避するためのモック
# themes_router が template_config から PRODUCTION_TEMPLATES, MOOD_THEMES, RECOMMENDED_COMBOS をインポートするため
if "template_config" not in sys.modules:
    mock_module = MagicMock()
    mock_module.PRODUCTION_TEMPLATES = {}
    mock_module.MOOD_THEMES = {}
    mock_module.RECOMMENDED_COMBOS = {}
    sys.modules["template_config"] = mock_module
else:
    mock_module = sys.modules["template_config"]
    if not hasattr(mock_module, "PRODUCTION_TEMPLATES"):
        mock_module.PRODUCTION_TEMPLATES = {}
    if not hasattr(mock_module, "MOOD_THEMES"):
        mock_module.MOOD_THEMES = {}
    if not hasattr(mock_module, "RECOMMENDED_COMBOS"):
        mock_module.RECOMMENDED_COMBOS = {}

# アライメントスクリプトの親ディレクトリをインポートパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from routers.usage_router import get_governance_status


def load_model_config() -> dict:
    """model_config.json から設定をロードする。失敗した場合は空の辞書を返す"""
    config_path = Path(__file__).parent.parent / "model_config.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError) as e:
        print(f"Warning: Failed to load model config: {e}", file=sys.stderr)
        return {}
    except OSError as e:
        print(f"Warning: OS error loading model config: {e}", file=sys.stderr)
        return {}
    except (TypeError, ValueError, RuntimeError) as e:
        print(f"Error: Unexpected error loading model config: {e}", file=sys.stderr)
        return {}


# model_config.json からモデル名を動的取得（BL-2: ハードコード排除）
_tiers = load_model_config().get("text_generation", {}).get("tiers", {})
PREMIUM_MODEL = _tiers.get("premium", {}).get("model", "gemini-3-flash-preview")
STANDARD_MODEL = _tiers.get("standard", {}).get("model", "gemini-2.5-flash")
BATCH_MODEL = _tiers.get("batch", {}).get("model", "gemini-2.5-flash-lite")


def _is_gemini_model(model_name: str) -> bool:
    """モデル名がgeminiモデルであるかを判定する"""
    return model_name.startswith("gemini")


def _print_governance_tiers_info(tiers: dict) -> None:
    """governance.tiers の情報を出力する"""
    print("1. governance.tiers:")
    for tier_name, tier_info in tiers.items():
        print(f"   {tier_name}: model={tier_info.get('model')}, label={tier_info.get('label')}")


def _print_model_usage_status(models: dict) -> None:
    """governance.usage.models の情報を出力する (geminiモデルのみ)"""
    print("\n2. governance.usage.models (gemini only):")
    for model_name, model_info in models.items():
        if _is_gemini_model(model_name):
            print(f"   {model_name}: used={model_info.get('used')}, limit={model_info.get('limit')}, ratio={model_info.get('usage_ratio')}")


def _print_model_fallback_chain(chain: dict) -> None:
    """governance.fallback_chain の情報を出力する"""
    print("\n3. governance.fallback_chain:")
    for source_model, target_model in chain.items():
        print(f"   {source_model} -> {target_model}")


def _check_alignment_rules(tiers: dict, models: dict, chain: dict) -> list[tuple[str, bool]]:
    """OperationsDashboard.jsx との整合性を判定するルール群を評価する"""
    return [
        ("tiers exists", bool(tiers)),
        ("tiers.premium.model", "model" in tiers.get("premium", {})),
        ("tiers.premium.label", "label" in tiers.get("premium", {})),
        ("tiers.standard.model", "model" in tiers.get("standard", {})),
        ("tiers.batch.model", "model" in tiers.get("batch", {})),
        ("usage.models exists", bool(models)),
        ("premium.usage_ratio", "usage_ratio" in models.get(PREMIUM_MODEL, {})),
        ("premium.used", "used" in models.get(PREMIUM_MODEL, {})),
        ("premium.limit", "limit" in models.get(PREMIUM_MODEL, {})),
        ("standard.usage_ratio", "usage_ratio" in models.get(STANDARD_MODEL, {})),
        ("batch.usage_ratio", "usage_ratio" in models.get(BATCH_MODEL, {})),
        ("fallback_chain exists", bool(chain)),
        ("fallback_chain has 3 entries", len(chain) == 3),
        ("chain: premium->standard", chain.get(PREMIUM_MODEL) == STANDARD_MODEL),
        ("chain: standard->batch", chain.get(STANDARD_MODEL) == BATCH_MODEL),
        ("chain: batch->null", chain.get(BATCH_MODEL) is None),
    ]


def _print_evaluation_results(checks: list[tuple[str, bool]]) -> bool:
    """整合性チェックの結果を出力し、すべてOKだったかを返す"""
    print("\n4. OperationsDashboard.jsx との整合性:")
    all_ok = True
    for label, is_ok in checks:
        icon = "OK" if is_ok else "NG"
        print(f"   [{icon}] {label}")
        if not is_ok:
            all_ok = False
    return all_ok


async def _fetch_governance_data() -> dict:
    """governance_status を取得し、辞書であることを保証する"""
    try:
        result = await get_governance_status()
        return result if isinstance(result, dict) else {}
    except (KeyError, ValueError, TypeError, ImportError, OSError, RuntimeError) as e:
        print(f"Error fetching governance data: {e}", file=sys.stderr)
        return {}


async def check_api_ui_alignment() -> None:
    """API-UIの整合性を取得・出力・評価するメイン関数"""
    result = await _fetch_governance_data()
    
    print("=== APIレスポンスとUIコードの整合性チェック ===\n")
    
    tiers = result.get("tiers", {})
    _print_governance_tiers_info(tiers)
    
    usage = result.get("usage", {})
    models = usage.get("models", {})
    _print_model_usage_status(models)
    
    chain = result.get("fallback_chain", {})
    _print_model_fallback_chain(chain)
    
    checks = _check_alignment_rules(tiers, models, chain)
    all_ok = _print_evaluation_results(checks)
    
    print()
    if all_ok:
        print("RESULT: ALL OK (16/16) -- ダッシュボードは正常表示されるはず")
    else:
        print("RESULT: NG -- 不整合あり")


# 既存の外部呼出（エイリアス）互換性の維持
check = check_api_ui_alignment


if __name__ == "__main__":
    asyncio.run(check())
