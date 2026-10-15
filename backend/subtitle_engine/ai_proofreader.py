"""
AI Proofreader - Phase 18 Architecture
Gemini 3.0による字幕校閲（フィラー除去、文法修正）
"""

import os
import sys
import json
import hashlib
import traceback
import logging
from pathlib import Path
from google import genai
from google.genai import types
from google.genai.errors import APIError

# Add parent directory for model_registry import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Model resolution: 各バッチで動的解決（枠チェック付き）
def _get_current_model() -> str:
    """現在の枠状況に応じた最適モデルを動的に取得。
    
    Premium → Standard → Batch の順で枠を確認し、
    利用可能な最上位モデルを返す。
    """
    try:
        from model_governance import model_governance
        return model_governance._resolve_model("proofreader")
    except (ImportError, ModuleNotFoundError):
        return "gemini-3.6-flash"
    except Exception as e:
        logger.warning(f"モデルの解決に失敗しました。デフォルトを使用します: {e}")
        return "gemini-3.6-flash"

logger = logging.getLogger(__name__)


def _confirmed(entry: dict) -> bool:
    """確認済みの辞書の項目か（confirmed が無い項目は確認済みとみなす）。未確認の項目は校閲に渡さない。"""
    return entry.get("confirmed", True) is not False


def _build_proper_noun_context() -> str:
    """固有名詞辞書からプロンプト用コンテキストを生成（Phase E）"""
    try:
        from proper_noun_dict import proper_noun_dict
        entries = proper_noun_dict.get_all_entries()
        if not entries:
            return "## 固有名詞辞書\n（辞書は空です。一般的な日本語校閲のみ実行してください）"
        
        lines = ["## 固有名詞辞書", "以下の固有名詞が出現する可能性があります。音声認識の誤変換を修正してください："]
        seen = set()
        for entry in entries:
            if not _confirmed(entry):
                continue
            incorrect = entry.get("incorrect", "")
            correct = entry.get("correct", "")
            # 同じ組は1行だけ（テストが残した同じ組が 161 件、指示の大半を占めていた・2026-10-06）
            if (incorrect, correct) in seen:
                continue
            seen.add((incorrect, correct))
            context = entry.get("context_hint", "")
            hint = f"（{context}）" if context else ""
            if entry.get("type") == "hint":
                hint += "（文脈で判断。合うときだけ直す）"
            lines.append(f"- 「{incorrect}」→「{correct}」{hint}")
        
        return "\n".join(lines)
    except (ImportError, ModuleNotFoundError) as e:
        logger.warning(f"固有名詞辞書モジュールが見つかりません。デフォルトの校閲のみ実行します: {e}")
        return "## 固有名詞辞書\n（辞書モジュールが利用できません。一般的な日本語校閲のみ実行してください）"
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        logger.error(f"固有名詞辞書データの解析に失敗しました。詳細: {e}", exc_info=True)
        return "## 固有名詞辞書\n（辞書の解析に失敗しました。一般的な日本語校閲のみ実行してください）"
    except Exception as e:
        logger.error(f"固有名詞辞書の処理中に予期せぬエラーが発生しました: {e}", exc_info=True)
        return "## 固有名詞辞書\n（辞書の処理中に予期せぬエラーが発生しました。一般的な日本語校閲のみ実行してください）"



# 乱数の種。温度 0 と合わせて、同じ文には毎回同じ直しを返させる（2026-10-06 実走で、
# 書き出すたびに校閲の出来が変わり、直ったはずの誤変換が次の書き出しで戻った）
SEED = 20261006

# 直した文が元の文とこれ以上似ていなければ、別の行の文とみなして捨てる
MIN_SIMILARITY = 0.5
SHORT_LINE = 5


def _has_kanji(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" or ch == "々" for ch in text)


def _plausible_correction(original: str, corrected: str, neighbours=()) -> bool:
    """校閲の直しが、同じ行の文の直しとして妥当か（番号ずれ・行の入れ替えを弾く）。"""
    return _correction_verdict(original, corrected, neighbours) == "ok"


def _correction_verdict(original: str, corrected: str, neighbours=()) -> str:
    """校閲の直しの判定。"ok" / "shifted"（前後の行の文。番号ずれ）/ "dissimilar"（元の文から遠い）。

    句読点と空白を除いて比べる。フィラーを消しただけの短縮は通す（直した文が元の文に含まれる）。
    かなだけの行を漢字に直すのは変換の直しなので通す（「たんじゅ」→「単純」）。
    "dissimilar" は音声認識で裏付けが取れれば採れる（proofread_segments の referee）。
    "shifted" は裏付けがあっても採らない（隣の行の声が聞こえる範囲に入るため）。
    """
    import difflib

    def norm(t):
        return "".join(ch for ch in str(t) if ch not in "、。，．,. 　\n「」『』！？!?")

    a, b = norm(original), norm(corrected)
    if not a or not b or a == b:
        return "ok"
    if b in a:  # 消しただけ
        return "ok"
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    for other in neighbours or ():
        m = norm(other)
        if m and difflib.SequenceMatcher(None, m, b).ratio() > max(ratio, MIN_SIMILARITY):
            return "shifted"
    if max(len(a), len(b)) <= SHORT_LINE:  # 短い行どうしは比べても決まらない
        return "ok"
    if ratio >= MIN_SIMILARITY:
        return "ok"
    # かなだけの行を漢字に直した。漢字はかなより短く書けるので、長くはならない
    kana_only = all("\u3041" <= ch <= "\u30ff" for ch in a)
    if kana_only and _has_kanji(b) and 0.3 * len(a) <= len(b) <= 1.2 * len(a):
        return "ok"
    return "dissimilar"


# 句読点で区切られた、この字数以下のかなだけの句は相づち・感動詞（「ああ」「うん」「へえ」）
SHORT_KANA_PHRASE = 3
_PHRASE_BREAKS = "、。，．,！？!?…「」『』（）()\n"


def _is_kana(ch: str) -> bool:
    return "\u3041" <= ch <= "\u30ff"


def keep_short_kana_phrases(original: str, corrected: str) -> str:
    """句読点で区切られた短いかなだけの句（相づち・感動詞）を、別のかなに書き換えた直しを戻す。

    校閲は声を聞いていない。「ああ」か「あお」かは前後の文からは決まらないので、書き換えは
    当て推量になる（2分37秒「ああ、強烈な」→「あお、強烈な」・28回目）。消す（フィラーを外す）・
    漢字にする・句の外を直すのは残す。長い句の中の1字（助詞など）は文脈で決まることがあるので
    ここでは見ない（音声認識での裏付けは `aligner.drop_unheard_edits`）。
    """
    import difflib

    if not original or not corrected:
        return corrected
    base = "".join(ch for ch in str(original) if ch not in " 　")
    short = [False] * len(base)
    head = 0
    for k in range(len(base) + 1):
        if k == len(base) or base[k] in _PHRASE_BREAKS:
            phrase = base[head:k]
            if phrase and len(phrase) <= SHORT_KANA_PHRASE and all(map(_is_kana, phrase)):
                short[head:k] = [True] * (k - head)
            head = k + 1
    if not any(short):
        return corrected
    out, kept = [], False
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, base, corrected, autojunk=False).get_opcodes():
        new = corrected[j1:j2]
        if op == "replace" and all(short[i1:i2]) and all(map(_is_kana, new)):
            out.append(base[i1:i2])
            kept = True
        else:
            out.append(new)
    return "".join(out) if kept else corrected


