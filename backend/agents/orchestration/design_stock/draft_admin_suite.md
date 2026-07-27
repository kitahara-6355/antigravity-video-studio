# 設計ドラフト: 管理者統合コントロールスイート (IMP-ADMIN-SUITE)

## 概要
憲法第7.3.2条（管理者のUX最低保証）および「UXストーリー充足マトリクス」の Admin ストーリー（A-1〜A-7）を完全に充足させるため、管理者がシステムの初期設定、API使用量、YouTube実績、システム自己修復、およびMCP外部連携を統合して視認・操作できる「管理者統合コントロールスイート (Admin Suite)」の設計ドラフト。

## 1. 統合アーキテクチャ (React / FastAPI)

Admin Suite は、既存のフロントエンド（React/Next.js）に管理者専用ルート `/admin` を追加し、バックエンドの各監視APIを集約する。

```
[フロントエンド: /admin]
   │
   ├── [A-1] セットアップ ── APIキー / 環境変数設定
   ├── [A-2] クォータ監視 ── 4段階エスカレーション状況
   ├── [A-3] YouTube分析 ── 動画実績フィードバック
   ├── [A-4] 品質保証 ──── テスト合格率 / カバレッジ推移
   ├── [A-5] 異常監視 ──── Incidentログ / 復旧履歴
   ├── [A-6] MCP連携 ───── Model Context Protocol 設定
   └── [A-7] チャンネル ─── 投稿先アカウント管理
```

---

## 2. 各コンポーネントの仕様

### ① [A-1] システムセットアップ (`AdminSetupDashboard`)
*   **.env / 設定ファイルのブラウザ編集**: `GOOGLE_API_KEY`、`YOUTUBE_CLIENT_ID` などの環境変数をブラウザからセキュアに入力し、バックエンドに暗号化保存する機能。
*   **依存関係チェック**: `ffmpeg`, `ffprobe`, `python` バージョン、GPU/CPU 状態をワンクリックで診断し、不足があれば回復用の `setup_dev_env` のトリガーを提示する。

### ② [A-2] API使用量監視 (`AdminQuotaDashboard`)
*   **憲法第18.4条（4段階エスカレーション）の可視化**:
    *   **60% (Info)**: 通常ログ出力（UI上は緑）。
    *   **80% (Warning)**: 警告アラート表示（UI上は黄、管理者メール/Slack通知）。
    *   **95% (Block)**: パイプライン処理を自動サスペンドし、待機モードに移行（UI上は赤）。
    *   **100% (Ban)**: 翌日（UTC 15:00）のリセットまでAPI呼び出しを強制禁止。
*   **ティア別温存状況**: gemini-pro (Premium) 枠の20%温存量の現在値を円グラフでリアルタイム表示。

### ③ [A-3] YouTube Analytics (`AdminAnalyticsDashboard`)
*   **実績フィードバックループ**: 投稿した動画のインプレッション数、CTR、視聴維持率を YouTube API 経由で定期取得し、折れ線グラフで可視化。
*   **学習への反映**: 好成績の動画で使われていたムードやカラーパレットを検出し、`evolution_log.json` の `preference_patterns` に自動反映させるための同期トリガーボタン。

### ④ [A-4] CI/CD品質保証 (`AdminQualityDashboard`)
*   **カバレッジ推移視覚化**: `pytest --cov` の履歴データを収集し、A/B/C分類（直接変更行100%カバー）の充足率をグラフ化。
*   **TDR残件数カウンター**: 現在オープン状態の技術負債（TDR）件数と、その優先度分布（Critical / Major / Non-Critical）のリアルタイム表示。

### ⑤ [A-5] 異常検知・復旧 (`AdminIncidentDashboard`)
*   **Self-Healing ログ**: システムが自律的にポート衝突やプロセスハングを検知し、`resume_dev.ps1` などで自動修復した履歴を表示。
*   **エラーマスキング**: APIキーなどのシークレット情報がエラーログに混入していないかの自動フィルタリング状況を表示。

### ⑥ [A-6] MCP外部連携 (`AdminIntegrationDashboard`)
*   **Model Context Protocol 設定**: Cursor などの外部エディタや他のエージェントが、Antigravity のコンテキスト（現在のパイプライン状態、演出哲学など）を読み取るための MCP サーバー（`mcpserver.py`）の稼働状態、およびポートマッピングの設定画面。

### ⑦ [A-7] チャンネル管理 (`AdminChannelManagement`)
*   複数のYouTubeチャンネルの切り替え、OAuth認証クレデンシャルの管理、シリーズごとの投稿デフォルト設定（再生リスト指定、公開設定）を行う。

---

## 3. 必要なバックエンド API

*   `GET /api/admin/system/diagnose`: 依存関係の診断結果取得。
*   `GET /api/admin/quota/status`: 現在のAPIクォータとエスカレーション段階の取得。
*   `POST /api/admin/quota/override`: 待機状態から「フォールバック」または「温存枠強制使用」を選択するオーバーライドAPI（憲法第18.8条）。
*   `GET /api/admin/incidents`: 異常検知および自律復旧（Self-Healing）ログの取得。

---

## 4. セルフチェックリスト / 完了条件
- [ ] 管理者UI用ルート `/admin` および各ダッシュボード（A-1〜A-7）のReactコンポーネント実装
- [ ] 4段階エスカレーション（60%/80%/95%/100%）をシミュレートし、95%で処理がサスペンドされるバックグラウンド監視関数のテストPASS
- [ ] `setup_dev_env` による依存関係チェックの正常動作検証
- [ ] 全フィットネス関数テストが PASS すること
