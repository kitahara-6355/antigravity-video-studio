\
import sys
import pytest
from pathlib import Path

# backend ディレクトリを sys.path に追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.shorts_generator import ShortsGenerator, shorts_generator


def test_build_candidate():
    """_build_candidate の単体テスト"""
    sg = ShortsGenerator()
    candidate = sg._build_candidate(
        video_id="vid123",
        strategy="hook_clip",
        title="フック",
        segments=[{"text": "こんにちは"}, {"text": "テスト"}],
        start=5.0,
        end=15.0,
        priority=1
    )
    assert candidate["id"] == "shorts_vid123_hook_clip_5"
    assert candidate["strategy"] == "hook_clip"
    assert candidate["title"] == "フック"
    assert candidate["start_sec"] == 5.0
    assert candidate["end_sec"] == 15.0
    assert candidate["duration_sec"] == 10.0
    assert candidate["priority"] == 1
    assert candidate["preview_text"] == "こんにちは テスト"
    assert candidate["estimated_views_boost"] == "本編比 3-5x の発見性向上"


def test_estimate_boost_default():
    """_estimate_boost のデフォルトフォールバックテスト"""
    sg = ShortsGenerator()
    boost = sg._estimate_boost("unknown_strategy")
    assert boost == "チャンネル発見性向上"


def test_extract_shorts_candidates_hook_only():
    """戦略1: 冒頭フック抽出のテスト"""
    sg = ShortsGenerator()
    segments = [
        {"start": 0, "end": 4, "text": "フック部分テキスト"},
        {"start": 4, "end": 10, "text": "ここもフック"}
    ]
    res = sg.extract_shorts_candidates(
        segments=segments,
        video_duration_sec=30,
        video_id="vid_hook"
    )
    assert res["success"] is True
    assert res["total_candidates"] == 1
    assert res["candidates"][0]["strategy"] == "hook_clip"
    assert res["candidates"][0]["start_sec"] == 0
    assert res["candidates"][0]["end_sec"] == 15  # min(15, 30)
    assert res["candidates"][0]["priority"] == 1


def test_extract_shorts_candidates_highlight_only():
    """戦略2: ハイライト抽出のテスト"""
    sg = ShortsGenerator()
    segments = [
        {"start": 20, "end": 25, "text": "これはすごい！面白い"}
    ]
    res = sg.extract_shorts_candidates(
        segments=segments,
        video_duration_sec=60,
        video_id="vid_highlight"
    )
    assert res["success"] is True
    assert res["total_candidates"] == 1
    assert res["candidates"][0]["strategy"] == "highlight"
    assert res["candidates"][0]["start_sec"] == 17  # max(0, 20 - 3)
    assert res["candidates"][0]["end_sec"] == 25  # min(25, 17+30)
    assert res["candidates"][0]["priority"] == 2


def test_extract_shorts_candidates_conclusion_only():
    """戦略3: まとめ・結論抽出のテスト"""
    sg = ShortsGenerator()
    # 終盤20%の閾値: 100秒の動画なら80秒以降
    segments = [
        {"start": 85, "end": 95, "text": "まとめです。"}
    ]
    res = sg.extract_shorts_candidates(
        segments=segments,
        video_duration_sec=100,
        video_id="vid_conclusion"
    )
    assert res["success"] is True
    assert res["total_candidates"] == 1
    assert res["candidates"][0]["strategy"] == "conclusion"
    assert res["candidates"][0]["start_sec"] == 85
    assert res["candidates"][0]["end_sec"] == 100  # min(85+45, 100) -> 100
    assert res["candidates"][0]["priority"] == 3


