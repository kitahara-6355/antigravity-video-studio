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


def _branding_mock():
    """`branding_manager` のモックを**確実に**得る（R1.5-C4・案D 掃引）。

    上の行は**このモジュールの import 時**に1回だけ効く。ところが同じプロセスで
    先に走った別のテストファイル（`test_routers/test_c4_quality_marks.py`）が
    本物の `branding_manager` を import し直すと、`sys.modules` の中身が
    本物のモジュールに戻る。すると
    `sys.modules["branding_manager"].branding_manager.generate_and_validate_thumbnail`
    は**束縛メソッド**になり、`.side_effect = ...` が AttributeError になる。

    `pytest.ini` の testpaths ではこのファイルが先に来るので CI は緑だが、
    **順序が変わると落ちる**（実際に手元で踏んだ）。収集順に依存させない。
    """
    mod = sys.modules.get("branding_manager")
    if not isinstance(mod, MagicMock):
        mod = MagicMock()
        sys.modules["branding_manager"] = mod
    return mod
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
    with patch("routers.render._品質の実測", return_value=(85, "/dummy/x.quality.json")):
        res = client.post("/api/render/start", json={"force_render": False})
        assert res.status_code == 200
        assert res.json()["success"] is False
        assert res.json()["error"] == "quality_block"

def test_start_render_nvenc_success():
    with patch("routers.render._品質の実測", return_value=(95, "/dummy/x.quality.json")), \
         patch("routers.render.detect_gpu") as mock_detect:
        
        mock_detect.return_value = {"gpu_available": True, "recommended_encoder": "nvenc"}
        res = client.post("/api/render/start", json={"encoder": "nvenc"})
        assert res.status_code == 200
        assert res.json()["success"] is True
        assert res.json()["encoder"] == "nvenc"
        assert res.json()["gpu_fallback"] is False

def test_start_render_nvenc_fallback():
    with patch("routers.render._品質の実測", return_value=(95, "/dummy/x.quality.json")), \
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
    """**R2-C1 で閉じた経路**（2026-09-25）。承認を1件も見ずに ffmpeg を回していた。

    かつては 200 でタスクを登録し、背景で `backend/temp/video_output/` に完成動画を
    書いていた。いまは断るので、**タスクも登録しない**（書き出しの準備すらしない）。
    """
    before = set(_video_tasks)
    res = client.post("/api/video/process", json={
        "video_paths": ["v1.mp4"], "mood": "warm", "output_name": "final_vid"
    })
    assert res.status_code == 409, res.text
    assert "承認" in res.json()["detail"]
    assert set(_video_tasks) == before, "断ったのにタスクを登録しています"

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


def test_start_render_未計測なら書き出さない():
    """**測っていないのに 95 点で通さない**（R1.5-C4・gate-verifier 8周目の指摘）。

    ここは以前「`_get_quality_score` を mock しない場合、デフォルトの 95 が返るため、
    ブロックされずに開始するはず」と書いてあり、**testpaths 内のこのテストが
    偽の success を緑で固定していた。**95 は直書きの定数で、
    そのせいで `if quality_score < 90` の品質ブロック（S17）は永久に偽だった。

    いまは本線が書き出す `*.quality.json` を読む。**無ければ点を名乗らない。**
    """
    with patch("routers.render.detect_gpu") as mock_detect,          patch("routers.render._品質の実測", return_value=(None, None)):
        mock_detect.return_value = {"gpu_available": False, "recommended_encoder": "libx264"}
        for body in ({"encoder": "libx264"},
                     {"encoder": "libx264", "force_render": True}):
            res = client.post("/api/render/start", json=body)
            assert res.status_code == 200
            data = res.json()
            # **未計測は必ず止める。force_render でも越えられない**
            # （2026-08-29 ユーザー決定）。UI は force_render: !is_ready で
            # 常に押してくるので、越えられるようにすると門が無いのと同じになる
            assert data["success"] is False, f"{body}: 未計測なのに書き出しを通した"
            assert data["error"] == "quality_unmeasured"
            assert data["force_render_available"] is False
            assert data["quality_score"] is None
            assert data["quality_checked"] is False
            assert data["is_real"] is False


