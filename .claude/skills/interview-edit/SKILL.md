---
name: interview-edit
description: 撮影済みの対談の raw（Google Drive）から、字幕つきの完成版を頭から通しで作る。raw をつないで書き出し、確認用ファイルを置き、承認済みの字幕と比べ、過程の資産を残すまでを1つのコマンドで進め、工程ライブの画面で見せるときに使う。
---

# 対談の自動編集を通しで作る（raw → 完成版）

1本の対談を、raw から完成版まで同じ手順で作る。手順は**コマンドとファイルだけ**で書いてある。
動かしている AI（Claude Code・Antigravity・Gemini）が何であっても、同じ job ファイルから
同じ手順で同じ動画を作れるようにするため。

人への知らせ（チャット・メール）はこの手順に入っていない。動かしている AI が自分の道具で行う。

## 部品

| 部品 | 場所 | 役目 |
|---|---|---|
| job ファイル | `backend/config/jobs/<名前>.json` | 何を作るか（raw の並び・素材の名前・版・物差し・置き場） |
| 通しの道具 | `backend/edit_job.py` | 手順を頭から通す。済んだ手順は飛ばすので、落ちても続きから |
| 本線 | `backend/agents/pipeline_coordinator.py` | 1回の書き出し（文字起こし → 校閲 → カット → プレビュー → 品質） |
| 校正台帳 | `backend/config/reviews/<素材>.json` | 人の直し。使い方はスキル `caption-review` |
| 工程ライブ | `process_live.html`（このフォルダ） | 置き場の `live/status.json` を15秒ごとに読み、手順を時間の軸に並べる画面 |

## job ファイル

```json
{
  "name": "raw4_repro_20261018",
  "label": "人が読む名前",
  "raw": {"folder": "<収録ID>", "parts": ["つなぐ順のファイル名.mp4", "..."]},
  "material": "raw4_concat.mp4",
  "versions": [
    {"key": "zero", "label": "ゼロからの版"},
    {"key": "ledger", "label": "朱を足した版", "review": "backend/config/reviews/<素材>.json"}
  ],
  "approved": "<物差しにする書き出しの字幕>.subtitles.json",
  "out": "/mnt/project-files/outputs/<名前>"
}
```

- `raw.folder` は raw のフォルダ（`10_raw`・環境変数 `AVS_RAW_DRIVE_FOLDER_ID`）の中の**収録ID**（例 `20250922_久木田ヒロノブ`）。
  置き場の決まりはスキル `drive-layout`。null は raw のフォルダそのもの（決まりの前の並び）
- `raw.parts` は Drive に出ている名前どおりに書く（`python -m backend.raw_source --list` で確かめる）
- `versions` は上から順に書き出す。最初の版は作業場が空なのでキャッシュ無し（AI を全部呼ぶ）。
  後の版は同じ素材のフォルダで走るので、最初の版の AI の出力をそのまま使う（台帳だけが違う版を比べられる）
- `approved` が無ければ比べる手順は飛ぶ

## 手順

すべてリポジトリの根で、`PYTHONPATH=./backend:.` をつけて動かす。

### 1. 始める前に確かめる（AI を呼ばない・無料）

```
python -m backend.edit_job check <名前>
```

道具（ffmpeg・ffprobe）・台帳・キー・実行が書き換えるファイルが戻っていること・空き・予算・
今日の無料枠を見る。1つでも欠けていれば終了コード 1 で、何が足りないかが出る。

### 2. 工程ライブの画面を開く

`process_live.html` を Artifact で公開する。capabilities は `{files: {project: "<プロジェクトの chan_ id>"}}`。
URL の末尾に `#<名前>` をつけると、その作業を映す（無ければ `raw4_repro_20261018`）。
画面は読むだけで、共有フォルダの `outputs/<名前>/live/status.json` を15秒ごとに読み直す。

### 3. 通す（ここで課金の可能性がある）

```
python -m backend.edit_job run <名前>
```

- 長い（キャッシュ無しだと43分の素材で AI を約410回呼ぶ。1日の無料枠（flash-lite 500回）の大半を使う）。裏で流して `status` か工程ライブで見る
- 書き出しの手順の前に毎回、無料枠・予算・空きを確かめ、足りなければ1回も API を呼ばずに止まる
- 本線が書き換えるファイル（`proper_nouns.json`・`usage_data.json`・`daily_usage.json`）は、書き出しの後に必ず戻す
- 落ちたら、出た理由を直してからもう一度 `run`。済んだ手順は飛ばす

### 4. 途中で決めたことを残す

```
python -m backend.edit_job note <名前> "なぜそうしたか"
```

モデルを待った・続きから始めた・枠が戻るまで止めた、など。工程ライブの「判断の記録」と時間の軸の旗に出る。

コードを直した後に同じ素材で作り直すときは、その手順から後をやり直す形に戻して `run` する:

```
python -m backend.edit_job redo <名前> edit:zero "なぜやり直すか"
```

作業場の AI の出力はそのまま使うので、API はほとんど呼ばない。前の確認用ファイルは置き場の
`previous/<時刻>/` に移して残す。理由は工程ライブの「判断の記録」に出る。

