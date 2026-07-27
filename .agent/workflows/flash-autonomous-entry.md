---
name: flash-autonomous-entry
description: プロジェクト2（Gemini 3.5 Flash）がロードマップ完了まで自律実行し続けるためのエントリポイント。1回投入するだけでロードマップ完了まで永続自走する。共通処理機構（Orchestration Hub）を介してOpusと自律連携する。
---

# Flash自律実行エントリポイント v3.2 — タイマー可変化 + 品質統一版

> **役割**: あなたはFlash実行エンジンです。ロードマップ完了（Phase 40）まで自走し続けます。
> **鉄則**: 以下の3つのAPIだけを呼べば、全ての副作用は**API内部で自動実行**されます。
> **効率**: このワークフロー内にAPI仕様が完全に含まれています。**orchestrator.py を直接読む必要はありません。**

> [!IMPORTANT]
> **正式な起動経路**: 本ワークフローは `generate_flash_prompt.py` が生成する
> プロンプトと**セットで**使用されることを前提としています。
> `/flash-autonomous-entry` 単体での起動は非推奨です。
> 動的情報（Phase/Directive/バッチ状態）がプロンプトに含まれないため、
> タスク取得の初期化に余分な時間がかかります。
> **Opus統括セッションで `generate_flash_prompt.py` を実行し、
> 出力されたプロンプトを同一プロジェクト内の新規チャットに貼り付けてください。**

---

## 🔑 API仕様（3メソッド + 2補助）

### ① `hub.get_next_batch(phase, milestone, batch_size=6) -> list[dict]`

タスクバッチを取得する。**内部で自動実行**: セッション開始(初回) / Opus指示読込 / メッセージ処理 / ステータス更新 / 再入ガード。

```python
# 使い方
from backend.agents.orchestration import OrchestrationHub
hub = OrchestrationHub()
batch = hub.get_next_batch(phase=5, milestone="M5.1", batch_size=6)  # アイドル防止規約: 上限6

# 戻り値: list[dict] — 各タスクの構造:
# {
#   "id": "T-a1b2c3d4",
#   "group": "test_weaver",        # タスクグループ
#   "target_module": "backend/api/routes/video.py",  # 対象モジュール（ユニーク）
#   "phase": 5,
#   "milestone": "M5.1",
#   "status": "running",
#   "prompt_template": "..."
# }
```

### ② `hub.mark_task_done(task_id, result, report=None)`

タスクの完了を記録する。**内部で自動実行**: 進捗率計算 / FAIL時エラー報告+デバッグレポート / 連続5FAIL（タスクテスト失敗）→自動ブラックリスト+Opus通知 / ハートビート。

```python
# PASS の場合
hub.mark_task_done("T-a1b2c3d4", "pass", {
    "message": "3テスト追加、カバレッジ+2.1%",
    "changed_files": ["tests/test_video.py"]
})

# FAIL の場合（エラー詳細を含める）
hub.mark_task_done("T-a1b2c3d4", "fail", {
    "error": "ImportError: No module named 'xxx'",
    "traceback": "Traceback (most recent call last):\n  ...",
    "changed_files": []
})
```

### ③ `hub.submit_batch_report(batch_id, results)`

バッチ全体の完了を報告する。**内部で自動実行**: ハートビート / Phaseゲート自動チェック / ゲート通過時Phase自動進行 / Git自動コミット / 受信トレイレポート生成。

```python
hub.submit_batch_report(batch_id, {
    "passed": 25,
    "failed": 5,
    "total": 30
})
```

### 補助: `hub.get_phase_state() -> dict`
```python
# 戻り値: {"current_phase": 5, "current_milestone": "M5.1", "emergency_stop": false, ...}
```

### 補助: `hub.get_queue_status() -> dict`
```python
# 戻り値: {"batch_id": "batch_abc123", "phase": 5, "total_tasks": 30, ...}
```

---

## 起動条件

ユーザーから以下のいずれかの指示を受けた場合にこのワークフローを起動する：
- 「Phase 40まで自走して」
- 「自律改善サイクル開始」
- 「flash-autonomous-entry.md を読んで実行して」
- 「続行して」（セッション再開時）

