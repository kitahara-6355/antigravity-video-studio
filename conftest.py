"""リポジトリ直下の pytest 設定。

いまの用途は1つだけ — テストが本番ファイルへ書き込むのを検出すること。
検出のみで挙動は変えない。詳細は `backend/tests/fs_guard.py` の docstring を参照。

ここに置く理由: 汚染は `backend/tests/` だけでなく `backend/test_*.py`
（ルート pytest.ini の testpaths 直下）からも出る。conftest は
`backend/tests/` `backend/harness/` `tests/` の3系統に分かれており、
さらに rootdir がバッチ構成で変わる（`backend/tests/` だけのバッチでは
rootdir が `backend/tests` になり、このファイルは読まれない）。
そのため同じフックを複数の conftest から取り込んでいる。install も報告も冪等。

sys.path は触らない。conftest の sys.path 操作を exec して検証しているテストが
あり、1要素足すだけで落ちる。ファイルパス直接指定で読み込み、sys.modules に
登録して同じインスタンスを共有する（登録しないと記録が分裂する）。
"""

from __future__ import annotations

import importlib.util as _ilu
import sys as _sys
from pathlib import Path as _Path

_fs_guard = _sys.modules.get("fs_guard")
if _fs_guard is None:
    _spec = _ilu.spec_from_file_location(
        "fs_guard",
        _Path(__file__).resolve().parent / "backend" / "tests" / "fs_guard.py",
    )
    _fs_guard = _ilu.module_from_spec(_spec)
    _sys.modules["fs_guard"] = _fs_guard
    _spec.loader.exec_module(_fs_guard)

pytest_configure = _fs_guard.pytest_configure
pytest_runtest_setup = _fs_guard.pytest_runtest_setup
pytest_terminal_summary = _fs_guard.pytest_terminal_summary
pytest_unconfigure = _fs_guard.pytest_unconfigure
