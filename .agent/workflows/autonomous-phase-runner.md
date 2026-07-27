---
name: autonomous-phase-runner
description: Phase 5〜20まで自走する24時間オーケストレーションワークフロー。Flash層30並列×50タスク(1500タスク/3時間)とOpus層(週5時間/20回)を協調させ、Phase 20まで議長承認なしに自律完走する。
---

# 自律Phase完走ワークフロー v1.0

> **憲法参照**: §26（無限改善サイクル条項）
> **ロードマップ**: MASTER v4.0 Phase 5〜20（711タスク/16フェーズ）
> **起動コマンド**: `/goal Phase 20まで自律完走`

## 起動条件

以下のいずれかでこのワークフローを起動する：
- ユーザーが「Phase 20まで自走して」「自律改善サイクル開始」等と指示
- ユーザーが `/goal` コマンドでPhase完走を指示

---

## アーキテクチャ概要

```
┌─────────────────────────────────────────────────────┐
│              Orchestrator (本ワークフロー)              │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐ │
│  │Phase Gate │  │Opus Timer│  │ Flash Dispatcher  │ │
│  │  Judge    │  │ (8h周期) │  │  (30並列×50タスク) │ │
│  └────┬─────┘  └────┬─────┘  └────────┬──────────┘ │
│       │             │                  │            │
│       ▼             ▼                  ▼            │
│  ┌─────────────────────────────────────────────┐    │
│  │         Phase State (JSON)                  │    │
│  │  current_phase / gate_status / metrics      │    │
│  └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

---

## Step 0: 初期化 — 現在Phase特定 + 状態ファイル生成

### 0.1 現在Phaseの特定

```python
# VerifiedFacts (category=progress) から最新Phase完了状況を取得
from agents.memory.verified_facts import verified_facts_store
progress = verified_facts_store.get_facts(category="progress")
# MASTER v4.0 のPhaseゲート条件と照合し、現在の未完了Phaseを特定
```

### 0.2 Phase状態ファイルの生成

`backend/agents/memory/phase_state.json` を生成/更新：

```json
{
  "schema_version": "1.0",
  "current_phase": 5,
  "current_milestone": "M5.1",
  "phase_started_at": "2026-05-21T00:00:00Z",
  "flash_batches_completed": 0,
  "flash_tasks_total": 0,
  "flash_tasks_passed": 0,
  "flash_tasks_failed": 0,
  "opus_reviews_this_week": 0,
  "opus_hours_used_this_week": 0.0,
  "opus_week_start": "2026-05-19T00:00:00Z",
  "metrics": {
    "test_count": 3400,
    "coverage_pct": 80.9,
    "quality_score": 0,
    "ratchet_items": 935,
    "critical_debt": 5
  },
  "gate_checklist": {},
  "last_opus_review": null,
  "emergency_stop": false,
  "stop_reason": null
}
```

### 0.3 ベースラインスナップショット

```bash
pytest tests/ -q --tb=no 2>&1 | tail -1 > phase_baseline.txt
pytest --cov=backend --cov-branch --cov-report=json tests/ 2>&1 | tail -5 >> phase_baseline.txt
```

---

## Step 1: Flash層ディスパッチ — 30並列タスク生成

### 1.1 タスクバッチ設計

現在のPhase/Milestoneに基づき、MASTERから対象タスクカテゴリを決定する：

| Phase | 重点タスク配分 |
|:---|:---|
| 5 (卓越) | テスト追加40% / リファクタ25% / バグ修正20% / ドキュメント15% |
| 6 (本番検証) | E2Eテスト35% / 異常系テスト30% / パフォーマンス20% / 品質スコア15% |
| 7 (堅牢化) | Chaos30% / セキュリティ25% / 負荷テスト25% / リカバリ20% |
| 8-10 (運用基盤) | Docker25% / CI/CD25% / 監視25% / データ基盤25% |
| 11-13 (知能深化) | エージェント40% / 予測AI30% / 学習ループ30% |
| 14-16 (スケール) | 認証25% / API25% / プラグイン25% / マーケット25% |
| 17-20 (自律進化) | 自己改善30% / 品質昇格25% / 設計自律25% / エコシステム20% |

### 1.2 サブエージェント起動テンプレート

30個のサブエージェントを以下のグループで起動する：

```
invoke_subagent で以下の8グループ × 指定台数を並列起動:

