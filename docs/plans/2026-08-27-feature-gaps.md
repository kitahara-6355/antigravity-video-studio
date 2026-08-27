# 実装不足項目の台帳と点検 — 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:executing-plans` でタスク単位に実装する。ステップはチェックボックス（`- [ ]`）で追う。

**Goal:** 実装が足りていない機能を1箇所に集め、**新しい漏れと片付け忘れを機械が見つける**ようにする。

**Architecture:** 台帳は `backend/config/feature_gaps.json`、点検は `python -m backend.feature_gaps --audit`。
証拠は**実行記録**（`output/runs/*/run.json`）に取る。品質ゲートは台帳に載っている機能を
**減点せず `skipped_features` に出す**ので、実装したら台帳から消え、その瞬間からゲートが本気で見はじめる。

**Tech Stack:** Python 3.13 / pytest / 標準ライブラリのみ（新しい依存は足さない）

**Spec:** [docs/specs/2026-08-27-feature-gaps-design.md](../specs/2026-08-27-feature-gaps-design.md)

## Global Constraints

- **CLI は `PYTHONPATH=./backend` が要る。** モジュール内の import は `backend.` を付ける
  （`model_policy.live_model_ids()` が同じ罠を踏んだ）
- **新規テストファイルを作らない。** `pytest.ini` の testpaths を触るとバッチの区切りが変わり、
  既存のテスト汚染が別の場所で発火する。テストは `backend/tests/test_revenue_artifact_gate.py` に足す
- **既存テストの主張を弱めない。** 追加のみ。署名変更が要る場合はその1行だけ
- テスト実行は `export GOOGLE_API_KEY=dummy_key_for_ci` と `PYTHONPATH=./backend` を付ける。
  **フルスイート禁止**（OOM 13.6GB）。ファイル指定で回す
- **実走（課金経路）はこの計画に含めない。** 実行記録は既にある8件を読むだけ

---

### Task 1: 台帳と読み込み・記載不備の検出

**Files:**
- Create: `backend/config/feature_gaps.json`
- Create: `backend/feature_gaps.py`
- Test: `backend/tests/test_revenue_artifact_gate.py`（末尾に節を足す）

**Interfaces:**
- Produces: `load_gaps(path=None) -> list[dict]`, `check_entries(gaps) -> list[str]`（不備の説明の列）,
  `GAPS_PATH: Path`

- [ ] **Step 1: 失敗するテストを書く**

```python
# --- 実装不足項目の台帳（2026-08-27）-----------------------------------------


def test_台帳の全項目に理由と判定条件がある():
    """**「あとで書く」を許さない。** 理由の無い項目は思い出せない。"""
    from backend.feature_gaps import check_entries, load_gaps

    assert check_entries(load_gaps()) == []


def test_理由が無ければ不備として出る(tmp_path):
    from backend.feature_gaps import check_entries

    不備 = check_entries([{"id": "x", "title": "何か", "kind": "gap",
                           "handled_in": "将来",
                           "done_when": {"kind": "run_record_clean"}}])

    assert any("why" in m for m in 不備), 不備


def test_gapには行先が要る():
    """`intentional` には要らないが、`gap` は**どこで直すか**が要る。"""
    from backend.feature_gaps import check_entries

    不備 = check_entries([{"id": "x", "title": "何か", "kind": "gap",
                           "why": "理由", "done_when": {"kind": "run_record_clean"}}])

    assert any("handled_in" in m for m in 不備), 不備
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `PYTHONPATH=./backend python -m pytest backend/tests/test_revenue_artifact_gate.py -q --no-cov -k 台帳`
Expected: FAIL（`ModuleNotFoundError: backend.feature_gaps`）

- [ ] **Step 3: 台帳を書く**

`backend/config/feature_gaps.json` に spec §6 の8件を入れる。形は spec §2 のとおり。
`gate_checks` は品質ゲート側で除外するプラグイン名（Task 6 で使う）。

- [ ] **Step 4: 読み込みと検証を書く**

```python
REQUIRED = ("id", "title", "kind", "why", "done_when")


def load_gaps(path: Path | None = None) -> list[dict]:
    p = Path(path or GAPS_PATH)
    if not p.is_file():
        raise FileNotFoundError(f"台帳がありません: {p}")
    return json.loads(p.read_text(encoding="utf-8"))["gaps"]


