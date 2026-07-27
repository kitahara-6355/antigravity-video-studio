# Metrics Collector Skill - Version 2 (metrics-collector-v2)

システム全体のテスト実行状況およびカバレッジ測定を行い、そのメトリクスを動的に状態管理ファイル（`phase_state.json`）に記録する新サブエージェント専用の役割と手順を定義します。

## Prerequisites (前提条件)
*   **トリガー条件**: バッチの実行完了時（`OrchestrationHubV2.submit_batch_report` の呼び出し時）、または手動でのメトリクス同期指示時。
*   **必要ツール**: `pytest` コマンド、`coverage` コマンド。
*   **参照ルール**: `backend/AGENTS_v2.md` (Metrics Collector の役割)。

## Recipe (実行手順)
1.  **テスト総数とパス率の測定**
    `pytest` コマンドを用いて、全テストケース数、および現在のパス数を動的に測定する。
    ```powershell
    python -m pytest --co -q
    ```
2.  **カバレッジの測定**
    `pytest-cov` または `coverage` を用いて、システム全体のブランチカバレッジを動的に取得する。
    ```powershell
    python -m pytest --cov=backend --cov-report=json
    ```
3.  **状態への反映**
    測定結果（`test_count`, `coverage_pct` 等）を `phase_state.json` の `metrics` セクションに書き出す。
    ```json
    "metrics": {
      "test_count": <測定されたテスト数>,
      "coverage_pct": <測定されたカバレッジ値>,
      "quality_score": <パス率など>,
      "ratchet_items": <検証項目数>,
      "critical_debt": <CRITICAL技術負債件数>
    }
    ```
4.  **ダッシュボード同期**
    メトリクス変更後、直ちに `generate_subagent_reports.py` を呼び出して README.md およびダッシュボードを再生成する。

## Error Handling (エラー時の対応)
*   カバレッジレポート生成に失敗した場合、前回の値を維持したまま警告ログを出力し、異常検出（Loop Detector v2）へ通知する。
*   テスト実行がフリーズした場合は、タイムアウト（60秒）でプロセスを終了させ、ペナルティ対象として一時退避する。

## References (参照)
*   [AGENTS_v2.md](file:///c:/Users/PC_User/Desktop/script/video-automation/backend/AGENTS_v2.md)
*   [phase_state.json](file:///c:/Users/PC_User/Desktop/script/video-automation/backend/agents/memory/phase_state.json)