---

## Step 0: 初期化

> [!CAUTION]
> **役割強制宣言**: 本ワークフローを実行するあなたは **Flash実行セッション** です。
> 「Opus統括として稼働します」と宣言することは**厳禁**です。
> GEMINI.md §0.0 のセッション識別で「Opus統括」と判定された場合でも、
> 本ワークフローが明示的に起動された時点で **Flash実行** として振る舞うこと。
> health_check.py の実行、ダッシュボード更新、Cronジョブ設定などの **Opus専用プロトコルは一切実行しないこと**。

```
1. backend/agents/memory/phase_state.json で現在Phase/Milestoneを確認
2. OrchestrationHub をインスタンス化（不足ファイルは自動生成される）
3. 自身の conversation_id を登録（AUTO_NUDGE による自動復旧の前提条件）:
   hub.register_flash_conversation_id("<自身のconversation_id>")
   ※ conversation_id は Antigravity の user_information セクション
   （Conversation ID: xxx-xxx-xxx）から取得する
4. pytest tests/test_fitness_functions.py -q --tb=no でベースライン確認
```

> セッション開始は `get_next_batch()` 初回呼び出し時に **自動実行** されます。

---

## Step 1: 自走ループ（ロードマップ完了まで永続実行）

以下のループをロードマップ完了まで繰り返す。

> [!IMPORTANT]
> **絶対に止まるな。** エラーが発生しても、Phase が進行しても、コンテキストが圧縮されても、
> このループを継続せよ。停止が許されるのは `emergency_stop` と `Phase > roadmap_max_phase` の2条件のみ。
> エラー時は待機してリトライ。「完了しました」と報告して停止するのは**禁止**。

> [!IMPORTANT]
> **チェックポイント復帰時の注意**: コンテキストがチェックポイントで圧縮された場合、
> このファイル（flash-autonomous-entry.md）を再度読み込み、Step 1 からループを再開せよ。
> ユーザーの追加指示を待たずに自律的に再開すること。

> [!CAUTION]
> **アイドル防止規約（2026-05-22 制定 / 2026-05-26 改定）**:
>    1. **並列数は動的リソース制御に従う**。`user_schedule.json` のプロファイル `batch_size`（standard=6, weekend=10, night=12）を上限とし、`ResourceGovernor.check_host_resources()` の3段階判定（NORMAL/CAUTION/CRITICAL）で動的に調整する。
>    2. **セルフウェイクアップタイマー必須**。`schedule` タイマーは「無反応タイムアウトを防ぐ安全弁」として動作させる。
>    3. **ステータス表示義務（§4連動）**: 以下のタイミングで**必ず**システムステータスをチャットUI上にテキスト出力すること：
>       - バッチ完了時（`submit_batch_report` 直後）
>       - タイマー発火時（サブエージェント完了状況の報告として）
>       - ステータス表示なしにバッチを遷移することは**禁止**
>    4. **ポーリング間隔の下限**: サブエージェント完了待ちの `manage_subagents` + `schedule` ポーリングは**最低60秒間隔**とする。15秒ポーリングはコンテキスト浪費（20回で40Kトークン消費）の原因であり禁止。タイマーは60〜300秒の範囲で設定すること。