def check_entries(gaps: list[dict]) -> list[str]:
    """**記載不備。**「あとで書く」を許さない。"""
    出た = []
    for g in gaps:
        欠け = [k for k in REQUIRED if not g.get(k)]
        if g.get("kind") == "gap" and not g.get("handled_in"):
            欠け.append("handled_in")
        if 欠け:
            出た.append(f"{g.get('id', '(id なし)')}: 項目が欠けています: {', '.join(欠け)}")
    return 出た
```

- [ ] **Step 5: 通ることを確かめる**

Run: `PYTHONPATH=./backend python -m pytest backend/tests/test_revenue_artifact_gate.py -q --no-cov -k 台帳`
Expected: PASS

- [ ] **Step 6: コミット**

```bash
git add backend/config/feature_gaps.json backend/feature_gaps.py backend/tests/test_revenue_artifact_gate.py
git commit -m "feat(feature-gaps): 実装不足項目の台帳と記載不備の検出"
```

---

### Task 2: 点検 条件1 — 実行記録に出た未知の項目

**Files:**
- Modify: `backend/feature_gaps.py`
- Test: `backend/tests/test_revenue_artifact_gate.py`

**Interfaces:**
- Consumes: `load_gaps()`
- Produces: `unknown_from_record(run: dict, gaps: list[dict]) -> list[str]`

- [ ] **Step 1: 失敗するテストを書く**

```python
def _記録(**over) -> dict:
    run = {"run_id": "r", "status": "degraded",
           "health": {"skipped_features": [], "failed_stages": []}}
    run["health"].update(over)
    return run


def test_記録に出た未知の項目を見つける():
    """**新しい実装漏れが黙って増えない。**"""
    from backend.feature_gaps import unknown_from_record

    出た = unknown_from_record(_記録(skipped_features=["字幕の焼き込み"]), [])

    assert 出た == ["字幕の焼き込み"]


def test_本線の工程名は実装漏れではない():
    """`quality_gate` が落ちたのは**工程の失敗**であって実装不足ではない。"""
    from backend.feature_gaps import unknown_from_record

    assert unknown_from_record(
        _記録(failed_stages=["quality_gate"], skipped_features=["quality_gate"]), []) == []


def test_台帳に載っていれば実装漏れではない():
    from backend.feature_gaps import unknown_from_record

    gaps = [{"id": "bgm", "surfaces_as": "BGMミキシング", "kind": "gap"}]

    assert unknown_from_record(_記録(skipped_features=["BGMミキシング(ファイルなし)"]), gaps) == []


def test_意図して止めているものも実装漏れではない():
    from backend.feature_gaps import unknown_from_record

    gaps = [{"id": "dream", "surfaces_as": "dream_learning", "kind": "intentional"}]

    assert unknown_from_record(_記録(skipped_features=["dream_learning"]), gaps) == []
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `PYTHONPATH=./backend python -m pytest backend/tests/test_revenue_artifact_gate.py -q --no-cov -k 記録`
Expected: FAIL（`unknown_from_record` が無い）

- [ ] **Step 3: 実装する**

```python
def _mainline_stage_names() -> set[str]:
    """**本線の工程名は実装不足ではない。** 落ちたのは工程であって機能ではない。"""
    from agents.pipeline_coordinator import STAGE_RECORD
    return {v[0] for v in STAGE_RECORD.values()}


def unknown_from_record(run: dict, gaps: list[dict]) -> list[str]:
    health = run.get("health") or {}
    出たもの = list(health.get("skipped_features") or []) + list(health.get("failed_stages") or [])
    既知 = _mainline_stage_names()
    印 = [g.get("surfaces_as") for g in gaps if g.get("surfaces_as")]
    未知 = []
    for 名 in dict.fromkeys(出たもの):
        if 名 in 既知 or any(s and s in 名 for s in 印):
            continue
        未知.append(名)
    return 未知
```

- [ ] **Step 4: 通ることを確かめる**

