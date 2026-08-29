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


---

# 4周目 — gate-verifier 3周目の指摘を潰す（2026-08-28）

3周目は **not_met**。指摘は「同じクラスの掃き残しが3度目」だった。
**「指摘されたファイルを直す」のをやめ、機械的に総当たりした。**

## 総当たりの結果

`pytest.ini` の testpaths の外にあり、R1.5 で変えた本番モジュールに触れている
テスト **127 ファイル**を1ファイルずつ実行し、`8eef716` を `git worktree` に
展開して**失敗テスト名の集合**を突き合わせた。

```
HEAD: 緑 68 / 赤 54
  → R1.5 で新しく赤くなったのは **16 テスト**
  → 残り 38 ファイルは基準でも同じだけ赤い（元から赤い・退行ではない）
```

**引継ぎ §6 の「元から赤いテスト」一覧は、これで実測の裏が取れた**（推測ではない）。

16 件はすべて「モデル ID を直書きした期待値」で、**大半は C2（解決器一本化）の回で
壊れたもの**だった。testpaths 外なので CI が一度も見ていない。

| 直し方 | 件数 |
|---|---|
| ImportError フォールバックの期待値 → 正典から引き直す | 9 |
| 既定モデルを返す経路 → `model_policy.default_model()` を新設して引く | 5 |
| 「素通し」の目印に使えなくなったモデル名 → `_deprecation_map = {}` で趣旨を保つ | 2 |

## 同じ突き合わせを CI ジョブにした

`.github/scripts/outside_testpaths_guard.py` + `testpaths 外の退行検知` ジョブ。
基準の版を worktree に展開して比べるので、**元から赤いものは自動的に無視される**
（ベースラインをファイルに固定しない — 固定すると腐る）。

**そのジョブが初回実行で17件目を捕まえた** —
`test_cov_phase5_b_class_1.py::TestWebSocketRouter::test_model_registry_import_fallback`。
手元（Windows）ではタイムアウトして「判定不能」に落ちており、
**手作業の掃引では見つからなかった。**

---

# 5周目に向けて — 4周目の指摘を潰す（2026-08-28）

4周目も **not_met**。指摘3件はいずれも実在する反例だった。

## C-5 サマリー側に「何も測っていないのに100点」が残っていた

ステージレポートは直っていたが、`GET /api/review/summary` が

```
基準 8eef716 : overall_score = 80.0
4周目の HEAD : overall_score = 100.0 / scored_stages = [] / ready_for_render = true
```

**1項目も採点していないのに 100.0 を名乗っていた。** ステージごとの 100.0
（見るものが無い）を4つ平均しただけ。3周目に「決定的・自分で作った退行」と
呼ばれた形が、ステージレポートからサマリーへ移動しただけだった。
`empty_stages` / `scored_stages` を足したのは**出所の開示であって数字の訂正ではない**。

いま:

```
overall_score = null / scored_stages = [] / ready_for_render = false
ready_for_render_reason = 採点できたステージがありません（品質ゲートが繋がっていません）
```

- `_測ったスコア()` が **`items` が空のステージも除く**ようにした
- `ready_for_render` は `pending_revisions == 0` **だけでは true にしない**。
  それは「修正を要求した人が誰もいない」の意味でしかなく、品質の主張ではない
- 契約は `backend/tests/test_routers/test_review_router.py`（**testpaths 内**）に2件

## C-6 同じ偽の success が1ファイル隣に残っていた

`backend/routers/admin_analytics_router.py`（`backend/main.py:280` でマウント済み＝
本番で到達可能）が未修正のままだった。`grep -c is_real` = **0**。

| 場所 | 何だったか |
|---|---|
| `:72-77` | `connected: True` + `last_sync: datetime.now()` — **一度も接続していないのに** |
| `:475` | 設定を更新しただけで `last_sync` に現在時刻。**設定画面を開くと「いま同期した」ように見える** |
| `:165-177` | `/retention-trend` が `40.0 + i*0.3 + (i%5)*0.5` で30日分の維持率を合成 |
| `:259-277` | `/chapter-effect` が固定の視聴時間 |

2周目 N-3 が `admin_channel_router` で「特に悪い」として直した挙動そのもの。
**24 経路すべてに `DATA_SOURCE` を機械的に付け**、`connected` を `False`、
`last_sync` を `None` にした。契約は
`backend/tests/test_admin_analytics_router.py`（**testpaths 内**）に3件。

## C-7 新しい CI ジョブが過去3周の掃き残しを1つも選べていなかった

`_参照形()` が `import {mod}` の形しか見ておらず、**いちばん普通の書き方である
`from {mod} import {Name}` に当たらなかった。** 実測で3件とも MATCHED=False:

- `test_report_generator_plugin_robustness.py`（3周目の未達根拠）
- `test_cov_admin_channel_router.py`（2周目 C-3）
- `tests/test_youtube_uploader_service.py`（1周目 N-4）

さらに `SKIP_TEST_DIRS = {"e2e"}` で `backend/tests/e2e/` を恒久除外しており、
2周目の掃き残し `test_e2e_m36_a7_channel_management.py:367,381` がそこにあった。

直した:

- **ドット付きのモジュール名はそのまま部分一致で見る**（書き方を問わない）。
  トップレベルの語だけ import の文脈に限る（`generator` のような一般語の誤ヒット回避）
- **`APIRouter(prefix=...)` の値も照合に足す。** e2e テストはモジュールを import せず
  `BASE = "http://localhost:8000/api/admin/channel"` と書くので、import 照合では
  原理的に当たらない
- **e2e を対象に戻した。** 基準の版と突き合わせる方式なので、サーバが無くて
  両方の版で同じように落ちるものは差が出ず、誤検知にならない