Group 1: Bug Hunter (台数はPhase依存)
  プロンプト: "GEMINI.mdを読め。Phase {N} のバグ修正タスク。
  対象: {target_modules}。
  手順: (1) pytest実行でFAIL検出 (2) 原因特定 (3) 修正 (4) テスト追加 (5) 全テストPASS確認。
  L2判断: 3ファイル以内の変更のみ。超過時は報告して停止。
  レポート: JSON形式で phase_reports/ に出力。"

Group 2: Test Weaver (台数はPhase依存)
  プロンプト: "GEMINI.mdを読め。Phase {N} のテスト追加タスク。
  対象: カバレッジ < 70% のモジュール {low_coverage_modules}。
  手順: (1) pytest --cov で未カバー行特定 (2) テスト設計 (3) テスト実装 (4) カバレッジ改善確認。
  L1判断: プロダクションコード変更禁止。テストコードのみ。
  レポート: JSON形式で phase_reports/ に出力。"

Group 3-8: 同様のパターンで Refactor/Edge/Doc/Perf/Security/Quality
```

### 1.3 バッチ完了判定

30エージェント全完了 → Step 2へ。
10タスクごとにカバレッジ中間計測：

```bash
pytest --cov=backend --cov-branch -q tests/ 2>&1 | grep "TOTAL"
```

### 1.4 停止条件チェック（各タスク完了時）

```python
# Emergency Stop 判定
if consecutive_failures >= 3:
    phase_state["emergency_stop"] = True
    phase_state["stop_reason"] = f"3テスト連続FAIL: {failed_tests}"
    # → ユーザーに通知して停止

if coverage_delta <= -2.0:
    phase_state["emergency_stop"] = True
    phase_state["stop_reason"] = f"カバレッジ{coverage_delta}%低下"

if coverage_delta <= -0.5:
    # 減速モード: 並列数を30→10に縮小
    phase_state["throttled"] = True

### 1.5 並列競合回避ポリシー

複数サブエージェント並列実行時の競合回避のため、以下のルールを自動適用する：

1. **Workspace Mode の分離**:
   並列サブエージェント起動時は、`Workspace: share` (または `branch`) を使用し、親エージェントのワーキングツリーとの直接競合を回避する。
2. **一時ディレクトリの個別生成**:
   エージェントごとに `temp/{conversation_id}/` などの専用領域を割り当て、競合を完全に排除する。
3. **テストDBネームスペースの分離**:
   テストスイート実行時は、環境変数 `ANTIGRAVITY_AGENT_ID` をインジェクションし、接続先DBファイルを `test_db_{agent_id}.db` のように動的分離する。
4. **pytest キャッシュの競合回避**:
   並列 pytest 実行時に `.pytest_cache` が競合するのを防ぐため、`-o cache_dir=.pytest_cache_{agent_id}` オプションを付与する。
5. **ポートの動的探索**:
   開発サーバーやモックAPIのポート衝突を回避するため、空きポートを動的に探索・選択する。
6. **I/O安全（UTF-8汚染防止）**:
   PowerShellの `Add-Content` / `Set-Content` によるShift-JIS(CP932)汚染を防ぐため、ファイルの書き込みはすべて Python スクリプト経由で実行する。
```

---

## Step 2: 品質ゲート検証 — バッチ完了後

### 2.1 5段階品質ゲート実行

```bash
# Level 1: pytest全テストPASS
pytest tests/ -q --tb=short

# Level 2: カバレッジ非退行
pytest --cov=backend --cov-branch --cov-report=json tests/
# → coverage.json の totals.percent_covered_branches >= baseline

# Level 3: ラチェットテスト
pytest tests/test_fitness_functions.py -q
pytest tests/test_ux_ratchet.py -q

# Level 4: 構造化証拠レポート生成 (EBVP準拠)
# → phase_reports/batch_{N}_evidence_report.md を自動生成

# Level 5: 本番RAW E2Eテスト (日次のみ)
# → 前回実行から24時間経過している場合のみ実行
```

### 2.2 品質ゲート通過判定

```python
gate_passed = all([
    pytest_all_pass,              # Level 1
    coverage >= baseline,          # Level 2
    fitness_all_pass,             # Level 3
    evidence_report_generated,     # Level 4
])

