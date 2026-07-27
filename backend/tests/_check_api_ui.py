"""API-UI整合性チェック"""
import sys, asyncio, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from routers.usage_router import get_governance_status

# model_config.json からモデル名を動的取得（BL-2: ハードコード排除）
_config_path = Path(__file__).parent.parent / "model_config.json"

_mc = {}
try:
    with open(_config_path, "r", encoding="utf-8") as f:
        _mc = json.load(f)
except (FileNotFoundError, json.JSONDecodeError, PermissionError) as e:
    import warnings
    warnings.warn(f"Failed to load model config from {_config_path}: {e}. Using default models.", RuntimeWarning)
except Exception as e:
    import warnings
    warnings.warn(f"Unexpected error loading model config from {_config_path}: {e}. Using default models.", RuntimeWarning)

if not isinstance(_mc, dict):
    _mc = {}

_text_gen = _mc.get("text_generation", {})
if not isinstance(_text_gen, dict):
    _text_gen = {}

_tiers = _text_gen.get("tiers", {})
if not isinstance(_tiers, dict):
    _tiers = {}

PREMIUM_MODEL = _tiers.get("premium", {}).get("model", "gemini-3-flash-preview")
STANDARD_MODEL = _tiers.get("standard", {}).get("model", "gemini-2.5-flash")
BATCH_MODEL = _tiers.get("batch", {}).get("model", "gemini-2.5-flash-lite")

async def check():
    try:
        result = await get_governance_status()
        if not isinstance(result, dict):
            import warnings
            warnings.warn(f"Governance status result is not a dict: {type(result)}. Treating as empty dict.", RuntimeWarning)
            result = {}
    except Exception as e:
        import warnings
        warnings.warn(f"Failed to fetch governance status: {e}", RuntimeWarning)
        result = {}

    tiers = result.get("tiers")
    if not isinstance(tiers, dict):
        tiers = {}
    usage = result.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    models = usage.get("models")
    if not isinstance(models, dict):
        models = {}
    chain = result.get("fallback_chain")
    if not isinstance(chain, dict):
        chain = {}

    def _get_dict(d, key):
        val = d.get(key)
        return val if isinstance(val, dict) else {}

    premium_tier = _get_dict(tiers, "premium")
    standard_tier = _get_dict(tiers, "standard")
    batch_tier = _get_dict(tiers, "batch")
    premium_model_usage = _get_dict(models, PREMIUM_MODEL)
    standard_model_usage = _get_dict(models, STANDARD_MODEL)
    batch_model_usage = _get_dict(models, BATCH_MODEL)

    checks = [
        ("tiers exists", bool(tiers)),
        ("tiers.premium.model", "model" in premium_tier),
        ("tiers.premium.label", "label" in premium_tier),
        ("tiers.standard.model", "model" in standard_tier),
        ("tiers.batch.model", "model" in batch_tier),
        ("usage.models exists", bool(models)),
        ("premium.usage_ratio", "usage_ratio" in premium_model_usage),
        ("premium.used", "used" in premium_model_usage),
        ("premium.limit", "limit" in premium_model_usage),
        ("standard.usage_ratio", "usage_ratio" in standard_model_usage),
        ("batch.usage_ratio", "usage_ratio" in batch_model_usage),
        ("fallback_chain exists", bool(chain)),
        ("chain count=3", len(chain) == 3),
        ("premium->standard", chain.get(PREMIUM_MODEL) == STANDARD_MODEL),
        ("standard->batch", chain.get(STANDARD_MODEL) == BATCH_MODEL),
        ("batch->null", chain.get(BATCH_MODEL) is None),
    ]

    ok_count = sum(1 for _, ok in checks if ok)
    for label, ok in checks:
        print(f"  [{'OK' if ok else 'NG'}] {label}")
    print(f"\nRESULT: {ok_count}/{len(checks)} passed")
    return ok_count == len(checks)

if __name__ == "__main__":
    try:
        asyncio.run(check())
    except Exception as e:
        print(f"Critical error during API-UI check: {e}", file=sys.stderr)
        sys.exit(1)