実測で5ファイルとも選ばれるようになった（過去3周の3件 + e2e の1件 + 17件目）。

## C-8 CI run ID の誤り（訂正）

3周目・4周目の報告で `33154713247` と書いたが**この run は存在しない**。
`4f17172` の実際の run は **`33159123056`**（conclusion success）。

## 変異テスト（新しい門が空振りでないことの確認）

```
analytics の1経路から印を外す              → 1 failed
サマリーの平均から items 空の除外を戻す      → 1 failed
ready_for_render を pending_revisions だけに → 1 failed
guard: testpaths 外に赤を1件作る            → 🚫 exit 1
```

---

# 6周目に向けて — 5周目の指摘を潰し、総当たりで残りを洗う（2026-08-29）

5周目も **not_met**。指摘3件は `08dfcff` で対応済みだったが、**この文書に
書いていなかった**ので先に記録する。そのうえで、5周連続で落ちた原因
（「同じクラスの別経路」の見落とし）に対して**先に総当たりを回した。**

## 5周目の指摘（`08dfcff` で対応済み）

| # | 指摘 | 対応 |
|---|---|---|
| **C-6** | 5周かけて直していた `/api/review/*` は本番にマウントされていない（ルート数 0）。本番で生きている品質スコアは `/api/pipeline/quality-gate/*` | quality-gate 系6経路に `QUALITY_GATE_DATA_SOURCE`（`is_real: false`）。検査していないのに `checked_at` へ現在時刻を打つのをやめた |
| **C-3** | guard の `_参照形()` が `patch("model_registry.get_model")` 形をトップレベルモジュールで拾えず、16ファイルが対象外 | `"{mod}.` / `'{mod}.` を照合に追加。対象 142 → **158 ファイル** |
| **C-8** | guard が `MAX_FILES` 超過とタイムアウトのどちらでも exit 0 | どちらも **exit 1**。`MAX_FILES` を 160 → 400 |

**ただし `08dfcff` は印を付けただけで契約テストを1件も足していなかった。**
`grep -rn is_real backend/tests` に quality-gate が出てこない状態だったので、
印を外しても何も落ちない。6周目に向けて
`backend/tests/test_routers/test_c4_quality_marks.py`（**testpaths 内**）を新設した。

## 総当たり（指摘を待たずに自分で洗った）

本番の全ルートを `TestClient` で起こして数えた。**460経路**のうち、
条件文の4カテゴリ（投稿・チャンネル統計・品質スコア・retention 分析）に
当たる語を含むものが **148経路**、GET で実際に叩けたものが **103経路**。
そのうち印が付いていたのは **43経路**だった。

### 見つかった残り（すべて本番マウント済み・すべて未検証で残っていた）

| # | 経路 | 何を偽っていたか |
|---|---|---|
| **1** | `pipeline_router` の O-7 品質改善ループ **6経路** | 72→85 のスコア推移。`apply` の実体は `improvement = 4  # シミュレーション: +4点` で、音量正規化もリエンコードも走らない。**初期状態からして `act-001` と `act-002` が `completed`**（開く前から2件の改善が終わったことになっている）。5周目に印を付けた O-6 の**190行下**で、出所は同じ `pipeline_default_states` |
| **2** | `/api/admin/integration/tool/quality-score` | `score: 92 / rank: "A"` を工程別の内訳つき・**現在時刻つき**で返す |
| **3** | `/api/admin/incident/quality-degradation` | `current_score: 72` と3点の推移を現在時刻つきで返す。**一度も測っていない品質低下を「検知した」と言っていた** |
| **4** | `director_engine.calculate_quality_score()` の except | 採点が落ちても `score: 50 / rank: "C" / **is_acceptable: True**` |

**4番がいちばん重い。** `is_acceptable` は
`frontend/src/components/DirectorBriefing.jsx:531,552,554` で
**緑の「制作開始 (Go)」ボタンを直接駆動している。** API キーが無効でも
通信が落ちても、画面には「合格しました・制作開始 (Go)」が出ていた。
**採点が一度も走っていないのに合格に見える**のは、条件文の「偽の success」そのもの。

いま:

```
score: null / rank: null / is_acceptable: false / is_real: false
comment: スコア計算に失敗しました（RuntimeError）。**採点は行われていません。**
```

### 誤検知として落としたもの（総当たりの結果を全部は直していない）

- `template_constants.py` / `soul_router.py` — 字幕の秒あたり文字数、CTR 平均 3.5% など。
  **編集の設計値と業界ベンチマークであって、このチャンネルの実測ではない**
- `services/thumbnail_analyzer.py` — 入力で分岐する規則ベースの採点（定数ではない）
- `video_pipeline/soul_feedback_engine.py` — 凍結（`limits` に記載済み）
- `backend/scratch/` と `agents/orchestration/mark_*` — 使い捨てスクリプト。本番経路ではない

## ユーザーに上げた範囲の判断（2026-08-29・3件とも決定済み）

| 問い | 決定 |
|---|---|
| 本線が使う SNS 統計のねつ造（`cross_media_service`）は「チャンネル統計」か | **含める。** 直した |
| 4カテゴリ外の admin デモ層（約110経路） | **対象外。** `limits` に記録。**6周目以降これを未達根拠にしない** |
| 開発プロセスの品質（`admin_quality_router` 25経路） | **「印」ではなく「実データへの接続」で扱う**（下記） |

### SNS クロスメディア相関分析（決定: 含める）

