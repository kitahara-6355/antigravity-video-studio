---
name: flash-session-archive
description: Flashセッションのアーカイブタイミング判定と手順。COMPLETE/WARN判定時にOpusから参照される。
---

# Flashセッション アーカイブガイド

> 作成: 2026-05-26
> 対象: Opus統括セッション

---

## 1. アーカイブとは

Flashセッションの「アーカイブ」とは、現在のセッションを正式に終了し、成果を記録した上で新規セッションを開設する一連の手順です。

---

## 2. アーカイブタイミングの判定基準

### 自動判定（`health_check.py` + `orchestrator.py` による）

| 判定 | 条件 | アクション |
|:---:|:---|:---|
| 🏁 **COMPLETE** | `flash_session.json` の `status == "stopped"` かつ完了タスク≧1 | **即アーカイブ推奨** |
| ⏳ **FINISHING** | `status == "running"` かつ pending=0, running=0 | 完遂プロトコル実行を待機→COMPLETE後にアーカイブ |
| ⚠️ **WARN** | `archive_urgency == "warn"` — コンテキスト予測が `context_target_pct`（70%）超過見込み、またはハードキャップ（バッチ数/時間）到達 | **アーカイブ検討** |
| ℹ️ **INFO** | `archive_urgency == "info"` — コンテキスト予測が `context_warn_pct`（60%）超過見込み | 情報提供のみ、継続可能 |
| 🔴 **UNHEALTHY** | 心拍30分超過で自動停止 | **強制アーカイブ+新規開設** |

> **アダプティブ判定（2026-06-04 導入）**: 従来の固定タスク数閾値（80/100/120タスク）は廃止。
> コンテキスト消費率の移動平均予測（3層構成）により、タスク複雑度に自動追従する。
> 詳細は GEMINI.md「アダプティブ・アーカイブ判定規約」を参照。

### 手動判定（Opus/ユーザーによる）

以下の条件のいずれかに該当する場合、Opusまたはユーザーの判断でアーカイブを実施する：

- **コンテキスト圧縮が頻発** — チェックポイントが多発し、ワークフロー再読み込みが増加
- **エラー率が上昇** — 連続エラーが3回以上発生
- **Phase完了** — 現在のPhaseの全タスクが完了
- **ユーザー指示** — 「Flash新規開設」等の直接指示

---

## 3. アーカイブ手順

### Step 1: 完遂プロトコルの確認

Flash側で完遂プロトコル（`flash-autonomous-entry.md` §6）が実行済みか確認：
- [ ] `hub.flash_session_end()` が呼ばれた
- [ ] 完了宣言がチャットUIに表示された
- [ ] 受信トレイに最終レポートが保存された

> Flash側で完遂プロトコルが実行されない場合（クラッシュ/トークン制限）は、
> `health_check.py` の自動停止機構が `flash_session.json` を `stopped` にするため、
> Step 2 に進んでよい。

### Step 2: 成果の記録確認

以下が自動保存されていることを確認（通常は自動で済んでいる）：

| 成果物 | 保存先 | 確認方法 |
|:---|:---|:---|
| バッチ完了報告 | `flash_reports.jsonl` | 最終バッチのエントリがある |
| Gitコミット | ローカルリポジトリ | `git log -5 --oneline` で `[Flash/...]` コミットがある |
| セッション統計 | `flash_session.json` | `tasks_completed_in_session` が正値 |

### Step 3: 新規セッション開設

**復旧ガイドの Step 3 と同一手順**（→ [recovery-from-token-limit.md](recovery-from-token-limit.md) §2 Step 3 参照）

1. `health_check.py` の自動出力プロンプトを使用（推奨）
2. または `generate_flash_prompt.py` を手動実行
3. 出力されたプロンプトを同一プロジェクト内の新規チャットに貼り付け

---

## 4. アーカイブ後の確認

新規Flashセッション開設後、Opusの次回Cronヘルスチェック（5分以内）で以下を確認：

- [ ] Flash心拍が更新されている
- [ ] セッション内タスク完了数が増加し始めている
- [ ] 判定が 🟢 HEALTHY に遷移している
- [ ] ダッシュボードの「セッション内」カウンタがリセットされている

---

## 5. サジェスト自動化

`health_check.py` の `assess_flash_lifecycle()` が以下のタイミングで自動サジェストを出力：

| 判定 | サジェスト内容 |
|:---|:---|
| COMPLETE | 「アーカイブ可能 → 新規Flashセッション開設を推奨」 |
| WARN (ctx予測超過) | 「コンテキスト予測がtarget超過見込み。状況に応じてアーカイブ検討」 |
| UNHEALTHY | 復旧用プロンプトを自動出力（`generate_flash_prompt.py` 経由） |

これらはダッシュボードの「📋 ユーザー向けアクション提案」セクションにも反映される。