def _proofread_prompt(proper_noun_context: str, batch_text: str) -> str:
    """Gemini校閲プロンプト（Phase E: 汎用化済み）。"""
    return f"""あなたはプロの動画字幕編集者です。以下の日本語字幕テキストを校閲および修正してください。

文脈を維持しつつ、以下の点を重点的に改善してください：
1. **固有名詞の修正**: 下記の固有名詞辞書を参考に、音声認識の誤変換を正しく修正してください。
2. **フィラーの削除**: 「えー」「あの」「えっと」「あー」などの不要な言葉を削除してください。
3. **自然な日本語**: 文末が不自然な助詞で終わっている場合、自然な言い切りや継続する形に修正してください。
4. **読みやすさ**: 意味を変えずに、字幕として読みやすい長さに調整してください。
5. **同音異義語の誤変換**: 音は合っているが文脈に合わない漢字を、前後の流れから正してください
   （例: ゲストを招いた場面の「読んでいただいて」→「呼んでいただいて」、「もう初会ね」→「もう初回ね」）。
   辞書の「文脈で判断」の項目も同じ扱いです。誤りでない語は言い換えないでください。
6. **行の対応を崩さない**: 各行は同じ index の行だけを直してください。行をまとめたり、
   別の行の文を移したりしないでください。直す所が無い行も、そのままの文で返してください。

{proper_noun_context}

**出力形式**:
必ず以下のJSON形式**のみ**を出力してください。Markdownのコードブロックは不要です。
[
  {{"index": 0, "text": "修正後のテキスト"}},
  {{"index": 1, "text": "修正後のテキスト"}}
]

**入力データ**:
""" + batch_text


# 校閲の控え（`ProofreadMemo`）の形式。控えの鍵に入るので、直しの決め方を変えたら上げる
MEMO_VERSION = 1


def _declared_model() -> str:
    """校閲に宣言されたモデル（段から引く。枠の残りでは変わらない）。控えの鍵に使う。"""
    try:
        from model_governance import model_governance
        return str(model_governance._resolve_declared("proofreader"))
    except Exception:  # 引けなくても校閲はする
        return ""


def _dictionary_rows() -> list:
    """辞書の (誤, 正, 種類, 説明) の組。控えの鍵には、行に掛かる組だけを入れる。"""
    try:
        from proper_noun_dict import proper_noun_dict
        return sorted({(str(e.get("incorrect") or ""), str(e.get("correct") or ""),
                        str(e.get("type") or ""), str(e.get("context_hint") or ""))
                       for e in proper_noun_dict.get_all_entries() if e.get("incorrect") and _confirmed(e)})
    except Exception:  # 辞書が読めなくても校閲はする
        return []


# 別の音声認識の聞き取り（`transcript_fusion.heard_hints`）の項目の説明。控えの鍵に入るので、渡し方を変えたら変える
HEARD_NOTE = "別の音声認識の聞き取り"


def _heard_rows(hints) -> list:
    """別の聞き取りを、辞書の「文脈で判断」の項目と同じ形 (誤, 正, "hint", 説明, 採ったかを見る語) にする。

    文字起こしは3回起こしても「座右の目」と書き、認識は「座右の銘」と聞いた（27分12秒・46回目）。
    文脈で決める校閲に渡す。項目の形にそろえるので、控え（`ProofreadMemo.earlier`）が前の直しに
    その語の直しだけを足す（AI が関係ない所を直し直さない）。5つ目は認識の字（`keep_term_edits` の語）。
    """
    rows = []
    for h in hints or ():
        wrong, right = str(h.get("incorrect") or ""), str(h.get("correct") or "")
        if wrong and right and wrong != right:
            rows.append((wrong, right, "hint", HEARD_NOTE, str(h.get("term") or "") or right))
    return rows