`metadata_source["sns_data"]` を埋める経路が**どこにも無い**ので、
`YouTubeOptWorker._run_cross_media_analysis()` は**常に**
`get_default_sns_data()` の作り物（X 12,500 フォロワー・Instagram 8,400 …）で
相関を取り、そこから決めた「最適な投稿先プラットフォーム」と推奨ハッシュタグを
**本線の `ctx.metadata["cross_media_correlation"]` に埋めていた。**

`retention_analysis` を本線で飛ばしているのと同じ扱いにした
（SNS の実データが無ければ分析しない・`skipped_features` に出る）。
サービスを直接呼ぶ経路（デモ・単体テスト）には `is_real` を付けた。
台帳: `sns_cross_media`。

### 開発プロセスの品質 — 「数字は出所を名乗る」規則を入れた

ユーザーの指示は「整合性をつけてどちらも大切にしたい。過去の開発資産は
最大限有効活用するとともに開発思想をブレずに」。開発思想を読み直して決めた:

- **憲法 §7.3.2 A-4**「push時にテスト/リント/セキュリティが自動実行」は
  **実際に GitHub Actions で動いている。** 画面が定数を返しているのは
  「実装が繋がっていない」状態であって、作り物だと札を貼って固定する話ではない
- **ペルソナ #23 選択的保持** / **憲法 §13.3 既存資産の優先活用** —
  再利用できる基盤を壊さない
- **ペルソナ #28 スコアベースの絶対評価** — 品質は客観的スコアで管理する

そこで出所を3段にした。`measured`（この実行で測った）/
`derived`（リポジトリの実データから引いた・`source` に出所）/
`sample`（作り物・`is_real: false`）。

**繋いだ結果、作り物と実体が食い違っていた:**

| 経路 | 画面の作り物 | リポジトリの実体 |
|---|---|---|
| `/ratchet` | `770/770`・連動率 **100.0%** | pass **75** / fail 16 / skip 954（`snapshots/v8_baseline.json`）|
| `/lint` | issues **2件** | **28,842件**（`.github/ruff-baseline.json`・うち W293 が 27,393件）|
| `/vision-gap` | score **60.35**（独自の定数） | **65.95**（正典 `vision_backlog.json`）|

`/vision-gap` がとくに悪い。**現在地の正典は `vision_backlog.json`**（憲法第5条）
なのに、画面が別の数字を持っていた。**台帳が2つあると、どちらが本当か分からない。**

残り22経路（テスト件数・カバレッジ・E2E・FV・各種トレンド）は **CI の実行結果が
要る**ので `sample` のまま。**無いものを繋いだことにしない。** そこは R2。

## 契約テスト（印を外したら落ちる）

| ファイル | testpaths | 内容 |
|---|:--:|---|
| `backend/tests/test_routers/test_c4_quality_marks.py`（新規）| ✅ | O-6/O-7 の**総当たり**・admin 2経路・`is_acceptable` の失敗時 |
| `backend/tests/test_admin_quality_router.py` | ✅ | 25経路の**総当たり**（出所が3段のどれかであること）・実データ接続3件・正典との一致 |
| `backend/tests/test_workers/test_cross_media_analyzer.py` | ✅ | SNS 実データが無ければ分析しない・サンプルはそう名乗る |

**総当たりにしたのは、人が25回思い出すのをやめるため。**
新しい経路を足して出所を書き忘れたら CI で落ちる。

## 旧来の挙動を固定していたテスト（新しい契約に更新した）

| ファイル | 何を期待していたか |
|---|---|
| `test_director_engine_unit.py::test_calculate_quality_score_fallback` | 採点失敗時に `score == 50 / rank == "C"` |
| `test_shared/test_director_engine.py::TestDirectorBrain::test_calculate_quality_score_fallback` | 同上 |
| `test_shared/test_batch13_director_preview.py::test_de_29_...` | 同上（`rank == "C"`）|
| `test_admin_quality_router.py::test_ratchet` | `valid is True`（**作り物が 770/770 だったから通っていた**）|
| `test_workers/test_cross_media_analyzer.py` ほか3件 | SNS データ無しで相関分析が走ること |

## 検証（手元）

```
pytest backend/tests/test_routers/test_c4_quality_marks.py     6 passed
pytest backend/tests/test_admin_quality_router.py             36 passed
pytest backend/tests/test_workers/test_cross_media_analyzer.py 8 passed
pytest backend/tests/test_director_engine_unit.py             34 passed
python .github/scripts/ruff_ratchet.py                        28842 → 28832（-10）
python .github/scripts/abspath_ratchet.py                     維持
python -m backend.ux_verification.ui_api_ratchet              95 → 95（新規 0）
python -m backend.feature_gaps --audit --static-only          exit 0
```

**基準（`8eef716`）と突き合わせて、退行が無いことを確認した赤:**
`test_ux_snapshot.py`(1) / `test_model_registry.py`(4) / `test_api_contract.py`(2) /
`test_batch18_pipeline_misc.py`(1) / `test_batch22_23_deep.py`(1) /
`test_batch14_pipeline_ws_补完.py`(2→base は 3) / `test_journey_integration.py`(1) /
`test_main_coverage.py`(2) / `test_batch29_30_deep_exec.py`(1) /
`test_youtube_opt_worker.py`(6) — **すべて `git worktree add --detach <path> main` で
基準を展開して同じ失敗を確認済み。**

---

# 7周目に向けて — 6周目の指摘2件を潰す（2026-08-29）

6周目も **not_met**。指摘はどちらも実在する反例で、**本番にマウントされ 200 を返し、
死蔵コードのラチェットにも載っていなかった。**

## なぜ6周目の総当たりで漏れたか

