# antigravity-video-studio

動画生成パイプライン。Python バックエンド + Next.js フロントエンド。

## このリポジトリについて

**独立した公開リポジトリ。** 2026-07-27 に、旧 private リポジトリ
`kitahara-6355/antigravity-video-studio` の作業ツリーから作り直した。

- 履歴は引き継いでいない。旧リポジトリの履歴には API キーが残っていたため、
  公開にあたって履歴ごと切り離した。旧リポジトリは Private のまま保管されている
- 到達点（旧リポジトリ CI run 30224919255 実測）: テスト 9,207件 失敗0 / カバレッジ 75.7%
- 経緯の詳細は `docs/CC_HANDOVER_TRACE_20260725.md` §11-12

### 旧リポジトリから持ち込まなかったもの

| 除外 | 理由 |
|---|---|
| `Human01_Official Artifact/` の本文 2,846件 | セッションレポート・受信トレイ。`.resolved` 272件と推移表は保持（FF ラチェットが要求） |
| `antigravity_phase18/19_*` | 過去版スナップショット。API キー直書きもここにあった |
| ルート直下の作業ゴミ 59件 | ログ・カバレッジダンプ・一時出力・バックアップ |
| 人物写真4点 | プレースホルダに差し替え済み（`assets/asset_index.json` は無変更） |
| `e2e-tests.yml` | `next-gen-ui` が `.gitmodules` 未登録の gitlink で、一度も成功していなかった |

## このブランチの目的

**main にマージできる状態に到達すること。** trinity-3.0 / 4.0 が止まった原因は「マージしてよいと判断する基準が存在しない」ことなので、まず基準を作る。

現状（2026-07-25 時点）:
- main は全ブランチの祖先。マージは fast-forward でコンフリクトは起きない
- CI は 2026-01-29 に1回失敗して以来動いていない（`ci.yml` は `branches: [main, develop]` のみで発火）
- 発火しても `|| true` と `continue-on-error` でゲートとして機能しない

<!-- マージ基準が確定したらこの下に「## main マージ基準」として追記する -->

## 検証（作業の締めに必ず実行）

```
pytest                              # pytest.ini の testpaths を全実行
pytest tests/test_ux_ratchet.py     # UX検証ラチェット（連動率85%以上が必須）
```

テストが 3 回連続で FAIL したら、そのまま続けず状況を報告して止まる。

## 触ってはいけないもの

- `backend/.env`、`*.key`、`vault-assets/raw/**` — 読み取りも行わない
- `archives/`、`antigravity_phase18_stable_v1/`、`antigravity_phase19_experimental_v1/` — 過去版のスナップショット
- `backend/branding/PROJECT_CONSTITUTION.md`、`backend/agents/memory/VERIFIED_FACTS.md` — 変更前に必ず承認を取る
- `TECHNICAL_DEBT_REGISTRY.md` は自動生成。手で編集せず `TechnicalDebtStore` API 経由で更新する

## 進め方

- TDD。テストを 1 つ書き、それを通す実装を 1 つ書く、を繰り返す
- デバッグは「仮説 → ログで観測 → 検証」。推測で直さない
- 破壊的操作（ファイル削除、大量書き換え、外部 API への書き込み）は事前に承認を取る

## 詳細ルールの原典

Antigravity 用の詳細ルールは以下にある。**必要になったときだけ読む**（常時読み込むと文脈を圧迫する）。

- `GEMINI.md` — 全ルールの本体（1075行）
- `.agent/Anthropic_Core_Rules.md` — 設計プロトコル
- `.agent/User_Persona_Manifesto.md` — ユーザーの判断基準
- `.agent/ux-verification-rulebook.md` — UX検証の手順
- `.agent/config_index.json` — 設定ファイルの所在マップ

これらは Antigravity 側の管理下。このブランチからは編集しない。
