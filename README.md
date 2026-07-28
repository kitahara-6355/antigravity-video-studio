# Antigravity Video Studio

> **Trinity 5.0** — AI（Antigravity）による完全自律型の動画生成・編集パイプライン  
> 最終更新: 2026-06-14 07:00 JST

---

<!-- DASHBOARD_START -->

🟢 **🏁 Flash完了 — 新規Flash開設が必要 | 🌴 WEEKEND** | Phase C | 🟢 ダッシュボード鮮度: 正常（0分前に更新）

---

### 📋 ユーザー向けアクション提案

- 🚨 **【効果検証しきい値逸脱】** 2026-06-28 に警告が自動生成されました。今後の方向性についてOpusチャット内で相談の上、必要に応じて手動で改善アクション（結合度しきい値調整や代替案A適用）を検討・適用してください。
- 📦 Flashセッションが完遂済みです → **Opusセッションで新規Flashセッションを開設**してください
- 🔴 Flashセッションが自動停止されました（heartbeat_stale_1506min_threshold_60min） → **新規Flashセッション開設が必要**

> Opusセッションに相談したい場合は、いつでもOpusセッションのチャットに話しかけてください。

---

### 🗺️ ロードマップ現在地

### 🗺️ ロードマップ現在地

```
Phase C (AI高機能化)  ████████████████████████████████████████  100%
Milestone: M2.1 進行中 (復帰タグ: v2.0-pre-oss-integration)
```

完了フェーズ: Phase A (品質基盤の確立)

#### ⚠️ ロードマップ更新サジェスト

- 🟡 **ロードマップ未更新**: phase_state.json の最終更新が1098時間前です。最新の進捗を反映するためにOpusセッションで更新してください。

> 💡 ロードマップはプロジェクト推進の羅針盤です。常に最新状態を維持してください。

---

### 🧪 品質ゲート

| 指標 | 値 | ステータス |
|:---|:---:|:---:|
| **フィットネステスト** | ? passed / 1 failed / ? skipped | 🔴 |
| **xfail 残数** | 7 件 | 🔴 |
| **TDR 未解消** | 470 件 (CRITICAL: 0) | 🟢 |

---

<!-- DASHBOARD_END -->
---

## 📂 Vault分離アーキテクチャ

コード本体（Git管理）と、素材・出力・環境ファイル（Git管理外）を物理的に分離。

```text
c:\Users\PC_User\Desktop\script\
│
├─ video-automation/           【本プロジェクト: アプリ本体】
│   ├─ backend/                - Python動画生成ロジック + Orchestration Hub
│   ├─ frontend/               - ユーザーインターフェース
│   ├─ config.json             - 外部Vaultフォルダへのパス定義
│   └─ GEMINI.md               - AIエージェントの自律ルール（AI憲法）
│
├─ vault-assets/               【Vault: 素材保管庫】（Git管理外）
├─ vault-outputs/              【Vault: 出力領域】（Git管理外）
└─ vault-environments/         【Vault: 実行環境】（Git管理外）
```

---

## 🔗 リンク集

| ドキュメント | パス |
|:---|:---|
| プロジェクト憲法 | [PROJECT_CONSTITUTION.md](backend/branding/PROJECT_CONSTITUTION.md) |
| AI憲法 | [GEMINI.md](GEMINI.md) |
| 設計書台帳 | [design_stock.json](backend/agents/orchestration/design_stock.json) |
| Phase状態 | [phase_state.json](backend/agents/memory/phase_state.json) |
| 技術負債台帳 | [technical_debt_index.json](backend/agents/memory/technical_debt_index.json) |

---

## 🚀 パイプライン制御（Pipeline Coordinator）

動画生成・編集の全工程を統合制御する、パイプラインの唯一の実行パスです。[pipeline_coordinator.py](backend/agents/pipeline_coordinator.py) に実装されています。

### 1. 適用している設計パターン
- **Prompt Chaining**: 各 Worker（音声認識、AI校閲、SmartCut、プレビュー、最適化、品質チェック、レンダリング）を順次実行し、TaskContract（DoD）で成否を検証します。
- **Guardrails**: Pre/Post Hook を統合し、権限チェック（GovernanceEngine）やレート制限を自動適用します。
- **Evaluator-Optimizer**: 品質スコアが90点未満の場合、フィードバックを蓄積しながら Preview再生成 と QualityGateチェック を最大3回自動リトライする改善ループを回します。

### 2. 特徴・機能
- **サステナブル並列設計**: 直列ステージ（S1〜S3）の完了後、並列ステージ（S4〜S6）を非同期実行（`asyncio.gather`）し、最後に最終レンダリングへ移行します。
- **ディスク残量ダブルチェック**: ディスク空き容量を監視し、1GB未満で即時エラー終了、5GB未満で警告を出力します。
- **パフォーマンスバジェット**: 各 Worker の実行時間を計測し、バジェット管理クラス（`PerformanceBudgetManager`）にレポートを出力・保存します。
- **制作ナレッジ還流**: パイプライン完了時に統計情報（Dreamシグナル）を `pipeline_knowledge/` 配下に記録し、DreamEngine の学習をキックします。

---

## 🛡️ エラーハンドリング戦略（Pipeline Error Strategy）

