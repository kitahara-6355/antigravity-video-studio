"""
ProofreadWorker — AI校閲ステージ

固有名詞辞書 + Gemini AI による字幕校閲。
テキスト整形 (18文字/行分割) を含む。
"""

import logging
import asyncio
import time

from agents.pipeline_types import PipelineStageWorker, PipelineContext, StageResult

logger = logging.getLogger(__name__)


class ProofreadWorker(PipelineStageWorker):
    def __init__(self):
        super().__init__("AI校閲", "📝", 1)

    def get_definition_of_done(self) -> str:
        return "全セグメントが校閲済みで、固有名詞誤りがゼロであること"

    async def execute(self, ctx: PipelineContext) -> StageResult:
        """AI校閲を実行

        入力契約:
            ctx.segments: list[dict] — 必須。各dictに text を含む
        出力契約:
            ctx.segments: list[dict] — 校閲済みテキストで更新
            ctx.skipped_features: list[str] — API障害時にスキップ理由を追加
            ctx.warnings: list[str] — API枠制限時に警告を追加
        """
        start = time.time()

        # ctx.segments の型保証と不正な要素の除外、および Segment オブジェクトの dict への変換
        has_segment_objects = False
        if ctx.segments is not None:
            if isinstance(ctx.segments, list):
                valid_segments = []
                for seg in ctx.segments:
                    if isinstance(seg, dict):
                        valid_segments.append(seg)
                    elif hasattr(seg, "to_dict") and hasattr(seg, "from_dict"):
                        valid_segments.append(seg.to_dict())
                        has_segment_objects = True
                    else:
                        logger.warning(f"Ignored invalid segment element: {type(seg)}")
                ctx.segments = valid_segments
            else:
                logger.warning("ctx.segments is not a list. Resetting to empty list.")
                ctx.segments = []
        else:
            ctx.segments = []

        logger.info(f"📊 [T-014] ProofreadWorker入口: ctx.segments={len(ctx.segments)}件")

        # T-018: セグメントなしでも安全に完了
        if not ctx.segments:
            return StageResult(
                stage_name=self.name, success=True,
                detail="セグメントなし — 校閲スキップ",
                data={"dict": 0, "ai": 0, "total": 0, "model_used": "none"},
                duration_seconds=round(time.time() - start, 1),
            )

        dict_corrections = 0
        ai_corrections = 0
        # 控えから使った直しの行数と、その直しを出したモデル（この回には呼んでいない）
        memo_hits, memo_models = 0, []
        # 番号ずれなどで直しを捨てて聞き直した行のうち、採れた行数と、採れずに残った行数
        retried, unproofed = 0, 0
        # 別の音声認識の聞き取り: 文字起こしから来た所・本文と並べて選んだ所・校閲が採った行
        heard = {"given": 0, "chosen": 0, "adopted": 0}
        # 2回目の起こしが割れた所: 候補・本文と並べて選んだ所・字を置いた所
        split = {"given": 0, "chosen": 0, "applied": 0}
        memo = None

        try:
            from proper_noun_dict import apply_dictionary
            for seg in ctx.segments:
                corrected, corrections = apply_dictionary(seg.get("text", ""))
                if corrections:
                    seg["text"] = corrected
                    dict_corrections += len(corrections)
        except Exception as e:
            logger.debug(f"固有名詞辞書適用スキップ: {e}")

        try:
            from subtitle_engine.ai_proofreader import proofread_segments
            original = [s.get("text", "") for s in ctx.segments]
            # UX-01: 同期AI呼び出しをスレッドプールにオフロード
            # → ステータスAPIの応答性を確保し、フロントエンドのタイムアウトを防止
            loop = asyncio.get_running_loop()
            # P-02: return_stats=Trueでリトライ統計を取得
            # 元の文から遠い直しを、音声認識の文字で裁く（認識が使えなければ裁かない）
            referee = await loop.run_in_executor(None, lambda: _referee_for(ctx.video_path))
            extra = {"referee": referee} if referee else {}
            # 一度採った直しは素材ごとに控えて次の書き出しでも使う（同じ入力でも校閲が揺れる・29回目）
            memo = _memo_for(ctx.video_path)
            if memo is not None:
                extra["memo"] = memo
            # 文字起こしで3回目でも決まらなかった所は、認識の字を渡して文脈で決めさせる（46回目の「座右の目」）。
            # 渡すのは、本文と並べて文として選ばせ、両順で認識の字を選んだ所だけ（47回目: そのまま渡すと
            # 「主催→主宰」「細いほど→細いわな」など、本文で通る所まで認識の字にした）
            if getattr(ctx, "heard_hints", None):
                # 聞き取りが無ければ判定は使わない（校閲だけ差し替える試験の偽物にも判定は無い）
                from subtitle_engine.ai_proofreader import judge_heard_hints
                chosen, judged = await loop.run_in_executor(
                    None, lambda: judge_heard_hints(ctx.heard_hints, ctx.segments, memo=memo))
                heard.update(given=len(ctx.heard_hints), chosen=len(chosen), models=judged.get("models") or [],
                             spots=judged.get("spots") or [])
                if judged.get("failed"):  # 字幕は校閲したものなので「AI校閲」の印は付けない（一部未校閲ではない）
                    ctx.warnings.append("別の聞き取り: 選べなかった所は、文字起こしのままにしました")
                if chosen:
                    extra["hints"] = chosen

            def proofread(segs, return_stats=True):
                return proofread_segments(segs, return_stats=return_stats, **extra)

            result = await loop.run_in_executor(None, lambda: proofread(ctx.segments))
            ctx.segments, retry_stats = result
            heard["adopted"] = int(retry_stats.get("heard_adopted", 0) or 0)
            # 失敗したバッチは小さく分けて校閲し直す（2026-10-06: 1/7 バッチが落ち、
            # 「呼んで→読んで」「初回→初会」が未校閲のまま字幕に出た）
            if retry_stats.get("failed_ranges"):
                retry_stats = await loop.run_in_executor(
                    None, lambda: _repair_failed_batches(ctx.segments, retry_stats, proofread))
            # 番号ずれなどで直しを捨てた行は、前後の行を付けた小さいバッチで聞き直す（45回目: 100行の
            # 途中から AI が1〜2行ずつ前の行の文を返し、10行が校閲されないまま残った）
            if retry_stats.get("rejected_rows"):
                retry_stats = await loop.run_in_executor(
                    None, lambda: _retry_rejected_rows(ctx.segments, original, retry_stats, proofread))
                retried, unproofed = int(retry_stats.get("retried_rows", 0) or 0), len(retry_stats["rejected_rows"])
                if unproofed:
                    ctx.warnings.append(f"AI校閲: {unproofed}行は直しが元の文と離れすぎて採れず、校閲していません")
            for i, seg in enumerate(ctx.segments):
                if i < len(original) and seg.get("text", "") != original[i]:
                    ai_corrections += 1
            memo_hits = int(retry_stats.get("memo_hits", 0) or 0)
            memo_models = list(retry_stats.get("memo_models") or [])
            # P-02: リトライ統計の可視化
            if retry_stats.get("total_retries", 0) > 0:
                logger.info(f"🔄 AI校閲リトライ発生: {retry_stats['total_retries']}回 "
                            f"(失敗バッチ: {retry_stats['failed_batches']}/{retry_stats['total_batches']})")
            ctx.proofread_failed_ranges = list(retry_stats.get("failed_ranges") or [])
            if retry_stats.get("failed_batches", 0) > 0:
                ctx.warnings.append(
                    f"AI校閲: {retry_stats['failed_batches']}/{retry_stats['total_batches']}バッチが"
                    f"リトライ上限({retry_stats['total_retries']}回)後に失敗しました。一部セグメントは未校閲です。"
                )
            total = int(retry_stats.get("total_batches", 0) or 0)
            failed = int(retry_stats.get("failed_batches", 0) or 0)
            # **採用した AI の出力の件数を記録に渡す**（宣言どおりは断定ではなく証拠で決める）
            ctx.ai_accepted = {**(getattr(ctx, "ai_accepted", None) or {}),
                               "AI校閲": int(retry_stats.get("accepted_items", 0) or 0)}
            if retry_stats.get("skipped") or (total > 0 and failed >= total):
                # 呼び出しは成功しても**応答を全部捨てた**なら、AI の出力は提案に届いていない
                # （R2-C5 検証3周目の P1）。記録には `ai_skipped` として残る
                if "AI校閲(Gemini)" not in ctx.skipped_features:
                    ctx.skipped_features.append("AI校閲(Gemini)")
        except Exception as e:
            logger.warning(f"Gemini AI proofread skipped: {e}")
            ctx.skipped_features.append("AI校閲(Gemini)")
            ctx.ai_accepted = {**(getattr(ctx, "ai_accepted", None) or {}), "AI校閲": 0}

        # 2回目の起こしが別の字を書き、認識も決め手にならない所（割れた所）は、校閲の後の文と並べて
        # 両順で選ばせ、選んだ所だけ字を置く（48回目の 27分05秒「鳴ってる→なってる」・8分15秒「羽毛→肌着」）。
        # 校閲の前に渡すと、校閲がもう直した所（1分45秒「書道教室」・17分41秒「書道人口」）まで2回目の字
        # （「初動教室」「初動人口」）に戻すおそれがある。校閲が効いていなければ選ばない
        if getattr(ctx, "second_readings", None) and "AI校閲(Gemini)" not in ctx.skipped_features:
            try:
                split = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: _choose_split_readings(ctx, memo))
            except Exception as e:  # noqa: BLE001 — 選べなくても字幕は校閲したもので進む
                logger.warning(f"割れた聞き取りの選び直しをスキップ: {e}")

        # 同じ語の書き分け（「僕」と「ぼく」）を動画の中で多い方にそろえる。校閲は100行ずつ
        # 見るので、動画全体の書き方まではそろわない（33回目・2026-10-13）
        notation = {}
        try:
            from subtitle_engine.notation import unify_notation
            notation = unify_notation(ctx.segments)
        except Exception as e:
            logger.warning(f"表記の統一スキップ: {e}")

        # 辞書は AI の後にもう一度当てる。校閲は辞書の語を自分の知っている字に戻すことがある
        # （2026-10-19: 文字起こしの「久木田ヒロノブ」を「久木田博信」に書き換え、ゼロからの版に残った）
        dict_after_ai = 0
        try:
            from proper_noun_dict import apply_dictionary
            for seg in ctx.segments:
                corrected, corrections = apply_dictionary(seg.get("text", ""))
                if corrected != seg.get("text", ""):  # 正と誤が同じ項目（表記の固定）は数えない
                    seg["text"] = corrected
                    dict_after_ai += sum(c.get("original") != c.get("corrected") for c in corrections)
        except Exception as e:
            logger.debug(f"固有名詞辞書（AI の後）スキップ: {e}")

        # 人が通しで見て直した所（校正台帳）を当てる。文字起こしと校閲は呼ぶたびに揺れるので、
        # 人の直しは AI に渡さず、AI と表記の統一の後・整形の前に毎回同じに当てる（2026-10-17）
        review = {}
        if getattr(ctx, "review_ledger", ""):
            try:
                from subtitle_engine import review_ledger
                review = {"ledger": str(ctx.review_ledger),
                          **review_ledger.apply(ctx.segments, review_ledger.load(ctx.review_ledger))}
            except Exception as e:  # noqa: BLE001 — 台帳が当たらなくても字幕は校閲したもので進む
                logger.warning(f"校正台帳スキップ: {e}")
                ctx.warnings.append(f"校正台帳を当てられませんでした（{e}）。人の直しが入っていません")
            if review.get("missing"):
                at = "・".join(f"{int(m['at']) // 60}分{int(m['at']) % 60:02d}秒" for m in review["missing"])
                ctx.warnings.append(f"校正台帳: {len(review['missing'])}件の直しが当たりませんでした（素材の {at}）。"
                                    "その所は字が変わっているので見直しが要ります")
            if review.get("near"):
                at = "・".join(f"{int(m['at']) // 60}分{int(m['at']) % 60:02d}秒" for m in review["near"])
                ctx.warnings.append(f"校正台帳: {len(review['near'])}件の直しを、字が少し違う所に当てました（素材の {at}）。"
                                    "当てた所が合っているか見直しが要ります")

        # ━━━ FIX-3A: テキスト整形（旧 src/clean_linguistic.py 復元） ━━━
        # 長文を18文字/行に分割し、字幕の画面はみ出しを防止
        format_stats = ""
        try:
            from subtitle_engine.text_formatter import format_segments, get_max_chars_from_template
            before_count = len(ctx.segments)
            # T-016 B案: format_segments前にsourceStart/sourceEndを保護
            # format_segmentsはstart/endを文字数按分で再計算するが、
            # sourceStart/sourceEnd is 元のWhisperタイムスタンプとして不変であるべき
            source_timestamps = {}
            for i, seg in enumerate(ctx.segments):
                if "sourceStart" in seg or "sourceEnd" in seg:
                    source_timestamps[i] = {
                        "sourceStart": seg.get("sourceStart"),
                        "sourceEnd": seg.get("sourceEnd"),
                    }
            max_chars = get_max_chars_from_template()
            ctx.segments = format_segments(ctx.segments, max_chars=max_chars)
            # sourceStart/sourceEnd再注入: 分割されたセグメントにも元の範囲を維持
            if source_timestamps:
                for seg in ctx.segments:
                    # 片方でも欠けている場合は再注入
                    if "sourceStart" not in seg or "sourceEnd" not in seg:
                        seg_start = seg.get("start", 0)
                        if seg_start is not None:
                            for orig_idx, ts in source_timestamps.items():
                                ts_start = ts.get("sourceStart")
                                ts_end = ts.get("sourceEnd")
                                
                                match_start = True
                                match_end = True
                                if ts_start is not None:
                                    match_start = (ts_start - 1e-5) <= seg_start
                                if ts_end is not None:
                                    match_end = seg_start <= (ts_end + 1e-5)
                                    
                                if (ts_start is not None or ts_end is not None) and match_start and match_end:
                                    seg["sourceStart"] = ts_start
                                    seg["sourceEnd"] = ts_end
                                    break
            after_count = len(ctx.segments)
            if after_count != before_count:
                format_stats = f" / 整形{before_count}→{after_count}箇所"
        except Exception as e:
            logger.warning(f"テキスト整形スキップ: {e}")

        total = dict_corrections + ai_corrections
        memo_note = f" / 校閲の控え{memo_hits}行（{'・'.join(memo_models) or '不明'}）" if memo_hits else ""
        retry_note = (f" / 番号ずれの聞き直し{retried}行" if retried else "") + \
            (f"（未校閲{unproofed}行）" if unproofed else "")
        notation_note = f" / 表記{sum(notation.values())}件" if notation else ""
        after_note = f" / AI の後に辞書{dict_after_ai}件" if dict_after_ai else ""
        heard_note = (f" / 別の聞き取り{heard['given']}か所中 選んだ{heard['chosen']}・採った{heard['adopted']}"
                      if heard["given"] else "")
        split_note = (f" / 割れた聞き取り{split['given']}か所中 選んだ{split['chosen']}・置いた{split['applied']}"
                      if split["given"] else "")
        review_note = ""
        if review:
            review_note = (f" / 人の直し{len(review['applied'])}件"
                           + (f"（既に直っていた{len(review['already'])}件）" if review["already"] else "")
                           + (f"（字の近い所に当てた{len(review['near'])}件）" if review.get("near") else "")
                           + (f"（当たらない{len(review['missing'])}件）" if review["missing"] else "")
                           + (f" / 用語{sum(review['glossary'].values())}件" if review["glossary"] else ""))
        # 使用モデルを取得（UI可視化用）
        try:
            from subtitle_engine.ai_proofreader import _get_current_model
            model_used = _get_current_model()
        except Exception:
            model_used = "unknown"
        # UX-15: API枠枯渇等でAI校閲がスキップされた場合、detailに警告を表示
        skip_warn = ""
        if "AI校閲(Gemini)" in ctx.skipped_features:
            # 理由を決めつけない（4周目の m3）: 枠制限のほかに、応答を全部捨てた場合もここに来る
            skip_warn = " ⚠️ AI校閲は効いていない"
            ctx.warnings.append("AI校閲は効いていません（API 枠の制限か、応答を使えなかった）。品質に影響する可能性があります。")
        # 元が Segment オブジェクトだった場合は、元の型に復元する
        if ctx.segments and has_segment_objects:
            try:
                from agents.pipeline_types import Segment
                restored_segments = []
                for seg in ctx.segments:
                    if isinstance(seg, dict):
                        restored_segments.append(Segment.from_dict(seg))
                    else:
                        restored_segments.append(seg)
                ctx.segments = restored_segments
            except (ImportError, KeyError, TypeError, ValueError) as e:
                logger.error(f"Failed to restore Segment objects: {e}")

        logger.info(f"📊 [T-014] ProofreadWorker出口: ctx.segments={len(ctx.segments)}件")
        return StageResult(
            stage_name=self.name, success=True,
            detail=f"辞書{dict_corrections}件 + AI{ai_corrections}件 = {total}件修正{memo_note}{retry_note}"
                   f"{heard_note}{split_note}{notation_note}{after_note}{review_note}{format_stats}{skip_warn}",
            data={"dict": dict_corrections, "ai": ai_corrections, "total": total, "model_used": model_used,
                  "dict_after_ai": dict_after_ai,
                  "memo_hits": memo_hits, "memo_models": memo_models, "notation": notation, "heard": heard,
                  "split": split, "review": review},
            duration_seconds=round(time.time() - start, 1),
        )


