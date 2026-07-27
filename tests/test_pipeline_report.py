import sys
import importlib.util
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

# カレントディレクトリを取得
cwd = Path.cwd()
workspace_root = str(cwd)
workspace_backend = str(cwd / "backend")

# sys.path に追加
if workspace_root not in sys.path:
    sys.path.insert(0, workspace_root)
if workspace_backend not in sys.path:
    sys.path.insert(0, workspace_backend)

# 対象の pipeline_report をインポート
import backend.routers.pipeline_report as report_mod

app = FastAPI()
app.include_router(report_mod.router)
client = TestClient(app)

# --- 1. _probe_video 関数のテスト ---

def test_probe_video_success():
    """ffprobeが正常にコーデック情報を返すケース"""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = '{"streams": [{"codec_type": "video", "codec_name": "h264"}, {"codec_type": "audio", "codec_name": "aac"}], "format": {"duration": "120.5"}}'
    
    with patch("subprocess.run", return_value=mock_result):
        res = report_mod._probe_video("dummy_path.mp4")
        assert res == {
            "video_codec": "h264",
            "audio_codec": "aac",
            "duration_sec": 120.5,
            "valid": True
        }

def test_probe_video_video_editor_import_error():
    """video_editor_engineインポート時に例外が発生し、デフォルトのffprobe_pathフォールバックをテスト"""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = '{"streams": [{"codec_type": "video", "codec_name": "h264"}, {"codec_type": "audio", "codec_name": "aac"}], "format": {"duration": "10.0"}}'
    
    with patch.dict(sys.modules, {"video_editor_engine": None}):
        with patch("subprocess.run", return_value=mock_result):
            res = report_mod._probe_video("dummy_path.mp4")
            assert res["valid"] is True

def test_probe_video_http_exception():
    """HTTPExceptionが発生した場合、そのままraiseされることをテスト"""
    mock_editor = MagicMock()
    type(mock_editor).ffmpeg = PropertyMock(side_effect=HTTPException(status_code=400, detail="error"))
    with patch("video_editor_engine.video_editor", mock_editor):
        with pytest.raises(HTTPException):
            report_mod._probe_video("dummy_path.mp4")

def test_probe_video_ffprobe_failed():
    """subprocess.runがエラー終了(returncode!=0)した場合"""
    mock_result = MagicMock()
    mock_result.returncode = 1
    
    with patch("subprocess.run", return_value=mock_result):
        res = report_mod._probe_video("dummy_path.mp4")
        assert res == {"valid": False, "error": "ffprobe不可"}

def test_probe_video_subprocess_exception():
    """subprocess.runが例外を発生させる場合"""
    with patch("subprocess.run", side_effect=Exception("process failed")):
        res = report_mod._probe_video("dummy_path.mp4")
        assert res == {"valid": False, "error": "ffprobe不可"}

def test_probe_video_exception_during_ffprobe_path_resolution():
    """ffprobe_path解決中に例外が発生し、かつ例外の二重トラップ(subprocess.runでの例外)をテスト"""
    with patch("video_editor_engine.video_editor", side_effect=Exception("import error")):
        with patch("subprocess.run", side_effect=Exception("run error")):
            res = report_mod._probe_video("dummy_path.mp4")
            assert res == {"valid": False, "error": "ffprobe不可"}


def test_probe_video_ffprobe_path_fallback():
    """ffmpeg_pathがre.subで置換されず、parent / ffprobe.exeにフォールバックされるケースをテスト"""
    mock_editor = MagicMock()
    mock_editor.ffmpeg.ffmpeg_path = "C:/custom/bin/my_encoder"
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = '{"streams": [{"codec_type": "video", "codec_name": "h264"}, {"codec_type": "audio", "codec_name": "aac"}], "format": {"duration": "10.0"}}'
    
    with patch("video_editor_engine.video_editor", mock_editor):
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            res = report_mod._probe_video("dummy_path.mp4")
            assert res["valid"] is True
            called_args = mock_run.call_args[0][0]
            expected_path = str(Path("C:/custom/bin/ffprobe.exe"))
            assert called_args[0] == expected_path