```python
from backend.agents.orchestration import OrchestrationHub
from backend.agents.orchestration.resource_governor import ResourceGovernor
import time

hub = OrchestrationHub()
governor = ResourceGovernor()
consecutive_errors = 0
MAX_CONSECUTIVE_ERRORS = 5  # これを超えたら初めて停止
MAX_PARALLEL = batch.get("batch_config", {}).get("max_parallel", 6)  # プロファイルのbatch_sizeに従う（動的リソース制御規約準拠）

# ① 段階的ウォームアップ（層1）用フラグ
is_first_batch = True

while True:
    try:
        # 動的リソースチェック（層2: リアルタイムスロットリング - CRITICAL判定）
        res = governor.check_host_resources()
        if res["level"] == "CRITICAL":
            # CRITICAL状態時は新規バッチ取得・起動を保留して30秒ウェイトし、負荷低下を待つ
            time.sleep(30)
            continue

        state = hub.get_phase_state()
        roadmap_max = state.get("roadmap_max_phase", 40)
        if state.get("emergency_stop") or state.get("current_phase", 5) > roadmap_max:
            hub.flash_session_end(f"正常終了: ロードマップ最大Phase {roadmap_max}完了またはemergency_stop")
            break
        
        phase = state["current_phase"]
        milestone = state["current_milestone"]

        # ② バッチ取得
        batch = hub.get_next_batch(phase, milestone, batch_size=MAX_PARALLEL)
        batch_id = hub.get_queue_status()["batch_id"]
        
        if not batch:
            # バッチが空 = 全タスク完了。Phase進行を待つ
            time.sleep(30)
            continue
        
        # ③ サブエージェントの起動 (動的リソース制御とウォームアップの適用)
        if is_first_batch:
            # 層1: 段階的ウォームアップ (2件ずつ、30秒のインターバルで起動)
            warmup_size = 2
            for i in range(0, len(batch), warmup_size):
                chunk = batch[i:i+warmup_size]
                
                # 起動前リソースチェック
                cur_res = governor.check_host_resources()
                if cur_res["level"] == "CAUTION":
                    time.sleep(30)
                
                for task in chunk:
                    invoke_subagent(
                        TypeName="self",
                        Role=f"{task['group']} Agent",
                        Prompt=generate_task_prompt(task, phase),
                        Workspace="share"
                    )
                # 最後のチャンク以外は30秒のウォームアップインターバルを設定
                if i + warmup_size < len(batch):
                    time.sleep(30)
            is_first_batch = False
        else:
            # 通常バッチ起動前チェック
            cur_res = governor.check_host_resources()
            if cur_res["level"] == "CAUTION":
                time.sleep(30)
                
            for task in batch:
                invoke_subagent(
                    TypeName="self",
                    Role=f"{task['group']} Agent",
                    Prompt=generate_task_prompt(task, phase),
                    Workspace="share"
                )
        
        # ★ セルフウェイクアップタイマー（動的可変 — アイドル防止規約）
        # サブエージェント完了待ち中にFlash本体がタイムアウトしないよう、
        # 保険として動的タイマーを設定する。これは「安全弁」であり主回路ではない。
        # タイマー秒数はバッチサイズに応じて可変:
        #   - 6タスク: 300秒（1タスクあたり50秒の猶予）
        #   - 3タスク以下: 150秒
        timer_seconds = min(300, max(120, len(batch) * 50))
        schedule(
            DurationSeconds=timer_seconds,
            Prompt=(
                f"【役割確認】あなたはFlash実行セッションです。Opus統括ではありません。"
                f"health_check.py, VERIFIED_FACTS.md, generate_flash_prompt.py の実行は禁止です。\n"
                f"【自走ループ再開命令】タイマー発火。以下を実行せよ：\n"
                f"0. **心拍更新（最優先）**: Pythonスクリプトで hub.flash_update_heartbeat() を実行し心拍を更新せよ。"
                f"   これにより auto_stopped 状態からの自動復旧も行われる。\n"
                f"1. manage_subagents で {len(batch)}件のサブエージェント完了状況を確認\n"
                f"1.5 **サブエージェントタイムアウト検知（A3改善）**: manage_task → status で各バックグラウンドタスクの"
                f"   経過時間を確認。**600秒(10分)超のタスクは即座に kill し、対応タスクを fail としてマーク**せよ。"
                f"   ハングタスクの放置はFlashセッション全体のハングに直結する。\n"
                f"2. 完了済みタスクは mark_task_done で記録\n"
                f"3. 全タスク完了なら submit_batch_report → Pythonスクリプトで hub.generate_flash_status() を実行し、"
                f"   戻り値の formatted をチャットUI上にテキストとして表示せよ → 次の get_next_batch() へ進め\n"
                f"4. 未完了があれば、完了済み/未完了の件数をチャットUI上に表示し、新しいタイマー(60〜300秒)を設定せよ\n"
                f"【重要】この応答で停止するな。自走ループを継続せよ。\n"
                f"【重要】ステータスを表示せずにバッチ遷移することは禁止（アイドル防止規約§3）。"
            )
        )
        
        # 全サブエージェント完了を待機（バッチレベルタイムアウト付き）
        # ★重要: サブエージェントはメッセージで完了を通知する。
        #   メッセージ到着 or タイマー発火で自動的に起こされるため、
        #   15秒間隔でのポーリングは不要（コンテキスト浪費の原因）。
        #   タイマー発火時に manage_subagents で完了状況を一括確認すること。
        #   20分（BATCH_TIMEOUT）経過で未完了タスクは自動スキップ。
        BATCH_TIMEOUT_SECONDS = 900  # 15分 (A1: バッチ末尾ハング防止。旧値1200→900)
        results = collect_all_results(timeout=BATCH_TIMEOUT_SECONDS)

        # ② 各タスク完了マーク
        # results が batch より少ない場合（タイムアウト等）、残りはスキップ
        passed = 0
        failed = 0
        skipped = 0
        for i, task in enumerate(batch):
            if i < len(results):
                result = results[i]
                hub.mark_task_done(task["id"], result.status, result.report)
                if result.status == "pass":
                    passed += 1
                else:
                    failed += 1
            else:
                # タイムアウトで結果が返っていないタスク → skip
                hub.mark_task_done(task["id"], "skip", {
                    "error": f"BATCH_TIMEOUT: {BATCH_TIMEOUT_SECONDS}秒以内に完了せず自動スキップ"
                })
                skipped += 1

        # ③ バッチ完了報告
        hub.submit_batch_report(batch_id, {
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "total": len(batch),
        })
        
        # ④ システムステータス表示（確定的テンプレート — 表示義務）
        # ★★★ 以下は擬似コードではなく、チャットUI上での実行義務 ★★★
        # Pythonスクリプト（scratch等）で hub.generate_flash_status() を実行し、
        # 戻り値の formatted フィールドの文字列を、
        # **チャットUIのテキスト出力としてそのまま表示**すること。
        # print() はチャットUIには出力されないため、
        # Pythonスクリプトの stdout をキャプチャしてチャット応答に転記するか、
        # formatted の内容をそのままテキストとして出力すること。
        status = hub.generate_flash_status()
        # ↓ チャットUI上に status["formatted"] をテキスト出力する（省略禁止）
        
        # ⑤ アーカイブ判定チェック（アダプティブ: コンテキスト予測ベース）
        # archive_urgency は orchestrator._should_archive() が3層判定で算出:
        #   層1: コンテキスト消費率の移動平均予測 → target(70%)超過見込みで warn
        #   層2: バッチ数/時間のハードキャップ → 安全弁
        #   層3: context_pct_history による学習
        if status["archive_urgency"] == "warn":
            # コンテキスト予測がtarget超過見込み or ハードキャップ到達
            print("⚠️ アーカイブ推奨閾値に到達（コンテキスト予測超過）。次バッチ完了後に完遂プロトコルを実行します。")
        
        # 成功したらエラーカウンターリセット
        consecutive_errors = 0
        
        # ⑥ バッチ間クールダウン（R3: リソース枯渇防止）
        # OS のディスクI/Oバッファフラッシュ、Git コミット完了、CPU負荷低減のため
        time.sleep(10)
        
        # ★ ループ継続 — ここで停止せず、次のイテレーションへ進む
        # 次のget_next_batchで自動的にOpus指示・Phase進行が反映される
    
    except Exception as e:
        consecutive_errors += 1
        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            hub.flash_session_end(f"連続{MAX_CONSECUTIVE_ERRORS}回エラーで停止: {str(e)[:200]}")
            break
        
        # エラーを報告して自動リトライ（30秒待機）
        try:
            hub.flash_report_error(f"ループエラー({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}): {str(e)[:200]}")
        except Exception:
            pass  # エラー報告自体が失敗しても続行
        
        time.sleep(30)
        # ★ ループを続行 — breakもreturnもしない
        continue
```