# 失敗したバッチを半分ずつに分けて校閲し直す回数
REPAIR_ROUNDS = 2


def _choose_split_readings(ctx, memo) -> dict:
    """2回目の起こしが割れた所を、校閲の後の文（ctx.segments）と並べて選ばせ、選んだ所の字を置く。

    返り値は記録に残す集計（given・chosen・applied・models・spots）。候補は
    `transcript_fusion.split_spots`（辞書の語は誤りの字も正しい字も候補にしない）。
    """
    from subtitle_engine import aligner, transcript_fusion
    from subtitle_engine.ai_proofreader import apply_hints, judge_heard_hints
    tokens = aligner.tokens_for(str(ctx.video_path))
    protect = [w for pair in aligner._dictionary_terms() for w in pair]
    spots = transcript_fusion.split_spots(ctx.segments, ctx.second_readings, tokens, protect=protect)
    hints = transcript_fusion.heard_hints(ctx.segments, spots, [("open", "")] * len(spots))
    split = {"given": len(hints), "chosen": 0, "applied": 0}
    if not hints:
        return split
    chosen, judged = judge_heard_hints(hints, ctx.segments, memo=memo)
    split.update(chosen=len(chosen), applied=apply_hints(ctx.segments, chosen),
                 models=judged.get("models") or [], spots=judged.get("spots") or [])
    if judged.get("failed"):
        ctx.warnings.append("割れた聞き取り: 選べなかった所は、校閲のままにしました")
    logger.info(f"🗳️ 2回目の起こしが割れた {len(hints)} か所を校閲の後の文と並べて選ばせ、"
                f"{split['applied']} か所の字を置きました（選んだ {len(chosen)}）")
    return split


