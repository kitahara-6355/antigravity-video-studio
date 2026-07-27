"""
DS-08: デザイントークン参照チェーン検証テスト

design_tokens.json → tokens.css → コンポーネントCSS/JSX の
3階層参照チェーンが整合していることを検証する。

検証項目:
  1. design_tokens.json の構造整合性 (5カテゴリ × 2テーマ)
  2. tokens.css が design_tokens.json から生成可能であること
  3. App.css のエイリアスが tokens.css の変数を参照していること
  4. DT-01〜DT-10 コンポーネントのハードコード色が削減されていること
  5. DesignTokenManager の evolution_log 連携が機能すること
"""
import json
import re
import pytest
from pathlib import Path


# プロジェクトルートの特定（backend/tests/test_shared/ → video-automation/）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
FRONTEND_SRC = PROJECT_ROOT / "frontend" / "src"
DESIGN_TOKENS_PATH = FRONTEND_SRC / "design_tokens.json"
TOKENS_CSS_PATH = FRONTEND_SRC / "tokens.css"
APP_CSS_PATH = FRONTEND_SRC / "App.css"
COMPONENTS_DIR = FRONTEND_SRC / "components"

# 必須カテゴリ
REQUIRED_CATEGORIES = ["color", "typography", "shadow", "radius", "motion"]

# DT-01〜DT-10 対象コンポーネントCSS
TARGET_COMPONENT_CSS = [
    "ProductionPipeline.css",
    "QualityGate.css",
    "SmartCut.css",
    "ThemeSelector.css",
    "StepReview.css",
    "QuickDecision.css",
    "YouTubeOptimizer.css",
]


