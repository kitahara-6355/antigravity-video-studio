---
name: program-style
description: 番組の雰囲気（OP の言葉の現れ方・背景・番組名の締め）を、見本の動画をたくさん並べて北原さんが選ぶだけで決める仕組み。番組共通 OP の資産（横・縦）の作り方と差し替え、選んだ理由をソウル・ナラティブに残すまで。Shorts と本編に共通。
---

# 番組の雰囲気えらび（番組共通 OP と見本）

2026-10-25 に北原さんが決めた制作順と仕組み。手順は**ファイルとコマンドだけ**で書いてある。どの AI が動かしても同じ mp4 が出る。

- 費用は0円。Gemini API も AI の画像・音声の生成も使わない（文字は Google Fonts、絵は numpy と PIL で描く）
- **北原さんは選ぶだけ**。AI は見本を作り、選ばれた形で書き出し、理由を記録する
- 選ぶ前の形は 10-23 に北原さんが OK した形（筆で書き足す・薄紫の光・光が走る）。見本はどれも**薄紫・金・明朝の方向性の中**で変える

## 制作の順番（2026-10-25 北原さん）

1. 投稿用の Shorts を先に仕上げる（スキル `shorts-cut` の手順5「投稿用フォルダ」）
2. **番組共通 OP を単体の動画として作り、資産として別に保存する**（この手順の1）
3. 本編を仕上げる（スキル `episode-finish`）。本編は OP の資産を頭に付けるだけ

OP の質が上がったら、資産の `version` を上げて書き出し、各回の本編を書き出し直せば全部の OP が差し替わる。

## 入力

| もの | 場所 |
|---|---|
| 番組の指定 | `backend/config/program/<番組名>.json`（見本 `examples/美麗の書道対談.json`）。番組名・言葉・秒数・曲・色・`style`・`version` |
| 曲 | 指定の `music.path`。出所のはっきりした曲だけ。仮の曲は `provisional: true`（出力名に「_仮曲入り」） |
| フォント | `python -m backend.program_package.thumbnail --fetch-fonts`（初回だけ） |

## 手順

### 1. 番組共通 OP の資産を書き出す

```
python -m backend.program_package.opening backend/config/program/<番組名>.json --out OUT
```

- `番組OP_<version>_横.mp4`（1280x720・本編用）と `番組OP_<version>_縦.mp4`（1080x1920・Shorts 用）が出る。曲入り
- 縦は文字を1.3倍にし、画面に入らない言葉は空白の所で2行に分ける
- Drive の `30_AVS_作業/番組資産/<番組名>/番組OP_<version>/` へ（`python -m backend.asset_store put OUT --to "番組資産/<番組名>/番組OP_<version>"`）。
  20_素材 は北原さんが置く所（AI は読むだけ）なので、AI が作る OP はここに置く。file id は指定の `asset` に控える
- 本編の指定（`backend/config/episode/<収録ID>.json`）の `program` が番組の指定を指す。`program_asset` に資産の mp4（横）を書くとそれをそのまま使う。null ならその場で作る

### 2. 見本を作る

```
python -m backend.program_package.style_picker backend/config/program/<番組名>.json --out DIR
```

- 軸ごと（`opening.CHOICES`）に、**ほかは今の形のまま、その軸だけを変えた**8秒の見本（言葉1枚＋番組名）と静止画を作る
- おすすめの組み合わせ（`style_picker.PRESETS`）は OP 全体（15秒・曲入り）の見本にする
- 見本は 640 幅・軽い mp4（1本 50〜300KB）。全部で約2MB・CPU で約4分
- 静止画は、現れ方なら出てくる途中、ほかは番組名の締めが見える所

### 3. 選択画面で北原さんに選んでもらう

