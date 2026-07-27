# UXストーリー検証連動ルールブック v1.0

> **制定日**: 2026-04-29
> **目的**: UXストーリーの更新と検証システムの完全連動を保証する
> **適用範囲**: O-1〜O-12, A-1〜A-7 の全UXストーリー
> **自動参照**: GEMINI.md §UX検証連動 / /qa-audit §3.1 / test_ux_ratchet.py

---

## §1 基本原則

### 1.1 連動の三原則

1. **UXストーリーなくして検証項目なし** — 全検証項目は必ずUXストーリーのシーンに紐付く
2. **検証項目なくして充足率なし** — 充足率はE2Eテスト通過項目のみからカウントする
3. **ラチェットなくして更新なし** — UXストーリー更新時は必ずラチェット検証を通す

### 1.2 禁止事項

- UXストーリーに紐付かない検証項目の追加 (連動率 ≥ 85%の保証違反)
- 検証項目の削除 (ラチェット違反: 項目数の単調増加保証)
- テスト通過数の後退 (ラチェット違反: PASS数の単調増加保証)
- 充足率の意図的な水増し (1項目 ≤ 0.3%の影響しか持たない設計)

---

## §2 検証5層モデル

全検証項目は以下の5層に分類される。各UXストーリーに全5層の項目が必要。

| 層 | 名称 | 検証内容 | 最低項目数/UX |
|:---:|:---|:---|:---:|
| L1 | DOM存在 | 要素の存在/可視性/属性値 | 5 |
| L2 | 視覚FBK | テキスト/色/状態バッジの正しさ | 4 |
| L3 | 操作 | クリック/入力/ドラッグ/キーボード | 5 |
| L4 | 状態遷移 | 正常→エラー→復帰の3状態 | 3 |
| L5 | E2E完走 | UXストーリーの完全シナリオ | 3 |

### 2.1 層の健全性基準

```
各UXストーリーにおいて:
  L1+L2 ≤ 全体の50%  (存在確認だけで充足しない)
  L3+L4+L5 ≥ 全体の50%  (操作・遷移・完走が半数以上)
```

---

## §3 UXストーリー更新プロトコル

### 3.1 更新トリガー

以下のいずれかに該当する場合、UXストーリーの更新が必要:

1. 新機能の実装完了時
2. 既存機能のUI/UX変更時
3. ユーザーフィードバックによる体験改善時
4. Phase移行時（品質ゲート条件）

### 3.2 更新手順 (6ステップ必須)

```
Step 1: PROJECT_CONSTITUTION.md §7.3 の該当UXストーリーを確認
  ↓
Step 2: ux_verification/stories/{ux_id}_{name}.json を更新
  - scenes[] にシーン追加/変更
  - verification_items[] に新規検証項目を追加
  - 全項目に story_scene の紐付けを設定
  ↓
Step 3: ラチェット検証 (必須ゲート)
  $ python -m pytest tests/test_ux_ratchet.py -v
  → FAIL なら Step 2 に戻る (検証項目・連動率・PASS数の単調増加違反)
  ↓
Step 4: E2Eテスト更新
  - tests/e2e/test_e2e_{nn}_{name}.py に新規テストを追加
  - テスト実行: $ python -m pytest tests/e2e/test_e2e_{nn}_*.py -v
  ↓
Step 5: スナップショット保存
  - ux_verification/snapshots/v{N}.json を生成
  - ラチェットレポートを出力
  ↓
Step 6: UX充足マトリクス更新
  - docs/ux_fulfillment_matrix.md のサマリーを更新
  - VERIFIED_FACTS.md に記録
```

### 3.3 更新時の制約条件

| 制約 | 条件 | 検証方法 |
|:---|:---|:---|
| 項目数 ≥ 前回 | `curr.total_items >= prev.total_items` | ラチェット自動検証 |
| 連動率 ≥ 前回 | `curr.correlation_rate >= prev.correlation_rate` | ラチェット自動検証 |
| PASS数 ≥ 前回 | `curr.pass_items >= prev.pass_items` | ラチェット自動検証 |
| 連動率 ≥ 85% | 全検証項目の85%以上がシーンに紐付き | correlation.py 自動検証 |
| 5層全存在 | 各UXに L1〜L5 の項目が必要 | test_ux_ratchet.py |
| 1項目影響 ≤ 0.3% | 項目数 ≥ 335 (12UX合計) | test_ux_ratchet.py |

