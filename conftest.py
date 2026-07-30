"""リポジトリ直下の pytest 設定。

いまの用途は1つだけ — テストが本番ファイルへ書き込むのを検出すること。
検出のみで挙動は変えない。詳細は `backend/tests/fs_guard.py` の docstring を参照。

ここに置く理由: 汚染は `backend/tests/` だけでなく `backend/test_*.py`
（ルート pytest.ini の testpaths 直下）からも出る。conftest は
`backend/tests/` `backend/harness/` `tests/` の3系統に分かれており、
さらに rootdir がバッチ構成で変わる（`backend/tests/` だけのバッチでは
rootdir が `backend/tests` になり、このファイルは読まれない）。
そのため同じフックを複数の conftest から取り込んでいる。install も報告も冪等。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend" / "tests"))

from fs_guard import (  # noqa: F401
    pytest_configure,
    pytest_runtest_setup,
    pytest_terminal_summary,
    pytest_unconfigure,
)
