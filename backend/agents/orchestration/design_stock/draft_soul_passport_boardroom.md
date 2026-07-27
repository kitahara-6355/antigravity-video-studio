# 設計ドラフト: Soul Passport & 演出評議会ボードルーム (IMP-BOARDROOM)

## 概要
Owner UXストーリー O-12（学習・進化）および憲法第5.2条（Soul Narrative）、第12条（自動進化プロトコル）、第15.5条（柔軟な撤回）をクリアするため、AIが自動学習したユーザーの「演出哲学（`evolution_log.json`）」や「ブランドポリシー（`constitution.json`）」を可視化し、ユーザーがAIの学習結果を編集・撤回・再審議できる「評議会ボードルーム (Boardroom UI)」の設計ドラフト。

## 1. ボードルームUIの構成概念

```
[Soul Passport: 魂の成長記録]
   ├── [演出哲学の年表 (Narrative Timeline)] ──── 過去の承認/却下から昇華された学びの歴史
   ├── [評議会室 (Boardroom UI)]
   │     ├── [自動追加されたポリシーの一覧] ─── AIが3回以上の却下パターンから学習したルール
   │     └── [編集・撤回（Veto / Delete）] ─── 「この自動ポリシーは極端なので削除/修正する」
   └── [ベンチマーク比較 (Soul Alignment)] ──── NHK規格、MrBeastなどの動画品質基準との一致度可視化
```

---

## 2. コア機能仕様

### ① 演出哲学の可視化タイムライン (`narrative_timeline.py`)
*   `evolution_log.json` に累積保存されている `philosophies[]` と `decision_insights` を時系列でマージ。
*   「どの動画の、どの却下判断から、どんな演出哲学が生まれたか」をストーリーとしてUI上に可視化する。
*   例: 「2026-05-21: 対談山田動画でBGMがうるさいと却下。ここから『BGMは-12dB以下』という哲学が生まれ、以降の動画に適用」

### ② 自動進化ポリシーの編集・撤回 (`policy_governor.py`)
*   憲法第12.2条に基づき、AIは「3回却下で `constitution.json` に自動追記」「5回承認でキーワード追加」を行う。
*   ボードルームUIでは、これらの「AIが自動で書き足したルール」をカード形式で表示し、ユーザーが個別に以下の操作を行えるようにする。
    *   **承認・恒久化**: ルールをシステム標準としてロックする。
    *   **撤回（Veto）**: ルールを削除し、AIに「このルールは適用外とする」と再学習させる（`constitution.json` からの自動削除）。
    *   **パラメータ変更**: 例: クランプ値を `-12dB` から `-15dB` へ直接手動調整。

### ③ 魂の適合度グラフ（Soul Alignment）
*   自己改善ループ時の品質スコア（NHKの字幕視認性規格や、MrBeastのCTRアテンション設計基準）の合格度合いをレーダーチャートやパーセンテージで表示する。
*   システム健康度、ワークフロー効率性、魂の満足度の3つを統合した `vision_realization_score` の推移を可視化。

---

## 3. バックエンド API 仕様

*   **`GET /api/boardroom/philosophies`**: 可視化タイムライン用データの取得。
*   **`GET /api/boardroom/policies`**: `constitution.json` に自動追記されたアクティブポリシーのリスト取得。
*   **`PUT /api/boardroom/policies/{id}`**: 自動ポリシーの編集（クランプ値の変更、スコープの調整）。
*   **`DELETE /api/boardroom/policies/{id}`**: 自動ポリシーの撤回・削除。
*   **`GET /api/boardroom/metrics/alignment`**: NHK規格/YouTuber基準との適合度およびビジョンスコア（3層評価）の推移の取得。

---

## 4. セルフチェックリスト / 完了条件
- [ ] 演出哲学タイムラインを `evolution_log.json` から動的生成する API の実装
- [ ] `constitution.json` の自動追記ルールを削除・編集する `policy_governor.py` の実装
- [ ] フロントエンドでの Boardroom（評議会ポリシー編集）UI画面の実装
- [ ] 適合度（NHK字幕 / YouTuber規格）の自動スコア化とレーダーチャート表示
- [ ] 全フィットネス関数テストが PASS すること
