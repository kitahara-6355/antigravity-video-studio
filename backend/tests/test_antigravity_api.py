import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, mock_open, AsyncMock
from pathlib import Path
import sys
import json

# パスを通す
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from antigravity_api import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

def test_get_proper_nouns():
    with patch("antigravity_api.proper_noun_dict") as mock_dict:
        mock_dict.get_all_entries.return_value = [
            {
                "id": "entry_1",
                "incorrect": "inc",
                "correct": "corr",
                "type": "word",
                "context_hint": "hint",
                "confirmed": True,
                "usage_count": 5
            }
        ]
        
        response = client.get("/api/antigravity/proper-nouns")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["entries"][0]["id"] == "entry_1"
        assert data["entries"][0]["incorrect"] == "inc"
        assert data["entries"][0]["correct"] == "corr"
        assert data["entries"][0]["type"] == "word"
        assert data["entries"][0]["context_hint"] == "hint"
        assert data["entries"][0]["confirmed"] is True
        assert data["entries"][0]["usage_count"] == 5

def test_add_proper_noun():
    # 正常系
    with patch("antigravity_api.proper_noun_dict") as mock_dict:
        mock_dict.add_entry.return_value = {"id": "noun_2", "incorrect": "X", "correct": "Y", "type": "word", "context_hint": ""}
        response = client.post("/api/antigravity/proper-nouns", json={
            "incorrect": "X",
            "correct": "Y",
            "type": "word",
            "context_hint": ""
        })
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["entry"]["id"] == "noun_2"
        
    # HTTPException を投げるケース
    with patch("antigravity_api.proper_noun_dict") as mock_dict:
        mock_dict.add_entry.side_effect = HTTPException(status_code=400, detail="Invalid fields")
        response = client.post("/api/antigravity/proper-nouns", json={
            "incorrect": "X",
            "correct": "Y"
        })
        assert response.status_code == 400
        assert "Invalid fields" in response.json()["detail"]
        
    # ValueError を投げるケース
    with patch("antigravity_api.proper_noun_dict") as mock_dict:
        mock_dict.add_entry.side_effect = ValueError("Value error")
        response = client.post("/api/antigravity/proper-nouns", json={
            "incorrect": "X",
            "correct": "Y"
        })
        assert response.status_code == 400
        assert "Value error" in response.json()["detail"]

def test_process_srt():
    # 正常系
    mock_path_inst = MagicMock()
    mock_path_inst.exists.return_value = True
    mock_path_inst.__truediv__.return_value = mock_path_inst
    
    with patch("antigravity_api.Path", return_value=mock_path_inst), \
         patch("antigravity_api._writable_path", return_value=mock_path_inst), \
         patch("antigravity_api.AntigravityPipeline") as mock_pipeline_cls:
        
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_srt.return_value = {"success": True}
        
        # AsyncMock to avoid Starlette's run_in_threadpool context for read()
        with patch("starlette.datastructures.UploadFile.read", new_callable=AsyncMock, return_value=b"1" + bytes([10]) + b"..."), \
             patch("antigravity_api.open", mock_open()) as mock_file:
            response = client.post("/api/antigravity/process-srt", files={"file": ("test.srt", b"1" + bytes([10]) + b"...", "text/plain")})
            assert response.status_code == 200
            assert response.json()["success"] is True
            mock_path_inst.unlink.assert_called_once()

    # HTTPException を投げるケース
    mock_path_inst = MagicMock()
    mock_path_inst.exists.return_value = True
    mock_path_inst.__truediv__.return_value = mock_path_inst
    
    with patch("antigravity_api.Path", return_value=mock_path_inst), \
         patch("antigravity_api._writable_path", return_value=mock_path_inst), \
         patch("antigravity_api.AntigravityPipeline") as mock_pipeline_cls:
        
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_srt.side_effect = HTTPException(status_code=400, detail="HTTP error")
        
        with patch("starlette.datastructures.UploadFile.read", new_callable=AsyncMock, return_value=b"1" + bytes([10]) + b"..."), \
             patch("antigravity_api.open", mock_open()) as mock_file:
            response = client.post("/api/antigravity/process-srt", files={"file": ("test.srt", b"1" + bytes([10]) + b"...", "text/plain")})
            assert response.status_code == 400
            assert "HTTP error" in response.json()["detail"]
            mock_path_inst.unlink.assert_called_once()

    # ValueError などの汎用例外を投げるケース
    mock_path_inst = MagicMock()
    mock_path_inst.exists.return_value = True
    mock_path_inst.__truediv__.return_value = mock_path_inst
    
    with patch("antigravity_api.Path", return_value=mock_path_inst), \
         patch("antigravity_api._writable_path", return_value=mock_path_inst), \
         patch("antigravity_api.AntigravityPipeline") as mock_pipeline_cls:
        
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_srt.side_effect = ValueError("Process error")
        
        with patch("starlette.datastructures.UploadFile.read", new_callable=AsyncMock, return_value=b"1" + bytes([10]) + b"..."), \
             patch("antigravity_api.open", mock_open()) as mock_file:
            response = client.post("/api/antigravity/process-srt", files={"file": ("test.srt", b"1" + bytes([10]) + b"...", "text/plain")})
            assert response.status_code == 500
            assert "Process error" in response.json()["detail"]
            mock_path_inst.unlink.assert_called_once()

