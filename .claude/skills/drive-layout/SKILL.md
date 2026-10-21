---
name: drive-layout
description: Google Drive の「動画制作」（共有ドライブ「美麗書院_共有データ」）の置き場の決まりを守る。新しい対談の raw や素材を足すとき、AI の作業の資産や完成動画を Drive に置くとき、重複した raw や古い版を 90_保管 へ寄せるとき、置き場が決まりどおりか点検するときに使う。
---

# 動画制作の置き場の決まり（Google Drive）

2026-10-21 に北原さんが承認した構成。正典は `backend/config/drive_layout.json`、
点検と用意は `python -m backend.drive_layout`。経緯と図は構成案
（https://claude.ai/artifact/H24KKV7HAWYn43xxhppn5z ）。

## 構成

共有ドライブ「美麗書院_共有データ」/「動画制作」の下に、工程順に番号を付けた6つ。
各フォルダの中は**収録ID**で分ける。

| フォルダ | 中身 | 入れる人 | AI |
|---|---|---|---|
| 00_使い方 | この決まりの要約1枚 | AI | 書く |
| 10_raw | 撮ったままの動画。`10_raw/<収録ID>/` | 北原さん（撮影後にアップロード） | **読むだけ** |
| 20_素材 | Bロール・インサート画像・OP 映像・ロゴ・BGM。`共通/` と `<収録ID>/` | 北原さん | 読むだけ |
| 30_AVS_作業 | 字幕データ・校正台帳・編集の固定・AI の控え・記録・スキル | AI | 書く |
| 40_完成 | 書き出した動画。`40_完成/<収録ID>/` | AI | 書く |
| 90_保管 | 古い版・重複していた raw。消す日を名前に付けた箱に入れる | 北原さん | 箱を作るだけ |

## 名前の付け方

- **収録ID** = `撮影日_ゲスト名`（例 `20250922_久木田ヒロノブ`）。同じ日の2本目は `_2`。
  確かめる: `python -m backend.drive_layout check-id <名前>`
- フォルダ名に「最新」「テスト中」、単独の「新」を入れない。次の版が出た時点で事実と合わなくなる
- 完成動画は `<収録ID>_v<版>_<用途>.mp4`（例 `20250922_久木田ヒロノブ_v61_確認用360p.mp4`）
- 撮ったままのファイル名（`2025-09-22_16-34-33.mp4`）は変えない。カメラの時刻がつなぐ順の手がかり
- 90_保管 の箱は `<消す日 YYYYMMDD>削除予定_<中身>`（例 `20261121削除予定_重複raw_20250922_久木田ヒロノブ`）
- 30_AVS_作業 の中: 収録の作業は `収録/<収録ID>/<作業>_<YYYYMMDD>`、スキルは `skills/<名前>_v<版>_<YYYYMMDD>`

## 鍵と権限（ここから来る決まり）

| 鍵 | 環境変数 | 権限 | 使う道具 |
|---|---|---|---|
| raw を読む | `ANTIGRAVITY_GOOGLE_TOKEN_JSON` | drive.readonly | `raw_source`・`drive_layout audit/plan` |
| 資産を書く | `AVS_ASSETS_GOOGLE_TOKEN_JSON` | drive.file | `asset_store`・`drive_layout prepare/hold` |

- drive.file は**アプリが作った物にしか触れない。** 人が作ったフォルダ（動画制作・10_raw）の中には書けず、
  raw も動かせない。raw を守るうえではこれが利点なので、広い権限は取らない
- だから AI が書くフォルダは AI が「30_AVS_作業」の中に作り、北原さんが「動画制作」へドラッグで移す。
  移しても名前を変えても、印（appProperties）で見つけ続ける
- **ファイルを動かす・消すのは北原さん。** AI は一覧と手順を出し、前後を md5 で照合する
- 「動画制作」は raw のフォルダ（`AVS_RAW_DRIVE_FOLDER_ID`）の親として id で辿る。名前は見ない
- 環境変数を足した・変えたときは、**新しく始めたセッション**でしか見えない。
  確かめは `create_trigger`（新しいセッション）→ `fire_trigger` で行う（同じコンテナの別エージェントでは確かめられない）

## 手順

すべてリポジトリの根で `PYTHONPATH=.:./backend` をつけて動かす。Drive API は無料。

### 新しい対談を足す

1. 収録ID を決めて `check-id` で確かめる
2. AI 側のフォルダを用意する: `python -m backend.drive_layout prepare --recording <収録ID>`
   （20_素材・40_完成・30_AVS_作業/収録 の下に収録ID のフォルダを作る）
3. 北原さんに頼む: `10_raw` に `<収録ID>` のフォルダを作って raw を入れる（AI は作れない）。
   素材は `20_素材/共通` か `20_素材/<収録ID>` へ
4. raw を確かめる: `python -m backend.raw_source --list --folder <収録ID>`
5. job ファイル（スキル `interview-edit`）の `raw.folder` に収録ID を書く

### AI の作業を残す

- 資産: `python -m backend.asset_store put <手元のフォルダ> --to 収録/<収録ID>/<作業>_<YYYYMMDD>`
  （送った後 md5 を照合する。目録は `--manifest` で共有フォルダへ）
- 並べ直し: `python -m backend.asset_store move <元> --to <先>`（id・md5 は変わらない。空になった元はゴミ箱へ）
- スキル: `skills/<名前>_v<版>_<YYYYMMDD>` へ put

### 重複や古い版を 90_保管 へ寄せる

1. 一覧を出す: `python -m backend.drive_layout plan`。10_raw と同じ md5 の動画を余分とし、
   中身が余分だけのフォルダは一番外側までまとめて、1回のドラッグで移せる単位で出る
2. 箱を作る: `python -m backend.drive_layout hold <中身の名前> [--until YYYY-MM-DD]`（既定は31日後）
3. 北原さんに一覧の物を箱へ移してもらう
4. `audit` で duplicate_raw が消え、10_raw の raw の md5 が変わっていないことを確かめる
5. 消す日が来たら `audit` が hold_overdue で知らせる。**消すのは北原さん。** 消す前に、
   同じ md5 が 10_raw にまだあることを `plan` / `audit` で確かめて伝える

### 点検する

```
python -m backend.drive_layout audit [--json 結果.json]
```

FAIL（終了コード 1）: 工程のフォルダが無い・2つある／raw のフォルダの名前が 10_raw でない／
10_raw の直下に動画がある・収録ID でないフォルダがある／10_raw と同じ動画がほかにある（duplicate_raw）／
10_raw に無い動画が2か所以上にある（duplicate_unkept。どれを raw にするか人が決める）。
WARN: 名前の決まり（最新・テスト中・新）、20_素材・40_完成の名前、90_保管 の消す日が無い・過ぎた。

## 範囲の外

- 「動画制作」の外（例: 「克洋アップロード」）は点検しない。重複を見つけたら知らせるだけ
- 「000_テスト中」のような整理前のフォルダの振り分けは、一覧を読んで案を出す（動かすのは北原さん）