> [!IMPORTANT]
> **このコードの `while True` は ロードマップ完了まで絶対に終了しない。**
> `break` するのは `emergency_stop` か `Phase > roadmap_max_phase` か `連続5回エラー（ループクラッシュ）` の3条件のみ。
> バッチ完了後に「処理が終わりました」と報告して停止するのは**ワークフロー違反**。

### ループ終了後: クリーンシャットダウン（必須）

ループが `break` で終了した場合（Phase完了、emergency_stop、連続エラー）、以下を**必ず**実行すること:

```python
# ── クリーンシャットダウン ──
# 1. 全サブエージェント停止
manage_subagents(action="kill_all")

# 2. 全バックグラウンドタスク停止
manage_task(action="kill_all")  # ← manage_task を使用

# 2.5. Opus統括セッションへの即時通知（v2.0.10 send_message）
opus_conv_id = None
try:
    import json
    with open("backend/agents/orchestration/flash_session.json", "r", encoding="utf-8") as f:
        sd = json.load(f)
    opus_conv_id = sd.get("opus_conversation_id")
except Exception:
    pass

if opus_conv_id:
    send_message(
        Recipient=opus_conv_id,
        Message="🏁 [FLASH_SESSION_COMPLETE] Flash実行セッションが全タスクを完遂しました。generate_flash_prompt.py を自動実行し、新規Flash開設用プロンプトをユーザーに提示してください。"
    )

# 3. 完遂プロトコル（session_end 未呼出なら呼ぶ）
hub.flash_session_end("ミッション完遂: Phase {N} 全タスク完了")

# 4. 閉鎖案内を表示（ユーザーへの最終メッセージ）
print("""
⚠️ 全処理が完了しました。リソース解放のため以下を実行してください:
👉 このチャット（Flash側チャット）を閉じてください。
　 閉じることでCPU/メモリが即座に解放されます。
　 閉じない場合、PCのCPU負荷が高止まりしUIがフリーズする恐れがあります。
""")

# 5. 新規タイマー/ツール呼び出し禁止 — ここで応答を終了する
```