if gate_passed:
    # → Step 3 へ (Phaseゲート判定)
    phase_state["flash_batches_completed"] += 1
    phase_state["metrics"]["test_count"] = new_test_count
    phase_state["metrics"]["coverage_pct"] = new_coverage
else:
    # → ロールバック + 再バッチ
    # 1. 失敗したファイルの特定と git stash/checkout/reset による状態復元
    # 2. ロールバックログの記録
    # 3. エラーが発生したモジュールを次回バッチの対象から除外（一時ブラックリスト化）
    git_revert_failed_changes()
    goto Step 1  # 次バッチで再挑戦
```

---

## Step 3: Phaseゲート判定 — Phase完了チェック

### 3.1 Phase別ゲート条件

`backend/agents/memory/phase_gates.json` を参照：

```python
# 現在Phaseのゲート条件を全項目チェック
gate = load_phase_gate(current_phase)
results = {}
for condition in gate["conditions"]:
    results[condition["name"]] = evaluate_condition(condition)

all_passed = all(results.values())
```

### 3.2 Phase完了 → 次Phase移行 (L3: Opus層判断)

```python
if all_passed:
    # Phase完了を記録
    verified_facts_store.add_fact(
        category="progress",
        content=f"Phase {current_phase} 完了。全ゲート条件達成。",
        evidence=json.dumps(results),
        source="autonomous_phase_runner",
        confidence=1.0,
    )
    # 次Phase開始
    phase_state["current_phase"] += 1
    phase_state["current_milestone"] = f"M{phase_state['current_phase']}.1"
    phase_state["phase_started_at"] = now_iso()
    
    # → Step 1 に戻る（次Phaseのバッチ開始）
else:
    # 未達条件に集中するバッチを生成
    weak_areas = [k for k, v in results.items() if not v]
    # → Step 1 に戻る（弱点集中バッチ）
```

---

## Step 4: Opus戦略レビュー — デュアルモデル手動切替（ワンクリック運用）

> **制約**: Antigravity 2.0ではモデル切替を自動実行できない。
> ユーザーが1日2-3回PCの前に来る際、**修正なしならワンクリックで完了**する運用を設計する。

### 4.1 運用フロー全体像

```
[Flash層自走中 — ユーザー不在でOK]
  │  Step 1-3 を自動繰返し（30並列ディスパッチ→品質ゲート→Phase判定）
  │
  ├─ 8時間経過 or Phaseゲート未達3回連続
  │
  ▼
[Flash層: Opus待機モード突入]
  │  ① opus_handoff.md を自動生成（Opusへの完全な指示プロンプト）
  │  ② phase_state.json に "awaiting_opus": true をセット
  │  ③ Flash層は低負荷モード（L1タスクのみ継続 or 待機）
  │
  ▼
[ユーザー介入 — ワンクリック運用]
  │  ユーザーがPCの前に来る
  │  ① 新規Opusチャットを開始
  │  ② 「opus_handoff.mdを読んで実行して」と入力 ← ★ワンクリック
  │  ③ Opus処理完了を待つ（~15分）
  │     Opusは opus_directive.md を生成して完了
  │  ④ Flash層チャットに戻り「続行」と入力 ← ★ワンクリック
  │
  ▼
[Flash層: 自走再開]
  │  opus_directive.md を読み込み、戦略指示に従って次バッチを生成
  │  "awaiting_opus": false に戻す
  │  Step 1 に戻る
```

### 4.2 Flash層 → Opus ハンドオフ（自動生成）

Flash層は8時間経過時に以下のファイルを **自動生成** する：

**生成先**: `backend/agents/memory/opus_handoff.md`

```markdown
# Opus戦略レビュー #{review_number} — 自動生成プロンプト

> このファイルはFlash層が自動生成したものです。
> Opusチャットで「このファイルを読んで実行して」と指示するだけでOKです。

## プロジェクト情報
- パス: c:\Users\PC_User\Desktop\script\video-automation
- GEMINI.md: プロジェクトルートの GEMINI.md を必ず読んで従うこと
- 憲法: backend/branding/PROJECT_CONSTITUTION.md §26 参照

