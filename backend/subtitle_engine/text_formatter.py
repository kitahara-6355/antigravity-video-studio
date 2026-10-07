"""
text_formatter.py — 字幕テキスト整形エンジン

旧 src/clean_linguistic.py から移植。
Whisper出力の長文セグメントを日本語の言語境界（助詞・句読点）で
15文字/行に分割し、字幕の画面はみ出しを防止する。

Phase C: word_timestamps対応 — 単語レベルタイミングで正確な発話同期を実現。
"""

import logging
import re

logger = logging.getLogger(__name__)

# ============================================================
# 設定
# ============================================================

MAX_CHARS_PER_LINE = 15  # A-2: NHK基準（13〜15文字/行）に変更
FILLERS = [
    "えーと", "えー", "あのー", "あのー、", "まぁ", "ちょっと",
    "そのー", "なんか", "そうそうそう", "あー", "うーん", "えっと",
]

# 日本語の助詞・句読点パターン（分割ポイント）
SPLIT_PATTERN = re.compile(r"(.+?[はがをにのでと、。？！]|.+?です|.+?ます)")



# ============================================================
# 安全なセグメントコピー
# ============================================================

def _safe_copy_segment(seg: dict) -> dict:
    """セグメント辞書を安全にコピーする。

    もしコピーに失敗した場合は例外を投げる。
    """
    if hasattr(seg, "copy"):
        return seg.copy()
    return dict(seg)


# ============================================================
# フィラー除去
# ============================================================

def remove_fillers(text: str) -> str:
    """フィラー（無意味なつなぎ言葉）を除去"""
    if not isinstance(text, str):
        logger.warning(f"Non-string input passed to remove_fillers: {type(text)}")
        return ""
    for filler in FILLERS:
        text = text.replace(filler, "")
    return text.strip()


# ============================================================
# 聞くだけで足りる言葉（2026-10-06 ユーザー指摘）
# ============================================================
# 「さて」「それから」は文字にすると重要そうに見えるが、話の中身には触れない。
# 耳で聞けば足りるので字幕から外す。一覧はテンプレートの subtitle_rules
# （omit_lead_words / omit_standalone_words）。

_LEAD_PUNCT = "、,，"
_STANDALONE_STRIP = "、。，．,.！？!?…ー〜～ 　"


def _omit_words(key: str) -> list[str]:
    try:
        from template_config import template_config
        words = template_config.get_subtitle_rules().get(key)
    except Exception:  # テンプレートが読めなければ外さない
        return []
    if not isinstance(words, list):
        return []
    return sorted({w for w in words if isinstance(w, str) and w}, key=len, reverse=True)


def _bare_follow_ok(text: str, j: int) -> bool:
    """「、」の無い文頭語の後ろが、別の語の始まりか（ひらがなが続くなら同じ語の一部とみなす）。"""
    return j < len(text) and (text[j] in " 　\n" or _script(text[j]) != "hiragana")


def strip_lead_words(text: str, words: list[str] | None = None,
                     bare: list[str] | None = None) -> str:
    """文頭（文・字幕の頭）の「さて、」「それから、」などを外す。

    `words` は**後ろに「、」が続くときだけ**外す。「それから3年後」のように内容に掛かる用法は残す。
    `bare`（「では」「さて」など話題に掛からない語）は「、」が無くても外す。ただし後ろに
    ひらがなが続くとき（「ではありません」）は残す（2026-10-06 ユーザー指摘「では」）。
    外した結果が空になるときは元のまま返す（相づちだけの字幕は別の規則で扱う）。
    """
    if not isinstance(text, str) or not text:
        return text
    words = _omit_words("omit_lead_words") if words is None else words
    bare = _omit_words("omit_lead_words_bare") if bare is None else bare
    if not words and not bare:
        return text
    out, i, n = [], 0, len(text)
    at_head = True
    while i < n:
        if at_head:
            hit = next((w for w in words if text.startswith(w, i)
                        and i + len(w) < n and text[i + len(w)] in _LEAD_PUNCT), None)
            if hit:
                i += len(hit) + 1
                while i < n and text[i] in " 　":
                    i += 1
                continue
            hit = next((w for w in bare if text.startswith(w, i)
                        and _bare_follow_ok(text, i + len(w))), None)
            if hit:
                i += len(hit)
                while i < n and text[i] in " 　\n":
                    i += 1
                continue
        ch = text[i]
        if at_head and ch in _LEAD_PUNCT:  # フィラーを外した跡の「、」
            i += 1
            continue
        out.append(ch)
        at_head = ch in SENTENCE_END
        i += 1
    result = "".join(out).strip()
    return result if result else text


_FILLER_LEFT = "、,，。！？!? 　\n"
_FILLER_COMMA = "、,，"
_FILLER_END = "。！？!?"


def strip_interjections(text: str, words: list[str] | None = None) -> str:
    """「、」で挟まれた言いよどみ（「時に、え、ま、お習字を」の「え」「ま」）を、文の途中でも外す。

    前が文頭・句読点・空白で、後ろが「、」か文末のときだけ外す。「あの人」「まあまあ」の
    ように語の一部になっているもの、「、」で区切られていないものは残す（2026-10-06 ユーザー指摘の
    「話題に触れないつなぎ言葉は字幕にしない」を、文頭だけでなく文の途中にも広げた）。
    外した結果が空（言いよどみだけ）なら元のまま返す（相づちだけの字幕の規則が扱う）。
    """
    if not isinstance(text, str) or not text:
        return text
    words = _omit_words("omit_interjections") if words is None else words
    if not words:
        return text
    alt = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    left = f"(?:^|(?<=[{re.escape(_FILLER_LEFT)}]))"
    # 後ろに「、」: 言いよどみと「、」を外す（前の区切りは残す）
    before_comma = re.compile(f"{left}(?:{alt})[{re.escape(_FILLER_COMMA)}][ 　]*")
    # 後ろが文末: 前の「、」ごと外す（「けども、あの。」→「けども。」）
    at_end = re.compile(f"[{re.escape(_FILLER_COMMA)}][ 　]*(?:{alt})(?=[{re.escape(_FILLER_END)}]|$)")
    out = text
    while True:  # 「え、ま、」のように続くもの
        nxt = at_end.sub("", before_comma.sub("", out))
        if nxt == out:
            break
        out = nxt
    out = out.strip()
    return out if out.strip(_FILLER_LEFT + _FILLER_END) else text