def test_start_render_実測が90未満ならブロックする():
    """**S17 の品質ブロックが実際に効く**（R1.5-C4・8周目の指摘）。

    `_get_quality_score()` が定数 95 だったので、この分岐は**一度も通らなかった**。
    `force_render` も意味を失っていた。
    """
    with patch("routers.render.detect_gpu") as mock_detect,          patch("routers.render._品質の実測",
               return_value=(89, "/dummy/x.quality.json")):
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
    """**進捗コールバックの経路ごと閉じた**（R2-C1・2026-09-25）。

    ここは背景処理の `update_progress` が `_video_tasks` を completed に書き換えるところを
    見ていた。経路を閉じたので背景処理そのものが無く、見るべきものは
    「**書き出しに至る部品を1つも動かさないこと**」に変わった。
    """
    from video_processor import video_processor

    video_processor.set_progress_callback.reset_mock()
    video_processor.process_video.reset_mock()
    video_processor.create_task.reset_mock()

    res = client.post("/api/video/process", json={
        "video_paths": ["v1.mp4"], "mood": "warm", "output_name": "final_vid"
    })

    assert res.status_code == 409
    video_processor.create_task.assert_not_called()
    video_processor.set_progress_callback.assert_not_called()
    video_processor.process_video.assert_not_called()


def test_start_render_auto_fallback():
    with patch("routers.render._品質の実測", return_value=(95, "/dummy/x.quality.json")), \
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

    # **フォールバックも落ちることを自分で用意する**（R1.5-C4・案D 掃引）。
    # 500 になるのは「生成も代替も失敗した」ときで、この検査はこれまで
    # **前のテストが残した `side_effect` に依存**していた。
    # モックが作り直されると前提が消えて 200 になる（収集順で結果が変わる）。
    _branding_mock().branding_manager.generate_and_validate_thumbnail.side_effect = (
        Exception("No thumbnails generated"))

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
    branding_mock = _branding_mock()
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


@patch("thumbnail_engine.generator.generator.generate")
def test_案D_ルーターが既定値で_CTR_を作り直さない(mock_generate):
    """**`render.py` の `.get("ctr_score", 5.0)` が値を再捏造していた**（R1.5-C4・案D 掃引）。

    `branding_manager` 側のフォールバックを直しても、ルーターが既定値 5.0 を
    置いていると**同じ数字が復活する**。ここでは manager が `ctr_score` を
    返さない状態を実際に作り、応答に 5.0 が出ないことを見る
    （§3: 分岐に入る側のケースを通さないと再発を捕まえられない）。

    あわせて、`status: "fallback"` はルーターが応答を組み立てる際に捨てられるので、
    **出所の印（`is_real` / `data_source`）が応答まで届くこと**も見る。
    """
    import base64 as _b64
    _bm = _branding_mock()

    # 生成を落としてフォールバック分岐に入れる
    mock_generate.side_effect = RuntimeError("生成失敗")

    dummy_b64 = create_dummy_image_base64(1280, 720)
    # **`side_effect` を消してから `return_value` を置く。**
    # 同ファイルの test_generate_thumbnail_fallback_failure が
    # `side_effect = Exception(...)` を立てたまま戻さないので、
    # 消さないと単体では緑・全体では赤になる（実際に踏んだ）
    _bm.branding_manager.generate_and_validate_thumbnail.side_effect = None
    _bm.branding_manager.generate_and_validate_thumbnail.return_value = {
        "status": "fallback",
        "concept_name": "Standard Fallback Concept",
        "description": "Fallback image due to system errors",
        "image_base64": dummy_b64,
        # **`ctr_score` を入れない。** 既定値が復活したらここで 5.0 になる
        "is_real": False,
        "data_source": "unavailable",
        "validation": {},
    }

    res = client.post("/api/render/thumbnail", json={
        "video_title": "案D 掃引テスト",
        "video_description": "フォールバック経路を通す",
        "width": 1280, "height": 720, "quality": 90,
    })

    assert res.status_code == 200, res.text
    thumb = res.json()["thumbnails"][0]
    assert thumb["ctr_score"] is None,         f"CTR 予測をしていないのに {thumb['ctr_score']} が応答に出た"
    assert thumb["is_real"] is False
    assert thumb["data_source"] == "unavailable"
    assert _b64.b64decode(thumb["image_base64"])