## 現在の状態
- **Phase**: {current_phase} / Milestone: {current_milestone}
- **テスト数**: {test_count} (前回Opus: {prev_test_count}, 変動: {delta})
- **カバレッジ**: {coverage_pct}% (前回: {prev_cov}%, 変動: {delta}%)
- **完了バッチ数**: {batches} (前回Opus以降: {new_batches})
- **技術的負債(CRITICAL)**: {critical_debt}件

## Flash層レポートサマリー（前回Opus以降）
{auto_generated_summary_of_flash_reports}

## Phaseゲート進捗
| 条件 | 達成 | 現在値 | 目標値 |
|:---|:---:|:---:|:---:|
{auto_generated_gate_progress_table}

## あなたのタスク（15分以内で完了してください）
1. 上記メトリクスを分析し、弱点を特定
2. 次バッチの優先度を再設定（8グループの配分を%で指示）
3. Phaseゲート移行可否を判断
4. 以下のファイルに戦略指示を出力:
   - `backend/agents/memory/opus_directive.md` に次バッチの具体的指示を書く

## 出力テンプレート（opus_directive.md）
以下の形式で出力してください:
\```markdown
# Opus戦略指示 #{review_number}
## 優先度配分
| グループ | 配分 | 重点対象 |
|:---|:---:|:---|
| Bug Hunter | XX% | {modules} |
| Test Weaver | XX% | {modules} |
| ... | ... | ... |

## Phase判断
- [ ] Phase {N} ゲート通過 → Phase {N+1} 開始
- [x] Phase {N} 継続 → 弱点集中

## 戦略メモ
{free_text_strategy_notes}
\```

## レポート出力
- `Human01_Official Artifact/受信トレイ/strategy_review_{N}.md` にレポートを保存
- `Human01_Official Artifact` を推移表管理ルールに従って整理整頓
```

### 4.3 ユーザー介入手順（修正なしの場合）

**所要時間: Opus処理15分 + ユーザー操作2分 = 合計17分**

| Step | 操作 | 所要時間 |
|:---|:---|:---:|
| ① | 新規Opusチャットを開き、以下を入力: | 30秒 |
| | `backend/agents/memory/opus_handoff.md を読んで実行して` | |
| ② | Opusが処理完了するのを待つ | ~15分 |
| ③ | Flash層チャットに戻り、以下を入力: | 30秒 |
| | `続行` | |
| ④ | PCから離席 → Flash層が次の8時間を自走 | — |

> **修正がある場合**: Step ② の後にOpusの出力を確認し、
> 必要に応じてopus_directive.mdを手動編集してからStep ③を実行。

### 4.4 Flash層の「続行」受信時の処理

ユーザーから「続行」を受信したFlash層は以下を自動実行：

```python
# 1. opus_directive.md を読み込み
directive = read_file("backend/agents/memory/opus_directive.md")

# 2. 優先度配分を解析
priorities = parse_priorities(directive)

# 3. Phase判断を確認
if directive.phase_advance:
    phase_state["current_phase"] += 1
    phase_state["current_milestone"] = f"M{phase_state['current_phase']}.1"

# 4. 状態更新
phase_state["awaiting_opus"] = False
phase_state["last_opus_review"] = now_iso()
phase_state["opus_reviews_this_week"] += 1

# 5. 次バッチ生成 → Step 1 に戻る
generate_next_batch(priorities)
```

### 4.5 Opusバジェット管理

```
週間バジェット: 5時間 / 20回
1回あたり: 平均15分
1日あたり: 約3回（8時間間隔）

推奨スケジュール（ユーザーの生活リズムに合わせる）:
  朝: 08:00頃 — 起床時にOpusレビュー①
  昼: 16:00頃 — 夕方にOpusレビュー②
  夜: 24:00頃 — 就寝前にOpusレビュー③（オプション）

Opus枠を使い切った場合:
  → Flash層はL1/L2の自律判断のみで継続（Opus不要で進行可能）
  → 翌週月曜にOpus枠がリセットされるまで自走
```

### 4.6 Opusスキップ条件（ユーザー不在時の自動判断）

Flash層が以下の条件を満たす場合、Opus待機モードに入らず自走を継続する：

