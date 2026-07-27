"""ダッシュボードのリンクがリポジトリ相対で、環境に依存しないことの検証

以前は `file:///C:/Users/.../script/video-automation/...` という **生成した環境の絶対パス**
で記録していた。取り違えのない書き方として導入されたものだが、

  - 別のチェックアウト（worktree）や CI(Linux) では 1 本も解決できない
  - ユーザーのフォルダ構成が変わると全リンクが死ぬ
  - リポジトリを配布・クローンした先で無意味な文字列になる

という環境依存を持ち込んでいた。リポジトリ内のファイルはリポジトリ相対で正確に書けるため、
相対リンクに統一する。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.agents.orchestration.link_validator import (  # noqa: E402
    WORKSPACE_DIR,
    get_rel_link,
    localize_links,
    validate_dashboard_links,
)

DASHBOARD_DIR = os.path.join(WORKSPACE_DIR, "Human01_Official Artifact", "サブエージェント体制報告")


class TestGetRelLink:
    def test_repo_file_becomes_relative(self):
        """リポジトリ内のファイルは、ドライブレターもホームディレクトリも含まない"""
        target = os.path.join(WORKSPACE_DIR, "backend", "agents", "orchestration", "link_validator.py")
        link = get_rel_link(target)

        assert link == "backend/agents/orchestration/link_validator.py"
        assert "file:///" not in link
        assert ":" not in link, f"ドライブレターが残っている: {link}"
        assert not link.startswith("/"), f"絶対パスになっている: {link}"

    def test_spaces_and_unicode_are_encoded(self):
        """スペースと非ASCIIは URL エンコードする（Markdown のリンクが壊れないため）"""
        target = os.path.join(DASHBOARD_DIR, "README.md")
        link = get_rel_link(target)

        assert "%20" in link, f"スペースが未エンコード: {link}"
        assert "サブエージェント" not in link, f"非ASCIIが未エンコード: {link}"
        assert link.startswith("Human01_Official%20Artifact/")

    def test_path_outside_repository_falls_back_to_absolute(self):
        """リポジトリ外は相対で書けないので file:/// にフォールバックする"""
        outside = os.path.join(os.path.expanduser("~"), ".gemini", "brain", "daily_report.md")
        link = get_rel_link(outside)

        assert link.startswith("file:///") or link.startswith("file://")

    def test_invalid_input(self):
        assert get_rel_link(None) == ""
        assert get_rel_link(123) == ""


class TestLocalizeLinks:
    """同じ本文を深さの違う README に書き出すため、書き込み先に合わせて付け替える"""

    def test_repo_root_target_is_unchanged(self):
        md = "- [報告](Human01_Official%20Artifact/a.md)\n"
        assert localize_links(md, WORKSPACE_DIR) == md

    def test_nested_target_gets_relative_path(self):
        """書き込み先から見た最短の相対パスになる（../.. を無条件に付けない）"""
        md = "- [報告](Human01_Official%20Artifact/a.md)\n"
        out = localize_links(md, DASHBOARD_DIR)
        assert out == "- [報告](../a.md)\n"

    def test_link_inside_target_dir_has_no_prefix(self):
        md = "- [報告](Human01_Official%20Artifact/%E3%82%B5%E3%83%96%E3%82%A8%E3%83%BC%E3%82%B8%E3%82%A7%E3%83%B3%E3%83%88%E4%BD%93%E5%88%B6%E5%A0%B1%E5%91%8A/x/y.md)\n"
        assert localize_links(md, DASHBOARD_DIR) == "- [報告](x/y.md)\n"

    def test_link_to_repo_root_file(self):
        md = "- [README](README.md)\n"
        assert localize_links(md, DASHBOARD_DIR) == "- [README](../../README.md)\n"

    def test_external_and_anchor_links_untouched(self):
        md = (
            "[web](https://example.com/x)\n"
            "[anchor](#section)\n"
            "[legacy](file:///C:/tmp/x.md)\n"
            "[mail](mailto:a@example.com)\n"
        )
        assert localize_links(md, DASHBOARD_DIR) == md

    def test_encoding_is_preserved(self):
        """付け替えでエンコードが崩れないこと"""
        md = "[a](%E5%88%86%E8%A7%A3/x.md)\n[b](docs/My%20Notes/y.md)"
        out = localize_links(md, DASHBOARD_DIR)
        assert "%E5%88%86%E8%A7%A3" in out, out
        assert "My%20Notes" in out, out
        assert "分解" not in out


class TestValidateDashboardLinks:
    def test_relative_links_resolve_from_the_document(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "exists.md").write_text("x", encoding="utf-8")
        readme = tmp_path / "README.md"
        readme.write_text(
            "- [ok](sub/exists.md)\n- [ng](sub/missing.md)\n", encoding="utf-8"
        )

        broken = validate_dashboard_links(str(readme))
        assert broken == ["sub/missing.md"]

    def test_encoded_relative_links_resolve(self, tmp_path):
        d = tmp_path / "Official Artifact" / "サブ"
        d.mkdir(parents=True)
        (d / "report.md").write_text("x", encoding="utf-8")
        readme = tmp_path / "README.md"
        readme.write_text(
            "- [ok](Official%20Artifact/%E3%82%B5%E3%83%96/report.md)\n", encoding="utf-8"
        )

        assert validate_dashboard_links(str(readme)) == []

    def test_external_links_are_not_checked(self, tmp_path):
        readme = tmp_path / "README.md"
        readme.write_text("[web](https://example.com/x)\n[a](#top)\n", encoding="utf-8")
        assert validate_dashboard_links(str(readme)) == []

    def test_legacy_absolute_links_still_checked(self, tmp_path):
        """移行期間中、古い file:/// リンクも解決を試みる"""
        readme = tmp_path / "README.md"
        readme.write_text(
            "- [old](file:///C:/no_such_dir_xyz/no_such_file.md)\n", encoding="utf-8"
        )
        broken = validate_dashboard_links(str(readme))
        assert len(broken) == 1


class TestProductionDashboard:
    """実物のダッシュボードが環境非依存であること"""

    @pytest.fixture(scope="class")
    def dashboard(self):
        path = os.path.join(DASHBOARD_DIR, "README.md")
        if not os.path.exists(path):
            pytest.skip("ダッシュボードが未生成")
        return path

    def test_no_absolute_paths_in_dashboard(self, dashboard):
        content = open(dashboard, encoding="utf-8").read()
        assert "file:///" not in content, (
            "ダッシュボードに生成環境の絶対パスが残っています。"
            "get_rel_link() を経由して相対リンクで書いてください。"
        )
        assert "C:/Users" not in content and "C:\\Users" not in content

    def test_all_links_resolve(self, dashboard):
        broken = validate_dashboard_links(dashboard)
        assert not broken, "リンク切れ:\n" + "\n".join(broken[:15])