def test_process_srt_no_file_exists():
    mock_path_inst = MagicMock()
    mock_path_inst.exists.return_value = False
    mock_path_inst.__truediv__.return_value = mock_path_inst
    
    with patch("antigravity_api.Path", return_value=mock_path_inst), \
         patch("antigravity_api._writable_path", return_value=mock_path_inst), \
         patch("antigravity_api.AntigravityPipeline") as mock_pipeline_cls:
        
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_srt.return_value = {"success": True}
        
        with patch("starlette.datastructures.UploadFile.read", new_callable=AsyncMock, return_value=b"1" + bytes([10]) + b"..."), \
             patch("antigravity_api.open", mock_open()) as mock_file:
            response = client.post("/api/antigravity/process-srt", files={"file": ("test.srt", b"1" + bytes([10]) + b"...", "text/plain")})
            assert response.status_code == 200
            mock_path_inst.unlink.assert_not_called()

def test_process_srt_strips_directories_from_upload_name(tmp_path, monkeypatch):
    """アップロード名の `../` で temp/ の外へ書けない。

    filename は multipart ヘッダ由来でクライアントが自由に決められる。
    上の各ケースのように `antigravity_api.Path` をモックすると連結の実装ごと
    隠れてしまうので、ここは書き込み先だけを一時ディレクトリへ向けて
    実物のパス解決を通す。
    """
    monkeypatch.setenv("ANTIGRAVITY_WRITABLE_ROOT", str(tmp_path))

    with patch("antigravity_api.AntigravityPipeline") as mock_pipeline_cls:
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.process_srt.return_value = {"success": True}

        response = client.post(
            "/api/antigravity/process-srt",
            files={"file": ("../../evil.srt", b"1" + bytes([10]) + b"...", "text/plain")}
        )

    assert response.status_code == 200
    used_path = Path(mock_pipeline.process_srt.call_args[0][0])
    assert used_path.parent == tmp_path / "temp"
    assert used_path.name == "evil.srt"
    # 抜けた先に書かれていないこと（finally で unlink されるのは temp/ 側だけ）
    assert not (tmp_path.parent / "evil.srt").exists()

def test_process_srt_rejects_traversal_only_name(tmp_path, monkeypatch):
    """ディレクトリ部分しか無い名前は 400 で弾く。"""
    monkeypatch.setenv("ANTIGRAVITY_WRITABLE_ROOT", str(tmp_path))

    with patch("antigravity_api.AntigravityPipeline") as mock_pipeline_cls:
        response = client.post(
            "/api/antigravity/process-srt",
            files={"file": ("..", b"1" + bytes([10]) + b"...", "text/plain")}
        )
        mock_pipeline_cls.assert_not_called()

    assert response.status_code == 400

