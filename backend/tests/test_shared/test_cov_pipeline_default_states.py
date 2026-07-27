"""
Milestone 22.6 Task B — pipeline_default_states.py カバレッジ 100% 達成テスト
"""
import sys
import types

stub_modules = [
    "routers.trinity", "routers.director", "routers.segments", "routers.render", 
    "routers.quality", "routers.collaboration", "routers.websocket", "routers.preview", 
    "routers.usage_router", "routers.youtube_optimizer", "routers.smartcut", 
    "routers.ab_test_tracker", "routers.shorts", "routers.youtube_upload", 
    "antigravity_api", "manager_monitoring", "routers.soul_router", "routers.dashboard_router", 
    "routers.approval_router", "routers.philosophy_router,", "routers.legacy_director_router", 
    "routers.legacy_council_router", "routers.legacy_production_router", "routers.legacy_management_router", 
    "routers.legacy_live_websocket", "routers.pipeline_router", "routers.health", 
    "routers.pipeline_report", "routers.admin_setup_router", "routers.admin_quota_router", 
    "routers.admin_analytics_router", "routers.admin_quality_router", "routers.admin_incident_router", 
    "routers.admin_integration_router,", "routers.admin_channel_router,", "log_manager", 
    "error_reporter", "google.adk"
]

class DummyObject:
    def __call__(self, *args, **kwargs):
        return DummyObject()
    def __getattr__(self, name):
        return DummyObject()
    def include_router(self, *args, **kwargs):
        pass

class StubModule(types.ModuleType):
    def __getattr__(self, name):
        if name == "router":
            return DummyObject()
        return DummyObject()



import copy
import pytest

# インポート前に一時的に sys.modules をスタブ化
original_modules = {}
for mod in stub_modules:
    if mod in sys.modules:
        original_modules[mod] = sys.modules[mod]
    sys.modules[mod] = StubModule(mod)

try:
    from routers.pipeline_default_states import (
        get_initial_pipeline_state,
        get_initial_transcription_state,
        get_initial_proofreading_state,
        get_initial_quality_gate_state,
        get_initial_improvement_state,
        get_default_transcription_segments,
        get_default_proofreading_segments,
        INITIAL_PIPELINE_STATE,
        INITIAL_TRANSCRIPTION_STATE,
        INITIAL_PROOFREADING_STATE,
        INITIAL_QUALITY_GATE_STATE,
        INITIAL_IMPROVEMENT_STATE,
        DEFAULT_TRANCRIPTION_SEGMENTS,
        DEFAULT_PROOFREADING_SEGMENTS,
    )
finally:
    # インポート完了後に sys.modules を元の状態に復元 (グローバル汚染を防ぐ)
    for mod in stub_modules:
        if mod in original_modules:
            sys.modules[mod] = original_modules[mod]
        else:
            sys.modules.pop(mod, None)

def test_get_initial_pipeline_state():
    res1 = get_initial_pipeline_state()
    res2 = get_initial_pipeline_state()
    assert res1 == INITIAL_PIPELINE_STATE
    assert res1 is not res2
    assert id(res1) != id(res2)
    
    # 内部のリストや辞書もディープコピーされているか検証
    assert id(res1["stages"]) != id(res2["stages"])
    assert len(res1["stages"]) > 0
    assert len(res1["stages"]) == 7  # 7ステージであることを明示的に検証

    # 各ステージの辞書構造およびデータ型の検証
    expected_keys = {"name", "icon", "status", "detail"}
    for stage in res1["stages"]:
        assert set(stage.keys()) == expected_keys
        assert isinstance(stage["name"], str)
        assert isinstance(stage["icon"], str)
        assert isinstance(stage["status"], str)
        assert isinstance(stage["detail"], str)

    for i in range(len(res1["stages"])):
        assert id(res1["stages"][i]) != id(res2["stages"][i])
        
    # 一方の変更が他方に影響しないことを検証 (ディープコピーの振る舞い保証)
    res1["stages"][0]["status"] = "completed"
    assert res2["stages"][0]["status"] == "pending"


def test_get_initial_transcription_state():
    res1 = get_initial_transcription_state()
    res2 = get_initial_transcription_state()
    assert res1 == INITIAL_TRANSCRIPTION_STATE
    assert res1 is not res2
    assert id(res1) != id(res2)
    
    # 内部のリストもディープコピーされているか検証
    assert id(res1["segments"]) != id(res2["segments"])


def test_get_initial_proofreading_state():
    res1 = get_initial_proofreading_state()
    res2 = get_initial_proofreading_state()
    assert res1 == INITIAL_PROOFREADING_STATE
    assert res1 is not res2
    assert id(res1) != id(res2)
    
    # 内部のリストもディープコピーされているか検証
    assert id(res1["segments"]) != id(res2["segments"])


