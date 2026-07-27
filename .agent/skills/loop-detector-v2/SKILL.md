# Loop Detector Skill - Version 2 (loop-detector-v2)

自律開発ループにおける空振り（空PASS）、重複した同一モジュールへの偏り、メトリクス固着などの「構造的機能不全（スタグネーション）」を自動で検知し、自律的に開発ループを制御・自己修復する新サブエージェント専用の役割と手順を定義します。

## Prerequisites (前提条件)
*   **トリガー条件**: 各バッチ実行完了時の結果集計フェーズ、および定期的なヘルスチェック実行時。
*   **必要ツール**: `backend/agents/orchestration/flash_reports.jsonl`, `backend/agents/memory/phase_state.json`, `backend/agents/orchestration/opus_directive.json`
*   **参照ルール**: `backend/AGENTS_v2.md` (Loop Detector の役割)、`PROJECT_CONSTITUTION.md` §26.5-26.9。

## Recipe (実行手順)

### 1. 空PASS（空振り）の検知とペナルティ適用
*   Flashエージェントがタスクを完了した際、`changed_files` が空 (`[]`) だった場合、その結果は「空PASS」と見なす。
*   同一のモジュール名（例: `comprehensive_preview.py`）に対して、連続して「空PASS」が3回検出された場合、システムはそのモジュールを自動的に `phase_state.json` の `blacklisted_modules` へ追加する。
*   この自動ブラックリストは、3バッチの間有効とし、タスク生成エージェントに対してそのモジュールを対象としたタスク生成を禁止する。

### 2. 有効打率 (Effective Rate) の低下検知
*   直近3バッチのタスク総数に対する有効タスク数（`changed_files` が1つ以上存在するタスク）の比率が **10% 未満**になった場合、自走ループが空回りしていると判定する。

### 3. メトリクス固着の検知
*   15バッチ連続で `test_count` や `coverage_pct` などの主要開発メトリクスに変動がない場合、開発の停滞（スタグネーション）と判定する。

### 4. 自動停止と自律修復（Self-Healing）
*   「有効打率の低下」または「メトリクスの固着」が検出された場合、即座にセッション状態を `auto_stop` とし、理由 (`stop_reason`) を記録して実行を一時停止する。
*   **自律修復アクション**: 
    1. 停滞の原因となっているモジュールを特定し、`opus_directive.json` の `blacklist_override` に追加。
    2. 優先タスクの配分を調整し、テスト作成やリファクタリングなど問題となっている部分にリソースを動的再配分する Directive を自律的に更新する。
    3. 自律修復アクション完了後、ダッシュボードに「LoopDetector: 停滞回避のためDirectiveを自動修復しました」とログ出力する。

## Error Handling (エラー時の対応)
*   誤検知を防ぐため、初期バッチ（最初の3バッチ）はペナルティや停止の適用対象外とする。

## References (参照)
*   [AGENTS_v2.md](file:///c:/Users/PC_User/Desktop/script/video-automation/backend/AGENTS_v2.md)
*   [flash_reports.jsonl](file:///c:/Users/PC_User/Desktop/script/video-automation/backend/agents/orchestration/flash_reports.jsonl)
*   [PROJECT_CONSTITUTION.md](file:///c:/Users/PC_User/Desktop/script/video-automation/backend/branding/PROJECT_CONSTITUTION.md)
