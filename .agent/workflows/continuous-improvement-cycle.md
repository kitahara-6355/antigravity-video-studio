---
description: 継続的改善サイクル v2.1 — 推奨タスク実行→FV/E2E検証→設計妥当性レビュー→レポート→VerifiedFacts反映→次期計画策定を1サイクルとして反復実行するワークフロー。フェーズ完了プロトコルと連携。
---

# 継続的改善サイクル (Continuous Improvement Cycle)

// turbo-all

## 設計思想

> **止まらない**: API枠・時間に関係なく、常に前進する。
> **サステナブル**: ステージ追加でも10分を維持。
> **品質不退転**: UXストーリーを下回らない（§7.3）。
> **検証駆動**: 毎サイクルで自動編集機能を1つ以上検証。

---

## 実行フロー

```
Step 1: バックログからタスク選定（3トラック制）
    ↓
Step 2: 実装 + Fitness テスト
    ↓
Step 3: フィーチャー検証（FV: 自動編集機能の実用品質確認）
    ↓
Step 3.5: UXストーリーE2E検証（実装完了した機能のUIUX確認）
    ↓
Step 4: 自己改善ループ（速度+品質のゲート判定）
    ↓
Step 4.5: 設計妥当性レビュー（初期設計の妥当性+見直し必要性判定）
    ↓
Step 5: バックログ更新 + レポート → Human01 保存
    ↓
Step 5.5: 開発学習のVerifiedFacts反映（パイプライン↔開発の橋渡し）
    ↓
Step 6: 報告 → 指示待ち
```

---

## Step 1: バックログからタスク選定

**参照**: `Human01_Official Artifact/20260415_改善バックログ.md`

### 3トラック制

| トラック | 条件 | 最低消化数 |
|---|---|---|
| ☁️ A: API依存 | API枠あり | 1タスク |
| 🖥️ L: ローカル | 常時実行可能 | 1タスク |
| 🔍 F: フィーチャー検証 | 常時実行可能 | **1タスク（必須）** |

**選定ルール**:
1. API枠確認 → 枠あり: A+L+F / 枠なし: L+F
2. 各トラックから **優先度🔴→🟡→🟢** の順に選定
3. 合計 **2〜3タスク** を1サイクルで消化

---

## Step 2: 実装 + Fitness テスト

タスク実装後:

```powershell
cd backend; python -m pytest tests/test_fitness_functions.py -q --tb=line
```

FAIL → 修正。PASS → Step 3 へ。

> **v2.0**: Step 3ではFV(機能実効性検証)を実行する。FVの詳細は `/qa-audit` §2 を参照。

---

## Step 3: フィーチャー検証（自動編集機能の品質）

**毎サイクル最低1つの自動編集機能を検証する。**

### 検証方法

| 機能 | API不要な検証 | API必要な検証 |
|---|---|---|
| 文字起こし | GPU速度、セグメント数 | — |
| AI校閲 | — | 修正件数、誤修正率 |
| SmartCut | カット率、目標尺乖離 | — |
| プレビュー | ファイルサイズ、字幕有無 | — |
| YouTube | — | タイトル案数、タグ数 |
| 品質チェック | ルールベーススコア | AIスコア |
| 最終レンダ | 画質(VMAF)、ラウドネス | — |
| 話者分離 | 対談動画で話者数検出 | — |
| テーマ適用 | 字幕スタイル確認 | — |
| ラウドネス | FFmpeg loudnorm で-16 LUFS確認 | — |
| Shorts量産 | 縦型変換、60秒制限 | — |

### 検証テンプレート

```python
# フィーチャー検証スクリプト
def verify_feature_XX():
    """F-XX: [機能名] の検証"""
    # 1. 入力条件
    # 2. 実行
    # 3. 出力確認
    # 4. 品質基準チェック
    assert result >= threshold, f"品質基準未達: {result} < {threshold}"
```

---

## Step 4: 自己改善ループ

### テスト方法の選択

