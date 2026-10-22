"""完成版の左上にロゴを足すかどうか — 書き出す口はすべてここに聞く。

決まりは ``backend/config/logo.json`` の ``enabled``（2026-10-22 から既定はなし）。
1回だけ変えるときは環境変数 ``AVS_LOGO``（on / off）。設定が読めなければ足さない
（ロゴの無い動画は作り直せるが、焼いたロゴは消せないため）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

SETTING = Path(__file__).parent / "config" / "logo.json"

_ON = {"on", "1", "true", "yes"}
_OFF = {"off", "0", "false", "no"}


def logo_enabled() -> bool:
    override = os.environ.get("AVS_LOGO", "").strip().lower()
    if override in _ON:
        return True
    if override in _OFF:
        return False
    try:
        return json.loads(SETTING.read_text(encoding="utf-8")).get("enabled") is True
    except (OSError, ValueError, AttributeError):
        return False