def _heard_context(rows, texts) -> str:
    """バッチの行に掛かる別の聞き取りを、指示に足す節にする（掛からなければ空。指示は変わらない）。"""
    lines = [f"- 「{r[0]}」→「{r[1]}」" for r in rows if any(r[0] in t for t in texts)]
    if not lines:
        return ""
    return ("\n\n## 別の音声認識の聞き取り\n"
            "次の所は、別の音声認識が違う字で聞いています。本文が聞き違えていて、別の聞き取りの方が前後の流れに"
            "合うときだけ、その語を直してください。合わないとき・どちらとも言えないとき（人名など）は本文のままに"
            "してください。別の聞き取りに無い語（呼びかけ・言いよどみ）を消すためには使わないでください。\n"
            + "\n".join(lines))


# 別の聞き取りを校閲に渡す前に、本文と並べて文として選ばせる（2026-10-15）。
# 「本文が聞き違えていれば直す」と渡すだけでは、校閲は28か所中18か所で認識の字を採った。直りは4か所
# （固唾・座右の銘・線質・仕上がり）で、崩れが10か所出た（47回目）。崩れは、同じ音で字だけ違う所
# （主催→主宰・引ける→弾ける。認識の字の選び方は聞き取りの証拠にならない）と、認識の方が聞き違えた所
# （細いほど→細いわな・関係なく→考え・機会をね→機会がです）。どちらも本文のままで文が通る。
# 選ばせる指示の版。控えの鍵に入るので、指示や決め方を変えたら上げる
JUDGE_VERSION = 1
JUDGE_CHOICES = {"1", "2", "either"}


def _judge_prompt(items, swap: bool) -> str:
    """本文と別の聞き取りを候補1・2に並べる。swap なら別の聞き取りを候補1にする（並べた順で選ぶ癖を消す）。"""
    head = """あなたは日本語の話し言葉の書き起こしを確かめる編集者です。
次の各項目は、同じ発話の書き起こしに2通りの候補がある所です。前後の行も付けています。
前後の行と話の流れから、日本語として意味が通り、話の筋に合う方を選んでください。

- 片方が意味の通らない語・不自然な言い回しになっていれば、もう片方を選ぶ
- 字が違うだけで同じ音の語なら、話の中身に合う字の方を選ぶ
- 両方とも意味が通るとき・決められないとき（人名・数など）は "either"

出力は JSON の配列だけにしてください（説明は不要）:
[{"id": 1, "choice": "1"}, {"id": 2, "choice": "either"}]
choice は "1"・"2"・"either" のどれかです。
"""
    out = [head]
    for n, it in enumerate(items, 1):
        first, second = (it["heard"], it["body"]) if swap else (it["body"], it["heard"])
        out.append(f"\n[{n}]\n前の行: {it['prev']}\n候補1: {first}\n候補2: {second}\n次の行: {it['next']}")
    return "\n".join(out)


