"""
Quality Router Unit Tests
"""
import sys
import types
import pydantic

# 🛡️ Pydantic v2 / Python 3.13 tuple.index MRO 回避パッチ
import pydantic._internal._model_construction as mc
original_import = mc.import_cached_base_model

def patched_import():
    base_model = original_import()
    frame = sys._getframe()
    while frame:
        if frame.f_code.co_name == '__new__' and 'cls' in frame.f_locals:
            cls = frame.f_locals['cls']
            mro = cls.__mro__
            if base_model not in mro:
                for item in mro:
                    if item.__name__ in ('BaseModel', 'BaseSettings', 'BaseModel_', 'Settings'):
                        return item
                if len(mro) > 1:
                    return mro[-2] if mro[-2] is not object else mro[0]
            break
        frame = frame.f_back
    return base_model

mc.import_cached_base_model = patched_import

try:
    from pydantic import RootModel
except ImportError:
    class RootModel:
        pass

if 'pydantic.root_model' not in sys.modules:
    m = types.ModuleType('pydantic.root_model')
    m.RootModel = RootModel
    sys.modules['pydantic.root_model'] = m

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path

# パス追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from routers.quality import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

def test_run_quality_check_success():
    mock_result = {"status": "passed", "score": 95, "details": []}
    with patch("quality_gate_agent.quality_gate.comprehensive_check", return_value=mock_result, create=True) as mock_check:
        response = client.post("/api/quality/check", json={
            "full_text": "テストテキスト",
            "scenes": [{"id": 1, "description": "シーン1"}],
            "segments": [{"id": 1, "text": "セグメント1"}]
        })
        assert response.status_code == 200
        assert response.json() == mock_result
        mock_check.assert_called_once_with(
            full_text="テストテキスト",
            scenes=[{"id": 1, "description": "シーン1"}],
            segments=[{"id": 1, "text": "セグメント1"}]
        )

def test_run_quality_check_default():
    mock_result = {"status": "passed", "score": 95, "details": []}
    with patch("quality_gate_agent.quality_gate.comprehensive_check", return_value=mock_result, create=True) as mock_check:
        response = client.post("/api/quality/check", json={})
        assert response.status_code == 200
        assert response.json() == mock_result
        mock_check.assert_called_once_with(
            full_text="",
            scenes=[],
            segments=[]
        )

def test_get_quality_threshold():
    response = client.get("/api/quality/threshold")
    assert response.status_code == 200
    data = response.json()
    assert data["pass_threshold"] == 90
    assert data["block_threshold"] == 60
    assert data["warning_threshold"] == 70

def test_verify_quality_success():
    mock_result = {"status": "ok"}
    with patch("quality_gate_agent.quality_gate.pre_render_check", return_value=mock_result, create=True) as mock_check:
        response = client.post("/api/quality/verify", json={"key": "val"})
        assert response.status_code == 200
        assert response.json() == mock_result
        mock_check.assert_called_once_with({"key": "val"})

def test_run_cleanup_dry_run():
    mock_result = {"preview": True, "files": []}
    with patch("cleanup_manager.cleanup_manager.preview_cleanup", return_value=mock_result, create=True) as mock_preview:
        response = client.post("/api/quality/cleanup", json={"dry_run": True, "category": "temp"})
        assert response.status_code == 200
        assert response.json() == mock_result
        mock_preview.assert_called_once()

def test_run_cleanup_execute():
    mock_result = {"cleaned": True, "count": 5}
    with patch("cleanup_manager.cleanup_manager.cleanup", return_value=mock_result, create=True) as mock_run:
        response = client.post("/api/quality/cleanup", json={"dry_run": False, "category": "temp"})
        assert response.status_code == 200
        assert response.json() == mock_result
        mock_run.assert_called_once_with(category="temp")

def test_run_cleanup_no_req():
    mock_result = {"cleaned": True, "count": 3}
    with patch("cleanup_manager.cleanup_manager.cleanup", return_value=mock_result, create=True) as mock_run:
        response = client.post("/api/quality/cleanup")
        assert response.status_code == 200
        assert response.json() == mock_result
        mock_run.assert_called_once_with(category=None)

def test_preview_cleanup():
    mock_result = {"files": ["file1.tmp"]}
    with patch("cleanup_manager.cleanup_manager.preview_cleanup", return_value=mock_result, create=True) as mock_preview:
        response = client.get("/api/quality/cleanup/preview")
        assert response.status_code == 200
        assert response.json() == mock_result
        mock_preview.assert_called_once()