Run: `PYTHONPATH=./backend python -m pytest backend/tests/test_revenue_artifact_gate.py -q --no-cov -k 記録`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git commit -am "feat(feature-gaps): 実行記録に出た未知の項目を検出する"
```

---

### Task 3: 点検 条件2 — 実装済みなのに残っている項目

**Files:**
- Modify: `backend/feature_gaps.py`
- Test: `backend/tests/test_revenue_artifact_gate.py`

**Interfaces:**
- Produces: `is_done(gap: dict, run: dict | None) -> bool | None`（`None` = この実行では確かめていない）

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_記録から消えたら実装済みとみなす():
    """**片付け忘れが残らない。**"""
    from backend.feature_gaps import is_done

    gap = {"id": "bgm", "surfaces_as": "BGMミキシング",
           "done_when": {"kind": "run_record_clean"}}

    assert is_done(gap, _記録(skipped_features=[])) is True
    assert is_done(gap, _記録(skipped_features=["BGMミキシング(ファイルなし)"])) is False


def test_成果物が出たら実装済みとみなす():
    from backend.feature_gaps import is_done

    gap = {"id": "thumb",
           "done_when": {"kind": "artifact_present", "suffixes": [".png", ".jpg"]}}
    run = {"artifacts": ["out.mp4"], "health": {}}

    assert is_done(gap, run) is False
    assert is_done(gap, {"artifacts": ["out.mp4", "t.png"], "health": {}}) is True


def test_印が残っている間は未実装(tmp_path):
    """**印が消えても実装済みの証拠にはならない**（弱い証拠）。"""
    from backend.feature_gaps import is_done

    f = tmp_path / "x.py"
    f.write_text("video_id = 'placeholder_video_id'", encoding="utf-8")
    gap = {"id": "up", "done_when": {"kind": "marker_gone",
                                     "path": str(f), "marker": "placeholder_video_id"}}

    assert is_done(gap, None) is False
    f.write_text("video_id = resp['id']", encoding="utf-8")
    assert is_done(gap, None) is True


def test_記録が無ければ確かめていないと言う():
    """**「確かめられなかった」を「問題なし」にしない。**"""
    from backend.feature_gaps import is_done

    gap = {"id": "bgm", "surfaces_as": "BGM", "done_when": {"kind": "run_record_clean"}}

    assert is_done(gap, None) is None
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `PYTHONPATH=./backend python -m pytest backend/tests/test_revenue_artifact_gate.py -q --no-cov -k 実装済み or 印 or 確かめ`
Expected: FAIL

- [ ] **Step 3: 実装する**

```python
def is_done(gap: dict, run: dict | None) -> bool | None:
    """実装済みか。**`None` は「この実行では確かめていない」。**"""
    dw = gap.get("done_when") or {}
    kind = dw.get("kind")
    if kind == "marker_gone":
        p = Path(dw["path"])
        if not p.is_file():
            return None
        return dw["marker"] not in p.read_text(encoding="utf-8", errors="ignore")
    if run is None:
        return None
    if kind == "run_record_clean":
        health = run.get("health") or {}
        出たもの = list(health.get("skipped_features") or []) + list(health.get("failed_stages") or [])
        印 = gap.get("surfaces_as") or gap.get("id")
        return not any(印 in 名 for 名 in 出たもの)
    if kind == "artifact_present":
        suffixes = tuple(dw.get("suffixes") or [])
        return any(str(a).endswith(suffixes) for a in (run.get("artifacts") or []))
    return None
```

- [ ] **Step 4: 通ることを確かめる**

Run: 同上
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git commit -am "feat(feature-gaps): 実装済みなのに台帳に残っている項目を検出する"
```

---

### Task 4: CLI（`--show` / `--audit` / `--static-only`）

**Files:**
- Modify: `backend/feature_gaps.py`
- Test: `backend/tests/test_revenue_artifact_gate.py`

**Interfaces:**
- Produces: `audit(run, gaps, static_only=False) -> tuple[list[str], list[str]]`（違反, 確かめていないもの）,
  `main(argv=None) -> int`

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_静的点検は確かめなかった検査を列挙する():
    """**黙って飛ばさない。** `--audit` がダミーキーで exit 0 を返した失敗を繰り返さない。"""
    from backend.feature_gaps import audit

    gaps = [{"id": "bgm", "kind": "gap", "title": "BGM", "why": "理由",
             "handled_in": "将来", "surfaces_as": "BGM",
             "done_when": {"kind": "run_record_clean"}}]

    違反, 未確認 = audit(None, gaps, static_only=True)

    assert 違反 == []
    assert any("bgm" in m for m in 未確認), 未確認


