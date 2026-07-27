---
description: 動画編集の意思決定ごとにプレビュースクリーンショットを生成・確認するワークフロー
---

# Progressive Preview ワークフローガイド

## 概要
「見てから決める。決めたら見せる。」

全ての編集意思決定は視覚的エビデンスに基づいて行い、結果も視覚的に報告する。

---

## 発動タイミング

### 1. 事前確認（時間のかかる処理の前）
```python
from progressive_preview import ProgressivePreview

preview = ProgressivePreview(session_id="my_session")

# 10秒サンプルでプレビュー
sample = extract_sample(input_video, duration=10)
processed_sample = apply_crop(sample, settings)

preview.snapshot_step("crop_preview", sample, processed_sample, num_samples=3)

# → HTMLレポートで承認確認してから本処理へ
```

### 2. 事後報告（処理完了後）
```python
# 本処理完了後
full_output = apply_crop(input_video, settings)

preview.snapshot_step("crop_complete", input_video, full_output, num_samples=5)
```

### 3. 即時確認（軽量だが意思決定を伴う処理）
```python
# テロップ位置変更など
output = adjust_telop(input_video, position="bottom")

preview.snapshot_step("telop_position", input_video, output, num_samples=1)
```

---

## レポート確認

// turbo
1. HTMLレポートをブラウザで開く（自動生成: `backend/temp/previews/{session_id}/preview_report.html`）
2. Before/After比較画像を確認
3. 「承認」または「修正要求」を選択
4. 承認されたら次の処理へ進む

---

## API経由での使用

### セッション作成
```bash
curl -X POST http://localhost:8000/api/preview/session -H "Content-Type: application/json" -d '{"session_id": "my_session"}'
```

### ステップスナップショット
```bash
curl -X POST http://localhost:8000/api/preview/step -H "Content-Type: application/json" -d '{
  "session_id": "my_session",
  "step_name": "crop",
  "before_video": "path/to/before.mp4",
  "after_video": "path/to/after.mp4"
}'
```

### レポート取得
```
ブラウザで http://localhost:8000/api/preview/report/my_session にアクセス
```

---

## 適用対象処理

| 処理 | プレビュータイミング |
|---|---|
| crop設定 | 事前（10秒サンプル） + 事後 |
| ロゴオーバーレイ | 事後 |
| テロップ追加 | 即時 |
| 字幕焼き込み | 事前（10秒サンプル） + 事後 |
| カラーグレーディング | 事後 |
| 最終結合 | 事後（開始/25%/50%/75%/終了の5枚） |

---

Northern Light 2.0
