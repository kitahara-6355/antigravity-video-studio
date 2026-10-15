"""
TranscribeWorker — 文字起こしステージ

Whisperサブプロセスによる音声文字起こし。
CTranslate2デストラクタ→CUDAクラッシュ回避のためサブプロセス分離。
チェックポイント(JSONL)による冪等性を保証。

**エンジンは2つ**（2026-09-26 ユーザー決定: 主は Gemini 音声入力、従は Whisper）。
`AVS_TRANSCRIBE_ENGINE=gemini` で Gemini（`subtitle_engine.gemini_transcriber`）を使い、
落ちたら Whisper に切り替える（切り替えた事実は警告と結果に残す）。
既定は whisper のまま — Gemini は課金経路なので、明示した実走だけが叩く。
"""

import functools
import json
import logging
import asyncio
import os
import time
import sys
import subprocess
import threading
from pathlib import Path

from agents.pipeline_types import PipelineStageWorker, PipelineContext, StageResult

logger = logging.getLogger(__name__)

ENGINE_ENV = "AVS_TRANSCRIBE_ENGINE"
ENGINES = ("whisper", "gemini")


def transcribe_engine() -> str:
    """この実走の文字起こしエンジン。知らない値は whisper に倒さず止める。"""
    engine = (os.environ.get(ENGINE_ENV) or "whisper").strip().lower()
    if engine not in ENGINES:
        raise ValueError(f"{ENGINE_ENV}={engine!r} は使えません（{' / '.join(ENGINES)}）")
    return engine


def _gemini_checkpoint(whisper_checkpoint: str, second: bool = False, third: bool = False,
                       second_tag: str | None = None) -> str:
    """Gemini の起こしのキャッシュ。**刻み方が変わったら別のキャッシュにする**
    （120 秒チャンクで欠落した起こしを、30 秒に変えた後も使い回さないため。
    30 秒ごとの機械的な区切りの起こしを、話の切れ目で区切るようにした後も使い回さないため）。
    second なら2回目の起こし（区切りをずらしたもの。second_tag を渡すと前の区切り方のもの）、
    third なら3回目の起こし（決めきれない所だけ。区間ごとの控えがそのままキャッシュ）のキャッシュ。"""
    from subtitle_engine.gemini_transcriber import (
        CHUNK_SEC, CUT_TAG, SECOND_PASS_TAG, THIRD_LOOK_TAG)
    p = Path(whisper_checkpoint)
    name = p.name.replace("_whisper_", "_gemini_", 1)
    tag = CUT_TAG + ((second_tag or SECOND_PASS_TAG) if second else THIRD_LOOK_TAG if third else "")
    if CHUNK_SEC != 120 or second or third:  # 120 秒時代のキャッシュ名はそのまま読めるようにしておく
        name = name.replace("_gemini_", f"_gemini_c{CHUNK_SEC}{tag}_", 1)
    return str(p.with_name(name))