def is_standalone_omittable(text: str, words: list[str] | None = None) -> bool:
    """相づちだけの字幕か（「はい。」「うん、なるほど。」）。音声は残し、字幕だけ出さない。"""
    if not isinstance(text, str):
        return False
    body = "".join(ch for ch in text if ch not in _STANDALONE_STRIP and ch != "\n")
    if not body:
        return False
    words = _omit_words("omit_standalone_words") if words is None else words
    # 一覧の言葉も本文と同じく伸ばし棒などを除いて比べる（「えー」は本文では「え」になる）
    words = [w for w in ("".join(ch for ch in w if ch not in _STANDALONE_STRIP) for w in words) if w]
    if not words:
        return False
    # 一覧の言葉だけでできているか（「はいはい」「うんうん」も）
    reachable = [True] + [False] * len(body)
    for i in range(len(body)):
        if reachable[i]:
            for w in words:
                if body.startswith(w, i):
                    reachable[i + len(w)] = True
    return reachable[-1]


# ============================================================
# 言語境界分割（メイン）
# ============================================================

def _split_at_boundary(text: str, max_chars: int = MAX_CHARS_PER_LINE) -> list[str]:
    """
    日本語の助詞・句読点境界でテキストを分割する。

    旧 src/clean_linguistic.py split_linguistically() の移植版。
    fugashi (MeCab) 依存を排除し、正規表現ベースで動作。
    イテレーティブ実装により再帰深度制限の問題を回避。

    Args:
        text: 分割するテキスト
        max_chars: 1行の最大文字数

    Returns:
        分割された文字列 of リスト
    """
    if not isinstance(text, str):
        return []

    # max_charsの安全ガード
    if not isinstance(max_chars, int):
        try:
            max_chars = int(max_chars)
        except (ValueError, TypeError):
            max_chars = MAX_CHARS_PER_LINE

    if max_chars <= 0:
        return [text]

    if len(text) <= max_chars:
        return [text]

    # イテレーティブに max_chars 以下のチャンクに分割
    chunks = []
    remaining = text

    while len(remaining) > max_chars:
        # パフォーマンス向上のため、対象をスライスして検索範囲を制限
        search_range = remaining[:max_chars + 5]
        best_split = -1
        for m in SPLIT_PATTERN.finditer(search_range):
            end_pos = m.end()
            if end_pos <= max_chars:
                best_split = end_pos
            else:
                break  # max_chars を超えたら探索終了

        if best_split >= 2:
            # 助詞・句読点 of 境界で分割
            chunks.append(remaining[:best_split].strip())
            remaining = remaining[best_split:].strip()
        else:
            # 分割ポイントが見つからない場合: max_chars で強制分割
            chunks.append(remaining[:max_chars].strip())
            remaining = remaining[max_chars:].strip()

    if remaining:
        chunks.append(remaining.strip())

    return [c for c in chunks if c]


def enforce_line_length(text: str, max_chars: int = MAX_CHARS_PER_LINE) -> str:
    """
    指定されたテキストの各行が max_chars 以下になるよう、
    必要に応じて改行 (\n) を挿入する。
    """
    if not isinstance(text, str):
        return ""

    if not isinstance(max_chars, int):
        try:
            max_chars = int(max_chars)
        except (ValueError, TypeError):
            max_chars = MAX_CHARS_PER_LINE

    if max_chars <= 0:
        return text

    if len(text) <= max_chars:
        return text

    lines = text.split("\n")
    new_lines = []
    for line in lines:
        if len(line) <= max_chars:
            new_lines.append(line)
        else:
            temp_line = line
            while len(temp_line) > max_chars:
                split_idx = max_chars
                # 助詞・句読点パターンで最後のマッチを探す
                matches = list(SPLIT_PATTERN.finditer(temp_line[:max_chars + 1]))
                if matches:
                    best_match = matches[-1]
                    end_idx = best_match.end()
                    if 2 <= end_idx <= max_chars:
                        split_idx = end_idx
                
                new_lines.append(temp_line[:split_idx].strip())
                temp_line = temp_line[split_idx:].strip()
            if temp_line:
                new_lines.append(temp_line)
                
    return "\n".join(new_lines)



# ============================================================
# 意味の塊での字幕分割（2026-10-05 ユーザー指摘）
# ============================================================
#
# `_split_at_boundary` は「は・が・を・に・の・で・と」の**文字**を見て、15文字に
# 収まる最後の位置で切る。語の途中の「の」「で」にも当たり、「書を|通して」
# 「その|思いを」のように意味の塊を割っていた。しかも1字幕1行（15文字）に
# 切るので、文が細切れになって次々に流れた。
#
# ここでは BudouX（Google の日本語の文節区切り）で文節に分け、
# 1) 文末（。！？）では必ず区切る 2) 1枚の字幕は max_lines 行まで詰める
# 3) 区切り・改行は「、」や助詞の後を選び、連体詞や「の」の直後は避ける。
# BudouX が無ければ従来の分割に戻る。

SENTENCE_END = "。！？!?"
_LEADING_PUNCT = "、。，．,.！？!?」』）)…ー〜"
_OPENING = "「『（(“"
_ADNOMINALS = ("この", "その", "あの", "どの", "こんな", "そんな", "あんな", "どんな")
# 後ろで切ってよい語尾。強いほど先に並べる（2点）
_GOOD_TAILS = ("から", "けど", "ので", "のに", "ため", "って", "では", "には", "とは",
               "は", "て", "で", "し", "ね", "よ", "な")
# 格助詞の直後は、次の動詞とひと塊のことが多い（「書を|通して」）ので弱め（1点）
_WEAK_TAILS = ("を", "に", "が", "と", "へ", "も", "や")
# 「て」の後ろに付く補助の動詞。前の動詞とひと塊なので、その手前では割らない
# （26回目の 27 秒「お届けして|まいります」で「まいります」だけが 0.8 秒出た・2026-10-06）
_HELPERS_AFTER_TE = ("いる", "いま", "いた", "いて", "いな", "いれ", "いく", "いき", "いっ", "いか", "いこ",
                     "おる", "おり", "おっ", "おら", "まい", "いただ", "いらっしゃ", "くれ", "くだ",
                     "もら", "しま", "おく", "おき", "みる", "みま", "みた", "みて", "みよ",
                     "くる", "きた", "きま", "きて", "こな", "ある", "あり", "あっ", "ござ", "ほし",
                     "あげ", "さしあげ", "頂", "下さ", "参り", "参る", "貰", "欲し", "差し上げ")
# 名詞の後ろの「で」に付くもの（「理事長で|いらっしゃいまして」「先生で|あります」）
_HELPERS_AFTER_DE = ("いらっしゃ", "ござ", "ある", "あり", "あっ", "いる", "いま")
# 引用の「って・と」と「いう」はひと塊（「きっかけって|いうのは」）
_QUOTE_TAILS = ("って", "と")
_QUOTE_HEADS = ("いう", "いっ", "いい", "言う", "言っ", "言い")

