# -*- coding: utf-8 -*-
import pytest
import os
import sys
import time
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

# 他の未インポートな依存モジュールのダミー登録
sys.modules["branding_manager"] = MagicMock()
sys.modules["project_archiver"] = MagicMock()
sys.modules["video_processor"] = MagicMock()
sys.modules["google.adk"] = MagicMock()
sys.modules["mcp"] = MagicMock()

# パス設定
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from routers.render import router, _render_jobs, _video_tasks, _render_settings

app = FastAPI()
app.include_router(router)
client = TestClient(app)

@pytest.fixture(autouse=True)
def clean_tasks_and_jobs():
    _render_jobs.clear()
    _video_tasks.clear()
    _render_settings.update({
        "encoder": "auto",
        "bgm_volume": 50.0,
        "bgm_ducking": True,
        "lufs_target": -16.0,
        "logo_enabled": True,
        "logo_position": "top-right",
        "logo_opacity": 0.8,
        "logo_height": 50,
        "subtitle_enabled": True,
        "subtitle_font": "Noto Sans JP",
        "subtitle_size": 24,
    })
    yield

def test_render_health():
    res = client.get("/api/render/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

def test_detect_gpu_success():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="GeForce RTX 4090")
        res = client.get("/api/render/gpu-detect")
        assert res.status_code == 200
        assert res.json()["gpu_available"] is True
        assert res.json()["gpu_name"] == "GeForce RTX 4090"
        assert res.json()["recommended_encoder"] == "nvenc"

def test_detect_gpu_fail_or_timeout():
    with patch("subprocess.run", side_effect=FileNotFoundError("nvidia-smi not found")):
        res = client.get("/api/render/gpu-detect")
        assert res.status_code == 200
        assert res.json()["gpu_available"] is False
    
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["nvidia-smi"], timeout=5)):
        res = client.get("/api/render/gpu-detect")
        assert res.status_code == 200
        assert res.json()["gpu_available"] is False

def test_start_render_quality_blocked():
    with patch("routers.render._get_quality_score", return_value=85):
        res = client.post("/api/render/start", json={"force_render": False})
        assert res.status_code == 200
        assert res.json()["success"] is False
        assert res.json()["error"] == "quality_block"

def test_start_render_nvenc_success():
    with patch("routers.render._get_quality_score", return_value=95), \
         patch("routers.render.detect_gpu") as mock_detect:
        
        mock_detect.return_value = {"gpu_available": True, "recommended_encoder": "nvenc"}
        res = client.post("/api/render/start", json={"encoder": "nvenc"})
        assert res.status_code == 200
        assert res.json()["success"] is True
        assert res.json()["encoder"] == "nvenc"
        assert res.json()["gpu_fallback"] is False

def test_start_render_nvenc_fallback():
    with patch("routers.render._get_quality_score", return_value=95), \
         patch("routers.render.detect_gpu") as mock_detect:
        
        mock_detect.return_value = {"gpu_available": False, "recommended_encoder": "libx264"}
        res = client.post("/api/render/start", json={"encoder": "nvenc"})
        assert res.status_code == 200
        assert res.json()["success"] is True
        assert res.json()["encoder"] == "libx264"
        assert res.json()["gpu_fallback"] is True

def test_get_render_status_not_found():
    res = client.get("/api/render/status/nonexistent")
    assert res.status_code == 200
    assert "error" in res.json()

def test_get_render_status_timeout():
    job_id = "testjob"
    _render_jobs[job_id] = {
        "started_at": time.time() - 2000,
        "status": "rendering",
        "progress": 50,
        "current_stage": "encoding",
        "stages": {},
        "encoder": "libx264",
        "gpu_fallback": False,
    }
    res = client.get(f"/api/render/status/{job_id}")
    assert res.status_code == 200
    assert res.json()["status"] == "timeout"
    assert "1800秒超過" in res.json()["message"]

def test_complete_render():
    job_id = "testjob"
    _render_jobs[job_id] = {
        "status": "rendering",
        "progress": 50,
        "completed_at": None,
        "current_stage": "encoding",
        "stages": {"encoding": {}},
    }
    res = client.post(f"/api/render/complete/{job_id}")
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert _render_jobs[job_id]["status"] == "completed"

