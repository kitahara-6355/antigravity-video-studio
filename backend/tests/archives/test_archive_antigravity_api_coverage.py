import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import json
from fastapi import HTTPException
from fastapi.testclient import TestClient

# backend ディレクトリへのパスを通す
backend_dir = Path(__file__).resolve().parents[2]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# テスト対象モジュールのインポート
import importlib.util
module_path = backend_dir / "archives" / "archive_stable_v3.0_20260118_0953" / "antigravity_api.py"
spec = importlib.util.spec_from_file_location("antigravity_api_archive_cov", str(module_path))
api_mod = importlib.util.module_from_spec(spec)
sys.modules["antigravity_api_archive_cov"] = api_mod
spec.loader.exec_module(api_mod)

router = api_mod.router
validate_safe_path = api_mod.validate_safe_path

from fastapi import FastAPI
app = FastAPI()
app.include_router(router)
client = TestClient(app)

# --- 1. validate_safe_path ---
def test_validate_safe_path_empty():
    with pytest.raises(HTTPException) as exc_info:
        validate_safe_path("")
    assert exc_info.value.status_code == 400
    assert "Path cannot be empty" in exc_info.value.detail

def test_validate_safe_path_resolve_exception():
    with patch("antigravity_api_archive_cov.Path") as mock_path_cls:
        mock_path_cls.side_effect = Exception("Resolution failed")
        with pytest.raises(HTTPException) as exc_info:
            validate_safe_path("any_string")
        assert exc_info.value.status_code == 400
        assert "Invalid path representation" in exc_info.value.detail

def test_validate_safe_path_relative_exception():
    # relative_to が ValueError を投げるケースをテストして 41-42 行目をカバー
    with pytest.raises(HTTPException) as exc_info:
        validate_safe_path(r"C:\Windows\System32\cmd.exe")
    assert exc_info.value.status_code == 400
    assert "Access denied" in exc_info.value.detail

# --- 2. Proper Noun Dictionary ---
def test_get_proper_nouns():
    with patch("antigravity_api_archive_cov.proper_noun_dict") as mock_dict:
        mock_entry = MagicMock()
        mock_entry.id = "noun_1"
        mock_entry.incorrect = "incorrect_val"
        mock_entry.correct = "correct_val"
        mock_entry.type = "word"
        mock_entry.context_hint = "hint"
        mock_entry.confirmed = True
        mock_entry.usage_count = 10
        mock_dict.get_all_entries.return_value = [mock_entry]

        response = client.get("/api/antigravity/proper-nouns")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        entry_data = data["entries"][0]
        assert entry_data["id"] == "noun_1"
        assert entry_data["incorrect"] == "incorrect_val"
        assert entry_data["correct"] == "correct_val"
        assert entry_data["type"] == "word"
        assert entry_data["context_hint"] == "hint"
        assert entry_data["confirmed"] is True
        assert entry_data["usage_count"] == 10

def test_add_proper_noun_empty_fields():
    # 空フィールドによる HTTPException の発生と raise の確認 (116, 125行目)
    response = client.post("/api/antigravity/proper-nouns", json={
        "incorrect": "   ",
        "correct": "some_value"
    })
    assert response.status_code == 400
    assert "cannot be empty" in response.json()["detail"]

def test_add_proper_noun_success_and_error():
    with patch("antigravity_api_archive_cov.proper_noun_dict") as mock_dict:
        mock_dict.add_entry.return_value = {"id": "noun_2", "incorrect": "X", "correct": "Y"}

        # 正常系
        response = client.post("/api/antigravity/proper-nouns", json={
            "incorrect": "X",
            "correct": "Y",
            "type": "word",
            "context_hint": "hint"
        })
        assert response.status_code == 200
        assert response.json()["entry"]["incorrect"] == "X"

        # 汎用例外 (Exception) の網羅テスト (TD-202 / 127行目)
        mock_dict.add_entry.side_effect = Exception("Dict insertion failure")
        response = client.post("/api/antigravity/proper-nouns", json={
            "incorrect": "X",
            "correct": "Y"
        })
        assert response.status_code == 400
        assert "Dict insertion failure" in response.json()["detail"]

# --- 3. process-srt ---
def test_process_srt_filename_empty():
    # filenameが空になるように "." をアップロード (136行目)
    response = client.post("/api/antigravity/process-srt", files={"file": (".", b"1\n...", "text/plain")})
    assert response.status_code == 400
    assert "Invalid filename" in response.json()["detail"]

