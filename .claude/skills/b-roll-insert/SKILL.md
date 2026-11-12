---
name: b-roll-insert
description: 対談の完成版に、話に合った絵（色紙・作品・写真・資料）を差し込む案を字幕から自動で出し、北原さんが承認した分だけ入れた版を書き出す（AI なし・0円）。絵が無い言葉は「素材待ち」の一覧にする。目視OKの完成版ができた後、番組の飾り（episode-finish）の前後で使う。
---

# B ロール（画像インサート）

道具は `backend/program_package/inserts.py`。案の置き場は `backend/config/inserts/<収録ID>.json`。

## 流れ

1. **案を出す**（字幕は承認済みの固定 lock、地図は `vision scan` の結果）

   ```
   python -m backend.program_package.inserts propose backend/config/episode/<収録ID>.json \
       --captions LOCK.json --map 地図.json [--materials 素材の一覧.json]
   ```

2. **一覧の絵を北原さんに見せる**（`sheet --video 完成版.mp4 --out 案の一覧.jpg`）。素材待ちの一覧も一緒に渡す
3. **北原さんがチャットで選んだ分を控える**（`approve` / `reject`。`--by 北原 --evidence "<日時と言葉>"`）。
   AI の名前では控えられない。案の置き場が変わるのでコミットする
4. **承認した分だけ入れた版を書き出す**（`render --video 完成版.mp4 --out …`。OP 付きの版なら `--offset <OP の長さ>`）。
   できた版を 40_完成 の投稿する棚に置くには、いつもどおり `program_gate` の承認が要る

## 人が書く所（案の置き場の `setup`）

| 項目 | 意味 |
|---|---|
| `board_keywords` | 収録の中で大きく映った色紙・作品を指す言葉（例 `["縁"]`）。地図から絵を自動で拾う |
| `recording_sources` | 収録の中のほかの絵（`id`・`at`・`crop`・`keywords`） |
| `extra_keywords` / `skip_keywords` | 素材待ちに足す言葉・出さない言葉 |
| `max_per_source` | 1つの絵を出す回数（既定 2） |

## 素材の一覧（`--materials`）

```json
[{"id": "kensen", "title": "フォント剣閃の見本", "file": "kensen.png", "keywords": ["剣閃"],
  "rights": "permitted", "people": "none"}]
```

- `rights`: `own`（自社の物）か `permitted`（許可を得た物）だけ使う。他社の広告・商品・アニメの絵は `third_party`
- `people`: `none`（写っていない）か `consented`（了解済み）だけ使う
- `ai_generated: true` と動画（`kind: "video"`）は案に出さない
- 書いていない物は「未確認」として外す。外した理由は案の置き場の `excluded` に出る

## 決まり

- 始まりと終わりは字幕の切れ目（4〜8秒）。場面の切れ目・章の見出し・テロップ・名前のポップとは重ねない
- 小窓は頭に掛からず字幕の帯に入らない所。置ける壁が無ければ全画面（字幕の帯は残す）
- 収録の中の絵は、映った後の話にだけ出す。差し込みどうしは 20 秒あける
- 承認の後に時刻・置き場・絵が変わった案は入らない（もう一度見てもらう）

## まだ無いもの（後送）

- Drive のラベルから素材の一覧を作る（今は一覧を手で渡す）。動画の B ロール。絵の下の説明文
- 本線の書き出し（`episode.py`）に載せる — V5。`inserts.shows()` が飾りと同じ形を返す
