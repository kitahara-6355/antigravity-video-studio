# YouTube API セットアップガイド

このドキュメントでは、video-automationプロジェクトでYouTube動画を直接アップロードするための設定手順を説明します。

## 前提条件

- Googleアカウント
- Google Cloud Consoleへのアクセス

## ステップ1: Google Cloud プロジェクトの作成

1. [Google Cloud Console](https://console.cloud.google.com/) にアクセス
2. 新しいプロジェクトを作成
   - 「プロジェクトを選択」→「新しいプロジェクト」
   - プロジェクト名: `video-automation-youtube`（任意）
3. プロジェクトを選択

## ステップ2: YouTube Data API v3 の有効化

1. 左メニューから「APIとサービス」→「ライブラリ」
2. 「YouTube Data API v3」を検索
3. 「有効にする」をクリック

## ステップ3: OAuth 2.0 認証情報の作成

1. 「APIとサービス」→「認証情報」
2. 「認証情報を作成」→「OAuthクライアントID」

### 3.1 OAuth同意画面の設定（初回のみ）

1. ユーザータイプ: 「外部」を選択
2. アプリ名: `Video Automation`
3. ユーザーサポートメール: あなたのメールアドレス
4. デベロッパーの連絡先: あなたのメールアドレス
5. 「保存して続行」

### 3.2 スコープの設定

1. 「スコープを追加または削除」
2. 以下のスコープを追加:
   - `https://www.googleapis.com/auth/youtube.upload`
   - `https://www.googleapis.com/auth/youtube`
3. 「更新」→「保存して続行」

### 3.3 テストユーザーの追加

1. 「ユーザーを追加」
2. あなたのGoogleメールアドレスを追加
3. 「保存して続行」

### 3.4 OAuthクライアントIDの作成

1. 「認証情報を作成」→「OAuthクライアントID」
2. アプリケーションの種類: 「ウェブアプリケーション」
3. 名前: `Video Automation Client`
4. 承認済みリダイレクトURI: `http://localhost:8000/api/youtube-upload/callback`
5. 「作成」をクリック

## ステップ4: 認証情報の設定

1. 作成したOAuthクライアントの「クライアントID」と「クライアントシークレット」をメモ

2. プロジェクトに認証情報ファイルを作成:

```bash
mkdir -p backend/config
```

3. `backend/config/youtube_credentials.json` を作成:

```json
{
  "client_id": "YOUR_CLIENT_ID.apps.googleusercontent.com",
  "client_secret": "YOUR_CLIENT_SECRET"
}
```

## ステップ5: 認証フローの実行

1. バックエンドサーバーを起動:

```bash
cd backend
python -m uvicorn main:app --reload --port 8000
```

2. ブラウザで認証を開始:

```
http://localhost:8000/api/youtube-upload/auth
```

3. Googleアカウントでログインし、アクセスを許可

4. 認証成功後、`backend/config/youtube_credentials.json` にトークンが保存される

## ステップ6: 動画アップロードのテスト

認証完了後、以下のAPIでアップロード可能:

```bash
curl -X POST http://localhost:8000/api/youtube-upload/upload \
  -H "Content-Type: application/json" \
  -d '{
    "video_path": "/path/to/video.mp4",
    "title": "テスト動画",
    "description": "説明文",
    "tags": ["test", "video"],
    "privacy_status": "private"
  }'
```

## APIエンドポイント

| エンドポイント | メソッド | 説明 |
|:---|:---|:---|
| `/api/youtube-upload/auth` | GET | OAuth認証開始 |
| `/api/youtube-upload/callback` | GET | OAuthコールバック |
| `/api/youtube-upload/upload` | POST | 動画アップロード |
| `/api/youtube-upload/status` | GET | 認証状態確認 |

## トラブルシューティング

### 「アクセスがブロックされました」エラー

- OAuth同意画面で「テストユーザー」に自分のメールアドレスを追加

### 「リダイレクトURIが一致しません」エラー

- 承認済みリダイレクトURIに `http://localhost:8000/api/youtube-upload/callback` が正確に設定されているか確認

### トークンの有効期限切れ

- `backend/config/youtube_credentials.json` を削除して再認証

## セキュリティ注意事項

⚠️ `youtube_credentials.json` には機密情報が含まれます。

- `.gitignore` に追加済み
- 本番環境では環境変数を使用することを推奨
