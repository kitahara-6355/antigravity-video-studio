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

> **裏取り先を差し替えた**（2026-08-28）。この `run.json` は
> `output/runs/` ごと消えている（テストの autouse フィクスチャが
> `shutil.rmtree(Path("output"))` を実行していた。修正済み `60db9fa`）。
> **同じ数字は `vault-outputs/final/final_20260828_012707.quality.json` に残っている**
> — `score: 89` / `raw_score: 89` / `feedback` 6件 / `category_scores`。

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

**1ファイルずつ走らせる**（ファイル間に順序依存があり、まとめると別の場所で落ちる）。

```bash
export GOOGLE_API_KEY=dummy_key_for_ci
PYTHONPATH=./backend python -m pytest backend/tests/test_revenue_artifact_gate.py -q --no-cov
PYTHONPATH=./backend python -m pytest backend/tests/test_agents_run_record.py -q --no-cov
PYTHONPATH=./backend python -m pytest backend/tests/test_report_generator_plugin.py -q --no-cov
# 2周目で足した／直したもの
PYTHONPATH=./backend python -m pytest backend/tests/test_youtube_optimizer_router.py -q --no-cov
PYTHONPATH=./backend python -m pytest backend/tests/test_progressive_review_plugin.py -q --no-cov
PYTHONPATH=./backend python -m pytest backend/tests/test_youtube_upload.py -q --no-cov
PYTHONPATH=./backend python -m pytest tests/test_youtube_uploader_service.py -q --no-cov
# backend/tests/test_admin_channel_router.py は単体では走らない（上の注記）。CI で見る
```

**訂正（2026-08-28）。** ここには「①②④ の契約はテストで固定してある」と書いていたが
**誤りだった。** 実際に固定されていたのは **①③④** で、**②を固定するテストは1件も無かった**
（`grep -rn "is_real\|DATA_SOURCE" backend/tests/` が 0 件・gate-verifier 1周目の指摘 N-5）。
2周目で②のテストを足した（下記）。

---

# 2周目 — gate-verifier の指摘4件を潰す（2026-08-28）

1周目は **not_met**。「偽の success を止めたつもりが、**別経路で残っていた**」。

## N-1 retention 分析の API 経路が素通しだった（決定的）

`backend/routers/youtube_optimizer.py` の `/api/youtube/retention-map` は
`IMPLEMENTED` を見ずに `analyze_retention_risks()` を直接呼び、`success: True` を
返したうえ **HTML 成果物まで書き出していた**。中身は `random.random()` なので
**同じリクエストで毎回違う値が API 応答と成果物に載る**。本線
（`pipeline_coordinator._run_retention_analysis`）は同じ印を見て飛ばしているのに、
API 経路だけ抜けていた。

```
POST /api/youtube/retention-map  → 501
{"detail": {"implemented": false, "feature": "retention_analysis",
            "reason": "映像・音声の解析が未実装です（現在の中身はモック）。
                       結果を成果物や記録に混ぜないため、分析を行いません",
            "ledger": "backend/config/feature_gaps.json"}}
分析の呼び出し: 0 回 / HTML の書き出し: 0 回
```

**この挙動を `backend/tests/test_youtube_optimizer_router.py::test_retention_map_success` が
`assert ...["success"] is True` で固定しており、CI で緑だった。**
そのテストを `test_retention_map_未実装なら501で止まる` に置き換え、
`test_retention_map_実装したら通る`（`IMPLEMENTED` を立てれば従来どおり）を足して
**門が恒真でないこと**も押さえた。例外処理を試す既存3件は `IMPLEMENTED` を
立ててから通すようにした。

## N-2 品質スコアの「未計測 → 0.0点・不合格」がもう1経路に残っていた

`backend/plugins/progressive_review_plugin.py:348-353` が
`context.quality_score or 0` → `f"品質スコア: {quality_score:.1f}/100"` /
`passed = quality_score >= 90`。**`report_generator_plugin` で直したのと同じ経路**
（`backend/core/context.py:67` の既定値 0.0）の取りこぼし。
`review_router.py:131` から公開されている。

```
content : 品質スコア: **未計測**（この経路に品質ゲートは繋がっていません）
metadata: {'score': None, 'measured': False} / passed: True
overall_score: 100.0        ← 未計測は合否の分母に入れない
表      : | quality_score | 品質スコア: **未計測**… | — | - |
```

**合格に数えれば偽の success、不合格に数えれば偽の測定結果になる。**
`measured: False` の項目は集計から外し、表の状態欄も `✅`/`⚠️` ではなく `—` にした。