**GET しか叩いていなかった。** 460経路のうち「GET で実際に叩けた 103 経路」を数えて
「これで尽きた」と書いたが、今回の2件は**どちらも POST**で、片方は path パラメータと
台帳レコードが要る。過去5周と同じ「同じクラスの別経路」が、今度は POST 側に残っていた。

## 指摘1 — 公開後フィードバックが `random` を「実績」と呼び、台帳に焼き付けていた（決定的）

`POST /api/youtube/feedback-loop/{wagamama_id}`（`main.py:236` でマウント）。

`services/post_publish_collector.py` の既定は **`YOUTUBE_API_MODE=mock`**（`real` は
`NotImplementedError` を投げる＝**本番の既定で必ず作り物になる**）。
`_generate_mock_data()` が `random.Random(seed)` で CTR・維持率・再生数を組み立てる。

```
HTTP 200 {"success": true, ...
  "validation_report": {"actual": {"ctr": 3.6, "elapsed_hours": 24}, ...},
  "knowledge_distilled": true, "evolution_log_updated": true}

evolution_log.json に書かれた行:
  {"actual_ctr": 3.6, "actual_retention": 37.9, "actual_views": 27829,
   "drop_off_points": ["01:24"], "lessons_learned": ["離脱集中ポイント: 01:24。…"]}
```

**収集側は `is_mock: true` を持っているのに、そこから先へ伝わっていなかった。**
しかもこれは読み戻されている:

- `GET /api/evolution` と `GET /api/director/evolution` が印なしで公開
- `youtube_optimizer.py:290` が直近10件の `lessons_learned` を読み、
  `POST /api/youtube/pre-plan` の**企画立案に混ぜていた**

`backend/branding/evolution_log.json` は **Git 追跡下**で、既に12件焼き付いている
（`actual_ctr 5.2` / `actual_retention 65.0` / `actual_views 1000` が繰り返し）。

直したのは4箇所:

| 場所 | 何をしたか |
|---|---|
| `youtube_optimizer.trigger_feedback_loop` | `is_mock` なら **501**（`retention-map` を止めたのと同じ形・2周目 N-1）|
| `_record_post_publish_feedback` | `is_mock` なら書かずに返る。**台帳は一度書くと残る**ので二重に止める |
| 同・書き込む行 | 実績には `is_real: True` を残す（読み手が古い作り物と区別できる）|
| `youtube_optimizer.py:290`（企画立案）| `is_real: true` が無い行は混ぜない（**fail-closed**）|

既存12件は**消さずに印を付ける**（記録は残す・ペルソナ #23 選択的保持）。
**印を付ける場所は `branding_manager.get_evolution_log_for_display()` の1箇所だけ。**
読み口が2つあるので、1経路ずつ塞ぐとまた「同じクラスの別経路」になる。
保存側（`get_evolution_log()`）は素のままなので、**印はファイルへ書き戻らない。**

## 指摘2 — チャンネル統計が「Real-World Link」を名乗って固定値を返していた

`POST /api/analytics/sync`（`routers/trinity.py`・`main.py:224` でマウント）。
docstring は `Triggers the Real-World Link` だが、出所は
`branding/analytics_manager.py` の `mock_my_stats`（`# TODO: Replace with real YouTube API call`）。

```
200 {"stats": {"subscribers": 150, "total_views": 4500, "videos": 12,
                "last_updated": "<現在時刻>"}, ..., "biz_xp": 45}
```

`admin_channel_router` の `watch_time_hours: 15200` を直したのと**同じクラスが本番の
別ルーターに無印で残っていた**。`last_updated` に現在時刻を打つのも、
2周目 N-3・4周目 C-6 で直した `last_sync = datetime.now()` と同型。

さらに悪いことに、`POST /api/analytics/simulate` が任意の数値を注入でき、
`sync` がそれを印なしの「stats」として返していた:

```
simulate?views=500000  →  sync stats: {"subscribers": 5150, "total_views": 504500}
```

**収益化の閾値（登録者1,000人）を任意に超えた数字が、実績の顔で通っていた。**

`mock_my_stats` に印を付け（読み口は `get_my_stats()` の1箇所で、消費者は
`POST /api/analytics/sync` と**本線の `agents/analyst.py:80`** の2つ）、
`last_updated` を `None` にし、`sync` / `simulate` の包みにも `ANALYTICS_DATA_SOURCE` を付けた。

## ついでに直した（6周目の note・未達根拠ではない）

`frontend/src/components/DirectorBriefing.jsx:225` の
`quality_score: qualityScore || { score: 50 }, // fallback if skipped`。
**品質チェックを一度も通していないセッションのレポートに 50 点が載っていた。**
バックエンド側の `calculate_quality_score()` を直したのと同じ扱いにして、
`score: null / is_acceptable: false / data_source: 'skipped'` を送る。

## 契約テスト（すべて変異テストで空振りでないことを確認済み）

`backend/tests/test_routers/test_c4_quality_marks.py`（**testpaths 内**）に5件追加、計11件。

| 変異 | 結果 |
|---|---|
| `feedback-loop` の 501 を `if False` にする | 1 failed |
| `sync` から `ANALYTICS_DATA_SOURCE` を外す | 1 failed |
| `get_evolution_log_for_display` の印を外す | 1 failed |
| 企画立案の `is_real is True` 絞り込みを戻す | 1 failed |

**1回目の `test_成長ログの作り物に印が付く` は変異させても落ちなかった**（実ファイルの
`post_publish_feedbacks` が空だと `if 行:` で黙って素通りする空振りだった）。
既知の中身を差し込む形に書き直して、落ちることを確かめた。
**変異テストをやらなければ、緑の空振りをそのまま証拠として出していた。**