| API枠 | テスト方法 |
|---|---|
| ✅ あり | E2Eテスト（本番RAW4動画） |
| ❌ なし | 単体テスト + ベンチマーク + フィーチャー検証 |

### 品質ゲート

| 指標 | 最低基準 |
|---|---|
| 品質スコア | ≥ ベースライン |
| Fitness | 23/23 PASS |
| フィーチャー検証 | 今回対象の機能がPASS |

---

## Step 3.5: UXストーリーE2E検証 — v2.0新設

**実装が完了した自動編集機能について、UXストーリー駆動のブラウザE2E検証を実行する。**

### 実行条件
- Worker実装が完了し、FV(Step 3)がPASSした場合のみ実行
- 対象機能に関連するUIコンポーネントが存在する場合のみ実行

### 実行手順
1. 当該機能に関連するUXストーリー(§7.3 O-1〜O-12)を確認
2. UXストーリーが最新の実装を反映しているか検証 → 未反映なら更新
3. UXストーリーからE2Eゴールを導出
4. Browser Agentでゴールシートに沿ってUI操作+検証
5. 結果をUXストーリー充足マトリクスに記録

> 詳細手順は `/qa-audit` §3 を参照。

### 完了判定
- 全UXストーリーの全E2EゴールがPASS = 機能完成
- FAILあり → 修正 → 再検証（UXストーリー全充足まで繰り返す）

---

## Step 5: バックログ更新 + レポート

1. 完了タスクにチェック ✅
2. 新規発見した問題をバックログに追加
3. フィーチャー検証結果を更新
4. レポートを `Human01_Official Artifact/` に保存
5. **ビジョン乖離度バックログ同期**: `backend/branding/vision_backlog.json` を更新
   - 解消した D-XX 項目を `resolved` に移動
   - 新規発見の乖離を `backlog` に追加
   - `axis_scores` の該当軸スコアを更新

---

## Step 5.5: 開発学習のVerifiedFacts反映 — v2.1新設

**今サイクルで得た開発知見をVerifiedFactsStoreに蓄積し、DreamEngineのGatherソースを開発セッションに拡張する。**

### 目的
パイプラインエージェント層(DreamEngine/VerifiedFacts)と開発エージェント層(.agent/)の間の「橋渡し」として、開発セッションで得た知見をパイプライン側のメモリに永続化する。

### 反映対象

| カテゴリ | 反映内容 | 例 |
|:---|:---|:---|
| `architecture` | 今サイクルで発見/確定した設計パターン | 「HookSystemは7イベントで完全」 |
| `lesson` | テスト失敗から得た教訓 | 「DiskGuardはread_onlyツールをスキップすべき」 |
| `preference` | ユーザーの好み・判断 | 「設定JSONは分散管理が正しい」 |
| `specification` | 確定した仕様変更 | 「GEMINI.mdは23行以下を維持」 |

### 実行手順

1. 今サイクルで確定した知見をリストアップ(最大5件)
2. 各知見をカテゴリ分類
3. 以下のコードで VerifiedFacts に追加:

```python
from agents.memory.verified_facts import verified_facts_store
verified_facts_store.add_fact(
    category="lesson",     # architecture / lesson / preference / specification
    content="今回の学習内容",
    evidence="根拠となるテスト結果やログ",
    source="development_session",
    confidence=0.8,
)
```

4. 追加後、VerifiedFacts統計を確認:

```python
print(verified_facts_store.get_stats())
# markdown_lines <= 200, markdown_size_kb <= 25 を確認
```

### スキップ条件
- 今サイクルで新たな知見がない場合はスキップ可
- 既存ファクトと重複する場合は自動スキップ(VerifiedFactsStore内蔵)

---

## Step 6: 完了報告 + VerifiedFacts進捗記録

### モード別の報告形式

| モード | 報告形式 | 参照 |
|:---|:---|:---|
| 🟢 実装 (Sonnet) | ✅完了レポート or 🆘ヘルプレポート | `.agent/workflows/briefing-protocol.md` |
| 🔴 設計 (Opus) | 設計結果をTKTに記録 + VFに反映 | 同上 |