def test_get_telop_proposals():
    # 提案ディレクトリが存在しない場合
    with patch("antigravity_api.Path.exists", return_value=False):
        response = client.get("/api/antigravity/telop-proposals")
        assert response.status_code == 200
        assert response.json() == {"proposals": []}

    # 提案ディレクトリが存在する場合
    with patch("antigravity_api.Path.exists", return_value=True), \
         patch("antigravity_api.Path.glob") as mock_glob:
        mock_file = MagicMock()
        mock_file.name = "demo_proposals.json"
        mock_glob.return_value = [mock_file]
        
        mock_data = {
            "telop_candidates": [{"text": "candidate"}],
            "scene_proposals": [{"scene": "scene"}]
        }
        with patch("antigravity_api.open", mock_open(read_data=json.dumps(mock_data))):
            response = client.get("/api/antigravity/telop-proposals")
            assert response.status_code == 200
            proposals = response.json()["proposals"]
            assert len(proposals) == 1
            assert proposals[0]["file"] == "demo_proposals.json"
            assert proposals[0]["telop_candidates"][0]["text"] == "candidate"

def test_approve_telop():
    with patch("antigravity_api.record_approval") as mock_approve, \
         patch("antigravity_api.record_rejection") as mock_reject:
        # approve & permanent=True
        response = client.post("/api/antigravity/telop-proposals/prop123/approve", json={
            "action": "approve",
            "permanent": True
        })
        assert response.status_code == 200
        assert response.json()["action"] == "approved"
        mock_approve.assert_called_once_with({"proposal_id": "prop123", "type": "telop"}, tags=["telop"], permanent=True)
        
        # approve & permanent=False
        mock_approve.reset_mock()
        response = client.post("/api/antigravity/telop-proposals/prop123/approve", json={
            "action": "approve",
            "permanent": False
        })
        assert response.status_code == 200
        assert response.json()["action"] == "approved"
        mock_approve.assert_not_called()
        
        # reject
        response = client.post("/api/antigravity/telop-proposals/prop123/approve", json={
            "action": "reject"
        })
        assert response.status_code == 200
        assert response.json()["action"] == "rejected"
        mock_reject.assert_called_once_with({"proposal_id": "prop123", "type": "telop"}, reason="rejected", tags=["telop"])

def test_assets():
    with patch("antigravity_api.asset_library") as mock_lib:
        mock_asset = MagicMock()
        mock_asset.id = "asset_1"
        mock_asset.category = "video"
        mock_asset.path = Path("path/to/asset.mp4")
        mock_asset.labels = ["test"]
        mock_asset.style_tags = ["tag"]
        mock_lib.assets = [mock_asset]
        
        # get_assets
        response = client.get("/api/antigravity/assets")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert "path/to/asset.mp4" in data["assets"][0]["path"].replace("\\", "/")
        mock_lib.scan.assert_called_once()
        
        # scan_assets
        mock_lib.scan.reset_mock()
        response = client.post("/api/antigravity/assets/scan")
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["count"] == 1
        mock_lib.scan.assert_called_once()
        
        # get_asset_sufficiency
        mock_lib.get_sufficiency_report.return_value = {"bgm": 1.0}
        response = client.get("/api/antigravity/assets/sufficiency")
        assert response.status_code == 200
        assert response.json() == {"bgm": 1.0}

