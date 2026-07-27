"""
M2.6 Batch 2: 0%脱出テスト（color_grading + routers/quality）

- color_grading.py: sys.modules事前注入でimportチェーン問題を回避
- routers/quality.py: FastAPI TestClient パターン
"""

import pytest
import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


# ============================================================
# color_grading.py テスト（方針A: sys.modules事前注入）
# ============================================================

# progressive_preview / progressive_preview_report / preview_report_generator のimportチェーンを事前にモック
# (pydanticモデルを含まないため Python 3.13 でも安全)
sys.modules.setdefault("progressive_preview", MagicMock())
sys.modules.setdefault("progressive_preview_report", MagicMock())
sys.modules.setdefault("preview_report_generator", MagicMock())

# color_grading.py はモジュールレベルで ColorGrading() を呼ぶが、
# FFmpegが見つからないとRuntimeError。shutil.whichをモックしてからimport
with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
    from color_grading import ColorGrading


class TestColorGrading:

    def test_presets_defined(self):
        """全プリセットが定義されている"""
        assert "cinematic" in ColorGrading.PRESETS
        assert "warm" in ColorGrading.PRESETS
        assert "cool" in ColorGrading.PRESETS
        assert "vintage" in ColorGrading.PRESETS
        assert "vibrant" in ColorGrading.PRESETS
        assert "none" in ColorGrading.PRESETS

    def test_init_ffmpeg_found(self, tmp_path):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            cg = ColorGrading()
        assert cg.ffmpeg == "/usr/bin/ffmpeg"

    def test_init_ffmpeg_not_found(self):
        with patch("shutil.which", return_value=None):
            with patch("color_grading.Path.exists", return_value=False):
                cg = ColorGrading()
                assert cg.ffmpeg is None
                with pytest.raises(RuntimeError, match="FFmpeg not found"):
                    cg.apply_preset("dummy.mp4", "cinematic")

    def test_apply_preset_file_not_found(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            cg = ColorGrading()
        with pytest.raises(FileNotFoundError):
            cg.apply_preset("/nonexistent.mp4", "cinematic")

    def test_apply_preset_unknown(self, tmp_path):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            cg = ColorGrading()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake")
        with pytest.raises(ValueError, match="Unknown preset"):
            cg.apply_preset(str(video), "invalid_preset")

    def test_apply_preset_none_copies(self, tmp_path):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            cg = ColorGrading()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake video")
        with patch("color_grading.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock()
            result = cg.apply_preset(str(video), "none")
        assert "graded_none" in result

    def test_apply_preset_cinematic(self, tmp_path):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            cg = ColorGrading()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake video")
        with patch("color_grading.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock()
            result = cg.apply_preset(str(video), "cinematic")
        assert "graded_cinematic" in result

    def test_apply_custom_lut_file_not_found(self):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            cg = ColorGrading()
        with pytest.raises(FileNotFoundError):
            cg.apply_custom_lut("/nonexistent.mp4", "/lut.cube")

    def test_apply_custom_lut_lut_not_found(self, tmp_path):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            cg = ColorGrading()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake")
        with pytest.raises(FileNotFoundError):
            cg.apply_custom_lut(str(video), "/nonexistent.cube")

    def test_init_ffmpeg_local_fallback(self):
        with patch("shutil.which", return_value=None):
            with patch("color_grading.Path.exists", return_value=True):
                cg = ColorGrading()
        assert "ffmpeg.exe" in cg.ffmpeg

    def test_apply_preset_preview_exception(self, tmp_path):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            cg = ColorGrading()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake video")
        
        # ProgressivePreview が例外を投げるように設定
        with patch("color_grading.ProgressivePreview") as mock_pp_cls:
            mock_pp_inst = MagicMock()
            mock_pp_inst.snapshot_step.side_effect = RuntimeError("Preview generation failed")
            mock_pp_cls.return_value = mock_pp_inst
            
            with patch("color_grading.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock()
                result = cg.apply_preset(str(video), "cinematic")
                
        assert "graded_cinematic" in result

    def test_apply_preset_preview_exception_logged(self, tmp_path):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            cg = ColorGrading()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake video")
        
        # ProgressivePreview が例外を投げるように設定
        with patch("color_grading.ProgressivePreview") as mock_pp_cls,              patch("color_grading.logger") as mock_logger:
            mock_pp_inst = MagicMock()
            mock_pp_inst.snapshot_step.side_effect = RuntimeError("Preview disk full")
            mock_pp_cls.return_value = mock_pp_inst
            
            with patch("color_grading.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock()
                result = cg.apply_preset(str(video), "cinematic")
                
        assert "graded_cinematic" in result
        mock_logger.warning.assert_called_once()
        assert "Preview generation failed" in mock_logger.warning.call_args[0][0]

    def test_apply_preset_ffmpeg_error(self, tmp_path):
        import subprocess
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            cg = ColorGrading()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake video")
        
        err = subprocess.CalledProcessError(
            returncode=1,
            cmd="ffmpeg",
            stderr=b"ffmpeg processing error"
        )
        with patch("color_grading.subprocess.run", side_effect=err):
            with pytest.raises(RuntimeError, match="Color grading failed: ffmpeg processing error"):
                cg.apply_preset(str(video), "cinematic")

    def test_apply_custom_lut_success(self, tmp_path):
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            cg = ColorGrading()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake video")
        lut = tmp_path / "lut.cube"
        lut.write_bytes(b"fake lut")
        
        with patch("color_grading.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock()
            result = cg.apply_custom_lut(str(video), str(lut))
            
        assert "lut_applied" in result
        args = mock_run.call_args[0][0]
        from color_grading import _escape_filter_path
        assert f"lut3d={_escape_filter_path(str(lut))}" in args

    def test_apply_custom_lut_ffmpeg_error(self, tmp_path):
        import subprocess
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            cg = ColorGrading()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake video")
        lut = tmp_path / "lut.cube"
        lut.write_bytes(b"fake lut")
        
        err = subprocess.CalledProcessError(
            returncode=1,
            cmd="ffmpeg",
            stderr=b"lut filter failure"
        )
        with patch("color_grading.subprocess.run", side_effect=err):
            with pytest.raises(RuntimeError, match="LUT application failed: lut filter failure"):
                cg.apply_custom_lut(str(video), str(lut))


# ============================================================
# routers/quality.py テスト（0%脱出）
# ============================================================

from fastapi.testclient import TestClient
from fastapi import FastAPI


@pytest.fixture
def quality_client():
    """quality router用TestClient"""
    from routers.quality import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestQualityRouter:

    def test_get_threshold(self, quality_client):
        r = quality_client.get("/api/quality/threshold")
        assert r.status_code == 200
        data = r.json()
        assert data["pass_threshold"] == 90

    def test_quality_check(self, quality_client):
        mock_qg = MagicMock()
        mock_qg.comprehensive_check.return_value = {"score": 85, "passed": True}
        with patch.dict("sys.modules", {"quality_gate_agent": MagicMock(quality_gate=mock_qg)}):
            r = quality_client.post("/api/quality/check", json={
                "full_text": "テスト文", "scenes": [], "segments": []
            })
        assert r.status_code == 200

    def test_cleanup_dryrun(self, quality_client):
        mock_cm = MagicMock()
        mock_cm.preview.return_value = {"files": []}
        with patch.dict("sys.modules", {"cleanup_manager": MagicMock(cleanup_manager=mock_cm)}):
            r = quality_client.post("/api/quality/cleanup", json={"dry_run": True})
        assert r.status_code == 200

    def test_cleanup_preview(self, quality_client):
        mock_cm = MagicMock()
        mock_cm.preview.return_value = {"files": []}
        with patch.dict("sys.modules", {"cleanup_manager": MagicMock(cleanup_manager=mock_cm)}):
            r = quality_client.get("/api/quality/cleanup/preview")
        assert r.status_code == 200

    def test_storage_stats(self, quality_client):
        mock_cm = MagicMock()
        mock_cm.get_stats.return_value = {"total_mb": 100}
        with patch.dict("sys.modules", {"cleanup_manager": MagicMock(cleanup_manager=mock_cm)}):
            r = quality_client.get("/api/quality/storage/stats")
        assert r.status_code == 200

    def test_apply_suggestion(self, quality_client):
        r = quality_client.post("/api/quality/apply-suggestion", json={
            "suggestion": "テスト改善", "index": 0
        })
        assert r.status_code == 200
        assert r.json()["status"] == "applied"

    def test_undo_suggestion(self, quality_client):
        r = quality_client.post("/api/quality/undo-suggestion", json={
            "suggestion": "テスト改善", "index": 0
        })
        assert r.status_code == 200
        assert r.json()["status"] == "undone"