def test_complete_render_not_found():
    res = client.post("/api/render/complete/nonexistent")
    assert res.status_code == 200
    assert "error" in res.json()

def test_download_render():
    job_id = "testjob"
    _render_jobs[job_id] = {
        "status": "completed",
        "output_file": {"path": "/output/render_testjob.mp4"}
    }
    res = client.get(f"/api/render/download/{job_id}")
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert res.json()["download_url"] == "/output/render_testjob.mp4"

def test_download_render_not_completed_or_missing():
    res = client.get("/api/render/download/nonexistent")
    assert "error" in res.json()

    _render_jobs["testjob"] = {"status": "rendering"}
    res2 = client.get("/api/render/download/testjob")
    assert "error" in res2.json()

def test_get_and_post_settings():
    res = client.get("/api/render/settings")
    assert res.status_code == 200
    assert res.json()["settings"]["bgm_volume"] == 50.0
    
    res2 = client.post("/api/render/settings", json={"bgm_volume": 80.0, "lufs_target": -14.0})
    assert res2.status_code == 200
    assert res2.json()["settings"]["bgm_volume"] == 80.0
    assert _render_settings["bgm_volume"] == 80.0

def test_force_render():
    job_id = "testjob"
    _render_jobs[job_id] = {"status": "rendering", "force_render": False}
    
    res = client.post(f"/api/render/force/{job_id}")
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert _render_jobs[job_id]["force_render"] is True
    
    with patch("routers.render.start_render") as mock_start:
        mock_start.return_value = {"success": True}
        client.post("/api/render/force/nonexistent")
        mock_start.assert_called_once()

def test_trigger_render():
    res = client.post("/api/render", json={"mode": "fast", "style": "cinematic"})
    assert res.status_code == 200
    assert res.json()["status"] == "completed"

def test_start_video_processing():
    res = client.post("/api/video/process", json={
        "video_paths": ["v1.mp4"], "mood": "warm", "output_name": "final_vid"
    })
    assert res.status_code == 200
    task_id = res.json()["task_id"]
    assert task_id in _video_tasks
    
    res_status = client.get(f"/api/video/status/{task_id}")
    assert res_status.status_code == 200
    assert res_status.json()["status"] == "processing"

def test_video_status_not_found():
    res = client.get("/api/video/status/nonexistent")
    assert "error" in res.json()

def test_get_video_preview(tmp_path):
    task_id = "task123"
    
    _video_tasks[task_id] = {"status": "processing"}
    res1 = client.get(f"/api/video/preview/{task_id}")
    assert "error" in res1.json()
    
    out_file = tmp_path / "out.mp4"
    out_file.write_text("dummy", encoding="utf-8")
    _video_tasks[task_id] = {"status": "done", "output_path": str(out_file)}
    res2 = client.get(f"/api/video/preview/{task_id}")
    assert res2.status_code == 200

def test_get_video_preview_not_found():
    res = client.get("/api/video/preview/nonexistent")
    assert "error" in res.json()

def test_download_processed_video(tmp_path):
    task_id = "task123"
    
    _video_tasks[task_id] = {"status": "processing"}
    res1 = client.get(f"/api/video/download/{task_id}")
    assert "error" in res1.json()
    
    out_file = tmp_path / "out.mp4"
    out_file.write_text("dummy", encoding="utf-8")
    _video_tasks[task_id] = {"status": "done", "output_path": str(out_file)}
    res2 = client.get(f"/api/video/download/{task_id}")
    assert res2.status_code == 200

def test_download_processed_video_not_found():
    res = client.get("/api/video/download/nonexistent")
    assert "error" in res.json()

def test_draft_endpoints():
    res1 = client.post("/api/draft/create", json={"input_path": "in.mp4", "quality": "low"})
    assert res1.status_code == 200
    
    res2 = client.post("/api/prefinal/create", json={"draft_paths": ["d1.mp4"]})
    assert res2.status_code == 200
    
    res3 = client.post("/api/final/create", json={"prefinal_path": "p.mp4"})
    assert res3.status_code == 200
    
    res4 = client.get("/api/draft/stats")
    assert res4.status_code == 200

