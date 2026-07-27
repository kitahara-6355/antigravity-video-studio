"""
MASTER v3.6 モックデータプリセット定義 (MD-01〜MD-07)

名前付きプリセットで、テストから簡潔に呼び出し可能。

使用例:
    from fixtures.mock_data import get_preset_ctx, PRESETS

    ctx = get_preset_ctx("MD-01")           # 空パイプライン
    ctx = get_preset_ctx("MD-03")           # 標準パイプライン
    ctx = get_preset_ctx("MD-05")           # 破損データ
    ctx = get_preset_ctx("MD-07", target_minutes=30)  # 長尺 + カスタム
"""

from .mock_pipeline import create_mock_ctx

# ============================================================
# プリセット定義
# ============================================================

PRESETS = {
    "MD-01": {
        "segments": 0,
        "description": "空パイプライン — セグメント0個",
    },
    "MD-02": {
        "segments": 1,
        "description": "最小パイプライン — セグメント1個 (3秒)",
        "duration_each": 3.0,
    },
    "MD-03": {
        "segments": 10,
        "description": "標準パイプライン — セグメント10個",
    },
    "MD-04": {
        "segments": 50,
        "description": "大量セグメント — 50個 (mixed言語想定)",
    },
    "MD-05": {
        "segments": 10,
        "corrupt": True,
        "description": "破損データ — text欠落, start>end 混入",
    },
    "MD-06": {
        "segments": 10,
        "type_error": True,
        "description": "型不正データ — start=str, end=None 混入",
    },
    "MD-07": {
        "segments": 100,
        "duration_each": 18.0,
        "description": "長尺データ — 100セグメント (30分相当)",
    },
}


def _validate_preset_id(preset_id: str) -> None:
    """プリセットIDの存在を確認し、存在しない場合は詳細なKeyErrorを投げる"""
    if preset_id not in PRESETS:
        available = sorted(list(PRESETS.keys()))
        raise KeyError(f"Unknown preset: {preset_id}. Available: {available}")


def get_preset_ctx(preset_id: str, **overrides):
    """プリセットIDからPipelineContextを生成

    Args:
        preset_id: "MD-01" 〜 "MD-07"
        **overrides: プリセット値を上書きするキーワード引数

    Returns:
        PipelineContext インスタンス

    Raises:
        KeyError: 不明なプリセットID
    """
    _validate_preset_id(preset_id)

    # description は create_mock_ctx に渡さない
    params = {k: v for k, v in PRESETS[preset_id].items() if k != "description"}
    params.update(overrides)
    return create_mock_ctx(**params)


def get_preset_description(preset_id: str) -> str:
    """プリセットの説明を取得"""
    _validate_preset_id(preset_id)
    return PRESETS[preset_id]["description"]