def test_get_storage_stats():
    mock_result = {"used": 1000}
    with patch("cleanup_manager.cleanup_manager.get_storage_stats", return_value=mock_result, create=True) as mock_stats:
        response = client.get("/api/quality/storage/stats")
        assert response.status_code == 200
        assert response.json() == mock_result
        mock_stats.assert_called_once()

def test_rhythm_split():
    mock_result = ["a", "b"]
    with patch("ai_rhythm.semantic_split", return_value=mock_result, create=True) as mock_split:
        response = client.post("/api/quality/rhythm/split", json={"text": "こんにちは世界", "target_chars": 10})
        assert response.status_code == 200
        assert response.json() == {"splits": mock_result}
        mock_split.assert_called_once_with("こんにちは世界", 10)

def test_quick_decision():
    req_data = {
        "item_id": "item123",
        "action": "approve",
        "timestamp": "2026-05-22T12:00:00",
        "comment": "Good quality"
    }
    with patch("pathlib.Path.mkdir") as mock_mkdir, \
         patch("builtins.open", mock_open()) as mock_file:
        response = client.post("/api/quality/decision/quick", json=req_data)
        assert response.status_code == 200
        res_json = response.json()
        assert res_json["status"] == "ok"
        assert res_json["decision"]["item_id"] == "item123"
        assert res_json["decision"]["action"] == "approve"
        assert res_json["decision"]["timestamp"] == "2026-05-22T12:00:00"
        assert res_json["decision"]["comment"] == "Good quality"
        mock_mkdir.assert_called_once()
        mock_file.assert_called_once()

def test_quick_decision_default_timestamp():
    req_data = {
        "item_id": "item123",
        "action": "approve",
        "comment": "Good quality"
    }
    with patch("pathlib.Path.mkdir") as mock_mkdir, \
         patch("builtins.open", mock_open()) as mock_file:
        response = client.post("/api/quality/decision/quick", json=req_data)
        assert response.status_code == 200
        res_json = response.json()
        assert res_json["status"] == "ok"
        assert res_json["decision"]["timestamp"] != ""
        mock_mkdir.assert_called_once()
        mock_file.assert_called_once()

def test_apply_suggestion():
    req_data = {
        "suggestion": "Make it better",
        "index": 2
    }
    response = client.post("/api/quality/apply-suggestion", json=req_data)
    assert response.status_code == 200
    assert response.json() == {"status": "applied", "index": 2}

def test_undo_suggestion():
    req_data = {
        "suggestion": "Make it better",
        "index": 2
    }
    response = client.post("/api/quality/undo-suggestion", json=req_data)
    assert response.status_code == 200
    assert response.json() == {"status": "undone", "index": 2}

def test_approve_review():
    req_data = {
        "stages": [{"stage": 1, "completed": True}, {"stage": 2, "completed": False}],
        "approved_at": "2026-05-22T12:00:00"
    }
    with patch("pathlib.Path.mkdir") as mock_mkdir, \
         patch("builtins.open", mock_open()) as mock_file:
        response = client.post("/api/quality/review/approve", json=req_data)
        assert response.status_code == 200
        res_json = response.json()
        assert res_json["status"] == "approved"
        entry = res_json["entry"]
        assert entry["stages"] == req_data["stages"]
        assert entry["approved_at"] == "2026-05-22T12:00:00"
        assert entry["total_stages"] == 2
        assert entry["completed_stages"] == 1
        mock_mkdir.assert_called_once()
        mock_file.assert_called_once()

def test_approve_review_default_approved_at():
    req_data = {
        "stages": [{"stage": 1, "completed": True}],
    }
    with patch("pathlib.Path.mkdir") as mock_mkdir, \
         patch("builtins.open", mock_open()) as mock_file:
        response = client.post("/api/quality/review/approve", json=req_data)
        assert response.status_code == 200
        res_json = response.json()
        assert res_json["status"] == "approved"
        assert res_json["entry"]["approved_at"] != ""
        mock_mkdir.assert_called_once()
        mock_file.assert_called_once()

