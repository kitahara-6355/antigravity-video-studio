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

## 目的 — **YouTube の収益化**（2026-08-15 ユーザー決定）

**北極星は `backend/branding/vision_backlog.json` の `revenue_goal`。**
ユーザー1人が YouTube 収益化（登録者1,000人 + 長尺4,000時間 / Shorts 1,000万回）に到達すること。
長尺を主軸に、Shorts で登録者を集める。

**成否を決めるのは外部の実績であって、リポジトリ内部の実現度スコアではない。**
実現度は「収益化に効いているか」を見る補助指標に降格した。

### 効いている制約（どちらも外部の期日）

| 期日 | 何が起きるか |
|---|---|
| **2027-02-01** | 新規申請者の収益化基準が**2倍**になる（長尺 8,000時間 / Shorts 2,000万回）。現行基準で通すなら残り約5.5ヶ月 |
| **2026-10-16** | **Gemini 2.5 系が提供終了。** リポジトリは `gemini-2.5-flash` を 475 箇所で参照している |

### 単一で最大のリスク — Inauthentic Content（量産型判定）

YouTube は 2025-07-15 に「反復コンテンツ」を「量産型コンテンツ」へ改称して厳格化した。
**テンプレで作られ、動画間の差分が小さく、容易に大量複製できるものは収益化不可。**
顔出しなしAI動画・読み上げ解説が名指しされている。

**このリポジトリは放置すると、完成した瞬間にこの類型に一致する。**
救いは「人間の創造的投入が明確なら AI 主体でも可」という運用基準なので、
**1本ごとに人間の承認を通す工程を必須にし、その証跡を残す**（R2）。
未完の Progressive Preview（D-16 / D-07）がそのまま証跡装置になる。

**これらは二次情報で確認したもの（confidence: unverified_secondary）。
実際に申請・投稿する前に一次情報と突き合わせること。**

### 旧目的（達成済み・凍結）

main にマージできる基準を作ること。P1〜P5 で静的検証と CI ゲートを作り終えた。
**これ以上は磨かない** — `scoring_policy` の「静的検証+CI ゲート=最大50%」が天井で、
収益化に寄与しない。既存のゲートは回帰防止として CI で動かし続ける。

現状（2026-07-25 時点）:
- main は全ブランチの祖先。マージは fast-forward でコンフリクトは起きない
- CI は 2026-01-29 に1回失敗して以来動いていない（`ci.yml` は `branches: [main, develop]` のみで発火）
- 発火しても `|| true` と `continue-on-error` でゲートとして機能しない

<!-- マージ基準が確定したらこの下に「## main マージ基準」として追記する -->

## 完了の定義（DoD）— **利用者に見える成果で示す**

フェーズの終了条件には**必ず1つ「人が見て分かる成果物」**を含める（動画・画面・数字）。
静的ゲートが緑であることは完了の証拠にならない。**回帰していないことの証拠**にすぎない。

- 「動く」の証拠は成果物（`*.mp4`・投稿記録・チャンネルの数字）
- 「壊れていない」の証拠は CI（run ID）
- **自分の成果を自分で採点しない**（憲法第4条は維持）

## 敵対的検証の停止規則（2026-08-15 ユーザー決定・`verification_policy` が正典）

**これが無かったので P3 は26回・P4 は14回・P5 は10回の作り直しになった。**
静的解析に対して反例は原理的に無限に出せる。

1. 反例は必ず**分類する** — 「うっかり書いてしまう類」か「意図的な回避」か
2. **意図的な回避は1回目から `limits` に宣言して先へ進む。塞がない**
3. うっかり型は塞ぐ。ただし**同一条件への `gate-verifier` は最大2周**
4. 3周目に入る前に、条件文そのものを見直してユーザーに上げる

実測コスト: `gate-verifier` 1周 = 約11万トークン / 修正込みで 30〜60分。

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

   `.claude/hooks/billing_gate.py` が機械的に見る。加えて **2026-08-15 から
   `backend/cost_guard.py` が課金経路の絞り口（`model_governance` の proxy）に入っており、
   呼び出しごとに実費を計上し、残高が尽きたら `CostLimitExceeded` で止める**。

   - 台帳: `.claude/cost_ledger.jsonl`（1行1呼び出し）／単価表: `backend/config/gemini_pricing.json`
   - `python -m backend.cost_guard --status` で残高、`--gate` で超過判定
   - **予算が無い実キーでの呼び出しは例外で止まる**（fail-closed）
   - 本番の全モジュールは `gemini_client_factory` を通る。**直接クライアントを組み立てない**
     （`backend/tests/test_cost_guard.py` が迂回の再発を止める）

   ただしフックもガードも**最後の一枚であって網ではない。**
   実行前に「これは API を叩くか」を自分で問う。
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
