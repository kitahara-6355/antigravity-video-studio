# 実装不足項目の台帳と点検 — 設計

**2026-08-27 / ユーザー承認済み（案 A）**

## 1. なぜ作るか

**実装が足りていない機能が、どこにも一覧されていない。** 分かっている7件のうち3件は正典
`vision_backlog.json` の R1.5-C4 の条件文に散らばって書かれ、残り4件は
**どこにも書かれていない**（実走ログと品質ゲートの出力にしか現れない）。

放置すると2つ困る:

1. **埋もれる。** サムネイル自動生成のように「将来やりたい」と思っている機能が、
   誰も一覧を持っていないので思い出されない
2. **品質ゲートが到達不能になる。** ゲートは本線に存在しない工程（サムネイル）を
   要求して減点する。**構成上どうやっても閾値に届かない**

実測（2026-08-27）: 品質スコアは満点100からの減点方式で、実走の減点合計は **−134**
（素点 −34、表示は0で床打ち）。うち **−50 は目標尺のミスマッチ**（別途修正済み）、
**−20以上がサムネイル**。目標尺を正すと 2点 → **52点**。残りの多くが「本線に無い機能」への減点。

### 既存の仕組みを使わない理由

`TechnicalDebtStore`（`backend/agents/memory/technical_debt.py`）は **1,463件**を持つ
自動登録の台帳で、キーは `file_path:line_number`、中身はほとんどが `except Exception` の
握り潰し。**存在しない機能は行番号を持てない**し、7件の戦略的な項目を1,463件の中に
入れたら**確実に埋もれる**（この台帳を作る目的そのものに反する）。

`TECHNICAL_DEBT_REGISTRY.md` は自動生成で、誰も読んでいない。同じ轍を踏まない。

## 2. 何を作るか

| もの | 置き場 | 既存の慣習 |
|---|---|---|
| 台帳 | `backend/config/feature_gaps.json` | `gemini_pricing.json` と同じ |
| CLI | `python -m backend.feature_gaps --show / --audit` | `model_policy` `cost_guard` と同じ |

### 1項目の形

```json
{
  "id": "thumbnail_generation",
  "title": "サムネイルの自動生成",
  "kind": "gap",
  "why": "品質ゲートが要求するが本線に工程が無い。−20点以上の固定減点になっている",
  "handled_in": "将来",
  "surfaces_as": "サムネイル",
  "done_when": {"kind": "artifact_present", "suffixes": [".png", ".jpg"]}
}
```

- **`kind` は2種類。** `gap`（実装が足りていない）と `intentional`（**意図して止めている**
  ので実装漏れではない）。実行記録には両方が同じ顔で出るので、区別しないと点検が誤検知する。
  例: `dream_learning` は `AVS_SKIP_LEARNING_SIDE_EFFECTS=1` で意図的に止めている
- **`handled_in` が行先の印。** `R1.5-C4` のようなフェーズの条件 ID か、`将来`
  （`intentional` の項目には要らない）
- **正典の条件文は書き換えない。** フェーズの定義はユーザーの領分（憲法第1条）。
  **台帳が一覧、正典が期限**という役割分担にする
- `surfaces_as` は実行記録の `health.skipped_features` / `failed_stages` に出るときの名前

### `done_when` の3種類

| kind | 実装済みと判定する条件 | 使う項目 |
|---|---|---|
| `run_record_clean` | 最新の実行記録の `skipped_features` / `failed_stages` に `surfaces_as` が出ない | BGM ミキシング / Shorts 候補 / サムネイル挿入 |
| `artifact_present` | 最新の実行記録の `artifacts` に指定の拡張子が出る | サムネイル生成 |
| `marker_gone` | 指定ファイルに指定の印（`[STUB]` / `placeholder_video_id` 等）が無い | retention 分析 / YouTube 投稿 / チャンネル統計 |

**`marker_gone` は弱い証拠。** 印が残っていることは「未実装」の確かな証拠だが、
印が消えたことは「実装された」の証拠にならない（`placeholder_video_id` がまさに
「書いてあるが動かない」の実例）。**実行記録で判定できる項目には使わない。**

## 3. 品質ゲートとの接続

**台帳に載っている機能は、減点せず `skipped_features` に出す。**