def _judge_key(salt: str, item: dict, swap: bool) -> str:
    raw = json.dumps([salt, swap, item["prev"], item["body"], item["heard"], item["next"]], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _as_side(choice, swap: bool):
    """候補の番号を、本文（body）・別の聞き取り（heard）・どちらとも（either）に戻す。読めなければ None。"""
    choice = str(choice).strip() if choice is not None else ""
    if choice not in JUDGE_CHOICES:
        return None
    if choice == "either":
        return "either"
    return "heard" if (choice == "1") == swap else "body"


def judge_heard_hints(hints, segments, memo=None):
    """別の聞き取りを本文と並べて文として選ばせ、両順で別の聞き取りを選んだ所だけを返す。

    hints は `transcript_fusion.heard_hints` の項目（誤 incorrect → 正 correct）。本文（segments）に
    1か所だけある所を、前後の行を付けて「候補1・2」に並べ、本文を先にした回と別の聞き取りを先にした回の
    2回聞く。両方で別の聞き取りを選んだ所だけ採る（並べた順で選ぶ癖・どちらとも言える所は本文のまま）。
    選んだ結果は控え（`ProofreadMemo`）に残し、同じ所（前後の行も同じ）は次から聞かない。
    呼べない・答えが読めないときは、その回の所を採らない（本文のまま）。

    Returns:
        (採る項目のリスト, stats)。stats の spots に所ごとの選び方（両順）を残す。
    """
    stats = {"judged": 0, "chosen": 0, "calls": 0, "memo_hits": 0, "failed": False, "skipped": False,
             "models": [], "spots": []}
    texts = [str(s.get("text") or "") if isinstance(s, dict) else "" for s in segments or ()]
    items = []
    for h in hints or ():
        wrong, right = str(h.get("incorrect") or ""), str(h.get("correct") or "")
        rows = [k for k, t in enumerate(texts) if wrong and wrong in t]
        if not right or wrong == right or len(rows) != 1 or texts[rows[0]].count(wrong) != 1:
            continue
        k = rows[0]
        items.append({"hint": h, "prev": texts[k - 1] if k else "", "body": texts[k],
                      "heard": texts[k].replace(wrong, right, 1), "next": texts[k + 1] if k + 1 < len(texts) else ""})
    stats["judged"] = len(items)
    if not items:
        return [], stats

    sides = {False: {}, True: {}}
    models = set()
    keys = {}
    if memo is not None:
        template = hashlib.sha256(_judge_prompt([], False).encode("utf-8")).hexdigest()
        salt = json.dumps([JUDGE_VERSION, template, _declared_model()])
        for swap in (False, True):
            for n, it in enumerate(items):
                keys[swap, n] = _judge_key(salt, it, swap)
                hit = memo.get(keys[swap, n])
                if hit is not None and _as_side(hit, swap) is not None:
                    sides[swap][n] = _as_side(hit, swap)
                    stats["memo_hits"] += 1
                    models.add(memo.model_of(keys[swap, n]) or "不明")

    pending = {swap: [n for n in range(len(items)) if n not in sides[swap]] for swap in (False, True)}
    if pending[False] or pending[True]:
        api_key = os.getenv("GOOGLE_GENERATIVE_AI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            logger.warning("AI Proofreader: No API Key found. 別の聞き取りは選ばずに本文のままにします")
            stats["skipped"] = True
            pending = {False: [], True: []}
    client = None
    for swap in (False, True):
        if not pending[swap] or stats["failed"]:
            continue
        try:
            if client is None:
                try:
                    from model_governance import get_governed_client
                    client = get_governed_client("ai_proofreader")
                except ImportError:
                    from gemini_client_factory import get_gemini_client
                    client = get_gemini_client()
            model_name = _get_current_model()
            response = client.models.generate_content(
                model=model_name,
                contents=_judge_prompt([items[n] for n in pending[swap]], swap),
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0, seed=SEED),
            )
            stats["calls"] += 1
            _record_call()
            served = getattr(response, "model_version", None)
            served_model = served if isinstance(served, str) and served else model_name
            answers = json.loads(response.text)
            if not isinstance(answers, list):
                raise ValueError("答えが配列ではありません")
        except Exception as e:  # 選べなければ採らない（本文のまま）
            logger.warning(f"AI Proofreader: 別の聞き取りを選べませんでした（本文のままにします）: {e}")
            stats["failed"] = True
            continue
        models.add(served_model)
        for a in answers:
            if not isinstance(a, dict):
                continue
            n = _as_index(a.get("id"))
            side = _as_side(a.get("choice"), swap)
            if n is None or not 1 <= n <= len(pending[swap]) or side is None:
                continue
            n = pending[swap][n - 1]
            sides[swap][n] = side
            if memo is not None:
                memo.put(keys[swap, n], str(a.get("choice")).strip(), served_model)
    if memo is not None:
        memo.save()

    chosen = []
    for n, it in enumerate(items):
        pair = [sides[False].get(n), sides[True].get(n)]
        take = pair == ["heard", "heard"]
        if take:
            chosen.append(it["hint"])
        h = it["hint"]
        stats["spots"].append({"start": h.get("start"), "incorrect": h.get("incorrect"),
                               "correct": h.get("correct"), "choices": pair, "chosen": take})
    stats["chosen"] = len(chosen)
    stats["models"] = sorted(models)
    logger.info(f"AI Proofreader: 別の聞き取り {len(items)} か所を本文と並べて選ばせ、{len(chosen)} か所を校閲に渡します"
                f"（呼び出し {stats['calls']} 回・控え {stats['memo_hits']}）")
    return chosen, stats


def _record_call() -> None:
    """API 使用量を記録する（記録できなくても校閲は続ける）。"""
    try:
        from usage_tracker.api_usage_tracker import record_api_call
        record_api_call(1, "ai_proofreader")
    except Exception as e:
        logger.debug(f"API使用量の記録をスキップ: {e}")


def keep_term_edits(base: str, corrected: str, terms) -> str:
    """corrected の直しのうち、terms（辞書の正しい語）に掛かるものだけを base に足す。

    terms に掛からない所は base のまま。terms が corrected に無ければ base を返す。
    """
    import difflib

    spans = []
    for term in terms or ():
        k = corrected.find(term) if term else -1
        while k != -1:
            spans.append((k, k + len(term)))
            k = corrected.find(term, k + 1)
    if not spans:
        return base
    out = []
    sm = difflib.SequenceMatcher(None, base, corrected, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            out.append(base[i1:i2])
        elif any((j1 < b and a < j2) if j2 > j1 else a <= j1 <= b for a, b in spans):
            out.append(corrected[j1:j2])  # 語に掛かる直し（語に接する削除も含む）
        else:
            out.append(base[i1:i2])
    return "".join(out)


class ProofreadMemo:
    """行ごとの校閲の控え（JSON・素材ごとに1つ）。

    温度 0・seed 固定でも、同じ100行の直しが書き出しごとに変わった（29回目は冒頭の「しかも」
    「初日ね」が戻らず、「主宰」が「主催」になった・2026-10-08）。一度採った直しは控えておき、
    同じ行には次からも同じ直しを使う。鍵は (控えの形式・指示文・宣言モデル・行に掛かる辞書の組・行)
    なので、指示文・モデル指定・その行に掛かる辞書が変われば、その行は校閲し直す。
    控えるのは AI の出力そのもの（文脈の項目を足して校閲し直した行は、前の控えに項目の語の直しだけを
    足したもの。`earlier`）。番号ずれや音声認識での確かめは毎回やり直す。
    """

    def __init__(self, path):
        self.path = Path(path)
        self.rows: dict = {}
        self._dirty = False
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self.rows = data
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:  # 壊れた控えは使わない（校閲し直す）
            logger.warning(f"AI Proofreader: 校閲の控えが読めないので使いません: {e}")

    @staticmethod
    def key(salt: str, text: str, rows) -> str:
        related = [list(r) for r in rows if r[0] and r[0] in text]
        raw = json.dumps([salt, related, text], ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def earlier(self, salt: str, text: str, rows):
        """文脈で判断する項目（hint）を足す前の、同じ行の控えと、足した項目の正しい語。

        項目を足すと行の鍵が変わって校閲し直すが、AI は項目と関係ない所まで直し直す
        （2分11秒: 前の回に外した「それで行っと」を「それで行って」と書いて戻した・2026-10-13）。
        控えが見つからなければ (None, ())。
        """
        import itertools

        related = [r for r in rows if r[0] and r[0] in text]
        hints = [r for r in related if len(r) > 2 and r[2] == "hint"]
        for size in range(len(hints) - 1, -1, -1):
            for kept in itertools.combinations(hints, size):
                subset = [r for r in related if r not in hints or r in kept]
                hit = self.get(self.key(salt, text, subset))
                if hit is not None:  # 別の聞き取りの項目（5つ目がある）は認識の字を語にする
                    return hit, tuple(str(r[4] if len(r) > 4 else r[1]) for r in hints if r not in kept)
        return None, ()

    def get(self, key: str):
        row = self.rows.get(key)
        return row.get("text") if isinstance(row, dict) and isinstance(row.get("text"), str) else None

    def model_of(self, key: str) -> str:
        row = self.rows.get(key)
        return str(row.get("model") or "") if isinstance(row, dict) else ""

    def put(self, key: str, text: str, model: str) -> None:
        self.rows[key] = {"text": text, "model": model}
        self._dirty = True

    def save(self) -> None:
        if not self._dirty:
            return
        try:
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(self.rows, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
            self._dirty = False
        except OSError as e:  # 書けなくても校閲の結果は返す
            logger.warning(f"AI Proofreader: 校閲の控えを書けませんでした: {e}")


class _MemoReply:
    """控えから組んだ応答（API の応答と同じく .text に JSON を持つ）。"""

    def __init__(self, text: str):
        self.text = text


def _as_index(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def proofread_segments(segments, update_callback=None, return_stats=False, referee=None, memo=None, hints=None):
    """
    Gemini APIを使用して字幕セグメントを校閲

    Args:
        segments (list): セグメントリスト（text, start, end等）
        update_callback (callable, optional): 進捗コールバック(status, message, progress)
        return_stats (bool): Trueの場合、(segments, stats_dict) のタプルを返す
        hints (list, optional): 別の音声認識の聞き取り（`transcript_fusion.heard_hints`）。掛かる行の
            バッチの指示に足し、採ったら控えの前の直しにその語の直しだけを足す

    Returns:
        list: 校閲済みセグメント（return_stats=Falseの場合）
        tuple: (segments, stats) のタプル（return_stats=Trueの場合）
            stats = {
                "proofread_count": int,    # 修正されたセグメント数
                "total_retries": int,      # 全バッチのリトライ合計回数
                "failed_batches": int,     # リトライ尽きた失敗バッチ数
                "total_batches": int,      # 全バッチ数
                "skipped": bool,           # APIキーなし等でスキップされたか
            }
    """
    # P-02: リトライ統計の初期化
    stats = {
        "proofread_count": 0,
        "total_retries": 0,
        # 失敗したバッチの [開始, 終了) 。呼び出し側が小さく分けて校閲し直す
        "failed_ranges": [],
        "failed_batches": 0,
        "total_batches": 0,
        "skipped": False,
        # **採用した AI の出力の件数**（R2-C5・2026-09-26）。記録の「宣言どおり」の証拠
        "accepted_items": 0,
        # 番号ずれなどで直しを捨てた行。校閲されないまま残るので、呼び出し側が小さく分けて聞き直す
        "rejected_rows": [],
        # 別の音声認識の聞き取りを渡した行と、その語を採った行
        "heard_hints": 0,
        "heard_adopted": 0,
    }
    heard = _heard_rows(hints)

    def _return(segs):
        if return_stats:
            return segs, stats
        return segs

    # 入力バリデーション
    if not isinstance(segments, list):
        logger.error("AI Proofreader: segments must be a list")
        stats["skipped"] = True
        return _return(segments)

    for idx, s in enumerate(segments):
        if not isinstance(s, dict):
            logger.error(f"AI Proofreader: segment at index {idx} must be a dict")
            stats["skipped"] = True
            return _return(segments)
        if "text" not in s:
            logger.error(f"AI Proofreader: segment at index {idx} must contain 'text' key")
            stats["skipped"] = True
            return _return(segments)
        if not isinstance(s.get("text"), str):
            logger.error(f"AI Proofreader: segment at index {idx} text must be a string")
            stats["skipped"] = True
            return _return(segments)

        # start, end のタイムスタンプ・バリデーション
        if "start" in s:
            start_val = s.get("start")
            if not isinstance(start_val, (int, float)):
                logger.error(f"AI Proofreader: segment at index {idx} 'start' must be int or float")
                stats["skipped"] = True
                return _return(segments)
            if start_val < 0:
                logger.error(f"AI Proofreader: segment at index {idx} 'start' must be non-negative")
                stats["skipped"] = True
                return _return(segments)

        if "end" in s:
            end_val = s.get("end")
            if not isinstance(end_val, (int, float)):
                logger.error(f"AI Proofreader: segment at index {idx} 'end' must be int or float")
                stats["skipped"] = True
                return _return(segments)
            if end_val < 0:
                logger.error(f"AI Proofreader: segment at index {idx} 'end' must be non-negative")
                stats["skipped"] = True
                return _return(segments)

        if "start" in s and "end" in s:
            if s.get("end") < s.get("start"):
                logger.error(f"AI Proofreader: segment at index {idx} 'end' must be greater than or equal to 'start'")
                stats["skipped"] = True
                return _return(segments)

    # API キーを環境変数から取得
    api_key = os.getenv("GOOGLE_GENERATIVE_AI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.warning("AI Proofreader: No API Key found. Skipping proofreading.")
        stats["skipped"] = True
        return _return(segments)

    try:
        # D-04修正: GovernedModelsProxy経由でフォールバックチェーンを有効化
        try:
            from model_governance import get_governed_client
            client = get_governed_client("ai_proofreader")
        except ImportError:
            from gemini_client_factory import get_gemini_client
            client = get_gemini_client()
        CHUNK_SIZE = 100  # サイクル3ループ2: 200→品質低下(-12%)→100に調整(APIコール18→9)
        total_segments = len(segments)
        before = [str(s.get("text") or "") for s in segments]
        proofread_count = 0

        total_batches = (total_segments + CHUNK_SIZE - 1) // CHUNK_SIZE
        stats["total_batches"] = total_batches

        logger.info(f"AI Proofreader: Processing {total_segments} segments in batches of {CHUNK_SIZE}...")

        # 校閲の控え: 鍵は校閲する前の行の文で決める（バッチを直すと次のバッチの前後が変わるため）
        keys = []
        if memo is not None:
            template = hashlib.sha256(_proofread_prompt("", "").encode("utf-8")).hexdigest()
            salt = json.dumps([MEMO_VERSION, template, _declared_model()])
            rows = _dictionary_rows() + heard
            texts = [str(s.get("text") or "") for s in segments]
            keys = [ProofreadMemo.key(salt, t, rows) for t in texts]
            stats["memo_hits"] = 0
        memo_models = set()

        for i in range(0, total_segments, CHUNK_SIZE):
            batch = segments[i:i + CHUNK_SIZE]
            batch_text = ""

            # バッチテキスト作成（絶対インデックス使用）
            for idx, s in enumerate(batch):
                abs_index = i + idx
                batch_text += f"[{abs_index}] {s['text']}\n"

            # 固有名詞辞書をプロンプトに注入（Phase E: 汎用化）。別の聞き取りは掛かる行のあるバッチだけ
            proper_noun_context = _build_proper_noun_context() + _heard_context(heard, [s["text"] for s in batch])

            prompt = _proofread_prompt(proper_noun_context, batch_text)

            # 進捗表示
            current_batch_num = i // CHUNK_SIZE + 1
            msg = f"AI校閲を実行中 ({current_batch_num}/{total_batches} バッチ)..."

            # 各バッチでモデルを動的解決（枠枯渇時に自動降格）
            model_name = _get_current_model()

            logger.info(f"AI Proofreader: Sending batch {current_batch_num} (model={model_name})...")
            if update_callback:
                update_callback("processing", msg, 99)

            # ━━━ FIX-2A: リトライ付きGemini API呼び出し ━━━
            MAX_RETRIES = 3
            BACKOFF_BASE = 2  # 指数バックオフ: 2s → 4s → 8s
            batch_succeeded = False
            response = None

            # 控えにある行は控えの直しを使う。全部あれば呼ばない
            remembered = {}
            for idx in range(len(batch) if memo is not None else 0):
                hit = memo.get(keys[i + idx])
                if hit is not None:
                    remembered[i + idx] = hit
            from_memo = memo is not None and len(remembered) == len(batch)
            if from_memo:
                response = _MemoReply("[]")
                batch_succeeded = True
                logger.info(f"AI Proofreader: batch {current_batch_num} は全行が校閲の控えにあるので呼びません")

            for retry in range(0 if from_memo else MAX_RETRIES + 1):
                try:
                    # Gemini API呼び出し（動的解決モデル使用）
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            temperature=0,
                            seed=SEED,
                        )
                    )
                    batch_succeeded = True
                    break  # 成功 → リトライループ脱出

                except APIError as e:
                    error_str = str(e).lower()
                    is_api_retryable = (
                        e.code in (429, 503)
                        or any(x in error_str for x in ["429", "503", "resource_exhausted", "resourceexhausted", "quota"])
                    )
                    if is_api_retryable and retry < MAX_RETRIES:
                        wait_sec = BACKOFF_BASE ** (retry + 1)
                        stats["total_retries"] += 1
                        logger.warning(
                            f"🔄 AI Proofreader: Batch {current_batch_num} "
                            f"API一時エラーによるリトライ {retry + 1}/{MAX_RETRIES} "
                            f"({wait_sec}秒待機): {e}"
                        )
                        import time as _time
                        _time.sleep(wait_sec)
                        continue
                    
                    logger.error(f"AI Proofreader: Batch {current_batch_num} APIエラーが継続し失敗: {e}")
                    traceback.print_exc()
                    break

                except (ConnectionError, TimeoutError, OSError) as e:
                    if retry < MAX_RETRIES:
                        wait_sec = BACKOFF_BASE ** (retry + 1)
                        stats["total_retries"] += 1
                        logger.warning(
                            f"🔄 AI Proofreader: Batch {current_batch_num} "
                            f"接続一時エラーによるリトライ {retry + 1}/{MAX_RETRIES} "
                            f"({wait_sec}秒待機): {e}"
                        )
                        import time as _time
                        _time.sleep(wait_sec)
                        continue

                    logger.error(f"AI Proofreader: Batch {current_batch_num} 接続エラーが継続し失敗: {e}")
                    traceback.print_exc()
                    break

                except (ValueError, TypeError, RuntimeError) as e:
                    # SDKの他の例外など、未知の例外に対するフォールバック
                    error_str = str(e).lower()
                    is_api_retryable = any(
                        x in error_str
                        for x in ["429", "503", "resource_exhausted", "resourceexhausted", "service_unavailable", "serviceunavailable", "quota"]
                    )
                    if is_api_retryable and retry < MAX_RETRIES:
                        wait_sec = BACKOFF_BASE ** (retry + 1)
                        stats["total_retries"] += 1
                        logger.warning(
                            f"🔄 AI Proofreader: Batch {current_batch_num} "
                            f"一時エラーによるリトライ {retry + 1}/{MAX_RETRIES} "
                            f"({wait_sec}秒待機): {e}"
                        )
                        import time as _time
                        _time.sleep(wait_sec)
                        continue

                    logger.error(f"AI Proofreader: Batch {current_batch_num} 予期せぬエラーが継続し失敗: {e}")
                    traceback.print_exc()
                    break

                except Exception as e:
                    # 一般的な例外だが、メッセージから再試行可能と判定される場合（429や503など）はリトライに回す
                    error_str = str(e).lower()
                    is_api_retryable = any(
                        x in error_str
                        for x in ["429", "503", "resource_exhausted", "resourceexhausted", "service_unavailable", "serviceunavailable", "quota"]
                    )
                    if is_api_retryable and retry < MAX_RETRIES:
                        wait_sec = BACKOFF_BASE ** (retry + 1)
                        stats["total_retries"] += 1
                        logger.warning(
                            f"🔄 AI Proofreader: Batch {current_batch_num} "
                            f"一時的例外によるリトライ {retry + 1}/{MAX_RETRIES} "
                            f"({wait_sec}秒待機): {e}"
                        )
                        import time as _time
                        _time.sleep(wait_sec)
                        continue

                    # API呼び出し時の想定外の例外に対する安全網
                    logger.error(f"AI Proofreader: Batch {current_batch_num} 予期せぬ重大なエラー: {e}", exc_info=True)
                    break

            if batch_succeeded and response is not None:
                # 実際に答えたモデル（枠切れで宣言と違うモデルに落ちることがある）。控えに残す
                served = getattr(response, "model_version", None)
                served_model = served if isinstance(served, str) and served else model_name
                # API使用量を記録（控えから組んだ応答は呼んでいない）
                try:
                    if not from_memo:
                        from usage_tracker.api_usage_tracker import record_api_call
                        record_api_call(1, "ai_proofreader")
                except (ImportError, ModuleNotFoundError) as e:
                    logger.debug(f"API使用量トラッカーが見つかりません。スキップします: {e}")
                except OSError as e:
                    logger.warning(f"API使用量の書き込みに失敗しました（I/Oエラー）: {e}")
                except (TypeError, ValueError) as e:
                    logger.warning(f"API使用量記録 of argument or value error: {e}")

                # レスポンスをパース（セキュアなバリデーション付き）
                try:
                    corrected_data = json.loads(response.text)
                except json.JSONDecodeError as jde:
                    logger.error(f"AI Proofreader: Failed to decode JSON response: {jde}")
                    # JSONパース失敗はバッチ失敗とする
                    stats["failed_batches"] += 1
                    stats["failed_ranges"].append([i, i + len(batch)])
                    continue

                if remembered and isinstance(corrected_data, list):
                    # 控えにある行は、この回に AI が返した直しではなく控えの直しを使う
                    corrected_data = [it for it in corrected_data
                                      if not (isinstance(it, dict) and _as_index(it.get("index")) in remembered)]
                    corrected_data += [{"index": k, "text": v, "_memo": True} for k, v in remembered.items()]

                batch_correction_map = {}
                if isinstance(corrected_data, list):
                    for item in corrected_data:
                        if not isinstance(item, dict):
                            logger.warning(f"AI Proofreader: Ignored invalid item format (not dict): {item}")
                            continue
                        if "index" not in item or "text" not in item:
                            logger.warning(f"AI Proofreader: Ignored item missing index or text: {item}")
                            continue

                        try:
                            item_idx = int(item["index"])
                        except (TypeError, ValueError):
                            logger.warning(f"AI Proofreader: Ignored item with invalid index type: {item}")
                            continue

                        # 境界値チェック: 現在のバッチ範囲内に収まっていること
                        if not (i <= item_idx < i + len(batch)):
                            logger.warning(
                                f"AI Proofreader: Ignored out-of-range index {item_idx} "
                                f"(batch range: {i} to {i + len(batch) - 1})"
                            )
                            continue

                        if not isinstance(item["text"], str):
                            logger.warning(f"AI Proofreader: Ignored item with non-string text: {item}")
                            continue

                        # 番号ずれの検知: 元の文とかけ離れた直しは採らない（2026-10-06 実走で、AI が
                        # 短い行「います。」を前に寄せ、以降の文を1つずつ前の行に詰めて返した。
                        # 字幕が前の発話の時刻に出て、0.3 秒ずつに潰れた）
                        neighbours = [segments[k]["text"] for k in (item_idx - 1, item_idx + 1)
                                      if 0 <= k < len(segments)]
                        verdict = _correction_verdict(segments[item_idx]["text"], item["text"],
                                                      neighbours)
                        # 元の文から遠い直しでも、音声認識の文字がはっきり裏付けるなら採る
                        # （「歌詞織」→「菓子折り」を捨てていた・2026-10-06 実走）
                        if verdict == "dissimilar" and referee is not None:
                            try:
                                if referee(segments[item_idx], item["text"]):
                                    verdict = "ok"
                                    stats["refereed_items"] = stats.get("refereed_items", 0) + 1
                                    logger.info(
                                        f"AI Proofreader: 音声認識で裏付けた直しを採りました [{item_idx}] "
                                        f"{segments[item_idx]['text'][:20]!r} → {item['text'][:20]!r}")
                            except Exception as e:  # 裁けなくても校閲は続ける
                                logger.debug(f"音声認識での裏付けをスキップ: {e}")
                        if verdict != "ok":
                            stats["rejected_items"] = stats.get("rejected_items", 0) + 1
                            stats["rejected_rows"].append(item_idx)
                            logger.warning(
                                f"AI Proofreader: 元の文と離れすぎた直しを捨てました [{item_idx}] "
                                f"{segments[item_idx]['text'][:20]!r} → {item['text'][:20]!r}")
                            continue
                        text = item["text"]
                        if item.get("_memo"):
                            stats["memo_hits"] += 1
                            memo_models.add(memo.model_of(keys[item_idx]) or "不明")
                        elif memo is not None:
                            # 文脈の項目を足して校閲し直した行は、前の控えに項目の語の直しだけを足す
                            base, terms = memo.earlier(salt, texts[item_idx], rows)
                            if base is not None:
                                merged = keep_term_edits(base, text, terms)
                                if merged != text:
                                    stats["hint_only_items"] = stats.get("hint_only_items", 0) + 1
                                    logger.info(f"AI Proofreader: 辞書の項目に掛かる直しだけを採りました [{item_idx}] "
                                                f"{text[:24]!r} → {merged[:24]!r}")
                                text = merged
                            memo.put(keys[item_idx], text, served_model)
                        # 校閲が足した字のうち、音声認識が「足さない形」で聞いているものは戻す
                        # （「最初 に 書 に」→「最初にな書に」・2026-10-06 実走）
                        trim = getattr(referee, "trim", None)
                        if trim is not None:
                            try:
                                trimmed = trim(segments[item_idx], text)
                                if trimmed != text:
                                    stats["trimmed_items"] = stats.get("trimmed_items", 0) + 1
                                    logger.info(f"AI Proofreader: 音声に無い足しを戻しました [{item_idx}] "
                                                f"{text[:24]!r} → {trimmed[:24]!r}")
                                    text = trimmed
                            except Exception as e:  # 確かめられなくても校閲は続ける
                                logger.debug(f"音声認識での足しの確認をスキップ: {e}")
                        kept = keep_short_kana_phrases(segments[item_idx]["text"], text)
                        if kept != text:
                            stats["kept_short_phrases"] = stats.get("kept_short_phrases", 0) + 1
                            logger.info(f"AI Proofreader: 相づちの書き換えを戻しました [{item_idx}] "
                                        f"{text[:24]!r} → {kept[:24]!r}")
                            text = kept
                        batch_correction_map[item_idx] = text
                else:
                    # **応答を丸ごと捨てたバッチは失敗に数える**（R2-C5 検証3周目の P1）。黙って無視すると
                    # 記録は「宣言どおり」になり、提案がそのモデルの出力ではないことが見えない
                    logger.warning("AI Proofreader: LLM response corrected_data is not a list")
                    stats["failed_batches"] += 1
                    stats["failed_ranges"].append([i, i + len(batch)])
                    continue

                if not batch_correction_map:
                    # **採用できた項目がゼロのバッチは失敗**（R2-C5 検証4周目の R4-1）。バッチ内の番号で
                    # 答えた・鍵が違う・空リスト、のどれも AI の出力が提案に届いていない。黙って通すと
                    # 記録が「宣言どおり」になる
                    logger.warning("AI Proofreader: no usable item in the response (counted as a failed batch)")
                    stats["failed_batches"] += 1
                    stats["failed_ranges"].append([i, i + len(batch)])
                    continue

                stats["accepted_items"] += len(batch_correction_map)

                # セグメントを更新
                for idx, s in enumerate(batch):
                    abs_index = i + idx
                    if abs_index in batch_correction_map:
                        original = s['text']
                        corrected = batch_correction_map[abs_index]
                        if original != corrected:
                            segments[abs_index]['text'] = corrected
                            proofread_count += 1
                            logger.debug(f"Corrected [{abs_index}]: '{original}' -> '{corrected}'")
            else:
                stats["failed_batches"] += 1
                stats["failed_ranges"].append([i, i + len(batch)])

        if memo is not None:
            memo.save()
            stats["memo_models"] = sorted(memo_models)
            logger.info(f"AI Proofreader: 校閲の控えから {stats['memo_hits']} 行を使いました"
                        f"（{'・'.join(stats['memo_models']) or 'なし'}）")
        stats["proofread_count"] = proofread_count
        # 別の聞き取りを渡した行と、その語（認識の字）が増えた行
        hinted = [(k, r) for k, text in enumerate(before) for r in heard if r[0] in text]
        stats["heard_hints"] = len({k for k, _ in hinted})
        stats["heard_adopted"] = len({k for k, r in hinted
                                      if str(segments[k].get("text") or "").count(r[4]) > before[k].count(r[4])})
        if hinted:
            logger.info(f"AI Proofreader: 別の音声認識の聞き取りを {stats['heard_hints']} 行に渡し、"
                        f"{stats['heard_adopted']} 行で採りました")
        logger.info(f"AI Proofreader: Successfully corrected {proofread_count} segments total."
                     f" (retries={stats['total_retries']}, failed_batches={stats['failed_batches']}/{total_batches})")
        return _return(segments)

    except Exception as e:
        logger.error(f"AI Proofreader Fatal Error: {e}", exc_info=True)
        stats["skipped"] = True
        return _return(segments)


if __name__ == "__main__":
    # 実際の誤変換ケースでテスト
    logging.basicConfig(level=logging.INFO)
    test_segments = [
        {"text": "こんにちは、初夏の北原美玲です。", "start": 0, "end": 5},
        {"text": "えー、あの、本日は久北博之先生にお越しいただいています。", "start": 5, "end": 10}
    ]
    print("--- Before Proofreading ---")
    for s in test_segments:
        print(s['text'])
    
    result = proofread_segments(test_segments)
    
    print("\n--- After Proofreading ---")
    for r in result:
        print(r['text'])
