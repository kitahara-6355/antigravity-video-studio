"""実行記録を開き直す（R2: 承認の後の書き出し・2026-09-19）。

本線は提案で止まって記録を `awaiting_approval` で閉じる。承認の後の書き出しは**同じ実行の記録**に工程を足す。
1本の動画の記録が2つに割れると、成果物ゲート（最新の1本で判定する）が提案だけの記録か書き出しだけの記録を
見ることになり、どちらでも「使ったモデル」か「動画」が欠ける。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.revenue.run_record import RunRecorder


def _ledger(tmp_path, rows):
    p = tmp_path / "ledger.jsonl"
    with p.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return p


def test_同じ記録に書き出しの工程を足せる(tmp_path):
    ledger = _ledger(tmp_path, [])
    r = RunRecorder(runs_dir=tmp_path, ledger_path=ledger, inputs={"video_path": "in.mp4"})
    with r.stage("transcribe", task="transcribe"):
        pass
    r.finish("awaiting_approval")

    again = RunRecorder.reopen(r.run_id, runs_dir=tmp_path, ledger_path=ledger)
    assert again.run_id == r.run_id
    with again.stage("render", task="render"):
        pass
    rec = again.finish("completed")

    assert [s["name"] for s in rec["stages"]] == ["transcribe", "render"]
    assert rec["inputs"] == {"video_path": "in.mp4"}
    assert rec["status"] == "completed"
    on_disk = json.loads((tmp_path / r.run_id / "run.json").read_text(encoding="utf-8"))
    assert on_disk["status"] == "completed"


def test_呼び出しと原価と所要は前半の分に足し込む(tmp_path):
    ledger = _ledger(tmp_path, [])
    r = RunRecorder(runs_dir=tmp_path, ledger_path=ledger)
    _ledger(tmp_path, [{"model": "m", "jpy": 1.5}, {"model": "m", "jpy": 0.5}])
    first = r.finish("awaiting_approval")
    assert first["calls"] == 2 and first["cost_jpy"] == 2.0

    again = RunRecorder.reopen(r.run_id, runs_dir=tmp_path, ledger_path=ledger)
    _ledger(tmp_path, [{"model": "m", "jpy": 0.25}])
    rec = again.finish("completed")

    assert rec["calls"] == 3, "提案までの呼び出しが消えています"
    assert rec["cost_jpy"] == 2.25, "提案までの原価が消えています"
    assert rec["duration_sec"] >= first["duration_sec"]


def test_無い記録は開き直せない(tmp_path):
    with pytest.raises(FileNotFoundError):
        RunRecorder.reopen("存在しない", runs_dir=tmp_path)