## N-3 チャンネル統計の印が 20 本中 3 本にしか付いていなかった

1周目は `DATA_SOURCE` を**人が選んで3本にだけ**混ぜていた。残り17本は無印で
固定値を返していた。特に `get_youtube_connection` が **`connected: true` と
現在時刻の `last_sync`** を返しており、同じファイルの `DATA_SOURCE` が
「接続していません」と書いているのと逆のことを言っていた
（現在時刻を返すのが特に悪く、**いま同期したように見える**）。
`get_growth_prediction` は `"model": "linear_regression_v2"` と**存在しない推論を
自称**していた。

**1本ずつ選ぶのをやめ、`return {` を機械的に全部拾って印を足した。**

```
経路 25 本 / 印なし 0 本
youtube-connection: {'connected': False, 'channel_id': None, 'last_sync': None, 'is_real': False}
growth-prediction : {'model': None, 'confidence': None, 'method': 'fixed_sample', 'is_real': False}
```

テストは `backend/tests/test_admin_channel_router.py` に3件足した
（`test_全エンドポイントが固定値の印を返す` が**全経路を掃く**ので、
新しい経路を足して印を忘れたら落ちる）。

> このテストファイルは**単体では実行できない**（`google.genai` を MagicMock に
> 差し替えており、他のモジュールの `from google.genai.errors import ...` が
> 落ちる）。**変更前から 31 errors で、私の変更で増えた 4 errors は新しく足した
> 4 件が同じ fixture で落ちているだけ。**CI はバッチで走らせるので緑になる（§6）。
> 手元では `TestClient` を直接組んで全経路を掃き、上の結果を確認した。

## N-4 testpaths の外で赤いまま残っていたテスト

`tests/test_youtube_uploader_service.py:322-325` が
`assert result.success is True` / `video_id == "placeholder_video_id"` を保持したまま
**赤くなっていた**。`backend/tests/test_youtube_upload.py` の重複テストで、
片方だけ直した取りこぼし。**`pytest.ini` の testpaths 外なので CI は見ていない。**

```
PYTHONPATH=./backend python -m pytest tests/test_youtube_uploader_service.py -q --no-cov
22 passed
```

> **testpaths は触らない**（バッチの区切りが変わると既存の汚染が別の場所で発火する）。
> 投稿の契約を CI で固定しているのは **`backend/tests/test_revenue_artifact_gate.py`**
> （`test_未実装の投稿は成功を返さない`）。
>
> **訂正（3周目）。** ここには「testpaths 内の `backend/tests/test_youtube_upload.py` が
> 固定している」と書いていたが**誤り。`test_youtube_upload.py` は testpaths の外**で、
> CI は走らせていない（`grep -n "test_youtube_upload" pytest.ini` = 0 件）。
> 1周目 N-5 と同じ「どのテストが契約を固定しているかの記述誤り」を、その訂正の中で
> 再発させていた（gate-verifier 2周目の指摘 C-7）。

## N-5 この文書の記述が誤っていた

「①②④ の契約はテストで固定してある」→ 正しくは **①③④**。上で訂正した。
③の裏取り先も `run.json` の消失に合わせて差し替えた。

---

## まだ直っていないこと

**4件とも「動かない」ことが分かっただけで、動くようにはなっていない。**
実装は台帳 `backend/config/feature_gaps.json` に残っており、
`python -m backend.feature_gaps --show` で一覧できる。C4 が求めているのは
「偽の success を返さない」ことなので、ここまでが範囲。


---

# 3周目 — gate-verifier 2周目の指摘を潰す（2026-08-28）

2周目も **not_met**。指摘は4件。

## C-4 直し方が間違っていた（決定的・自分で作った退行）

N-2 で「未計測を合否の分母から外す」ようにした結果、**分母が空のときに
`overall_score = 100.0` を返すようになった。** 実測（`GET /api/review/stages/final/report`）:

```
基準 8eef716 : | 全体スコア | **0.0**/100 |
2周目        : | 全体スコア | **100.0**/100 |
               「全チェック項目をパスしました！レンダリング準備完了です」
```

**何ひとつ測っていない状態で「100点・準備完了」と名乗る。**
0.0 を返す以前より強い偽の success で、直したつもりが悪化していた。

いま:

```
| 全体スコア | **未計測**（測った項目がありません）|
| quality_score | 品質スコア: **未計測**（この経路に品質ゲートは繋がって | — | - |
- **このステージでは何も測れていません。**品質ゲートが繋がっていないため、合否を判定できません
```

