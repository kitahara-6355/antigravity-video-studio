# State Resumption Skill
長時間処理（動画エンコード等）の途中でクラッシュ・中断が発生しても、最後の成功ステップから安全に再開するためのスキル。

## Prerequisites (前提条件)
*   **トリガー条件**: 複数ステップにまたがる長時間処理の開始前。PC再起動後の復帰時。
*   **必要ツール**: `tools/record_skill_metrics.py`
*   **参照ルール**: [Anthropic_Core_Rules.md](file:///.agent/Anthropic_Core_Rules.md) — Section 6 (State Management)

## Recipe (実行手順)
1.  **状態ファイルの初期化**
    処理開始前に `vault-outputs/state/<task_name>_state.json` を作成し、全ステップのリストと初期ステータス（`pending`）を書き出す。
    ```json
    {
      "task": "subtitle-pipeline",
      "steps": [
        {"name": "transcription", "status": "pending"},
        {"name": "proofreading", "status": "pending"},
        {"name": "burn_in", "status": "pending"}
      ],
      "last_success_index": -1
    }
    ```
2.  **各ステップ完了時の状態更新**
    ステップが成功するたびに、該当ステップの `status` を `done` に更新し、`last_success_index` をインクリメントする。
3.  **復帰時の再開判定**
    処理が中断された後に再開する場合、状態ファイルを読み込み、`last_success_index + 1` のステップから処理を再開する。すでに `done` のステップは絶対にスキップする（冪等性の確保）。
4.  **完了時のクリーンアップ**
    全ステップが `done` になった場合、状態ファイルをアーカイブ（リネーム）または削除する。
5.  **メトリクス記録 (終了前必須)**
    ```bash
    python tools/record_skill_metrics.py --skill state-resumption \
      --success <true|false> \
      --tokens <estimated_tokens> \
      --trigger_accuracy <high|medium|low> \
      --tool_efficiency <high|medium|low>
    ```

## Error Handling (エラー時の対応)
*   状態ファイル自体が破損・消失した場合は、全ステップを最初からやり直す（フルリセット）こと。その旨をユーザーに報告すること。
*   部分的に完了したステップの出力ファイルが不完全な場合は、該当ステップのみを再実行すること。

## Persona & Developer Rules (ユーザー固有スタイルの局所注入)
*   **【鉄則】「壊れても、3秒で復活する。」**
*   状態ファイルはGit管理外（`vault-outputs/`）に保存し、コード空間を汚染しないこと。（Persona No.3, 4）
*   環境固有のパスをハードコードしないこと。GitHubからCloneし直すだけで復活できる設計を常に維持すること。（Persona No.4, 8）

## References (参照)
*   [User_Persona_Manifesto.md](file:///.agent/User_Persona_Manifesto.md) — No.3, 4, 8
