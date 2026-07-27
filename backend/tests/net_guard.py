"""テスト実行中の外部ネットワーク接続を遮断する。

## なぜ必要か

モックが外れたテストが実ネットワークへ出ると、接続待ちで **止まる**。
pytest-timeout は Windows では thread 方式しか使えず、発動するとプロセス全体が落ちるため、
1 件のハングでテスト結果もカバレッジ計測も丸ごと失われる（2026-07-26 に実際に発生）。

さらに、外部に出るテストは実行環境（ネットワーク、プロキシ、CI の到達性）に結果が左右される。
基準環境を CI(Linux) に揃える方針と矛盾する。

そこで **接続そのものを禁止** し、ハングではなく即座の失敗に変える。
どのテストが外へ出ているかがスタックトレースで一目で分かる。

## 例外

- `localhost` / `127.0.0.1` / `::1` への接続は許可（TestClient やローカルサーバのテスト）
- `@pytest.mark.network` を付けたテストは許可
- 環境変数 `ANTIGRAVITY_ALLOW_NETWORK=1` を設定すると全体で許可
"""

import os
import socket

_REAL_CONNECT = socket.socket.connect
_REAL_CONNECT_EX = socket.socket.connect_ex
_REAL_GETADDRINFO = socket.getaddrinfo

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "", None}

# install() 時点の値。テストが socket を patch していた場合、その patch を壊さずに戻すため
# 「差し替えた本人が置いた関数のままなら戻す」という判定に使う。
_saved: dict = {}
_installed: dict = {}


class NetworkAccessBlocked(RuntimeError):
    """テスト中に外部ネットワークへ接続しようとした。"""


def _is_local(address) -> bool:
    if isinstance(address, (tuple, list)) and address:
        host = address[0]
    elif isinstance(address, str):
        # UNIX ソケットなど
        return True
    else:
        return True
    if host in _LOCAL_HOSTS:
        return True
    return isinstance(host, str) and (host.startswith("127.") or host == "::1")


def _blocked(address):
    return NetworkAccessBlocked(
        f"テスト中の外部ネットワーク接続はブロックされています: {address}\n"
        "→ 外部呼び出しをモックしてください（モックが外れている可能性があります）。\n"
        "→ 意図的に外へ出るテストは @pytest.mark.network を付けてください。\n"
        "→ 一時的に全体で許可する場合は ANTIGRAVITY_ALLOW_NETWORK=1。"
    )


def install() -> None:
    """外部接続を遮断する。"""
    if os.environ.get("ANTIGRAVITY_ALLOW_NETWORK") == "1":
        return

    def guarded_connect(self, address):
        if not _is_local(address):
            raise _blocked(address)
        return _REAL_CONNECT(self, address)

    def guarded_connect_ex(self, address):
        if not _is_local(address):
            raise _blocked(address)
        return _REAL_CONNECT_EX(self, address)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host not in _LOCAL_HOSTS and not (
            isinstance(host, str) and (host.startswith("127.") or host == "::1")
        ):
            raise _blocked(host)
        return _REAL_GETADDRINFO(host, *args, **kwargs)

    # 差し替える前の値を控える。他のテストが socket を patch している最中でも、
    # そこへ戻せるようにする（無条件に import 時の値へ戻すと、その patch を壊す）。
    _saved["connect"] = socket.socket.connect
    _saved["connect_ex"] = socket.socket.connect_ex
    _saved["getaddrinfo"] = socket.getaddrinfo

    socket.socket.connect = guarded_connect
    socket.socket.connect_ex = guarded_connect_ex
    socket.getaddrinfo = guarded_getaddrinfo

    _installed["connect"] = guarded_connect
    _installed["connect_ex"] = guarded_connect_ex
    _installed["getaddrinfo"] = guarded_getaddrinfo


def uninstall() -> None:
    """遮断を解除する。

    自分が置いた関数のままの場合だけ戻す。テスト側が後から socket を patch していた場合に
    その patch を上書きしないため（上書きすると、相手の後始末で遮断が復活し続ける）。
    """
    if not _installed:
        return
    if socket.socket.connect is _installed.get("connect"):
        socket.socket.connect = _saved.get("connect", _REAL_CONNECT)
    if socket.socket.connect_ex is _installed.get("connect_ex"):
        socket.socket.connect_ex = _saved.get("connect_ex", _REAL_CONNECT_EX)
    if socket.getaddrinfo is _installed.get("getaddrinfo"):
        socket.getaddrinfo = _saved.get("getaddrinfo", _REAL_GETADDRINFO)
    _installed.clear()
    _saved.clear()


__all__ = ["install", "uninstall", "NetworkAccessBlocked"]