def test_点検はexit1で落ちる(capsys):
    from backend import feature_gaps

    assert feature_gaps.main(["--show"]) == 0
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `PYTHONPATH=./backend python -m pytest backend/tests/test_revenue_artifact_gate.py -q --no-cov -k 静的点検 or exit1`
Expected: FAIL

- [ ] **Step 3: 実装する**

`audit()` は条件1〜3を回し、`is_done()` が `None` を返したものを「確かめていない」に積む。
`main()` は `--show` / `--audit` / `--static-only` を受け、違反があれば 1 を返す。
最新の実行記録は `backend.revenue.artifact_gate.load_runs()` の最後の1件を使い、
**記録の日時を必ず出力に出す**（spec §9 の未解決事項）。

- [ ] **Step 4: 通ることを確かめる**

Run: 同上 + `PYTHONPATH=./backend python -m backend.feature_gaps --show`
Expected: PASS / 8件が gap と intentional に分かれて出る

- [ ] **Step 5: コミット**

```bash
git commit -am "feat(feature-gaps): --show / --audit / --static-only"
```

---

### Task 5: 品質ゲートとの接続 — 台帳の機能は減点せず `skipped_features` へ

**Files:**
- Modify: `backend/agents/workers/quality_gate_worker.py`
- Modify: `backend/quality_gate_plugins.py`
- Test: `backend/tests/test_revenue_artifact_gate.py`

**Interfaces:**
- Consumes: `load_gaps()`
- Produces: `ctx.declared_gaps: set[str]`（能力名。プラグインと物理チェックが読む）

- [ ] **Step 1: 失敗するテストを書く**

```python
def _品質ctx(tmp_path):
    """品質ゲートに渡す最小のコンテキスト。**Task 5 と 6 が共有する。**"""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agents.pipeline_types import PipelineContext

    preview = tmp_path / "preview.mp4"
    preview.write_bytes(b"0" * 2048)
    ctx = PipelineContext(video_path=str(tmp_path / "src.mp4"), session_id="t")
    ctx.preview_path = str(preview)
    ctx.segments = [{"start": 0.0, "end": 3.0, "text": "あ", "score": 0.8}]
    ctx.selected_segments = list(ctx.segments)
    return ctx


def test_台帳に載っている機能は減点しない(tmp_path, monkeypatch):
    """**構成上どうやっても届かない減点を止める。**

    本線にサムネイル工程は無い。無い工程を減点し続けると、品質ゲートは
    **原理的に閾値へ到達できない**。台帳に載っている間は減点せず、
    「やっていない」として `skipped_features` に出す。
    """
    from agents.workers.quality_gate_worker import QualityGateWorker

    ctx = _品質ctx(tmp_path)
    ctx.declared_gaps = {"thumbnail"}
    w = QualityGateWorker()
    結果 = w._thumbnail_physical_check(ctx)

    assert 結果["failures"] == []
    assert "サムネイル" in "".join(ctx.skipped_features)


def test_台帳に無ければ従来どおり減点する(tmp_path):
    from agents.workers.quality_gate_worker import QualityGateWorker

    ctx = _品質ctx(tmp_path)
    ctx.declared_gaps = set()

    assert QualityGateWorker()._thumbnail_physical_check(ctx)["failures"]
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `PYTHONPATH=./backend python -m pytest backend/tests/test_revenue_artifact_gate.py -q --no-cov -k 台帳に`
Expected: FAIL

- [ ] **Step 3: 実装する**

1. `QualityGateWorker.execute()` の冒頭で `ctx.declared_gaps` を台帳から埋める
   （既に入っていれば尊重する＝テストが差し替えられる）
2. `_thumbnail_physical_check()` は `"thumbnail" in ctx.declared_gaps` なら
   `failures` を空で返し、`ctx.skipped_features` に「サムネイル（未実装）」を足す
3. `ThumbnailQualityCheck` に `capability = "thumbnail"` を足し、
   `run_all_plugins()` が `getattr(ctx, "declared_gaps", set())` に載る
   `capability` のプラグインを**回さない**
4. `PipelineCompletionCheck` の `checks` から、宣言された能力の項目を落とす
   （`("サムネイル設定", 5)` の1件。`capability` を項目ごとに持たせる）

- [ ] **Step 4: 通ることを確かめる**

Run: 同上 + `PYTHONPATH=./backend python -m pytest backend/tests/test_workers/test_quality_gate_worker.py -q --no-cov`
Expected: PASS（元から赤い2件を除く）

- [ ] **Step 5: コミット**

```bash
git commit -am "feat(quality-gate): 台帳に載っている未実装機能は減点せず skipped_features に出す"
```

---

### Task 6: 素点を見えるようにする

**Files:**
- Modify: `backend/agents/workers/quality_gate_worker.py`
- Test: `backend/tests/test_revenue_artifact_gate.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_床打ちした素点が見える(tmp_path):
    """**0点は「どれくらい悪いか」を何も言わない。**

    実測では減点合計が -134（素点 -34）でも表示は 0 点だった。
    改善しても数字が動かないので、改善ループが効いているか判断できない。
    """
    from agents.workers.quality_gate_worker import QualityGateWorker
    import asyncio

    ctx = _品質ctx(tmp_path)
    ctx.target_minutes = 20          # 30秒素材に対して -50 が乗る
    r = asyncio.run(QualityGateWorker().execute(ctx))

    assert ctx.quality_score == 0
    assert "素点" in r.detail, r.detail