_budoux_parser = None


def _phrase_parser():
    """BudouX の日本語パーサ（無ければ None）。"""
    global _budoux_parser
    if _budoux_parser is None:
        try:
            import budoux
            _budoux_parser = budoux.load_default_japanese_parser()
        except ImportError:
            _budoux_parser = False
    return _budoux_parser or None


def _binds_to_next(p: str, nxt: str) -> bool:
    """文節 p と次の文節 nxt がひと塊（補助の動詞・引用の「っていう」）か。"""
    nxt = nxt.lstrip()
    if not nxt:
        return False
    if p.endswith(_QUOTE_TAILS) and nxt.startswith(_QUOTE_HEADS):
        return True
    # 動詞の「て・で」（書いて・読んで・泳いで）と、名詞の後ろの「で」で、付くものが違う
    if p.endswith("て") or p.endswith(("んで", "いで")):
        return nxt.startswith(_HELPERS_AFTER_TE)
    return p.endswith("で") and nxt.startswith(_HELPERS_AFTER_DE)


def _break_score(phrase: str, nxt: str = "") -> int:
    """この文節の**後ろで**切るときの良さ。大きいほど自然。nxt は次の文節（あれば見る）。"""
    p = phrase.rstrip()
    if not p:
        return 0
    if p.rfind("「") > p.rfind("」") or p.rfind("『") > p.rfind("』"):
        return -2  # 鉤括弧の中では割らない
    if p[-1] in SENTENCE_END:
        return 5
    if p[-1] in "、,…":
        return 4
    if p in _ADNOMINALS or p.endswith("の"):
        return -3  # 「この|チャンネル」「人々の|心に」は割らない
    if _binds_to_next(p, nxt):
        # 「お届けして|まいります」「きっかけって|いうのは」は割らない。「の」の後ろ（「協会の|理事長で
        # いらっしゃいまして」）より悪い
        return -4
    if p.endswith(_GOOD_TAILS):
        return 2
    if p.endswith(_WEAK_TAILS):
        return 1
    return 0


def _script(ch: str) -> str:
    if "\u30a0" <= ch <= "\u30ff":
        return "katakana"
    if "\u3040" <= ch <= "\u309f":
        return "hiragana"
    if "\u4e00" <= ch <= "\u9fff" or ch in "々〆":
        return "kanji"
    return "other"


def _is_bare_tail(text: str) -> bool:
    """ひらがなと句読点だけの短い切れ端（「で、」「は」）。1行にすると浮く。"""
    return len(text) <= 3 and all(_script(c) == "hiragana" or c in _LEADING_PUNCT for c in text)


def _cut_score(text: str, i: int) -> int | None:
    """長い文節を位置 i で割るときの良さ（割れない位置は None）。

    2: 漢字・カタカナの語の頭（「日本デザイン|書道」）
    1: 「た・て・で・だ」の後ろでひらがなが続く（「教えた|のかも」）
    0: 漢字の後ろの送り仮名の手前（「教|えた」）— 最後の手段
    """
    prev, cur = text[i - 1], text[i]
    if cur in _LEADING_PUNCT or _is_bare_tail(text[i:]):
        return None
    a, b = _script(prev), _script(cur)
    if a != b and b in ("kanji", "katakana"):
        return 2
    if a == b == "hiragana" and prev in "たてでだ":
        return 1
    if a != b:
        return 0
    return None


def _split_long_phrase(phrase: str, max_chars: int) -> list[str]:
    """1行に入らない文節（長い複合名詞など）を、語の切れ目らしい位置で割る。

    「日本デザイン書道作家協会理事長で、」→「日本デザイン」「書道作家協会理事長で、」。
    左が短すぎる位置（1行の4割未満）は後回し。割れる位置が無ければ max_chars で切る。
    """
    out = []
    rest = phrase
    while len(rest) > max_chars:
        cuts = [(_cut_score(rest, i), i) for i in range(1, min(len(rest), max_chars + 1))]
        cuts = [(sc, i) for sc, i in cuts if sc is not None]
        if cuts:
            _, _, cut = max((i >= max_chars * 0.4, sc, i) for sc, i in cuts)
        else:
            cut = max_chars
        out.append(rest[:cut])
        rest = rest[cut:]
    if rest:
        out.append(rest)
    return out


def _phrases(text: str, max_chars: int) -> list[str]:
    parser = _phrase_parser()
    if parser is None:
        return []
    phrases: list[str] = []
    for part in parser.parse(text):
        # 句読点で始まる文節は前の文節に付ける（行頭に「、」を置かない）
        while part and part[0] in _LEADING_PUNCT and phrases:
            phrases[-1] += part[0]
            part = part[1:]
        # 前の文節が開き括弧で終わっていたら、括弧をこの文節に回す（行末に「「」を置かない）
        while part and phrases and phrases[-1] and phrases[-1][-1] in _OPENING:
            part = phrases[-1][-1] + part
            phrases[-1] = phrases[-1][:-1]
            if not phrases[-1]:
                phrases.pop()
        # 漢字1字だけの文節は、漢字で終わる前の文節に付ける。BudouX は熟語の末尾を
        # 分けることがある（「一般社団法｜人」が「一般社団法\n人…」の折り目になった）
        if (len(part) == 1 and _script(part) == "kanji" and phrases and phrases[-1]
                and _script(phrases[-1][-1]) == "kanji" and len(phrases[-1]) < max_chars):
            phrases[-1] += part
            continue
        if part:
            phrases.extend(_split_long_phrase(part, max_chars))
    return phrases


def _sentences(phrases: list[str]) -> list[list[str]]:
    out, cur = [], []
    for ph in phrases:
        cur.append(ph)
        if ph.rstrip()[-1:] in SENTENCE_END:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _line_len(line: str, trim: bool = False) -> int:
    """行の字数。trim なら、行末で消える句読点（strip_punctuation）を数えない。"""
    return len(line.rstrip(_PUNCT)) if trim else len(line)