def test_generations():
    # thumbnail normal
    with patch("antigravity_api.generate_thumbnail", return_value={"thumbnail": "thumb.png"}) as mock_gen:
        response = client.post("/api/antigravity/generate/thumbnail", json={"title": "test", "context": {}})
        assert response.status_code == 200
        assert response.json()["thumbnail"] == "thumb.png"
        
    # thumbnail HTTPException
    with patch("antigravity_api.generate_thumbnail", side_effect=HTTPException(status_code=400, detail="HTTP error")):
        response = client.post("/api/antigravity/generate/thumbnail", json={"title": "test"})
        assert response.status_code == 400
        assert "HTTP error" in response.json()["detail"]

    # thumbnail ValueError
    with patch("antigravity_api.generate_thumbnail", side_effect=ValueError("Gen thumb error")):
        response = client.post("/api/antigravity/generate/thumbnail", json={"title": "test"})
        assert response.status_code == 500
        assert "Gen thumb error" in response.json()["detail"]

    # opening normal
    with patch("antigravity_api.generate_opening", return_value={"video": "opening.mp4"}) as mock_gen:
        response = client.post("/api/antigravity/generate/opening", json={"channel_name": "美丽"})
        assert response.status_code == 200
        assert response.json()["video"] == "opening.mp4"

    # opening HTTPException
    with patch("antigravity_api.generate_opening", side_effect=HTTPException(status_code=400, detail="HTTP error")):
        response = client.post("/api/antigravity/generate/opening", json={"channel_name": "美丽"})
        assert response.status_code == 400

    # opening ValueError
    with patch("antigravity_api.generate_opening", side_effect=ValueError("Gen opening error")):
        response = client.post("/api/antigravity/generate/opening", json={"channel_name": "美丽"})
        assert response.status_code == 500
        assert "Gen opening error" in response.json()["detail"]

    # ending normal
    with patch("antigravity_api.generate_ending", return_value={"video": "ending.mp4"}) as mock_gen:
        response = client.post("/api/antigravity/generate/ending", json={"channel_name": "美丽"})
        assert response.status_code == 200
        assert response.json()["video"] == "ending.mp4"

    # ending HTTPException
    with patch("antigravity_api.generate_ending", side_effect=HTTPException(status_code=400, detail="HTTP error")):
        response = client.post("/api/antigravity/generate/ending", json={"channel_name": "美丽"})
        assert response.status_code == 400

    # ending ValueError
    with patch("antigravity_api.generate_ending", side_effect=ValueError("Gen ending error")):
        response = client.post("/api/antigravity/generate/ending", json={"channel_name": "美丽"})
        assert response.status_code == 500
        assert "Gen ending error" in response.json()["detail"]

def test_self_review():
    # status
    with patch("antigravity_api.self_review_engine") as mock_engine:
        mock_engine.THRESHOLDS = {"quality": 80}
        response = client.get("/api/antigravity/self-review/status")
        assert response.status_code == 200
        assert response.json()["thresholds"]["quality"] == 80
        
    # check normal
    with patch("antigravity_api.self_review_engine") as mock_engine:
        mock_result = MagicMock()
        mock_result.passed = True
        mock_result.score.overall = 90.0
        mock_result.issues = ["none"]
        mock_engine.review.return_value = mock_result
        
        response = client.post("/api/antigravity/self-review/check", json={"content": "text", "type": "text"})
        assert response.status_code == 200
        assert response.json()["passed"] is True
        
    # check HTTPException
    with patch("antigravity_api.self_review_engine") as mock_engine:
        mock_engine.review.side_effect = HTTPException(status_code=400, detail="HTTP error")
        response = client.post("/api/antigravity/self-review/check", json={"content": "text"})
        assert response.status_code == 400

    # check ValueError
    with patch("antigravity_api.self_review_engine") as mock_engine:
        mock_engine.review.side_effect = ValueError("Review error")
        response = client.post("/api/antigravity/self-review/check", json={})
        assert response.status_code == 500
        assert "Review error" in response.json()["detail"]