@patch("thumbnail_engine.generator.generator.generate")
def test_案D_成功経路の印が応答まで届く(mock_generate):
    """**印を応答へ運んでいることを、既定値と違う値で確かめる。**

    フォールバックだけを見ると `is_real: False` が期待値になり、
    運び忘れたときの既定値 `False` と**区別が付かない**。
    成功経路（`is_real: True`）を通して初めて「運んでいる」ことが分かる。

    この検査が無いと「ルーターが印を応答へ運ばない」変異が生き残る（実際に生き残った）。
    """
    mock_generate.side_effect = None
    # **生成器が自分で印を付けて返す**（thumbnail_engine/generator.py が
    # コンセプトの出所を知っている唯一の場所）。ルーターはそれを運ぶだけ
    mock_generate.return_value = [{
        "id": "thumbnail_0", "concept_name": "C", "description": "D",
        "prompt": "p", "image_base64": create_dummy_image_base64(1280, 720),
        "ctr_score": 8.5, "is_real": True, "data_source": "gemini",
    }]
    res = client.post("/api/render/thumbnail", json={
        "video_title": "成功経路", "video_description": "d",
        "width": 1280, "height": 720, "quality": 90,
    })
    assert res.status_code == 200, res.text
    thumb = res.json()["thumbnails"][0]
    assert thumb["is_real"] is True, "成功経路の印が応答まで届いていない"
    assert thumb["data_source"] == "gemini"
    assert thumb["ctr_score"] == 8.5


@patch("thumbnail_engine.generator.generator.generate")
def test_案D_ルーターが生成器の印を捏造しない(mock_generate):
    """**自分の修正が作った偽**（R1.5-C4・案D 掃引で自己検出）。

    最初この経路を `for _t in raw_thumbnails: _t["is_real"] = True` と書いた。
    ところが生成器は、コンセプト生成が全滅すると
    `_get_fallback_concept`（`expected_ctr` を持たない既定構成）に落ちる。
    **一律に True を貼ると、その回まで「実測」に化ける。**

    ルーターは出所を知らないので、**印の無い戻りは悲観側に倒す**のが正しい。
    """
    mock_generate.side_effect = None
    # 生成器が印を付けずに返した（＝出所が分からない）場合
    mock_generate.return_value = [{
        "id": "thumbnail_0", "concept_name": "C", "description": "D",
        "prompt": "p", "image_base64": create_dummy_image_base64(1280, 720),
        "ctr_score": 5.0,
    }]
    res = client.post("/api/render/thumbnail", json={
        "video_title": "印なし生成器", "video_description": "d",
        "width": 1280, "height": 720, "quality": 90,
    })
    assert res.status_code == 200, res.text
    thumb = res.json()["thumbnails"][0]
    assert thumb["is_real"] is False, "ルーターが印を捏造している（一律 True）"
    assert thumb["data_source"] == "unavailable"


@patch("thumbnail_engine.generator.generator.generate")
def test_案D_印の無い戻りは成功側に倒さない(mock_generate):
    """**既定値は悲観側でなければならない。**

    manager が印を返さなかったとき、`thumb.get("is_real", True)` のように
    成功側へ倒すと、**印を忘れた経路が「実測」を名乗る**。

    この検査が無いと「ルーターの印を fail-open にする」変異が生き残る（実際に生き残った）。
    """
    _bm = _branding_mock()

    mock_generate.side_effect = RuntimeError("生成失敗")
    _bm.branding_manager.generate_and_validate_thumbnail.side_effect = None
    _bm.branding_manager.generate_and_validate_thumbnail.return_value = {
        "status": "fallback",
        "concept_name": "C", "description": "D",
        "image_base64": create_dummy_image_base64(1280, 720),
        # **印を1つも入れない** — ここで既定値が効く
    }
    res = client.post("/api/render/thumbnail", json={
        "video_title": "印なし", "video_description": "d",
        "width": 1280, "height": 720, "quality": 90,
    })
    assert res.status_code == 200, res.text
    thumb = res.json()["thumbnails"][0]
    assert thumb["is_real"] is False, "印が無い戻りを成功側に倒している（fail-open）"
    assert thumb["data_source"] == "unavailable"
    assert thumb["ctr_score"] is None