def test_probe_video_run_http_exception():
    """subprocess.run実行時にHTTPExceptionが発生し、そのままraiseされることをテスト"""
    with patch("subprocess.run", side_effect=HTTPException(status_code=500, detail="http error during run")):
        with pytest.raises(HTTPException):
            report_mod._probe_video("dummy_path.mp4")


# --- 2. _build_category_html 関数のテスト ---

def test_build_category_html_empty():
    res = report_mod._build_category_html({})
    assert "カテゴリ別スコア: データなし" in res

def test_build_category_html_invalid_item():
    quality = {
        "category_report": ["not_a_dict"]
    }
    res = report_mod._build_category_html(quality)
    assert "not_a_dict" not in res
    assert "<table" in res

def test_build_category_html_valid_items():
    quality = {
        "category_report": [
            {
                "category": "video",
                "label": "映像品質",
                "score": 95,
                "status": "PASS",
                "deductions": 0,
                "plugin_count": 3
            },
            {
                "category": "audio",
                # label欠落
                "score": None,
                "status": "FAIL",
                "deductions": 10,
                "plugin_count": 1
            }
        ]
    }
    res = report_mod._build_category_html(quality)
    assert "映像品質" in res
    assert "audio" in res
    assert "95" in res
    assert "—" in res
    assert "PASS" in res
    assert "10点" in res

# --- 3. _build_feedback_html 関数のテスト ---

def test_build_feedback_html_empty():
    res = report_mod._build_feedback_html({})
    assert "✅ フィードバック: なし" in res

def test_build_feedback_html_with_items():
    quality = {
        "feedback": ["音量が小さすぎます", "字幕が重なっています"]
    }
    res = report_mod._build_feedback_html(quality)
    assert "⚠ フィードバック (2件):" in res
    assert "音量が小さすぎます" in res
    assert "字幕が重なっています" in res

# --- 4. /api/pipeline/report エンドポイントのテスト ---

@pytest.fixture
def clean_pipeline_states():
    # 関係するすべての pipeline_router モジュールの _pipeline_state をリセット
    states_to_clean = []
    for name in ["routers.pipeline_router", "backend.routers.pipeline_router"]:
        mod = sys.modules.get(name)
        if mod and hasattr(mod, "_pipeline_state"):
            states_to_clean.append((mod._pipeline_state, mod._pipeline_state.copy()))
    
    yield states_to_clean
    
    # リセット
    for state, orig in states_to_clean:
        state.clear()
        state.update(orig)