def test_learning():
    # pending
    with patch("antigravity_api.learning_loop") as mock_loop:
        mock_loop.get_pending_proposals.return_value = [{"proposal_id": "p1"}]
        response = client.get("/api/antigravity/learning/pending")
        assert response.status_code == 200
        assert response.json()["count"] == 1
        
    # approve learning
    with patch("antigravity_api.record_approval") as mock_approve, \
         patch("antigravity_api.record_rejection") as mock_reject:
        # approve
        response = client.post("/api/antigravity/learning/approve", json={"proposal_id": "p1", "action": "approve", "permanent": True})
        assert response.status_code == 200
        mock_approve.assert_called_once_with({"proposal_id": "p1", "type": "learning"}, permanent=True)
        
        # reject
        response = client.post("/api/antigravity/learning/approve", json={"proposal_id": "p1", "action": "reject"})
        assert response.status_code == 200
        mock_reject.assert_called_once_with({"proposal_id": "p1", "type": "learning"})
        
    # preferences
    with patch("antigravity_api.learning_loop") as mock_loop:
        mock_loop.get_preferences.return_value = {"pref": "value"}
        response = client.get("/api/antigravity/learning/preferences")
        assert response.status_code == 200
        assert response.json()["pref"] == "value"

def test_editor():
    # status
    with patch("antigravity_api.check_ffmpeg", return_value=True), \
         patch("antigravity_api.video_editor") as mock_editor:
        mock_editor.output_dir = Path("out")
        response = client.get("/api/antigravity/editor/status")
        assert response.status_code == 200
        assert response.json()["ffmpeg_available"] is True
        
    # create final video normal
    with patch("antigravity_api.video_editor") as mock_editor:
        mock_editor.create_final_video.return_value = {"success": True}
        response = client.post("/api/antigravity/editor/create-final", json={
            "main_video": "main.mp4",
            "opening": "open.mp4",
            "ending": "end.mp4",
            "telops": [],
            "output_name": "final.mp4"
        })
        assert response.status_code == 200
        assert response.json()["success"] is True

    # create final video HTTPException
    with patch("antigravity_api.video_editor") as mock_editor:
        mock_editor.create_final_video.side_effect = HTTPException(status_code=400, detail="HTTP error")
        response = client.post("/api/antigravity/editor/create-final", json={
            "main_video": "main.mp4"
        })
        assert response.status_code == 400

    # create final video ValueError
    with patch("antigravity_api.video_editor") as mock_editor:
        mock_editor.create_final_video.side_effect = ValueError("Editor error")
        response = client.post("/api/antigravity/editor/create-final", json={
            "main_video": "main.mp4"
        })
        assert response.status_code == 500
        assert "Editor error" in response.json()["detail"]

def test_pipeline_status():
    with patch("antigravity_api.AntigravityPipeline") as mock_pipeline_cls, \
         patch("antigravity_api.check_ffmpeg", return_value=True):
        mock_pipeline = mock_pipeline_cls.return_value
        mock_pipeline.get_pipeline_status.return_value = {
            "proper_noun_entries": 1,
            "pending_confirmations": 2,
            "available_assets": 3,
            "pending_proposals": 4
        }
        
        response = client.get("/api/antigravity/status")
        assert response.status_code == 200
        data = response.json()
        assert data["proper_noun_entries"] == 1
        assert data["pending_confirmations"] == 2
        assert data["available_assets"] == 3
        assert data["pending_proposals"] == 4
        assert data["ffmpeg_available"] is True


def test_add_proper_noun_type_error():
    # TypeError などのその他の例外を投げるケース
    with patch("antigravity_api.proper_noun_dict") as mock_dict:
        mock_dict.add_entry.side_effect = TypeError("Type mismatch error")
        response = client.post("/api/antigravity/proper-nouns", json={
            "incorrect": "X",
            "correct": "Y",
            "type": "word"
        })
        assert response.status_code == 400
        assert "Type mismatch error" in response.json()["detail"]

def test_process_srt_io_error():
    # UploadFile読み込み中に OSError などのI/O例外が発生するケース
    with patch("antigravity_api.AntigravityPipeline") as mock_pipeline_cls:
        with patch("antigravity_api.open", mock_open()) as mock_file, \
             patch("antigravity_api.Path.exists", return_value=True), \
             patch("antigravity_api.Path.unlink") as mock_unlink:
            
            # FastAPIのUploadFile.readで例外が発生するようモック
            with patch("starlette.datastructures.UploadFile.read", side_effect=OSError("Read failure")):
                response = client.post("/api/antigravity/process-srt", files={"file": ("test.srt", b"1\n...", "text/plain")})
                assert response.status_code == 500
                assert "Read failure" in response.json()["detail"]
                mock_unlink.assert_called_once()

