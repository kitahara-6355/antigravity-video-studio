# 死蔵コードの棚卸し（2026-08-06）

P2 の終了条件 C-5「死蔵コード（未登録エンドポイント・到達不能コンポーネント）の
扱いを決める」への回答。

**結論を先に書く。10件の死蔵のうち、消してよいのは 2 件だけ。**
残り 8 件は `PROJECT_CONSTITUTION` が要求している機能の実装が、
**結線されていないだけ**で丸ごと眠っている。

再現:

```bash
python -m backend.ux_verification.dead_code
```

---

## 全体

| 区分 | 件数 | 実体 |
|---|---:|---|
| **未結線** — 実装はあるが呼び出し口が無い | **8** | `review_router` 7 / `ModelQuotaDashboard` 1 |
| **重複** — 同じものが呼び出し側に展開済み | **2** | `useSegments` / `RivalRadar` |

走査: エンドポイント 454 件 / frontend ソース 31 ファイル。
バックログの D-23（未登録エンドポイント）・D-24（到達不能ファイル）に対応する。

## 1. なぜカバレッジで見つからなかったか

**テストが通っていることは、そのコードが到達可能であることを意味しない。**

`backend/tests/test_routers/test_review_router.py` は自前で `FastAPI()` を組み立て、
そこへ `include_router(router)` している:

```python
@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)      # ← テストの中でだけ登録される
    return TestClient(app)
```

この 21 件は緑で、カバレッジ 75.4% にも計上されている。
しかし**本番の `backend/main.py` は `review_router` を登録していない。**
`routers/__init__.py` に import すら無い。呼べば 404 が返る。

カバレッジは「その行を実行したか」しか見ない。「本番から到達できるか」は別の問いで、
既存のゲートはどれもそれを見ていなかった。だから独立したゲートを置く。

なおバックログ D-23 は「`archives/` の E2E テストだけが参照しており」と書いているが、
**`backend/tests/test_routers/test_review_router.py` は `pytest.ini` の `testpaths`
に載っている現役のテスト**で、CI で毎回 21 件が緑になっている。
「参照しているのは archives だけ」という前提で消すと、現役テストが 21 件落ちる。

## 2. 未結線（8件）

### 2.1 `review_router` — 憲法 §16.5 の段階的レビュー機能

7 エンドポイントすべてが未登録。

| メソッド | パス | 定義 |
|---|---|---|
| GET | `/api/review/stages` | `routers/review_router.py:83` |
| GET | `/api/review/stages/{stage}` | `:100` |
| GET | `/api/review/stages/{stage}/report` | `:115` |
| GET | `/api/review/status` | `:202` |
| GET | `/api/review/summary` | `:231` |
| POST | `/api/review/stages/{stage}/approve` | `:146` |
| POST | `/api/review/stages/{stage}/revision` | `:172` |

依存する `backend/plugins/progressive_review_plugin.py` は**実在する。**
`PROJECT_CONSTITUTION` §16.5 は5段階レビュー（字幕統一感 / テロップデザイン /
サムネイル・画像 / OP・ED / 最終統合）と承認・修正指示のフローを規定しており、
このルーターはその API そのもの。

**憲法が要求する機能が、登録されていないという理由だけで存在しない。**

### 2.2 `ModelQuotaDashboard.jsx` — 憲法 §18.8 の待機オプション

`frontend/src/components/ModelQuotaDashboard.jsx`（10,287 バイト）。
どこからも import されておらず、バンドルに入らない。

呼び先の API は**両方とも実在し、登録もされている**:

| コンポーネントが叩く先 | 実体 |
|---|---|
| `GET /api/usage/two-tier-status` | `routers/usage_router.py:413`（登録済み） |
| `POST /api/usage/select-option` | `routers/usage_router.py:452`（登録済み） |

憲法 §18.8 は枠切れ時に「待機 / フォールバック / 強制使用」の3択を提示せよと
規定している。**バックエンドもフロントも完成していて、`import` 1行が無いだけ。**

## 3. 重複（2件）

### 3.1 `useSegments.js`

`frontend/src/hooks/useSegments.js`（3,003 バイト）。
`setSegments` / `activeSegmentIndex` / `cutMode` を持つ同じ状態管理が
`EditorPage.jsx`・`TranscriptionStagePanel.jsx`・`ProofreadingStagePanel.jsx`
に直接展開されている。抽出したフックが取り込まれないまま残った形。

### 3.2 `RivalRadar.jsx` — 生きている側がハードコードのモック

`frontend/src/components/RivalRadar.jsx`（3,791 バイト）。
`rivals` / `quests` / `currentSubs` を props で受ける**データ駆動の実装**だが、
到達不能。

一方 `Boardroom.jsx:162-183`（到達可能）に**同じ「ライバル出現 (RIVAL DETECTED)」
UI がインラインで書かれており、そちらは値がハードコードされている**:

