"""完成版に左上のロゴを足すかどうかの決まり（backend/config/logo.json）。"""
import json

import pytest

import logo_policy
import smart_cut_engine


@pytest.fixture
def setting(tmp_path, monkeypatch):
    path = tmp_path / "logo.json"

    def write(enabled):
        path.write_text(json.dumps({"enabled": enabled}), encoding="utf-8")

    monkeypatch.setattr(logo_policy, "SETTING", path)
    monkeypatch.delenv("AVS_LOGO", raising=False)
    return write


def test_the_shipped_setting_leaves_the_logo_out():
    # 2026-10-22 北原さん: ロゴなしをフェーズ1完了動画にする
    assert json.loads(logo_policy.SETTING.read_text(encoding="utf-8"))["enabled"] is False


def test_the_setting_decides(setting):
    setting(False)
    assert logo_policy.logo_enabled() is False
    setting(True)
    assert logo_policy.logo_enabled() is True


def test_the_environment_overrides_one_run(setting, monkeypatch):
    setting(False)
    monkeypatch.setenv("AVS_LOGO", "on")
    assert logo_policy.logo_enabled() is True
    setting(True)
    monkeypatch.setenv("AVS_LOGO", "off")
    assert logo_policy.logo_enabled() is False


def test_a_missing_setting_leaves_the_logo_out(tmp_path, monkeypatch):
    monkeypatch.setattr(logo_policy, "SETTING", tmp_path / "none.json")
    monkeypatch.delenv("AVS_LOGO", raising=False)
    assert logo_policy.logo_enabled() is False


def test_the_burn_has_no_logo_when_off(setting):
    setting(False)
    assert smart_cut_engine._get_logo_path() is None


def test_the_render_worker_skips_the_logo_when_off(setting, monkeypatch):
    from agents.workers.render_worker import RenderWorker

    setting(False)
    called = []
    monkeypatch.setattr("logo_overlay.LogoOverlay.apply_logo", lambda *a, **k: called.append(1))
    RenderWorker()._overlay_logo("/nonexistent/final.mp4")
    assert called == []
