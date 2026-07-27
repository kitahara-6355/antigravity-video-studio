# OBS 自動録画セットアップガイド

## 📋 前提条件

- ✅ OBS Studio 28.0以上がインストール済み
- ✅ Python 3.8以上
- ✅ バックエンド・フロントエンドが起動中

---

## 🚀 セットアップ手順

### Step 1: OBS Studio の起動と設定

1. **OBS Studio を起動**

2. **WebSocket サーバーを有効化**:
   - メニュー: `ツール` → `WebSocketサーバー設定`
   - ☑️ `WebSocketサーバーを有効にする` にチェック
   - サーバーポート: `4455`（デフォルト）
   - 認証: パスワードなしでOK（ローカル環境）
   - `適用` → `OK`

3. **出力設定の確認**:
   - メニュー: `設定` → `出力`
   - 録画フォーマット: `mp4`
   - 出力先: 任意の場所（例: `C:\Users\PC_User\Videos\OBS`）
   - エンコーダ: `x264` または `NVENC H.264`（GPU使用）
   - `適用` → `OK`

---

### Step 2: Python パッケージのインストール

```powershell
# OBS WebSocket Python クライアント
pip install obsws-python

# ブラウザ自動化
pip install playwright

# Chromium ブラウザのインストール
playwright install chromium
```

---

### Step 3: 録画スクリプトの実行

```powershell
cd C:\Users\PC_User\Desktop\script\video-automation
python record_demo.py
```

**実行されること**:
1. OBS に接続
2. 録画開始
3. ブラウザで Phase 28 テストページを開く
4. Vibrant プリセットを選択
5. プレビュー生成
6. 動画再生（7秒間）
7. 録画停止

**所要時間**: 約30秒

---

## 🎬 録画ファイルの場所

OBS の設定で指定した出力先に保存されます。

確認方法:
1. OBS Studio を開く
2. `ファイル` → `録画を表示`

---

## ❓ トラブルシューティング

### エラー: "OBS接続失敗"
**解決法**:
1. OBS Studio が起動しているか確認
2. WebSocket サーバーが有効か確認
3. ポート 4455 が使用中でないか確認

### エラー: "ModuleNotFoundError: obsws_python"
**解決法**:
```powershell
pip install obsws-python
```

### エラー: "playwright._impl._api_types.Error"
**解決法**:
```powershell
playwright install chromium
```

### 録画ファイルが見つからない
**解決法**:
1. OBS の `設定` → `出力` で出力先を確認
2. OBS のメニュー `ファイル` → `録画を表示`

---

## 🎯 カスタマイズ

### プリセットを変更
`record_demo.py` の L96 を編集:
```python
page.click('button:has-text("cinematic")')  # Cinematic に変更
```

### 録画時間を延長
`record_demo.py` の L110 を編集:
```python
time.sleep(15)  # 15秒間再生
```

### 解像度を変更
`record_demo.py` の L63 を編集:
```python
viewport={'width': 2560, 'height': 1440'}  # 2K
```

---

**Northern Light 2.0**