```
GadgetReviewer / You: 200 / Target: 250 / 差分: 50 人
TechMastery / 目標: 10,000 人
```

**画面に出ているのはモックのほうで、props を受け取れる実装が死んでいる。**

## 4. ビルド成果物での裏取り

「到達不能」が机上の話でないことを、実際のバンドルで確認した。

```bash
cd frontend && npm run build      # vite 7.3.6 / ✓ built in 9.53s
```

| 探した文字列 | 由来 | `dist/assets/index-*.js` |
|---|---|---:|
| `two-tier-status` | `ModelQuotaDashboard` | **0** |
| `activeSegmentIndex` | `useSegments` | **0** |
| `pipeline_recent_videos` | 到達可能なコンポーネント（対照） | 1 |
| `RIVAL DETECTED` | `Boardroom`（到達可能）と `RivalRadar`（到達不能） | 1 |

最後の1件は `Boardroom.jsx` のインライン版で、`RivalRadar.jsx` 由来ではない
（同じ文字列を両方が持つため件数だけでは区別できない。出どころは
`grep -rn "RIVAL DETECTED" frontend/src/` で確認した）。

**3件とも、バンドルには入っていない。**
バックログ D-24 の「いずれも…ビルドには含まれる」という記述は事実と異なるので、
この実測で訂正する。

## 5. なぜ L1 判定に現れなかったか

3 件のうち **`data-testid` を1つも持たないものが3件**（全部）。
L1 は「ストーリーが要求した `testid` が到達可能な場所にあるか」を見るので、
`testid` を持たないファイルは `unreachable` 判定の対象にすらならない。

L1 は**要求されたものが在るか**を見る。この棚卸しはその裏返しで、
**在るのに誰からも呼ばれないもの**を見る。両方無いと片側が盲点になる。

なお `frontend/` にテストファイルは 1 つも無い（`*.test.*` / `*.spec.*` が 0 件）。
フロント側は build が通ることしか保証されていない。

## 6. 決めたこと — 増やさない

削除するか結線するかは製品判断で、実行系の領分ではない（憲法第1条）。
**この実行系が引き受けるのは「増やさないこと」**に限る。

現状の 10 件を項目ごとにベースラインへ固定し、新しい死蔵が生まれたら CI で落とす:

```bash
python -m backend.ux_verification.dead_code --ratchet          # CI ゲート
python -m backend.ux_verification.dead_code --update-baseline  # 意図した増減の締め直し
```

ベースラインは `backend/ux_verification/snapshots/dead_code_baseline.json`。
**件数の合計ではなく項目ごとに突き合わせる。** 1件が結線され別の1件が死蔵化しても
合計は動かず、集計値では見逃すため（`l1_ratchet` と同じ理由）。

計測器が仕事をしなかった場合（エントリを見失う・ルーターを走査できない・
登録状況を判定できない）は、**0 件ではなく失敗として扱う。**
走査できなかったことを緑にすると、計測器を壊すだけでゲートを黙らせられる。

## 7. ユーザーの判断を仰ぐこと

| # | 対象 | 判断 |
|---|---|---|
| 1 | `review_router` 7本 | 憲法 §16.5 を実装として復活させるか（`include_router` 1行）、機能ごと畳むか |
| 2 | `ModelQuotaDashboard` | 憲法 §18.8 を UI に出すか（`import` 1行）、畳むか |
| 3 | `useSegments` | 重複解消として削除してよいか（呼び出し側を書き換えるか、フックを消すか） |
| 4 | `RivalRadar` | 消すか、逆に `Boardroom` のハードコードを置き換えるか |

**1 と 2 は「実装が足りない」のではなく「繋いでいない」。**
どちらも憲法が明文で要求している機能なので、畳む場合は憲法側の改訂が要る
（憲法第1条によりユーザーとの協働事項）。

**4 は「消す」が正解とは限らない。** 生きている `Boardroom` 側がモックなので、
死んでいる `RivalRadar` のほうが本来の実装に近い。

なお 1 を「使っていないから消す」と判断する場合、
`backend/tests/test_routers/test_review_router.py` の 21 件も一緒に消えることに注意。

## 8. 判定の限界

隠さずに書く。

- **WebSocket は見ていない。** 走査は `@router.get` 等の HTTP 動詞だけを拾う。
  `@router.websocket` のルート（`/ws/progress`・`/ws/live`）は対象外。
  現状はどちらも登録済みなので取りこぼしは無いが、未登録になっても気づけない
- **動的な `include_router` は追えない。** ループや条件分岐で登録すると、
  登録済みでも未登録と出る（現状は 42 箇所すべてが直接呼び出し）
- **到達可能性は相対 import だけで辿る。** `@/components/...` のようなエイリアスを
  導入すると、到達しているのに死蔵と出る
- **「登録されている」は「200 を返す」ではない。** 静的走査なので、
  ハンドラが例外を投げるかどうかまでは分からない
