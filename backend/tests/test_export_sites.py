"""R2-C1 の走査ゲート（`backend/export_sites.py`）の契約。

**手で grep する限り3度目が起きる。** gate-verifier は1周目に `POST /api/shorts/render`、
2周目に `POST /api/video/process/start` で、承認を1件も作らずに完成動画を実生成した。
どちらも私が塞いだつもりの経路の**隣**にあった。

そこで「動画を書きうる本番の関数」を機械に列挙させ、台帳と突き合わせる。
ここで見るのは**その仕組みが本当に見張れているか**:

- 新しい書き出し口が増えたら FAIL するか（**これが本体**）
- 理由の無い宣言を通さないか
- 台帳から消えた口に気づくか
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend import export_sites as es


def test_台帳と実態が一致している():
    """**本番の現在地。** ここが赤いなら、塞ぎ忘れか宣言忘れがある。"""
    ledger = es.load_ledger()
    不備 = es.check_entries(ledger["sites"])
    違反, _ = es.audit(ledger["sites"])

    assert not 不備, f"台帳の不備: {不備}"
    assert not 違反, f"台帳に無い書き出し口: {違反}"


@pytest.mark.parametrize("書き方", [
    "shutil.copy(src, VAULT_OUTPUTS_DIR / 'final' / 'x.mp4')",
    "ffmpeg.run_command(['-i', src, str(output_path)])",
    "(VAULT_OUTPUTS_DIR / 'final' / 'x.mp4').write_bytes(b'')",
    "subprocess.Popen(['ffmpeg', '-i', src, 'x.mp4'])",
    "shutil.move(src, str(final_path))",
])
def test_走査が拾うと宣言している書き方は本当に拾う(tmp_path, 書き方):
    """**検出そのものを `scan()` を通して確かめる**（2026-09-25 の gate-verifier の指摘）。

    以前のテストは候補の辞書を `audit()` に直接渡していて、検出が壊れても気づけなかった。
    ここに並べた書き方は走査が**拾うと約束しているもの**。拾えない書き方
    （`subprocess.run`・`open().write`・`os.replace`・`Path.rename` など）は約束していない —
    それは置き場の監査（`approval_gate --gate`）が結果で捕まえる（正典 limits に宣言済み）。
    """
    mod = tmp_path / "backend" / "zz_probe.py"
    mod.parent.mkdir(parents=True)
    mod.write_text(
        "import shutil, subprocess\n"
        "from safe_io import VAULT_OUTPUTS_DIR\n"
        f"def 書き出す(src, ffmpeg=None, output_path=None, final_path=None):\n"
        f"    {書き方}\n",
        encoding="utf-8")

    出た = {c["id"] for c in es.scan(tmp_path)}

    assert "backend/zz_probe.py::書き出す" in 出た, f"拾えていない: {書き方}"


def test_新しい書き出し口は台帳に無いと違反になる():
    """**これが本体。** 承認を通さない書き出しを足したら、機械が見つける。"""
    ledger = es.load_ledger()
    新しい口 = {"id": "backend/routers/新しい.py::書き出す", "file": "backend/routers/新しい.py",
                "symbol": "書き出す", "line": 1, "tools": ["run_command"]}

    違反, _ = es.audit(ledger["sites"], es.scan() + [新しい口])

    assert any("新しい.py::書き出す" in v for v in 違反), 違反


def test_消えた口は情報として出る():
    """改名・削除は違反ではないが、黙って消さない（台帳の掃除の合図）。"""
    ledger = es.load_ledger()
    余分 = ledger["sites"] + [{"id": "backend/消えた.py::書き出す", "file": "backend/消えた.py",
                              "symbol": "書き出す", "status": "gated", "reason": "テスト用"}]

    違反, 情報 = es.audit(余分)

    assert not [v for v in 違反 if "消えた" in v]
    assert any("消えた.py" in i for i in 情報), 情報


@pytest.mark.parametrize("壊し方, 期待", [
    ({"status": "なんとなく"}, "status"),
    ({"reason": "短い"}, "理由"),
    ({"reason": ""}, "項目が欠けています"),
    ({"symbol": ""}, "項目が欠けています"),
])
def test_宣言の不備を通さない(壊し方, 期待):
    """**理由の無い宣言は宣言ではない。** 「対象外」と書くだけで通るなら台帳の意味が無い。"""
    site = {"id": "x::y", "file": "x", "symbol": "y",
            "status": "intermediate", "reason": "これは十分な長さの理由です（テスト）"}
    site.update(壊し方)

    問題 = es.check_entries([site])

    assert any(期待 in p for p in 問題), 問題


def test_重複した宣言を見つける():
    """同じ口を2回宣言すると、片方だけ直したときに矛盾が隠れる。"""
    site = {"id": "x::y", "file": "x", "symbol": "y", "status": "gated", "reason": "門を引く"}

    問題 = es.check_entries([site, dict(site)])

    assert any("重複" in p for p in 問題), 問題


def test_走査は門を引いている工程を見つける():
    """**本線の書き出し（RenderWorker.execute）は必ず掃き出される。**

    ここが拾えなくなったら、走査そのものが壊れている（網が細くなった）。
    """
    出た = {c["id"]: c for c in es.scan()}

    assert "backend/agents/workers/render_worker.py::RenderWorker.execute" in 出た
    # **ffmpeg を直接叩く口も拾う。** ここが落ちると、出力先を引数で受け取る
    # 書き出し関数（閉じた Shorts の実体など）が網から漏れる
    ffmpegだけの口 = "backend/routers/shorts.py::_execute_ffmpeg_render"
    assert ffmpegだけの口 in 出た, "ffmpeg を直接叩く関数を拾えていない"
    assert 出た[ffmpegだけの口]["tools"] == ["run_command"]


def test_台帳の門は本当に門を引いている():
    """`gated` と宣言した口が、実際に `export_allowed` に到達すること。

    宣言と実装がずれたら（門を消したのに `gated` のまま）、台帳は嘘になる。
    """
    ledger = es.load_ledger()
    門 = [s for s in ledger["sites"] if s["status"] == "gated"]
    assert 門, "門を引く口が1つも無い"

    # **本線の書き出しは必ず `gated`。** ここを中間物に書き換えれば台帳は緑のまま
    # 素通りできてしまうので、名指しで留める
    本線 = {s["id"]: s for s in ledger["sites"]}
    execute = 本線["backend/agents/workers/render_worker.py::RenderWorker.execute"]
    assert execute["status"] == "gated", f"本線の書き出しが {execute['status']} と宣言されている"

    本体 = Path(__file__).parent.parent / "agents" / "workers" / "render_worker.py"
    src = 本体.read_text(encoding="utf-8")
    assert "export_allowed" in src, "RenderWorker が承認を確かめていない"
    assert all(s["file"].endswith("render_worker.py") for s in 門), \
        "門を引く口が render_worker.py の外にある（台帳の宣言を見直すこと）"


def test_台帳は正典の定義を指している():
    """「書き出し」の定義は正典にある。台帳がそれを指していないと、判断がぶれる。"""
    ledger = es.load_ledger()

    assert "vision_backlog" in ledger.get("note", ""), ledger.get("note")
    canon = json.loads((Path(__file__).parent.parent / "branding" / "vision_backlog.json")
                       .read_text(encoding="utf-8"))
    c1 = [c for c in canon["current_phase"]["exit_criteria"] if c["id"] == "R2-C1"][0]
    assert "「書き出し」" in c1["condition"], "正典に書き出しの定義が無い"
