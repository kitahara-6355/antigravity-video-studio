"""testpaths 外の退行検知が「同じ土俵」で比べていることのテスト。

## なぜこれだけを見るか

このガードは **基準の版を別のワークツリーに展開して、同じテストを両側で
走らせ、いまの版にしか無い失敗を退行と呼ぶ。** 基準側のワークツリーには
**基準の版の `pytest.ini`** が入るので、`pytest.ini` そのものを変えた回は
両側が違う設定で走る。中身を誰も壊していなくても差が出る。

2026-09-12 に実際に踏んだ。`timeout = 60` と `pytest-randomly` を入れた
コミット（eae2de3）で **13件 / 7ファイルが「新しく赤くなった」**と報告された。
調べると、基準側だけ pytest-randomly が有効（基準の `pytest.ini` に
`-p no:randomly` が無い）で実行順がシャッフルされ、**順序依存のテストの
当落が両側で入れ替わっていた**だけだった。

手元で同じ手順を再現すると、対称にする前後でこうなった:

    非対称: 3対6 / 2対4 / 7対8 / 1対0  → 「新しく赤い」が出る
    対称  : 5対5 / 4対4 / 7対7 / 0対0  → 差分ゼロ

**元から赤いものが両側で同じだけ赤くなることが、このガードの前提。**
その前提を保つのが `harness_args()` なので、ここだけを直接叩く。
"""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_GUARD = _ROOT / ".github" / "scripts" / "outside_testpaths_guard.py"


@pytest.fixture(scope="module")
def guard():
    """`.github/scripts/` はパッケージではないのでパスから直接読み込む。"""
    spec = importlib.util.spec_from_file_location("outside_testpaths_guard", _GUARD)
    module = importlib.util.module_from_spec(spec)
    sys.modules["outside_testpaths_guard"] = module
    spec.loader.exec_module(module)
    return module


def test_実行順を必ず固定する(guard):
    """`-p no:randomly` が無いと、基準側だけシャッフルされる。

    pytest-randomly は**入っているだけで既定で有効**になる。基準の版の
    `pytest.ini` は変えられないので、**引数で両側に明示的に渡す**しかない。
    """
    args = guard.harness_args()
    assert "no:randomly" in args
    assert args[args.index("no:randomly") - 1] == "-p"


def test_pytest_ini_の_timeout_を両側へ運ぶ(guard):
    """`timeout = 60` を HEAD 側だけに効かせない。

    HEAD だけ打ち切られると、基準でゆっくり通るテストが「新しく赤い」に化ける。
    """
    args = guard.harness_args()
    ini = (_ROOT / "pytest.ini").read_text(encoding="utf-8")
    m = re.search(r"^\s*timeout\s*=\s*(\d+)\s*$", ini, re.MULTILINE)
    assert m, "pytest.ini に timeout が無い。あるなら期待値をここから引き直す"
    assert f"timeout={m.group(1)}" in args, "pytest.ini の timeout が引数に載っていない"
    assert args[args.index(f"timeout={m.group(1)}") - 1] == "-o"


def test_timeout_が無い版では_o_を付けない(guard, tmp_path, monkeypatch):
    """基準の版（timeout 未設定）へ遡っても壊れないこと。

    `-o timeout=` のような空値を渡すと pytest が起動時に落ち、**ファイル全体が
    「判定不能」に倒れて退行検知が黙る。** 沈黙は緑ではない。
    """
    ini = tmp_path / "pytest.ini"
    ini.write_text("[pytest]\nasyncio_mode = auto\n", encoding="utf-8")
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    args = guard.harness_args()
    assert "-o" not in args
    assert "no:randomly" in args, "順序の固定は timeout の有無と無関係に要る"


def test_その引数が実際に_pytest_へ渡っている(guard, monkeypatch):
    """**`harness_args()` を呼んでいるだけでは意味がない。**

    組み立てた引数が `failures()` の subprocess まで届いていることを見る。
    ここが切れていると、上の3件は緑のままガードだけが非対称に戻る。
    """
    渡った = {}

    class _R:
        stdout = ""

    def _fake_run(args, **kw):
        渡った["args"] = args
        return _R()

    monkeypatch.setattr(guard.subprocess, "run", _fake_run)
    guard.failures("tests/test_dummy.py", _ROOT)

    args = 渡った["args"]
    for a in guard.harness_args():
        assert a in args, f"{a} が pytest へ渡っていない"
