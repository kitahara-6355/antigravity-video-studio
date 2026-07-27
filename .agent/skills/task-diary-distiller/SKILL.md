# Task Diary Distiller Skill
セッションの終了やフェーズ完了時に、一時的なコンテキストから「永続的なシステムの教訓」を抽出し、複利的に知識を蓄積するスキル。

## Prerequisites (前提条件)
*   **トリガー条件**: 大きな機能の実装完了時、特定フェーズの終了時、またはユーザーからの「今回は何を学んだか記録して」という指示があった時。
*   **必要ツール**: `tools/record_skill_metrics.py`
*   **参照ルール**: [Anthropic_Core_Rules.md](file:///.agent/Anthropic_Core_Rules.md) — Section 6 (State Management), Section 8 (Metrics)

## Recipe (実行手順)
1.  **メトリクス・ログの分析**
    直近の開発活動における `vault-outputs/logs/skills_metrics.jsonl` （特にツール失敗と最適化提案の項目）や、デバッグで苦労した事象のチャットコンテキストを振り返る。
2.  **教訓（Lessons Learned）の抽出**
    「何がうまくいったか」「何でつまずいたか」「どうすれば次回から防げるか」という観点で、具体的で実行可能な教訓を3〜5個抽出する。
3.  **知識の永続化（CLAUDE.md / Persona への統合）**
    抽出した教訓のうち、システム全体で永続化すべき極めて重要なものは、内容の妥当性を十分に検証し、ユーザーの承認（USER HALT）を得た上で `User_Persona_Manifesto.md` または `Anthropic_Core_Rules.md` 等へ直接追記する。
    局所的な知見の場合は、プロジェクト内の `knowledge/` 等に `Lessons_Learned.md` として蓄積する。
4.  **メトリクス記録 (終了前必須)**
    ```bash
    python tools/record_skill_metrics.py --skill task-diary-distiller \
      --success <true|false> \
      --tokens <estimated_tokens> \
      --trigger_accuracy <high|medium|low> \
      --tool_efficiency <high|medium|low>
    ```

## Error Handling (エラー時の対応)
*   メトリクスログが空の場合や有効な教訓が得られない場合は、無理に知識を作出せず「特筆すべき課題なし」として終了すること。
*   ルールファイル（憲法）を改変する際は、`skill-linter`等の既存エコシステムを破壊しないよう細心の注意を払うこと。

## Persona & Developer Rules (ユーザー固有スタイルの局所注入)
*   **【鉄則】「同じエラーで二度泣くな。」**
*   セッションが終わればコンテキストは消える。消える前に、肉体（アーキテクチャ）に教訓を刻み込め。（Task Diary の教訓）
*   抽象的なポエムではなく、「次回からこのツールにはこの引数をつけろ」といった明確な具体性を持たせること。

## References (参照)
*   [User_Persona_Manifesto.md](file:///.agent/User_Persona_Manifesto.md) — No.9, 15, 30