def test_list_available_videos(tmp_path):
    with patch("routers.render.Path.exists", return_value=True), \
         patch("routers.render.Path.rglob") as mock_rglob:
         
        mock_file = MagicMock()
        mock_file.name = "video1.mp4"
        mock_file.stat.return_value.st_size = 1024 * 1024 * 10
        mock_rglob.return_value = [mock_file]
        
        res = client.get("/api/available-videos")
        assert res.status_code == 200
        assert len(res.json()["videos"]) == 1
        assert res.json()["videos"][0]["name"] == "video1.mp4"


def test_start_render_未計測なら点を名乗らない():
    """**測っていないのに 95 点で通さない**（R1.5-C4・gate-verifier 8周目の指摘）。

    ここは以前「`_get_quality_score` を mock しない場合、デフォルトの 95 が返るため、
    ブロックされずに開始するはず」と書いてあり、**testpaths 内のこのテストが
    偽の success を緑で固定していた。**95 は直書きの定数で、
    そのせいで `if quality_score < 90` の品質ブロック（S17）は永久に偽だった。

    いまは本線が書き出す `*.quality.json` を読む。**無ければ点を名乗らない。**
    """
    with patch("routers.render.detect_gpu") as mock_detect,          patch("routers.render._get_quality_score", return_value=None),          patch("routers.render._品質の出所", return_value=None):
        mock_detect.return_value = {"gpu_available": False, "recommended_encoder": "libx264"}
        res = client.post("/api/render/start", json={"encoder": "libx264"})
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True, "未計測でも書き出し自体は止めない（従来の挙動）"
        assert data["quality_score"] is None, "測っていないのに点を名乗った"
        assert data["quality_checked"] is False
        assert data["is_real"] is False
        assert "未計測" in data["message"]


def test_start_render_実測が90未満ならブロックする():
    """**S17 の品質ブロックが実際に効く**（R1.5-C4・8周目の指摘）。

    `_get_quality_score()` が定数 95 だったので、この分岐は**一度も通らなかった**。
    `force_render` も意味を失っていた。
    """
    with patch("routers.render.detect_gpu") as mock_detect,          patch("routers.render._get_quality_score", return_value=89),          patch("routers.render._品質の出所", return_value="/dummy/x.quality.json"):
        mock_detect.return_value = {"gpu_available": False, "recommended_encoder": "libx264"}

        止まった = client.post("/api/render/start", json={"encoder": "libx264"}).json()
        assert 止まった["success"] is False
        assert 止まった["error"] == "quality_block"
        assert 止まった["quality_score"] == 89
        assert 止まった["is_real"] is True

        越えた = client.post("/api/render/start",
                             json={"encoder": "libx264", "force_render": True}).json()
        assert 越えた["success"] is True, "force_render で越えられない"
        assert 越えた["quality_score"] == 89

def test_video_processing_progress_callback():
    from video_processor import video_processor
    
    callback_holder = {}
    def mock_set_callback(cb):
        callback_holder["cb"] = cb
        
    def mock_process_video(task_id):
        if "cb" in callback_holder:
            mock_t = MagicMock()
            mock_t.phase.value = "completed"
            mock_t.progress = 100
            mock_t.current_step = "完了"
            mock_t.output_path = "/tmp/out.mp4"
            mock_t.preview_url = "http://preview/out"
            callback_holder["cb"](mock_t)
            
    video_processor.set_progress_callback.side_effect = mock_set_callback
    video_processor.process_video.side_effect = mock_process_video
    
    res = client.post("/api/video/process", json={
        "video_paths": ["v1.mp4"], "mood": "warm", "output_name": "final_vid"
    })
    assert res.status_code == 200
    task_id = res.json()["task_id"]
    
    assert _video_tasks[task_id]["status"] == "completed"
    assert _video_tasks[task_id]["progress"] == 100
    assert _video_tasks[task_id]["output_path"] == "/tmp/out.mp4"


