# 単独スクリプト → ハーネス正規移行ワークフロー

## 概要

単独スクリプト（`src/` + Phase18安定版）の成功実績をハーネス統合システム（`backend/`）へ移行するための正規ワークフロー。

### 設計原則（2026-04-13 承認）

- **アーキテクチャ**: Anthropic公式 [Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents) に準拠
- **API実行**: Google Gemini API（無料枠500RPD最適化）
- **核心方針**: パイプライン制御は **Workflow（コード制御）**、LLMは **ステージ内部のAI判断のみ** に使用

## フェーズ構成

```
Phase A: 差分分析サイクル（v1〜v10）          ← ✅ 完了 (2026-04-13)
Phase A': メタ分析                             ← ✅ 完了 (2026-04-13)

Phase B: 4層分離アーキテクチャ実装（Strangler Fig方式）
  B-1: Harness-on-Legacy ブリッジ（Layer 1 + 2）
  B-2: Google APIゲートウェイ統合（Layer 3）
  B-3: メディア・品質レイヤー統合（Layer 3 + 4）

Phase C: Fitness Function構築
  C-1: Architecture Fitness Function 8本の定義・実装
  C-2: 自動テストスイートへ組み込み
  C-3: 潜在問題の自動検出→修正

Phase D: 残存個別修正 + 最終検証
  D-1: FF-C3で検出された問題の修正
  D-2: フロントエンドUI連携修正
  D-3: 最終E2Eテスト + /harness-audit 監査
```

---

## Phase A: 差分分析サイクル（✅ 完了）

### 成果

- **10サイクル反復分析**: v1〜v10（B系列〜K系列）
- **累計発見**: 54件（v3で22件修正済み、32件未解決）
- **メタ分析による根の問題特定**: 5つの Root Cause に集約
- **アーキテクチャ判定**: 現行ADK SequentialAgentは Anthropic "Agent" パターンの誤適用

### 分析サイクル履歴

| サイクル | 対象レイヤー | 新規発見 | 系列 |
|---|---|---|---|
| v1 | 旧→新ファイルマッピング | 12件 | B系列 |
| v2 | API存在チェック | 7件 | C系列 |
| v3 | 根本原因追跡 | 8件 | D系列 |
| v4 | パイプライン制御フロー | 8件 | E系列 |
| v5 | テンプレート・品質ゲート | 4件 | F系列 |
| v6 | ハーネスインフラ | 3件 | G系列 |
| v7 | メディア処理 | 4件 | H系列 |
| v8 | フロントエンド | 3件 | I系列 |
| v9 | モデル管理 | 3件 | J系列 |
| v10 | エッジケース・エラーパス | 4件 | K系列 |

### 参照ドキュメント

- `Human01_Official Artifact/20260413_v10最終統合版_解決対象リスト.md`
- `Human01_Official Artifact/20260413_v10メタ分析レポート.md`
- `Human01_Official Artifact/20260413_アーキテクチャ改善方針v2.md`

---

## Phase B: 4層分離アーキテクチャ実装

### ターゲットアーキテクチャ

```
Layer 1: Pipeline Control — Anthropic "Prompt Chaining" パターン
  決定的Worker順次実行 + ゲートチェック。LLMは呼ばない。

Layer 2: Harness Middleware — Anthropic "Guardrails" パターン
  HookSystem (Pre/Post/Failure)
  GovernanceEngine (Permission/Tracing)
  SessionManager (Progress/Resume/WebSocket)

Layer 3: AI Execution — Google Gemini API
  AI-Powered: ProofreadWorker, SmartCutWorker, YouTubeOptWorker
  Non-AI: TranscribeWorker (Whisper), PreviewWorker (FFmpeg), RenderWorker (FFmpeg)

Layer 4: Infrastructure — 共有基盤
  PipelineContext, template_config, model_governance, disk_manager, safe_io
```

### B-1: Harness-on-Legacy ブリッジ（1-2日）

**目標**: Layer 1 (Prompt Chaining) + Layer 2 (Harness Middleware) の統合

**作業**:
1. `pipeline_coordinator.execute()` に HookSystem/GovernanceEngine/SessionManager を装着
2. `HARNESS_MODE` 分岐を廃止 → 単一パスに簡素化
3. `adk_bridge.py` の ADK オーケストレーション部分を無効化
4. `pipeline_router.py` を単一パスに簡素化
5. `template_config.set_active_template()` を `execute()` 開始時に呼び出し
6. WebSocket 進捗通知を SessionManager 経由に統合
7. 戻り値を統一インターフェースに（quality_score, segments_count 等を保証）

**自動解消する問題**: E-02, E-03, G-02, K-01, K-03, T3-01, T3-02（7件）

**完了条件**:
- [ ] py_compile 全ファイル 0 エラー
- [ ] pytest 全パス
- [ ] `/health` 応答確認
- [ ] Browser Agent で Pipeline UI 動作確認
- [ ] `_pipeline_state["stages"]` がHarnessパスで正常更新