def test_pipeline_report_all_ok(clean_pipeline_states, tmp_path):
    # ダミーファイルの作成（サイズ > 1MB）
    dummy_preview = tmp_path / "preview.mp4"
    dummy_preview.write_bytes(b"\x00" * (1024 * 1024 + 100))
    dummy_final = tmp_path / "final.mp4"
    dummy_final.write_bytes(b"\x00" * (1024 * 1024 + 100))
    dummy_thumb = tmp_path / "thumb.jpg"
    dummy_thumb.write_bytes(b"\x00" * 2000)

    test_state = {
        "status": "completed",
        "result": {
            "session_id": "test-session-12345678",
            "duration_seconds": 150,
            "segments_count": 10,
            "preview_path": str(dummy_preview),
            "final_path": str(dummy_final),
            "thumbnail_path": str(dummy_thumb),
            "stage_results": [
                {"name": "文字起こしステージ", "success": True, "duration": 12.5, "detail": "文字起こし完了"},
                {"name": "AI校閲ステージ", "success": True, "duration": 5.0, "detail": "校閲完了"},
                {"name": "SmartCutステージ", "success": True, "duration": 8.0, "detail": "カット完了"},
                {"name": "プレビュー生成ステージ", "success": True, "duration": 20.0, "detail": "プレビュー完了"},
                {"name": "品質ゲートステージ", "success": True, "duration": 3.0, "detail": "品質合格"},
                {"name": "最終レンダリングステージ", "success": True, "duration": 60.0, "detail": "レンダリング完了"},
                {"name": "YouTube最適化ステージ", "success": True, "duration": 2.0, "detail": "最適化完了"},
                {"name": "サムネイル生成ステージ", "success": True, "duration": 1.0, "detail": "サムネイル完了"},
            ],
            "quality_details": {
                "score": 95,
                "category_report": [
                    {"category": "transcription", "label": "文字起こし", "score": 95, "status": "PASS"}
                ],
                "feedback": []
            },
            "metadata": {
                "titles": ["最強の動画"],
                "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
                "chapters": [{"time": 0, "title": "OP"}]
            }
        }
    }

    for state, _ in clean_pipeline_states:
        state.update(test_state)

    # _probe_video が H.264 + AAC を返すように直接上書き
    mock_probe = {
        "video_codec": "h264",
        "audio_codec": "aac",
        "duration_sec": 120.5,
        "valid": True
    }
    orig_probe = report_mod._probe_video
    report_mod._probe_video = MagicMock(return_value=mock_probe)
    try:
        response = client.get("/api/pipeline/report")
        assert response.status_code == 200
        html = response.text
        assert "🚀 Antigravity パイプライン完了レポート" in html
        assert "✅ 全機能適用済み完成動画" in html
        assert "文字起こしステージ" in html
        assert "文字起こし完了" in html
        assert "h264" in html
        assert "aac" in html
    finally:
        report_mod._probe_video = orig_probe

def test_pipeline_report_some_fail(clean_pipeline_states):
    # ファイルが無い、または条件を満たさないケース
    test_state = {
        "status": "failed",
        "result": {
            "session_id": "test-session-failed",
            "duration_seconds": 45,
            "segments_count": 0,  # 文字起こしNG
            "preview_path": None,  # プレビューNG
            "final_path": "non_existent_final.mp4",  # レンダリングNG
            "stage_results": [
                {"name": "文字起こしステージ", "success": False, "duration": 1.0, "detail": "失敗"},
                {"name": "最終レンダリングステージ", "success": False, "duration": 1.0, "detail": "失敗"},
            ],
            "quality_details": {
                "score": 85,  # 品質スコアNG (<90)
                "category_report": [],
                "feedback": ["修正点あり"]
            },
            "metadata": {
                "titles": [],  # YouTube最適化NG
                "tags": ["tag1"],
                "chapters": []
            }
        }
    }

    for state, _ in clean_pipeline_states:
        state.update(test_state)

    response = client.get("/api/pipeline/report")
    assert response.status_code == 200
    html = response.text
    assert "⚠️ 改善余地あり（0/8合格）" in html
    assert "❌" in html
    assert "修正点あり" in html


# --- 5. サムネイル画像取得エンドポイントおよびフォールバックのテスト ---

def test_get_report_thumbnail_success(clean_pipeline_states, tmp_path):
    """thumbnail_pathが正しく設定されており、存在するファイルを返すケース"""
    dummy_thumb = tmp_path / "thumb_endpoint.jpg"
    dummy_thumb.write_bytes(b"\x00" * 2000)

    test_state = {
        "status": "completed",
        "result": {
            "thumbnail_path": str(dummy_thumb)
        }
    }
    for state, _ in clean_pipeline_states:
        state.update(test_state)

    response = client.get("/api/pipeline/report/thumbnail")
    assert response.status_code == 200
    assert len(response.content) == 2000