def _referee_for(video_path):
    """校閲の直しを裁く関数（音声認識）。使えなければ None。"""
    try:
        from subtitle_engine import aligner
        return aligner.referee_for(str(video_path)) if video_path else None
    except Exception as e:  # 認識が無くても校閲はする
        logger.debug(f"音声認識での裏付けを使いません: {e}")
        return None


def _memo_for(video_path):
    """素材ごとの校閲の控え（素材と同じ場所の `_proofread_<鍵>.json`）。作れなければ None。

    鍵は素材の中身（`video_hash.material_cache`。音声認識・映像の切り替わりの控えと同じ決め方）。
    素材が変われば別の控え。素材を別の場所に置いても、控えを隣に戻せば使える。
    """
    try:
        from subtitle_engine.ai_proofreader import ProofreadMemo
        from subtitle_engine.video_hash import material_cache
        return ProofreadMemo(material_cache(str(video_path), "_proofread_"))
    except Exception as e:  # 控えが無くても校閲はする
        logger.debug(f"校閲の控えを使いません: {e}")
        return None


def _repair_failed_batches(segments, stats, proofread):
    """失敗した範囲を半分に分けて校閲し直す。残った失敗の数で stats を更新して返す。

    proofread は渡したリストの字幕（dict）をその場で直す。
    """
    ranges = [tuple(r) for r in stats.get("failed_ranges") or []]
    stats = dict(stats)
    for _ in range(REPAIR_ROUNDS):
        if not ranges:
            break
        left = []
        for a, b in ranges:
            mid = (a + b + 1) // 2
            for lo, hi in ((a, mid), (mid, b)) if b - a > 1 else ((a, b),):
                if hi <= lo:
                    continue
                _, sub = proofread(segments[lo:hi], return_stats=True)
                stats["total_retries"] = stats.get("total_retries", 0) + 1
                stats["accepted_items"] = stats.get("accepted_items", 0) + int(sub.get("accepted_items", 0) or 0)
                stats["rejected_rows"] = list(stats.get("rejected_rows") or []) + [
                    lo + k for k in sub.get("rejected_rows") or []]
                if sub.get("failed_batches") or sub.get("skipped"):
                    left.append((lo, hi))
        ranges = left
    repaired = len(stats.get("failed_ranges") or []) - len(ranges)
    logger.info(f"🔁 AI校閲の失敗バッチを分けて再実行: 残った失敗 {len(ranges)}件")
    stats["failed_ranges"] = [list(r) for r in ranges]
    stats["failed_batches"] = len(ranges)
    stats["repaired_batches"] = max(0, repaired)
    return stats