def test_start_render_auto_fallback():
    with patch("routers.render._get_quality_score", return_value=95), \
         patch("routers.render.detect_gpu") as mock_detect:
        
        mock_detect.return_value = {"gpu_available": False, "recommended_encoder": "libx264"}
        res = client.post("/api/render/start", json={"encoder": "auto"})
        assert res.status_code == 200
        assert res.json()["success"] is True
        assert res.json()["encoder"] == "libx264"
        assert res.json()["gpu_fallback"] is False


def test_get_render_status_normal():
    job_id = "testjob_normal"
    _render_jobs[job_id] = {
        "started_at": time.time(),
        "status": "rendering",
        "progress": 25,
        "current_stage": "encoding",
        "stages": {},
        "encoder": "libx264",
        "gpu_fallback": False,
    }
    res = client.get(f"/api/render/status/{job_id}")
    assert res.status_code == 200
    assert res.json()["status"] == "rendering"
    assert res.json()["progress"] == 25
    assert res.json()["message"] is None


def test_list_available_videos_dir_not_exists():
    with patch("routers.render.Path.exists", return_value=False):
        res = client.get("/api/available-videos")
        assert res.status_code == 200
        assert res.json()["videos"] == []



# ═══════════════════════════════════════════════════════════════
# サムネイル生成・検証関連のテスト (Phase 27 thumbnail タスク #1)
# ═══════════════════════════════════════════════════════════════

def create_dummy_image_base64(width=100, height=100):
    from PIL import Image
    from io import BytesIO
    import base64
    img = Image.new("RGB", (width, height), color="red")
    out = BytesIO()
    img.save(out, format="JPEG")
    return base64.b64encode(out.getvalue()).decode("utf-8")

@patch("thumbnail_engine.generator.generator.generate")
def test_generate_thumbnail_success(mock_generate):
    dummy_b64 = create_dummy_image_base64(100, 100)
    mock_generate.return_value = [
        {
            "id": "thumbnail_0",
            "concept_name": "Test Concept",
            "description": "Test Description",
            "prompt": "Test Prompt",
            "image_base64": dummy_b64,
            "ctr_score": 8.5
        }
    ]
    
    # 正常系 (デフォルト解像度 1280x720)
    res = client.post("/api/render/thumbnail", json={
        "video_title": "Test Title",
        "video_description": "Test Desc",
        "width": 1280,
        "height": 720,
        "quality": 95
    })
    
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert len(data["thumbnails"]) == 1
    
    thumb = data["thumbnails"][0]
    assert thumb["id"] == "thumbnail_0"
    assert thumb["concept_name"] == "Test Concept"
    assert thumb["width"] == 1280
    assert thumb["height"] == 720
    assert thumb["aspect_ratio"] == "1280:720"
    assert thumb["file_size_bytes"] > 0
    
    # 画像が正しくリサイズされているかバイナリ検証
    import base64
    from io import BytesIO
    from PIL import Image
    img_data = base64.b64decode(thumb["image_base64"])
    img = Image.open(BytesIO(img_data))
    assert img.size == (1280, 720)


@patch("thumbnail_engine.generator.generator.generate")
def test_generate_thumbnail_invalid_requests(mock_generate):
    # 1. タイトルが空
    res = client.post("/api/render/thumbnail", json={
        "video_title": "   ",
        "width": 1280,
        "height": 720
    })
    assert res.status_code == 400
    assert "title" in res.json()["detail"].lower()
    
    # 2. 幅が不正
    res = client.post("/api/render/thumbnail", json={
        "video_title": "Test",
        "width": 0,
        "height": 720
    })
    assert res.status_code == 400
    
    # 3. 高さが不正
    res = client.post("/api/render/thumbnail", json={
        "video_title": "Test",
        "width": 1280,
        "height": -10
    })
    assert res.status_code == 400

    # 4. 画質が不正 (101)
    res = client.post("/api/render/thumbnail", json={
        "video_title": "Test",
        "width": 1280,
        "height": 720,
        "quality": 101
    })
    assert res.status_code == 400

    # 5. 画質が不正 (0)
    res = client.post("/api/render/thumbnail", json={
        "video_title": "Test",
        "width": 1280,
        "height": 720,
        "quality": 0
    })
    assert res.status_code == 400

    # 6. アスペクト比が許容範囲外 (1:1 スクエア)
    res = client.post("/api/render/thumbnail", json={
        "video_title": "Test",
        "width": 1280,
        "height": 1280
    })
    assert res.status_code == 400
    assert "aspect ratio" in res.json()["detail"].lower()