def test_approve_telop_invalid_action():
    # 無効なアクションが渡された場合に reject として処理される挙動のテスト
    with patch("antigravity_api.record_approval") as mock_approve,          patch("antigravity_api.record_rejection") as mock_reject:
        response = client.post("/api/antigravity/telop-proposals/prop123/approve", json={
            "action": "invalid_action_value",
            "permanent": False
        })
        assert response.status_code == 200
        assert response.json()["action"] == "rejected"
        mock_reject.assert_called_once_with({"proposal_id": "prop123", "type": "telop"}, reason="rejected", tags=["telop"])
        mock_approve.assert_not_called()

def test_create_final_video_type_error():
    # TypeError や OSError を投げるケース
    with patch("antigravity_api.video_editor") as mock_editor:
        mock_editor.create_final_video.side_effect = TypeError("Invalid path argument type")
        response = client.post("/api/antigravity/editor/create-final", json={
            "main_video": "main.mp4",
            "opening": None,
            "ending": None,
            "telops": [],
            "output_name": "final.mp4"
        })
        assert response.status_code == 500
        assert "Invalid path argument type" in response.json()["detail"]


def test_add_proper_noun_other_errors():
    # KeyError, AttributeError, OSError, RuntimeError などを投げるケース
    with patch("antigravity_api.proper_noun_dict") as mock_dict:
        mock_dict.add_entry.side_effect = KeyError("Key mismatch error")
        response = client.post("/api/antigravity/proper-nouns", json={
            "incorrect": "X",
            "correct": "Y",
            "type": "word"
        })
        assert response.status_code == 400
        assert "Key mismatch error" in response.json()["detail"]

        mock_dict.add_entry.side_effect = AttributeError("Attribute access error")
        response = client.post("/api/antigravity/proper-nouns", json={
            "incorrect": "X",
            "correct": "Y"
        })
        assert response.status_code == 400
        assert "Attribute access error" in response.json()["detail"]

        mock_dict.add_entry.side_effect = RuntimeError("Runtime error")
        response = client.post("/api/antigravity/proper-nouns", json={
            "incorrect": "X",
            "correct": "Y"
        })
        assert response.status_code == 400
        assert "Runtime error" in response.json()["detail"]


def test_generations_errors():
    # opening generate / ending generate のエラーケース
    with patch("antigravity_api.generate_opening", side_effect=KeyError("Key error in opening")):
        response = client.post("/api/antigravity/generate/opening", json={"channel_name": "美丽"})
        assert response.status_code == 500
        assert "Key error in opening" in response.json()["detail"]

    with patch("antigravity_api.generate_ending", side_effect=RuntimeError("Runtime error in ending")):
        response = client.post("/api/antigravity/generate/ending", json={"channel_name": "美丽"})
        assert response.status_code == 500
        assert "Runtime error in ending" in response.json()["detail"]


def test_learning_permanent_false():
    # permanent=False での学習承認
    with patch("antigravity_api.record_approval") as mock_approve:
        response = client.post("/api/antigravity/learning/approve", json={"proposal_id": "p1", "action": "approve", "permanent": False})
        assert response.status_code == 200
        mock_approve.assert_called_once_with({"proposal_id": "p1", "type": "learning"}, permanent=False)


def test_self_review_other_errors():
    # self review で KeyError などの例外が発生した場合
    with patch("antigravity_api.self_review_engine") as mock_engine:
        mock_engine.review.side_effect = KeyError("Key error in review")
        response = client.post("/api/antigravity/self-review/check", json={"content": "text"})
        assert response.status_code == 500
        assert "Key error in review" in response.json()["detail"]
