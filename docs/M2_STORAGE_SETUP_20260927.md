# M2 手順書 — raw 4本を Google Drive（法人 Workspace）に置く（ユーザー作業・2026-09-27）

**決定（2026-09-27・M1g）**: raw 素材（4本・約1.1GB）のクラウド側の保管場所は **法人 Workspace（`info@kitahara-birei.com`）の Google Drive**。
方針は「Workspace で完結できるものは Workspace に。GCP は足りないときだけ」（2026-09-27 ユーザー）。
当初 Cloudflare R2 と決めたが、同日この方針に合わせて改めた。GCS は請求先が必須なので採らない。

これが済むと R2.5-C5（クラウドのセッションだけで C1〜C4 が再現する）に進める。**済むまでの実走はローカル**。
リポジトリには Drive の読み書きの実装が既にある（`backend/services/google_oauth.py`・`workspace_sync.py` の `GoogleDriveStore`）。新しく作るのは「読み取り専用で raw を落とす口」だけ。

所要 30〜45 分（アップロードの時間を含む）。**課金は発生しない**（Drive API は無料。Workspace の容量に収まる）。

## お金と権限の話（先に読む）

| 項目 | 内容 | 確度 |
|---|---|---|
| 費用 | Drive API は無料。容量は法人 Workspace の枠（1.1GB は誤差） | 一次情報（Workspace の契約内容）はユーザーが把握 |
| 鍵と API の置き場 | OAuth クライアントと Drive API の有効化は **GCP プロジェクト `avs-prod-free`**（法人・請求先なし）に置く。Drive API の有効化に請求先は要らない。**「Workspace 完結」は正確には「データは Workspace に、鍵は請求先なしの GCP プロジェクトに」** | 二次情報（unverified_secondary） |
| 同意画面 | 法人 Workspace なので **User Type を「内部」** にできる。内部なら Google の審査が不要で、テスト公開の「リフレッシュトークン 7 日失効」も当たらない（`scripts/google_oauth_login.py` の注意書きは個人 Gmail 時代のもの） | 二次情報。**同意画面で「内部」が選べなければ私に言ってください** |
| スコープ | **`drive.readonly`**（読むだけ）。既存の `DRIVE_SCOPES` は `drive`（読み書き）なので、raw 用は読み取り専用の口を別に作る（私の作業） | — |

事故止め:
- クラウドのセッションに渡すトークンは**読み取り専用スコープ**で作る。書き出しは M2 の中で別途決める（憲法 §11「raw は聖域」）
- raw のフォルダは**共有ドライブ**に置く（所有者が個人にならない。`workspace_sync.py` の 2026-07-30 の設計と同じ）
- `verify_account --projects` が台帳と Secrets の食い違いを FAIL で止める

## 1. Drive 側（10分）

1. 法人 Workspace で共有ドライブを1つ用意する（既存の「10-チャンネルA」があればそれでよい）
2. その中に raw 用フォルダ `01-input/`（未処理 RAW）を置き、**フォルダ ID**（URL の `folders/` の後ろ）を控える
3. raw 4本をブラウザからアップロードする（Drive のブラウザアップロードは 1.1GB なら問題ない。回線しだいで 10〜30 分）
4. 4本の名前と大きさを控える（後で私が `--list` の結果と突き合わせる）

## 2. GCP 側（`avs-prod-free`・10分・請求先は付けない）

1. [Cloud Console](https://console.cloud.google.com/) で **`avs-prod-free`**（プロジェクト ID は `avs-prod-free-kb`）を選ぶ（法人アカウントで）
2. 「API とサービス」→「ライブラリ」→ **Google Drive API** を有効化
3. 「OAuth 同意画面」: User Type **内部**、アプリ名 `avs-raw-reader`、連絡先 `info@kitahara-birei.com`。スコープに `https://www.googleapis.com/auth/drive.readonly` を追加
4. 「認証情報」→ OAuth クライアント ID → 種類 **デスクトップアプリ**、名前 `avs-raw-reader`。JSON をダウンロード
5. ダウンロードした JSON を**ローカルの** `backend/data/google/client_secret.json` に置く（`.gitignore` 済み。リポジトリに入れない）

## 3. ローカルで同意してトークンを作る（5分・私が用意するスクリプト）

```
python scripts/google_oauth_login.py --readonly --token backend/data/google/token_raw_readonly.json
```

（`--readonly` と `--token` は M2 の最初の PR で足す。それまでは実行しない）
ブラウザが開くので、**法人アカウント**で同意する。トークンが 1 ファイルできる（秘密）。

## 4. クラウド環境の Secrets に登録する（5分）

Claude Code（Web）の環境設定 → Secrets / 環境変数に 2 つ追加する（`GOOGLE_API_KEY` と同じ場所）:

| 名前 | 値 |
|---|---|
| `ANTIGRAVITY_GOOGLE_TOKEN_JSON` | 手順 3 でできたトークンファイルの**中身**（JSON をそのまま貼る） |
| `AVS_RAW_DRIVE_FOLDER_ID` | 手順 1 のフォルダ ID |

保存すると**次に作るセッションから**有効。台帳（`backend/config/api_projects.json`）にはフォルダ ID の末尾4文字だけを記す（教えてください）。

## 5. 確認（私がやる・新しいクラウドのセッションで）

```
python -m backend.verify_account --projects   # 台帳と Secrets の突き合わせ（Drive の 2 変数も見る）
python -m backend.raw_source --list           # Drive から raw 4本の名前と大きさを読む（M2 で作る。読むだけ）
```

2つとも exit 0 で保管場所の準備は完了。**実走はしない**（実走は R2.5 の PR で、`plan-M2` の枠内）。

## 6. まだやらないこと

| 項目 | いつ |
|---|---|
| 完成品（`vault-outputs/`）を Drive の `02-output/` に書く | R2.5 の書き出しをクラウドで通すとき（書き込みスコープのトークンを別に作る） |
| Monthly spend cap（pro のプロジェクト） | pro のキーをどこかに置く直前 |
| YouTube Data API の OAuth | M3 の着手時（同じ `avs-prod-free`・同じ同意画面にスコープを足す） |
