# Progressive Preview Skill
動画に関する破壊的・高負荷な処理を行う際、AIはこのレシピ手順と制約に従うこと。

## Prerequisites (前提条件)
*   **トリガー条件**: 動画のCrop設定、字幕焼き込み、カラーグレーディングなどを行う直前。または「プレビューを見せて」「プレビュー優先で」という指示があった時。
*   **必要ツール**: `tools/generate_preview.py`
*   **参照ルール**: [Anthropic_Core_Rules.md](file:///.agent/Anthropic_Core_Rules.md)

## Recipe (実行手順)
1.  **事前確認（Kitchen呼び出し）**
    本処理に進む前に、対象動画の短いサンプル（例：10秒）を抽出し、適用予定の処理（crop等）を行った画像や動画を生成する。
    ```
    tools/generate_preview.py --input <source_video> --duration 10 --effect <effect_name>
    ```
2.  **レポート出力**
    Before/Afterを比較できるHTMLレポートまたはスクショ画像を規定フォルダ（`vault-outputs/previews/`）へ出力する。
3.  **ユーザーへの一時停止と確認 (USER HALT)**
    結果を出力したら直ちに処理を中断し、ユーザーに「プレビューを出力しました。ブラウザで確認し、問題なければ承認してください」と `notify_user` で必ず確認を求める。
4.  **本処理の実行**
    ユーザーから「承認」または「OK」と返答があった場合のみ、フル動画に対する本番処理を開始する。事後にも完了報告のプレビューを出力すること。
5.  **メトリクス記録 (終了前必須)**
    処理完了後、または明示的な中止後に必ず以下のツールを呼び出し、実行結果とトークン消費を記録すること。
    ```bash
    python tools/record_skill_metrics.py --skill progressive-preview \
      --success <true|false> \
      --tokens <estimated_tokens> \
      --trigger_accuracy <high|medium|low> \
      --tool_efficiency <high|medium|low>
    ```

## Error Handling (エラー時の対応)
*   プレビュー生成ツールがタイムアウトまたは失敗した場合、静止画のスクリーンショット1枚（フレーム抽出）にフォールバックして、最低限の目視確認を可能にすること。
*   ツール側の失敗は握り潰さず、エラー内容をログに記録した上でユーザーに報告すること。

## Persona & Developer Rules (ユーザー固有スタイルの局所注入)
*   **【鉄則】「見てから決める。決めたら見せる。」**
*   ユーザーが一言で「動画全部クロップしておいて」と指示してきた場合でも、処理が重い場合は勝手に完了させず、AI側から「まずプレビューを作りますか？」とヒアリング・提案して処理を一時停止する【わがまま要件】を最優先すること。

## References (参照)
*   [User_Persona_Manifesto.md](file:///.agent/User_Persona_Manifesto.md) - ユーザーの開発理念（項目1: Progressive Preview要件）