def test_process_srt_invalid_extension():
    # 無効な拡張子による HTTPException スローおよび raise の確認 (138, 162行目)
    response = client.post("/api/antigravity/process-srt", files={"file": ("test.txt", b"1\n...", "text/plain")})
    assert response.status_code == 400
    assert "Only SRT files are allowed" in response.json()["detail"]

def test_process_srt_too_large():
    # ファイルサイズ制限 (148行目)
    large_content = b"a" * (10 * 1024 * 1024 + 100)
    response = client.post("/api/antigravity/process-srt", files={"file": ("test.srt", large_content, "text/plain")})
    assert response.status_code == 400
    assert "exceeds the 10MB limit" in response.json()["detail"]

def test_process_srt_success():
    # 正常系フローと一時ファイルの削除 (158-160行目)
    with patch("antigravity_api_archive_cov.AntigravityPipeline") as mock_pipeline_cls:
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_srt.return_value = {"success": True}

        # 一時ファイルの書き込み、unlinkをモック
        with patch("antigravity_api_archive_cov.open", mock_open()) as mock_file, \
             patch("antigravity_api_archive_cov.Path.unlink") as mock_unlink:
            response = client.post("/api/antigravity/process-srt", files={"file": ("test.srt", b"1\n...", "text/plain")})
            assert response.status_code == 200
            assert response.json()["success"] is True
            mock_unlink.assert_called_once()

def test_process_srt_exception_handling():
    with patch("antigravity_api_archive_cov.AntigravityPipeline") as mock_pipeline_cls:
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_srt.side_effect = Exception("SRT parsing crash")

        # ファイル書き込み、および unlink をモックして副作用を防ぐ
        with patch("antigravity_api_archive_cov.open", mock_open()) as mock_file, \
             patch("antigravity_api_archive_cov.Path.unlink") as mock_unlink:
            response = client.post("/api/antigravity/process-srt", files={"file": ("test.srt", b"1\n...", "text/plain")})
            assert response.status_code == 500
            assert "SRT parsing crash" in response.json()["detail"]

# --- 4. Telop Proposals ---
def test_get_telop_proposals_no_dir():
    with patch("antigravity_api_archive_cov.Path") as mock_path_cls:
        mock_inst = MagicMock()
        mock_path_cls.return_value = mock_inst
        mock_inst.exists.return_value = False

        response = client.get("/api/antigravity/telop-proposals")
        assert response.status_code == 200
        assert response.json() == {"proposals": []}

def test_get_telop_proposals_with_files():
    with patch("antigravity_api_archive_cov.Path") as mock_path_cls:
        mock_inst = MagicMock()
        mock_path_cls.return_value = mock_inst
        mock_inst.exists.return_value = True

        mock_file = MagicMock()
        mock_file.name = "demo_proposals.json"
        mock_inst.glob.return_value = [mock_file]

        mock_json_data = {
            "telop_candidates": [{"text": "Sample Telop"}],
            "scene_proposals": [{"scene": "Scene 1"}]
        }

        with patch("antigravity_api_archive_cov.open", mock_open(read_data=json.dumps(mock_json_data))):
            response = client.get("/api/antigravity/telop-proposals")
            assert response.status_code == 200
            proposals = response.json()["proposals"]
            assert len(proposals) == 1
            assert proposals[0]["file"] == "demo_proposals.json"
            assert proposals[0]["telop_candidates"][0]["text"] == "Sample Telop"

def test_approve_telop_scenarios():
    with patch("antigravity_api_archive_cov.record_approval") as mock_approve, \
         patch("antigravity_api_archive_cov.record_rejection") as mock_reject:

        # 承認 & 恒久化あり
        response = client.post("/api/antigravity/telop-proposals/prop123/approve", json={
            "action": "approve",
            "permanent": True
        })
        assert response.status_code == 200
        assert response.json()["action"] == "approved"
        mock_approve.assert_called_once_with("prop123", "telop")

        # 承認 & 恒久化なし
        mock_approve.reset_mock()
        response = client.post("/api/antigravity/telop-proposals/prop123/approve", json={
            "action": "approve",
            "permanent": False
        })
        assert response.status_code == 200
        mock_approve.assert_not_called()

        # 却下
        response = client.post("/api/antigravity/telop-proposals/prop123/approve", json={
            "action": "reject"
        })
        assert response.status_code == 200
        assert response.json()["action"] == "rejected"
        mock_reject.assert_called_once_with("prop123", "telop")