```python
skip_opus = any([
    # 全メトリクスが順調（カバレッジ上昇中 + テスト増加中 + FAIL 0）
    coverage_improving and test_count_increasing and no_failures,
    
    # 前回Opusから3バッチ未満（判断材料が少ない）
    batches_since_last_opus < 3,
    
    # 週間Opus枠を使い切り
    opus_reviews_this_week >= 20,
])

if skip_opus:
    # Opus待機せず、Flash層のみで自走継続
    continue_flash_only()

# --- Gemini 3.5 Flash によるOpus代替（自走優先） ---
# Opus待機モードに入ったが、ユーザーが不在の場合、または週間バジェット上限（20回）に達しそうな場合：
# スケジュール上のフリーズを避けるため、Opusの役割である「バッチの戦略的調整」「優先度配分」を
# Gemini 3.5 Flashへ一時的にフォールバック（代替）させて処理し、実行を止めずに次のバッチに進める。
```

---

## Step 5: 日次/週次レポート生成

### 5.1 日次レポート（自動生成、06:00 JST）

```markdown
# 日次自律改善レポート — {date}

## メトリクスサマリー
| 指標 | 昨日 | 今日 | 変動 |
|:---|:---:|:---:|:---:|
| テスト数 | {prev} | {curr} | {delta} |
| カバレッジ | {prev}% | {curr}% | {delta}% |
| Phase | {phase} | {phase} | — |
| 完了バッチ数 | {prev} | {curr} | +{delta} |
| 技術的負債(CRITICAL) | {prev} | {curr} | {delta} |

## Flash層活動
- 完了タスク: {count}
- 成功率: {rate}%
- 主な成果: {top_3_achievements}

## Opus層判断
- レビュー回数: {count}/20 (週間)
- 主な戦略変更: {changes}

## 要注意事項
- {warnings_if_any}

## 明日の重点エリア
- {focus_areas}
```

### 5.2 週次レポート（毎週日曜 自動生成）

Phase進捗サマリー、KPIトレンドグラフ（テキスト表現）、技術的負債の増減、次週計画。

---

## Step 6: ループ継続 — Phase 20完了まで

```
while current_phase <= 20 and not emergency_stop:
    
    # --- Flash層自走ゾーン（ユーザー不在OK）---
    Step 1: Flash層ディスパッチ(30並列)
    Step 2: 品質ゲート検証
    Step 3: Phaseゲート判定
    
    if 日付変更:
        Step 5: 日次レポート生成
    
    # --- Opus判断ポイント ---
    if 8時間経過 and not skip_opus_conditions:
        opus_handoff.md を自動生成
        awaiting_opus = true
        Flash層は低負荷モード（L1のみ）で継続
        # → ユーザーがOpusチャットを起動するまで待機
        # → ユーザーが「続行」と入力で再開
    else:
        # Opusスキップ → Flash層のみで自走継続
        continue
    
    # Phase 20 ゲート通過で完了
    if current_phase > 20:
        generate_final_report()
        notify_user("🎉 Phase 20完了。本番投入品質達成。")
        break

---

## 4.7 自律判断レベル (L1〜L4)

自律改善ループ中における意思決定の範囲と、安全のための制限を定義する：

- **Level 1 (完全自律 / Flash)**:
  - 範囲: テストコード追加、ドキュメント修正、テストパラメータ調整。
  - 制限: プロダクションコードの変更禁止。自動マージ（承認不要）。
- **Level 2 (条件付き自律 / Flash)**:
  - 範囲: 3ファイル以内のプロダクションコードバグ修正、リファクタリング。
  - 制限: `pytest` 全PASSおよびカバレッジ非退行が自動チェックで確認されること。
- **Level 3 (要監査 / Opus)**:
  - 範囲: 4ファイル以上の同時変更、DBスキーマ変更、共有基盤の変更。
  - 制限: Opusによる設計妥当性レビューおよび `sprint_design.md` の作成・合意が必須。
- **Level 4 (要決裁 / 人間)**:
  - 範囲: 憲法（PROJECT_CONSTITUTION.md）の変更、Verified Factsの手動変更。
  - 制限: ユーザーによるチャット上の明示的な承認が必須。
```

---

## Emergency Stop Protocol