def _wrap_lines(phrases: list[str], max_chars: int, max_lines: int, trim: bool = False):
    """1枚の字幕を max_lines 行以内に折る。改行も文節の境目を選ぶ。

    折れなければ None（呼び出し側が字幕を短くする）。返り値は (本文, 改行の良さ)。
    trim なら行末の句読点を字数に数えない（後で消えるので。見える字が18字なら折らない）。
    """
    text = "".join(phrases)
    if _line_len(text, trim) <= max_chars:
        return text, 0
    if max_lines <= 1:
        return None
    best = None
    acc = 0
    for i, ph in enumerate(phrases[:-1], start=1):
        acc += len(ph)
        head = "".join(phrases[:i])
        if _line_len(head, trim) > max_chars:
            break
        if _binds_to_next(ph.rstrip(), phrases[i]):
            # 補助の動詞・「っていう」の手前では折らない。ほかに折れなければ字幕の方を分ける
            # （76 秒「きっかけって/いうのは」・2026-10-06）
            continue
        tail = _wrap_lines(phrases[i:], max_chars, max_lines - 1, trim)
        if tail is None:
            continue
        rest = len(text) - acc
        # 1〜2字だけの行は、ほかに折り方が無いときだけ（「が」/「もう1個別の…」・2026-10-06 実測）
        short = _line_len(head, trim) <= 2 or ("\n" not in tail[0] and _line_len(tail[0], trim) <= 2)
        # 区切りの良さを優先し、同じなら行の長さが揃う方
        key = (_break_score(ph, phrases[i]) + tail[1] - 6 * short, -abs(acc - rest))
        if best is None or key > best[0]:
            best = (key, "".join(phrases[:i]) + "\n" + tail[0])
    if best is None:
        return None
    return best[1], best[0][0]


def split_into_captions(text: str, max_chars: int = MAX_CHARS_PER_LINE,
                        max_lines: int = 2, trim: bool = False) -> list[str]:
    """発話を、意味の塊で区切った字幕（1枚 max_lines 行まで・改行は \\n）に分ける。

    - 文末（。！？）では必ず区切る
    - 1枚に入りきらない文は、入る範囲で区切りの良さが最大の文節の後ろで切る
      （短すぎる字幕は作らない: 1枚の容量の 4割以上）
    - 改行・区切りは「、」や助詞の後を選び、連体詞や「の」の直後は避ける

    - trim なら行末の句読点を字数に数えない（strip_punctuation で消える）

    BudouX が無ければ空リストを返す（呼び出し側が従来の分割に戻る）。
    """
    if not isinstance(text, str) or not text.strip():
        return []
    max_lines = max(1, int(max_lines or 1))
    phrases = _phrases(text.strip(), max_chars)
    if not phrases:
        return []
    capacity = max_chars * max_lines
    captions: list[str] = []
    for sentence in _sentences(phrases):
        rest = sentence
        while rest:
            choice = None  # (key, n, text)
            acc = 0
            for n in range(1, len(rest) + 1):
                acc += len(rest[n - 1])
                if acc > capacity and n > 1:
                    break
                wrapped = _wrap_lines(rest[:n], max_chars, max_lines, trim)
                if wrapped is None:
                    continue
                whole = n == len(rest)
                cut_score = 9 if whole else _break_score(rest[n - 1], rest[n])
                long_enough = whole or acc >= capacity * 0.4
                # 字幕の切れ目は行の折り目より優先する。「この対談では、/各界で」＋
                # 「ご活躍されている方を」のように、字幕の途中で文節をまたがせない
                # （2026-10-06 ユーザー指摘）
                key = (long_enough, cut_score, wrapped[1], acc)
                if choice is None or key > choice[0]:
                    choice = (key, n, wrapped[0])
            if choice is None:  # 1文節でも折れない（来ないはず）— そのまま置く
                choice = (None, 1, enforce_line_length(rest[0], max_chars))
            captions.append(choice[2])
            rest = rest[choice[1]:]
    return [c for c in captions if c.strip()]


def _semantic_line_break(text: str) -> str | None:
    """1行の字幕を、文節の境目で2行に折る（区切りの良さ優先・同点なら長さが揃う方）。

    端（2文字以内）では折らない。BudouX が無い・境目が無ければ None。
    """
    if "\n" in text or _phrase_parser() is None:
        return None
    phrases = _phrases(text, len(text))
    best = None
    acc = 0
    for i, ph in enumerate(phrases[:-1], start=1):
        acc += len(ph)
        if not 2 < acc < len(text) - 2:
            continue
        key = (_break_score(ph, phrases[i]), -abs(acc - (len(text) - acc)))
        if best is None or key > best[0]:
            best = (key, acc)
    if best is None or best[0][0] < 1:  # 「の」の後や語の途中では折らない
        return None
    return text[:best[1]] + "\n" + text[best[1]:]


# ============================================================
# Phase C: 単語タイミングベース分割
# ============================================================

def _split_by_word_timing(words: list[dict], max_chars: int, parent_seg: dict) -> list[dict]:
    """Phase C: 単語タイミングに基づいて正確にチャンク分割

    wordsの実際のタイムスタンプを使い、max_chars以内で自然にグルーピング。
    按分計算と違い、字幕と発話が完全に同期する。
    """
    if not isinstance(words, list) or not isinstance(parent_seg, dict):
        return []

    if not words:
        return []

    # max_charsの安全ガード
    if not isinstance(max_chars, int):
        try:
            max_chars = int(max_chars)
        except (ValueError, TypeError):
            max_chars = MAX_CHARS_PER_LINE

    if max_chars <= 0:
        max_chars = MAX_CHARS_PER_LINE

    chunks = []
    current_text = ""
    chunk_start = None
    chunk_end = None
    current_words = []

    for w in words:
        if not isinstance(w, dict):
            continue
        word_text = w.get("word", "")
        if not isinstance(word_text, str):
            continue
        word_text = word_text.strip()
        if not word_text:
            continue

        # フィラーチェック
        if word_text in FILLERS:
            continue

        w_start = w.get("start")
        if not isinstance(w_start, (int, float)):
            parent_start = parent_seg.get("start")
            w_start = parent_start if isinstance(parent_start, (int, float)) else 0.0

        w_end = w.get("end")
        if not isinstance(w_end, (int, float)):
            w_end = w_start

        # 安全ガード：単語レベルでのタイムスタンプ逆転防止
        w_end = max(w_end, w_start)

        if chunk_start is None:
            chunk_start = w_start
            chunk_end = w_end

        # この単語を追加するとmax_charsを超えるか？
        if current_text and len(current_text) + len(word_text) > max_chars:
            # 現在のチャンクを保存
            if current_text.strip():
                try:
                    new_seg = _safe_copy_segment(parent_seg)
                    new_seg["text"] = current_text.strip()
                    new_seg["start"] = chunk_start
                    new_seg["end"] = chunk_end
                    if "words" in new_seg:
                        new_seg["words"] = current_words.copy()
                    chunks.append(new_seg)
                except Exception as e:
                    logger.error(f"Error copying parent segment in word timing split: {e}")
            # 新しいチャンク開始
            current_text = word_text
            chunk_start = w_start
            chunk_end = w_end
            current_words = [w]
        else:
            current_text += word_text
            chunk_end = w_end
            current_words.append(w)

    # 最後のチャンク
    if current_text.strip():
        try:
            new_seg = _safe_copy_segment(parent_seg)
            new_seg["text"] = current_text.strip()
            new_seg["start"] = chunk_start if chunk_start is not None else parent_seg.get("start", 0)
            new_seg["end"] = chunk_end if chunk_end is not None else parent_seg.get("end", 0)
            # 安全ガード：逆転防止
            if new_seg["start"] is not None and new_seg["end"] is not None:
                new_seg["end"] = max(new_seg["end"], new_seg["start"])
            if "words" in new_seg:
                new_seg["words"] = current_words.copy()
            chunks.append(new_seg)
        except Exception as e:
            logger.error(f"Error copying parent segment for final chunk: {e}")

    return chunks if len(chunks) > 1 else []


