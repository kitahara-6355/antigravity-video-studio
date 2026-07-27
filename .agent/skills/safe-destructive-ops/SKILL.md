# Safe Destructive Operations Skill
ファイル削除・本番デプロイ・外部API送信など、不可逆な破壊的操作を実行する際のセキュリティゲート。

## Prerequisites (前提条件)
*   **トリガー条件**: ファイル一括削除、本番環境へのデプロイ、外部APIへのデータ送信、DB変更の直前。
*   **必要ツール**: `tools/record_skill_metrics.py`
*   **参照ルール**: [Anthropic_Core_Rules.md](file:///.agent/Anthropic_Core_Rules.md) — Section 9 (Security)

## Recipe (実行手順)
1.  **影響範囲リストの生成**
    操作対象のファイル名、レコード件数、送信先URLなどを一覧にまとめ、影響範囲を「局所・コンポーネント・全体」で分類する。
2.  **ロールバック手段の確認**
    操作を取り消す手段（Gitの`revert`、バックアップファイルの存在、APIのundo等）が事前に存在するかを確認・記録する。ロールバック手段がない場合はその旨を明記する。
3.  **ユーザー承認の強制取得 (USER HALT)**
    影響範囲リストとロールバック手段をユーザーに提示し、`notify_user` で明示的な承認を得る。承認なしに絶対に実行してはならない。
4.  **操作の実行と証跡記録**
    承認後に操作を実行する。実行した操作の内容をログに記録する（何を削除したか、何を送信したか等）。
5.  **メトリクス記録 (終了前必須)**
    ```bash
    python tools/record_skill_metrics.py --skill safe-destructive-ops \
      --success <true|false> \
      --tokens <estimated_tokens> \
      --trigger_accuracy <high|medium|low> \
      --tool_efficiency <high|medium|low>
    ```

## Error Handling (エラー時の対応)
*   操作途中でエラーが発生した場合、即座に停止し、実行済みの範囲と未実行の範囲をユーザーに報告すること。
*   ロールバック手段が事前に確認されていた場合は、その実行をユーザーに提案すること。

## Persona & Developer Rules (ユーザー固有スタイルの局所注入)
*   **【鉄則】「壊す前に聞け。壊したら証拠を残せ。」**
*   コストカット時にリポジトリごと吹き飛ばすのではなく、「古いイメージのみ削除し、基盤は保持する」等の選択的保持を徹底すること。（Persona No.23, 25）
*   影響範囲がアーキテクチャ全体に及ぶ場合は、ユーザーが「進め」と言っても自律的にブロックし、議論を要求すること。（Persona No.11）

## References (参照)
*   [User_Persona_Manifesto.md](file:///.agent/User_Persona_Manifesto.md) — No.11, 23, 25
