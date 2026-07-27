# Phase Completion Skill
あるフェーズから次のフェーズへ移行・完了報告する際、AIはこのレシピ手順と制約に従うこと。

## Prerequisites (前提条件)
*   **トリガー条件**: 開発フェーズが完了し、次のフェーズへ進みたい時。総合評価レポートの出力が必要な時。
*   **必要ツール**: `tools/run_quality_audit.py`, `tools/run_backend_tests.py`, `tools/start_server_check.py`
*   **参照ルール**: [Anthropic_Core_Rules.md](file:///.agent/Anthropic_Core_Rules.md)

## Recipe (実行手順)
1.  **品質チェック実行 (Kitchen連携)**
    バックエンドテストと品質監査を実行し、品質スコアを取得する。
    ```
    tools/run_backend_tests.py --verbose
    tools/run_quality_audit.py --mode full --output json
    ```
2.  **安定稼働確認**
    サーバーをテスト起動し、主要APIやUIが正常動作するか疎通確認を行う。
    ```
    tools/start_server_check.py --port 8000 --timeout 30
    ```
3.  **影響範囲分析の実行**
    フェーズ内で蓄積された改善タスク（バックログ）の影響範囲を「局所・コンポーネント・全体」に分類してレポート化する。
4.  **メトリクス記録 (終了前必須)**
    レポート出力後、フェーズ移行の可否に関わらずツールの実行結果と時間を必ず記録すること。
    ```bash
    python tools/record_skill_metrics.py --skill phase-completion \
      --success <true|false> \
      --tokens <estimated_tokens> \
      --trigger_accuracy <high|medium|low> \
      --tool_efficiency <high|medium|low>
    ```

## Error Handling (エラー時の対応)
*   テストが1つでも失敗した場合、フェーズ移行を自動的にブロックし、失敗したテスト名とエラーログをユーザーに報告すること。
*   サーバー起動タイムアウトが発生した場合、ポート競合の可能性を調査し、代替ポートまたはプロセスKillを提案すること。

## Persona & Developer Rules (ユーザー固有スタイルの局所注入)
*   **【鉄則】「安定第一・立ち止まる勇気」**
*   基本的にはスクリプトに従って「一気通貫」の実装・進行を奨励する。
*   ただし、影響範囲が「全体（アーキテクチャ）」に及ぶ改善タスクが発生した場合や、品質スコアが規定値（9.0/10.0）に満たない場合は、**ユーザーから「次へ進め」と指示されても、AI側から自律的にフェーズ移行をブロック（ストップ）し、設計見直しのディスカッションをユーザーに要求**すること。【わがまま要件：無理に進めず止めること】

## References (参照)
*   [User_Persona_Manifesto.md](file:///.agent/User_Persona_Manifesto.md) - ユーザーの開発理念（項目2, 11, 30: フェーズ移行プロトコル、安定第一、スコアベース評価）
