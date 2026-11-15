"""字幕の書体を PC とクラウドで揃える（subtitle_font）。"""
from pathlib import Path

import subtitle_font as sf


def test_default_family_is_free_font(monkeypatch):
    monkeypatch.delenv("AVS_SUBTITLE_FONT", raising=False)
    assert sf.family() == "BIZ UDPGothic"


def test_env_overrides_family_for_old_episodes(monkeypatch):
    # 久木田回（v67 まで）は PC で Yu Gothic UI のまま書き出せる
    monkeypatch.setenv("AVS_SUBTITLE_FONT", "Yu Gothic UI")
    assert sf.family() == "Yu Gothic UI"


def test_fontsdir_option_points_to_bundled_dir(tmp_path, monkeypatch):
    (tmp_path / "BIZUDPGothic-Regular.ttf").write_bytes(b"x")
    monkeypatch.setattr(sf, "FONT_DIR", tmp_path)
    opt = sf.fontsdir_option()
    assert opt.startswith(":fontsdir='") and opt.endswith("'")
    assert "\\" not in opt.replace("\\:", "")  # Windows の \ は / に、: は \: に


def test_fontsdir_option_empty_when_font_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(sf, "FONT_DIR", tmp_path)
    assert sf.fontsdir_option() == ""


def test_escape_windows_path():
    assert sf.escape_filter_path(r"C:\avs\backend\data\fonts") == "C\\:/avs/backend/data/fonts"


def test_template_style_uses_family(monkeypatch):
    monkeypatch.delenv("AVS_SUBTITLE_FONT", raising=False)
    from template_config import template_config
    assert "FontName=BIZ UDPGothic," in template_config.get_subtitle_style()


def test_smart_cut_fallback_uses_family():
    src = (Path(sf.__file__).parent / "smart_cut_engine.py").read_text(encoding="utf-8")
    assert "FontName=Yu Gothic UI" not in src
    assert "fontsdir_option()" in src


def test_size_matches_pc_look(monkeypatch):
    monkeypatch.delenv("AVS_SUBTITLE_FONT", raising=False)
    assert sf.size(16) == 11
    monkeypatch.setenv("AVS_SUBTITLE_FONT", "Yu Gothic UI")
    assert sf.size(16) == 16


def test_template_style_scales_size(monkeypatch):
    monkeypatch.delenv("AVS_SUBTITLE_FONT", raising=False)
    from template_config import template_config
    assert "FontSize=11," in template_config.get_subtitle_style()