def test_extract_shorts_candidates_all_strategies_and_limit():
    """全戦略が混在し、最大5件制限がかかる場合のテスト"""
    sg = ShortsGenerator()
    segments = [
        # 戦略1: フック
        {"start": 2, "end": 5, "text": "フックだぞ"},
        # 戦略2: ハイライト 6件
        {"start": 20, "end": 25, "text": "すごい"},
        {"start": 30, "end": 35, "text": "やばい"},
        {"start": 40, "end": 45, "text": "衝撃"},
        {"start": 50, "end": 55, "text": "最高"},
        {"start": 60, "end": 65, "text": "驚き！"},
        {"start": 70, "end": 75, "text": "なんだって!?"},
        # 戦略3: 結論
        {"start": 90, "end": 95, "text": "結論として"}
    ]
    # 動画長 100秒
    res = sg.extract_shorts_candidates(
        segments=segments,
        video_duration_sec=100,
        video_id="vid_all"
    )
    assert res["success"] is True
    assert res["total_candidates"] == 5
    assert res["candidates"][0]["strategy"] == "hook_clip"
    for i in range(1, 5):
        assert res["candidates"][i]["strategy"] == "highlight"


def test_extract_shorts_candidates_edge_cases():
    """エッジケースに対するテスト (video_duration_sec <= 0 や segments が空、キー/値が None など)"""
    sg = ShortsGenerator()

    # 1. segments が空の場合
    res = sg.extract_shorts_candidates([], 100, "vid_empty")
    assert res["success"] is True
    assert res["total_candidates"] == 0

    # 2. video_duration_sec <= 0 の場合
    res = sg.extract_shorts_candidates([{"start": 0, "text": "フック"}], 0, "vid_zero")
    assert res["success"] is True
    assert res["total_candidates"] == 0

    res = sg.extract_shorts_candidates([{"start": 0, "text": "フック"}], -10, "vid_negative")
    assert res["success"] is True
    assert res["total_candidates"] == 0

    # 3. キー start, end が None または欠落している場合
    segments = [
        {"text": "これはすごい！面白い"},  # start/end 欠落
        {"start": None, "end": None, "text": "やばい！"},  # start/end が None
        {"start": 5, "end": None, "text": "衝撃！"},  # end が None
        {"start": None, "end": 10, "text": "最高！"}  # start が None
    ]
    res = sg.extract_shorts_candidates(segments, 60, "vid_nones")
    assert res["success"] is True
    assert res["total_candidates"] > 0

    # 4. highlight で start >= video_duration_sec の場合 (スキップされる)
    segments = [
        {"start": 100, "end": 105, "text": "すごい！"}
    ]
    res = sg.extract_shorts_candidates(segments, 50, "vid_out_of_bounds")
    assert res["success"] is True
    assert len(res["candidates"]) == 0

    # 5. highlight で end <= start の場合 (スキップされる)
    segments = [
        {"start": 20, "end": 15, "text": "すごい！"}
    ]
    res = sg.extract_shorts_candidates(segments, 50, "vid_invalid_range")
    assert res["success"] is True
    assert len(res["candidates"]) == 0

    # 6. conclusion で start >= video_duration_sec の場合 (スキップされる)
    segments = [
        {"start": 105, "end": 110, "text": "結論"}
    ]
    res = sg.extract_shorts_candidates(segments, 100, "vid_conclusion_out")
    assert res["success"] is True
    assert len(res["candidates"]) == 0


# ============================================================
# Routers/Shorts API エンドポイントのテスト
# ============================================================

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch, AsyncMock

from routers.shorts import router as shorts_router

app = FastAPI()
app.include_router(shorts_router)
client = TestClient(app, raise_server_exceptions=False)


