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
4. **承認した分だけ入れた版を書き出す。** ふつうは通しの道具で、飾り・曲と一緒に入れる:

   ```
   python -m backend.program_package.finish backend/config/episode/<収録ID>.json --version v68 --out OUT \
       --music-dir 曲の置き場 --map 地図.json --review
   ```

   `episode.py` も承認済みの案を自動で重ねる（案の置き場が無い回・`"inserts": false` の回は何もしない）。
   出来上がった版にだけ後から重ねたいときは `inserts render --video … --offset <OP の長さ>`。
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
  "rights": "permitted", "people": "none", "ai_generated": false}]
```

- `rights`: `own`（自社の物）か `permitted`（許可を得た物）だけ使う。他社の広告・商品・アニメの絵は `third_party`
- `people`: `none`（写っていない）か `consented`（了解済み）だけ使う
- `ai_generated: false` と書いた物だけ使う（`true` も未記入も外す）。動画（`kind: "video"`）は案に出さない
- 書いていない物は「未確認」として外す。外した理由は案の置き場の `excluded` に出る

## 決まり

- 始まりは字幕の出だし、終わりは字幕の切れ目（4〜8秒。切れ目で終われるなら 8.5 秒まで。4 秒に満たない字幕は 4 秒まで残す）。場面の切れ目・章の見出し・テロップ・名前のポップとは重ねない
- 小窓は頭に掛からず字幕の帯に入らない所。置ける壁が無ければ全画面（字幕の帯は残す）。地図（`--map`）が無ければ小窓にしない（全画面だけ）
- 案の名前は「絵の名前-分秒」（例 `board-3041`）。素材を足しても変わらない
- 収録の中の絵は、映った後の話にだけ出す。差し込みどうしは 20 秒あける
- 承認の後に時刻・置き場・絵が変わった案は入らない（もう一度見てもらう）。決まりを直して出し方だけ変わった時は、人が見て決めた方の案を残す
- 書き出しの前に止まる所: 承認の後に飾り（見出し・テロップ・名前）が動いて重なった／字幕（lock）が案を出した時と違う（置き場の `base` と比べる）
- `finish` の頭の確かめは差し込みも見る。地図が無ければ「確かめていない」と控えに出る

## 仕組みで防いでいない所（人の約束）

- 案の置き場と承認者の台帳を手で書き換えること。`rights`・`people`・`ai_generated` は人が書いた申告
- 頭を避ける確かめは地図の精度まで。収録の中の絵は、書き出しに渡した映像から切り出す
- 曲なし（`--no-music`）でも「承認待ち」になる（控えに「曲は入っていない」と出る）

## まだ無いもの（後送）

- Drive のラベルから素材の一覧を作る（今は一覧を手で渡す）。動画の B ロール。絵の下の説明文

## 曲（`backend/program_package/music.py`・曲の台帳 `backend/config/music.json`）

- 台帳に、番組ごとの OP・BGM・ED の曲と出どころを書く。曲のファイルはリポジトリに置かない（`--music-dir`）
- `music plan AUDIO.json --program … --music-dir …` が remix の指定を作る。OP の使い始めは、曲の山の入りを番組名の出だしに合わせる
- 出どころの無い曲・ファイルの決まっていない曲では、書き出す前に止まる
- 打ち合わせで決めた音量をそのまま再現したいときは、`finish --audio AUDIO.json` でその指定を渡す
