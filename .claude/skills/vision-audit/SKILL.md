---
name: vision-audit
description: ビジョン実現度を実測し、正典 vision_backlog.json を更新する。antigravity-video-studio 用。フェーズ終了時・四半期・ユーザー手動発動で使う。Antigravity 版 /vision-gap-audit の後継で、除去済みの Human01_Official Artifact に依存しない。
---

# ビジョン乖離度監査（リポジトリ内完結版）

`.agent/workflows/vision-gap-audit.md` の後継。**旧版は基準文書と出力先が
`Human01_Official Artifact/` を指しており、このリポジトリでは走らない**
（公開時にディレクトリごと除去したため。CLAUDE.md 参照）。

## スコアの原則

    コード存在 = 最大 20%
    E2E 動作確認 = 50% 以上
    本番動画での確認 = 100%

**「実装されている」を根拠にしない。** 2026-04-18 に、キャッシュ依存で通った
E2E を根拠に 50% と評価し、キャッシュを消したら 26% だったことがある。
**厳格監査ではキャッシュを必ず除去してから測る。**

## 10軸と重み

正典 `backend/branding/vision_backlog.json` の `axis_scores` にある。
重みの合計で加重平均を取る。軸を勝手に増減しない（時系列が切れる）。

| 軸 | 重み | 実測の取り方 |
|---|---:|---|
| pipeline_e2e | 20 | キャッシュ除去 → パイプライン起動 → 各ステージの status |
| ui_api_connection | 15 | Browser の read_page で7コンポーネント表示 + API 応答 |
| ux_guarantee_owner | 15 | O-1〜O-12 の動作率（`docs/ux_fulfillment_matrix.md`） |
| quality_auto_improve | 10 | 品質ゲート < 90 で改善ループが回るか |
| soul_auto_evolution | 10 | evolution_log の自動更新（**writable_path 経由**なので振り向け先を見る） |
| test_coverage | 10 | CI の coverage.json。**手元計測は権威にしない** |
| trinity_council | 5 | 実装存在 + 本番セッション実行の有無 |
| storage_auto_manage | 5 | 自動クリーンアップの稼働 |
| progressive_preview | 5 | 承認フローの強制 |
| ux_guarantee_admin | 5 | A-1〜A-7 の動作率 |

## 課金する軸がある（監査を計画する時点で予算を取る）

**`pipeline_e2e` の実測はパイプラインを実際に走らせる = Gemini API を叩く = 課金。**
`ui_api_connection` も、UI からパイプラインを起動する経路を踏むと同じ。

憲法第3条により、**監査に着手する時点で**この2軸ぶんの予算を取り
`.claude/budget.json` に記録する。**予算内なら実行のたびに確認しない。**
走らせたら実績を `spent_jpy` に反映する。

予算が無い/取れないときは、その軸を `status: "not_measured"` として前回値を据え置き、
**据え置いたことを監査レポートに明記する。** 測っていないものを測ったことにしない。

無料で測れる軸: `test_coverage`（CI の coverage.json）、
`trinity_council` / `storage_auto_manage` / `progressive_preview`（実装存在 + テスト）、
`soul_auto_evolution`（振り向け先のファイル更新）。
`ux_guarantee_*` は表示確認までなら無料、操作で生成を起こすと課金。

## 手順

1. **前回値を読む** — `vision_realization_score` / `score_history` / `axis_scores`。
   サマリー欄と履歴が食い違っていたら**それ自体を所見として記録**する
2. **軸ごとに実測** — 上表の方法で。測れなかった軸は前回値を据え置き、
   `status: "not_measured"` を付ける。**測っていないものを測ったことにしない**
3. **バックログを更新** — 新規の乖離を追加、解消したものを `resolved` へ。
   `resolved` にするには証拠（テスト名・CI run ID）を `note` に書く
4. **スコアを再計算し `score_history` に追記** — `date` / `score` / `trigger`
5. **`vision_realization_score` を履歴の最新と一致させる**（ここが乖離していた）
6. **レポートを `docs/vision_audit_YYYYMMDD.md` に出す** —
   出力先は `Human01_Official Artifact/` では**ない**

## 出力に必ず含めるもの

- 前回 vs 今回のスコアカード比較（軸ごと）
- 測れなかった軸とその理由
- 次フェーズの候補（P0 = 重み × 改善余地が最大のもの）

## 落とし穴

- **カバレッジは CI(Linux) の実測のみを使う。** ローカル全体実行はメモリ死する
- **フロントには CI が無い。** 「全部グリーン」でもビルド可否は未検証。
  UI 軸を測るときは手元で `npm run build` / `npm run lint` を回す
- **スコアを上げるための実装をしない。** 監査は測るだけ。直すのは次フェーズ
