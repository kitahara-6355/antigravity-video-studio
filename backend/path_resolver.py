"""プロジェクトの基準ディレクトリの解決を一箇所に集約する。

## なぜ必要か

2026-07-28 時点で、ローカル絶対パスが 533 行 / 262 ファイルに直書きされていた。
実体は5種類の基準ディレクトリしかなく、それぞれが各ファイルで別々に
再定義されている状態だった。

    C:\\Users\\PC_User\\Desktop\\script\\video-automation   … プロジェクトルート
    C:\\Users\\PC_User\\Desktop\\script\\vault-assets        … 素材（撮影RAW）
    C:\\Users\\PC_User\\Desktop\\script\\vault-environments  … 環境別の設定
    C:\\Users\\PC_User\\.gemini\\antigravity                 … Antigravity のアプリデータ
    （+ その配下の brain/ と scratch/）

このままでは以下ができない。

- **GitHub Actions での実行** — Ubuntu ランナーに `C:\\Users\\PC_User` は無い
- **素材の Drive 移行** — 置き場を変えるたびに 262 ファイルを直すことになる
- **別マシンでの開発** — ユーザー名が違うだけで動かない

`font_resolver.py` が日本語フォントについて解いたのと同じ問題。
新しくパスを扱うコードは、直書きせずこのモジュールを使うこと。

## 使い方

    from path_resolver import project_root, vault_assets_dir

    out = project_root() / "logs" / "run.log"
    raw = vault_assets_dir() / "raw_videos"

## 定数ではなく関数である理由

`safe_io.VAULT_OUTPUTS_DIR` は import 時に確定するモジュール定数なので、
テストで差し替えるには `importlib.reload()` が要る。関数にしておけば
`monkeypatch.setenv()` だけで済み、reload 忘れによる漏れも起きない。

## 環境変数

| 変数 | 差し替わるもの | 既定 |
|---|---|---|
| `ANTIGRAVITY_BASE_DIR` | プロジェクトルート | `backend/` の親 |
| `VIDEO_AUTOMATION_BASE_DIR` | 同上（旧名・後方互換） | — |
| `ANTIGRAVITY_WRITABLE_ROOT` | 実行時に書き換わるファイルの起点 | プロジェクトルート |
| `ANTIGRAVITY_VAULT_OUTPUTS` | 出力の保存先 | `<root>/vault-outputs` |
| `ANTIGRAVITY_VAULT_ASSETS` | 素材の置き場 | `<root>/../vault-assets` |
| `ANTIGRAVITY_VAULT_ENVIRONMENTS` | 環境別設定 | `<root>/../vault-environments` |
| `ANTIGRAVITY_APP_DATA_DIR` | Antigravity アプリデータ | `~/.gemini/antigravity` |
| `ANTIGRAVITY_APP_DATA` | 同上（旧名・後方互換） | — |
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "app_data_dir",
    "app_scratch_dir",
    "backend_dir",
    "brain_dir",
    "project_root",
    "raw_videos_dir",
    "vault_assets_dir",
    "vault_environments_dir",
    "vault_outputs_dir",
    "workspace_root",
    "writable_path",
]


def _from_env(*names: str) -> Path | None:
    """環境変数を順に見て、最初に見つかった非空の値を Path で返す。

    空文字列は「未設定」として扱う。`FOO=` のような指定でルート直下を
    指してしまう事故を防ぐため。
    """
    for name in names:
        value = os.environ.get(name)
        if value:
            return Path(value)
    return None


def backend_dir() -> Path:
    """このモジュールが置かれている `backend/` を返す。

    コードの所在なので環境変数では差し替えない。データの置き場を移したい
    ときに使うのは `project_root()` のほう。
    """
    return Path(__file__).resolve().parent


def project_root() -> Path:
    """プロジェクトルート（`backend/` の親）を返す。

    既存コードに `ANTIGRAVITY_BASE_DIR` と `VIDEO_AUTOMATION_BASE_DIR` の
    2つの名前が混在していたので両方を受ける。前者を優先。
    新しいコードは `ANTIGRAVITY_BASE_DIR` を使うこと。
    """
    return (
        _from_env("ANTIGRAVITY_BASE_DIR", "VIDEO_AUTOMATION_BASE_DIR")
        or backend_dir().parent
    )


def writable_path(relative: str) -> Path:
    """**実行時に書き換わる**ファイルのパスを返す。

    使用量ログや進化履歴のように、動かすたびに中身が変わるファイル専用。
    `ANTIGRAVITY_WRITABLE_ROOT` が設定されていればそこを起点にする。

    なぜ `project_root()` の環境変数ではなく別の名前かというと、
    `ANTIGRAVITY_BASE_DIR` を振り向けると `model_config.json` のような
    **読み取り専用の設定ファイルまで**振り向いてしまい、読めなくなるため。
    書き換わるものだけを移せる必要がある。

    テスト実行時に conftest がこれを一時ディレクトリへ向ける。そうしないと
    テストが本番のファイルを書き換える。2026-07-31 の実測では、Git 追跡下の
    7ファイルがテストによって上書きされていた（`backend/branding/`の
    ブランド画像を含む）。

    Args:
        relative: プロジェクトルートからの相対パス（POSIX 区切りでよい）。
    """
    root = _from_env("ANTIGRAVITY_WRITABLE_ROOT") or project_root()
    return root.joinpath(*relative.split("/"))


def official_artifact_dir() -> Path:
    """`Human01_Official Artifact/` の置き場を返す。

    会話ログを含むため公開時にディレクトリごと除去したもの（CLAUDE.md 参照）。
    orchestration の 9 モジュールがここへレポートを書くが、それぞれが
    `WORKSPACE_DIR` から自前で組み立てていたため、テストを流すたびに
    **リポジトリ内に再生成されていた**（2026-08-01 の CI 実測で 16 パス）。

    `.gitignore` 済みなので `git status` には出ない。気づかず
    `git add -f` すると、除去した意味が消える。

    `writable_path` に寄せることで、テスト中は一時ディレクトリへ向く。
    本番では従来どおりプロジェクトルート直下になる。読み書きの両方を
    ここへ通すこと — 書き込みだけ振り向けると読み返しが壊れる。
    """
    return writable_path("Human01_Official Artifact")


def workspace_root() -> Path:
    """プロジェクトルートの親を返す。

    `vault-assets` と `vault-environments` はリポジトリの外、
    プロジェクトルートと同階層に置かれている。その基準点。
    """
    return project_root().parent


def vault_outputs_dir() -> Path:
    """生成物（merged / preview / final）の保存先。

    `safe_io.VAULT_OUTPUTS_DIR` と同じ環境変数を見る。両者が食い違うと
    書き込み先と読み出し先がずれるため、名前は必ず揃えること。
    """
    return _from_env("ANTIGRAVITY_VAULT_OUTPUTS") or (project_root() / "vault-outputs")


def vault_assets_dir() -> Path:
    """撮影 RAW などの素材置き場。

    Drive へ移す予定があるのはここ。移行時に書き換えるのは
    `ANTIGRAVITY_VAULT_ASSETS` の1点だけで済む。
    """
    return _from_env("ANTIGRAVITY_VAULT_ASSETS") or (workspace_root() / "vault-assets")


def vault_environments_dir() -> Path:
    """環境別の設定・資材の置き場。"""
    return _from_env("ANTIGRAVITY_VAULT_ENVIRONMENTS") or (
        workspace_root() / "vault-environments"
    )


def app_data_dir() -> Path:
    """Antigravity のアプリデータ（`~/.gemini/antigravity`）。

    既存コードに `ANTIGRAVITY_APP_DATA_DIR` と `ANTIGRAVITY_APP_DATA` の
    2つの名前が混在していたので両方を受ける。`_DIR` 付きを優先。
    新しいコードは `_DIR` 付きを使うこと。
    """
    return _from_env("ANTIGRAVITY_APP_DATA_DIR", "ANTIGRAVITY_APP_DATA") or (
        Path.home() / ".gemini" / "antigravity"
    )


def brain_dir() -> Path:
    """会話ごとの作業領域（`<app_data>/brain`）。

    配下は会話 UUID のディレクトリ。UUID を直書きしたコードは
    そのマシンのその会話でしか動かないので、新しく増やさないこと。
    """
    return app_data_dir() / "brain"


def app_scratch_dir() -> Path:
    """Antigravity の一時領域（`<app_data>/scratch`）。

    リポジトリ内の `scratch/` とは別物。
    """
    return app_data_dir() / "scratch"


def raw_videos_dir() -> Path:
    """プロジェクト内の素材動画ディレクトリ（`<root>/raw_videos`）。

    `vault_assets_dir()` の RAW とは別。こちらは編集済み・変換済みの
    入力を置く作業用。
    """
    return project_root() / "raw_videos"