---

## §4 ストーリーJSON仕様

各UXストーリーは `ux_verification/stories/` 配下にJSONファイルとして定義する。

### 4.1 ファイル命名規則

```
{ux_id_normalized}_{function_name}.json

例:
  o1_material.json       (O-1 素材選択)
  o2_transcription.json  (O-2 文字起こし)
  o3_proofreading.json   (O-3 AI校閲)
  o10_theme.json         (O-10 テーマ選択)
```

### 4.2 JSON構造

```json
{
  "ux_id": "O-2",
  "name": "文字起こし",
  "description": "...",
  "scenes": [
    {
      "id": "S1",
      "text": "OwnerはWhisperモデルを選択できる",
      "linked_items": ["O2-L1-01", "O2-L3-01"]
    }
  ],
  "verification_items": [
    {
      "id": "O2-L1-01",
      "layer": 1,
      "story_scene": "S1",
      "description": "...",
      "test_method": "dom_exists"
    }
  ]
}
```

### 4.3 検証項目ID命名規則

```
{UX_ID}-L{Layer}-{Sequential}

例: O2-L1-01, O2-L3-07, O3-L5-06
```

---

## §5 適合度差分レポート

### 5.1 自動生成タイミング

- UXストーリー更新時
- Phase移行時の品質ゲート
- `/qa-audit` 実行時

### 5.2 レポート内容

```
╔══════════════════════════════════════════════════════╗
║  UX検証適合度差分レポート v{N-1} → v{N}            ║
╠══════════════════════════════════════════════════════╣
║  検証項目数:  N → M  (+K) ✅/❌                    ║
║  連動率:      X% → Y%  (+Z%) ✅/❌                 ║
║  充足PASS:    A → B  (+C) ✅/❌                    ║
║  充足率:      P% → Q%  (+R%)                       ║
║  システム適合度ギャップ:                             ║
║    O-X: a/b (c%) — LN層でd件未PASS                  ║
╚══════════════════════════════════════════════════════╝
```

---

## §6 自動実行パス

### 6.1 テスト実行コマンド

```powershell
# ラチェット + 連動率 + 5層検証 (ユニットテスト)
python -m pytest tests/test_ux_ratchet.py -v --timeout=60

# E2E 5層検証 (Playwright)
python -m pytest tests/e2e/test_e2e_02_transcription.py tests/e2e/test_e2e_03_proofreading.py -v --timeout=60

# ラチェットレポート生成 (スクリプト)
python -c "
from ux_verification.snapshot import SnapshotStore
from ux_verification.ratchet import RatchetValidator
store = SnapshotStore()
versions = store.list_versions()
if len(versions) >= 2:
    prev = store.load(versions[-2])
    curr = store.load(versions[-1])
    result = RatchetValidator().validate(prev, curr)
    print(result.report)
"
```

### 6.2 品質ゲート条件

```
Phase移行時に全て必須:
  □ test_ux_ratchet.py 全PASS
  □ E2E全テスト PASS
  □ ラチェットレポートで全3指標 ✅
  □ 連動率 ≥ 85% (全UXストーリー)
  □ 充足率 ≥ 前回充足率 (後退禁止)
```

---

## §7 エスカレーション

| 状況 | 対応 |
|:---|:---|
| ラチェット3回連続FAIL | 即停止 → ユーザーに設計相談 |
| 連動率 < 85% | UXストーリーのシーン分解が不足 → シーン追加 |
| 充足率が下がった | 検証項目増加による正常な低下か確認 → 分母増なら許容 |
| 検証項目の削除要求 | 原則禁止。廃止されたUXストーリーの場合のみユーザー承認で可 |

---

## 改定履歴

| バージョン | 日付 | 内容 |
|:---|:---|:---|
| 1.0 | 2026-04-29 | 初版制定。検証5層モデル、ラチェット機構、連動率保証、更新プロトコル定義 |