# 番号ずれなどで直しを捨てた行を聞き直すとき、前後に付ける行数と、1バッチの行数の上限
# （100行のバッチでずれた。前後の数行があれば同音の語を文脈で直せる）
RETRY_CONTEXT = 4
RETRY_MAX_ROWS = 30


def _retry_windows(rows, n):
    """聞き直す行を、前後 RETRY_CONTEXT 行を付けた [lo, hi) のまとまりに分ける（RETRY_MAX_ROWS 行まで）。

    返り値は [(lo, hi, そのまとまりで聞き直す行)]。
    """
    windows = []
    for r in sorted(set(rows)):
        lo, hi = max(0, r - RETRY_CONTEXT), min(n, r + RETRY_CONTEXT + 1)
        if windows and lo <= windows[-1][1] and hi - windows[-1][0] <= RETRY_MAX_ROWS:
            windows[-1] = (windows[-1][0], hi, windows[-1][2] + [r])
        else:
            windows.append((lo, hi, [r]))
    return windows


def _retry_rejected_rows(segments, original, stats, proofread):
    """番号ずれなどで直しを捨てた行を、前後の行を付けた小さいバッチで校閲し直す。stats を更新して返す。

    渡すのは校閲の前の文（original）。直すのは捨てた行だけで、前後の行は文脈（1回目の直しのまま）。
    失敗したバッチの再実行で直った行は聞き直さない。聞き直しても捨てた行は stats["rejected_rows"] に残す。
    proofread は渡したリストの字幕（dict）をその場で直す。
    """
    stats = dict(stats)
    rows = [r for r in sorted(set(stats.get("rejected_rows") or []))
            if r < len(segments) and segments[r].get("text", "") == original[r]]
    left, retried = [], 0
    for lo, hi, targets in _retry_windows(rows, len(segments)):
        part = [dict(segments[k], text=original[k]) for k in range(lo, hi)]
        _, sub = proofread(part, return_stats=True)
        stats["total_retries"] = stats.get("total_retries", 0) + 1
        if sub.get("failed_batches") or sub.get("skipped"):
            left.extend(targets)
            continue
        again = {lo + k for k in sub.get("rejected_rows") or []}
        for r in targets:
            if r in again:
                left.append(r)
            else:
                segments[r]["text"] = part[r - lo]["text"]
                retried += 1
    if rows:
        logger.info(f"🔁 AI校閲で直しを捨てた {len(rows)} 行を小さいバッチで聞き直し: "
                    f"{retried} 行を採り、{len(left)} 行は校閲せずに残しました")
    stats["accepted_items"] = stats.get("accepted_items", 0) + retried
    stats["retried_rows"] = retried
    stats["rejected_rows"] = left
    return stats