- 見本を `m/` に置いた1枚のページ（Artifact。capabilities `db`・`user`）を出す。見本 `examples/選択画面.html`
- 並べ方: **まとめて選ぶ（組み合わせ）→ 軸ごと**。カードを押すと選ばれ、下の帯に今の組み合わせが出る。「ひとこと」に理由を書ける
- 「この形で決める」で db の `picks/latest`（と履歴 `picks_log`）に `reveal`・`background`・`finish`・`note`・`at` が入る
- 北原さんはスマホで見るので、1列でも崩れないこと。音は押してからしか鳴らない（自動再生は無音）

### 4. 選ばれた形を書き込み、記録する

1. Claude が `ArtifactData` で `picks/latest` を読み、JSON に保存する
2. `python -m backend.program_package.style_picker backend/config/program/<番組名>.json --apply PICK.json`
   - 指定の `style` に書き、`history` に1行足す
   - **ソウル・ナラティブ**（憲法 §5.2・§10）: `DecisionLogger.record_decision`（target_type `program_style`・理由＝ひとこと・変えた軸をタグ）→ `sync_to_soul_narrative()` で `evolution_log.json` に入る。次の案はこの記録から作る（同じ質問を繰り返さない）
3. `version` を上げて手順1で資産を書き出し直し、本編・Shorts に当てる

## 選べる軸（2026-10-25 時点）

| 軸 | 選択肢 | 元にした考え方 |
|---|---|---|
| `reveal` 言葉の現れ方 | brush 筆で書き足す / rise 行ごとに浮き上がる / blur 焦点が合う / stagger 一文字ずつ跳ねる | kinetic-typography の4つの定番（mask・blur・clip wipe・char stagger）を書道に寄せた |
| `background` 背景 | glow 中央が明るい / drift 光が漂う / washi 和紙の繊維 / gold_dust 金の粉 | motion-background: 文字より目立たない・ゆっくり・低いコントラスト |
| `finish` 番組名の締め | sweep 光が走る / seal 朱の落款 / brush_line 金の筆線 / halo 金の光が灯る | motion-art-direction:「見せ場は1つだけ」 |

軸を足すときは `opening.CHOICES` に1つ足し、`frames()` に描き方を足し、テスト（`test_every_style_draws_frames_without_errors`）が通ることを確かめる。

## 演出の決まり（調べて分かったこと。二次情報）

- **動きの言葉は1つに揃える**（motion-art-direction）。イージングは1種類（入りは減速）、時間の単位を決めてその倍数にする。OP・章の見出し・Shorts のキャッチで同じ現れ方を使うと「同じ番組」に見える
- 番組の位置は「静か×柔らかい」（Premium: 0.35〜0.6秒・はね返りなし）。跳ねる・速い動きは書道の格に合わない
- 一文字ずつ出すのは短い文に限る。長い文は行ごと・言葉ごとの方が落ち着く
- YouTube の OP は短いほど離脱が少ないとされる（3〜8秒が多い。メーカーのブログの数字で、一次情報ではない）。**今は番組 OP 15秒 → 今回の名場面**の順。名場面を先に出す（つかみ→番組名）案も選べるようにする候補

参考（MIT・2026-10-25 に読んだ）: iart-ai/kinetic-typography-skills・iart-ai/motion-design-skills（motion-art-direction・motion-background）、remotion-dev/skills

## 決まりの経緯

| 日付 | 北原さんの判断 |
|---|---|
| 10-23 | 番組 OP はカット集ではなく文字だけの映像に。背景の斜線なし。言葉は書き足されていく形に |
| 10-23 | 後日、美麗さんの手書きの映像を撮って差し替え、唯一無二の OP にする |
| 10-25 | 制作順: Shorts → 番組共通 OP（資産・Shorts としても）→ 本編。OP は資産として別に保存し差し替えられるように |
| 10-25 | 公開 SKILL.md と他番組を調べ、案をたくさん見せて選ぶだけで雰囲気が決まる仕組みを。Shorts・本編に共通。ナラティブ構想につなげる |
