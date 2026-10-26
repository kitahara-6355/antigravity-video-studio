---
name: program-style
description: 番組の雰囲気（色・書体・縦書き・言葉の現れ方・背景・番組名の締め）を、絵コンテの画像をたくさん並べて北原さんが選び、注文カードで手直しを足すだけで決める仕組み。番組共通 OP の資産（横・縦）の作り方と差し替え、選んだ理由をソウル・ナラティブに残すまで。Shorts と本編に共通。曲は最後に当てる。
---

# 番組の雰囲気えらび（番組共通 OP と見本）

2026-10-25 に北原さんが決めた制作順と仕組み。手順は**ファイルとコマンドだけ**で書いてある。どの AI が動かしても同じ mp4 が出る。

- 費用は0円。Gemini API も AI の画像・音声の生成も使わない（文字は Google Fonts、絵は numpy と PIL で描く）
- **北原さんは選ぶだけ**。AI は見本を作り、選ばれた形で書き出し、理由を記録する
- 選ぶ前の形は 10-23 に北原さんが OK した形（薄紫と金・明朝・中央・筆で書き足す・光が走る）
- **案は幅広く**（10-26 北原さん「ほぼ同じパターンから選ぶ方式ではなく、様々なパターンから」）。色・書体・置き方まで変える
- **画像で先に決め、動画と曲は後**（10-26 北原さん）。絵コンテは1枚ずつ描けるので 16案＋注文160枚が約50秒

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

### 2. 絵コンテを作る

```
python -m backend.program_package.style_picker backend/config/program/<番組名>.json --out DIR
```

- 方向（`style_picker.DIRECTIONS`・16案）ごとに、絵コンテ `<id>-board.jpg`（2x2: 書き足す途中 → 言葉が出そろう → 番組名が出る途中 → 締め）と縦の画面の1枚 `<id>-v.jpg`
- 注文カード（`style_picker.ORDERS`・10枚）を、その方向に当てた1枚ずつ `<id>-orders.jpg`（5x2 のまとめ画像）。選択画面で押すとすぐ見比べられる
- `board.json` に方向・注文・4コマの名前。音は無し。CPU で約50秒（4並列）
- 1枚ずつ描くのは `opening.painter(program, size)(t)`。動画の同じ時刻のコマと同じ（テストで確かめている）

### 3. 選択画面で北原さんに選んでもらう

- 絵コンテを `b/` に置いた1枚のページ（Artifact。capabilities `db`・`user`）を出す。見本 `examples/選択画面.html`（`__DATA__` に `board.json` を入れる）
- 並べ方: **① 方向を選ぶ → ② 注文カード（左が今・右が注文後）→ ③ ひとこと → 決める**。同じ種類の注文（大きく／控えめに など）は1つだけ
- 「この形で決める」で db の `picks/latest`（と履歴 `picks_log`）に `direction`・`style`・`orders`・`note`・`at` が入る
- 「ほかの案も見たい」で db の `requests/<時刻>`（`kind: more`・ひとこと）が入る → ひとことを手がかりに `DIRECTIONS` に案を足して作り直す
- 北原さんはスマホで見るので、1列でも横にはみ出さないこと（`grid-template-columns: minmax(0, 1fr)`・`overflow-wrap: anywhere`）

### 4. 選ばれた形を書き込み、動画にして、最後に曲を当てる

1. Claude が `ArtifactData` で `picks/latest` を読み、JSON に保存する
2. `python -m backend.program_package.style_picker backend/config/program/<番組名>.json --apply PICK.json`
   - 指定の `style`（6つの軸）と `tune`（注文）に書き、`history` に1行足す
   - **ソウル・ナラティブ**（憲法 §5.2・§10）: `DecisionLogger.record_decision`（target_type `program_style`・理由＝ひとこと・方向と注文をタグ）→ `sync_to_soul_narrative()` で `evolution_log.json` に入る。次の案はこの記録から作る（同じ質問を繰り返さない）
3. 曲なしの動画（横・縦）で動きを確かめてもらう（注文を2つ以上足した形はここで初めて見える）
4. OK なら `version` を上げ、曲を当てて手順1で資産を書き出し直し、本編・Shorts に当てる

## 選べる軸（2026-10-26 時点）

| 軸 | 選択肢 | 元にした考え方 |
|---|---|---|
| `palette` 色 | murasaki 薄紫と金 / kinari 生成りの紙と墨 / ai 藍と銀 / yoru 夜の黒と金 / sakura 桜色と金 | 書道の素材（紙・墨・朱・金）と、番組の場の色 |
| `font` 書体 | mincho 明朝 / fude 毛筆（Yuji Syuku）/ tokumin 飾りのある明朝（Kaisei Tokumin）/ pen 手書きのペン字（Zen Kurenaido）/ gothic 太いゴシック | Google Fonts（SIL OFL）。`thumbnail --fetch-fonts` で入る |
| `layout` 置き方 | center 中央に横書き / vertical 縦書き（右の列から）/ left 左寄せ | 縦書きは列ごとに上から書き足す。いちばん長い列が画面に入る大きさにそろえる |
| `reveal` 言葉の現れ方 | brush 筆で書き足す / rise 行ごとに浮き上がる / blur 焦点が合う / stagger 一文字ずつ跳ねる | kinetic-typography の4つの定番を書道に寄せた |
| `background` 背景 | glow 中央が明るい / drift 光が漂う / washi 和紙の繊維 / gold_dust 金の粉 | motion-background: 文字より目立たない・ゆっくり |
| `finish` 番組名の締め | sweep 光が走る / seal 朱の落款 / brush_line 金の筆線 / halo 金の光が灯る | motion-art-direction:「見せ場は1つだけ」 |

注文（`tune`）: `text_scale` 言葉の大きさ・`title_scale` 番組名の大きさ・`pace` 書く速さ・`bright` 背景の明るさ（±1）・`lines` 金の線・`frame` 金の額縁・`seal` 落款を足す。既定は今の形のまま。

軸や選択肢を足すときは `opening.CHOICES`（色は `PALETTES`）に足し、`painter()` に描き方を足し、`DIRECTIONS` のどれかで使う（テスト `test_storyboard_directions_cover_every_choice...` が、どの選択肢もどこかの方向で見られることを確かめる）。注文は `opening.TUNE` と `style_picker.ORDERS` に足す。

**ED も同じ仕組みにする予定**（10-26 北原さん）。色・書体・置き方は番組の指定の `style` を ED も読む形にすれば、選び直しは1回で済む。

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
| 10-26 | ほぼ同じ形からではなく様々な形から選び、選んだ雰囲気にカードで注文を付けたい。画像で決めて試す時間を短く。曲は後で当てる。後々 ED も同じ作り方に |
