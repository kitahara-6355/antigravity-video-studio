# TDD Orchestrator Skill
システムのロジックや機能を追加・変更する際、コンテキスト汚染を防ぎながら Red-Green-Refactor の極小サイクルを強制するスキル。

## Prerequisites (前提条件)
*   **トリガー条件**: 新機能の実装、既存ロジックの変更、バグ修正（コード変更を伴う場合）。
*   **必要ツール**: `tools/run_backend_tests.py`, `tools/record_skill_metrics.py`
*   **参照ルール**: [Anthropic_Core_Rules.md](file:///.agent/Anthropic_Core_Rules.md) — Section 11 (TDD Protocol), Section 13 (Opponent Processor)

## Recipe (実行手順)
1.  **Red (失敗するテストの作成)**
    実装ファイルには一切触れず、仕様を満たしているかを検証する「失敗するテスト（1件のみ）」を作成する。作成後、テストを実行して確実に「失敗（Red）」すること（またはモックの不足等で落ちること）を確認する。
    ```bash
    python tools/run_backend_tests.py --target <test_file_path>
    ```
2.  **Green (最小限の実装)**
    テストが失敗する事実（エラーログ）を証拠として、そのテストをパスさせるための「最小限の実装」のみを行う。余計な機能や将来の拡張を先回りして実装してはならない。実装後、テストを実行して「成功（Green）」することを確認する。
3.  **Refactor (リファクタリングとOpponent Processorの自己監査)**
    テストが通った直後、必ず「あえて自分の実装を厳しく批判・異議表明する（Auditor）」という別の視点を持つ**対立検証（Opponent Processor）プロセス**を踏むこと。
    「このコードの脆弱性はどこか？」「より計算効率の良い代替アプローチはないか？」をAuditorとして考察し、その議論による見解がまとまってから、必要に応じてリファクタリングを行い、再度テストが通ることを確認する。
4.  **サイクルの反復**
    未実装の仕様が残っている場合は Step 1 に戻り、1件ずつ極小スコープでループを回す。一度に複数のテストを書く「カンニング」は厳禁。
5.  **メトリクス記録 (終了前必須)**
    ```bash
    python tools/record_skill_metrics.py --skill tdd-orchestrator \
      --success <true|false> \
      --tokens <estimated_tokens> \
      --trigger_accuracy <high|medium|low> \
      --tool_efficiency <high|medium|low>
    ```

## Error Handling (エラー時の対応)
*   Greenステップでテストが通らない場合、実装のアプローチが間違っている可能性をログから分析し、仮説を立て直してコードを修正すること。
*   Refactorステップによってテストが落ちた場合は、直前の変更を即座に元に戻し（revert）、安全な状態から再試行すること。

## Persona & Developer Rules (ユーザー固有スタイルの局所注入)
*   **【鉄則】「正直なテストを書け。一気書きはカンニングである。」**
*   テストは必ず「観察された振る舞い」を検証するものであり、「想像された振る舞い」をテストしてはならない。スコープドリフトを防ぐ極小サイクルを死守すること。（Zenn記事の教訓）
*   AIはリファクタリングをサボりやすいため、明示的なStep 3の自己監査を絶対に省略しないこと。

## References (参照)
*   [User_Persona_Manifesto.md](file:///.agent/User_Persona_Manifesto.md) — No.9, 27, 30
*   [Anthropic_Core_Rules.md](file:///.agent/Anthropic_Core_Rules.md) — Section 11, Section 13