### B-2: Google APIゲートウェイ統合（1日）

**目標**: Layer 3 (AI Execution) の統一。全Gemini呼び出しを `model_governance.call()` に。

**作業**:
1. `model_governance` に `call()` メソッド追加（タスク→モデル選択・フォールバック・RPD追跡）
2. 全Worker の Gemini直接呼び出し → `model_governance.call()` に統一
3. `ModelRegistry` のタスクマッピングを `model_governance` に統合
4. `GovernedModelsProxy` / `get_gemini_client()` を廃止

**自動解消する問題**: E-07, J-01, J-02, T3-03, T3-04, K-04（6件）

**完了条件**:
- [ ] `grep "get_gemini_client" backend/` → 0件
- [ ] 全AI Worker が `model_governance.call()` 経由
- [ ] 429/503 フォールバック動作確認

### B-3: メディア・品質レイヤー統合（1日）

**目標**: Layer 3 (Non-AI Workers) + Layer 4 (Infrastructure) の整備

**作業**:
1. `AudioMaster` を `RenderWorker` に統合（`print()` → `logger`、`template_config` 連携）
2. 品質プラグインのサイレント失敗をログ化
3. `bare except:` → `except Exception:` 一括置換（本番パス上）
4. `duck_amount` パラメータをFFmpegコマンドに反映

**自動解消する問題**: H-01〜H-03, T3-05, F-02〜F-04, E-08, G-03（9件）

**完了条件**:
- [ ] `grep "except:" backend/*.py` → 本番パスで0件
- [ ] `grep "print(" backend/audio_master.py` → 0件
- [ ] AudioMaster が template_config のLUFS設定を使用

---

## Phase C: Fitness Function構築（1日）

### 目的

手動v11-v20分析ではなく、**自動テストで潜在問題を継続検出**する仕組み。

### Architecture Fitness Functions（8本）

| # | テスト名 | 検出対象 | 合格基準 |
|---|---|---|---|
| FF-1 | bare-except検出 | `except:` パターン | 0件 |
| FF-2 | print()検出 | 本番コードのprint | 0件 |
| FF-3 | デュアルパス検出 | HARNESS_MODE分岐 | 0件 |
| FF-4 | 直接モデルアクセス検出 | `get_gemini_client()` 直接呼び出し | 0件 |
| FF-5 | PipelineContext分断検出 | pipeline_tools.py内のContext新規生成 | 0件 |
| FF-6 | ステージ進捗API契約テスト | `/api/pipeline/status` レスポンス形状 | stages正常 |
| FF-7 | エンドポイント存在テスト | フロントエンドが参照する全APIパス | 全て応答 |
| FF-8 | template_config初期化テスト | パイプライン開始時にis_active | True |

---

## Phase D: 残存個別修正 + 最終検証（1日）

### 作業

1. Phase C の Fitness Function で検出された問題の修正
2. フロントエンド修正: I-01（存在しないエンドポイント）、I-02（残像表示）、I-03（WebSocket統合）
3. 個別修正: E-01（マジックナンバー）、E-05（ハードコードパス）
4. 最終E2Eパイプラインテスト

### 移行完了判定

- [ ] 全Fitness Function PASS
- [ ] E2Eパイプラインテスト 7/7 ステージ PASS
- [ ] 品質スコア 85点(B)以上
- [ ] `/harness-audit` 監査合格
- [ ] Gemini API 呼び出し ≤ 4回/実行（旧14回から78%削減）

---

## 付録A: ADK再配置方針

ADKは「廃止」ではなく「再配置」。

- **パイプライン制御（SequentialAgent）**: ❌ 撤去
- **将来的にステージ内部エージェント**: ⚠️ SmartCut / QualityGate で複雑な判断が必要になった場合に再利用可能
- **現時点**: ✅ 直接Gemini API呼び出しで十分（"Start Simple"）

## 付録B: 問題系列命名規則

| サイクル | 系列 | 例 |
|---|---|---|
| v1 | B系列 | B-01, B-02, ... |
| v2 | C系列 | C-01, C-02, ... |
| v3 | D系列 | D-01, D-02, ... |
| v4 | E系列 | E-01, E-02, ... |
| v5 | F系列 | F-01, F-02, ... |
| v6 | G系列 | G-01, G-02, ... |
| v7 | H系列 | H-01, H-02, ... |
| v8 | I系列 | I-01, I-02, ... |
| v9 | J系列 | J-01, J-02, ... |
| v10 | K系列 | K-01, K-02, ... |

## 改定履歴

| バージョン | 日付 | 変更内容 |
|---|---|---|
| 1.0.0 | 2026-04-13 | 初版制定。Phase A/B/C の3フェーズ構成 |
| 2.0.0 | 2026-04-13 | Phase A完了を反映。Anthropic設計×Google APIデュアルベンダー戦略に基づきPhase B/C/Dを全面改訂。ADK SequentialAgent撤去、4層分離アーキテクチャ、Fitness Function導入 |