@patch("thumbnail_engine.generator.generator.generate")
def test_generate_thumbnail_generator_error(mock_generate):
    # Imagen 4.0 が例外を投げる場合
    mock_generate.side_effect = Exception("API quota limit reached")
    
    res = client.post("/api/render/thumbnail", json={
        "video_title": "Test Title",
        "width": 1280,
        "height": 720
    })
    assert res.status_code == 500
    assert "failed" in res.json()["detail"].lower()


@patch("thumbnail_engine.generator.generator.generate")
def test_generate_thumbnail_empty_result(mock_generate):
    # Imagen 4.0 が空を返す場合
    mock_generate.return_value = []
    
    import sys
    branding_mock = sys.modules["branding_manager"]
    branding_mock.branding_manager.generate_and_validate_thumbnail.side_effect = Exception("No thumbnails generated")
    
    res = client.post("/api/render/thumbnail", json={
        "video_title": "Test Title",
        "width": 1280,
        "height": 720
    })
    assert res.status_code == 500
    assert "no thumbnails" in res.json()["detail"].lower()


@patch("thumbnail_engine.generator.generator.generate")
def test_generate_thumbnail_processing_error(mock_generate):
    # 画像データが壊れている（base64デコードに失敗する、あるいは壊れた画像）
    mock_generate.return_value = [
        {
            "id": "thumbnail_0",
            "concept_name": "Test Concept",
            "description": "Test Description",
            "prompt": "Test Prompt",
            "image_base64": "invalid_base64_data_!!!",
            "ctr_score": 8.5
        }
    ]
    
    res = client.post("/api/render/thumbnail", json={
        "video_title": "Test Title",
        "width": 1280,
        "height": 720
    })
    assert res.status_code == 500
    assert "processing failed" in res.json()["detail"].lower()


@patch("thumbnail_engine.generator.generator.generate")
def test_thumbnail_quality_validation(mock_generate, tmp_path):
    # テスト用の一時データベースと一時出力フォルダを使用
    test_db = str(tmp_path / "test_thumbnails.db")
    
    # 正常な 100x100 画像データを生成
    dummy_b64 = create_dummy_image_base64(100, 100)
    mock_generate.return_value = [
        {
            "id": "thumb_test_qual",
            "concept_name": "Quality Concept",
            "description": "Quality Description",
            "prompt": "Quality Prompt",
            "image_base64": dummy_b64,
            "ctr_score": 9.9
        }
    ]
    
    # リクエストの送信 (解像度 1280x720)
    res = client.post("/api/render/thumbnail", json={
        "video_title": "Quality Title",
        "video_description": "Quality Desc",
        "width": 1280,
        "height": 720,
        "quality": 85,
        "db_path": test_db
    })
    
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert len(data["thumbnails"]) == 1
    
    thumb = data["thumbnails"][0]
    
    # 1. 解像度が 1280x720 以上であること
    assert thumb["width"] >= 1280
    assert thumb["height"] >= 720
    
    # 2. アスペクト比が 16:9 であること
    aspect = thumb["width"] / thumb["height"]
    assert abs(aspect - 16.0 / 9.0) < 0.01
    
    # 3. ファイルサイズが 4MB 未満であること
    import base64
    from io import BytesIO
    from PIL import Image
    img_data = base64.b64decode(thumb["image_base64"])
    file_size = len(img_data)
    assert file_size < 4 * 1024 * 1024
    
    # 4. Pillow等で正常にロード可能で、破損していないこと
    img = Image.open(BytesIO(img_data))
    img.load()
    img.close()
        
    # 5. DBに結果が保存されていること
    import sqlite3
    import json
    conn = sqlite3.connect(test_db)
    try:
        cursor = conn.execute("SELECT status, result FROM tasks WHERE stage = 'thumbnail'")
        rows = cursor.fetchall()
        assert len(rows) == 1
        status, result_str = rows[0]
        assert status == "COMPLETED"
        result_val = json.loads(result_str)
        assert result_val["id"] == "thumb_test_qual"
        # ファイルが実際に存在することを確認
        out_file_path = result_val["path"]
        assert os.path.exists(out_file_path)
        # 存在することを確認したら、一時出力ファイルをロードしてみる
        img_file = Image.open(out_file_path)
        img_file.load()
        img_file.close()
    finally:
        conn.close()



