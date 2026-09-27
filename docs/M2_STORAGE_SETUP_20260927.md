# M2 手順書 — raw 4本を Cloudflare R2 に置く（ユーザー作業・2026-09-27）

**決定（2026-09-27・M1g）**: raw 素材（4本・約1.1GB）のクラウド側の保管場所は **Cloudflare R2 の無料枠**。
GCS は請求先が必須で `avs-prod-free` に置けないため採らない。

これが済むと R2.5-C5（クラウドのセッションだけで C1〜C4 が再現する）に進める。**済むまでの実走はローカル**。

所要 30〜60 分（アップロードの時間を含む）。**課金は発生しない見込み**（下の「お金の話」）。

## お金の話（先に読む）

| 項目 | 内容 | 確度 |
|---|---|---|
| 無料枠 | **保存 10 GB/月・Class A 操作 100万回/月・Class B 操作 1,000万回/月・下り転送（egress）は無制限で無料** | 二次情報（unverified_secondary）。この実行環境のプロキシは developers.cloudflare.com を遮断しており一次情報を引けなかった。**登録画面の表示で確かめる** |
| 超えたとき | 保存 $0.015/GB-月。raw 4本 1.1GB では到達しない。**Cloudflare には Google の spend cap のような月額上限は無い** | 同上 |
| 支払い方法 | **R2 を有効化するときに支払い方法（カード）の登録を求められる可能性が高い**（無料枠の範囲なら請求は $0）。私が前回の選択肢で「クレカ登録不要」と書いたのは**確認の取れていない記述**だったので、ここで訂正する | 同上。**登録画面で求められたら、進める前に私に言ってください**（このまま進めるか・当面ローカルにするかを選択肢で出す） |

事故止め（¥10,000 の天井の中で）:
- バケットは **1つ**（`avs-raw`）。raw 以外を置かない。10 GB の1割で止まる
- トークンは**読み取り専用**（Object Read only）。クラウドのセッションは書けない（憲法 §11「raw は聖域」）
- Cloudflare の **Billing → Notifications** で請求通知を ON にする（あれば）

## 1. アカウントとバケット（10分）

1. https://dash.cloudflare.com/ でアカウントを作る（既にあればそれを使う。**法人のメール `info@kitahara-birei.com` を推奨** — 本番の資産を法人側に寄せる方針、CLAUDE.md「本番は法人に置く」と同じ）
2. 左メニュー **R2 Object Storage** → 有効化。**ここで支払い方法を求められたら上の「お金の話」へ**
3. **Create bucket** → 名前 `avs-raw`、Location は Automatic（APAC が選べれば APAC）。**Public access は OFF のまま**
4. 何も設定を足さない（ライフサイクル・イベント通知・カスタムドメインは使わない）

## 2. 読み取り専用のトークン（5分）

1. R2 の画面 → **Manage R2 API Tokens** → **Create API token**
2. 名前: `avs-raw-read`（**キー名＝用途**。CLAUDE.md のキーのルール2と同じ考え方）
3. Permissions: **Object Read only**
4. Specify bucket(s): **`avs-raw` だけ**
5. TTL: 無期限でよい（漏えい時はこの画面で失効させる）
6. 作成後に表示される **Access Key ID / Secret Access Key / エンドポイント**（`https://<ACCOUNT_ID>.r2.cloudflarestorage.com`）を控える。**Secret はこの画面を閉じると二度と見られない**

## 3. クラウド環境の Secrets に登録する（5分）

Claude Code（Web）の環境設定 → Secrets / 環境変数に4つ追加する（`GOOGLE_API_KEY` と同じ場所。M0 の手順書 §2）:

| 名前 | 値 |
|---|---|
| `R2_ACCOUNT_ID` | エンドポイントの `<ACCOUNT_ID>` の部分 |
| `R2_ACCESS_KEY_ID` | トークンの Access Key ID |
| `R2_SECRET_ACCESS_KEY` | トークンの Secret Access Key |
| `R2_BUCKET` | `avs-raw` |

保存すると**次に作るセッションから**有効。**リポジトリには一切書かない**。台帳（`backend/config/api_projects.json`）には Access Key ID の末尾4文字だけを記す（私が作った後に教えてください）。

## 4. raw 4本をアップロードする（15〜40分・回線しだい）

ダッシュボードの直接アップロードは1ファイルの上限が小さい（二次情報: 300 MB）ので、**rclone**（S3 互換）を使う。

1. rclone を入れる（Windows: `winget install Rclone.Rclone`／mac: `brew install rclone`）
2. **書き込みできるトークンを別に1本**作る（§2 と同じ手順で Permissions を **Object Read & Write**、名前 `avs-raw-upload`）。**アップロードが終わったら失効させる**（クラウド側には読み取り専用しか残さない）
3. 設定（`~/.config/rclone/rclone.conf` に追記。値は自分のものに置き換える）:

```
[r2]
type = s3
provider = Cloudflare
access_key_id = <avs-raw-upload の Access Key ID>
secret_access_key = <avs-raw-upload の Secret>
endpoint = https://<ACCOUNT_ID>.r2.cloudflarestorage.com
acl = private
```

4. アップロード（ローカルの raw 置き場を指定。`vault-assets/raw/` の実体の場所）:

```
rclone copy "<ローカルの raw フォルダ>" r2:avs-raw/raw/ --progress --checksum
rclone ls r2:avs-raw/
```

5. 4本が出て合計が約 1.1 GB なら完了。**`avs-raw-upload` のトークンを失効させる**

## 5. 確認（私がやる・新しいクラウドのセッションで）

```
python -m backend.verify_account --projects   # 台帳と Secrets の突き合わせ（R2 の4変数も見る）
python -m backend.raw_source --list           # R2 から raw 4本の名前と大きさを読む（M2 で作る。読むだけ）
```

2つとも exit 0 で保管場所の準備は完了。**実走はしない**（実走は R2.5 の PR で、`plan-M2` の枠内）。

## 6. まだやらないこと

| 項目 | いつ |
|---|---|
| 完成品（`vault-outputs/`）をクラウドに置く | R2.5 の書き出しをクラウドで通すとき（別の書き込み用バケットかローカルへ戻すかを M2 の中で決める） |
| Monthly spend cap（pro のプロジェクト） | pro のキーをどこかに置く直前 |
| YouTube Data API の OAuth | M3 の着手時 |
