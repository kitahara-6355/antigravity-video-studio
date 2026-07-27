import pytest
import sys
from pathlib import Path
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

# backend ディレクトリへのパスを通す
backend_dir = Path(__file__).resolve().parents[2]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# テスト対象モジュールのインポート
import importlib.util
module_path = backend_dir / "archives" / "archive_stable_v3.0_20260118_0953" / "antigravity_api.py"
spec = importlib.util.spec_from_file_location("antigravity_api_archive", str(module_path))
api_mod = importlib.util.module_from_spec(spec)
sys.modules["antigravity_api_archive"] = api_mod
spec.loader.exec_module(api_mod)

router = api_mod.router
validate_safe_path = api_mod.validate_safe_path
ProperNounEntry = api_mod.ProperNounEntry
TelopApprovalRequest = api_mod.TelopApprovalRequest
GenerateThumbnailRequest = api_mod.GenerateThumbnailRequest
GenerateVideoRequest = api_mod.GenerateVideoRequest
CreateFinalVideoRequest = api_mod.CreateFinalVideoRequest

from fastapi import FastAPI
app = FastAPI()
app.include_router(router)
client = TestClient(app)

def test_validate_safe_path_valid():
    file_path = backend_dir / "archives" / "archive_stable_v3.0_20260118_0953" / "antigravity_api.py"
    resolved = validate_safe_path(str(file_path))
    assert resolved.exists()

def test_validate_safe_path_invalid():
    with pytest.raises(HTTPException) as exc_info:
        validate_safe_path(r"C:\Windows\System32\cmd.exe")
    assert exc_info.value.status_code == 400
    assert "Access denied" in exc_info.value.detail

    with pytest.raises(HTTPException) as exc_info:
        validate_safe_path("../../../../../../../../Windows/System32/cmd.exe")
    assert exc_info.value.status_code == 400
    assert "Access denied" in exc_info.value.detail

def test_add_proper_noun_empty():
    response = client.post("/api/antigravity/proper-nouns", json={
        "incorrect": "   ",
        "correct": " "
    })
    assert response.status_code == 400
    assert "cannot be empty" in response.json()["detail"]

def test_process_srt_traversal():
    from unittest.mock import patch
    with patch("antigravity_api_archive.AntigravityPipeline") as mock_pipeline_cls:
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_srt.return_value = {"success": True}
        
        files = {"file": ("../../traversal.srt", b"1\n00:00:01,000 --> 00:00:02,000\nHello", "text/plain")}
        response = client.post("/api/antigravity/process-srt", files=files)
        assert response.status_code == 200
        
        called_path = mock_pipeline.process_srt.call_args[0][0]
        assert called_path.name == "traversal.srt"
        assert "temp" in called_path.parts

def test_process_srt_invalid_extension():
    files = {"file": ("test.txt", b"Hello", "text/plain")}
    response = client.post("/api/antigravity/process-srt", files=files)
    assert response.status_code == 400
    assert "Only SRT files are allowed" in response.json()["detail"]

def test_process_srt_too_large():
    large_content = b"a" * (10 * 1024 * 1024 + 100)
    files = {"file": ("test.srt", large_content, "text/plain")}
    response = client.post("/api/antigravity/process-srt", files=files)
    assert response.status_code == 400
    assert "exceeds the 10MB limit" in response.json()["detail"]

def test_create_final_video_traversal():
    from unittest.mock import patch
    with patch("antigravity_api_archive.video_editor") as mock_editor:
        mock_editor.create_final_video.return_value = {"success": True}
        
        response = client.post("/api/antigravity/editor/create-final", json={
            "main_video": r"C:\Windows\System32\cmd.exe",
            "opening": None,
            "ending": None,
            "telops": [],
            "output_name": "final.mp4"
        })
        assert response.status_code == 400
        assert "Access denied" in response.json()["detail"]

        dummy_file = backend_dir / "archives" / "archive_stable_v3.0_20260118_0953" / "antigravity_api.py"
        response = client.post("/api/antigravity/editor/create-final", json={
            "main_video": str(dummy_file),
            "opening": None,
            "ending": None,
            "telops": [],
            "output_name": "final.mp4"
        })
        assert response.status_code == 200