@patch("thumbnail_engine.generator.generator.generate")
def test_thumbnail_aspect_ratio_cropping_and_size_limits(mock_generate, tmp_path):
    test_db = str(tmp_path / "test_thumbnails.db")
    
    # 1. アスペクト比が 16:9 ではない元画像（100x100 スクエア画像）をモック生成
    dummy_b64 = create_dummy_image_base64(100, 100)
    mock_generate.return_value = [
        {
            "id": "thumb_square",
            "concept_name": "Square Concept",
            "description": "Square Description",
            "prompt": "Square Prompt",
            "image_base64": dummy_b64,
            "ctr_score": 9.0
        }
    ]
    
    # リクエスト送信（解像度 1280x720 = 16:9）
    res = client.post("/api/render/thumbnail", json={
        "video_title": "Square Title",
        "video_description": "Square Desc",
        "width": 1280,
        "height": 720,
        "quality": 85,
        "db_path": test_db
    })
    
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    thumb = data["thumbnails"][0]
    
    # 解像度とアスペクト比が 16:9 になっていることを確認
    assert thumb["width"] == 1280
    assert thumb["height"] == 720
    
    import base64
    from io import BytesIO
    from PIL import Image
    img_data = base64.b64decode(thumb["image_base64"])
    img = Image.open(BytesIO(img_data))
    assert img.size == (1280, 720)
    img.close()
    
    # 2. ファイルサイズが 4MB 以上の制限を超える場合の検証
    # ランダムノイズを用いて圧縮しにくい巨大画像を生成
    import os
    rand_data = os.urandom(2000 * 2000 * 3)
    huge_img = Image.frombytes("RGB", (2000, 2000), rand_data)
    huge_io = BytesIO()
    huge_img.save(huge_io, format="JPEG", quality=100)
    huge_b64 = base64.b64encode(huge_io.getvalue()).decode("utf-8")
    
    mock_generate.return_value = [
        {
            "id": "thumb_huge",
            "concept_name": "Huge Concept",
            "description": "Huge Description",
            "prompt": "Huge Prompt",
            "image_base64": huge_b64,
            "ctr_score": 7.0
        }
    ]
    
    res = client.post("/api/render/thumbnail", json={
        "video_title": "Huge Title",
        "video_description": "Huge Desc",
        "width": 3840,
        "height": 2160,
        "quality": 100,
        "db_path": test_db
    })
    
    # 自動品質調整リトライにより、ファイルサイズが4MB未満に抑えられて200 OKが返るはず
    assert res.status_code == 200
    res_data = res.json()
    assert res_data["success"] is True
    thumb = res_data["thumbnails"][0]
    assert thumb["file_size_bytes"] < 4 * 1024 * 1024


# ═══════════════════════════════════════════════════════════════
# 追加されたサムネイル品質・エラーハンドリングの追加検証テスト
# ═══════════════════════════════════════════════════════════════

@patch("thumbnail_engine.generator.generator.generate")
def test_generate_thumbnail_invalid_width_height_boundary(mock_generate):
    # 解像度の境界値テスト: 幅が1280未満 (1279) のときに400エラーが返るか
    res = client.post("/api/render/thumbnail", json={
        "video_title": "Boundary Resolution Title",
        "width": 1279,
        "height": 720
    })
    assert res.status_code == 400
    assert "resolution" in res.json()["detail"].lower()

    # 高さが720未満 (719) のときに400エラーが返るか
    res = client.post("/api/render/thumbnail", json={
        "video_title": "Boundary Resolution Title",
        "width": 1280,
        "height": 719
    })
    assert res.status_code == 400
    assert "resolution" in res.json()["detail"].lower()


