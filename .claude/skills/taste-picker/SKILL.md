---
name: taste-picker
description: チャンネル主（美麗さん）の好みを、スマホの二択（同じ場面で曲だけ違う2本を見比べて押す）で集め、順位と「好みカルテ」にする。OP・ED・対談中の曲を選び直すとき、美麗さんに好みを聞きたいとき、集まった答えを読んで次の案を作るときに使う。
---

# 好みえらび（二択で好みを学ぶ）

2026-11-13 北原さん承認（提案書 https://claude.ai/artifact/1rJiryrxTb4CuVEZ9pqDgc ）。
美麗さんに曲を「選んで」もらうのをやめて、**本物の場面に当てた 2 本を「比べて」もらう**。
答えは全部残し、好みカルテとして育てる。北原さんの手を借りずに、美麗さんが 1 人で回せることが目的。

- 費用は0円。AI を呼ばない。ページは info@ の Apps Script（clasp で送る）、答えは Drive のシート
- 比べる見本は曲の大きさをそろえる（大きい方を良いと感じる癖を消す）。曲名は結果の画面まで見せない
- 両方を番組名のところ（11 秒）まで聞くと押せるようになる。曲は番組名で山が来るように合わせてある
- YouTube などの音は落とさない・解析しない（規約）。候補は出どころの分かる無料曲だけ
- 選んだ曲が後で規約に触れると分かったら（2026-11-13 北原さん）: 好みは確定しているので、
  似た曲に差し替える・似た曲を作る・特徴を言葉にして自主制作する、のどれかで好みを反映し続ける。
  そのために、見本の控えに曲の特徴（速さ・明るさ・音の密度・拍の安定・盛り上がりの差）を残す

## 部品

| 部品 | 場所 |
|---|---|
| 見本を作る・順位を出す | `python -m backend.program_package.taste`（clips / put / report） |
| 二択のページ | `.claude/skills/taste-picker/webapp/`（Code.js・Index.html・appsscript.json） |
| 好みカルテ | `backend/config/taste/<人>.json`。行は 未確認 → そう／違う（本人が押す。AI は そう にしない） |
| Drive の置き場 | `30_AVS_作業/好みカルテ/<名前>/候補曲`（曲と sources.json）・`/見本`（taste_pack.json と mp4・シート「好みの答え」） |

## 手順

### 1. 候補曲を集める（PC）

クラウドからは opentracks.com・dova-s.jp に届かない（プロキシが拒否）。PC の Remote Control で
OpenTracks（旧 DOVA）から MP3 を落とし、`候補曲/` に置く。`sources.json` に曲ごとの
file・title・artist・page_url・track・page_tags・creator_terms（クレジット要否・収益化可否）・md5 を書く。
作曲者の条件で収益化できない曲は落とさず `skipped` に理由を書く。

候補は 12 曲前後。**方向がばらけるように**選ぶ（ピアノ／和楽器／ジャズ・ボサノバ／弦や管、速め／ゆっくり）。
前回の決定曲と、前回だめだった曲も 1 曲ずつ入れておくと、好みの軸が分かりやすい。

### 2. 見本を作って置く（クラウドでも PC でも）

```
python -m backend.program_package.taste clips --base 番組OP.mp4 --songs 候補曲 --sources 候補曲/sources.json \
    --program backend/config/program/美麗の書道対談.json --out OUT --name OP曲えらび_YYYYMMDD
python -m backend.program_package.taste put OUT --dest 好みカルテ/OP曲えらび_YYYYMMDD/見本
```

- 番組 OP の絵は資産の `番組OP_<version>_横`（音は捨てる）。Drive id は番組の指定の `asset`
- 1 本 15 秒・幅 640・数百 KB。12 本でクラウド 1 分ほど
- 出力の各行で「番組名で何 dB 上がるか」を見る。0 に近い曲は山が合っていない
- `put` は drive.file のトークンで書くので、**PC で作ったフォルダ（候補曲の親など）は見えない**（同じ名前のフォルダが別にできる）。
  候補曲と同じ親に置くときは、Drive 全体のトークン（AVS_DRIVE_ORGANIZER_TOKEN_JSON）で親の id を指して置く。
  2026-11-13 の初回はこの方法で `OP曲えらび_20261113/見本`（id 1UTCkiyVpE5hfnIMVieLc6DbFbWeuYc_W）に置いた
- 速さ（bpm）は 70〜150 に寄せる（拍の細分を倍の速さと数えない）。ページの BPM と照らすと New Departure 95 → 92、South Wind 120 → 120

### 3. 美麗さんに送る

ページの URL に `?pack=<見本フォルダの id>` を付けて、北原さんから美麗さんに送ってもらう。
info@ のドメイン（kitahara-birei.com）の Google アカウントでログインしたスマホで開く。
10 回で終わる（5 分ほど）。結果の画面で上位 3 曲が出て、「この曲に決める」を押せる。

### 4. 答えを読む

シート「好みの答え」を CSV で書き出し（読み取りトークンの Drive export）、

```
python -m backend.program_package.taste report --pack OUT/taste_pack.json --answers 答え.csv --karte 美麗
```

- 順位は Bradley–Terry（引き分けは半分ずつ・答えの少ない曲は真ん中に寄せる）
- 「勝った曲に共通する特徴」は、はっきり差のある組が 4 つ以上・7 割以上そろったときだけ言う
- 一言はそのままカルテの行にする。どれも 未確認 で足す。美麗さんに見せて そう／違う を押してもらうまで決まりにしない
- 決めた曲（decided）があれば、曲の台帳 `backend/config/music.json` を直す前に北原さんに一言確かめる

### 5. 公開（clasp・PC）

PC の `Desktop\script\clasp\taste-picker` に webapp/ の 3 ファイルを写し、`clasp push -f` →
初回は `clasp deploy`、以後は `clasp update-deployment <id>`。初回だけ info@ で許可が要る（北原さん）。
info@ の clasp は Workspace の再認証で切れることがある（invalid_rapt → 北原さんが `clasp login`）。

## この先（提案書の段）

2. 好きの種（好きな動画・曲の URL や曲名を送る入口）を同じページに足す
3. 見ながらひとこと（30 秒・60 秒の見本に秒付きのボタン）。対談中の曲の音量・差し込みの絵・字幕の切れ目へ
4. カルテから次の回の最初の案を作る
