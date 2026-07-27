import pytest
from fixtures.mock_data import get_preset_ctx, get_preset_description, PRESETS
from agents.pipeline_coordinator import PipelineContext

def test_get_preset_ctx_all():
    # 全てのプリセットIDで正常に PipelineContext が生成されるかテスト
    for preset_id in PRESETS:
        ctx = get_preset_ctx(preset_id)
        assert isinstance(ctx, PipelineContext)
        # プリセットごとの検証
        if preset_id == "MD-01":
            assert len(ctx.segments) == 0
        elif preset_id == "MD-02":
            assert len(ctx.segments) == 1
        elif preset_id == "MD-03":
            assert len(ctx.segments) == 10
        elif preset_id == "MD-04":
            assert len(ctx.segments) == 50
        elif preset_id == "MD-05":
            assert len(ctx.segments) == 10
            # 破損データの混入（textフィールド欠落などの検証）
            # mock_pipelineで corrupt=True のときは i%5==3 のテキストが欠落し、i%5==4 の start>end になる
            assert "text" not in ctx.segments[3]
            assert ctx.segments[4]["start"] > ctx.segments[4]["end"]
        elif preset_id == "MD-06":
            assert len(ctx.segments) == 10
            # 型不正データの混入 (start=str, end=None)
            assert isinstance(ctx.segments[2]["start"], str)
            assert ctx.segments[3]["end"] is None
        elif preset_id == "MD-07":
            assert len(ctx.segments) == 100

def test_get_preset_ctx_overrides():
    # overrides が正しく適用されるかテスト
    ctx = get_preset_ctx("MD-03", target_minutes=15, session_id="custom-session")
    assert ctx.target_minutes == 15
    assert ctx.session_id == "custom-session"

    # segments や duration_each などのパラメータ上書きも検証
    ctx_overridden = get_preset_ctx("MD-03", segments=5, duration_each=5.0)
    assert len(ctx_overridden.segments) == 5
    assert ctx_overridden.segments[0]["end"] - ctx_overridden.segments[0]["start"] == 5.0

def test_get_preset_ctx_unknown():
    # 未定義のIDで KeyError が発生するかテスト
    with pytest.raises(KeyError) as exc_info:
        get_preset_ctx("UNKNOWN-ID")
    assert "Unknown preset" in str(exc_info.value)
    # エラーメッセージに利用可能なIDリストが含まれていることを詳細検証
    for preset_id in PRESETS:
        assert preset_id in str(exc_info.value)

def test_get_preset_description():
    # 全てのプリセットで説明が正しく取得できるかテスト
    for preset_id in PRESETS:
        desc = get_preset_description(preset_id)
        assert desc == PRESETS[preset_id]["description"]
        assert len(desc) > 0

def test_get_preset_description_unknown():
    # 未定義のIDで KeyError が発生するかテスト
    with pytest.raises(KeyError) as exc_info:
        get_preset_description("UNKNOWN-ID")
    assert "Unknown preset" in str(exc_info.value)
    # エラーメッセージに利用可能なIDリストが含まれていることを詳細検証
    for preset_id in PRESETS:
        assert preset_id in str(exc_info.value)

def test_presets_structure_metadata():
    # PRESETS 辞書自体のメタ構造を検証（将来の追加時のバグ防止）
    assert isinstance(PRESETS, dict)
    assert len(PRESETS) > 0
    for preset_id, info in PRESETS.items():
        assert isinstance(preset_id, str)
        assert preset_id.startswith("MD-")
        assert isinstance(info, dict)
        assert "description" in info
        assert isinstance(info["description"], str)
        assert len(info["description"]) > 0
        assert "segments" in info
        assert isinstance(info["segments"], int)
        assert info["segments"] >= 0


def test_validate_preset_id_direct():
    # プライベート関数 _validate_preset_id を直接テスト
    from fixtures.mock_data import _validate_preset_id
    for preset_id in PRESETS:
        # 定義済みのIDでは例外が発生しないこと
        _validate_preset_id(preset_id)

    # 不正なIDでは KeyError が発生すること
    with pytest.raises(KeyError) as exc_info:
        _validate_preset_id("MD-INVALID-999")
    assert "Unknown preset: MD-INVALID-999" in str(exc_info.value)

def test_get_preset_ctx_extreme_overrides():
    # 極端なオーバーライド値や境界値のテスト
    ctx_zero = get_preset_ctx("MD-03", segments=0, duration_each=0.0)
    assert len(ctx_zero.segments) == 0

    ctx_empty_session = get_preset_ctx("MD-03", session_id="")
    assert ctx_empty_session.session_id == ""

    # 負のセグメント数（もし許容されているか、あるいはエラーになるか）
    # create_mock_ctxの仕様上、 range(segments) を使うため、負数だと空になる
    ctx_negative = get_preset_ctx("MD-03", segments=-5)
    assert len(ctx_negative.segments) == 0
