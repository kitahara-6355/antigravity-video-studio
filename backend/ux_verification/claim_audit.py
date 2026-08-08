"""主張と判定手段の対応を突き合わせる（P3 C-1）。

P2 では「充足率 90% 以上」を終了条件にしたが、**数え方に依存する値**だったため
検証のたびに数字が動いた。gate-verifier は3回とも「走査範囲の外に同型の偽 PASS が
残っている」と指摘し、そのたびに新しいポケットが出てきた:

    1回目: 37件が未判定 → 68.0%
    2回目:  6件が未判定 → 89.34%
    3回目:  7件が未判定 → 86.07%

**同じ実装のまま、数え方だけで 68% にも 89% にもなる。**
原因は「どの項目が何を主張しているか」を人間が description を読んで数えていたこと。
3回とも数え漏れた。

そこで主張の種類を項目自身に `claim` として書かせ、**宣言された判定手段で
その主張を判定できるか**を機械的に突き合わせる。

    python -m backend.ux_verification.claim_audit --persona owner

## 判定できるかの規則

`CLAIM_METHODS` が「この主張を判定するには何の宣言が要るか」を持つ。値は3通り:

- **タプル** — その宣言があれば判定できる
- **空タプル** — 判定手段が**まだ無い**（実装すれば埋まる）
- **`None`** — 静的走査では**原理的に判定できないと結論した**

最後の2つを混ぜないのが肝。同じ扱いにすると、実装をサボったものと結論を出した
ものが区別できず、「あと何を作れば終わるのか」が分からなくなる。

`None` の項目は対応が取れているとみなすが、**PASS には逃がさない。**
executor が `unjudgeable` の FAIL として出す。判定していないものを緑にするのが、
P2 で3回潰した偽 PASS そのものだから。

対応が取れていない理由は4種類:

- `no_claim`      — `claim` が書かれていない（**新しい項目の取りこぼしはここで出る**）
- `unknown_claim` — 知らない種類
- `no_method`     — その主張を判定する手段が実装されていない
- `not_declared`  — 手段はあるが、項目が必要な宣言を持っていない

`not_declared` が P2 で3回とも見落とした型。`O1-L1-01`「動画一覧APIが正常応答を
返す」は経路の主張なのに `testid` しか持たず、DOM 要素の実在だけで PASS していた。
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# 主張の種類 → その主張を判定するために項目が宣言すべきもの。
# 空タプル = 判定手段がまだ無い。
CLAIM_METHODS: dict[str, tuple[str, ...] | None] = {
    "dom_exists": ("testid",),
    "route_exists": ("endpoint",),
    "response_field": ("endpoint", "response_field"),
    "storage_key": ("storage_key",),
    "value_constraint": ("endpoint", "value_literals"),
    "request_contract": ("endpoint", "request_field"),
    # 値そのものの主張（`success=true`）。フィールドの実在では測れない。
    "response_value": ("endpoint", "response_field", "expected_value"),
    # 集合の主張（「対応拡張子**のみ**」）。値が現れることでは「のみ」を測れない。
    "value_exclusive": ("endpoint", "value_set"),
    # None = **静的走査では原理的に判定できないと結論した**主張。
    # 空タプル（未実装）とは別物で、こちらは実装しても埋まらない。
    # 該当項目は PASS に逃がさず、理由つきで FAIL にする（P3 C-3）。
    "element_count": None,
    "idempotency": None,
    "parameter_coverage": None,
    "spec_incomplete": None,
    # 状態遷移（「更新される」）。前後を比べる必要があり、1回の静的走査では
    # 「返る」との区別が付かない。ユーザー判断（2026-08-07）で FAIL とした。
    "state_transition": None,
}

# 各 claim が**何を確かめ、何を確かめないか**。
# ここを書かずに分類だけしていると、「正常応答を返す」を経路の実在で PASS に
# しているのが妥当なのか読み手に分からない。判定の意味を言葉で固定する。
CLAIM_SEMANTICS: dict[str, tuple[str, str]] = {
    "dom_exists": (
        "その data-testid が、エントリから到達できるソースに書かれている",
        "実行時に本当に描画されるか（条件分岐で一度も出ない要素も PASS になる）",
    ),
    "route_exists": (
        "そのエンドポイントが定義され、アプリに include_router されている",
        "**呼んで 200 が返るか。** ハンドラが例外を投げるかは静的には分からない。"
        "L1 が保証するのは『呼び先が存在し、404 にはならない』ところまで",
    ),
    "response_field": (
        "宣言されたフィールドが、ハンドラの返り値（呼び先を一段展開）に現れる",
        "その値が何であるか。空配列でもフィールドが在れば PASS になる",
    ),
    "storage_key": (
        "その localStorage キーの読み書きが、到達できるソースにある",
        "実行時に実際に書かれるか",
    ),
    "value_constraint": (
        "宣言された値が、エンドポイントの実装（参照するモジュール変数を含む）に現れる",
        "実行時にその値だけが返るか（「〜のみ」の『のみ』は確かめていない）",
    ),
    "request_contract": (
        "そのフィールドがリクエストモデルに定義されている",
        "その値域が受理されるか",
    ),
    "response_value": (
        "宣言されたフィールドに、宣言された値**以外のリテラルを返す経路が"
        "ハンドラのソースに無い**",
        "実行時に必ずその値になるか。ソースに無いだけで、動的に組み立てた値までは"
        "追えない",
    ),
    "value_exclusive": (
        "宣言した集合と**完全に一致する**リスト・リテラルが実装にある"
        "（余分な要素が無い）",
        "実行時にその集合だけが返るか。リストを作ったあとで足す経路は追えない",
    ),
    "element_count": (
        "（判定手段なし）",
        "**描画される件数。** 既定データの件数なら静的に数えられるが、"
        "主張は『表示される』で、実際の描画件数は実行時のデータ次第。"
        "既定データで代用するのは別の主張への置き換えになる",
    ),
    "idempotency": (
        "（判定手段なし）",
        "2回呼んで同じ結果になるか。実行しないと分からない",
    ),
    "parameter_coverage": (
        "（判定手段なし）",
        "**特定の入力値の集合が受理されるか。** 型が int としか書かれておらず、"
        "受理する値の集合が実装のどこにも宣言されていない場合、"
        "静的走査には照合する相手が無い",
    ),
    "spec_incomplete": (
        "（判定手段なし）",
        "何を照合すべきかが仕様に書かれていない。"
        "推測で照合先を書けば判定は出るが、それは実装ではなく判定の捏造",
    ),
    "state_transition": (
        "（判定手段なし）",
        "**呼ぶ前と後で値が変わったか。** 1回の静的走査では『返る』としか言えず、"
        "『更新される』と区別が付かない。実行層（L2）が要る",
    ),
}

# 主張の書き方を**閉じる**（P3 C-3）。
#
# claim は人が貼るラベルで、description との対応を誰も検証していなかった。
# `description: "success=true"` に `claim: response_field`（＝値は見ないと
# CLAIM_SEMANTICS が自ら明記）を貼れば、主張の半分が消えても緑になった
# （gate-verifier 5回目）。**ラベルの妥当性を機械で見る層が要る。**
#
# ここは3回作り直している。**2回とも「同じ主張が書き方の違いで強弱に振れる」で
# 破られた。**
#
#   10回目: 文末の動詞しか見ておらず、`…正常応答し success=true が返る` で
#           値の主張が消えた（空白の有無で振れる）
#   11回目: スロット検査が文末アンカーで、句点を1文字足すと素通りした
#   12回目: マーカーに**当たらなかった部分が黙って捨てられる**。読点で強い主張を
#           節の外へ押し出せた（`ステータスが completed になり、hook_score を返す`）
#
# 3回目の作り直しでは**文全体**を見る。description は登録済みのテンプレートに
# **丸ごと**一致しなければならず、一致しなければ `unparsed`。部分一致は無い。
#
# 節の区切り（読点・句点）はテンプレートが許さない。**一文一主張**にすることで、
# 「強い主張を別の節に逃がす」経路が構造的に消える。
# 名詞句。**節の区切りを含められない。** 読点・句点だけでなく、セミコロンや
# 改行・中黒も区切りとして扱う（14回目: `；` で別節に主張を逃がされた）。
_NP = "[^、。，．,.;；・｜|]*?"

# **強い述語。** これが文のどこかに在るのに、テンプレートがそれを引き受けて
# いなければ、その主張は測られていない。
#
# 13回目の指摘: 以前は名前付きスロットしか走査していなかったので、テンプレートの
# **無名部分**（`^{_NP}正常応答し…` の先頭）や括弧の中に強い述語を逃がせた。
# `locked_segments が更新され固定解除APIが正常応答し locked_segments を返す` が
# 「経路＋フィールド」に化けた。**走査は文全体にかける。**
_STRONG_MARKERS: dict[str, str] = {
    "状態遷移": r"更新|変わ|反映|切り替わ|増え|減っ",
    "値の指定": r"[=＝]",
    "排他": r"のみ|だけ",
    "件数": r"\d+\s*件",
    "範囲": r"以内|以上|以下|超え|限ら",
    "可能": r"が可能|できる",
}


def strong_markers_in(text: str) -> frozenset:
    return frozenset(
        name for name, pattern in _STRONG_MARKERS.items()
        if re.search(pattern, text)
    )


_IDENT = r"[A-Za-z_][A-Za-z0-9_.]*"

# (名前, 文全体の正規表現, 許される claim, **そのテンプレートが引き受ける強い述語**)。
# 引き受けていない強い述語が文に残っていたら、一致させない。
DESCRIPTION_TEMPLATES: tuple[tuple[str, str, tuple[str, ...], frozenset], ...] = (
    ("値の指定", rf"^(?P<slot>{_IDENT})\s*[=＝]\s*\S+$", ("response_value",),
     frozenset({"値の指定"})),
    ("〜のみ", rf"^(?P<slot>{_NP})のみ含まれる$", ("value_exclusive",),
     frozenset({"排他"})),
    ("件数", rf"^(?P<slot>{_NP})が\d+件以上表示される$", ("element_count",),
     frozenset({"件数", "範囲"})),
    ("プリセット網羅",
     rf"^\d+種プリセット\([^、。]*\)で(?P<slot>{_NP})が正常応答する$",
     ("parameter_coverage",), frozenset()),
    ("可能である", rf"^(?P<slot>{_NP})が可能\([^、。]*\)$", ("idempotency",),
     frozenset({"可能"})),
    ("列挙の実在", rf"^\d+カテゴリ\((?P<slot>[^、。]*)\)が存在する$",
     ("value_constraint",), frozenset()),
    ("経路＋状態遷移",
     rf"^(?P<prefix>{_NP})正常応答し(?P<slot>{_NP})が更新される$", ("state_transition",),
     frozenset({"状態遷移"})),
    ("保存キーの実在",
     rf"^(?:localStorage|sessionStorage)に(?P<slot>{_NP})が存在する$",
     ("storage_key",), frozenset()),
    ("経路＋フィールド",
     rf"^(?P<prefix>{_NP})正常応答し(?P<slot>{_NP})(?:が返る|を返す)$", ("response_field",),
     frozenset()),
    ("経路のみ", rf"^(?P<slot>{_NP})(?:が)?正常応答(?:を返す|する)?$",
     ("route_exists",), frozenset()),
    ("リクエスト契約", rf"^(?P<slot>{_NP})(?:を受け付ける|を受け取る)$",
     ("request_contract",), frozenset()),
    ("必須フィールド", rf"^(?P<slot>{_NP})が必須フィールドを返す$",
     ("response_field",), frozenset()),
    ("フィールドの実在", rf"^(?P<slot>{_NP})フィールドが存在する?$",
     ("response_field",), frozenset()),
    ("フィールドを返す", rf"^(?P<slot>{_NP})(?:を返す|が返る|が含まれる|含む)$",
     ("response_field",), frozenset()),
    # 「〜が存在する」は DOM の要素にもレスポンスのフィールドにも使われている。
    # ただしスロットが**そのまま ASCII 識別子**なら、それはフィールド名なので
    # DOM 要素の実在では測れない（12回目の指摘 C）。
    ("要素の実在", rf"^(?P<slot>{_NP})(?:が存在する|が存在|存在)$",
     ("dom_exists", "response_field"), frozenset()),
)

# フィールド名を書くテンプレート。スロットは宣言した response_field と一致すべき。
# 「要素の実在」もスロットが ASCII 識別子なら response_field に振り替えるので、
# ここに含めないとその経路だけスロット照合が走らない（15回目の指摘）。
# `download_url存在` と `download_urlフィールドが存在する` で強弱が振れていた。
_FIELD_TEMPLATES = ("フィールドを返す", "必須フィールド", "フィールドの実在",
                    "経路＋フィールド", "要素の実在")

_TYPED_SLOT = re.compile(rf"^{_IDENT}(?:/{_IDENT})*$")
# スロットに英数字の語が混じっていると、名前なのか値なのか判別できない。
# 2文字（`ID`）で回避されていたので下限を外した（15回目の指摘）。
_ASCII_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


# **名詞句の語彙。** ここに無い名詞句は書けない（15回目・ユーザー判断 2026-08-07）。
#
# 強い述語の検査は語彙に依存し、語彙外の述語（`以外` `一致する` `巻き戻して`
# `5個まで`）は名詞句に吸収される。**足すたびに次の未登録語で抜ける。5回作り直して
# 5回ともそうだった。** 既存項目の書き換えはラチェットが止めるが、新規項目は
# 素通りしていた（`--update-baseline` 一発で恒久に緑になる）。
#
# 名詞句そのものを閉じれば、そこで初めて原理的に閉じる。新しい項目を足すときは
# ここに登録する——**その登録が、人が主張を読む機会**になる。
#
# ASCII 識別子のスロット（フィールド名）は登録不要。`slot_not_declared` が
# 宣言した response_field と突き合わせる。
NOUN_PHRASES: dict = {
    "AI改善提案API": frozenset({'経路のみ'}),
    "BGM設定": frozenset({'フィールドを返す'}),
    "CTR予測": frozenset({'要素の実在'}),
    "GPU検出API": frozenset({'経路のみ'}),
    "LUFS設定": frozenset({'フィールドを返す'}),
    "SEOスコア": frozenset({'要素の実在'}),
    "SRTエクスポートボタン": frozenset({'要素の実在'}),
    "SmartCutヘルスチェックAPI": frozenset({'経路のみ'}),
    "SmartCut初期化API": frozenset({'経路のみ'}),
    "TXTエクスポートボタン": frozenset({'要素の実在'}),
    "Whisperモデルセレクトボックス": frozenset({'要素の実在'}),
    "actions配列": frozenset({'要素の実在'}),
    "analyze-scriptAPI": frozenset({'経路のみ'}),
    "diffコンテナ": frozenset({'要素の実在'}),
    "entries配列": frozenset({'フィールドを返す'}),
    "plan-storyboardAPI": frozenset({'経路のみ'}),
    "pre-planAPI": frozenset({'経路のみ'}),
    "quality-scoreAPI": frozenset({'経路のみ'}),
    "stagesフィールド": frozenset({'要素の実在'}),
    "user_modelオブジェクト": frozenset({'フィールドを返す'}),
    "アクション一覧API": frozenset({'経路のみ'}),
    "エクスポートAPI": frozenset({'経路のみ'}),
    "オーバーライドAPI": frozenset({'経路のみ'}),
    "カテゴリ別スコアAPI": frozenset({'経路のみ'}),
    "サムネイル候補": frozenset({'要素の実在'}),
    "サムネコンセプトAPI": frozenset({'経路のみ'}),
    "シーン固定API": frozenset({'経路のみ'}),
    "スキップトグル": frozenset({'要素の実在'}),
    "スコア変化API": frozenset({'経路のみ'}),
    "セグメント": frozenset({'件数'}),
    "セグメント一覧コンテナ": frozenset({'要素の実在'}),
    "タイトル候補リスト": frozenset({'要素の実在'}),
    "タグリスト": frozenset({'要素の実在'}),
    "チャプターリスト": frozenset({'要素の実在'}),
    "テンプレート一覧API": frozenset({'経路のみ'}),
    "テンプレート詳細API": frozenset({'経路のみ'}),
    "テーマ一覧API": frozenset({'経路のみ'}),
    "テーマ詳細API": frozenset({'経路のみ'}),
    "ドリルダウンAPI": frozenset({'経路のみ'}),
    "ドロップゾーン要素": frozenset({'要素の実在'}),
    "ハッシュタグ": frozenset({'要素の実在'}),
    "バリデーションAPI": frozenset({'経路のみ'}),
    "ヘルスチェックAPI": frozenset({'経路のみ'}),
    "メタデータAPI": frozenset({'必須フィールド'}),
    "ロゴ設定": frozenset({'フィールドを返す'}),
    "個別却下ボタン": frozenset({'要素の実在'}),
    "個別承認ボタン": frozenset({'要素の実在'}),
    "候補にtimestamp": frozenset({'フィールドの実在'}),
    "候補にtype": frozenset({'フィールドの実在'}),
    "候補レスポンスにchapters配列": frozenset({'要素の実在'}),
    "候補レスポンスにhighlights配列": frozenset({'要素の実在'}),
    "全候補API": frozenset({'経路のみ'}),
    "全却下ボタン": frozenset({'要素の実在'}),
    "全承認ボタン": frozenset({'要素の実在'}),
    "再度同一パラメータで推奨取得": frozenset({'可能である'}),
    "動画リストに対応拡張子": frozenset({'〜のみ'}),
    "動画一覧API": frozenset({'経路のみ'}),
    "動画一覧にvideos配列": frozenset({'要素の実在'}),
    "品質ゲートステータスAPI": frozenset({'経路のみ'}),
    "固定APIが": frozenset({'経路＋フィールド'}),
    "固定解除APIが": frozenset({'経路＋状態遷移'}),
    "字幕設定": frozenset({'フィールドを返す'}),
    "完了通知API": frozenset({'経路のみ'}),
    "履歴API": frozenset({'経路のみ'}),
    "履歴にhistory配列": frozenset({'要素の実在'}),
    "履歴キー": frozenset({'保存キーの実在'}),
    "差分マーク要素": frozenset({'要素の実在'}),
    "投稿準備バッジ": frozenset({'要素の実在'}),
    "推奨API": frozenset({'経路のみ'}),
    "推奨APIが目標尺パラメータ": frozenset({'リクエスト契約'}),
    "推奨APIで再計算": frozenset({'可能である'}),
    "推奨セグメントにscore": frozenset({'フィールドの実在'}),
    "推奨モデルバッジ": frozenset({'要素の実在'}),
    "推奨レスポンスにestimated_output_seconds": frozenset({'要素の実在'}),
    "推奨レスポンスにestimated_output_str": frozenset({'要素の実在'}),
    "推奨レスポンスにrecommended_segments": frozenset({'要素の実在'}),
    "推奨レスポンスにrecommended_segments配列": frozenset({'要素の実在'}),
    "改善ループステータスAPI": frozenset({'経路のみ'}),
    "最適化API": frozenset({'経路のみ'}),
    "校閲ステージパネル": frozenset({'要素の実在'}),
    "校閲進捗バー": frozenset({'要素の実在'}),
    "比較ビューコンテナ": frozenset({'要素の実在'}),
    "現在設定取得API": frozenset({'経路のみ'}),
    "確定API": frozenset({'経路のみ'}),
    "経過時間表示": frozenset({'要素の実在'}),
    "統計API": frozenset({'経路のみ'}),
    "設定取得API": frozenset({'経路のみ'}),
    "説明文エリア": frozenset({'要素の実在'}),
    "辞書パネル": frozenset({'要素の実在'}),
    "進捗テキスト(%)": frozenset({'要素の実在'}),
    "進捗バー": frozenset({'要素の実在'}),
    "適用API": frozenset({'経路のみ'}),
    "開始API": frozenset({'経路のみ'}),
}


def parse_description(description: str) -> tuple[str, tuple[str, ...], str] | None:
    """description をテンプレートに丸ごと突き合わせる。

    返り値は (テンプレート名, 許される claim, スロット)。
    どのテンプレートにも一致しなければ `None`。**部分一致は認めない。**
    """
    text = (description or "").strip()
    if not text or any(ch in text for ch in (chr(10), chr(13), chr(9))):
        return None  # 改行やタブで節を分けるのも許さない
    present = strong_markers_in(text)
    for name, pattern, claims, accounts in DESCRIPTION_TEMPLATES:
        match = re.match(pattern, text)
        if match is None:
            continue
        # **引き受けていない強い述語が文に残っていたら、一致させない。**
        # 走査はスロットではなく文全体（無名部分・括弧の中も含む）。
        if present - accounts:
            return None
        groups = match.groupdict()
        slot = (groups.get("slot") or "").strip()
        # **名詞句は「どのテンプレートで使ってよいか」まで登録する。**
        # グローバルな集合にしていたので、判定不能の項目のために登録した名詞句を
        # PASS できる弱いテンプレートへ移せた（16回目の指摘2）。
        # 無名の前置も検査する。名前を付けていなかったので素通りしていた（指摘1）。
        for part in (slot, (groups.get("prefix") or "").strip()):
            if not part or _TYPED_SLOT.match(part):
                continue  # フィールド名は slot_not_declared が宣言と突き合わせる
            if name not in NOUN_PHRASES.get(part, frozenset()):
                return None
        if name in _FIELD_TEMPLATES and not slot:
            return None  # `正常応答しを返す` のような空スロットを通さない
        if name == "要素の実在" and _TYPED_SLOT.match(slot):
            # `download_url存在` のような ASCII 識別子は、DOM 要素ではなく
            # レスポンスのフィールド名。要素の実在では測れない。
            return name, ("response_field",), slot
        return name, claims, slot
    return None


def slot_matches_declaration(description: str, item: dict) -> bool:
    """フィールド名を書くテンプレートで、スロットが**宣言したフィールドと一致**するか。

    13回目の指摘: スロットが ASCII 識別子なら無条件で「フィールド名」と見なして
    いたので、`completed を返す` / `true が返る` のように**値そのもの**を書いても
    宣言不要で通った。`hook_score` と `completed` は機械には見分けられないが、
    **項目が何を測ると宣言しているか**とは突き合わせられる。
    """
    parsed = parse_description(description)
    if parsed is None:
        return True
    name, _claims, slot = parsed
    if name not in _FIELD_TEMPLATES or not _TYPED_SLOT.match(slot):
        return True
    declared = {str(f) for f in _declared_fields(item)}
    return bool(declared) and set(slot.split("/")) <= declared


def _declared_fields(item: dict) -> list:
    raw = item.get("response_field")
    if raw is None:
        return []
    return list(raw) if isinstance(raw, (list, tuple)) else [raw]


def needs_value_note(description: str) -> bool:
    """項目自身に「この文が値の主張かどうか」を書かせる必要があるか。

    `hook_score を返す`（フィールドの実在）と `ステータスが completed を返す`
    （値の主張）は、どちらも同じテンプレートに乗る。`completed` が値なのか
    フィールド名なのかを機械は知らない。**判別できないものは人に宣言させる**
    （ユーザー判断 2026-08-07）。
    """
    parsed = parse_description(description)
    if parsed is None:
        return False  # そもそも通らない（unparsed で落ちる）
    name, _claims, slot = parsed
    if _TYPED_SLOT.match(slot):
        return False
    # ユーザー判断（2026-08-07）で要求の範囲が2つに分かれている。
    # フィールド系は**識別子でなければ必ず**、要素の実在は**英数字の語が
    # 混じっているときだけ**（`進捗バーが存在する` のような純粋な UI 名は対象外）。
    if name in ("フィールドを返す", "必須フィールド", "フィールドの実在",
                "経路＋フィールド"):
        return True
    if name == "要素の実在":
        return bool(_ASCII_TOKEN.search(slot))
    return False


# 項目が「何を照合先にするか」を宣言しているキー。**CLAIM_METHODS から導く。**
# ここを手で並べると、新しい判定手段を足したときに片方だけ増えて、
# 増えたほうがラチェットの外に落ちる（走査範囲の外のポケットの型）。
# **description も宣言のうち。**
#
# 14回目の指摘: 強い述語の検査は語彙（6本の正規表現）に依存していて、語彙外の
# 述語（`以外` `一致する` `巻き戻して` `5個まで`）は名詞句に吸収された。
# 語彙を足しても、次の語彙外の述語で同じことが起きる——4回続けてそうだった。
#
# テンプレート検査は「**新しい**項目が最低限の形をしていること」までしか
# 保証できない。**既存の項目の主張が黙って変わらないこと**は、ラチェットの
# 仕事にする。description を宣言に含めれば、書き換えは `substituted` として
# 検出され、`--redeclare` の理由と before/after が永久に残る。
DECLARATION_KEYS: tuple[str, ...] = ("claim", "description", "value_note") + tuple(sorted(
    {key for required in CLAIM_METHODS.values() if required for key in required}
))


def declaration_of(item: dict) -> dict:
    """項目の**宣言内容**を取り出す。「何を測ると言っているか」そのもの。

    ラチェットがこれを固定する。verdict と理由コードだけを記録していた頃は、
    `response_field` を `hook_score` → `success` のような**実在するが別の
    フィールド**に差し替えるだけで FAIL が PASS になり、違反ゼロ・改善1件として
    記録された（P3 C-4 / gate-verifier 5回目）。description は変わっていないので、
    項目が要求する内容だけが静かに緩む。
    """
    return {k: item[k] for k in DECLARATION_KEYS if item.get(k)}


# 判定手段がまだ無い主張（実装すれば埋まる）。ここが空でないと C-3 を満たせない。
UNSUPPORTED_CLAIMS = tuple(k for k, v in CLAIM_METHODS.items() if v == ())

# 静的には判定できないと結論した主張。FAIL として出すことで対応が取れたとみなす。
UNJUDGEABLE_CLAIMS = tuple(k for k, v in CLAIM_METHODS.items() if v is None)


@dataclass(frozen=True)
class ClaimRow:
    item_id: str
    ux_story: str
    description: str
    claim: str
    declared: tuple[str, ...]
    reason: str  # "" = 対応が取れている

    @property
    def matched(self) -> bool:
        return not self.reason

    def as_text(self) -> str:
        why = {
            "no_claim": "claim が書かれていない",
            "unknown_claim": f"知らない主張の種類（{self.claim}）",
            "no_method": f"{self.claim} を判定する手段が無い",
            "not_declared": (
                f"{self.claim} を判定するには "
                f"{'・'.join(CLAIM_METHODS.get(self.claim) or ())} が要るが、"
                f"持っているのは {'・'.join(self.declared) or 'なし'}"
            ),
            "unparsed": (
                "description がテンプレートに一致しない。"
                "DESCRIPTION_TEMPLATES か NOUN_PHRASES に足して判定手段を決めるか、"
                "登録済みの書き方に直す"
            ),
            "slot_not_declared": (
                "description が書いているフィールド名が、宣言した "
                "response_field に無い。フィールド名ではなく**値**を書いている疑いがある"
            ),
            "value_note_required": (
                "『〜を返す／含まれる』の手前が ASCII 識別子でないため、"
                "フィールド名なのか値なのかを機械が判別できない。"
                "value_note に『この文が値の主張かどうか』を書く"
            ),
            "claim_too_weak": (
                f"description の述語『{(parse_description(self.description) or ('?', ()))[0]}』は "
                f"{'・'.join((parse_description(self.description) or ('', ()))[1])} を要求するが、"
                f"貼られているのは {self.claim}"
                f"（{CLAIM_SEMANTICS.get(self.claim, ('', '?'))[1]}）"
            ),
        }.get(self.reason, self.reason)
        return f"{self.item_id:<11} {self.description}\n      → {why}"


@dataclass
class ClaimAuditReport:
    persona: str
    rows: list[ClaimRow] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def mismatched(self) -> list[ClaimRow]:
        return [r for r in self.rows if not r.matched]

    def by_claim(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.rows:
            out[r.claim or "(未記入)"] = out.get(r.claim or "(未記入)", 0) + 1
        return out

    def keys(self) -> list[str]:
        return sorted(r.item_id for r in self.mismatched)


def audit(stories_dir: Path, persona: str = "owner") -> ClaimAuditReport:
    """**判定側と同じ列挙**で走査する。

    別々に列挙していた頃は監査の範囲のほうが狭く、その隙間に置いた claim 無しの
    項目が実行系では PASS になるのに監査に現れなかった。範囲がずれていると、
    「対応ゼロ」は「監査が見ている範囲では対応ゼロ」という意味しか持たない。
    """
    from .executor import iter_l1_items

    report = ClaimAuditReport(persona=persona)
    prefix = "O" if persona == "owner" else "A"
    for ux_id, item in iter_l1_items(stories_dir, prefix):
        item_id = item.get("id") or item.get("item_id") or ""
        report.rows.append(_judge(item_id, ux_id, item))
    report.rows.sort(key=_sort_key)
    return report


def _judge(item_id: str, story: str, item: dict) -> ClaimRow:
    claim = (item.get("claim") or "").strip()
    declared = tuple(k for k in DECLARATION_KEYS
                     if k != "claim" and item.get(k))
    common = {
        "item_id": item_id, "ux_story": story,
        "description": item.get("description", ""),
        "claim": claim, "declared": declared,
    }

    if not claim:
        return ClaimRow(**common, reason="no_claim")
    if claim not in CLAIM_METHODS:
        return ClaimRow(**common, reason="unknown_claim")

    # **description の述語と claim の対応。** ここが無かったので、弱いラベルを
    # 貼るだけで主張の一部を捨てたまま PASS にできた（gate-verifier 5回目）。
    parsed = parse_description(common["description"])
    if parsed is None:
        return ClaimRow(**common, reason="unparsed")
    if CLAIM_METHODS[claim] == ():
        # 判定手段がそもそも無いなら、ラベルの当否より先にそれを言う。
        return ClaimRow(**common, reason="no_method")
    _, allowed, _slot = parsed
    # 「そもそも測れない」は述語の種類とは別の軸。**どの述語にも貼れる。**
    # ユーザー判断（2026-08-07）: 必ず FAIL に落ちるので偽の緑は作れず、
    # 付け替えはラチェットの substituted が捕まえて --redeclare の理由が残る。
    # PASS だった項目を落とすには --tighten も要る。
    if claim not in allowed and claim not in UNJUDGEABLE_CLAIMS:
        return ClaimRow(**common, reason="claim_too_weak")

    # 機械が型付けできないスロットは、**人に宣言させる。**
    # ユーザー判断（2026-08-07）: 「機械と明記の両方」の明記側をここで使う。
    # 空欄は許さない。宣言を消したり書き換えたりすれば、ラチェットの
    # substituted が捕まえて --redeclare の理由が残る。
    if (claim not in ("response_value", "value_exclusive")
            and needs_value_note(common["description"])
            and not (item.get("value_note") or "").strip()):
        return ClaimRow(**common, reason="value_note_required")

    # スロットが宣言したフィールドと違うなら、それはフィールド名ではなく
    # **値**を書いている疑いがある（`completed を返す` に response_field=status）。
    if claim not in ("response_value", "value_exclusive") and             not slot_matches_declaration(common["description"], item):
        return ClaimRow(**common, reason="slot_not_declared")

    required = CLAIM_METHODS[claim]
    if required is None:
        # 判定できないと**結論した**もの。結論も対応のうちなので mismatch にしない。
        # ただし PASS には逃がさず FAIL として出すことが前提（executor 側）。
        return ClaimRow(**common, reason="")
    if not required:
        return ClaimRow(**common, reason="no_method")
    if any(r not in declared for r in required):
        return ClaimRow(**common, reason="not_declared")
    return ClaimRow(**common, reason="")



def _sort_key(row: ClaimRow):
    try:
        head, tail = row.item_id.split("-L1-")
        return (int(head[1:]), int(tail))
    except (ValueError, IndexError):
        return (999, 0)


def _project_root() -> Path:
    try:
        from backend.path_resolver import project_root

        return Path(project_root())
    except (ImportError, OSError, ValueError):
        return Path(__file__).resolve().parents[2]


def for_repo(persona: str = "owner") -> ClaimAuditReport:
    return audit(_project_root() / "backend" / "ux_verification" / "stories", persona)


# --- CLI ---------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="検証項目の主張と判定手段の対応を突き合わせる",
    )
    parser.add_argument("--persona", default="owner", choices=["owner", "admin"])
    parser.add_argument("--json", action="store_true",
                        help="対応が取れていない項目の ID だけを JSON で出す")
    parser.add_argument("--gate", action="store_true",
                        help="対応が取れていない項目が1件でもあれば exit 1")
    parser.add_argument("--semantics", action="store_true",
                        help="各 claim が何を確かめ、何を確かめないかを出す")
    args = parser.parse_args(argv)

    if args.semantics:
        for claim in CLAIM_METHODS:
            verifies, does_not = CLAIM_SEMANTICS[claim]
            mark = "⛔" if claim in UNJUDGEABLE_CLAIMS else "  "
            print(f"{mark} {claim}")
            print(f"     確かめる  : {verifies}")
            print(f"     確かめない: {does_not}\n")
        return 0

    report = for_repo(args.persona)

    if args.json:
        print(json.dumps(report.keys(), ensure_ascii=False, indent=2))
        return 0

    print(f"主張と判定手段の対応 — persona={report.persona} / L1 {report.total} 項目")
    for claim, count in sorted(report.by_claim().items(), key=lambda kv: -kv[1]):
        if claim in UNSUPPORTED_CLAIMS:
            mark = "  ⚠️"          # 判定手段が未実装
        elif claim in UNJUDGEABLE_CLAIMS:
            mark = "  ⛔"          # 静的には判定できないと結論した
        else:
            mark = "    "
        print(f"{mark} {claim:<18}{count:>4} 件")

    bad = report.mismatched
    print(f"\n  対応が取れていない項目: {len(bad)} 件")
    for row in bad:
        print(f"    {row.as_text()}")
    if not bad:
        print("    なし。すべての主張が、それを判定できる手段で測られている。")

    if args.gate:
        # 走査が成立していないことを 0 件として通さない。項目が1つも取れて
        # いなければ、ストーリーを見失っただけで緑になってしまう。
        if report.total == 0:
            print("\n🚫 検証項目を1件も読み取れませんでした。"
                  "走査できなかったことを『対応ゼロ』として通しません。")
            return 1
        if bad:
            print("\n🚫 主張と判定手段の対応が取れていない項目があります。"
                  "判定していないものを PASS にしないでください。")
            return 1
        print(f"\n✅ {report.total} 項目すべてで対応が取れています。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