> [!CAUTION]
> **クリーンシャットダウンを省略するとCPUリークが発生し、PCのUIがフリーズする恐れがある。**
> 過去のインシデント（2026-05-26, 2026-05-28）で、完遂後もプロセスが残存しCPU 80%超が7時間継続した実績あり。

---

## タスクプロンプト生成テンプレート

### test_weaver（テスト追加 — L1）
```
Phase {N} のテスト追加タスク。
対象モジュール: {target_module}
手順:
1. pytest --cov --timeout=300 で未カバー行を特定
2. 未カバー行へのユニットテストを設計・実装
3. pytest --timeout=300 でテスト実行し全PASS確認
4. カバレッジ改善量を報告
制約: プロダクションコードの変更禁止（L1）。テストコードのみ。
⚠️ pytest実行時は必ず --timeout=300 を付与すること（ハング防止）。
```

### bug_hunter（バグ修正 — L2）
```
Phase {N} のバグ修正タスク。
対象モジュール: {target_module}
手順:
1. pytest --timeout=300 実行でFAIL/Warning検出
2. 原因特定・修正（3ファイル以内）
3. テスト追加
4. pytest --timeout=300 で全テストPASS確認
制約: 3ファイル以内の変更のみ（L2）。超過時は報告して停止。
⚠️ pytest実行時は必ず --timeout=300 を付与すること（ハング防止）。
```

### refactor（リファクタリング — L2）
```
Phase {N} のリファクタリングタスク。
対象モジュール: {target_module}
手順:
1. dead code検出・除去
2. 命名改善・関数分割
3. pytest --timeout=300 で全テストPASS確認
4. カバレッジ非退行確認
制約: 3ファイル以内の変更のみ（L2）。機能変更禁止。
⚠️ pytest実行時は必ず --timeout=300 を付与すること（ハング防止）。
```

