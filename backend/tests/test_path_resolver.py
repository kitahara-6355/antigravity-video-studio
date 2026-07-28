"""path_resolver の検証。

このモジュールが守るべき性質は3つ。

1. 環境変数が無いとき、従来の直書きパスと同じ場所を指す（移行で挙動が変わらない）
2. 環境変数があればそちらを指す（Drive / CI / 別マシンへ移せる）
3. どの OS でも `C:` を前提にしない（CI は Ubuntu）
"""

import os
from pathlib import Path

import pytest

import path_resolver


ALL_ENV_VARS = [
    "ANTIGRAVITY_BASE_DIR",
    "VIDEO_AUTOMATION_BASE_DIR",
    "ANTIGRAVITY_VAULT_OUTPUTS",
    "ANTIGRAVITY_VAULT_ASSETS",
    "ANTIGRAVITY_VAULT_ENVIRONMENTS",
    "ANTIGRAVITY_APP_DATA_DIR",
    "ANTIGRAVITY_APP_DATA",
]


@pytest.fixture
def clean_env(monkeypatch):
    """このモジュールが見る環境変数を全て外した状態にする。

    他のテストや実行環境の設定が既定値の検証に混ざらないようにする。
    """
    for name in ALL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


# --- 既定値: 従来の直書きパスと同じ場所を指すこと ---

def test_backend_dir_is_this_packages_directory(clean_env):
    """backend_dir はこのモジュール自身の置き場を指す"""
    assert path_resolver.backend_dir() == Path(path_resolver.__file__).resolve().parent
    assert path_resolver.backend_dir().name == "backend"


def test_project_root_defaults_to_backend_parent(clean_env):
    """既定のプロジェクトルートは backend/ の親（safe_io.PROJECT_ROOT と同じ定義）"""
    assert path_resolver.project_root() == path_resolver.backend_dir().parent


def test_project_root_matches_safe_io(clean_env):
    """safe_io と食い違うと、書き込み先と読み出し先がずれる"""
    import safe_io

    assert path_resolver.project_root() == safe_io.PROJECT_ROOT


def test_vault_outputs_defaults_under_project_root(clean_env):
    assert path_resolver.vault_outputs_dir() == path_resolver.project_root() / "vault-outputs"


def test_vault_assets_defaults_beside_project_root(clean_env):
    """vault-assets はリポジトリの外、プロジェクトルートと同階層にある"""
    assert path_resolver.vault_assets_dir() == path_resolver.workspace_root() / "vault-assets"
    # リポジトリ内ではないことを明示（取り違えると成果物を素材置き場に書く）
    assert path_resolver.project_root() not in path_resolver.vault_assets_dir().parents


def test_vault_environments_defaults_beside_project_root(clean_env):
    assert (
        path_resolver.vault_environments_dir()
        == path_resolver.workspace_root() / "vault-environments"
    )


def test_app_data_defaults_to_home_gemini(clean_env):
    """既定は ~/.gemini/antigravity。C:\\Users\\PC_User 決め打ちではない"""
    assert path_resolver.app_data_dir() == Path.home() / ".gemini" / "antigravity"


def test_brain_and_scratch_hang_off_app_data(clean_env):
    assert path_resolver.brain_dir() == path_resolver.app_data_dir() / "brain"
    assert path_resolver.app_scratch_dir() == path_resolver.app_data_dir() / "scratch"


def test_raw_videos_is_under_project_root(clean_env):
    assert path_resolver.raw_videos_dir() == path_resolver.project_root() / "raw_videos"


# --- 環境変数による差し替え ---

def test_base_dir_env_moves_project_root(monkeypatch, tmp_path, clean_env):
    monkeypatch.setenv("ANTIGRAVITY_BASE_DIR", str(tmp_path / "elsewhere"))
    assert path_resolver.project_root() == tmp_path / "elsewhere"


def test_base_dir_env_cascades_to_derived_dirs(monkeypatch, tmp_path, clean_env):
    """ルートを移せば、そこから導出される場所も一緒に動くこと。

    ここが連動しないと「ルートだけ移したのに出力は旧パス」という
    最も気づきにくい壊れ方をする。
    """
    root = tmp_path / "elsewhere"
    monkeypatch.setenv("ANTIGRAVITY_BASE_DIR", str(root))

    assert path_resolver.vault_outputs_dir() == root / "vault-outputs"
    assert path_resolver.raw_videos_dir() == root / "raw_videos"
    assert path_resolver.vault_assets_dir() == tmp_path / "vault-assets"


def test_backend_dir_ignores_base_dir_env(monkeypatch, tmp_path, clean_env):
    """コードの所在は環境変数で動かない（動かすと import が壊れる）"""
    monkeypatch.setenv("ANTIGRAVITY_BASE_DIR", str(tmp_path / "elsewhere"))
    assert path_resolver.backend_dir() == Path(path_resolver.__file__).resolve().parent


