# R1.5-C4 — 依存機能を1つずつ実際に動かした記録

**2026-08-28 / HEAD `4570a5a` 系列**

正典 R1.5-C4 の verify は「`docs/` 配下の実走記録」。**4つの依存機能を1つずつ呼び、
返ってきたものをそのまま貼る。**主張ではなく出力を残す。

---

## ① YouTube 投稿 — `services.youtube_uploader.upload_video()`

**認証もファイルも揃った、本来なら投稿できるはずの場面**で呼んだ。

```
success=False / error=not_implemented / video_id=None
message=YouTube への投稿は**未実装**です。動画の隣に置いた
        `<動画名>.youtube.json` のタイトル・タグ・説明文を使って
        手動で投稿してください
```

**直す前は `success=True` / `video_id="placeholder_video_id"` を返していた。**
投稿していないのに「できた」と記録され、チャンネルの数字と実装の状態が食い違う。
2026-08-26 のユーザー決定どおり、**実装も削除もせず未実装として失敗させる**。

実装するときは `resumable upload` を同じ場所に入れる（メタデータ `body` は組み立て済み）。
台帳: `backend/config/feature_gaps.json` の `youtube_upload`。

## ② チャンネル統計 — `routers.admin_channel_router`

```
get_channel_detail("ch-001"):
  is_real=False / data_source=sample
  kpi.watch_time_hours=15200（固定値）
get_channels():
  is_real=False / 3 件
```

**YouTube Analytics には一度も接続していない。**`subscribers` も `total_views` も
`watch_time_hours` も固定値。数字そのものは残したが、**返すたびに
`is_real: false` と `data_source: "sample"` を添える**ようにした
（`DATA_SOURCE` を混ぜる形）。フロントエンドからの参照は無い（grep で確認）。

台帳: `channel_stats`。

## ③ 品質スコア — 本線の実走記録

```
run=20260827T162619967876-0000 / quality_gate 試行=5 / 最後=failed
_StageFailed: quality_gate: スコア: 89点 (ランクB)
サイドカー: score=89 / raw_score=89 / feedback 6件
```

**本線の品質スコアは動いている**（89点／閾値90）。正典が名指ししていた
「常に 0.0 になる quality_score」は**別経路**だった — `backend/core/context.py` を使う
プラグイン経路で、品質ゲートが繋がっていないため dataclass の既定値 `0.0` が
そのまま「0.0/100」と表示されていた。**測っていないことを 0点という測定結果に
見せない**よう「未計測」表示に変えた（`plugins/report_generator_plugin.py`）。

なお 2 → 89 になった経緯は引継ぎ §2.5 を参照（主因は目標尺のミスマッチ −50点）。

## ④ retention 分析 — `agents.pipeline_coordinator._run_retention_analysis()`

```
返り値=None（走った工程ではないので stage_results に積まない）
skipped_features=['retention分析（未実装）']
metadata に retention_analysis があるか: False
```

**直す前は `random.random()` で組み立てたセグメントを `success=True` で返していた。**
その中身は `ctx.metadata["retention_analysis"]` に入り、**AI メタデータの
サイドカー（成果物）にまで載っていた。**`RetentionMapPlugin.IMPLEMENTED = False` を
立て、コーディネータがそれを見て飛ばすようにした。モックのコード自体は残してある
（実装するときの土台）。

**宣言の置き場は `skipped_features`** — `stage_results` は「走った工程」の並びで、
未実装は工程の失敗ではない（C1b で決めた形）。最初これを失敗した工程として
積んだところ、`test_e2e_pipeline_scenarios` の「走った工程はすべて成功」という
主張が落ちて気づいた。

台帳: `retention_analysis`。

---

## 再現

```bash
export GOOGLE_API_KEY=dummy_key_for_ci
PYTHONPATH=./backend python -m pytest \
  backend/tests/test_revenue_artifact_gate.py \
  backend/tests/test_agents_run_record.py \
  backend/tests/test_report_generator_plugin.py -q --no-cov
```

①②④ の契約はテストで固定してある（`test_未実装の投稿は成功を返さない` /
`test_未実装のretention分析を成果物に混ぜない` / `test_未計測の品質スコアを0点として出さない`）。

## まだ直っていないこと

**4件とも「動かない」ことが分かっただけで、動くようにはなっていない。**
実装は台帳 `backend/config/feature_gaps.json` に残っており、
`python -m backend.feature_gaps --show` で一覧できる。C4 が求めているのは
「偽の success を返さない」ことなので、ここまでが範囲。