- `overall_score` は **`None`**（`Optional[float]`）。`0.0`（全部落ちた）と区別する
- **「見るものが無いステージ」（`items` が空）は 100.0 のまま。**「見るものはあったが
  1つも測れなかった」とは別で、条件文が名指ししているのは後者
- サマリーの平均は未計測のステージを混ぜない（`unmeasured_stages` に出す）

**契約は `backend/tests/test_routers/test_review_router.py` に置いた**（testpaths 内 = CI が見張る）。
`test_progressive_review_plugin.py` は testpaths の外なので、そこだけに置くと CI では守れない。

## C-3 チャンネル統計の掃き残し（1周目 N-4 と同じクラス）

`backend/tests/test_shared/test_cov_admin_channel_router.py`（testpaths 外）が
`connected is True` / `confidence == 0.78` を保持したまま赤くなっていた。
`backend/tests/e2e/test_e2e_m36_a7_channel_management.py:367,381` も同じ。

```
PYTHONPATH=./backend python -m pytest backend/tests/test_shared/test_cov_admin_channel_router.py -q --no-cov
27 passed          （基準 8eef716 と同じ本数）
```

あわせて `backend/tests/test_shared/test_routers_youtube_optimizer.py` の
retention テスト3件に `mock_plugin.IMPLEMENTED = True` を明示した。
`MagicMock` だと `IMPLEMENTED` が truthy で **501 の門を偶然素通りしていた**ので、
「実装済みなら通る」を試していることが読めなかった。

## C-7 検証文書の記述が誤っていた（1周目 N-5 の再発）

上で訂正した。**どのテストが CI で契約を守っているか**を、以後は実測して書く:

| 契約 | 固定しているテスト | CI |
|---|---|:--:|
| 投稿は偽の success を返さない | `backend/tests/test_revenue_artifact_gate.py` | ✅ |
| retention の API は 501 | `backend/tests/test_youtube_optimizer_router.py` | ✅ |
| チャンネル統計は全経路に印 | `backend/tests/test_admin_channel_router.py` | ✅ |
| 未計測を点数で表さない | `backend/tests/test_routers/test_review_router.py` | ✅ |
| （参考）投稿の単体 | `backend/tests/test_youtube_upload.py` | ❌ testpaths 外 |
| （参考）レビューの単体 | `backend/tests/test_progressive_review_plugin.py` | ❌ testpaths 外 |
| （参考）投稿サービスの重複 | `tests/test_youtube_uploader_service.py` | ❌ testpaths 外 |

## C-2 正典の `decision` と実装の食い違い（**2026-08-28 ユーザー決定で解決**）

> **決定: 戻り値のままにし、`decision` の文言を実装に合わせる。**
> 例外にすると `UploadResult` を受ける呼び出し元（ルーター・UI）が全部落ちるのに対し、
> 戻り値なら「失敗した」を通常のエラー表示に載せられるため。正典2箇所を訂正済み。

以下は決定の前に整理した内容。


正典 `R1.5-C4` の `decision` は「**呼ばれたら明示的に例外で止める**」だが、
実装（`backend/services/youtube_uploader.py:228-235`）は例外ではなく
`UploadResult(success=False, error="not_implemented")` を返している。

**条件文（「偽の success を返さない」）は満たしているが、`decision` の字義とは違う。**
`decision` はユーザーの領分（憲法第1条）なので、私からは変えない。ゲート報告で上げる。

- 例外にすると `UploadResult` を受ける呼び出し元（ルーター・UI）が全部落ちる
- 戻り値のままなら呼び出し元は「失敗した」を受け取って通常のエラー表示に載せられる

## C-6 CI

3周目の CI は下の「検証」に run ID を書く。

## 検証（CI）

**run `33131860127`** / headSha `416b8f6` — **conclusion: success**。

```
テスト全PASS   PASS   10,199件中 失敗0 エラー0    （要求 失敗0件）
UXラチェット   PASS   失敗0件
カバレッジ     PASS   76.0%                     （要求 70.0%以上）
CRITICAL負債   PASS   0件（参考: 全open 472件）
全条件クリア。main へのマージ条件を満たしています。
```


---

## 統一感スコアの扱い（2026-08-28 ユーザー決定）

`progressive_review` の**統一感スコア**は、1つも測れていなくても `100.0/100` を出す。

- **`8eef716` から変わっておらず、退行ではない**
- 数えているのは「報告された問題の件数」で、品質ゲート未接続とは別の指標
- C4 の条件文が名指ししているのは `quality_score` だけ

**R2（品質の担保）に送る**とユーザーが決定した。正典 `R1.5` の `limits` に記録済み。