# ============================================================
# メイン整形関数
# ============================================================

# 起こしの区切り（30 秒ごと）や話の間で、1つの文節が2つのセグメントに割れることがある。
# 字幕が助詞から始まり、文の途中で切れて見える（2026-10-06 実測: 56 秒「…書道塾」「を主宰されていて、」、
# 29 分「私が手がけた仕事」「を深掘りして」、13 分「…とかあと」「は…」「…中国は取れる」「とかがあったんで、」）。
# つなぎ目が文節の途中（BudouX でつないで読むと前の文節に付き、後ろだけで読んでも頭が1文節）で、
# 後ろの頭が前の語に付く短い助詞なら、頭を前のセグメントの尻に戻す。読点・文末が近ければ
# （12 字以内）そこまで、セグメントが短ければ全部を戻す。
# 小書きの字（「っていう」）で始まる語は無いので、前が文末でも戻す（相づちの後ろには付けない）。
_HEAD_MAX_CHARS = 12
_DEPENDENT_HEADS = ("を", "は", "が", "に", "と", "で", "も", "の", "へ", "や", "か", "よ", "ね",
                    "し", "ば", "けど", "けれど", "まで", "より", "から")
# 3 字以上で戻してよい助詞の連なり。これ以外の長い頭は語の一部（「やっぱり」）
_HEAD_COMPOUNDS = ("とかが", "とかは", "とかも", "とかね", "けれど", "けれども", "までは", "よりも",
                   "からは", "からね", "ですね", "ですよ")
# 上の字で始まるが、それだけで文を始められる語（「はい」「もう」「でも」）
_FREE_HEADS = ("はい", "はあ", "はー", "へえ", "へー", "ねえ", "ねー", "もう", "もし", "もっと",
               "もちろん", "よし", "よく", "とても", "とにかく", "とりあえず", "ところで",
               "でも", "では", "でしょ", "ですから", "しかし", "しかも", "かな", "やっぱ", "やはり")
# 文末の「です」「ます」の後ろに付くのは終助詞・接続助詞だけ（「ですに」「ますを」は無い）
_POLITE_ENDS = ("です", "ます", "でした", "ました")
_AFTER_POLITE = ("ね", "よ", "か", "が", "けど", "けれど", "から", "し", "ので", "のに", "って", "と")
_SMALL_KANA = "っゃゅょぁぃぅぇぉゎー"
_NOUN_SCRIPTS = ("kanji", "katakana")
_BOUND_N = ("んで", "んだ", "んじゃ", "んす")
_HEAD_PUNCT = "、,，" + SENTENCE_END
# 「です・ます」（＋終助詞）だけの頭は文を始められない。前の述語の続き（26回目の 2分55秒
# 「…もう行かないってなりそう」「ですよね」、締めの「…お越しいただき」「ました。」）。
# 「ですから」「でしょ」は文を始められるので _FREE_HEADS で先に外れる
_POLITE_HEAD_STARTS = ("です", "でし", "ます", "まし", "ませ")
_POLITE_HEAD = re.compile(r"(?:です|でした|でしょう|ます|ました|ません|ましょう)"
                          r"(?:よね|かね|かな|けど|けども|けれど|けれども|よ|ね|か|な|わ)?")
# 言い直しとみなす重なりの最短の字数（「いただ」）。2 字の重なり（「その」「この」）は偶然にもある
_RESTART_MIN_CHARS = 3


def _phrase_ends(parser, text: str) -> list[int]:
    ends, pos = [], 0
    for ph in parser.parse(text):
        pos += len(ph)
        ends.append(pos)
    return ends


def _is_bound(text: str) -> bool:
    """単独では語を始められない頭（「っていう」「んです」）。"""
    return text[:1] in _SMALL_KANA or text.startswith(_BOUND_N)


def _echo_len(prev: str, cur: str) -> int:
    """cur の頭が prev の尻の繰り返し（「…この問題はっていう。」「っていう…」）なら、その字数。"""
    tail = prev.rstrip(_HEAD_PUNCT)
    for n in range(min(8, len(cur)), 1, -1):
        if cur[n - 1] not in _HEAD_PUNCT and tail.endswith(cur[:n]):
            return n
    return 0


def _ends_mid_verb(text: str) -> bool:
    """促音で切れた動詞で終わるか（「…習字入れ入っ」）。後ろの「て・た」と1語なので、そこで割らない。

    「あっ」「えっ」のような感嘆（文の頭か、読点の後ろの「ひらがな1字＋っ」）は除く。
    """
    if len(text) < 2 or text[-1] != "っ":
        return False
    if _script(text[-2]) == "kanji":
        return True
    return _script(text[-2]) == "hiragana" and len(text) >= 3 and text[-3] not in _HEAD_PUNCT + " 　"


def _restart_len(prev: str, cur: str) -> int:
    """cur の頭が、prev の尻で途切れた語の言い直しなら、prev の尻から捨てる字数（無ければ 0）。

    起こしの区切りで語が割れると、前の区切りは語を補って言い切り（「…お越しいただい」）、
    次の区切りは同じ語を頭から起こす（「いただきました。」・締めの 43分9秒の実例）。
    重なり（_RESTART_MIN_CHARS 字以上）の後ろに、前の尻だけ1字余っていてもよい（補った字）。
    前が句読点で終わっていれば言い直しではない（2人が続けて「ありがとうございました。」）。
    """
    if not prev or prev[-1] in _HEAD_PUNCT:
        return 0
    for m in range(min(8, len(cur)), _RESTART_MIN_CHARS - 1, -1):
        head = cur[:m]
        if any(c in _HEAD_PUNCT or c in " 　" for c in head):
            continue
        for extra in (0, 1):
            cut = m + extra
            # 前に何も残らないなら言い直しとみなさない（同じ語を2人が言った）
            if len(prev) - cut >= 2 and prev[len(prev) - cut:len(prev) - extra] == head:
                return cut
    return 0


