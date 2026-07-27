import pytest
from unittest.mock import patch, MagicMock
import json
import sys
import os
import shutil
from pathlib import Path

class TestThemesRouterCoverage:
    def _get_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers.themes_router import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    @pytest.fixture(autouse=True)
    def manage_evolution_log(self):
        log_path = Path(__file__).parent.parent.parent / "branding" / "evolution_log.json"
        
        backup_path = log_path.with_name("evolution_log.json.bak_test")
        
        existed = log_path.exists()
        if existed:
            shutil.copy2(log_path, backup_path)
            
        yield log_path
        
        if log_path.exists():
            os.remove(log_path)
        if existed:
            shutil.move(backup_path, log_path)

    def test_health_check(self):
        client = self._get_client()
        res = client.get("/themes/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert "templates_count" in data
        assert "themes_count" in data

    def test_apply_import_error_and_exceptions(self):
        # 1) ImportError in template_config
        with patch.dict("sys.modules", {"template_config": None}):
            mock_dtm = MagicMock()
            mock_dtm.update_tokens.return_value = {"updated": True}
            with patch("design_system.design_token_manager.design_token_manager", mock_dtm), \
                 patch("routers.themes_router._record_template_selection"):
                client = self._get_client()
                res = client.post("/themes/apply", json={
                    "template_id": "nhk_documentary", "theme_id": "warm"
                })
                assert res.status_code == 200
                assert res.json()["status"] == "applied"

        # 2) HTTPException inside apply_template_and_theme
        from fastapi import HTTPException
        mock_dtm = MagicMock()
        mock_dtm.update_tokens.side_effect = HTTPException(status_code=400, detail="Test HTTP Error")
        mock_config = MagicMock()
        with patch("design_system.design_token_manager.design_token_manager", mock_dtm), \
             patch("template_config.template_config", mock_config), \
             patch("routers.themes_router._record_template_selection"):
            client = self._get_client()
            res = client.post("/themes/apply", json={
                "template_id": "nhk_documentary", "theme_id": "warm"
            })
            assert res.status_code == 400
            assert res.json()["detail"] == "Test HTTP Error"

        # 3) Generic Exception inside apply_template_and_theme
        mock_dtm = MagicMock()
        mock_dtm.update_tokens.side_effect = RuntimeError("Generic Error")
        mock_config = MagicMock()
        with patch("design_system.design_token_manager.design_token_manager", mock_dtm), \
             patch("template_config.template_config", mock_config), \
             patch("routers.themes_router._record_template_selection"):
            client = self._get_client()
            res = client.post("/themes/apply", json={
                "template_id": "nhk_documentary", "theme_id": "warm"
            })
            assert res.status_code == 500
            assert "Generic Error" in res.json()["detail"]

    def test_get_current_config_variations(self):
        # 1) With history
        mock_dtm = MagicMock()
        mock_dtm.get_change_history.return_value = [
            {"mood": "warm", "timestamp": "2026-05-22T00:00:00", "reason": "applied 📺 NHKドキュメンタリー風"}
        ]
        with patch("design_system.design_token_manager.design_token_manager", mock_dtm):
            client = self._get_client()
            res = client.get("/themes/current/active")
            assert res.status_code == 200
            data = res.json()
            assert data["template"]["id"] == "nhk_documentary"
            assert data["theme"]["id"] == "warm"

        # 2) Without history
        mock_dtm.get_change_history.return_value = []
        with patch("design_system.design_token_manager.design_token_manager", mock_dtm):
            client = self._get_client()
            res = client.get("/themes/current/active")
            assert res.status_code == 200
            data = res.json()
            assert data["template"] is None
            assert data["theme"] is None

        # 3) HTTPException in current config
        from fastapi import HTTPException
        mock_dtm.get_change_history.side_effect = HTTPException(status_code=401, detail="Unauthorized")
        with patch("design_system.design_token_manager.design_token_manager", mock_dtm):
            client = self._get_client()
            res = client.get("/themes/current/active")
            assert res.status_code == 401

        # 4) Exception in current config
        mock_dtm.get_change_history.side_effect = RuntimeError("Fetch failed")
        with patch("design_system.design_token_manager.design_token_manager", mock_dtm):
            client = self._get_client()
            res = client.get("/themes/current/active")
            assert res.status_code == 500
            assert "Fetch failed" in res.json()["detail"]

    def test_get_template_stats_variations(self, manage_evolution_log):
        log_path = manage_evolution_log
        client = self._get_client()
        
        # 0) Log doesn't exist
        if log_path.exists():
            os.remove(log_path)
        res = client.get("/themes/stats")
        assert res.status_code == 200
        assert res.json() == {"stats": {}, "total_selections": 0}

        # 1) Log exists and has selections
        log_data = {
            "template_selections": [
                {"template_id": "nhk_documentary", "theme_id": "warm", "satisfaction": 4},
                {"template_id": "nhk_documentary", "theme_id": "cool", "satisfaction": 5},
                {"template_id": "mrbeast_entertainment", "theme_id": "energetic", "satisfaction": 2}
            ]
        }
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps(log_data), encoding="utf-8")

        res = client.get("/themes/stats")
        assert res.status_code == 200
        data = res.json()
        assert data["total_selections"] == 3
        assert data["by_template"]["nhk_documentary"] == 2
        assert data["avg_satisfaction"]["nhk_documentary"] == 4.5

        # 2) Exceptions (HTTPException and Exception)
        original_exists = Path.exists
        def mock_exists_http(self_path):
            if "evolution_log.json" in str(self_path):
                from fastapi import HTTPException
                raise HTTPException(status_code=403, detail="Forbidden")
            return original_exists(self_path)

        with patch("pathlib.Path.exists", side_effect=mock_exists_http, autospec=True):
            res = client.get("/themes/stats")
            assert res.status_code == 403

        def mock_exists_exc(self_path):
            if "evolution_log.json" in str(self_path):
                raise RuntimeError("Read error")
            return original_exists(self_path)

        with patch("pathlib.Path.exists", side_effect=mock_exists_exc, autospec=True):
            res = client.get("/themes/stats")
            assert res.status_code == 500
            assert "Read error" in res.json()["detail"]

    def test_recommend_template_variations(self):
        # 1) Normal recommendation
        mock_rec = MagicMock()
        mock_rec.recommend.return_value = ("nhk_documentary", {"score": 9.5, "reasons": ["test"], "profile": {}})
        mock_rec.recommend_with_alternatives.return_value = []
        
        # We patch sys.modules to mock template_recommender import
        fake_recommender = MagicMock()
        fake_recommender.template_recommender = mock_rec
        with patch.dict("sys.modules", {"template_recommender": fake_recommender}):
            client = self._get_client()
            res = client.post("/themes/recommend", json={"segments": [], "total_duration_seconds": 10})
            assert res.status_code == 200
            assert res.json()["recommended"]["template_id"] == "nhk_documentary"

        # 2) ImportError in template_recommender
        with patch.dict("sys.modules", {"template_recommender": None}):
            # This triggers ImportError inside themes_router because template_recommender is None
            client = self._get_client()
            res = client.post("/themes/recommend", json={})
            assert res.status_code == 500
            assert "detail" in res.json()
            assert "template_recommender not available" in res.json()["detail"]

        # 3) HTTPException in recommend
        from fastapi import HTTPException
        mock_rec = MagicMock()
        mock_rec.recommend.side_effect = HTTPException(status_code=400, detail="Recommend HTTP error")
        fake_recommender = MagicMock()
        fake_recommender.template_recommender = mock_rec
        with patch.dict("sys.modules", {"template_recommender": fake_recommender}):
            client = self._get_client()
            res = client.post("/themes/recommend", json={})
            assert res.status_code == 400

        # 4) Exception in recommend
        mock_rec = MagicMock()
        mock_rec.recommend.side_effect = RuntimeError("Recommend failed")
        fake_recommender = MagicMock()
        fake_recommender.template_recommender = mock_rec
        with patch.dict("sys.modules", {"template_recommender": fake_recommender}):
            client = self._get_client()
            res = client.post("/themes/recommend", json={})
            assert res.status_code == 500
            assert "Recommend failed" in res.json()["detail"]

    def test_apply_template_overrides_variations(self):
        # 1) template_config not active
        mock_config = MagicMock()
        mock_config.is_active = False
        with patch("template_config.template_config", mock_config):
            client = self._get_client()
            res = client.post("/themes/override", json={"overrides": {}})
            assert res.status_code == 400
            assert "テンプレートが未選択" in res.json()["detail"]

        # 2) template_config active and success
        mock_config.is_active = True
        mock_config.template_id = "nhk_documentary"
        with patch("template_config.template_config", mock_config):
            client = self._get_client()
            res = client.post("/themes/override", json={"overrides": {"key": "val"}})
            assert res.status_code == 200
            assert res.json()["status"] == "overridden"

        # 3) ImportError in template_config
        with patch.dict("sys.modules", {"template_config": None}):
            client = self._get_client()
            res = client.post("/themes/override", json={})
            assert res.status_code == 500
            assert "template_config not available" in res.json()["detail"]

    def test_record_template_selection_variations(self, manage_evolution_log):
        from routers.themes_router import _record_template_selection
        log_path = manage_evolution_log

        # 1) Log doesn't exist
        if log_path.exists():
            os.remove(log_path)
        _record_template_selection("nhk_documentary", "warm")
        assert log_path.exists()
        data = json.loads(log_path.read_text(encoding="utf-8"))
        assert len(data["template_selections"]) == 1

        # 2) Log exists
        _record_template_selection("nhk_documentary", "warm")
        data = json.loads(log_path.read_text(encoding="utf-8"))
        assert len(data["template_selections"]) == 2

        # 3) Exception raised
        original_write_text = Path.write_text
        def mock_write_text(self_path, *args, **kwargs):
            if "evolution_log.json" in str(self_path):
                raise RuntimeError("Disk full")
            return original_write_text(self_path, *args, **kwargs)

        with patch("pathlib.Path.write_text", side_effect=mock_write_text, autospec=True):
            # Should not raise exception
            _record_template_selection("nhk_documentary", "warm")

    def test_list_templates_and_details(self):
        client = self._get_client()
        # 1) list templates
        res = client.get("/themes/templates")
        assert res.status_code == 200
        data = res.json()
        assert "templates" in data
        assert data["count"] > 0

        # 2) get specific template (success)
        res = client.get("/themes/templates/nhk_documentary")
        assert res.status_code == 200
        assert res.json()["template"]["id"] == "nhk_documentary"

        # 3) get specific template (not found)
        res = client.get("/themes/templates/nonexistent_template")
        assert res.status_code == 404
        assert "detail" in res.json()

    def test_list_themes_and_details(self):
        client = self._get_client()
        # 1) list themes
        res = client.get("/themes")
        assert res.status_code == 200
        data = res.json()
        assert "themes" in data
        assert data["count"] > 0

        # 2) get specific theme (success)
        res = client.get("/themes/warm")
        assert res.status_code == 200
        assert res.json()["theme"]["id"] == "warm"

        # 3) get specific theme (not found)
        res = client.get("/themes/nonexistent_theme")
        assert res.status_code == 404
        assert "detail" in res.json()

    def test_apply_template_and_theme_success(self):
        mock_dtm = MagicMock()
        mock_dtm.update_tokens.return_value = {"updated": True}
        mock_config = MagicMock()
        with patch("design_system.design_token_manager.design_token_manager", mock_dtm), \
             patch("template_config.template_config", mock_config), \
             patch("routers.themes_router._record_template_selection"):
            client = self._get_client()
            res = client.post("/themes/apply", json={
                "template_id": "nhk_documentary",
                "theme_id": "warm",
                "reason": "JUnit Test Reason"
            })
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "applied"
            assert data["template"]["id"] == "nhk_documentary"
            assert data["theme"]["id"] == "warm"
            assert data["pipeline_connected"] is True
            assert "quality_standards" in data

    def test_apply_template_and_theme_validation_errors(self):
        client = self._get_client()
        # 1) Invalid template
        res = client.post("/themes/apply", json={"template_id": "invalid", "theme_id": "warm"})
        assert res.status_code == 400
        assert "Template 'invalid' not found" in res.json()["detail"]

        # 2) Invalid theme
        res = client.post("/themes/apply", json={"template_id": "nhk_documentary", "theme_id": "invalid"})
        assert res.status_code == 400
        assert "Theme 'invalid' not found" in res.json()["detail"]

    def test_get_template_not_found(self):
        client = self._get_client()
        res = client.get("/themes/templates/nonexistent")
        assert res.status_code == 404
        assert "Template 'nonexistent' not found" in res.json()["detail"]

    def test_get_theme_not_found(self):
        client = self._get_client()
        res = client.get("/themes/nonexistent")
        assert res.status_code == 404
        assert "Theme 'nonexistent' not found" in res.json()["detail"]

    def test_exceptions_register_technical_debt(self):
        mock_rec = MagicMock()
        mock_rec.recommend.side_effect = RuntimeError("Recommend test error")
        fake_recommender = MagicMock()
        fake_recommender.template_recommender = mock_rec
        
        with patch.dict("sys.modules", {"template_recommender": fake_recommender}), \
             patch("routers.themes_router._register_router_technical_debt") as mock_tdr:
            client = self._get_client()
            res = client.post("/themes/recommend", json={})
            assert res.status_code == 500
            mock_tdr.assert_called_once()
            called_kwargs = mock_tdr.call_args[1]
            assert "Recommend test error" in called_kwargs["notes"]

    def test_generate_theme_thumbnail_success(self):
        client = self._get_client()
        with patch("PIL.Image.new") as mock_new, \
             patch("combined_overlay.CombinedOverlay") as mock_overlay, \
             patch("os.path.exists", return_value=True), \
             patch("os.remove"), \
             patch("os.rename"):
            
            mock_img = MagicMock()
            mock_new.return_value = mock_img
            
            mock_ov_instance = MagicMock()
            mock_ov_instance.validate_thumbnail.return_value = {"valid": True}
            mock_overlay.return_value = mock_ov_instance
            
            res = client.post("/themes/thumbnail", json={
                "theme_id": "warm",
                "text": "Hello Warm",
                "output_path": "dummy_path.png"
            })
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "success"
            assert data["theme_id"] == "warm"
            assert data["validation"]["valid"] is True

    def test_generate_theme_thumbnail_invalid_theme(self):
        client = self._get_client()
        res = client.post("/themes/thumbnail", json={
            "theme_id": "invalid_theme"
        })
        assert res.status_code == 400
        assert "Theme 'invalid_theme' not found" in res.json()["detail"]

    def test_generate_theme_thumbnail_exception_registration(self):
        client = self._get_client()
        with patch("PIL.Image.new", side_effect=RuntimeError("Pillow crashed")), \
             patch("routers.themes_router._register_router_technical_debt") as mock_tdr, \
             patch("os.path.exists", return_value=False):
            
            res = client.post("/themes/thumbnail", json={
                "theme_id": "warm",
                "output_path": "dummy_path.png"
            })
            assert res.status_code == 500
            assert "Pillow crashed" in res.json()["detail"]
            mock_tdr.assert_called_once()
            called_kwargs = mock_tdr.call_args[1]
            assert "Pillow crashed" in called_kwargs["notes"]

    def test_specific_exception_types_handling(self):
        # 具体的例外のハンドリング検証
        client = self._get_client()
        
        # 1) recommend_template で TypeError が発生した場合
        mock_rec = MagicMock()
        mock_rec.recommend.side_effect = TypeError("Recommend mock type error")
        fake_recommender = MagicMock()
        fake_recommender.template_recommender = mock_rec
        
        with patch.dict("sys.modules", {"template_recommender": fake_recommender}),              patch("routers.themes_router._register_router_technical_debt") as mock_tdr:
            res = client.post("/themes/recommend", json={})
            assert res.status_code == 500
            assert "Recommend mock type error" in res.json()["detail"]
            mock_tdr.assert_called_once()
            called_kwargs = mock_tdr.call_args[1]
            assert "TypeError" in called_kwargs["pattern"]

        # 2) apply_template_and_theme 内で _record_template_selection が KeyError を投げた場合
        mock_dtm = MagicMock()
        mock_dtm.update_tokens.return_value = {"updated": True}
        mock_config = MagicMock()
        with patch("design_system.design_token_manager.design_token_manager", mock_dtm),              patch("template_config.template_config", mock_config),              patch("routers.themes_router._record_template_selection", side_effect=KeyError("Selection key error")),              patch("routers.themes_router._register_router_technical_debt"):
            res = client.post("/themes/apply", json={
                "template_id": "nhk_documentary", "theme_id": "warm"
            })
            assert res.status_code == 200
            assert res.json()["status"] == "applied"

    def test_import_errors_pattern_registration(self):
        # design_token_manager が無いときの ImportError 時のパターン登録検証
        with patch.dict("sys.modules", {"design_system.design_token_manager": None}),              patch("routers.themes_router._register_router_technical_debt") as mock_tdr,              patch("template_config.template_config", MagicMock()):
            client = self._get_client()
            res = client.post("/themes/apply", json={
                "template_id": "nhk_documentary", "theme_id": "warm"
            })
            assert res.status_code == 500
            mock_tdr.assert_called_once()
            called_kwargs = mock_tdr.call_args[1]
            assert called_kwargs["pattern"] == "except ImportError:"
            assert called_kwargs["line_number"] == 268
