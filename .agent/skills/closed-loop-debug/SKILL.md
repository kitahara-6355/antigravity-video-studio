# Closed-Loop Debug Skill
エラーやバグが発生した際、推測による修正を禁止し、証拠に基づく厳格なデバッグループを実行するスキル。

## Prerequisites (前提条件)
*   **トリガー条件**: ツール実行エラー発生時、ユーザーからのバグ報告時、テスト失敗時。
*   **必要ツール**: `tools/run_backend_tests.py`, `tools/record_skill_metrics.py`
*   **参照ルール**: [Anthropic_Core_Rules.md](file:///.agent/Anthropic_Core_Rules.md) — Section 7 (Error Handling & Recovery)

## Recipe (実行手順)
1.  **根本原因の探索（Root Cause First）**
    パッチを当てる前に、過去のログやメトリクス（`vault-outputs/logs/skills_metrics.jsonl`）から「いつ・なぜこれが失敗したか」の証拠を掘り返す。
2.  **仮説の立案**
    証拠に基づき、失敗の原因仮説を1〜3個に絞り込んで明文化する。
3.  **ログ仕込みと検証**
    仮説を検証するためのログ出力やprint文を対象コードに仕込み、再実行して「事実」を取得する。
4.  **事実に基づくコード修正**
    ログの事実が仮説を裏付けた場合のみ、コードを修正する。裏付けられなかった場合はステップ2に戻る。
5.  **回帰テストの実行**
    修正後、関連するテストを実行し、デグレード（他の箇所への影響）が発生していないことを確認する。
    ```bash
    python tools/run_backend_tests.py --verbose
    ```
6.  **メトリクス記録 (終了前必須)**
    ```bash
    python tools/record_skill_metrics.py --skill closed-loop-debug \
      --success <true|false> \
      --tokens <estimated_tokens> \
      --trigger_accuracy <high|medium|low> \
      --tool_efficiency <high|medium|low>
    ```

## Error Handling (エラー時の対応)
*   リトライは最大3回まで。3回を超えた場合はユーザーに報告し、判断を仰ぐこと（Core Rule 7）。
*   PC負荷依存のタイムアウトが疑われる場合は、すぐにコードのバグと決めつけず、リトライや負荷軽減の仮説を立てること。

## Persona & Developer Rules (ユーザー固有スタイルの局所注入)
*   **【鉄則】「推測でコードを修正するな。事実だけが真実である。」**
*   仮説の段階でコードを直してはならない。必ずログの「事実」を見てから修正すること。（Persona No.9, 30, 32）
*   過去に成功した処理のタイムアウトは、バグではなくPC負荷を疑うこと。（Persona No.16）

## References (参照)
*   [User_Persona_Manifesto.md](file:///.agent/User_Persona_Manifesto.md) — No.9, 14, 15, 16, 30, 32