def _to_stop(cur: str, k: int) -> int:
    """戻す頭の字数 k を、読点・文末が近ければそこまで、短いセグメントなら全部に広げる。"""
    stops = [i + 1 for i, c in enumerate(cur) if c in _HEAD_PUNCT]
    if stops and k <= stops[0] <= _HEAD_MAX_CHARS + 1:
        return stops[0]
    if len(cur) <= _HEAD_MAX_CHARS + 1 and not any(c in SENTENCE_END for c in cur[:-1]):
        return len(cur)
    return k


def _continuation_len(prev: str, cur: str, parser) -> int:
    """cur の頭の文節（読点・文末が近ければそこまで）を prev に続けるときの字数。prev が句読点で終われば 0。"""
    if not prev or prev[-1] in _HEAD_PUNCT:
        return 0
    tail = prev[-20:]
    later = [e - len(tail) for e in _phrase_ends(parser, tail + cur[:24]) if e > len(tail)]
    return _to_stop(cur, later[0] if later else min(len(cur), 24))


def _split_head(prev: str, cur: str, parser) -> int:
    """cur の頭のうち、prev の続きとして前に戻す字数（戻さなければ 0）。"""
    if _is_bound(cur):
        # 相づちの後ろには付けない（「…じゃないやって。うん。」「って、どういうわけだか」）
        last = re.split(r"[。！？!?]", prev.rstrip(_HEAD_PUNCT))[-1]
        if prev[-1] in SENTENCE_END and is_standalone_omittable(last):
            return 0
        k = _phrase_ends(parser, cur)[0]
    else:
        if prev[-1] in _HEAD_PUNCT or cur.startswith(_FREE_HEADS):
            return 0
        noun = _script(prev[-1]) in _NOUN_SCRIPTS and _script(cur[0]) in _NOUN_SCRIPTS
        # 促音で切れた動詞の続き（「入っ」「てへえ」）と「です・ます」の頭（「なりそう」「ですよね」）は、
        # 助詞の頭より強いつながり（前の語の一部）。助詞の決まりで止めない
        verb = _ends_mid_verb(prev) and _script(cur[0]) == "hiragana"
        polite = cur.startswith(_POLITE_HEAD_STARTS) and not prev.endswith(_POLITE_ENDS)
        if not noun and not verb and not polite and not cur.startswith(_DEPENDENT_HEADS):
            return 0
        tail = prev[-20:]
        ends = _phrase_ends(parser, tail + cur[:24])
        # つなぎ目がちょうど文節の切れ目なら、後ろは新しい文節（「すごい」「もう…」）
        if len(tail) in ends:
            return 0
        k = next(e for e in ends if e > len(tail)) - len(tail)
        head = cur[:k].rstrip(_HEAD_PUNCT)
        if verb or (polite and _POLITE_HEAD.fullmatch(head)):
            return _to_stop(cur, k)
        if noun:
            # 名詞が割れた（56 秒「…久木田デザイン書道塾」「主宰、そして」）。読点・句点までの短い名詞だけ戻す
            # （「東京」「大阪に行きました」のような、区切りの無いつなぎは割れ目と決められない）
            if not (0 < len(head) <= 4 and k == len(head) + 1 and cur[len(head)] in _HEAD_PUNCT
                    and all(_script(c) in _NOUN_SCRIPTS for c in head)):
                return 0
            return k if k in _phrase_ends(parser, cur[:24]) else 0
        if not head or any(_script(c) != "hiragana" for c in head):
            return 0
        if len(head) > 2 and head not in _HEAD_COMPOUNDS:
            return 0
        # 「で」は前が「ん」で終わるとき（「選ん」「で」）だけ。ほかは接続詞の「で、」（「思うし」「で、実際に」）
        if head == "で" and not prev.endswith("ん"):
            return 0
        if prev.endswith(_POLITE_ENDS) and not head.startswith(_AFTER_POLITE):
            return 0
        # 「にこにこ」「はらはら」のような畳語は1語（BudouX は「に|こに|こ…」と割ることがある）
        if cur[:2] == cur[2:4] or cur[:3] == cur[3:6]:
            return 0
        # 後ろだけで読んでも頭が1文節であること（「は|い」「や|っぱり」を割らない）
        if k != len(cur) and k not in _phrase_ends(parser, cur[:24]):
            return 0
    # 読点・文末が近ければそこまで、短いセグメントなら全部を戻す
    return _to_stop(cur, k)


def _rejoin_split_heads(segments: list) -> list:
    """文節の途中で割れたセグメントの頭を、前のセグメントの尻に戻す。元のリストは変えない。"""
    parser = _phrase_parser()
    if parser is None:
        return segments
    out = []
    for seg in segments:
        try:
            text = seg.get("text") if isinstance(seg, dict) else None
            prev_seg = out[-1] if out and isinstance(out[-1], dict) else None
            prev = prev_seg.get("text") if prev_seg else None
            if (isinstance(text, str) and isinstance(prev, str) and prev.strip() and text.strip()
                    and not seg.get("words") and not prev_seg.get("words")):
                cur, base = text.strip(), prev.rstrip()
                # 起こしの窓の重なりで前の尻が繰り返された頭（「…問題はっていう。」「っていう…」）は捨てる
                echo = _echo_len(base, cur) if _is_bound(cur) else 0
                # 区切りで途切れて言い直された語（「…お越しいただい」「いただきました。」）は、前の尻の
                # 切れ端を捨て、言い直した語を前に続ける
                restart = 0 if echo or _is_bound(cur) else _restart_len(base, cur)
                if restart:
                    base = base[:-restart].rstrip()
                    n = _continuation_len(base, cur, parser)
                else:
                    n = 0 if echo else _split_head(base, cur, parser)
                if n and not restart and not _is_bound(cur):
                    # 戻す助詞が前の尻にもう付いている（校閲が「あと」を「あとは」に直し、後ろの
                    # 「は有名な…」が残った。戻すと「あとはは」になる・13 分 43 秒の実例）なら、後ろの頭を捨てる
                    dup = next((m for m in range(min(n, 3), 0, -1) if base.endswith(cur[:m])), 0)
                    if dup:
                        echo, n = dup, 0
                if echo or n or restart:
                    if n and _is_bound(cur):
                        base = base.rstrip(_HEAD_PUNCT)
                    rest = cur[echo or n:].lstrip(_HEAD_PUNCT + " 　")
                    joined = {**prev_seg, "text": base + cur[:n]}
                    if not rest:
                        if n and isinstance(seg.get("end"), (int, float)) and isinstance(joined.get("end"), (int, float)):
                            joined["end"] = max(joined["end"], seg["end"])
                        out[-1] = joined
                        continue
                    out[-1] = joined
                    seg = {**seg, "text": rest}
        except Exception:  # 読めないセグメントはそのまま（整形の本体が扱う）
            pass
        out.append(seg)
    return out


