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
  "raw": {"folder": null, "parts": ["つなぐ順のファイル名.mp4", "..."]},
  "material": "raw4_concat.mp4",
  "versions": [
    {"key": "zero", "label": "ゼロからの版"},
    {"key": "ledger", "label": "朱を足した版", "review": "backend/config/reviews/<素材>.json"}
  ],
  "approved": "<物差しにする書き出しの字幕>.subtitles.json",
  "out": "/mnt/project-files/outputs/<名前>"
}
```

- `raw.folder` は raw のフォルダ（環境変数 `AVS_RAW_DRIVE_FOLDER_ID`）の中の素材のフォルダ名。null ならそのフォルダそのもの
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

### 5. 見る

```
python -m backend.edit_job status <名前>
```

置き場（`out`）にできるもの:

- `<版>/first3.mp4`（3分版）・`full360.mp4`（全編 360p 版）・`contact.jpg`（一覧画像）・`review_captions.json`（レビュー画面の控え）
- `<版>/compare.txt`（物差しとの違い）。違いは「台帳の直しが当たらなかった所」と「AI が前と違う字を書いた所」に分かれる
- `assets/`（AI の出力・字幕データ・記録）と `assets.json`（役目・sha256・残すか一時か）

確認用ファイルは置いた後に照合してある（mp4 は映像と音声のハッシュ、他は sha256）。

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