自律型パイプラインの安定運用のため、[pipeline_error_strategy.py](backend/pipeline_error_strategy.py) は4つのエラー分類戦略と3つの高度な自律自己修復パターンを提供しています。

### 1. 4分類のエラーハンドリング戦略

| 戦略 | 役割 | 挙動 |
|:---|:---|:---|
| **RETRY** | 一時的障害への対処 | 最大3回、指数バックオフを挟んで自動リトライを行います。 |
| **FALLBACK** | 代替手段の適用 | エラー時に品質低下ログを記録した上で代替値（デフォルト値等）を返します。 |
| **FATAL** | 復旧不能な重大エラー | リトライやフォールバックを行わず、例外を即座に再送出します。 |
| **DIAGNOSE** | 非クリティカルな問題 | 警告ログの記録のみ行い、None を返して処理を続行します。 |

### 2. 3つの高度な自己修復（Self-Healing）パターン

1. **API制限/タイムアウト時の動的指数バックオフ & リトライ (`robust_retry`)**
   - 分類エンジンによって `API_RATE_LIMIT` または `NETWORK_TIMEOUT` と判定されたエラーのみを対象に、動的な指数バックオフ（API制限時は2倍の待機時間）を挟んでリトライします。
2. **JSON破損/LLM不整合時のプロンプト・パラメータ動的修正 & 再試行 (`intelligent_fallback`)**
   - LLMからの返却データの破損（`DATA_CORRUPTION`）を検知した際、自動的に `temperature=0.0` に下げて一度だけ再試行を行い、解決しない場合はフォールバック値を返します。
3. **IO/ディスク容量エラー時のクリーンアップを伴う自動修復 & 再試行 (`healing_io_retry`)**
   - `FILE_IO_ERROR` や `RESOURCE_EXHAUSTED` を検知した際、自動的にディスククリーンアップスクリプト (`cleanup_disk.main()`) を実行して一時ファイルなどを削除した上でリトライします。

---

## 🖼️ テロップ自動生成（Caption Generator）

動画内の各シーンやテーマに応じたテロップ画像を自動生成・合成する処理は、[gen_telops.py](backend/gen_telops.py) で行われます。

### 1. 処理フロー
1. **フォントスキャン**: Windows, macOS, Linux のシステムフォントを自動スキャンし、利用可能なフォントをロードします。フォントが検出できない場合は、デフォルトフォントに自動フォールバックします。
2. **ロゴ処理**: 指定されたブランドロゴ (`brand_logo.png`) をロードし、テロップのレイアウト規格（23x45）にリサイズします。
3. **描画と合成**: 指定されたテーマテキスト (`THEMES`) ごとに、半透明の背景画像（400x45）を作成してテキストを白色で描画し、ロゴ画像と連結・合成（最終サイズ: 430x45）します。
4. **出力**: 合成されたテロップ画像（RGBA形式のPNG）を一時ディレクトリに保存し、レンダリングパイプラインでの利用に備えます。

### 2. 耐障害性（Robustness）
- **フォントロードフォールバック**: システムフォントの不足や、フォントファイル読み込み時の `OSError` 発生時にプログラムを落とさず、代替フォントを使用します。
- **ロゴエラー処理**: ロゴが見つからない (`FileNotFoundError`)、または画像破損等で読み込めない (`UnidentifiedImageError`) 場合には適切に例外をスローして親パイプラインにエラーを伝播します。
- **IOエラー保護**: 一時ディレクトリがフルまたはアクセス権限がない場合の `OSError` を検知し、安全にアサーションログを記録します。

---

## 📝 字幕生成・チェックポイント処理（Subtitle Engine & Video Hash）

動画に対する音声認識・字幕生成（Whisper）の中間データ管理として、動画ハッシュおよびチェックポイントパスの自動生成機能が [video_hash.py](backend/subtitle_engine/video_hash.py) に実装されています。

### 1. 処理フローと設計
- **ハッシュ値の算出**: 動画ファイルパスから一意な SHA-256 ハッシュを計算し、その先頭 8 文字を抽出します。
- **パス生成**: 算出されたハッシュ値を用いて `_whisper_{hash}.jsonl` 形式のチェックポイントパスを動画ファイルと同じディレクトリ内に決定します。これにより、処理中に中断されても次回実行時に同一動画のキャッシュから進捗を復帰（チェックポイント復元）することができます。
- **ロバストな検証と正規化**: 入力パスの型チェック、絶対パスへの自動正規化（親ディレクトリ走査の解決）、ファイルの存在およびファイル形式の検証を行います。

### 2. 耐障害性（Robustness）
- **I/Oエラー処理**: ファイル読み取り権限不足（`PermissionError`）や、その他システム起因のI/Oエラー（`OSError`）が発生した場合には、分かりやすい日本語のエラーメッセージとともに上位層に例外を伝播します。
- **不正パラメータ防止**: 抽出するハッシュ文字列の長さ（`length`）に対する型バリデーションおよび非負・正の数チェックを行い、想定外の入力によるバグを防止します。

---

## 🔧 セットアップ

1. **Vaultフォルダ準備**: プロジェクトと同階層に `vault-assets`, `vault-outputs`, `vault-environments` を作成
2. **パス確認**: `config.json` に各Vaultへの相対パス（`../vault-*`）が記述されていることを確認
3. **実行**: `backend.core.paths` がVaultを自動解決
