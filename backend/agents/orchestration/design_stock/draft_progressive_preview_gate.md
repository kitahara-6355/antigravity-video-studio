# 設計ドラフト: 視覚的2段階承認ゲート (IMP-PREVIEW-GATE)

## 概要
憲法第9条（視覚確認プロトコル：Progressive Preview）およびビジョンバックログ D-16 を完全にクリアするため、動画エンコードや字幕焼き込みなどの時間とリソースのかかる「不可逆的・高負荷処理」の前にパイプラインを一時サスペンド（待機）し、ユーザーが視覚的エビデンス（Before/After 画像カルーセル）を確認して承認するまで処理をブロックする「2段階承認ゲート」の設計ドラフト。

## 1. 2段階承認シーケンス

```
[Pipeline実行] 
     │
     ▼
[Stage: プレビュー生成] ── 開始/中間/終盤の3-5点から「字幕ありフレーム」をサンプリング
     │
     ├─► ffmpeg / Pillow で [Before / After] 横並び画像を生成
     ├─► WebSocket でフロントエンドに「承認要求」とHTMLカルーセルをプッシュ
     │
     ▼
[Pipeline Suspend (待機状態)] 
     │
     ├── ユーザーが [👍 承認 (Gavel)] を押す ────► [Pipeline Resume (再開)] ──► レンダリング実行
     │
     └── ユーザーが [👎 却下 (Veto)] を押す ────► パラメータ修正指示 ──► プレビュー再生成へ戻る
```

---

## 2. コア機能仕様

### ① 自動フレームサンプリング (`frame_sampler.py`)
*   容量の大きい動画全体を出力する前に、構成（`edit_config.json`）および SRT ファイルを解析。
*   文字起こしの「発話区間（字幕が実際に表示されるキーフレーム）」から、開始、中間、終盤の最低3つのフレームインデックスをサンプリングする。
*   シーンチェンジ（トランジション）などの「エフェクト適用ポイント」も優先的にサンプリング対象に含める。

### ② Before/After 画像合成 (`preview_generator.py`)
*   サンプリングしたフレームに対して：
    *   **Before**: RAW動画の元フレーム。
    *   **After**: 色補正（LUT）、テロップ字幕、およびロゴウォーターマークを適用（合成）したフレーム。
*   Before と After の画像を左右（または上下）に結合し、比較用画像を生成する。
*   軽量化のため、プレビュー画像は最大1080p（推奨は720p）にクランプする。

### ③ WebSocket 待機ゲート (`pipeline_suspend_gate.py`)
*   パイプラインが本番書き出しに入る前に、状態を `Awaiting_Approval`（承認待ち）に変更し、ループの処理をブロックする。
*   WebSocket を介してフロントエンドに `PREVIEW_READY` イベントと画像を送信する。
*   ユーザーが承認（`Approve`）または却下（`Reject`）を返すまで、状態を保持（タイムアウトは最大30分とし、タイムアウト時は安全のため自動サスペンドのまま処理を保留、または設定に基づき一時停止を維持する）。

### ④ プレビューカルーセル UI (`ProgressivePreviewCarousel`)
*   フロントエンド上で、生成されたBefore/After画像をスライド形式（カルーセル）で確認できる。
*   ユーザーが直感的に「字幕の位置」「文字のフォント」「色彩の仕上がり」を確認できるようにする。
*   画面下に「ガベル（承認の小槌）ボタン 🔨」と「却下＆修正指示（Veto）ボタン」を配置。

---

## 3. バックエンド API および WebSocket イベント

*   **WebSocket 送信 (Server -> Client)**:
    ```json
    {
      "event": "PREVIEW_READY",
      "data": {
        "video_id": "v-12345",
        "previews": [
          {"stage": "color_grading", "before": "data:image/jpeg;base64,...", "after": "data:image/jpeg;base64,..."},
          {"stage": "subtitle_burn", "before": "data:image/jpeg;base64,...", "after": "data:image/jpeg;base64,..."}
        ]
      }
    }
    ```
*   **API 受信 (Client -> Server)**:
    *   `POST /api/pipeline/approve` : `{"video_id": "v-12345", "action": "approve"}` -> 待機ゲート解除、エンコード再開。
    *   `POST /api/pipeline/reject` : `{"video_id": "v-12345", "action": "reject", "feedback": {"subtitle_font_size": 18}}` -> 構成パラメータ修正、再プレビュー生成。

---

## 4. セルフチェックリスト / 完了条件
- [ ] 字幕のあるフレームを狙ってサンプリングする `frame_sampler.py` の実装
- [ ] Before/After 画像を結合・生成する `preview_generator.py` の実装
- [ ] WebSocket で処理をサスペンド・レジュームする `pipeline_suspend_gate.py` の実装
- [ ] フロントエンドでの Before/After 比較カルーセルUIの実装
- [ ] 全フィットネス関数テストが PASS すること
