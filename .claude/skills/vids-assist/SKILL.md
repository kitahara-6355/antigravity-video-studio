---
name: vids-assist
description: Google Vids（定額・手作業）を自動編集と並べて使う。北原さんが Vids で曲や短い動画を作るときの指示書を書き、作った物（曲・指示文・書き出し）を台帳に控えて資産にし、曲は自動編集（曲の台帳・山合わせ）に流す。Vids で OP・ED の曲を作るとき、Shorts や OP を Vids で手直しするとき、Vids で作った物を本編に入れるときに使う。
---

# Vids を並べて使う

北原さんの決定（2026-11-14）: 自動編集と Vids を並行で進める。手作業でも、何から何をどう作ったかを残せば資産になる。

## 分担

| 物 | 道具 | 理由 |
|---|---|---|
| 対談の本編（30 分超）・字幕・承認の控え・品質ゲート | 自動編集（このリポジトリ） | Vids の作品は 30 分まで。API が無く、同じ指定から作り直せない |
| OP・ED・BGM の曲を作る | Vids の曲の生成（人が押す） | 定額の中でフル曲 月 20・30 秒 月 50。権利のはっきりした、好みに寄せた曲を作れる |
| Shorts・OP など 30 分以内の手直し | Vids（人が押す） | 見ながらその場で直せる |

- **ボタンは人が押す。** Vids の画面操作を自動化しない（消費者向け・Workspace の画面操作の自動化はしない方針）
- **ゲストの映像を AI 機能に渡さない**（本人の了解の範囲が決まるまで）。曲を作るだけなら、空の作品で作れるので映像は要らない
- 実在の曲名・作曲者名を指示文に入れない。楽器・速さ・雰囲気・構成の言葉で書く

## 置き場（2026-11-14 北原さん承認。決まりの正典は drive_layout.json の vids）

| 物 | 置き場（「動画制作」の中） | 置く人 |
|---|---|---|
| 曲の書き出し（mp4） | `20_素材/共通/Vids曲/` | 北原さん（個人の Drive に書き出して info@ に共有 → Claude がここへ写す。名前は `曲_<役>_<連番>`） |
| 取り出した曲（mp3） | `30_AVS_作業/番組資産/曲/`（`music fetch` が探す所） | AI |
| Vids で手直しした短尺（Shorts・OP） | `40_完成/<収録ID>/Vids/` | 北原さん |
| 何を・どの指示文で・どのアカウントで作ったか | 曲は `backend/config/music.json`。曲以外は `30_AVS_作業/Vids台帳`（シート） | AI |
| 好みえらびの候補 | `30_AVS_作業/好みカルテ/<回>/候補曲/`（sources.json に `ai_generated` と台帳の key） | AI |

## 曲を作って本編に入れる流れ

1. Claude が指示書を書く（指示文 3〜5 案。日本語の説明と、Vids に貼る文）。北原さんの「こういう曲」の言葉は、そのまま指示書に残す
2. 北原さんが **個人アカウント（Google AI Pro）** の Vids で作り、気に入った案を **曲だけ入れた作品として mp4 で書き出す**。作品の名前は `曲_<役>_<連番>`（例 `曲_OP_01`）。
   info@（Business Standard）の Workspace では Vids が使えない（2026-11-14 北原さん）。書き出しは個人の Drive に置き、info@ に共有してもらって Claude が `Vids曲` へ写す
3. Claude が台帳に足しながら音を取り出す。**指示文が資産**なので必ず残す

       python -m backend.program_package.music add op_vids_01 --title "OP 案1" --file op_vids_01.mp3 \
           --source "Google Vids（2026-11-14）" --by 北原 --ai --made-with "Google Vids" --prompt "<貼った文>" \
           --account <作った個人のアカウント> --original "20_素材/共通/Vids曲/曲_OP_01.mp4" \
           --from-video 曲_OP_01.mp4 --music-dir 曲の置き場

   - 足した曲は `provisional`（仮）。出力名に「_仮曲入り」が付き、公開には使わない
   - 選ばれたら仮を外す。個人で作った曲は、作った人から法人への利用許諾の控えが要る:
     `music clear op_vids_01 --cleared "Google 利用規約（2026-07-30 版）: 所有権を主張しない・商用の制限なし" --transfer "2026-11-14 北原が美麗書院に利用を許諾（チャット）"`
   - 法人の Workspace で作った曲なら `--transfer` は要らず、Google の補償も付く（`indemnified`）
4. 聞き比べ: OP の使い始めは **山合わせが既定**（台帳でも `--audio` でも `start` が無ければ、曲の山の入りを番組名 10.5 秒に合わせる）。
   頭から流したいときだけ `"start": 0.0` と書く。好みを聞く画面は taste-picker（候補曲の置き場に写す）
5. 決まったら曲の台帳の `programs.<番組>.op.track` を替えて `finish` を流す。控え（`_仕上げの控え.json`）の `ai_music` に、
   AI で作った曲と「投稿のときに開示を『はい』にする」が出る

## 使ってよい条件（2026-11-14 一次情報で確認）

**個人アカウント（Google AI Pro）で作る場合 — いまの形**

- Google は生成物の所有権を主張しない。商用の制限は無く、事業での利用も想定されている（[Google 利用規約](https://policies.google.com/terms)、2026-07-30 版）。禁止は生成物で AI を作ること・[生成 AI の禁止事項](https://policies.google.com/terms/generative-ai/use-policy)
- **補償は無い。** 他人の曲に似ていると言われたら自分で対応する → 指示文に実在の曲名・アーティスト名を入れない（[Vids ヘルプ](https://support.google.com/docs/answer/16855124)）。公開前に耳で既存曲に似ていないか確かめる
- **持ち主は作った個人。** 法人の動画に使うので、作った人から法人への利用許諾を台帳に残す（`--transfer`）
- AI だけで作った曲は著作物と認められにくい（文化庁「AIと著作権に関する考え方」）。同じような曲を他の人も作れる前提で、Content ID には登録しない

**法人の Workspace で作れるようになった場合**

- 生成物は顧客のデータ・商用の制限なし・Google Vids は補償の対象（[Workspace サービス固有規約](https://workspace.google.com/intl/en/terms/service-terms/) 12.4・12.10・12.12、[対象一覧](https://cloud.google.com/terms/generative-ai-indemnified-services)、有料の契約のみ）

**どちらでも**

- YouTube: 「AI で作った音楽」は開示が要る例（[YouTube ヘルプ](https://support.google.com/youtube/answer/14328491)）。投稿で「改変・合成コンテンツ」を「はい」にする。控えの `ai_music` で付け忘れを防ぐ
- 曲には聞こえない印（SynthID）が入る前提で扱う

## Vids の上限（2026-11 の公式ヘルプ）

作品 30 分まで／取り込み 95 分・4GB まで（30 分以下に切るまで他の編集ができない）／動画 50 個・音 50 個／曲の生成 フル曲 月 20・30 秒 月 50／AI 動画 月 500 秒。Business Standard と Google AI Pro は同じ回数。