def test_quick_decision_actual_file_write(tmp_path):
    import json
    import builtins
    import pathlib
    
    original_mkdir = pathlib.Path.mkdir
    original_open = builtins.open
    
    # 2026-07-26: 文字列でのパス突き合わせは Windows 前提だった（詳細は
    # test_approve_review_actual_file_write のコメント参照）。pathlib で判定する。
    decisions_dir = (pathlib.Path(__file__).parent.parent / "data" / "decisions").resolve()
    redirect_dir = tmp_path / "decisions"

    def redirect_path(path_obj):
        try:
            resolved = pathlib.Path(path_obj).resolve()
        except (OSError, TypeError, ValueError):
            return path_obj
        try:
            relative = resolved.relative_to(decisions_dir)
        except ValueError:
            return path_obj
        return redirect_dir / relative

    def patched_mkdir(self, *args, **kwargs):
        new_self = redirect_path(self)
        return original_mkdir(new_self, *args, **kwargs)

    def patched_open(file, *args, **kwargs):
        new_file = redirect_path(file)
        return original_open(new_file, *args, **kwargs)

    with patch.object(pathlib.Path, "mkdir", patched_mkdir), \
         patch("builtins.open", patched_open):
        req_data = {
            "item_id": "item_actual_123",
            "action": "approve",
            "timestamp": "2026-06-03T10:00:00",
            "comment": "Actual file writing test"
        }
        response = client.post("/api/quality/decision/quick", json=req_data)
        assert response.status_code == 200
        
        real_log_dir = tmp_path / "decisions"
        log_files = list(real_log_dir.glob("decisions_*.jsonl"))
        assert len(log_files) == 1
        
        with open(log_files[0], "r", encoding="utf-8") as f:
            lines = f.readlines()
            assert len(lines) == 1
            data = json.loads(lines[0])
            assert data["item_id"] == "item_actual_123"
            assert data["action"] == "approve"
            assert data["comment"] == "Actual file writing test"

def test_approve_review_actual_file_write(tmp_path):
    import json
    import builtins
    import pathlib
    
    original_mkdir = pathlib.Path.mkdir
    original_open = builtins.open
    
    # 2026-07-26: 以前は str(path).replace("/", "\\") で正規化した文字列と、
    # 正規化していない base_dir を突き合わせていた。Linux では base_dir が
    # 前方スラッシュのままなので一致せず、リダイレクトが効かないまま本物の
    # ディレクトリに書き込まれ、tmp_path 側が空で assert 0 == 1 になっていた。
    # 文字列操作をやめ、pathlib の関係判定で書き換える。
    reviews_dir = (pathlib.Path(__file__).parent.parent / "data" / "reviews").resolve()
    redirect_dir = tmp_path / "reviews"

    def redirect_path(path_obj):
        try:
            resolved = pathlib.Path(path_obj).resolve()
        except (OSError, TypeError, ValueError):
            return path_obj
        try:
            relative = resolved.relative_to(reviews_dir)
        except ValueError:
            return path_obj
        return redirect_dir / relative

    def patched_mkdir(self, *args, **kwargs):
        new_self = redirect_path(self)
        return original_mkdir(new_self, *args, **kwargs)

    def patched_open(file, *args, **kwargs):
        new_file = redirect_path(file)
        return original_open(new_file, *args, **kwargs)

    with patch.object(pathlib.Path, "mkdir", patched_mkdir), \
         patch("builtins.open", patched_open):
        req_data = {
            "stages": [{"stage": 1, "completed": True}],
            "approved_at": "2026-06-03T10:00:00"
        }
        response = client.post("/api/quality/review/approve", json=req_data)
        assert response.status_code == 200
        
        real_log_dir = tmp_path / "reviews"
        log_files = list(real_log_dir.glob("reviews_*.jsonl"))
        assert len(log_files) == 1
        
        with open(log_files[0], "r", encoding="utf-8") as f:
            lines = f.readlines()
            assert len(lines) == 1
            data = json.loads(lines[0])
            assert data["stages"] == req_data["stages"]
            assert data["approved_at"] == "2026-06-03T10:00:00"
            assert data["total_stages"] == 1
            assert data["completed_stages"] == 1

def test_rhythm_split_edge_cases():
    with patch("ai_rhythm.semantic_split", return_value=[], create=True) as mock_split:
        response = client.post("/api/quality/rhythm/split", json={"text": "", "target_chars": -5})
        assert response.status_code == 200
        assert response.json() == {"splits": []}
        mock_split.assert_called_once_with("", -5)


def test_quality_gate_agent_comprehensive_check_direct():
    from quality_gate_agent import quality_gate
    res = quality_gate.comprehensive_check(
        full_text="テスト原稿です。以外と難しい。",
        segments=[{"text": "以外と難しい。", "start": 0.0, "end": 2.0}]
    )
    assert "status" in res
    assert "score" in res
    assert "details" in res
    assert res["score"] < 100
    assert len(res["details"]) > 0

def test_quality_gate_agent_pre_render_check_direct():
    from quality_gate_agent import quality_gate
    res = quality_gate.pre_render_check({
        "full_text": "正常な原稿です。",
        "segments": [],
        "scenes": []
    })
    assert "status" in res
    assert res["status"] == "ok"
