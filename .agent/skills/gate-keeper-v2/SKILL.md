# Gate Keeper Skill - Version 2 (gate-keeper-v2)

現在の開発状況が目標マイルストーン（Phase Gate）を通過できるか検証し、進行の意思決定（フェーズ移行）を司る新サブエージェント専用の役割と手順を定義します。

## Prerequisites (前提条件)
*   **トリガー条件**: バッチレポート送信後（`submit_batch_report` の後続処理）、または手動による移行チェック要求時。
*   **必要ツール**: `backend/agents/memory/phase_gates.json`, `backend/agents/memory/phase_state.json`
*   **参照ルール**: `backend/AGENTS_v2.md` (Gate Keeper の役割)。

## Recipe (実行手順)
1.  **ゲート定義の読み込み**
    `phase_gates.json` を読み込み、現在のPhaseに対応する移行条件（例: 最小カバレッジ、最大技術負債、テストPASS等）を抽出する。
2.  **基本条件と個別条件のチェック**
    *   **基本条件（全Phase共通）**:
        - カバレッジ目標達成 (70%以上)
        - 技術的負債が許容値以下 (0件)
        - 緊急停止フラグ (`emergency_stop`) が False であること
        - **変更対象行カバレッジ 100% の保証 (憲法 §20.4)**
        - **UXストーリー検証ラチェットテスト (test_ux_ratchet.py) の全PASS**
3.  **フォールバック判定 (フェイルセーフの緩和)**
    *   もし `phase_gates.json` に該当Phaseの定義が存在しない場合（Phase 21〜29など）、**基本条件のみ**（カバレッジ目標 70% 以上、変更行カバレッジ100%、UXラチェットPASS、負債 0、緊急停止なし）で検証を行い、全条件が満たされていれば通過（フォールバック通過）と判定する。
4.  **移行処理**
    *   すべてのゲート条件をクリアした場合、`phase_state.json` の `current_phase` を `+1` に更新し、マイルストーンを次のPhaseの最初のコード（例: M28.1）に進める。
    *   条件をクリアしていない場合は、現在のPhaseのまま開発を継続し、未達項目をログ出力する。

## Error Handling (エラー時の対応)
*   `phase_gates.json` 破損時は、移行処理を完全に中断し、デフォルトエラー状態としてProduct Ownerへエスカレーションする。

## References (参照)
*   [AGENTS_v2.md](file:///c:/Users/PC_User/Desktop/script/video-automation/backend/AGENTS_v2.md)
*   [phase_gates.json](file:///c:/Users/PC_User/Desktop/script/video-automation/backend/agents/memory/phase_gates.json)