def test_get_initial_quality_gate_state():
    res1 = get_initial_quality_gate_state()
    res2 = get_initial_quality_gate_state()
    assert res1 == INITIAL_QUALITY_GATE_STATE
    assert res1 is not res2
    assert id(res1) != id(res2)
    
    # categories および details の独立性検証
    assert id(res1["categories"]) != id(res2["categories"])
    for i in range(len(res1["categories"])):
        assert id(res1["categories"][i]) != id(res2["categories"][i])
        assert id(res1["categories"][i]["details"]) != id(res2["categories"][i]["details"])
        for j in range(len(res1["categories"][i]["details"])):
            assert id(res1["categories"][i]["details"][j]) != id(res2["categories"][i]["details"][j])
            
    # history の独立性検証
    assert id(res1["history"]) != id(res2["history"])
    for i in range(len(res1["history"])):
        assert id(res1["history"][i]) != id(res2["history"][i])
        
    res1["categories"][0]["score"] = 99
    assert res2["categories"][0]["score"] == 88


def test_get_initial_improvement_state():
    res1 = get_initial_improvement_state()
    res2 = get_initial_improvement_state()
    assert res1 == INITIAL_IMPROVEMENT_STATE
    assert res1 is not res2
    assert id(res1) != id(res2)
    
    # actions, score_history, applied_actions の独立性検証
    assert id(res1["actions"]) != id(res2["actions"])
    for i in range(len(res1["actions"])):
        assert id(res1["actions"][i]) != id(res2["actions"][i])
        
    assert id(res1["score_history"]) != id(res2["score_history"])
    for i in range(len(res1["score_history"])):
        assert id(res1["score_history"][i]) != id(res2["score_history"][i])
        
    assert id(res1["applied_actions"]) != id(res2["applied_actions"])
    
    res1["actions"][0]["status"] = "running"
    assert res2["actions"][0]["status"] == "completed"


def test_get_default_transcription_segments():
    res1 = get_default_transcription_segments()
    res2 = get_default_transcription_segments()
    assert res1 == DEFAULT_TRANCRIPTION_SEGMENTS
    assert res1 is not res2
    assert id(res1) != id(res2)
    
    for i in range(len(res1)):
        assert id(res1[i]) != id(res2[i])
        
    res1[0]["text"] = "modified"
    assert res2[0]["text"] == "こんにちは、今日は新機能について紹介します"


def test_get_default_proofreading_segments():
    res1 = get_default_proofreading_segments()
    res2 = get_default_proofreading_segments()
    assert res1 == DEFAULT_PROOFREADING_SEGMENTS
    assert res1 is not res2
    assert id(res1) != id(res2)
    
    for i in range(len(res1)):
        assert id(res1[i]) != id(res2[i])
        if "changes" in res1[i]:
            assert id(res1[i]["changes"]) != id(res2[i]["changes"])
            for j in range(len(res1[i]["changes"])):
                assert id(res1[i]["changes"][j]) != id(res2[i]["changes"][j])
                
    res1[0]["changes"][0]["original"] = "modified"
    assert res2[0]["changes"][0]["original"] == "きょう"


# ファクトリ関数の新しい引数チェックのテスト
def test_factory_arguments_validation():
    # 正常系
    state = get_initial_pipeline_state(session_id="session-123", video_path="/path/to/video.mp4", target_minutes=15)
    assert state["session_id"] == "session-123"
    assert state["video_path"] == "/path/to/video.mp4"
    assert state["target_minutes"] == 15

    # 異常系
    with pytest.raises(TypeError):
        get_initial_pipeline_state(session_id=123)
    with pytest.raises(TypeError):
        get_initial_pipeline_state(session_id=True)
    with pytest.raises(TypeError):
        get_initial_pipeline_state(video_path=123)
    with pytest.raises(TypeError):
        get_initial_pipeline_state(video_path=False)
    with pytest.raises(TypeError):
        get_initial_pipeline_state(target_minutes="15")
    with pytest.raises(TypeError):
        get_initial_pipeline_state(target_minutes=True)
    with pytest.raises(ValueError):
        get_initial_pipeline_state(target_minutes=0)
    with pytest.raises(ValueError):
        get_initial_pipeline_state(target_minutes=-5)

    # transcription model 引数の型チェック
    state_t = get_initial_transcription_state(model="large")
    assert state_t["model"] == "large"
    with pytest.raises(TypeError):
        get_initial_transcription_state(model=123)
    with pytest.raises(TypeError):
        get_initial_transcription_state(model=True)
    with pytest.raises(ValueError):
        get_initial_transcription_state(model="")

# 状態検証（バリデーション）関数のテスト