def format_segments(segments: list[dict], max_chars: int = MAX_CHARS_PER_LINE) -> list[dict]:
    """
    セグメントリストにテキスト整形を適用する。

    1. フィラー除去
    2. Phase C: wordsフィールドがある場合は単語タイミングベースで分割
    3. wordsがない場合は従来の言語境界分割 + タイミング按分

    Args:
        segments: セグメントリスト
        max_chars: 1行の最大文字数

    Returns:
        整形済みセグメントリスト
    """
    if not isinstance(segments, list):
        return []

    if not segments:
        return segments

    # max_charsの安全ガード
    if not isinstance(max_chars, int) or max_chars <= 0:
        try:
            max_chars = int(max_chars)
            if max_chars <= 0:
                max_chars = MAX_CHARS_PER_LINE
        except (ValueError, TypeError):
            max_chars = MAX_CHARS_PER_LINE

    max_lines = get_max_lines_from_template()
    trim = _strip_punctuation_enabled()
    segments = _rejoin_split_heads(segments)
    lead_words = _omit_words("omit_lead_words")
    bare_words = _omit_words("omit_lead_words_bare")
    mid_fillers = _omit_words("omit_interjections")
    formatted = []
    split_count = 0
    semantic_count = 0
    filler_count = 0
    word_split_count = 0

    for seg in segments:
        if not isinstance(seg, dict):
            continue

        try:
            text = seg.get("text", "")
            if not isinstance(text, str):
                continue
            text = text.strip()

            # Step 1: フィラー除去・「、」で挟まれた言いよどみと文頭の聞き流し語（さて、それから、）を外す
            cleaned = strip_lead_words(strip_interjections(remove_fillers(text), mid_fillers),
                                       lead_words, bare_words)
            if cleaned != text:
                filler_count += 1

            if not cleaned:
                continue

            # Step 2: Phase C — word_timestampsベースの分割
            words = seg.get("words")
            if isinstance(words, list) and words and len(cleaned) > max_chars:
                chunks = _split_by_word_timing(words, max_chars, seg)
                if chunks and len(chunks) > 1:
                    formatted.extend(chunks)
                    word_split_count += 1
                    continue

            # Step 3: 短いテキストはそのまま（行末で消える句読点は数えない）
            if _line_len(cleaned, trim) <= max_chars:
                new_seg = _safe_copy_segment(seg)
                new_seg["text"] = cleaned
                formatted.append(new_seg)
                continue

            # Step 4: 意味の塊で字幕に分ける（BudouX が無ければ従来の言語境界分割）+ タイミング按分
            chunks = split_into_captions(cleaned, max_chars, max_lines, trim)
            if chunks:
                semantic_count += 1
            else:
                chunks = _split_at_boundary(cleaned, max_chars)

            if len(chunks) <= 1:
                new_seg = _safe_copy_segment(seg)
                # 1枚に収まった（2行に折っただけ）ならその折り方を使う
                new_seg["text"] = chunks[0] if chunks else cleaned
                formatted.append(new_seg)
                continue

            total_chars = sum(len(c.replace("\n", "")) for c in chunks)
            
            start = seg.get("start")
            end = seg.get("end")
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
                start = 0.0
                end = 0.0
            # タイムスタンプ逆転防止
            if end < start:
                end = start
            duration = end - start
            current_start = start

            # 2枚目以降の頭に来た「じゃあ」なども外す（文の途中で分けた字幕の頭・39分17秒の実例）
            chunks = chunks[:1] + [strip_lead_words(c, lead_words, bare_words) for c in chunks[1:]]
            total_chars = sum(len(c.replace("\n", "")) for c in chunks)
            for chunk in chunks:
                chunk_duration = (len(chunk.replace("\n", "")) / total_chars) * duration if total_chars > 0 else duration / len(chunks)
                new_seg = _safe_copy_segment(seg)
                new_seg["text"] = chunk
                new_seg["start"] = current_start
                new_seg["end"] = current_start + chunk_duration
                # sourceStart/sourceEnd は元のまま維持（SmartCut用）
                formatted.append(new_seg)
                current_start += chunk_duration

            split_count += 1
        except Exception as e:
            logger.error(f"Unexpected error formatting segment: {e}", exc_info=True)
            # フォールバック: エラーが発生した場合は元のセグメントをそのまま追加して処理を継続
            try:
                formatted.append(_safe_copy_segment(seg))
            except Exception:
                formatted.append(seg)

    if split_count > 0 or filler_count > 0 or word_split_count > 0:
        logger.info(
            f"✂️ テキスト整形完了: フィラー除去 {filler_count}件, "
            f"word_timestamps分割 {word_split_count}件, "
            f"言語境界分割 {split_count}件（うち意味の塊 {semantic_count}件） ({len(segments)} → {len(formatted)} セグメント)"
        )

    # 字幕速度の自動調整を適用
    formatted = adjust_segment_speeds(formatted)

    # 句読点を出さない（区切りの判定に使い終わってから外す）。行の長さは消した後の見える字で測る
    # （「。」まで数えて、見える字が18字の行を「も」/「お料理…」に折っていた・2026-10-06 実測）
    if trim:
        for seg in formatted:
            if isinstance(seg, dict) and isinstance(seg.get("text"), str):
                seg["text"] = strip_punctuation(seg["text"])
        formatted = [s for s in formatted if not isinstance(s, dict) or s.get("text") != ""]

    # 1行の強制改行制限を適用
    for seg in formatted:
        if isinstance(seg, dict) and "text" in seg:
            seg["text"] = enforce_line_length(seg["text"], max_chars)

    return formatted


_PUNCT = "、。，．,"


def _strip_punctuation_enabled() -> bool:
    try:
        from template_config import template_config
        return bool(template_config.get_subtitle_rules().get("strip_punctuation", False))
    except Exception:
        return False