@patch("thumbnail_engine.generator.generator.generate")
def test_generate_thumbnail_aspect_ratio_boundary(mock_generate):
    # アスペクト比の境界値テスト: 16:9 (1.777...) からズレている (1280x800 = 1.6) のときに400エラーが返るか
    res = client.post("/api/render/thumbnail", json={
        "video_title": "Aspect Boundary Title",
        "width": 1280,
        "height": 800
    })
    assert res.status_code == 400
    assert "aspect ratio" in res.json()["detail"].lower()


@patch("thumbnail_engine.generator.generator.generate")
def test_generate_thumbnail_corrupted_image_handling(mock_generate):
    import base64
    # デコードはできるが画像データとして壊れている場合
    invalid_image_base64 = base64.b64encode(b"not_a_valid_image_file_bytes").decode("utf-8")
    
    mock_generate.return_value = [
        {
            "id": "thumb_corrupted",
            "concept_name": "Corrupted Concept",
            "description": "Corrupted Description",
            "prompt": "Corrupted Prompt",
            "image_base64": invalid_image_base64,
            "ctr_score": 5.0
        }
    ]
    
    res = client.post("/api/render/thumbnail", json={
        "video_title": "Corrupted Image Title",
        "width": 1280,
        "height": 720
    })
    assert res.status_code == 500
    detail = res.json()["detail"].lower()
    assert "image format" in detail or "processing failed" in detail


@patch("thumbnail_engine.generator.generator.generate")
def test_generate_thumbnail_invalid_base64_decoding(mock_generate):
    # base64 としてデコードできない文字列の場合
    mock_generate.return_value = [
        {
            "id": "thumb_invalid_b64",
            "concept_name": "Invalid b64 Concept",
            "description": "Invalid b64 Description",
            "prompt": "Invalid b64 Prompt",
            "image_base64": "!!!_not_valid_base64_!!!",
            "ctr_score": 5.0
        }
    ]
    
    res = client.post("/api/render/thumbnail", json={
        "video_title": "Invalid b64 Title",
        "width": 1280,
        "height": 720
    })
    assert res.status_code == 500
    detail = res.json()["detail"].lower()
    assert "decode base64" in detail or "processing failed" in detail


@patch("thumbnail_engine.generator.generator.generate")
def test_generate_thumbnail_db_error(mock_generate, tmp_path):
    test_db = str(tmp_path / "test_thumbnails_error.db")
    dummy_b64 = create_dummy_image_base64(100, 100)
    mock_generate.return_value = [
        {
            "id": "thumb_db_err",
            "concept_name": "DB Err Concept",
            "description": "DB Err Description",
            "prompt": "DB Err Prompt",
            "image_base64": dummy_b64,
            "ctr_score": 9.9
        }
    ]
    
    import sqlite3
    real_connect = sqlite3.connect
    
    class ConnectionProxy:
        def __init__(self, conn):
            self.__dict__["_conn"] = conn
        def execute(self, query, *args, **kwargs):
            if "SELECT result FROM tasks" in query:
                raise sqlite3.Error("Mock database execute error")
            return self._conn.execute(query, *args, **kwargs)
        def __getattr__(self, name):
            return getattr(self._conn, name)
        def __setattr__(self, name, value):
            setattr(self._conn, name, value)
    
    def mock_connect(database, *args, **kwargs):
        conn = real_connect(database, *args, **kwargs)
        return ConnectionProxy(conn)

    with patch("sqlite3.connect", side_effect=mock_connect):
        res = client.post("/api/render/thumbnail", json={
            "video_title": "DB Error Title",
            "width": 1280,
            "height": 720,
            "db_path": test_db
        })
        assert res.status_code == 500
        assert "database fetch failed" in res.json()["detail"].lower()
