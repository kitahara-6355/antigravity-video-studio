# M0 手順書 — クラウドのセッションに実キーを渡す（ユーザー作業・2026-09-26）

**決定（2026-09-26）**: クラウド環境の Secrets に登録するのは **`avs-prod-free`（Free tier・請求先なし）の `GOOGLE_API_KEY` だけ**。
pro のキーは登録しない → クラウドからは**課金が物理的に起きない**。raw 素材の保管場所（GCS / Cloudflare R2）は **M1g のゲートで決める**（当面の実走はローカル）。

所要 15〜20 分。課金は発生しない。

## 1. キーが Free tier であることを確かめる（3分）

1. [AI Studio](https://aistudio.google.com/) → 左の **API キー** 一覧を開く
2. `avs-prod-free` の行の **「請求階層」列が `無料枠`** であることを見る
   - `Tier 1` と出ていたら、CLAUDE.md「Free tier のプロジェクトの作り方」の手順2（請求先のリンク解除）へ戻る。**この状態で先へ進まない**
3. キー本体はコピーしておく（このあと Secrets に貼る）。**リポジトリには書かない**（キーのルール3）

## 2. クラウド環境の Secrets に登録する（5分）

1. Claude Code（Web）の **環境（Environment）設定** を開く（このセッションを作った環境）
2. **Secrets / 環境変数** に追加:

   | 名前 | 値 |
   |---|---|
   | `GOOGLE_API_KEY` | `avs-prod-free` のキー本体 |

   `GOOGLE_API_KEY_PRO` は**登録しない**（クラウドからの課金経路を作らない）
3. 保存する。**次に作るセッションから**有効になる（いまのセッションには入らない）

設定画面の場所が分からないときは、私に「環境の設定を出して」と言ってください（`read_documentation` で現在の手順を出します）。

## 3. 台帳に末尾4文字を記す（2分）

- `backend/config/api_projects.json`（M0 で私が作る台帳）に、`avs-prod-free` のキーの**末尾4文字だけ**を書きます。
  私が作った後に、末尾4文字を教えてください（キー本体は送らないでください）

## 4. 確認（私がやる）

新しいクラウドのセッションで:

```
python -m backend.verify_account --projects      # 台帳と Secrets の突き合わせ（M0 で作る）
python -m backend.model_policy --audit           # models.list と照合（実キーで初めて通る）
python -m backend.cost_guard --status            # active な予算枠（plan-M1）の残高
```

3つとも exit 0 で M0 の完了。**実走はしない**（M1 の PR4 まで実キーの呼び出しはない）。

## 5. まだやらないこと（後のゲートで決める）

| 項目 | いつ |
|---|---|
| raw 4本の保管場所（GCS on avs-prod-paid ＋ 請求先の自動切断 ／ Cloudflare R2 無料枠） | **M1g** |
| Monthly spend cap（pro のプロジェクト） | pro のキーをどこかに置く直前（M1 PR4 をローカルでやるとき） |
| YouTube Data API の OAuth | M3 の着手時（`docs/youtube_api_setup.md`） |
