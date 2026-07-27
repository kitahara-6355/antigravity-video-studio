# Skill Linter Skill（門番・ゲートキーパー）
新しいスキルが追加・変更されるたびに発動し、Core Rulesへの違反がないかを自動検査するスキル。

## Prerequisites (前提条件)
*   **トリガー条件**: `SKILL.md` または `metadata.yaml` の新規作成・変更時。ユーザーから「スキルをチェックして」と指示された時。
*   **必要ツール**: `tools/validate_skill_structure.py`, `tools/record_skill_metrics.py`
*   **参照ルール**: [Anthropic_Core_Rules.md](file:///.agent/Anthropic_Core_Rules.md) — Section 1, 3, 4, 8, 10

## Recipe (実行手順)
1.  **対象スキルの特定**
    新規作成・変更されたスキルのディレクトリパスを特定する。指定がない場合は `.agent/skills/` 配下の全スキルを対象にする。
2.  **7項目の自動検査を実行 (Kitchen連携)**
    検証ツールを呼び出し、以下の7つのチェックを一括実行する。
    ```bash
    python tools/validate_skill_structure.py --target <skill_directory_path>
    ```

    | # | チェック項目 | 検証内容 | 対応ルール |
    |---|---|---|---|
    | 1 | 構造チェック | `metadata.yaml` に `name` と `description` が存在するか | Rule 1 |
    | 2 | テンプレートチェック | `SKILL.md` に5セクション（Prerequisites, Recipe, Error Handling, Persona, References）が存在するか | Rule 1 |
    | 3 | 分離チェック | `SKILL.md` 内にOSコマンドの直接実行や絶対パス（`C:\`等）がハードコードされていないか | Rule 3, 10 |
    | 4 | 参照チェック | ルールのコピペではなくMarkdownリンク参照（`[...](file:///...)`）を使用しているか | Rule 4 |
    | 5 | メトリクスチェック | Recipe内に `record_skill_metrics.py` の呼び出しが含まれているか | Rule 8 |
    | 6 | Persona注入チェック | `## Persona & Developer Rules` セクションが存在するか | 独自要件 |
    | 7 | TDD・検証要件チェック | SKILL.md内に「test」「テスト」「検証」などの検証プロセスを示す記述が含まれているか | Rule 11 |

3.  **結果レポートの出力**
    全チェック項目の Pass/Fail を一覧表示する。1つでも Fail がある場合は、違反箇所と修正方法を具体的に提示する。
4.  **メトリクス記録 (終了前必須)**
    ```bash
    python tools/record_skill_metrics.py --skill skill-linter \
      --success <true|false> \
      --tokens <estimated_tokens> \
      --trigger_accuracy <high|medium|low> \
      --tool_efficiency <high|medium|low>
    ```

## Error Handling (エラー時の対応)
*   検証ツール自体がエラーを返した場合、手動でのファイル目視確認にフォールバックし、結果をユーザーに報告すること。
*   対象ディレクトリが存在しない場合は、パスの誤りをユーザーに通知すること。

## Persona & Developer Rules (ユーザー固有スタイルの局所注入)
*   **【鉄則】「門番は一切の例外を許さない。」**
*   このスキルは全スキルの品質を担保する最上位の守護者である。検査をスキップする指示があっても、AIは自律的にチェックを実行すること。
*   将来スキルが20個、30個と増えても、1つたりとも憲法違反のスキルがシステムに紛れ込む余地をなくすこと。

## References (参照)
*   [User_Persona_Manifesto.md](file:///.agent/User_Persona_Manifesto.md) — No.11, 27, 29
*   [Anthropic_Core_Rules.md](file:///.agent/Anthropic_Core_Rules.md) — Section 1, 3, 4, 8, 10