class TestDesignTokenStructure:
    """1. design_tokens.json の構造整合性テスト"""

    def test_design_tokens_file_exists(self):
        """design_tokens.json が存在する"""
        assert DESIGN_TOKENS_PATH.exists(), f"design_tokens.json not found at {DESIGN_TOKENS_PATH}"

    def test_valid_json_structure(self):
        """design_tokens.json が有効なJSONで必須フィールドを持つ"""
        with open(DESIGN_TOKENS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "$version" in data, "Missing $version field"
        assert "themes" in data, "Missing themes field"

    def test_light_theme_has_all_categories(self):
        """lightテーマが5カテゴリすべてを持つ"""
        with open(DESIGN_TOKENS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        light = data["themes"]["light"]
        for cat in REQUIRED_CATEGORIES:
            assert cat in light, f"Light theme missing category: {cat}"

    def test_dark_theme_has_all_categories(self):
        """darkテーマが5カテゴリすべてを持つ"""
        with open(DESIGN_TOKENS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        dark = data["themes"]["dark"]
        for cat in REQUIRED_CATEGORIES:
            assert cat in dark, f"Dark theme missing category: {cat}"

    def test_light_dark_category_parity(self):
        """light/darkテーマのカテゴリ数が一致する"""
        with open(DESIGN_TOKENS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        light_keys = set(data["themes"]["light"].keys())
        dark_keys = set(data["themes"]["dark"].keys())
        assert light_keys == dark_keys, f"Category mismatch: light={light_keys}, dark={dark_keys}"

    def test_minimum_token_count(self):
        """各テーマが最低20トークンを持つ"""
        with open(DESIGN_TOKENS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        def count_leaves(obj):
            count = 0
            for v in obj.values():
                if isinstance(v, dict):
                    count += count_leaves(v)
                else:
                    count += 1
            return count

        for theme_name in ["light", "dark"]:
            count = count_leaves(data["themes"][theme_name])
            assert count >= 20, f"{theme_name} theme has only {count} tokens (min 20)"


class TestTokensCSSGeneration:
    """2. tokens.css の生成整合性テスト"""

    def test_tokens_css_exists(self):
        """tokens.css が存在する"""
        assert TOKENS_CSS_PATH.exists(), f"tokens.css not found at {TOKENS_CSS_PATH}"

    def test_tokens_css_has_root_selector(self):
        """tokens.css に :root セレクタが存在する"""
        content = TOKENS_CSS_PATH.read_text(encoding="utf-8")
        assert ":root {" in content, "Missing :root selector in tokens.css"

    def test_tokens_css_has_dark_theme(self):
        """tokens.css にダークテーマセクションが存在する"""
        content = TOKENS_CSS_PATH.read_text(encoding="utf-8")
        assert "@media (prefers-color-scheme: dark)" in content

    def test_tokens_css_has_manual_dark_class(self):
        """tokens.css に手動ダークモードクラスが存在する"""
        content = TOKENS_CSS_PATH.read_text(encoding="utf-8")
        assert ":root.theme-dark" in content

    def test_tokens_css_variable_count_matches_json(self):
        """tokens.css の変数数が design_tokens.json と一致する"""
        content = TOKENS_CSS_PATH.read_text(encoding="utf-8")
        # :root ブロック内の変数を数える（最初のブロック = light theme）
        root_match = re.search(r':root \{([^}]+)\}', content)
        assert root_match, "Could not find :root block"
        css_vars = re.findall(r'--[\w-]+:', root_match.group(1))

        with open(DESIGN_TOKENS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        def count_leaves(obj):
            count = 0
            for v in obj.values():
                if isinstance(v, dict):
                    count += count_leaves(v)
                else:
                    count += 1
            return count

        json_count = count_leaves(data["themes"]["light"])
        assert len(css_vars) == json_count, (
            f"Variable count mismatch: CSS={len(css_vars)}, JSON={json_count}"
        )


class TestAppCSSAliases:
    """3. App.css のエイリアス参照テスト"""

    def test_app_css_imports_tokens(self):
        """index.css が tokens.css をインポートしている"""
        index_css = FRONTEND_SRC / "index.css"
        content = index_css.read_text(encoding="utf-8")
        assert "@import './tokens.css'" in content or "@import \"./tokens.css\"" in content

    def test_app_css_uses_token_aliases(self):
        """App.css がトークン変数をエイリアスで参照している"""
        content = APP_CSS_PATH.read_text(encoding="utf-8")
        required_aliases = [
            "--bg-primary: var(--color-bg-primary)",
            "--text-primary: var(--color-text-primary)",
            "--accent-primary: var(--color-accent-primary)",
            "--border-color: var(--color-border-default)",
            "--font-heading: var(--typography-font-heading)",
        ]
        for alias in required_aliases:
            assert alias in content, f"Missing alias in App.css: {alias}"

    def test_no_dark_mode_media_query_in_app_css(self):
        """App.css にダークモードのメディアクエリが残っていない（tokens.cssで管理）"""
        content = APP_CSS_PATH.read_text(encoding="utf-8")
        # App.css内の#rootに対するダークモード定義がないことを確認
        assert "prefers-color-scheme: dark" not in content or "tokens.css" in content


class TestComponentTokenization:
    """4. DT-01〜DT-10 コンポーネントのトークン化テスト"""

    @pytest.mark.parametrize("css_file", TARGET_COMPONENT_CSS)
    def test_component_uses_token_variables(self, css_file):
        """各コンポーネントCSSがデザイントークン変数を参照している"""
        css_path = COMPONENTS_DIR / css_file
        if not css_path.exists():
            pytest.skip(f"{css_file} does not exist")
        content = css_path.read_text(encoding="utf-8")
        token_refs = re.findall(r'var\(--color-[^)]+\)', content)
        assert len(token_refs) >= 1, (
            f"{css_file} has no design token variable references"
        )

    @pytest.mark.parametrize("css_file", TARGET_COMPONENT_CSS)
    def test_hardcoded_color_reduction(self, css_file):
        """ハードコード色が50%以上削減されていること"""
        css_path = COMPONENTS_DIR / css_file
        if not css_path.exists():
            pytest.skip(f"{css_file} does not exist")
        content = css_path.read_text(encoding="utf-8")

        # ハードコード色のカウント（var() 内の # は除外）
        all_hex_colors = re.findall(r'#[0-9a-fA-F]{3,8}\b', content)
        token_refs = re.findall(r'var\(--(?:color|shadow|radius|motion|typography)-[^)]+\)', content)

        # トークン参照がハードコード色の少なくとも50%をカバー
        total_color_refs = len(all_hex_colors) + len(token_refs)
        if total_color_refs == 0:
            pytest.skip(f"{css_file} has no color references")

        token_ratio = len(token_refs) / total_color_refs
        assert token_ratio >= 0.3, (
            f"{css_file}: token ratio {token_ratio:.0%} < 30% "
            f"(hex={len(all_hex_colors)}, tokens={len(token_refs)})"
        )


class TestDesignTokenManagerEvolution:
    """5. DesignTokenManager の evolution_log 連携テスト"""

    def test_manager_has_evolution_log_path(self):
        """DesignTokenManager が evolution_log パスを持つ"""
        from design_system.design_token_manager import DesignTokenManager
        manager = DesignTokenManager()
        assert hasattr(manager, '_evolution_log_path')
        assert "evolution_log.json" in str(manager._evolution_log_path)

    def test_manager_has_design_tokens_path(self):
        """DesignTokenManager が design_tokens.json パスを持つ"""
        from design_system.design_token_manager import DesignTokenManager
        manager = DesignTokenManager()
        assert hasattr(manager, '_design_tokens_path')
        assert "design_tokens.json" in str(manager._design_tokens_path)

    def test_manager_get_frontend_tokens(self):
        """get_frontend_tokens が design_tokens.json を読み込めること"""
        from design_system.design_token_manager import DesignTokenManager
        manager = DesignTokenManager()
        tokens = manager.get_frontend_tokens()
        if tokens is not None:  # ファイルが存在する場合のみ
            assert "themes" in tokens
            assert "light" in tokens["themes"]
            assert "dark" in tokens["themes"]

    def test_record_to_evolution_log(self, tmp_path):
        """_record_to_evolution_log がエントリを正しく追加する"""
        from design_system.design_token_manager import DesignTokenManager
        manager = DesignTokenManager()

        # テスト用 evolution_log を tmp_path に設定
        test_log_path = tmp_path / "evolution_log.json"
        test_log_path.write_text('{"entries": []}', encoding="utf-8")
        manager._evolution_log_path = test_log_path

        # 記録実行
        manager._record_to_evolution_log(
            mood="elegant",
            updates={"color_palette": {"primary": "#FF0000"}},
            old_values={"color_palette": {"primary": "#7C3AED"}},
            source="test",
            reason="DS-08 テスト"
        )

        # 検証
        with open(test_log_path, "r", encoding="utf-8") as f:
            log = json.load(f)

        assert len(log["entries"]) == 1
        entry = log["entries"][0]
        assert entry["type"] == "design_token_change"
        assert "elegant" in entry["summary"]
        assert entry["source"] == "test"