class TranscribeWorker(PipelineStageWorker):
    def __init__(self):
        super().__init__("文字起こし", "🎤", 0)

    def get_definition_of_done(self) -> str:
        return "字幕セグメントが1件以上生成され、各セグメントにタイムスタンプが付与されていること"

    def _load_segments_from_checkpoint(self, checkpoint_path: Path | str) -> list[dict]:
        """チェックポイントファイルからセグメントを読み込みます。
        
        パースエラーが発生した行は警告ログを出力してスキップし、可能な限り復旧します。
        """
        path = Path(checkpoint_path)
        if not path.exists():
            return []

        segments = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    segments.append(json.loads(line))
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"⚠️ チェックポイント行のパースに失敗しました（スキップします）: {e}")
        return segments

    def _read_stdout_worker(self, proc: subprocess.Popen, state: dict) -> None:
        """スレッド内で実行されるstdout読み取り処理"""
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if "progress" in data:
                        logger.info(f"文字起こし進捗: {data['progress']}%")
                    if "status" in data:
                        state["last_result"] = data
                except (json.JSONDecodeError, ValueError):
                    pass
        except (ValueError, OSError) as e:
            logger.debug(f"stdout読取スレッド終了 (想定内): {e}")
        except (AttributeError, TypeError, KeyError, RuntimeError) as e:
            state["thread_exception"] = e
            logger.error(f"stdout読取スレッドで予期しない例外が発生: {e}", exc_info=True)

    def _handle_timeout(self, proc: subprocess.Popen, checkpoint_path: str, model_size: str, timeout: int) -> dict:
        """タイムアウト発生時の後処理とリカバリを試みる"""
        logger.error(f"⏰ Whisperサブプロセスがタイムアウト({timeout}秒) — 強制終了")
        proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("⚠️ サブプロセスがkill後も正常終了しませんでした")

        # チェックポイントが途中まで書けていれば使う
        cp_file = Path(checkpoint_path)
        if cp_file.exists() and cp_file.stat().st_size > 500:
            logger.warning("⚠️ タイムアウトだがチェックポイントあり — 部分結果で続行")
            return {"status": "completed", "device": "timeout_partial", "model": model_size}
        raise RuntimeError(f"Whisperサブプロセスが{timeout}秒でタイムアウト")

    def _run_whisper_subprocess(self, video_path: str, checkpoint_path: str, model_size: str) -> dict:
        """サブプロセスでWhisperを実行（タイムアウト付き）"""
        whisper_script = str(Path(__file__).parent.parent.parent / "subtitle_engine" / "whisper_subprocess.py")
        TIMEOUT = 3600  # 60分タイムアウト（CPUモードでの長尺動画処理を保証）

        # 言語パラメータ "ja" の伝搬確認テストのために "ja" の記載を残す
        proc = subprocess.Popen(
            [sys.executable, whisper_script, video_path, checkpoint_path, model_size, "ja"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace"
        )

        state = {"last_result": None, "thread_exception": None}
        reader_thread = threading.Thread(
            target=self._read_stdout_worker,
            args=(proc, state),
            daemon=True
        )
        reader_thread.start()

        stderr_out = ""
        try:
            # タイムアウト付きで完了を待つ
            try:
                proc.wait(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                try:
                    stderr_out = proc.stderr.read() if proc.stderr else ""
                except OSError:
                    pass
                return self._handle_timeout(proc, checkpoint_path, model_size, TIMEOUT)
            finally:
                # 読込スレッドの終了を待つ
                if reader_thread.is_alive():
                    reader_thread.join(timeout=5)
                # エラー出力の先取り (パイプを閉じる前)
                if proc.returncode != 0:
                    try:
                        stderr_out = proc.stderr.read() if proc.stderr else ""
                    except (OSError, ValueError):
                        pass
        finally:
            # 1. パイプのクローズ
            for pipe in (proc.stdout, proc.stderr):
                if pipe and hasattr(pipe, "close"):
                    try:
                        pipe.close()
                    except OSError:
                        pass
            # 2. プロセスの確実な回収（ゾンビプロセス防止）
            if proc.poll() is None:
                logger.warning("⚠️ サブプロセスがまだ実行中のため、強制終了します")
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except OSError as e:
                    logger.error(f"サブプロセスの強制終了中にエラーが発生しました: {e}")
        logger.info(f"Whisperサブプロセス終了: exit_code={proc.returncode}")

        thread_exception = state["thread_exception"]
        if thread_exception:
            raise RuntimeError(f"stdout読取スレッドで予期しない例外が発生しました: {thread_exception}") from thread_exception

        last_result = state["last_result"]
        if last_result and last_result.get("status") == "completed":
            return last_result

        # フォールバック: stdoutパース失敗でも、チェックポイントファイルが存在すれば成功とみなす
        cp_file = Path(checkpoint_path)
        if proc.returncode == 0 and cp_file.exists() and cp_file.stat().st_size > 1000:
            logger.warning("⚠️ サブプロセスのstdout解析失敗、チェックポイントファイルから復旧")
            return {"status": "completed", "device": "unknown", "model": model_size}

        # **末尾を出す。** 先頭は起動時の INFO ログで埋まり、原因（例外）が切れて見えなかった
        raise RuntimeError(f"Whisperサブプロセス失敗: exit={proc.returncode}, stderr=…{stderr_out[-800:]}")

    async def execute(self, ctx: PipelineContext) -> StageResult:
        """文字起こしを実行

        入力契約:
            ctx.video_path: str — 必須。動画ファイルパス（音声トラック含む）
        出力契約:
            ctx.segments: list[dict] — {start, end, text, sourceStart, sourceEnd}
        """
        start = time.time()
        try:
            # T-028: 動画ファイル固有のハッシュ付きチェックポイントパス
            from subtitle_engine.video_hash import compute_video_hash, get_checkpoint_path as _get_cp, OLD_CHECKPOINT_NAME
            checkpoint_path = _get_cp(ctx.video_path)

            # T-029: 旧形式キャッシュ (_whisper_segments.jsonl) の検出と無視
            old_checkpoint = Path(ctx.video_path).parent / OLD_CHECKPOINT_NAME
            if old_checkpoint.exists():
                logger.info(f"⚠️ 旧形式キャッシュ検出 — 無視します: {old_checkpoint}")

            engine = transcribe_engine()
            if engine == "gemini":
                result = await self._execute_gemini(ctx, checkpoint_path, start)
                if result is not None:
                    return result
                # 落ちた → Whisper へ（切り替えた事実は _execute_gemini が警告に残した）

            # 既存のチェックポイントがある場合はWhisperを完全スキップ
            if Path(checkpoint_path).exists() and Path(checkpoint_path).stat().st_size > 1000:
                logger.info(f"📋 既存チェックポイント検出 — Whisperスキップ: {checkpoint_path}")
                segments = self._load_segments_from_checkpoint(checkpoint_path)
                ctx.segments = segments
                return StageResult(
                    stage_name=self.name, success=True,
                    detail=f"{len(segments)}セグメント検出 (キャッシュ)",
                    data={"segment_count": len(segments), "model": "cached"},
                    duration_seconds=round(time.time() - start, 1),
                )

            # model_size_is_small テストのために model_size = "small" の表記を残す
            model_size = "small"  # medium→small: 8GB VRAMで長尺動画のOOM回避
            logger.info(f"🚀 Whisperサブプロセス起動: model={model_size}")
            logger.info(f"📐 出力: {checkpoint_path}")

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, self._run_whisper_subprocess, ctx.video_path, checkpoint_path, model_size
            )

            # チェックポイントからセグメントを読み込み
            logger.info(f"📖 チェックポイントからセグメント読み込み: {checkpoint_path}")
            segments = self._load_segments_from_checkpoint(checkpoint_path)
            ctx.segments = segments
            logger.info(f"📊 [T-013] TranscribeWorker出口: ctx.segments={len(ctx.segments)}件")

            device_info = result.get("device", "unknown")
            return StageResult(
                stage_name=self.name, success=True,
                detail=f"{len(segments)}セグメント検出 (GPU={device_info=='cuda'}, model={model_size})",
                data={"segment_count": len(segments), "model": model_size, "device": device_info},
                duration_seconds=round(time.time() - start, 1),
            )
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError) as e:
            logger.error(f"TranscribeWorker.execute で例外が発生しました: {e}", exc_info=True)
            return StageResult(
                stage_name=self.name, success=False,
                detail=str(e), duration_seconds=round(time.time() - start, 1),
            )

    async def _execute_gemini(self, ctx: PipelineContext, whisper_checkpoint: str,
                              start: float):
        """Gemini で起こす。**落ちたら `None`**（呼び出し側が Whisper に切り替える）。"""
        checkpoint = _gemini_checkpoint(whisper_checkpoint)
        if Path(checkpoint).exists() and Path(checkpoint).stat().st_size > 1000:
            from subtitle_engine import gemini_transcriber
            segments = self._read_gemini_checkpoint(checkpoint)
            meta = gemini_transcriber.read_meta(checkpoint)
            segments, fusion = await self._second_pass(ctx, whisper_checkpoint, segments,
                                                       meta.get("cuts") or ())
            ctx.segments = segments
            ctx.verified_quiet = [tuple(q) for q in meta.get("quiet", [])]
            ctx.transcript_coverage = meta.get("coverage")
            return StageResult(
                stage_name=self.name, success=True,
                detail=f"{len(segments)}セグメント検出 (Gemini・キャッシュ)",
                data={"segment_count": len(segments), "engine": "gemini", "model": "cached",
                      "second_pass": fusion},
                duration_seconds=round(time.time() - start, 1),
            )
        try:
            from subtitle_engine import gemini_transcriber
            loop = asyncio.get_running_loop()
            journal = gemini_transcriber.journal_path(checkpoint)
            tx = await loop.run_in_executor(None, functools.partial(
                gemini_transcriber.transcribe, ctx.video_path, journal=journal))
            gemini_transcriber.write_checkpoint(
                tx.segments, checkpoint,
                meta={"quiet": tx.quiet, "coverage": tx.coverage, "rechecked": tx.rechecked,
                      "cuts": tx.cuts})
            journal.unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001 — 主経路の失敗は従経路へ。理由は残す
            logger.warning(f"⚠️ Gemini 文字起こしに失敗 → Whisper に切り替えます: {e}")
            ctx.warnings.append(f"文字起こし: Gemini が失敗したため Whisper に切り替えました（{e}）")
            return None
        segments, fusion = await self._second_pass(ctx, whisper_checkpoint, tx.segments, tx.cuts)
        ctx.segments = segments
        ctx.verified_quiet = list(tx.quiet)
        ctx.transcript_coverage = tx.coverage
        return StageResult(
            stage_name=self.name, success=True,
            detail=f"{len(segments)}セグメント検出 (Gemini {', '.join(tx.models_used)}・{tx.chunks}チャンク)",
            data={"segment_count": len(segments), "engine": "gemini", "model": tx.model,
                  "models_used": tx.models_used, "chunks": tx.chunks,
                  "rechecked": tx.rechecked, "coverage": tx.coverage, "second_pass": fusion},
            duration_seconds=round(time.time() - start, 1),
        )

    def _read_gemini_checkpoint(self, checkpoint: str) -> list[dict]:
        from subtitle_engine import gemini_transcriber
        meta = gemini_transcriber.read_meta(checkpoint)
        return gemini_transcriber.drop_boundary_echoes(gemini_transcriber.join_spaced_words(
            self._load_segments_from_checkpoint(checkpoint)), cuts=meta.get("cuts"))

    async def _second_pass(self, ctx: PipelineContext, whisper_checkpoint: str,
                           segments: list[dict],
                           cuts: list[float] | tuple = ()) -> tuple[list[dict], dict | None]:
        """区切りをずらしてもう1回起こし、食い違いを手元の音声認識で決める（`transcript_fusion`）。

        区切りを変えると Gemini の聞き違いが別の所に出る（2026-10-06 実測）。cuts は1回目の区切りで、
        2回目はそこから離して切る（`gemini_transcriber.SECOND_PASS_GAP_SEC`）。前の区切り方の2回目の
        キャッシュは、区切りが変わらないチャンクを写す元にし、いまの2回目の後にもう1つの聞き取りとして
        突き合わせる（集計の `earlier`）。認識が使えない・2回目が落ちたら1回目のまま進む（2回目は
        直すためだけに使う）。返り値は (行, 集計)。
        """
        from subtitle_engine import aligner, gemini_transcriber, transcript_fusion
        if not gemini_transcriber.SECOND_PASS:
            return segments, None
        loop = asyncio.get_running_loop()
        tokens = await loop.run_in_executor(None, aligner.tokens_for, str(ctx.video_path))
        if not tokens:
            logger.info("手元の音声認識が使えないので、文字起こしの2回目は飛ばします")
            return segments, None
        checkpoint = _gemini_checkpoint(whisper_checkpoint, second=True)
        earlier = [(t, c) for t, c in ((t, _gemini_checkpoint(whisper_checkpoint, second=True, second_tag=t))
                                       for t in gemini_transcriber.SECOND_PASS_EARLIER_TAGS)
                   if Path(c).exists() and Path(c).stat().st_size > 1000]
        if Path(checkpoint).exists() and Path(checkpoint).stat().st_size > 1000:
            second = self._read_gemini_checkpoint(checkpoint)
            made = gemini_transcriber.read_meta(checkpoint)
        else:
            try:
                journal = gemini_transcriber.journal_path(checkpoint)
                tx = await loop.run_in_executor(None, functools.partial(
                    gemini_transcriber.transcribe, ctx.video_path,
                    first_chunk_sec=gemini_transcriber.SECOND_PASS_FIRST_SEC, avoid_cuts=list(cuts),
                    journal=journal, earlier=[c for _, c in earlier]))
                made = {"cuts": tx.cuts, "models_used": tx.models_used, "carried": tx.carried}
                gemini_transcriber.write_checkpoint(tx.segments, checkpoint, meta=made)
                journal.unlink(missing_ok=True)
                second = tx.segments
            except Exception as e:  # noqa: BLE001 — 2回目は直すためだけ。落ちても1回目で進む
                logger.warning(f"⚠️ 文字起こしの2回目に失敗 → 1回目のまま進みます: {e}")
                ctx.warnings.append(f"文字起こし: 2回目（聞き違いの突き合わせ）に失敗したため1回目のまま進みました（{e}）")
                return segments, None
        fused, stats = transcript_fusion.fuse(segments, second, tokens, cuts=list(cuts))
        # 2回目のモデルも実行記録に残す（前の区切り方から写したチャンクはモデルを記録していないことがある）
        stats = dict(stats, models=list(made.get("models_used") or []), carried=int(made.get("carried") or 0))
        logger.info(f"🗳️ 文字起こしの2回目と突き合わせ: 食い違い {stats['differences']} か所のうち "
                    f"{stats['adopted']} か所を、2回目と手元の音声認識が同じ字に直しました")
        # 前の区切り方の2回目も、もう1つの聞き取りとして突き合わせる。区切りが違えば聞き違える所も
        # 違うので、捨てると、前の2回目が正しかった所が1回目の字に戻る（45回目: 2回目を起こし直したら
        # 締めの「絶やして」「増やしていく」や「豊橋筆」「書道家」が戻った。突き合わせると 44 か所を直し、
        # 変わった 39 行のうち 36 行が認識に近づいた。遠のいたのは「これね」「なんというのか」の2行・2026-10-15）
        stats["earlier"], readings = [], [second]
        for tag, path in earlier:
            readings.append(self._read_gemini_checkpoint(path))
            fused, more = transcript_fusion.fuse(fused, readings[-1], tokens, cuts=list(cuts))
            stats["earlier"].append({"tag": tag, "differences": more["differences"], "adopted": more["adopted"]})
            logger.info(f"🗳️ 前の区切り方の2回目（{tag}）とも突き合わせ: 食い違い {more['differences']} か所のうち "
                        f"{more['adopted']} か所を直しました")
        fused, look = await self._third_look(ctx, whisper_checkpoint, fused, readings, tokens)
        if look is not None:
            stats = dict(stats, third_look=look)
        return fused, stats

    async def _third_look(self, ctx: PipelineContext, whisper_checkpoint: str, fused: list[dict],
                          readings: list[list[dict]], tokens: list) -> tuple[list[dict], dict | None]:
        """2回でも決めきれない所だけ、そこが真ん中に来るように区切ってもう1回起こして決める。

        2回の起こしが同じ所で聞き違えると突き合わせても直らない（3分03秒「普通泣いて帰ったら」）。
        候補は `transcript_fusion.look_spots`、裁きは `transcript_fusion.judge`。3回目で決まらない所は
        区間の前後の余白を広げて読み直す（`gemini_transcriber.LOOK_PADS`。区間の長さで聞き取りが変わる）。
        区間ごとの控えがキャッシュで、候補が変わらなければ2回目以降の実行は呼ばない。
        認識だけが別の字を聞いた所（2回とも同じ字の "swap"、2回が食い違ってどちらも聞こえない "neither"）は、
        種類ごとに別の区間で読む（同じ区間にまとめると、先にあった候補の区間が変わって控えが使えず、
        直っていた所を読み直すことになる）。辞書の語は候補にしない。
        落ちたら、それまでに決まった所だけを直して進む（3回目は直すためだけに使う）。
        readings は2回目の起こし（いまの区切り方のもの、前の区切り方のもの）。候補は起こしごとに探して
        まとめる（前の区切り方の2回目だけが1字消した所も読む。45回目の後に「書道で→書で」などが戻った）。
        3回目でも決まらない所は、校閲に「別の聞き取り」として渡す（`ctx.heard_hints`。Gemini は何度
        起こしても「座右の目」と書き、認識は「座右の銘」と聞いた・46回目）。
        """
        from subtitle_engine import aligner, gemini_transcriber, transcript_fusion
        if not gemini_transcriber.THIRD_LOOK:
            return fused, None
        protect = [correct for _, correct in aligner._dictionary_terms()]
        spots, taken = [], set()
        for reading in readings:
            for spot in transcript_fusion.look_spots(fused, reading, tokens, protect=protect):
                if (spot["row"], spot["c0"], spot["c1"]) not in taken:
                    taken.add((spot["row"], spot["c0"], spot["c1"]))
                    spots.append(spot)
        if not spots:
            return fused, {"spots": 0, "windows": 0, "adopted": 0, "examples": []}
        loop = asyncio.get_running_loop()
        rows = [fused[s["row"]] for s in spots]
        spans = [(float(r.get("start") or 0), float(r.get("end") or r.get("start") or 0)) for r in rows]
        verdicts = [("open", "")] * len(spots)
        windows, models, error = 0, set(), None
        try:
            quiet = await loop.run_in_executor(None, gemini_transcriber.QuietMap.from_media, str(ctx.video_path))
            journal = gemini_transcriber.journal_path(_gemini_checkpoint(whisper_checkpoint, third=True))
            for kinds in (("omit", "drop"), ("swap",), ("neither",)):
                for pad in gemini_transcriber.LOOK_PADS:
                    pending = [i for i, (verdict, _) in enumerate(verdicts)
                               if verdict == "open" and spots[i]["kind"] in kinds]
                    if not pending:
                        break
                    for w in gemini_transcriber.look_windows([spans[i] for i in pending], quiet, pad=pad):
                        third, used = await loop.run_in_executor(None, functools.partial(
                            gemini_transcriber.transcribe_windows, ctx.video_path, [w], journal=journal))
                        windows += 1
                        models.update(used)
                        # 行の真ん中が入る区間の起こしだけで裁く（重なる区間の起こしを混ぜない）
                        for i in pending:
                            if verdicts[i][0] == "open" and w[0] <= sum(spans[i]) / 2 <= w[0] + w[1]:
                                verdicts[i] = transcript_fusion.judge(fused, third, spots[i])
        except Exception as e:  # noqa: BLE001 — 3回目は直すためだけ。落ちても決まった所だけ直して進む
            error = str(e)
            logger.warning(f"⚠️ 文字起こしの3回目に失敗 → 決まった所だけ直して進みます: {e}")
            ctx.warnings.append(f"文字起こし: 3回目（決めきれない所の起こし直し）に失敗したため、"
                                f"それまでに決まった所だけを直して進みました（{e}）")
        settled, look = transcript_fusion.settle(fused, spots, verdicts)
        ctx.heard_hints = transcript_fusion.heard_hints(fused, spots, verdicts, settled)
        look.update(spots=len(spots), windows=windows, models=sorted(models), hints=len(ctx.heard_hints))
        if error is not None:
            look["error"] = error
        logger.info(f"🔍 決めきれない {len(spots)} か所を {windows} 区間で起こし直し、{look['adopted']} か所を"
                    f"3回目と手元の音声認識がそろう字に直しました（そのまま {look['kept']}・決まらない {look['open']}）。"
                    f"{len(ctx.heard_hints)} か所は認識の字を校閲に渡します")
        return settled, look

    def verify(self, result: StageResult) -> bool:
        return result.success and result.data.get("segment_count", 0) > 0