@pytest.mark.parametrize(
    "env_name, func_name",
    [
        ("ANTIGRAVITY_VAULT_OUTPUTS", "vault_outputs_dir"),
        ("ANTIGRAVITY_VAULT_ASSETS", "vault_assets_dir"),
        ("ANTIGRAVITY_VAULT_ENVIRONMENTS", "vault_environments_dir"),
        ("ANTIGRAVITY_APP_DATA_DIR", "app_data_dir"),
    ],
)
def test_each_dir_honors_its_env(monkeypatch, tmp_path, clean_env, env_name, func_name):
    target = tmp_path / "moved"
    monkeypatch.setenv(env_name, str(target))
    assert getattr(path_resolver, func_name)() == target


def test_project_root_accepts_legacy_env_name(monkeypatch, tmp_path, clean_env):
    """旧名 VIDEO_AUTOMATION_BASE_DIR も受ける。

    phase0_preflight / gen_telops の既存テスト十数件がこの名前で
    ルートを差し替えている。集約したせいでそれらが効かなくなると、
    テストは通るのに本番だけ旧パスを向く、という壊れ方をする。
    """
    target = tmp_path / "legacy_root"
    monkeypatch.setenv("VIDEO_AUTOMATION_BASE_DIR", str(target))
    assert path_resolver.project_root() == target


def test_project_root_prefers_new_env_name(monkeypatch, tmp_path, clean_env):
    monkeypatch.setenv("VIDEO_AUTOMATION_BASE_DIR", str(tmp_path / "legacy"))
    monkeypatch.setenv("ANTIGRAVITY_BASE_DIR", str(tmp_path / "current"))
    assert path_resolver.project_root() == tmp_path / "current"


def test_app_data_accepts_legacy_env_name(monkeypatch, tmp_path, clean_env):
    """旧名 ANTIGRAVITY_APP_DATA も受ける（既存コードが両方使っている）"""
    target = tmp_path / "legacy"
    monkeypatch.setenv("ANTIGRAVITY_APP_DATA", str(target))
    assert path_resolver.app_data_dir() == target


def test_app_data_prefers_new_env_name(monkeypatch, tmp_path, clean_env):
    """両方あるときは _DIR 付きが勝つ（移行中に旧名が残っていても新名で上書きできる）"""
    monkeypatch.setenv("ANTIGRAVITY_APP_DATA", str(tmp_path / "legacy"))
    monkeypatch.setenv("ANTIGRAVITY_APP_DATA_DIR", str(tmp_path / "current"))
    assert path_resolver.app_data_dir() == tmp_path / "current"


def test_empty_env_value_falls_back_to_default(monkeypatch, clean_env):
    """空文字はルート直下を指しかねないので「未設定」として扱う"""
    monkeypatch.setenv("ANTIGRAVITY_VAULT_OUTPUTS", "")
    assert path_resolver.vault_outputs_dir() == path_resolver.project_root() / "vault-outputs"


def test_env_change_takes_effect_without_reload(monkeypatch, tmp_path, clean_env):
    """importlib.reload なしで差し替わること（関数にした理由そのもの）"""
    first = tmp_path / "first"
    second = tmp_path / "second"

    monkeypatch.setenv("ANTIGRAVITY_VAULT_OUTPUTS", str(first))
    assert path_resolver.vault_outputs_dir() == first

    monkeypatch.setenv("ANTIGRAVITY_VAULT_OUTPUTS", str(second))
    assert path_resolver.vault_outputs_dir() == second


# --- 環境非依存であること ---

def test_no_windows_drive_letters_in_defaults(clean_env):
    """既定値に C: が混ざっていないこと。CI(Ubuntu) で解決できなくなる。

    ローカル(Windows) では project_root() 自体が C: 配下なので、
    ドライブレターの有無ではなく「PC_User 決め打ちが無いこと」を見る。
    """
    resolved = [
        path_resolver.project_root(),
        path_resolver.vault_outputs_dir(),
        path_resolver.vault_assets_dir(),
        path_resolver.vault_environments_dir(),
        path_resolver.app_data_dir(),
        path_resolver.brain_dir(),
        path_resolver.raw_videos_dir(),
    ]
    for path in resolved:
        assert "PC_User" not in str(path) or "PC_User" in str(Path.home()), (
            f"{path} に特定マシンのユーザー名が直書きされている"
        )


def test_all_public_names_are_callable(clean_env):
    """__all__ に挙げたものが全て呼べること（書き忘れ・改名の検出）"""
    for name in path_resolver.__all__:
        func = getattr(path_resolver, name)
        assert callable(func), f"{name} が呼び出せない"
        assert isinstance(func(), Path), f"{name}() が Path を返していない"


def test_module_source_has_no_hardcoded_local_path():
    """このモジュール自身が直書きパスを持たないこと。

    集約先が直書きしていては意味がない。docstring には「何を集約したのか」の
    説明として旧パスを載せてあるので、それは除外し、実行される文字列だけを見る。
    """
    import ast

    source = Path(path_resolver.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                docstrings.add(doc)

    offenders = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in docstrings
        and "PC_User" in node.value
    ]
    assert not offenders, f"実行される文字列に直書きパスがある: {offenders}"
