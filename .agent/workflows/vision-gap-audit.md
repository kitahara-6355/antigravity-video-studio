# ビジョン乖離度監査ワークフロー (`/vision-gap-audit`)

> **目的**: 憲法§1-25 および UXストーリー O-1〜O-12, A-1〜A-7 と現実のコード・UIの乖離を厳格に計測し、ビジョン実現度スコアを更新する。
> **基準文書**: `Human01_Official Artifact/strict_gap_review_20260415.md`
> **発動条件**: 工数大タスク完了後 / 四半期レビュー / ユーザー手動発動

// turbo-all

---

## Phase 0: 前回スコアの読み込み

### Step 0-1: 改善バックログの現状確認

```
cat "backend/branding/vision_backlog.json"
```

前回のビジョン実現度スコアと未解決バックログ件数を確認する。

---

## Phase 1: E2E完走テスト（D-01）

### Step 1-1: バックエンド起動確認

```
curl http://127.0.0.1:8000/health
```

- UP → Step 1-2へ
- DOWN → バックエンド起動してから再実行

### Step 1-2: キャッシュ除去（厳格テスト必須）

> **⚠️ 絶対ルール: 厳格監査では必ずキャッシュを除去してからテストすること。**
> キャッシュ依存の成功は「虚像」であり、評価に使用してはならない（2026-04-18 教訓）。

```
Remove-Item "backend/scripts/vault-assets/test_videos/_whisper_segments.jsonl" -Force -ErrorAction SilentlyContinue
```

### Step 1-3: パイプラインE2Eドライラン

テスト動画でパイプラインを起動し、各Workerの通過/失敗を記録する。

```
curl -X POST http://127.0.0.1:8000/api/pipeline/start -H "Content-Type: application/json" -d "{\"video_paths\":[\"backend/scripts/vault-assets/test_videos/test_30sec.mp4\"],\"target_minutes\":1}"
```

### Step 1-4: ステータス確認（10秒待機後）

```
curl http://127.0.0.1:8000/api/pipeline/status
```

各ステージの `status` を記録:
- `completed` → ✅
- `error` → 🔴（エラー内容を記録）
- `skipped` → ⚠️
- `pending` → 未到達

---

## Phase 2: UI接続テスト（D-02）

### Step 2-1: フロントエンド起動確認

Browser Agent で `http://localhost:5173` にアクセスし、画面が表示されるか確認。

### Step 2-2: 主要コンポーネント表示確認

以下の各コンポーネントが**表示可能か**をBrowser Agentで確認:

| コンポーネント | 確認方法 |
|---|---|
| ProductionPipeline | 「制作パイプライン」画面を開く |
| SmartCutPanel | SmartCutボタンを押す |
| QuickDecisionBar | クイックレビューを開く |
| StepReviewPanel | 段階的レビューを開く |
| SoulPassport | Soul Passportボタンを押す |
| YouTubeOptimizer | YouTube最適化を開く |
| OperationsDashboard | 運用監視を開く |

### Step 2-3: API接続確認

各コンポーネントが対応するAPIにリクエストを送信し、レスポンスを受信できるか確認。

---

## Phase 3: 憲法条項チェック（D-03〜D-08）

### Step 3-1: 条項別実装状態チェック

以下の各条項について、**実装が動作するか**を検証:

| 条項 | チェック内容 | 検証方法 |
|---|---|---|
| §4 Trinity評議会 | Nexus+3専門家のコード存在 | grep検索 |
| §5.2 Soul Narrative | evolution_log の自動更新 | ファイル更新日時確認 |
| §8 品質ゲート | 自動改善ループの動作 | ログ確認 |
| §9 Progressive Preview | 承認フロー強制 | API呼び出し |
| §11 ストレージ管理 | 自動クリーンアップ | cron/スケジューラ確認 |
| §12 自動進化 | 閾値トリガー動作 | decision_logger確認 |
| §15 UX至上主義 | ワンアクション原則 | UI操作テスト |
| §17 デザインシステム | design_tokens参照率 | grep検索 |
| §20 テスト | カバレッジ計測 | pytest --cov |

### Step 3-2: UX最低保証チェック

O-1〜O-12, A-1〜A-7 の各項目について:
- ✅ 動作確認済み
- ⚠️ コードはあるが未検証
- 🔴 未実装 or 動作不可

---

## Phase 4: スコアカード更新

### Step 4-1: ビジョン実現度スコア算出

以下の10軸で評価（各軸 0-100%）:

```
ビジョン実現度 = Σ(各軸スコア × 重み) / Σ(重み)
```

| 軸 | 重み | 計測方法 |
|---|---|---|
| パイプラインE2E完走 | 20 | Phase 1 結果 |
| UI→API接続 | 15 | Phase 2 結果 |
| Trinity評議会 | 5 | §4 実装状態 |
| 品質自動改善 | 10 | §8/§15.2 動作 |
| Soul自動進化 | 10 | §5.2/§12 動作 |
| ストレージ自動管理 | 5 | §11 動作 |
| Progressive Preview | 5 | §9 動作 |
| テストカバレッジ | 10 | §20 カバレッジ% |
| UX保証 O-1〜O-12 | 15 | O-項目の動作率 |
| UX保証 A-1〜A-7 | 5 | A-項目の動作率 |

### Step 4-2: バックログ更新

`backend/branding/vision_backlog.json` を更新:
- 新規発見の乖離をバックログに追加
- 解消済みの項目を `resolved` に移動
- 前回スコアとの差分を記録

### Step 4-3: レポート作成

`Human01_Official Artifact/` に以下を出力:
- `vision_gap_audit_YYYYMMDD.md` — 監査レポート
- スコアカード比較（前回 vs 今回）
- 次期改善サイクルの推奨アクション

---

## Phase 5: 次期改善サイクル設計

### Step 5-1: バックログ優先度付け

未解決バックログを以下の基準で優先度付け:

| 優先度 | 基準 |
|---|---|
| P0 | ビジョン実現度への寄与が最大（重み × 改善幅） |
| P1 | 中程度の寄与 |
| P2 | 低寄与だが放置リスクあり |
| P3 | 将来対応（ロードマップ） |

### Step 5-2: 次サイクルの実装計画策定

P0 項目を中心に、次サイクルの implementation_plan.md を作成。

---

## 終了条件

- ビジョン実現度スコアが算出され、前回と比較可能
- バックログが更新されている
- 次期改善サイクルの方向性が提示されている