# --- 5. Assets ---
def test_get_assets():
    with patch("antigravity_api_archive_cov.asset_library") as mock_lib:
        mock_asset = MagicMock()
        mock_asset.id = "vid_1"
        mock_asset.category = "video"
        mock_asset.path = Path("path/to/vid1.mp4")
        mock_asset.labels = ["test"]
        mock_asset.style_tags = ["modern"]
        mock_lib.assets = [mock_asset]

        response = client.get("/api/antigravity/assets")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["assets"][0]["id"] == "vid_1"
        assert data["assets"][0]["path"] == "path\\to\\vid1.mp4" or data["assets"][0]["path"] == "path/to/vid1.mp4"
        mock_lib.scan.assert_called_once()

def test_scan_assets():
    with patch("antigravity_api_archive_cov.asset_library") as mock_lib:
        mock_lib.assets = [MagicMock(), MagicMock(), MagicMock()]
        response = client.post("/api/antigravity/assets/scan")
        assert response.status_code == 200
        assert response.json()["count"] == 3
        mock_lib.scan.assert_called_once()

def test_get_asset_sufficiency():
    with patch("antigravity_api_archive_cov.asset_library") as mock_lib:
        mock_lib.get_sufficiency_report.return_value = {"bgm": 1.0}
        response = client.get("/api/antigravity/assets/sufficiency")
        assert response.status_code == 200
        assert response.json() == {"bgm": 1.0}
        mock_lib.scan.assert_called_once()

# --- 6. Generation (Thumbnail / Opening / Ending) ---
def test_generate_thumbnail():
    # タイトル空チェック
    response = client.post("/api/antigravity/generate/thumbnail", json={"title": " "})
    assert response.status_code == 400
    assert "Title cannot be empty" in response.json()["detail"]

    # 正常系
    with patch("antigravity_api_archive_cov.generate_thumbnail") as mock_gen:
        mock_gen.return_value = {"thumbnail": "thumb.png"}
        response = client.post("/api/antigravity/generate/thumbnail", json={"title": "Title"})
        assert response.status_code == 200
        assert response.json()["thumbnail"] == "thumb.png"

        # 例外系
        mock_gen.side_effect = Exception("Thumbnail generation crash")
        response = client.post("/api/antigravity/generate/thumbnail", json={"title": "Title"})
        assert response.status_code == 500
        assert "Thumbnail generation crash" in response.json()["detail"]

def test_generate_opening():
    # チャンネル名空チェック
    response = client.post("/api/antigravity/generate/opening", json={"channel_name": " "})
    assert response.status_code == 400
    assert "Channel name cannot be empty" in response.json()["detail"]

    # 正常系
    with patch("antigravity_api_archive_cov.generate_opening") as mock_gen:
        mock_gen.return_value = {"video": "opening.mp4"}
        response = client.post("/api/antigravity/generate/opening", json={"channel_name": "A"})
        assert response.status_code == 200
        assert response.json()["video"] == "opening.mp4"

        # 例外系
        mock_gen.side_effect = Exception("Opening generation crash")
        response = client.post("/api/antigravity/generate/opening", json={"channel_name": "A"})
        assert response.status_code == 500
        assert "Opening generation crash" in response.json()["detail"]

def test_generate_ending():
    # チャンネル名空チェック
    response = client.post("/api/antigravity/generate/ending", json={"channel_name": " "})
    assert response.status_code == 400
    assert "Channel name cannot be empty" in response.json()["detail"]

    # 正常系
    with patch("antigravity_api_archive_cov.generate_ending") as mock_gen:
        mock_gen.return_value = {"video": "ending.mp4"}
        response = client.post("/api/antigravity/generate/ending", json={"channel_name": "A"})
        assert response.status_code == 200
        assert response.json()["video"] == "ending.mp4"

        # 例外系
        mock_gen.side_effect = Exception("Ending generation crash")
        response = client.post("/api/antigravity/generate/ending", json={"channel_name": "A"})
        assert response.status_code == 500
        assert "Ending generation crash" in response.json()["detail"]

# --- 7. Self Review ---
def test_get_self_review_status():
    with patch("antigravity_api_archive_cov.self_review_engine") as mock_engine:
        mock_engine.THRESHOLDS = {"quality": 90}
        response = client.get("/api/antigravity/self-review/status")
        assert response.status_code == 200
        assert response.json()["thresholds"]["quality"] == 90
        assert response.json()["enabled"] is True