def test_router_extract_shorts_candidates_success():
    """POST /api/shorts/candidates - 正常系"""
    mock_result = {
        "success": True,
        "total_candidates": 1,
        "candidates": [
            {
                "id": "shorts_vid123_hook_clip_5",
                "strategy": "hook_clip",
                "title": "フック",
                "start_sec": 5.0,
                "end_sec": 15.0,
                "duration_sec": 10.0,
                "priority": 1,
                "preview_text": "テストテキスト",
                "estimated_views_boost": "本編比 3-5x の発見性向上"
            }
        ]
    }

    mock_generator = MagicMock()
    mock_generator.extract_shorts_candidates.return_value = mock_result

    with patch.dict(sys.modules, {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.post(
            "/api/shorts/candidates",
            json={
                "segments": [{"start": 5.0, "end": 15.0, "text": "テストテキスト"}],
                "video_duration_sec": 100,
                "video_id": "vid123"
            }
        )
        assert response.status_code == 200
        assert response.json() == mock_result


def test_router_extract_shorts_candidates_exception():
    """POST /api/shorts/candidates - 一般例外発生時"""
    mock_generator = MagicMock()
    mock_generator.extract_shorts_candidates.side_effect = Exception("Test generator failure")

    with patch.dict(sys.modules, {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.post(
            "/api/shorts/candidates",
            json={
                "segments": [],
                "video_duration_sec": 100,
                "video_id": "vid123"
            }
        )
        assert response.status_code == 500
        assert "Test generator failure" in response.json()["detail"]


def test_router_extract_shorts_candidates_http_exception():
    """POST /api/shorts/candidates - HTTPException 発生時 (そのまま透過)"""
    mock_generator = MagicMock()
    mock_generator.extract_shorts_candidates.side_effect = HTTPException(status_code=400, detail="Invalid duration")

    with patch.dict(sys.modules, {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.post(
            "/api/shorts/candidates",
            json={
                "segments": [],
                "video_duration_sec": -10,
                "video_id": "vid123"
            }
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid duration"


def test_router_generate_shorts_success():
    """POST /api/shorts/generate - 正常系"""
    mock_clip = MagicMock()
    mock_clip.id = "clip_001"
    mock_clip.title = "ハイライト1"
    mock_clip.highlight_type = "highlight"
    mock_clip.start_time = 10.0
    mock_clip.end_time = 25.0
    mock_clip.duration = 15.0
    mock_clip.output_path = "/path/to/output.mp4"
    mock_clip.status = "completed"

    mock_result = MagicMock()
    mock_result.total_clips = 1
    mock_result.completed_clips = 1
    mock_result.clips = [mock_clip]
    mock_result.output_dir = "/path/to/output"
    mock_result.message = "Shorts generated successfully"

    mock_generator = MagicMock()
    mock_generator.generate_from_highlights = AsyncMock(return_value=mock_result)

    with patch.dict(sys.modules, {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.post(
            "/api/shorts/generate",
            json={
                "video_path": "test.mp4",
                "highlights": [{"start": 10.0, "end": 25.0, "text": "ハイライト1"}],
                "task_id": "task_123"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total_clips"] == 1
        assert data["completed_clips"] == 1
        assert data["clips"][0]["id"] == "clip_001"


def test_router_generate_shorts_exception():
    """POST /api/shorts/generate - 一般例外発生時"""
    mock_generator = MagicMock()
    mock_generator.generate_from_highlights = AsyncMock(side_effect=Exception("Generation logic crashed"))

    with patch.dict(sys.modules, {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.post(
            "/api/shorts/generate",
            json={
                "video_path": "test.mp4",
                "highlights": [],
                "task_id": "task_123"
            }
        )
        assert response.status_code == 500
        assert "Generation logic crashed" in response.json()["detail"]


def test_router_list_shorts_success():
    """GET /api/shorts/list - 正常系"""
    mock_clips = [
        {"id": "clip_1", "title": "clip 1", "output_path": "out1.mp4"}
    ]
    mock_generator = MagicMock()
    mock_generator.get_clip_list.return_value = mock_clips

    with patch.dict(sys.modules, {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.get("/api/shorts/list?task_id=task_123")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["clips"] == mock_clips


def test_router_list_shorts_exception():
    """GET /api/shorts/list - 一般例外発生時"""
    mock_generator = MagicMock()
    mock_generator.get_clip_list.side_effect = Exception("Database unreadable")

    with patch.dict(sys.modules, {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.get("/api/shorts/list")
        assert response.status_code == 500
        assert "Database unreadable" in response.json()["detail"]


def test_router_export_shorts_success():
    """POST /api/shorts/export - 正常系（クリップが見つかった場合）"""
    mock_clips = [
        {"id": "clip_1", "title": "clip 1"},
        {"id": "clip_2", "title": "clip 2"}
    ]
    mock_generator = MagicMock()
    mock_generator.get_clip_list.return_value = mock_clips

    with patch.dict(sys.modules, {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.post(
            "/api/shorts/export",
            json={
                "clip_ids": ["clip_1"],
                "format": "mp4",
                "task_id": "task_123"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["export_count"] == 1


def test_router_export_shorts_not_found():
    """POST /api/shorts/export - 指定されたクリップが見つからない場合"""
    mock_clips = [
        {"id": "clip_1", "title": "clip 1"}
    ]
    mock_generator = MagicMock()
    mock_generator.get_clip_list.return_value = mock_clips

    with patch.dict(sys.modules, {"services.shorts_generator": MagicMock(shorts_generator=mock_generator)}):
        response = client.post(
            "/api/shorts/export",
            json={
                "clip_ids": ["clip_nonexistent"],
                "format": "mp4",
                "task_id": "task_123"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "見つかりませんでした" in data["message"]


def test_router_render_short_invalid_duration():
    """**R2-C1 で閉じた経路**（2026-09-25）。入力の良し悪しで挙動を変えない（かつて 400）

    承認を1件も見ずに 1080x1920 の完成動画を書いていたので閉じた。
    見るものは「書き出さないこと」に変わった。
    """
    response = client.post(
        "/api/shorts/render",
        json={"video_path": "/v.mp4", "start_sec": 0.0, "end_sec": 10.0},
    )
    assert response.status_code == 409
    assert "承認" in response.json()["detail"]

def test_router_render_short_success():
    """**R2-C1 で閉じた経路**（2026-09-25）。正常系だった（かつて 200）

    承認を1件も見ずに 1080x1920 の完成動画を書いていたので閉じた。
    見るものは「書き出さないこと」に変わった。
    """
    response = client.post(
        "/api/shorts/render",
        json={"video_path": "/v.mp4", "start_sec": 0.0, "end_sec": 10.0},
    )
    assert response.status_code == 409
    assert "承認" in response.json()["detail"]

def test_router_render_short_ffmpeg_not_available():
    """**R2-C1 で閉じた経路**（2026-09-25）。FFmpeg 不在の扱いだった（かつて 500）

    承認を1件も見ずに 1080x1920 の完成動画を書いていたので閉じた。
    見るものは「書き出さないこと」に変わった。
    """
    response = client.post(
        "/api/shorts/render",
        json={"video_path": "/v.mp4", "start_sec": 0.0, "end_sec": 10.0},
    )
    assert response.status_code == 409
    assert "承認" in response.json()["detail"]

def test_router_render_short_ffmpeg_command_failed():
    """**R2-C1 で閉じた経路**（2026-09-25）。FFmpeg 失敗の扱いだった（かつて 500）

    承認を1件も見ずに 1080x1920 の完成動画を書いていたので閉じた。
    見るものは「書き出さないこと」に変わった。
    """
    response = client.post(
        "/api/shorts/render",
        json={"video_path": "/v.mp4", "start_sec": 0.0, "end_sec": 10.0},
    )
    assert response.status_code == 409
    assert "承認" in response.json()["detail"]

def test_router_render_short_general_exception():
    """**R2-C1 で閉じた経路**（2026-09-25）。内部例外の扱いだった（かつて 500）

    承認を1件も見ずに 1080x1920 の完成動画を書いていたので閉じた。
    見るものは「書き出さないこと」に変わった。
    """
    response = client.post(
        "/api/shorts/render",
        json={"video_path": "/v.mp4", "start_sec": 0.0, "end_sec": 10.0},
    )
    assert response.status_code == 409
    assert "承認" in response.json()["detail"]

def test_router_shorts_health():
    """GET /api/shorts/health - 正常系"""
    response = client.get("/api/shorts/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "shorts_generator"}
