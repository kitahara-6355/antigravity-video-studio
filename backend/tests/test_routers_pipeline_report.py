import os
import sys
import pytest
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# backendパスをインポートできるように設定
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from routers.pipeline_report import (
    router,
    _probe_video,
    _build_category_html,
    _build_feedback_html
)

app = FastAPI()
app.include_router(router)
client = TestClient(app)


# ==========================================
# _probe_video 関数のテスト
# ==========================================

def test_probe_video_success():
    """ffprobe が正常にコーデック情報を返すケース"""
    mock_editor = MagicMock()
    mock_editor.ffmpeg.ffmpeg_path = "C:\\path\\to\\ffmpeg.exe"
    
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = '{"streams": [{"codec_name": "h264", "codec_type": "video"}, {"codec_name": "aac", "codec_type": "audio"}], "format": {"duration": "123.45"}}'
    
    # 依存関係モジュール mock の適用
    with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_editor)}), \
         patch("subprocess.run", return_value=mock_result) as mock_run:
        res = _probe_video("dummy_path.mp4")
        assert res["valid"] is True
        assert res["video_codec"] == "h264"
        assert res["audio_codec"] == "aac"
        assert res["duration_sec"] == 123.5


def test_probe_video_ffmpeg_exception():
    """video_editor_engine ロード時に例外が発生しフォールバックするケース"""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = '{"streams": [{"codec_name": "h264", "codec_type": "video"}], "format": {"duration": "10.0"}}'
    
    with patch("subprocess.run", return_value=mock_result):
        # インポート時に一般例外を投げる
        with patch("importlib.import_module", side_effect=Exception("No module")):
            res = _probe_video("dummy_path.mp4")
            assert res["valid"] is True
            assert res["video_codec"] == "h264"
            assert res["audio_codec"] == "unknown"


def test_probe_video_http_exception():
    """HTTPException が発生した場合はそのまま上に投げる（raise される）"""
    class DummyModule:
        @property
        def video_editor(self):
            raise HTTPException(status_code=404, detail="Not Found")

    with patch.dict(sys.modules, {"video_editor_engine": DummyModule()}):
        with pytest.raises(HTTPException) as exc_info:
            _probe_video("dummy_path.mp4")
        assert exc_info.value.status_code == 404


def test_probe_video_run_error():
    """subprocess.run が例外を投げるか、またはエラー終了（returncode != 0）した場合"""
    mock_editor = MagicMock()
    mock_editor.ffmpeg.ffmpeg_path = "C:\\path\\to\\ffmpeg.exe"
    
    # 例外スローケース
    with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_editor)}), \
         patch("subprocess.run", side_effect=Exception("Subprocess failed")):
        res = _probe_video("dummy_path.mp4")
        assert res["valid"] is False
        assert res["error"] == "ffprobe不可"

    # returncode != 0 ケース
    mock_result_err = MagicMock()
    mock_result_err.returncode = 1
    with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_editor)}), \
         patch("subprocess.run", return_value=mock_result_err):
        res = _probe_video("dummy_path.mp4")
        assert res["valid"] is False
        assert res["error"] == "ffprobe不可"


# ==========================================
# _build_category_html 関数のテスト
# ==========================================

def test_build_category_html_empty():
    """category_report が無い、または空の場合の表示確認"""
    assert "カテゴリ別スコア: データなし" in _build_category_html({})
    assert "カテゴリ別スコア: データなし" in _build_category_html({"category_report": []})


def test_build_category_html_with_data():
    """各種カテゴリデータおよびエッジケース（辞書以外、スコアNone）の表示確認"""
    quality = {
        "category_report": [
            {
                "label": "映像品質",
                "score": 95,
                "status": "PASS",
                "deductions": 0,
                "plugin_count": 2
            },
            # dictionary 以外の要素（スキップされるべき）
            "not_a_dict",
            # scoreがNone（「—」が表示されるべき）
            {
                "category": "音響品質",
                "score": None,
                "status": "FAIL",
                "deductions": 10,
                "plugin_count": 1
            }
        ]
    }
    html = _build_category_html(quality)
    assert "映像品質" in html
    assert "95" in html
    assert "音響品質" in html
    assert "—" in html
    assert "10点" in html


# ==========================================
# _build_feedback_html 関数のテスト
# ==========================================

def test_build_feedback_html_empty():
    """フィードバックが無い場合の表示確認"""
    assert "✅ フィードバック: なし" in _build_feedback_html({})


def test_build_feedback_html_with_data():
    """フィードバックが有る場合のリスト表示確認"""
    quality = {
        "feedback": ["音量が小さすぎます", "テロップのフォントが見づらい"]
    }
    html = _build_feedback_html(quality)
    assert "音量が小さすぎます" in html
    assert "テロップのフォントが見づらい" in html


# ==========================================
# GET /api/pipeline/report/thumbnail のテスト
# ==========================================