### VF進捗記録 (必須)

完了時に以下を必ず実行:

```python
# category="progress", confidence=1.0 で証拠付き事実を記録
verified_facts_store.add_fact(
    category="progress",
    content="[Worker] [Cカテゴリ]: X/X PASS, branch cov XX%",
    evidence="pytest [テストファイル] → X passed, 0 failed",
    source="development_session",
    confidence=1.0,
)
```

> [!IMPORTANT]
> **計画・予定・状態は記録しない。事実のみ。**
> 次チャットは MASTER v3.6 + VF(progress) から現在地を導出する。

---

## コンテキスト効率化ルール — v2.2改訂

### 2モード制タスクチャット運用

| モード | 開始時 | 実行中 | 完了時 |
|:---|:---|:---|:---|
| 🔴 設計 (Opus) | フルブリーフィング(12項目) | ユーザーと対話 | 設計結果をVF+TKTに記録 |
| 🟢 実装 (Sonnet) | 最小指示のみ | **サイレント実行** | 完了/ヘルプレポート |

### チャット粒度ガイドライン

| タスク規模 | チャット数 | 理由 |
|:---|:---:|:---|
| テスト3-5件 | 1チャット | Sonnetのスイートスポット |
| テスト6-8件 | 2チャットに分割 | コンテキスト圧迫回避 |
| テスト9件以上 | 3チャット以上 | QualityGate(181テスト)等 |
| 設計タスク | 1チャット(設計のみ) | 設計結果をTKTに記録 |
| FV検証 | 1チャット | 検証と判定のみ |

### 状態管理原則

| 原則 | 内容 |
|:---|:---|
| **事実のみ記録** | VF(progress)には「pytest X passed」等の検証可能な事実のみ |
| **計画は保存しない** | MASTER v3.6が唯一の計画書。別所に複製しない |
| **導出で現在地を知る** | MASTER(計画) - VF(事実) = 未完了リストの先頭 |
| **実状確認** | チャット開始時にpytest実行でVFと現実を突合 |
| **チャット使い捨て** | 1チャット=1タスク。設計と実装は別チャット |

### ブリーフィングプロトコル

詳細は `.agent/workflows/briefing-protocol.md` を参照。

---

## 連携ワークフロー

| ワークフロー | 関係 | 発動条件 |
|---|---|---|
| `/qa-audit` | **FV検証+UXストーリーE2E** | Worker実装完了時(必須) |
| `/vision-gap-audit` | **ビジョン乖離度の厳格計測** | 工数大タスク完了後 / 四半期 / 手動 |
| `/phase-completion-protocol` | フェーズ完了の品質ゲート+設計レビュー | Phase完了時 |
| `/harness-audit` | ハーネス・パイプライン基盤監査+実効性検証 | 四半期 / 手動 |

> **運用**: 通常は `/continuous-improvement-cycle` で改善を積み上げ、
> Worker完了時に `/qa-audit` でFV+E2E検証を実行し、
> 節目で `/vision-gap-audit` を実行してビジョン実現度を厳格に再計測する。

---

## 改定履歴

| バージョン | 日付 | 変更内容 |
|:---|:---|:---|
| 1.0.0 | 2026-04-13 | 初版。3トラック制+フィーチャー検証+ビジョン同期 |
| 2.0.0 | 2026-04-19 | Step 3.5(UXストーリーE2E検証)+Step 4.5(設計妥当性レビュー)新設。FVの参照を/qa-auditに統一。連携ワークフローにqa-audit追加 |
| **2.1.0** | **2026-04-19** | **Step 5.5(開発学習のVerifiedFacts反映)新設。コンテキスト効率化ルール追加。パイプライン↔開発エージェントの橋渡し強化** |
| **2.2.0** | **2026-04-19** | **2モード制(設計/実装)ブリーフィング導入。VF導出型状態管理(current_task.json不要)。チャット粒度ガイドライン。完了/ヘルプレポートテンプレート。briefing-protocol.md新設** |