### 5. 見る

```
python -m backend.edit_job status <名前>
```

置き場（`out`）にできるもの:

- `<版>/first3.mp4`（3分版）・`full360.mp4`（全編 360p 版）・`contact.jpg`（一覧画像）・`review_captions.json`（レビュー画面の控え。
  機械の要確認には、ほかの聞き取りの字の候補が付いている。人の見方はスキル caption-review の「人の手間を最小にする流れ」）
- `<版>/standards.txt`（編集の決まりの点検。❌ があれば人に見せる前に直す。決まりと直し方はスキル `edit-standards`）
- `<版>/compare.txt`（物差しとの違い）。違いは「台帳の直しが当たらなかった所」と「AI が前と違う字を書いた所」に分かれる
- `assets/`（AI の出力・字幕データ・記録）と `assets.json`（役目・sha256・残すか一時か）

確認用ファイルは置いた後に照合してある（mp4 は映像と音声のハッシュ、他は sha256）。

### 6. 控えから作り直す（API をほとんど呼ばない再現）

承認した書き出しは「raw + AI の控え + 校正台帳 + コード」で同じ字幕に作り直せる。
2026-10-19 に 61回目を 60回目の控えから作り直し、字幕は1字も違わず品質も同じ 91 だった（API は1回）。

1. 空のフォルダに素材を置く（`ln` のハードリンクなら容量を使わない）
2. 控え（`_gemini_*`・`_proofread_*`・`_align_rz_*`）をその隣に写す。控えは置き場の `assets/` か
   `cache/<回>/` にある。写したら sha256 で照合する。映像の切り替わり（`_shots_*`）は毎回同じに作れるので要らない
3. 承認したときの台帳で書き出す:

```
PYTHONPATH=./backend:. python -m backend.agents.pipeline_coordinator <フォルダ>/<素材>.mp4 \
    --transcriber gemini --review backend/config/reviews/<素材>.json
```

4. 承認した字幕と比べる（「字幕は承認したものと同じです」と出れば再現できている）:

```
PYTHONPATH=./backend python -m backend.subtitle_engine.review_sheet compare <承認>.subtitles.json <作り直し>.subtitles.json
```

- 書き出しの後、本線が書き換えるファイルを戻す（手順 3 と同じ）
- 校閲の控えの鍵には、その行に掛かる辞書の項目が入る。全体の辞書（`backend/branding/proper_nouns.json`）を
  変えると、掛かる行だけ校閲を呼び直す。違いが出たらまずそこを見る
- 違いが出たら、caption-review の手順 6 と同じく「台帳が当たらなかった所」と「AI が前と違う字を書いた所」に分ける

### 7. 承認したら編集を固定する

人が承認した版は、スキル caption-review の手順 7（`edit_lock make`）で固定し、置き場の `assets/` に置く。
固定があれば、AI の控えが無くても、コードが変わっても、raw から同じ字幕の動画を作り直せる（`edit_lock render`・AI を呼ばない）。
手順 6 の「控えから作り直す」は、コードの直しが承認した字幕を変えないかを確かめるために使う。

## 品質の基準

字幕・カットの品質の基準は、スキル `edit-standards` の決まりの台帳（`backend/config/edit_standards.json`）にある。
北原さんがチャットで出した指示（句読点・つなぎ言葉・あいさつはノーカット など）と、書き出しの失敗から
できた決まりで、本線がもう守っている。別の対談でもチャットの指示はいらない。
新しい指摘や失敗が出たら、同じスキルの「指示と失敗のサイクル」で決まりに足す。

## 辞書と台帳の分け方

- **どの素材でも正しい直し**（ゲストのお名前・社名の聞き違い）は全体の辞書に入れる。台帳の無いゼロからの版にも効く
- **その素材でだけ誤りになる直し**（「剣先」は普通の言葉なので、全体で「剣閃」にすると他の素材を壊す）は台帳の `glossary` に残す

## AI の工程を誰がやるか

いまは本線が **Gemini API**（無料枠の段）を呼ぶ。段とモデルは `backend/model_config.json` が正典で、
`python -m backend.model_policy --show` で見られる。pro（課金）にはユーザーの指示が無い限り上げない。

動かしている AI 自身が文字起こしや校閲を受け持つ形（API を呼ばない形）は、まだ無い。
足すときは本線の工程ごとのキャッシュ（`_gemini_*`・`_proofread_*`）と同じ形のファイルを
作業場の素材のフォルダに置けば、本線はそれを使って先へ進む。

## 守ること

- **課金**: `run` だけが API を呼ぶ。1円でも請求されうるものは、承認された予算（`.claude/budget.json`）の範囲だけで行う
- raw は読むだけ（読み取り専用のトークン）。Drive に書かない
- 作業場（`pipeline_work/jobs/<名前>/`）は git の外。キャッシュを消す前に `assets/` が置き場にあることを確かめる
- 確認用ファイルをすべて差し替えたことを確かめてから、人に知らせる