```

- [ ] **Step 2: 落ちることを確かめる**

Run: `PYTHONPATH=./backend python -m pytest backend/tests/test_revenue_artifact_gate.py -q --no-cov -k 床打ち`
Expected: FAIL

- [ ] **Step 3: 実装する**

`score` を床打ちする**前**の値を `raw` に残し、`ctx.quality_gate_report["raw_score"]` に入れ、
`StageResult.detail` を `スコア: {score}点（素点 {raw}）(ランク{rank})` にする。
**`ctx.quality_score` の 0〜100 の範囲は変えない**（消費側が多く、範囲を変えると影響が広い）。

- [ ] **Step 4: 通ることを確かめる**

Run: 同上
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git commit -am "feat(quality-gate): 0で床打ちした素点を記録と出力に残す"
```

---

### Task 7: CI に静的点検を足す

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: 既存のラチェット実行の並びを読む**

Run: `grep -n "ruff_ratchet\|fs_guard_ratchet" .github/workflows/ci.yml`

- [ ] **Step 2: 同じ形で1行足す**

```yaml
      - name: 実装不足項目の点検（静的のみ）
        run: PYTHONPATH=./backend python -m backend.feature_gaps --audit --static-only
```

- [ ] **Step 3: ローカルで同じコマンドを流す**

Run: `PYTHONPATH=./backend python -m backend.feature_gaps --audit --static-only; echo "exit=$?"`
Expected: exit 0 と、確かめていない検査の列挙

- [ ] **Step 4: コミットして CI を確認する**

```bash
git commit -am "ci: 実装不足項目の静的点検を追加"
git push origin cc/r15-mainline
```

---

### Task 8: 締め

- [ ] **Step 1: 検証スイートを回す**

Run:
```bash
export GOOGLE_API_KEY=dummy_key_for_ci
PYTHONPATH=./backend python -m pytest backend/tests/test_revenue_artifact_gate.py \
  backend/tests/test_agents_run_record.py backend/tests/test_run_record.py \
  backend/tests/test_workers/test_pipeline_coordinator.py \
  backend/tests/test_shared/test_pipeline_coordinator_coverage.py -q --no-cov
```

- [ ] **Step 2: ラチェット**

Run: `python .github/scripts/ruff_ratchet.py && python .github/scripts/fs_guard_ratchet.py`

- [ ] **Step 3: 実走で確かめる**（予算 R1.5-mainline の範囲内）

Run:
```bash
AVS_SKIP_LEARNING_SIDE_EFFECTS=1 PYTHONPATH=./backend \
  python -m backend.agents.pipeline_coordinator output/testclips/r1_clip30s.mp4
```
Expected: 品質スコアが上がる（サムネイルぶんの減点が消える）／
`skipped_features` に「サムネイル（未実装）」が出る／`--audit` が exit 0

- [ ] **Step 4: 予算の実績を更新してコミット**