## 旧来の挙動を固定していたテスト（新しい契約に更新）

| ファイル | 何を期待していたか |
|---|---|
| `test_trinity_coverage.py::test_sync_analytics` | `resp.json()` の完全一致（印が増えて崩れた）|
| `test_trinity_coverage.py::test_get_evolution` / `test_all_endpoints_exceptions` | `get_evolution_log` をモックしていた（表示用の読み口が別になった）|
| `test_shared/test_cov_smartcut_trinity.py::test_get_evolution` | 同上（**唯一の実退行**。基準では緑だった）|

## 検証（手元）

```
pytest backend/tests/test_routers/test_c4_quality_marks.py       11 passed
pytest backend/tests/test_trinity_coverage.py                    20 passed
pytest backend/tests/test_shared/test_cov_smartcut_trinity.py    44 passed
pytest backend/tests/test_shared/test_routers_youtube_optimizer.py  123 passed
pytest backend/tests/test_youtube_optimizer_router.py           126 passed
pytest backend/tests/test_analytics_manager.py                   24 passed
pytest backend/tests/test_legacy_director_router.py              20 passed
pytest tests/test_ux_ratchet.py                                  37 passed
python .github/scripts/ruff_ratchet.py                           28842 → 28832（-10）
python -m backend.ux_verification.ui_api_ratchet --redeclare …   受理（行番号ずれのみ）
python -m backend.feature_gaps --audit --static-only             exit 0
```

`4a7eddd` の CI（run **33229835413**）は「Python テストスイート (3.13)」
「コード品質ラチェット」「シークレットスキャン」が success。

**基準（`8eef716`）と突き合わせて元から赤だと確認したもの（追加分）:**
`test_analyst.py`(14) / `test_shared/test_branding_manager.py`(5)。

## gate-verifier 自身が報告した測定の不備（記録として残す）

6周目の検証で、`net_guard` は pytest フィクスチャなので **`TestClient` を pytest の外で
回すと効かない**ことが分かった。掃引の初回に `backend/list_models.py` が
実際に googleapis.com へ出ている（400 API_KEY_INVALID・課金なし）。
**手元で本番アプリを起こすときは、自分で外向きを塞いでから叩くこと。**

## 自前の POST 掃引（6周目の指摘を受けて）

「総当たりが GET だけだった」と分かったので、**POST も掃いた**
（`net_guard` は pytest 専用なので、外向き接続は自分で塞いでから叩いた）。
4カテゴリに当たる POST は 50 経路、200 で無印だったのは 12 件。
そのうち条件文の「品質スコア」に当たるのが2件あった。

### 見るものが無いのに満点を返していた（`/api/quality/check`・`/verify`）

```
POST /api/quality/check  {}
  →  {"is_ready": true, "score": 100,
      "summary": "✅ 優秀な品質です。レンダリングを推奨します。"}
```

`_calculate_score()` は 100 点からの**減点式**なので、**入力が空だと減点対象が
1つも見つからず必ず満点になる。** 動画を1フレームも見ていないのに
「優秀・レンダリング推奨」。4周目 C-5（`/api/review/summary` が1項目も採点せず
100.0）と同型だが、**あちらは死蔵で、こちらはフロントエンドが呼ぶ本番経路**
（`frontend/src/gateway/endpoints.js` の `/api/quality/*`）。

`run_gate()` に「採点する材料が1つでもあるか」の門を足し、
無ければ `score: None / scored: False / is_ready: False` を返す。
`QualityReport` に `scored` を追加した（**「問題ゼロで満点」と「見ていない」を
取り違えないための印**）。

```
POST /api/quality/check  {}
  →  {"is_ready": false, "score": null, "scored": false,
      "summary": "⚠️ 採点していません（脚本・シーン・字幕のいずれも渡されていません）。
                  **品質を保証する材料がありません。**"}
```

### QA エンジンが落ちても「進行可能」と言っていた（`verify_production_quality`）

`director_engine.py:724` の except が
`{"is_ready": True, "score": 80, "suggestions": ["自動チェックに失敗しましたが、進行可能です。"]}`
を返していた。**QA エンジンが一度も走っていなくてもレンダリングへ進めた。**
6周目に直した `calculate_quality_score()` の except と**同じ関数群の隣**。
`is_ready: False / score: None / is_real: False` にした。

### 変異テスト

| 変異 | 結果 |
|---|---|
| 空入力の門を `if False` にする | 1 failed |
| `verify_production_quality` の except を `is_ready: True / score: 80` に戻す | 1 failed |

### 旧来の挙動を固定していたテスト（更新）

`test_quality_gate_agent.py`(3) / `test_shared/test_batch7_zero_pct.py`(4) /
`test_director_engine_unit.py`(1) / `test_shared/test_batch13_director_preview.py`(1)。
いずれも**空入力で満点・検査失敗で進行可能**を期待していた。

**元から赤（確認済み・追加分）:** `test_quality_unified.py` は
`ModuleNotFoundError: No module named 'unified'` で収集できない（testpaths 外・基準でも同じ）。

---

# 8周目に向けて — 7周目の指摘2件と CI の赤を潰す（2026-08-29）

7周目も **not_met**。指摘は2件とも実在した。加えて `ae93f60` の CI
（run **33232106707**）が赤くなっており、そちらも同時に直した。

## 指摘1 — 成長ログの読み口は**3つ**あった（決定的）

6周目に `branding_manager.get_evolution_log_for_display()` へ印を集約し、
その docstring に**「読み口が2つあるので印を付ける場所は1つにする。
1経路ずつ塞ぐと同じクラスの別経路になる」**と書いた。**その文章自身が間違っていた。**