def test_get_report_thumbnail_fallback(clean_pipeline_states):
    """thumbnail_pathは無いが、glob.globでサムネイルが検出されて取得できるケース"""
    test_state = {
        "status": "completed",
        "result": {}
    }
    for state, _ in clean_pipeline_states:
        state.update(test_state)

    thumb_dir = Path("output/thumbnails")
    thumb_dir.mkdir(parents=True, exist_ok=True)
    dummy_file = thumb_dir / "fallback_temp.jpg"
    dummy_file.write_bytes(b"\x00" * 2000)

    try:
        response = client.get("/api/pipeline/report/thumbnail")
        assert response.status_code == 200
        assert len(response.content) == 2000
    finally:
        if dummy_file.exists():
            dummy_file.unlink()
        try:
            thumb_dir.rmdir()
        except OSError:
            pass


def test_get_report_thumbnail_not_found(clean_pipeline_states):
    """サムネイルが一切見つからず、404エラーが返るケース"""
    test_state = {
        "status": "completed",
        "result": {
            "thumbnail_path": None
        }
    }
    for state, _ in clean_pipeline_states:
        state.update(test_state)

    with patch("glob.glob", return_value=[]):
        response = client.get("/api/pipeline/report/thumbnail")
        assert response.status_code == 404
        assert response.json()["detail"] == "サムネイル画像が見つかりません"


def test_pipeline_report_thumbnail_glob_fallback(clean_pipeline_states, tmp_path):
    """resultにthumbnail_pathが無いとき、globフォールバックによりサムネイル情報が解決されるケース"""
    dummy_preview = tmp_path / "preview.mp4"
    dummy_preview.write_bytes(b"\x00" * (1024 * 1024 + 100))
    dummy_final = tmp_path / "final.mp4"
    dummy_final.write_bytes(b"\x00" * (1024 * 1024 + 100))

    thumb_dir = Path("output/thumbnails")
    thumb_dir.mkdir(parents=True, exist_ok=True)
    dummy_file = thumb_dir / "fallback_report.jpg"
    dummy_file.write_bytes(b"\x00" * 2000)

    test_state = {
        "status": "completed",
        "result": {
            "session_id": "test-session-12345678",
            "duration_seconds": 150,
            "segments_count": 10,
            "preview_path": str(dummy_preview),
            "final_path": str(dummy_final),
            "stage_results": [
                {"name": "文字起こしステージ", "success": True, "duration": 12.5, "detail": "文字起こし完了"},
                {"name": "AI校閲ステージ", "success": True, "duration": 5.0, "detail": "校閲完了"},
                {"name": "SmartCutステージ", "success": True, "duration": 8.0, "detail": "カット完了"},
                {"name": "プレビュー生成ステージ", "success": True, "duration": 20.0, "detail": "プレビュー完了"},
                {"name": "品質ゲートステージ", "success": True, "duration": 3.0, "detail": "品質合格"},
                {"name": "最終レンダリングステージ", "success": True, "duration": 60.0, "detail": "レンダリング完了"},
                {"name": "YouTube最適化ステージ", "success": True, "duration": 2.0, "detail": "最適化完了"},
                {"name": "サムネイル生成ステージ", "success": True, "duration": 1.0, "detail": "サムネイル完了"},
            ],
            "quality_details": {
                "score": 95,
                "category_report": [
                    {"category": "transcription", "label": "文字起こし", "score": 95, "status": "PASS"}
                ],
                "feedback": []
            },
            "metadata": {
                "titles": ["最強の動画"],
                "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
                "chapters": [{"time": 0, "title": "OP"}]
            }
        }
    }

    for state, _ in clean_pipeline_states:
        state.update(test_state)

    mock_probe = {
        "video_codec": "h264",
        "audio_codec": "aac",
        "duration_sec": 120.5,
        "valid": True
    }
    orig_probe = report_mod._probe_video
    report_mod._probe_video = MagicMock(return_value=mock_probe)

    try:
        response = client.get("/api/pipeline/report")
        assert response.status_code == 200
        html = response.text
        assert "✅ 全機能適用済み完成動画" in html
        assert "fallback_report.jpg" in html
    finally:
        report_mod._probe_video = orig_probe
        if dummy_file.exists():
            dummy_file.unlink()
        try:
            thumb_dir.rmdir()
        except OSError:
            pass