def test_run_self_review():
    with patch("antigravity_api_archive_cov.self_review_engine") as mock_engine:
        mock_result = MagicMock()
        mock_result.passed = True
        mock_result.score.overall = 85.0
        mock_result.issues = ["Minor issue"]
        mock_engine.review.return_value = mock_result

        response = client.post("/api/antigravity/self-review/check", json={"content": "text"})
        assert response.status_code == 200
        assert response.json()["passed"] is True
        assert response.json()["score"] == 85.0
        assert response.json()["issues"] == ["Minor issue"]

        # 汎用例外 (Exception) の網羅テスト (307行目)
        mock_engine.review.side_effect = Exception("Review engine crash")
        response = client.post("/api/antigravity/self-review/check", json={})
        assert response.status_code == 500
        assert "Review engine crash" in response.json()["detail"]

        # HTTPException を投げるモックで 305行目をカバー
        mock_engine.review.side_effect = HTTPException(status_code=400, detail="Review HTTP exception")
        response = client.post("/api/antigravity/self-review/check", json={})
        assert response.status_code == 400
        assert "Review HTTP exception" in response.json()["detail"]

# --- 8. Learning Loop ---
def test_get_pending_proposals():
    with patch("antigravity_api_archive_cov.learning_loop") as mock_loop:
        mock_loop.get_pending_proposals.return_value = [{"proposal_id": "prop_1"}]
        response = client.get("/api/antigravity/learning/pending")
        assert response.status_code == 200
        assert response.json()["count"] == 1
        assert response.json()["proposals"][0]["proposal_id"] == "prop_1"

def test_approve_learning():
    with patch("antigravity_api_archive_cov.record_approval") as mock_approve, \
         patch("antigravity_api_archive_cov.record_rejection") as mock_reject:

        # 承認
        response = client.post("/api/antigravity/learning/approve", json={
            "proposal_id": "prop_1",
            "action": "approve",
            "permanent": True
        })
        assert response.status_code == 200
        assert response.json()["action"] == "approved"
        mock_approve.assert_called_once_with("prop_1", permanent=True)

        # 却下
        response = client.post("/api/antigravity/learning/approve", json={
            "proposal_id": "prop_2",
            "action": "reject"
        })
        assert response.status_code == 200
        assert response.json()["action"] == "rejected"
        mock_reject.assert_called_once_with("prop_2")

def test_get_preferences():
    with patch("antigravity_api_archive_cov.learning_loop") as mock_loop:
        mock_loop.get_preferences.return_value = {"style": "minimal"}
        response = client.get("/api/antigravity/learning/preferences")
        assert response.status_code == 200
        assert response.json() == {"style": "minimal"}

# --- 9. Video Editor & Status ---
def test_get_editor_status():
    with patch("antigravity_api_archive_cov.check_ffmpeg") as mock_check, \
         patch("antigravity_api_archive_cov.video_editor") as mock_editor:
        mock_check.return_value = True
        mock_editor.output_dir = Path("path/to/output")

        response = client.get("/api/antigravity/editor/status")
        assert response.status_code == 200
        assert response.json()["ffmpeg_available"] is True
        assert response.json()["output_dir"] == "path\\to\\output" or response.json()["output_dir"] == "path/to/output"

def test_create_final_video():
    # validate_safe_path をバイパスするためモック
    with patch("antigravity_api_archive_cov.validate_safe_path") as mock_validate, \
         patch("antigravity_api_archive_cov.video_editor") as mock_editor:

        mock_validate.return_value = Path("safe_video.mp4")

        # 出力ファイル名が空
        response = client.post("/api/antigravity/editor/create-final", json={
            "main_video": "main.mp4",
            "output_name": ""
        })
        assert response.status_code == 400
        assert "Invalid output name" in response.json()["detail"]

        # 正常系
        mock_editor.create_final_video.return_value = {"video": "final.mp4"}
        response = client.post("/api/antigravity/editor/create-final", json={
            "main_video": "main.mp4",
            "output_name": "final.mp4"
        })
        assert response.status_code == 200
        assert response.json()["video"] == "final.mp4"

        # 例外系
        mock_editor.create_final_video.side_effect = Exception("FFmpeg compile error")
        response = client.post("/api/antigravity/editor/create-final", json={
            "main_video": "main.mp4",
            "output_name": "final.mp4"
        })
        assert response.status_code == 500
        assert "FFmpeg compile error" in response.json()["detail"]

def test_get_pipeline_status():
    with patch("antigravity_api_archive_cov.AntigravityPipeline") as mock_pipeline_cls, \
         patch("antigravity_api_archive_cov.check_ffmpeg") as mock_ffmpeg:
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.get_pipeline_status.return_value = {
            "proper_noun_entries": 10,
            "pending_confirmations": 2,
            "available_assets": 5,
            "pending_proposals": 1
        }
        mock_ffmpeg.return_value = True

        response = client.get("/api/antigravity/status")
        assert response.status_code == 200
        data = response.json()
        assert data["proper_noun_entries"] == 10
        assert data["pending_confirmations"] == 2
        assert data["available_assets"] == 5
        assert data["pending_proposals"] == 1
        assert data["ffmpeg_available"] is True
