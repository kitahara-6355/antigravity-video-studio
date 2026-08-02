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
| `Human01_Official Artifact/` **一式** | セッションレポート・受信トレイ・会話ログ。ディレクトリごと除外した |
| `antigravity_phase18/19_*` | 過去版スナップショット。API キー直書きもここにあった |
| ルート直下の作業ゴミ 59件 | ログ・カバレッジダンプ・一時出力・バックアップ |
| 人物写真4点 | プレースホルダに差し替え済み（`assets/asset_index.json` は無変更） |
| `e2e-tests.yml` | `next-gen-ui` が `.gitmodules` 未登録の gitlink で、一度も成功していなかった |

#### `Human01_Official Artifact/` について（重要）

**このリポジトリには 1 ファイルも存在しない。**`.resolved` 272件と開発推移表も含めて除外済み。
かつてこの表には「`.resolved` 272件と推移表は保持」と書かれていたが**事実と異なっていた**ため、
2026-07-28 に訂正した。原本は private の
`kitahara-6355/antigravity-video-studio-archive` にある。

- **再生成しないこと。** `generate_subagent_reports.py` やフルスイート実行で
  このディレクトリが作られることがある。コミットすると除去した意味が消える。
  `.gitignore` で無視しているが、`git add -f` では入ってしまう
- FF-25 / FF-27 はこのディレクトリを前提としたフィットネス関数なので、
  不在時は `pytest.skip` する（`backend/tests/test_fitness_functions.py`）。
  検証が必要なら原本のある private リポジトリ側で実行する

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
- `backend/branding/PROJECT_CONSTITUTION.md` — **製品のビジョンそのもの**なので憲法第1条により協働。私からは提案だけ
- `backend/agents/memory/VERIFIED_FACTS.md` — 自動生成（DreamEngine）。手で編集しない
- `TECHNICAL_DEBT_REGISTRY.md` も自動生成。手で編集せず `TechnicalDebtStore` API 経由で更新する

## 憲法 — Claude Code の行動規範（2026-08-02 制定・最優先）

**human-on-the-loop。** 実務は Claude Code が自律実行し、人間はフェーズの境界だけで判断する。

1. **判断の分界。** ビジョン・方針・優先順位・フェーズの定義は**ユーザーと協働**（私は提案するだけ）。
   そのフェーズ内の実装・設計・PR 分割・マージ時機・検証方法は**私が単独で決めて実行し、事後報告**する。
2. **停止条件。** フェーズの終了条件を満たしたら止まり、`/gate-report` を出して判断を待つ。
   **次のフェーズには入らない。**
3. **自律の対象外は課金判断のみ。** それ以外は main への push も含めて私が単独で実行してよい。
   **1円でも請求されるものはすべて対象。**

   **相談は「計画段階」でする。実行の直前ではない。**
   フェーズを設計する時点で有料利用を洗い出し、内訳と上限を示して予算を取る。
   **承認された予算の範囲内は都度確認せずに実行してよい**（`.claude/budget.json` が台帳。
   使ったら `spent_jpy` を更新する）。予算が無い有料利用に着手しない。

   有料になるもの:
   - **従量課金 API の実行** — このリポジトリでは **Gemini API**（本番38モジュール）と
     `text-embedding-004`。**パイプラインを1回走らせるだけで課金される。**
     Whisper / pyannote はローカルなので無料。**テスト実行も無料**
     （`net_guard` が外部接続を遮断し、キーは `dummy_key_for_ci`）
   - **Claude Code のプラン上限超過**（定額プラン）と**大規模 fan-out**（workflow・エージェント並列）
   - **外部サービスの課金操作** — GCP/npm publish/決済 API、GitHub Pro が要るブランチ保護など。
     これは予算ではなく個別判断なので、枠があっても止める

   `.claude/hooks/billing_gate.py` が機械的に見る。ただし
   `python backend/foo.py` の中で Gemini を呼ぶ経路は静的に見えないので、
   **フックは最後の一枚であって網ではない。** 実行前に「これは API を叩くか」を自分で問う。
4. **証拠主義。** 「完了」は主張ではなく証拠で示す（コマンドと出力、CI の run ID）。
   **自分の成果を自分で採点しない** — ゲート判定は `gate-verifier` に別コンテキストで検証させる。
5. **正典は1つ。** 現在地の正典は `backend/branding/vision_backlog.json`。
   `phase_state.json` と `docs/BACKLOG_MASTER.md` は参照資料。
   **台帳が食い違ったら実装を止めて正典の修復を優先する。**
6. **実装は Claude Code に一本化。** `.agent/` と `GEMINI.md` は読むが書かない。

手順の本体は `.claude/skills/`（`/phase-run`・`/vision-audit`・`/gate-report`）にある。

## 進め方

- TDD。テストを 1 つ書き、それを通す実装を 1 つ書く、を繰り返す
- デバッグは「仮説 → ログで観測 → 検証」。推測で直さない
- 破壊的操作は実行前に対象を確認する（承認は憲法第3条の範囲のみ）

## 詳細ルールの原典

Antigravity 用の詳細ルールは以下にある。**必要になったときだけ読む**（常時読み込むと文脈を圧迫する）。

- `GEMINI.md` — 全ルールの本体（1075行）
- `.agent/Anthropic_Core_Rules.md` — 設計プロトコル
- `.agent/User_Persona_Manifesto.md` — ユーザーの判断基準
- `.agent/ux-verification-rulebook.md` — UX検証の手順
- `.agent/config_index.json` — 設定ファイルの所在マップ

これらは Antigravity 側の管理下。このブランチからは編集しない。