@patch("routers.pipeline_router._pipeline_state")
def test_get_report_thumbnail_success(mock_state, tmp_path):
    """result 内に存在する thumbnail_path から正常にファイルを返すケース"""
    thumb_file = tmp_path / "dummy_thumb.jpg"
    thumb_file.write_bytes(b"dummy image data")
    
    mock_state.get.side_effect = lambda key, default=None: {
        "result": {
            "thumbnail_path": str(thumb_file)
        }
    }.get(key, default)
    
    response = client.get("/api/pipeline/report/thumbnail")
    assert response.status_code == 200
    assert response.content == b"dummy image data"



@patch("routers.pipeline_router._pipeline_state")
def test_get_report_thumbnail_glob_success(mock_state, tmp_path):
    """result に thumbnail_path がないが、glob.glob で見つかるケース"""
    mock_state.get.return_value = {
        "result": {
            "metadata": {
                "thumbnail_path": ""
            }
        }
    }
    thumb_file = tmp_path / "found.jpg"
    thumb_file.write_bytes(b"glob image data")
    
    with patch("glob.glob", return_value=[str(thumb_file)]):
        response = client.get("/api/pipeline/report/thumbnail")
        assert response.status_code == 200
        assert response.content == b"glob image data"


@patch("routers.pipeline_router._pipeline_state")
def test_get_report_thumbnail_not_found(mock_state):
    """サムネイルファイルがどこにも存在しない場合に 404 を返すケース"""
    mock_state.get.return_value = {}
    with patch("glob.glob", return_value=[]):
        response = client.get("/api/pipeline/report/thumbnail")
        assert response.status_code == 404
        assert response.json()["detail"] == "サムネイル画像が見つかりません"


# ==========================================
# GET /api/pipeline/report のテスト
# ==========================================

@patch("routers.pipeline_router._pipeline_state")
def test_pipeline_report_all_ok(mock_state, tmp_path):
    """全 8 項目が合格（OK）となるレポートページの表示テスト"""
    preview_file = tmp_path / "preview.mp4"
    preview_file.write_bytes(b"x" * (1 * 1024 * 1024 + 100)) # 1MB超
    
    final_file = tmp_path / "final.mp4"
    final_file.write_bytes(b"x" * (1 * 1024 * 1024 + 100)) # 1MB超
    
    thumb_file = tmp_path / "thumb.jpg"
    thumb_file.write_bytes(b"x" * 2000) # 1000バイト超
    
    mock_state.get.side_effect = lambda key, default=None: {
        "status": "completed",
        "video_path": "path/to/raw_video.mp4",
        "result": {
            "segments_count": 5,
            "preview_path": str(preview_file),
            "final_path": str(final_file),
            "thumbnail_path": str(thumb_file),
            "duration_seconds": 120.0,
            "session_id": "session-1234567890",
            "quality_details": {
                # **採点したかどうかを持つ**（R1.5-C4・9周目）。実走の
                # `_build_result` はこの旗を付ける
                "scored": True,
                "score": 95,
                "category_report": [{"category": "UX", "score": 95}]
            },
            "metadata": {
                "titles": ["title1"],
                "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
                "chapters": ["chapter1"]
            },
            "stage_results": [
                {"name": "文字起こし", "success": True, "duration": 1.2, "detail": "テキスト抽出完了"},
                {"name": "AI校閲", "success": True, "detail": "校閲完了", "retries": 1},
                {"name": "SmartCut", "success": True, "detail": "カット完了"},
                {"name": "プレビュー", "success": True, "duration": 5.0},
                {"name": "品質", "success": True},
                {"name": "レンダリング", "success": True},
                {"name": "YouTube", "success": True},
                {"name": "サムネイル", "success": True}
            ]
        }
    }.get(key, default)
    
    mock_probe = {
        "video_codec": "h264",
        "audio_codec": "aac",
        "duration_sec": 60.0,
        "valid": True
    }
    
    with patch("routers.pipeline_report._probe_video", return_value=mock_probe):
        response = client.get("/api/pipeline/report")
        assert response.status_code == 200
        # HTMLレスポンスであることを確認
        assert "text/html" in response.headers["content-type"]
        # 全機能適用済み/合格が含まれることを確認
        assert "全機能適用済み完成動画" in response.text
        assert "✅" in response.text
        assert "文字起こし" in response.text
        assert "UX" in response.text


@patch("routers.pipeline_router._pipeline_state")
def test_pipeline_report_some_fail(mock_state):
    """一部の機能適用に失敗、または未カバーがあるレポートページの表示テスト"""
    mock_state.get.side_effect = lambda key, default=None: {
        "status": "failed",
        "result": {
            "segments_count": 0,
            "stage_results": [
                {"name": "文字起こし", "success": False}
            ]
        }
    }.get(key, default)
    
    response = client.get("/api/pipeline/report")
    assert response.status_code == 200
    assert "改善余地あり" in response.text
    assert "❌" in response.text
    assert "セグメントなし" in response.text
