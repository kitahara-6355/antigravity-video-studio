# L1 に残る FAIL 7件の切り分け（2026-08-03）

P2 の終了条件 C-4「残る FAIL を実在の欠落か仕様の穴かに切り分ける」への回答。

**結論を先に書く。7件のうち実在の機能欠落は 1 件だけ。**
残り 6 件は照合先の書き方が実装と食い違っているだけで、機能は動いている。

前提は `docs/ux_l1_triage_20260802.md`（P1 C-5）の続き。
判定は `python -m backend.ux_verification.executor --persona owner` の実測。

---

## 全体

| 区分 | 件数 | 項目 |
|---|---:|---|
| **仕様の穴** — 機能は実在。照合先の書き方が誤り | **5** | O1-L1-02 / 03 / 04 / 06 / 07 |
| **実在の欠落** — 機能そのものが無い | **1** | O9-L1-11 |
| **仕様が不完全** — 何を指しているか特定できない | **1** | O9-L1-12 |

## 1. 仕様の穴（5件）

O-1 の 5 件はいずれも `testid` に DOM 要素ではない名前が書かれている。
説明文は API・localStorage の主張で、**対応する実体はすべて存在し、登録もされている。**

| 項目 | 宣言された testid | 説明文の主張 | 実体 |
|---|---|---|---|
| O1-L1-02 | `video-list` | 動画一覧に videos 配列が存在する | `GET /api/pipeline/videos`（`pipeline_router.py:429` / 登録済み） |
| O1-L1-03 | `video-metadata` | メタデータAPIが必須フィールドを返す | `POST /api/pipeline/videos/metadata`（`:467` / 登録済み） |
| O1-L1-04 | `extension-filter` | 動画リストに対応拡張子のみ含まれる | `GET /api/pipeline/videos`（同上） |
| O1-L1-06 | `validation-api` | バリデーションAPIが正常応答を返す | `POST /api/pipeline/videos/validate`（`:574` / 登録済み） |
| O1-L1-07 | `recent-history` | localStorage に履歴キーが存在する | **実装済み**（下記） |

`validation-api` や `video-metadata` は **DOM 要素の名前ではない。**
P1 C-5 で明らかになった「旧ハーネスが `dom_exists` のラベルで API を測っていた」
という食い違いが、O-1 にだけ testid 付きで残っていた形。

### O1-L1-07 は機能が完全に実装されている

`frontend/src/components/ProductionPipeline.jsx`:

```
 38  const saved = localStorage.getItem('pipeline_recent_videos');
 50  localStorage.setItem('pipeline_recent_videos', JSON.stringify(updated));
550  <div data-testid="recent-videos-section" ...>
```

読み書きも描画もある。**ストーリーが要求する `recent-history` が、実物の
`recent-videos-section` と名前で食い違っているだけ。**

## 2. 実在の欠落（1件）

**O9-L1-11「投稿準備バッジが存在」。**
`YouTubeOptimizerPanel.jsx` を全行走査したが、投稿準備状態を示すバッジは無い。
P1 で「仕様が無い(`no_testid`)」ではなく「機能が無い(`not_found`)」と診断できるよう
`youtube-publish-readiness` を記入してあり、そのとおり FAIL のまま残っている。

**これが Owner L1 で唯一、実装で埋めるべき FAIL。**

## 3. 仕様が不完全（1件）

**O9-L1-12「エクスポートAPIが正常応答」。**
エクスポート系のエンドポイントは 8 件あるが、YouTube 最適化メタデータの
エクスポートに当たるものは無い（proofreading / subtitle / shorts / quota / setup の
エクスポートと、レンダリング成果物のダウンロード）。

何を指しているか特定できないため、**推測で `endpoint` を書いていない。**
書けば判定は出るが、それは実装ではなく判定を捏造することになる。

## 4. 提案（判断はユーザーの領分）

1. **O-1 の 5 件は照合先を実体に合わせる。**
   - O1-L1-02 / 03 / 04 / 06 は `testid` を外し `endpoint` を記入する
   - O1-L1-07 は `testid` を `recent-videos-section` に直す
   - **`test_method` は書き換えない**（P2 の方針どおり）。
     項目の削除も説明文の変更も起きないのでラチェットに抵触しない。
     ただし**誤った仕様を消す**操作なので、実行前に承認を取る
   - 実施すれば充足率は 94.26% → **98.36%**（PASS 115 → 120）
2. **O9-L1-11 は実装が要る。** UX として投稿準備状態を出すかどうかの product 判断。
   出さないなら項目そのものの見直し（ただし削除はラチェット違反）
3. **O9-L1-12 は仕様の確定が要る。** 何をエクスポートする API なのかが決まれば、
   実在するかを機械的に判定できる

---

## 付録: 再現方法

```bash
python -m backend.ux_verification.executor --persona owner
python -m backend.ux_verification.api_contract --list-endpoints
```