| 読み口 | 経路 | 6周目の状態 |
|---|---|:--:|
| `GET /api/evolution` | `routers/trinity.py` | ✅ 印あり |
| `GET /api/director/evolution` | `routers/legacy_director_router.py` | ✅ 印あり |
| **`GET /api/v1/mcp/resources/evolution_log`** | `mcp_server.py` → `api_versioning.py:67` | ❌ **印なし** |

3つ目は `branding_manager` を通さず JSON を直接読むので、集約点を**迂回**していた。
同一プロセスでの対照（gate-verifier 実測）:

```
GET /api/v1/mcp/resources/evolution_log  →  post_publish_feedbacks 12件 / 印のある行 0件
GET /api/evolution                        →  同 12件 / 印のある行 12件
```

**過去7周の総当たりは `/api/v1/*` を一度も含んでいなかった**（この文書に `v1` も
`mcp` も1度も出てこない）。MCP ルーターは v1 プレフィクスの下にしか存在しない。

直し方を変えた。**印そのものを `backend/evolution_log_marks.py` に出し、
`branding_manager` と `mcp_server` の両方がそこに依存する形にした。**
`mcp_server` は起動を軽く保つため `branding_manager` を import しないので、
**両方が依存できる、依存を持たない場所**が要る。「読み口を増やしたら印も付ける」
ではなく「**印を付けずに読む道が無い**」に寄せる。

ついでに `mcp_server._calculate_quality_score()` も直した。
`round(completed / max(len(stages), 1) * 100)` なので、**ステージが1つも無いと
`0/1*100 = 0`** になり、未計測が「0点」として出ていた。条件文が名指しする
「常に 0.0 になる quality_score」と同型（2周目 N-2 と同じ形）。

## 指摘2 — 私の契約テストが**また空振り**だった

`test_企画立案は作り物の学びを混ぜない` は

```python
assert 'fb.get("is_real") is True' in src   # ソース文字列の grep
```

で、**挙動を一度も呼んでいなかった。** 絞り込みを `list(feedbacks)` に戻しても
文字列がコメントに残るだけで緑のまま（gate-verifier が変異生存を実測）。

**空振りを作るのはこれで2件目。**（1件目は `test_成長ログの作り物に印が付く` で、
実ファイルが空だと `if 行:` で素通りしていた。）
挙動で見る形に書き直し、変異させて落ちることを確かめた:

```
実績 = [fb for fb in feedbacks if fb.get("is_real") is True]  →  実績 = list(feedbacks)
  → test_企画立案は作り物の学びを混ぜない  1 failed
```

**教訓: 「テストが緑」は証拠にならない。「変異させたら赤くなる」が証拠。**

## 副次の指摘 — 材料の門が緩かった

`POST /api/quality/check {"scenes":[{}]}`（空の dict 1個）が
`score: 100 / 「✅ 優秀な品質です。レンダリングを推奨します。」` を通していた。
`ae93f60` で足した門は `bool(content.get("scenes"))` を見ていたので、
**中身の無い入れ物でも通った**（4検査のうち3つは空を見たまま）。
`name` / `text` に中身がある行を数える形に締めた。

## CI が赤くなっていた件（run 33232106707）

| ジョブ | 何が落ちたか | 原因 |
|---|---|---|
| Python テストスイート | `test_c4_quality_marks.py` の2件 | **他のテストが `sys.modules` に残した MagicMock。**`test_render_router.py` などが `patch.dict("sys.modules", {...})` で `branding_manager` を差し替えたまま漏らす。**単体では緑なのに全件実行だけ落ちる** |
| testpaths 外の退行検知 | 5件 / 3ファイル | 下記 |

**手元（Windows）では再現しなかった。** 汚染は
`pytest backend/tests/test_render_router.py backend/tests/test_routers/test_c4_quality_marks.py`
の2ファイル同時実行で再現できた。**モジュールでないものだけ**を `sys.modules` から
落とす autouse フィクスチャを入れた（実体はそのまま使う）。

testpaths 外の3ファイル:

- `tests/test_quality_gate_agent.py` — **`backend/tests/` 側と同名の重複**。
  `backend/tests/` だけ直して root 側を見落としていた
- `test_shared/test_director_engine.py::test_verify_production_quality_fallback` —
  `is_ready: True` を期待していた（`ae93f60` で直した挙動の取り残し）
- `test_e2e_stability.py` の2件 — **私の変更とは無関係の環境依存だった。**
  `create_test_video` は `subprocess.run` の前に `os.access(output_dir, os.W_OK)` を見る。
  `Path.mkdir` をモックしているのでディレクトリは作られず、**Linux では
  `os.access` が False を返して `PermissionError` になり `unlink` へ到達しない。**
  `/tmp/test_dir` が実在するかどうかで結果が変わっていた。
  `os.access` もモックして決定的にした

## 契約テスト（17件・すべて変異テストで確認済み）

| 変異 | 結果 |
|---|---|
| MCP の読み口から印を外す | 1 failed |
| MCP の「0点ガード」を外す | 1 failed |
| 材料の門を `bool(scenes)` に戻す | 1 failed |
| 企画立案の fail-closed を戻す（**7周目に生存した変異**）| 1 failed |

## 旧来の挙動を固定していたテスト（更新）

`tests/test_quality_gate_agent.py`(2) / `test_shared/test_director_engine.py`(1) /
`test_shared/test_mcp_server.py`(1) / `tests/test_mcp_server.py`(2)。

**元から赤（基準 `main` と突き合わせ済み）:** `test_shared/test_branding_manager.py`(5)。

---

# 9周目に向けて — 8周目の指摘と、掃引の絞り方そのものを直す（2026-08-29）