これが台帳を飾りにしない仕掛け。実装したら台帳から項目が消える →
**その瞬間からゲートが本気で見はじめる。** 逆に、ゲートが要求するのに本線が
作らないものを黙って減点し続けることがなくなる。

対象は現時点でサムネイル関連（物理チェック `_thumbnail_physical_check` と
プラグイン側の両方が二重に引いている）。

## 4. 点検が FAIL する条件

| # | 条件 | 何を防ぐか |
|---|---|---|
| 1 | 実行記録の `skipped_features` / `failed_stages` に出た項目が、**本線の工程名でも台帳の項目でもない** | **新しい実装漏れが黙って増える** |
| 2 | `kind: "gap"` の項目の `done_when` が満たされている | **直したのに台帳に残る**（片付け忘れ） |
| 3 | 台帳の項目に `why` / `done_when` が無い（`gap` はさらに `handled_in` が要る） | 記載不備 |

**条件1で「本線の工程名」を除くのが要。** 実行記録には3種類が同じ顔で出る:

| 記録に出るもの | 例 | 扱い |
|---|---|---|
| 本線の工程が落ちた | `quality_gate` | **実装漏れではない。**`STAGE_RECORD` の工程名で除外する |
| 意図して止めている | `dream_learning` | 台帳に `kind: "intentional"` で宣言 |
| 実装が足りていない | `BGMミキシング(ファイルなし)` | 台帳に `kind: "gap"` で宣言 |

**どれにも当てはまらないものが出たら FAIL。** これが「新しい漏れが埋もれない」の実体。

## 5. CI で何を見るか（重要）

**CI はパイプラインを実走できない**（実キーが無く、`output/` は gitignore なので
実行記録も無い）。したがって CI では条件1・2の実行記録側を評価できない。

**「確かめられなかった」を「問題なし」にしない**ため、モードを分ける:

- `--audit`（手元・実行記録あり）: 全部見る。ゲート報告が引用するのはこちら
- `--audit --static-only`（CI）: `marker_gone` と記載不備だけを見る。
  **評価しなかった検査を出力に列挙する**（黙って飛ばさない）

これは `model_policy --audit` がダミーキーで exit 0 を返してしまう問題と同じ形なので、
**同じ間違いを繰り返さないためにここで明示する。**

## 6. 初期登録（点検の結果・2026-08-27）

| id | title | kind | handled_in | done_when |
|---|---|---|---|---|
| `thumbnail_generation` | サムネイルの自動生成 | gap | 将来 | `artifact_present` |
| `thumbnail_insert` | サムネイルの自動インサート | gap | 将来 | `run_record_clean` |
| `retention_analysis` | retention 分析（現在モック） | gap | R1.5-C4 | `marker_gone` |
| `bgm_mixing` | BGM ミキシング（アセット未配置） | gap | 将来 | `run_record_clean` |
| `youtube_upload` | YouTube 投稿（placeholder を返す） | gap | R1.5-C4 | `marker_gone` |
| `channel_stats` | チャンネル統計（固定値） | gap | R1.5-C4 | `marker_gone` |
| `shorts_candidates` | Shorts 候補の抽出 | gap | 将来 | `run_record_clean` |
| `dream_learning` | 学習の副作用（意図して止めている） | intentional | — | `run_record_clean` |

## 7. テスト

**新規テストファイルを作らない。** `pytest.ini` の testpaths を触るとバッチの区切りが
変わり、既存のテスト汚染が別の場所で発火する（2026-08-26 に2回踏んだ）。
`backend/tests/test_revenue_artifact_gate.py` の隣に節を足す。

守る性質:

1. 台帳の全項目に `why` / `handled_in` / `done_when` がある
2. 実行記録に出た未知の項目を検出して FAIL する
3. `done_when` が満たされた項目を検出して FAIL する
4. `--static-only` が**評価しなかった検査を列挙する**（黙って飛ばさない）
5. 品質ゲートが、台帳に載っている機能を減点せず `skipped_features` に出す

## 8. スコープ外（YAGNI）

進捗率・担当者・期日・優先度・依存関係。**7項目に管理台帳を作り込む意味はない。**
必要になったら足す。

## 9. 未解決

- **実行記録の鮮度を見ていない。** 実走しなければ古い事実で判定し続ける。
  いまは記録の日時を出力に出すだけにして、FAIL 条件にはしない
  （CI が実走できない以上、鮮度を強制すると常に赤になる）