### tdr_cleanup（技術負債解消 — L2）
```
Phase {N} の技術負債解消タスク。
backend/agents/memory/technical_debt_index.json を読み、
CRITICAL/HIGH の未解消エントリから1件を選択して修正する。
手順:
1. TDRエントリの内容を確認
2. 修正を実施（3ファイル以内）
3. 全テストPASS確認
4. TDR APIで resolve_debt() を呼び、証拠を記録
制約: 3ファイル以内の変更のみ（L2）。
```

---

## 停止条件

以下の条件に該当した場合 **のみ** ループを停止する。それ以外は **絶対に止まらない**。

1. `phase_state.emergency_stop == true`
2. `current_phase > roadmap_max_phase`（ロードマップ完了 → 正常終了）

### 停止時の処理
```python
hub.flash_session_end("終了理由をここに記載")
# → 内部で自動的にOpusへ緊急通知が送信される
```

### 復旧
- Opus側で `hub.resume_from_stop()` が実行される
- プロジェクト2で「続行して」と入力すると自走ループが再開される

---

## 安全規約

> 全安全規約の正の定義は `FLASH_RULES.md` に集約されています。
> ここでは重複を避けるため、参照のみとします。
> **変更・追加は必ず `FLASH_RULES.md` に対して行うこと。**

---

## 改定履歴

| バージョン | 日付 | 変更内容 |
|:---|:---|:---|
| 1.0.0 | 2026-05-21 | 初版。OrchestrationHub連携。Phase 20まで永続自走。 |
| 2.0.0 | 2026-05-21 | 自動計装版。3 APIに全副作用を埋め込み。 |
| **3.0.0** | **2026-05-21** | **コンテキスト効率化版。API仕様をワークフロー内に完全内蔵し、orchestrator.py の直接参照を排除（~13,500トークン/バッチ削減）。安全規約をインライン化。** |
| **3.1.0** | **2026-05-22** | **アイドル防止規約追加。batch_size=15→4に制限（6時間ストール防止）。セルフウェイクアップタイマー（3分おき）を必須化。夜間無人運転での実績に基づく改定。** |
| **3.2.0** | **2026-05-26** | **Single Source of Truth化。Phase上限を25に統一。タイマーを動的可変化(180秒固定→batch_size×50秒)。安全規約をFLASH_RULES.md参照に一元化。API仕様のbatch_size=15→6に修正。** |
| **3.3.0** | **2026-05-26** | **ステータス表示義務化。バッチ完了時・タイマー発火時のgenerate_flash_status()表示を必須化。15秒ポーリング禁止→最低60秒間隔を義務化。print()→チャットUIテキスト出力への転記を明示。** |
| **3.4.0** | **2026-05-27** | **心拍レジリエンス強化。タイマー発火時にflash_update_heartbeat()による心拍更新を最優先実行。auto_stopped状態からの自動復旧ロジック追加。自動停止閾値を30分→60分に延長（30-60分はHub連携維持のまま警告）。** |
| **3.5.0** | **2026-05-27** | **恒久的運用改善4点。R1:ユーザーメッセージ受信後の自走ループ自動復帰(§⑦)。R2:タイマー発火プロンプトへの強制役割再確認注入(§⑧)。R3:バッチ間10秒クールダウン(リソース枯渇防止)。R4:30分超stale runningタスクの自動リセット(セッション引き継ぎ効率化)。** |
| **3.6.0** | **2026-05-29** | **v2.0.10 send_message統合。Flash完遂時にOpus統括セッションへ即時通知を送信。ファイルベース通知の遅延（最大5分）を解消。** |
| **3.7.0** | **2026-05-29** | **タイムロス改善A1: BATCH_TIMEOUT 1200→900秒に短縮。サブエージェントのタイムアウト（600秒）検知 → タスク `fail` マーク → `hub.flash_update_heartbeat()` で心拍更新 → 次バッチへ遷移。末尾タスクハングによるSTALE→DEAD連鎖を防止。** |