8周目も **not_met**。指摘は1件だが、**掃引の作り方が間違っていた**ことが分かった。

## 指摘 — 書き出し前の品質スコアが `return 95` の直書きだった（決定的）

`backend/routers/render.py`

```python
def _get_quality_score() -> int:
    """品質スコアを取得（O-6連携）"""
    # 実装ではquality_gate APIから取得する
    # テスト用にデフォルト95を返す
    return 95
```

```
POST /api/render/start → 200
{"success": true, "quality_score": 95, "message": "レンダリングを開始しました", ...}
```

三重に悪い:

1. **何も測っていないのに `quality_score: 95` を `success: true` で返す**
2. **S17 の品質ブロックが死んでいた。** `if quality_score < 90 and not req.force_render:`
   は 95 が定数なので永久に偽。**書き出し前の品質ゲートは一度も止まらず、
   `force_render` も意味を失っていた**
3. 同じ 95 が `_render_jobs[job_id]["quality_score"]` に記録される

本番マウント済み（`main.py:227`）で、**UI から呼ばれる**
（`ProductionPipeline.jsx:1015` → `endpoints.js:75`）。リポジトリ自身の UI-API
ラチェット台帳がこの結線を記録している（`ui_api_baseline.json:507`）。**元から**で、
`limits` のどの除外にも当たらない。

**しかも `backend/tests/test_render_router.py:268`（testpaths 内）が
「デフォルトの95が返るため、ブロックされずに開始するはず」と書いて、
この偽 success を CI 緑で積極的に保証していた。**

### 直し方

本線（`agents.pipeline_coordinator._write_quality_sidecar`）は最終動画の隣へ
`*.quality.json` を書いており、**実測はそこにある**（実走で 89 / 94 / 88 / 89）。
その関数の docstring 自身が「**消費者として宣言していた render は
`quality_score`（数値）しか読んでおらず**」と書いていた。
**宣言していた消費者が、実は読んでいなかった。**

直近の `*.quality.json` を読む形にした。実測が入ったので **S17 のブロックが
初めて生きた**:

```
POST /api/render/start                        → 200 {"success": false, "error": "quality_block",
                                                     "quality_score": 89, "is_real": true}
POST /api/render/start {"force_render": true} → 200 {"success": true, "quality_score": 89}
```

サイドカーが無い（＝本線を実走していない）ときは**点を名乗らずに通す**。
`quality_score: null / quality_checked: false` を返す。
**ここで止めないのは、以前も 95 の直書きで素通りしていたから**で、
止める方針に変えるなら UI の書き出しから本線の品質ゲートを直接呼ぶ結線が先
（台帳に `render_quality_gate` として登録）。

## なぜ8周も出なかったか — **掃引の絞り方が間違っていた**

過去8周の掃引は「**パス文字列**に4カテゴリの語を含むか」で母集団を作っていた
（6周目: 460→148→GET 103 / 7周目: POST 50 / 8周目: v1 固有 7）。
`/api/render/start` は**パスに語を1つも持たないが、応答本文に `quality_score` を持つ**。
絞り込みが本文ではなくパスに掛かっていたので、**どの周回でも母集団に入っていなかった**。

そこで**応答本文で絞る掃引**に作り直した。200 を返した **345 経路**のうち、
4カテゴリの数字を無印で返すものが **14 件**。うち実在の欠陥は3件だった。

| 見つかったもの | 何が偽だったか |
|---|---|
| `SelfReviewEngine._fallback_review()` | docstring が**「フォールバックレビュー（デフォルト合格）」**。`passed: True / overall: 0.75` を返し、`POST /api/antigravity/self-review/check` が AI レビュー未実行でも `{"passed": true, "score": 0.75}` を返していた。**`calculate_quality_score` / `verify_production_quality` と同じクラスの3件目** |
| `AnalyticsManager.scout_rivals()` | `mock_rival_db` の固定値（TechStarter 180人 / TechMastery 15,000人）から `random.choice` で選ぶだけ。`GET /api/status` が `subs` / `views` つきで返す |
| `/api/admin/integration/tool/evolution-log` | セッションごとの点（88 / 91 / 93）と日時が定数。`/tool/quality-score` の隣 |

**誤検知だったもの**: `/api/thumbnail/history`（`actual_ctr: null` で正直）、
`/api/admin/integration/dashboard`（`sections` の文字列に "quality_score" が入るだけ）、
`/openapi.json`（スキーマ文書）、`/themes/recommend`・`/api/smartcut/finalize`・
`/api/shorts/candidates`（入力から計算する実値）。

## 8周目の note も直した（未達根拠ではない）

- `routers/pipeline_report.py:196` `quality.get("score", 0)` — 未計測が「スコア: 0点」と出ていた
- `ProductionWizard.jsx:176` `quality_score || 0` — 同上（`品質スコア0点`）

## 契約テスト（21件・新規4件はすべて変異テストで確認）

| 変異 | 結果 |
|---|---|
| `render` を `return 95` に戻す | 1 failed |
| レビューを「デフォルト合格」に戻す | 1 failed |
| ライバルの印を外す | 1 failed |
| 進化ログツールの印を外す | 1 failed |

**新しいテストからソース文字列の grep を外した。** 7周目に「文字列がコメントに
残るだけで通る」空振りを指摘されており、**実際、書きかけの版で自分のコメントに
`return 95` が入って誤検知した。** 挙動だけで見る。

## 旧来の挙動を固定していたテスト（更新）