### 即時停止条件と自動回避
- **FAIL監視時の自動回避**:
  - 単一エージェントで3テスト連続FAILした際、即座に停止するのではなく、まず失敗原因となったソースコード変更を自動でロールバック（`git stash` / `git reset --hard HEAD~1`）し、そのモジュールを次回バッチ対象から除外（一時ブラックリスト化）した上で、他の健全なモジュールの改善タスクで自律実行を「止めずに」継続する。
- **停止条件（自動回避不能な場合のみ）**:
  - 全タスクがブラックリスト化され、実行可能な健全モジュールがない場合
  - カバレッジが2%以上低下し、かつロールバックでも回復しない場合
  - テストの総数が減少した場合
  - 5タスク連続で自動回避・復旧不能なエラーとしてOpusへエスカレーションが発生した場合
  - テストがハングし、`pytest.ini` の `timeout`（60秒）で強制終了されても復旧できない場合

### 停止時の処理
1. `phase_state.json` に停止理由を記録
2. 進行中のFlashエージェントに停止指示（タスクkill）
3. 停止直前のgit状態をタグ付け保存 (`git tag -a emergency_stop_{timestamp}`)
4. 失敗コミットを `git reset --hard` または `git revert` により自動ロールバック
5. 停止レポートを `Human01_Official Artifact/受信トレイ/` に出力
6. ユーザーに通知（次回チャット開始時に自動表示）

### 復旧手順
1. ユーザーが停止原因を確認
2. 修正指示 or 「再開して」で続行
3. phase_state.json の emergency_stop を false に戻す
4. Step 1 から再開

---

## 試算: Phase 20までの所要時間

### Flash層スループット
- 1バッチ: 30並列 × 50タスク = 1,500タスク / 3時間
- 1日: 8バッチ = 12,000タスク（理論上限）
- 実効（品質ゲート・再試行込み）: 1日6バッチ = 9,000タスク

### Opus層キャパシティ
- 週20回 × 15分 = 5時間/週
- 1日3回のPhaseゲート判定 + 戦略調整

### Phase別推定

| Phase | タスク数 | Flash推定 | Opus回数 | 推定所要 |
|:---|:---:|:---|:---:|:---|
| 5 (卓越) | 56 | 1バッチ以内 | 1回 | 3-4時間 |
| 6 (本番検証) | 50 | 1バッチ以内 | 1回 | 3-4時間 |
| 7 (堅牢化) | 50 | 1バッチ以内 | 1回 | 6-8時間 |
| 8-10 (運用基盤) | 150 | 1バッチ以内 | 3回 | 1-2日 |
| 11-13 (知能深化) | 145 | 1バッチ以内 | 3回 | 2-3日 |
| 14-16 (スケール) | 130 | 1バッチ以内 | 3回 | 2-3日 |
| 17-19 (自律進化) | 95 | 1バッチ以内 | 2回 | 1-2日 |
| 20 (エコシステム) | 35 | 1バッチ以内 | 1回 | 1日 |
| **合計** | **711** | **1バッチで全完了可能** | **15回** | **約1-2週間** |

> **注**: 711タスクは1バッチ(1,500タスク)の半分以下。
> 純粋なFlash実行時間は1.5時間。
> ボトルネックはOpus層の週20回制限と品質ゲート検証時間。
> Opus15回 × 8時間間隔 = 5日がOpus律速の最短完了。
> 品質ゲート検証・再試行を含めると実効1-2週間。

---

## 改定履歴

| バージョン | 日付 | 変更内容 |
|:---|:---|:---|
| 1.0.0 | 2026-05-20 | 初版。Flash30並列+Opus8h周期。Phase 5-20自走。停止条件。試算。 |
| **1.1.0** | **2026-05-20** | **Step 4全面改定: ワンクリック・ハンドオフ方式導入。opus_handoff.md自動生成、Opusスキップ条件、「続行」コマンドで再開。ユーザー介入=ワンクリック×2回** |
| **1.2.0** | **2026-05-21** | **共通処理機構（OrchestrationHub）導入。タスクキュー・メッセージボックス・指示管理をPython API化。Flash用自走エントリ `flash-autonomous-entry.md` 新設。プロジェクト2/3のファイルベース自律連携を実現。** |