def strip_punctuation(text: str) -> str:
    """字幕から句読点（、。）を外す（2026-10-06 ユーザー指摘「句読点は不要」）。

    行末の句読点は消す。行の途中の句読点は全角スペースにして、語の切れ目を残す
    （「はい、いえいえ。」→「はい　いえいえ」）。「！」「？」は語気なので残す。
    """
    if not isinstance(text, str):
        return text
    lines = []
    for line in text.split("\n"):
        out = []
        for ch in line:
            if ch in _PUNCT:
                if out and out[-1] != "　":
                    out.append("　")
            else:
                out.append(ch)
        lines.append("".join(out).strip(" 　"))
    # 句読点だけの字幕は空にする（呼び出し側が捨てる）
    return "\n".join(line for line in lines if line)


# ============================================================
# 字幕表示速度の自動調整
# ============================================================

def adjust_segment_speeds(segments: list[dict], max_cps: float = None) -> list[dict]:
    """セグメントの表示速度（CPS）が目標閾値（max_cps * 2）を超えないよう調整する。

    1. 前後のセグメントと衝突しない範囲で、endを次のstartの手前まで延長する。
    2. それでもCPSが閾値を超える場合、テキストが長く、改行を含まない場合は適切な位置に改行を入れることで最長行文字数を減らす。
    """
    if not isinstance(segments, list):
        return []

    if not segments:
        return segments

    if max_cps is None:
        max_cps = get_chars_per_second_from_template()

    # max_cps のガード（None や 0 以下、NaN / INF の場合の安全フォールバック）
    import math
    if (not isinstance(max_cps, (int, float)) 
            or math.isnan(max_cps) 
            or math.isinf(max_cps) 
            or max_cps <= 0):
        max_cps = 4.0

    limit_cps = max_cps * 2  # NHK基準の2倍（デフォルト 8.0 文字/秒）を超えると検品違反になる
    
    adjusted = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        try:
            adjusted.append(_safe_copy_segment(seg))
        except Exception as e:
            logger.error(f"Error copying segment in adjust_segment_speeds: {e}")
            adjusted.append(seg)
        
    n = len(adjusted)

    for i in range(n):
        seg = adjusted[i]
        text = seg.get("text", "")
        # text が文字列でない場合はスキップ
        if not isinstance(text, str) or not text:
            continue

        # 表示字幕速度: 改行で分割された各行の最長行で判定
        lines = text.split("\n")
        max_line_len = max((len(line) for line in lines), default=0)

        # 短い字幕（8文字以下）は一目で読めるため、元々速度チェック対象外
        if max_line_len <= 8:
            continue

        start = seg.get("start")
        end = seg.get("end")

        # start, end が None または数値型でない場合はスキップ
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            continue

        dur = end - start

        if dur <= 0:
            continue

        current_cps = max_line_len / dur
        if current_cps <= limit_cps:
            continue

        # --- ステップ1: 表示時間の延長 ---
        # 次のセグメントの開始時間（なければ動画末尾や大きなマージン）
        next_start = None
        if i < n - 1:
            next_seg = adjusted[i+1]
            if isinstance(next_seg, dict):
                next_start = next_seg.get("start")
                
        if not isinstance(next_start, (int, float)):
            next_start = end + 5.0
        # 次のセグメントと 0.05秒 の安全マージンを空ける
        max_end = min(next_start - 0.05, end + 2.0)

        if max_end > end:
            # 必要な秒数を算出: max_line_len / limit_cps
            target_dur = max_line_len / limit_cps
            new_end = min(max_end, start + target_dur)
            seg["end"] = new_end
            dur = new_end - start
            current_cps = max_line_len / dur

        # --- ステップ2: 改行の挿入による最長行文字数の削減 ---
        if current_cps > limit_cps and "\n" not in text and len(text) > 8:
            # 文節の境目で改行できればそれを使う（意味の塊を割らない）
            broken = _semantic_line_break(text)
            if broken:
                seg["text"] = broken
                max_line_len = max(len(line) for line in broken.split("\n"))
                current_cps = max_line_len / dur
            # 助詞・句読点で自然に改行できるか調べる
            # BudouX が使えるときは文字単位の折り方（語の途中で割る）に戻らない
            semantic = _phrase_parser() is not None
            split_points = ([m.end() - 1 for m in SPLIT_PATTERN.finditer(text)]
                            if not broken and not semantic else [])
            if split_points:
                # 文字列の中央に最も近い分割ポイントを選択
                mid = len(text) // 2
                best_point = min(split_points, key=lambda x: abs(x - mid))
                # 端すぎるポイント（前後のマージン2文字）でなければ改行を挿入
                if 2 < best_point < len(text) - 2:
                    new_text = text[:best_point+1] + "\n" + text[best_point+1:]
                    seg["text"] = new_text

                    # 最長行とCPSを再計算
                    lines = new_text.split("\n")
                    max_line_len = max(len(line) for line in lines)
                    current_cps = max_line_len / dur

            # それでもダメなら中央で単純に改行を入れる
            if current_cps > limit_cps and "\n" not in seg["text"] and not semantic:
                mid = len(text) // 2
                new_text = text[:mid] + "\n" + text[mid:]
                seg["text"] = new_text

                # 再計算
                lines = new_text.split("\n")
                max_line_len = max(len(line) for line in lines)
                current_cps = max_line_len / dur

    return adjusted


# ============================================================
# テンプレート連携
# ============================================================

def get_max_chars_from_template() -> int:
    """テンプレートから最大文字数を取得（未設定時はデフォルト15文字）"""
    try:
        from template_config import template_config
        rules = template_config.get_subtitle_rules()
        if not isinstance(rules, dict):
            return MAX_CHARS_PER_LINE
        val = rules.get("max_chars_per_line", MAX_CHARS_PER_LINE)
        if not isinstance(val, int):
            return MAX_CHARS_PER_LINE
        return val
    except Exception as e:
        logger.warning(f"Template config fallback due to template/system exception: {e}")
        return MAX_CHARS_PER_LINE


def get_max_lines_from_template() -> int:
    """テンプレートから1枚の字幕の最大行数を取得（未設定時は2行）"""
    try:
        from template_config import template_config
        rules = template_config.get_subtitle_rules()
        val = rules.get("max_lines", 2) if isinstance(rules, dict) else 2
        return val if isinstance(val, int) and val >= 1 else 2
    except Exception as e:
        logger.warning(f"Template config max_lines fallback: {e}")
        return 2


def get_chars_per_second_from_template() -> float:
    """テンプレートから秒間最大文字数（CPS）を取得（未設定時はデフォルト4.0文字）"""
    try:
        from template_config import template_config
        rules = template_config.get_subtitle_rules()
        if not isinstance(rules, dict):
            return 4.0
        val = rules.get("chars_per_second", 4.0)
        if not isinstance(val, (int, float)):
            return 4.0
        return float(val)
    except Exception as e:
        logger.warning(f"Template config CPS fallback due to template/system exception: {e}")
        return 4.0
