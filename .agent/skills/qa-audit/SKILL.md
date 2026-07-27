# QA Audit Skill
システムの品質監査およびデバッグを行う際、AIはこのレシピ手順と制約に従うこと。

## Prerequisites (前提条件)
*   **トリガー条件**: ユーザーが「システム挙動に不安」と発言した時。UIやロジックの変更後に動作確認やデバッグが必要な時。
*   **必要ツール**: `tools/run_quality_audit.py`, `tools/capture_browser_state.py`
*   **参照ルール**: [Anthropic_Core_Rules.md](file:///.agent/Anthropic_Core_Rules.md)

## Recipe (実行手順)
1.  **自己監査とスコアチェック (Kitchen連携)**
    品質監査ツールを呼び出し、現在のアーキテクチャの品質スコアとエラーログを抽出する。
    ```
    tools/run_quality_audit.py --mode full --output json
    ```
2.  **UATテスト検分**
    UI変更が伴う場合は、Browser Agent を起動し、視認性と動作を実機確認する。
    ```
    tools/capture_browser_state.py --url http://localhost:3000 --output screenshot.png
    ```
3.  **自律的改善サイクルの実行**
    指定された問題点に対し、『原因調査 → 改善コード生成 → テスト検証 → 完了確認』の一連のサイクルを自動で回す。
4.  **メトリクス記録 (終了前必須)**
    監査と修復の完了（または中断）後、必ず以下のツールを呼び出し、今回の実績を記録すること。
    ```bash
    python tools/record_skill_metrics.py --skill qa-audit \
      --success <true|false> \
      --tokens <estimated_tokens> \
      --trigger_accuracy <high|medium|low> \
      --tool_efficiency <high|medium|low>
    ```

## Error Handling (エラー時の対応)
*   品質監査ツールがエラーを返した場合、そのエラー自体をログに記録した上で、手動での `pytest` 実行にフォールバックすること。
*   Browser Agentが環境変数（`$HOME`等）の未設定で初期化失敗した場合、ヘルスチェック結果をユーザーに報告し、環境修正を依頼すること。

## Persona & Developer Rules (ユーザー固有スタイルの局所注入)
*   **【鉄則】「クローズドループによるデバッグ」**
*   推測だけでコードを修正してはならない。エラー発生時は、必ず以下のループを厳格に回すこと。
    1.  原因の仮説を立てる
    2.  ログ出力を仕込む
    3.  実際にログの「事実」を見てからコードを修正する
*   UI変更時は、ソースコードの修正で満足せず、必ず「Browser Agent等を駆使してAI自身の眼と画面で視認・動作確認を行う」という【わがまま要件】を最優先タスクとして実行すること。

## References (参照)
*   [User_Persona_Manifesto.md](file:///.agent/User_Persona_Manifesto.md) - ユーザーの開発理念（項目9, 10: クローズドループ、Browser Agent目視）