`test_render_router.py::test_start_render_default_quality`（**偽 success を緑で
固定していた張本人**）を、未計測とブロックの2本に置き換えた。ほか
`tests/test_self_review_engine.py`(2) / `test_scratch_self_review_engine.py`(5) /
`test_shared/test_cov_phase5_a_class.py`(3) / `test_analytics_manager.py`(3)。

**元から赤（基準と突き合わせ済み・追加分）:**
`test_shared/test_batch17_engines_plugins.py::test_cr_04_collect_model_requirements_exceptions`。

---

# 10周目に向けて — 未計測の番兵値を根から直す（2026-08-29）

9周目も **not_met**。指摘は3件だが**根は1つ**だった。

## 根本原因 — 未計測の番兵値が生産側と判定側で食い違っていた

```
生産側: PipelineContext.quality_score: int = 0      （agents/pipeline_types.py:120）
判定側: 採点した = isinstance(quality_score, (int, float))  ← 0 でも True
```

**8周目に入れた「`None` なら未計測」の門は、本番から一度も通らなかった。**
生産側が出すのは `0`（int）なので、`isinstance` は常に真になる。
つまり `GET /api/pipeline/report` は相変わらず「総合スコア: **0.0点**」を出し、
UI は「0点 / ❌ 不合格」を描いていた。**条件文が名指しする
「常に 0.0 になる quality_score」は、まだ生きていた。**

しかも `pipeline_report.py:392` の HTML は
`{quality.get('score', 'N/A')}点` を直接埋めており、**私が足した門を
まったく通っていなかった。**

### 直し方 — 値で「無い」を表すのをやめる

**0 は実際に取りうる点なので、値の側で「無い」を表そうとすると必ず取り違える。**
「測ったかどうか」を値と別に持つことにした。

| 場所 | 何をしたか |
|---|---|
| `agents/pipeline_types.py` | `quality_scored: bool = False` を追加（本線の context）|
| `core/context.py` | 同上（`ProductionContext` にも同じ取り違えがあった）|
| `agents/workers/quality_gate_worker.py` | **ここでしか立てない**（採点した瞬間に True）|
| `agents/pipeline_coordinator.py` | `_build_result` が `quality_scored` と `quality_details["scored"]` を持ち回す |
| `routers/pipeline_report.py` | 門を旗に繋ぎ、**HTML 側にも `_品質の表示()` を通した** |
| `ProductionWizard.jsx` | 分割代入の既定 `quality_score = 0` が `typeof === 'number'` を真にしていた → `null` に |
| `ProductionPipeline.jsx` | 「0点 / ❌不合格」を「未計測」と描き分ける |

**`0 点`（採点して 0 だった）と `未計測`（見ていない）を書き分けられる**ようになった。

## 指摘A — 書き出しの未計測ブロック（2026-08-29 ユーザー決定）

**「必ず止める。`force_render` でも越えられない」**に決まった。ユーザーへ示した事実:

- **この経路は何もレンダリングしていない。**`_render_jobs` に dict を登録して
  `status: "rendering"` を返すだけで、ffmpeg も背景タスクも出力ファイルも無い
- **本線は通らない。**`pipeline_coordinator` は `RenderWorker` で自分で書き出す
- UI は既に `force_render: !is_ready` で呼ぶ設計なので、
  「強制で越えられる」にすると**門が無いのと同じ**になる

止めても実作業は1つも止まらない、と分かった上での決定。

## 指摘A の付随 — **別の動画の点を付けていた**

9周目が見つけた鋭い点。`_品質の出所()` は
`vault-outputs/final/*.quality.json` を **mtime 最新で1件**返すだけで、
`/api/render/start` は**どの動画を書き出すのかを言う引数を持っていなかった**。
つまり「直前に測った**別の動画**の点」が
`is_real: true / data_source: "derived"` として今回のジョブに付いていた。
**8周目に私が入れた `derived` の主張自体が根拠を欠いていた。**

`_品質の実測(video)` に作り替え、`RenderStartRequest.video_path` を足した。
**動画を言われなければ未計測**（fail-closed）。UI も `final_path` を渡すようにした。

```
{}                                        → quality_unmeasured（force_render 不可）
{"force_render": true}                    → 同上
{"video_path": "final_20260828_091542.mp4"} → quality_block（実測 89 < 90）
上に force_render: true                    → success（89点・出所つき）
```

## ついでに

`/api/admin/integration/tool/evolution-log` に残っていた
`last_updated: datetime.now().isoformat()` を `None` にした
（9周目の「参考」で指摘された、2周目・4周目・5周目と同型の残り）。

## 契約テスト（26件・新規5件はすべて変異テストで確認）

| 変異 | 結果 |
|---|---|
| `quality_scored` の既定を True にする | 1 failed |
| レポートの門を値判定に戻す | 1 failed |
| 未計測でも書き出しを通す | 1 failed |
| 動画を言われなくても最新のサイドカーを拾う | 1 failed |

## 9周目が確認したこと（こちらは met）

- **契約テスト21件すべてが変異で死ぬ**ことを、24変異の総当たりで確認された
  （空振り3件目は無し）
- **CI が完走して緑になった** — `aa7e62f` の run **33240074434** は4ジョブすべて success。
  `testpaths 外の退行検知` が初めて完走した（228ファイル×2版）。
  テスト **10,231件 失敗0 / カバレッジ 76.0%**

### CI が長らく緑にならなかった理由（記録）

`ci.yml` の `concurrency` は PR イベントで `cancel-in-progress: true`。
`testpaths 外の退行検知` は1時間超かかるので、**1周ごとに push するたび
走行中の run が打ち切られていた**（`908eeff` の run 33237682523 は
228 中 36 で cancelled）。**周回のたびに push しない**か、
run の完走を待つ運用が要る。
