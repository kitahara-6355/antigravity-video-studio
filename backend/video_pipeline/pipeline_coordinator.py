"""
pipeline_coordinator.py — パイプライン全体オーケストレーション

全パイプラインステージの逐次実行を管理するオーケストレーター。
各ステージの実行・リトライ・中間成果物管理・event_log.jsonl記録を行う。

ステージ実行順序:
  ingest → audio_extract → transcribe → subtitle_gen → soul_feedback →
  telop_render → compose → quality_gate → thumbnail

FFmpeg呼び出しは _run_ffmpeg() メソッドに分離し、テスト時にモック可能な設計。

subprocess.Popenモック安全規約:
  - poll() は return_value=0 で即座に終了コードを返すこと
  - readline() は空文字列 "" を返すこと
  - conftest.py の safe_popen_mock fixture を使用すること
"""

import json
import logging
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
import sys
import backend.core
import backend.core.plugin
import backend.core.context
import backend.core.registry

# core パッケージのエイリアス登録（from core import ... を使用するプラグインへの互換性確保）
sys.modules["core"] = backend.core
sys.modules["core.plugin"] = backend.core.plugin
sys.modules["core.context"] = backend.core.context
sys.modules["core.registry"] = backend.core.registry

from backend.revenue.run_record import (
    LOCAL_PREFIX,
    RunRecorder,
    failed_stage,
    is_unserializable,
    load_run,
)

logger = logging.getLogger(__name__)


class ResumeNotPossible(RuntimeError):
    """記録から再開できない。**「再開したつもりで壊れたもの」を作らない。**"""


class StageServiceFailed(RuntimeError):
    """サービスが `success=False` を返した。**工程の失敗として扱う。**"""


def _require_success(stage_name: str, result):
    """サービスの戻り値の `success` を必ず見る。**捨てない。**

    2026-08-20 に音声トラックの無い素材で実走したところ、10/10 完走・
    success=True・所要 8.9 秒で終わり、**成果物は入力とバイト一致**
    だった。`subtitles.srt` は作られてすらいない。

    原因は `_execute_stage` が各サービスの戻り値から必要なフィールドだけ
    取り出し、`success` を一度も読んでいなかったこと。個別のバグではなく
    型なので、ここで型ごと閉じる。

    - `success` が `False` **そのもの**のときだけ失敗にする。
      MagicMock の属性は Mock であって False ではないので、既存の
      パイプラインテストは通る（`is False` で見る理由）
    - `success` を持たない戻り値は従来どおり通す
    """
    if getattr(result, "success", None) is False:
        detail = getattr(result, "error", "") or "(理由の記録なし)"
        raise StageServiceFailed(f"{stage_name}: {detail}")
    return result


class _StageFailed(RuntimeError):
    """`run_stage` の失敗を `RunRecorder.stage` に伝えるための内部例外。

    **外へは漏らさない。** `run_pipeline` の契約（失敗しても
    `PipelineResult` を返す）は変えない。
    """


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 定数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STAGE_ORDER: list[str] = [
    "ingest",
    "smart_cut",
    "audio_extract",
    "transcribe",
    "subtitle_gen",
    "soul_feedback",
    "telop_render",
    "compose",
    "quality_gate",
    "thumbnail",
]

MAX_RETRIES: int = 2

# 工程ごとのモデル宣言（R1-C6 の見える化）。
#
# **`local:` は「LLM を使っていない」ことの宣言**であって、書き忘れの
# 代用ではない。宣言が無い工程は成果物ゲートが FAIL する仕様なので、
# 使っていないなら使っていないと書く。
#
# 値が `local:` で始まらないものは `model_policy` の**工程名**として扱い、
# 段からモデルを引く。**モデル名は直書きしない** — 直書きすると入替の
# たびに全工程を書き換えることになり、実際それで `gemini-3-flash-preview`
# が居座って腐った。
#
# 2026-08-19 の実測: Gemini を呼ぶのは soul_feedback だけ。quality_gate は
# model_policy に premium として登録されているが、`video_pipeline` の
# QualityGate は完全にローカル判定で、API を1回も叩かない。
STAGE_MODELS: dict[str, str] = {
    "ingest": "local:ffmpeg",
    "smart_cut": "local:auto-editor",
    "audio_extract": "local:ffmpeg",
    "transcribe": "local:whisper",
    "subtitle_gen": "local:rule-based",
    "soul_feedback": "director",          # model_policy の工程名
    "telop_render": "local:pillow",
    "compose": "local:ffmpeg",
    "quality_gate": "local:rule-based",
    "thumbnail": "local:ffmpeg",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# データクラス定義
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class StageResult:
    """ステージ実行結果。

    Attributes:
        success: ステージ成功フラグ
        stage_name: ステージ名
        output_data: 出力データの辞書
        duration_seconds: 実行時間（秒）
        error_message: エラーメッセージ（失敗時のみ）
    """

    success: bool = False
    stage_name: str = ""
    output_data: dict = field(default_factory=dict)
    duration_seconds: float = 0.0
    error_message: str = ""


@dataclass
class PipelineResult:
    """パイプライン全体の実行結果。

    Attributes:
        success: パイプライン成功フラグ
        job_id: ジョブID
        stages_completed: 完了したステージ名のリスト
        output_path: 最終出力ファイルのパス
        quality_score: 品質スコア (0.0〜1.0)
        duration_seconds: 総実行時間（秒）
        error_message: エラーメッセージ（失敗時のみ）
    """

    success: bool = False
    job_id: str = ""
    stages_completed: list[str] = field(default_factory=list)
    output_path: str = ""
    quality_score: float = 0.0
    duration_seconds: float = 0.0
    error_message: str = ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PipelineCoordinator クラス
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class PipelineCoordinator:
    """パイプライン全体オーケストレーター。

    全パイプラインステージを STAGE_ORDER に従って逐次実行する。
    各ステージの成果物は work_dir/{job_id}/ に保存され、
    event_log.jsonl にステージの開始/完了/エラーを記録する。

    失敗したステージは最大2回リトライする。

    Args:
        work_dir: 作業ディレクトリのパス（省略時はカレントディレクトリ）
        config: パイプライン設定の辞書
    """

    def __init__(
        self,
        work_dir: Optional[str] = None,
        config: Optional[dict] = None,
        runs_dir: Optional[Path] = None,
        ledger_path: Optional[Path] = None,
    ) -> None:
        """PipelineCoordinatorを初期化する。

        Args:
            work_dir: 作業ディレクトリのパス
            config: パイプライン設定の辞書
            runs_dir: 実行記録（run.json）の置き場。**渡したときだけ記録する。**
                既定で `output/runs/` に書くと、既存のパイプラインテストが
                本番ディレクトリを汚す。実走の入口（CLI）が明示的に渡す。
                記録が無ければ成果物ゲートが FAIL するので、渡し忘れは
                ゲート側で捕まる
        """
        self.work_dir: str = work_dir or os.getcwd()
        self.config: dict = config or {}
        self.runs_dir: Optional[Path] = (
            Path(runs_dir) if runs_dir is not None else None)
        # **台帳は記録先と別に差し替える。** 実行の終わりに1本ぶんの要約を
        # 追記するので、`runs_dir` だけ差し替えたテストが本番の
        # `.claude/cost_ledger.jsonl` に書き込んでしまう（実際に 40 行混ざり、
        # 成果物ゲートが「トークンを読めなかった呼び出し 40 件」と誤検知した）。
        # **渡されなければ要約を書かない。** 本番の入口が両方を明示的に渡す。
        self.ledger_path: Optional[Path] = (
            Path(ledger_path) if ledger_path is not None else None)
        self._jobs: dict[str, dict[str, Any]] = {}
        Path(self.work_dir).mkdir(parents=True, exist_ok=True)

    def run_pipeline(
        self, input_path: str, stages: Optional[list[str]] = None,
        initial_data: Optional[dict] = None,
        resumed_from: str = "",
    ) -> PipelineResult:
        """パイプライン全体を実行する。

        STAGE_ORDER に従って各ステージを逐次実行し、
        失敗時は最大2回リトライする。

        Args:
            input_path: 入力ファイルのパス
            stages: 実行するステージ名のリスト。省略時は全ステージを実行
            initial_data: 工程間で受け渡す初期データ。**再開に使う。**
                前の実行が作った中間成果物のパスなどが入る。
                `job_dir` もここから引き継ぐ（再開は同じ作業場で続ける）
            resumed_from: 再開元の run_id。実行記録に残して辿れるようにする

        Returns:
            PipelineResult: パイプライン全体の実行結果
        """
        start_time = time.time()
        job_id = self._create_job(input_path)
        job_dir = os.path.join(self.work_dir, job_id)

        logger.info("パイプライン開始: job_id=%s, input=%s", job_id, input_path)
        self._log_event(job_id, "pipeline_start", {"input_path": input_path})

        stages_completed: list[str] = []
        current_data: dict[str, Any] = {
            "input_path": input_path,
            "job_id": job_id,
            "job_dir": job_dir,
        }
        if initial_data:
            # **再開は前の作業場をそのまま使う**（job_dir を含めて引き継ぐ）。
            # ただし帳簿の job_id はこの実行のもの。
            current_data.update(initial_data)
            current_data["job_id"] = job_id
            job_dir = current_data["job_dir"]
        error_message = ""
        target_stages = stages if stages is not None else STAGE_ORDER
        recorder = self._new_recorder(input_path, resumed_from=resumed_from)

        for stage_name in target_stages:
            stage_result = self._run_recorded_stage(
                recorder, stage_name, current_data,
            )

            if stage_result.success:
                stages_completed.append(stage_name)
                current_data.update(stage_result.output_data)
                logger.info(
                    "ステージ完了: %s (%.1f秒)",
                    stage_name, stage_result.duration_seconds,
                )
            else:
                error_message = (
                    f"ステージ '{stage_name}' が失敗: "
                    f"{stage_result.error_message}"
                )
                logger.error(error_message)
                self._log_event(job_id, "pipeline_error", {
                    "stage": stage_name,
                    "error": stage_result.error_message,
                })
                break

        elapsed = time.time() - start_time
        success = len(stages_completed) == len(target_stages)

        if recorder is not None:
            output_path = current_data.get("output_path", "")
            # **成果物は完走したときだけ載せる。** 途中で落ちた実行の
            # 中間ファイルを「成果物」として並べると、成果物ゲートが
            # 落ちた実行を緑にしてしまう。
            if success and output_path:
                self._guarded(recorder.artifact, output_path)
            self._guarded(recorder.finish)

        # ジョブ状態を更新
        self._jobs[job_id]["status"] = "completed" if success else "failed"
        self._jobs[job_id]["stages_completed"] = stages_completed
        self._jobs[job_id]["duration_seconds"] = elapsed

        self._log_event(job_id, "pipeline_end", {
            "success": success,
            "stages_completed": stages_completed,
            "duration_seconds": elapsed,
        })

        logger.info(
            "パイプライン%s: job_id=%s, %d/%d ステージ完了 (%.1f秒)",
            "完了" if success else "失敗",
            job_id, len(stages_completed), len(STAGE_ORDER), elapsed,
        )

        return PipelineResult(
            success=success,
            job_id=job_id,
            stages_completed=stages_completed,
            output_path=current_data.get("output_path", ""),
            quality_score=current_data.get("quality_score", 0.0),
            duration_seconds=elapsed,
            error_message=error_message,
        )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # 実行記録（R1-C1/C4/C5/C6）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #
    # **記録は付帯物。書けなくても動画を作るのを諦めない。**
    # ただし記録が無ければ成果物ゲートが FAIL するので、黙って
    # 無かったことにはならない。

    @staticmethod
    def _guarded(func, *args, **kwargs):
        """記録の書き出しでパイプラインを落とさない。"""
        try:
            return func(*args, **kwargs)
        except Exception as e:  # TDR登録済み: DP-02（記録は付帯物）
            logger.warning("実行記録の書き出しに失敗: %s", e)
            return None

    def _new_recorder(self, input_path: str, resumed_from: str = ""):
        """`runs_dir` が指定されていれば記録係を作る。無ければ None。"""
        if self.runs_dir is None:
            return None
        inputs: dict[str, Any] = {
            "source": input_path, "config": dict(self.config)}
        if resumed_from:
            inputs["resumed_from"] = resumed_from
        return self._guarded(
            RunRecorder, runs_dir=self.runs_dir, inputs=inputs,
            ledger_path=self.ledger_path,
        )

    def resume_run(self, run_id: str,
                   runs_dir: Optional[Path] = None) -> PipelineResult:
        """落ちた工程から**実際に再実行する**（R1-C4）。

        `run_record --resume` は「どこで落ちたか」を報告するだけだった。
        報告と再開は別物なので、ここで再開そのものを行う。

        - 完了済みの工程はやり直さない（それが再開の意味）
        - **元の作業ディレクトリを引き継ぐ。** 前の工程が作った中間
          成果物を使う
        - **元の失敗記録は書き換えない。** 証拠として残し、再開は
          新しい記録に `resumed_from` を書く
        - 復元できない入力があれば断る（fail-closed）

        Raises:
            ResumeNotPossible: 記録が無い・失敗していない・入力が復元できない
        """
        base = Path(runs_dir if runs_dir is not None else (self.runs_dir or ""))
        path = base / run_id / "run.json"
        if not path.is_file():
            raise ResumeNotPossible(f"実行記録がありません: {path}")

        run = load_run(path)
        stage = failed_stage(run)
        if stage is None:
            raise ResumeNotPossible(
                f"{run_id} に失敗した工程はありません"
                f"（status={run.get('status')}）。再開するものがありません")

        stage_name = stage.get("name", "")
        if stage_name not in STAGE_ORDER:
            raise ResumeNotPossible(f"知らない工程です: {stage_name}")

        data = dict(stage.get("input") or {})
        # **印だけ残っている値は復元できない。** これを渡して動かすと
        # 「再開したつもりで壊れたもの」ができる。どこまで戻ればいいかを
        # 添えて断る。
        lost = sorted(k for k, v in data.items() if is_unserializable(v))
        if lost:
            producer = self._stage_that_produces(lost, stage_name)
            raise ResumeNotPossible(
                f"入力を復元できないので '{stage_name}' からは再開できません"
                f"（記録できなかった値: {', '.join(lost)}）。"
                f"'{producer}' からやり直してください")

        remaining = STAGE_ORDER[STAGE_ORDER.index(stage_name):]
        logger.info("再開: %s の '%s' から %d 工程",
                    run_id, stage_name, len(remaining))
        return self.run_pipeline(
            run.get("inputs", {}).get("source", data.get("input_path", "")),
            stages=remaining, initial_data=data, resumed_from=run_id,
        )

    @staticmethod
    def _stage_that_produces(keys: list[str], before: str) -> str:
        """`keys` を作る工程のうち、いちばん手前のものを返す。

        戻り先を「先頭から」と言うと再開の意味が無いので、**必要な値を
        作り直せる最小の地点**を示す。
        """
        producers = {
            "normalized_path": "ingest",
            "format_info": "ingest",
            "duration_seconds": "ingest",
            "audio_path": "audio_extract",
            "transcript": "transcribe",
            "transcript_segments": "transcribe",
            "subtitle_path": "subtitle_gen",
            "soul_suggestions": "soul_feedback",
            "telop_images": "telop_render",
            "output_path": "compose",
        }
        candidates = [producers[k] for k in keys if k in producers]
        if not candidates:
            return STAGE_ORDER[0]
        return min(candidates, key=STAGE_ORDER.index)

    def _run_recorded_stage(
        self, recorder, stage_name: str, input_data: dict
    ) -> StageResult:
        """1工程を実行し、記録係がいれば結果を書き残す。

        `run_stage` は失敗を例外ではなく `StageResult.success=False` で
        返す。`RunRecorder.stage` は例外で失敗を検知するので、ここで
        いったん例外に変換して投げ直し、外へは漏らさない。
        """
        if recorder is None:
            return self.run_stage(stage_name, input_data)

        declared = STAGE_MODELS.get(stage_name, "")
        kwargs: dict[str, Any] = {"stage_input": dict(input_data)}
        if declared.startswith(LOCAL_PREFIX):
            kwargs["model"] = declared
        elif declared:
            kwargs["task"] = declared
        # どちらでもなければ宣言なし。**空のまま残してゲートに落とさせる。**

        holder: dict[str, StageResult] = {}
        try:
            with recorder.stage(stage_name, **kwargs):
                result = self.run_stage(stage_name, input_data)
                holder["result"] = result
                if not result.success:
                    raise _StageFailed(result.error_message or stage_name)
        except _StageFailed:
            pass
        except Exception as e:  # TDR登録済み: DP-02（記録は付帯物）
            logger.warning("実行記録の書き出しに失敗: %s", e)
            if "result" not in holder:
                return self.run_stage(stage_name, input_data)
        return holder.get("result", StageResult(
            success=False, stage_name=stage_name,
            error_message="実行記録の初期化に失敗しました",
        ))

    def run_stage(
        self, stage_name: str, input_data: dict
    ) -> StageResult:
        """個別ステージを実行する（リトライ付き）。

        最大 MAX_RETRIES 回のリトライを行う。

        Args:
            stage_name: ステージ名
            input_data: ステージへの入力データ

        Returns:
            StageResult: ステージ実行結果
        """
        last_error = ""
        job_id = input_data.get("job_id", "")

        for attempt in range(MAX_RETRIES + 1):
            start_time = time.time()

            if attempt > 0:
                logger.info(
                    "ステージ '%s' リトライ (%d/%d)",
                    stage_name, attempt, MAX_RETRIES,
                )

            self._log_event(job_id, "stage_start", {
                "stage": stage_name,
                "attempt": attempt,
            })

            try:
                output_data = self._execute_stage(stage_name, input_data)
                elapsed = time.time() - start_time

                self._log_event(job_id, "stage_complete", {
                    "stage": stage_name,
                    "duration_seconds": elapsed,
                })

                return StageResult(
                    success=True,
                    stage_name=stage_name,
                    output_data=output_data,
                    duration_seconds=elapsed,
                )

            except FileNotFoundError as e:
                elapsed = time.time() - start_time
                last_error = f"ファイルが見つかりません: {e}"
                logger.error(
                    "ステージ '%s' 失敗 (attempt=%d): %s",
                    stage_name, attempt, last_error,
                )
            except Exception as e:  # TDR登録済み: DP-02
                elapsed = time.time() - start_time
                last_error = str(e)
                logger.exception(
                    "ステージ '%s' で予期しないエラー (attempt=%d)",
                    stage_name, attempt,
                )

            self._log_event(job_id, "stage_error", {
                "stage": stage_name,
                "attempt": attempt,
                "error": last_error,
            })

        return StageResult(
            success=False,
            stage_name=stage_name,
            duration_seconds=time.time() - start_time,
            error_message=last_error,
        )

    def _execute_stage(
        self, stage_name: str, input_data: dict
    ) -> dict:
        """ステージに対応するサービスクラスを呼び出す。

        Args:
            stage_name: ステージ名
            input_data: ステージへの入力データ

        Returns:
            ステージの出力データ辞書

        Raises:
            ValueError: 未知のステージ名が指定された場合
        """
        input_path = input_data.get("input_path", "")
        job_dir = input_data.get("job_dir", self.work_dir)

        if stage_name == "ingest":
            from backend.video_pipeline.ingest_service import IngestService
            service = IngestService(output_dir=job_dir)
            result = _require_success(stage_name, service.ingest(input_path))
            return {
                "normalized_path": result.normalized_path,
                "format_info": result.format_info,
                "duration_seconds": result.duration_seconds,
            }

        elif stage_name == "smart_cut":
            from backend.plugins.smart_cut_plugin import SmartCutPlugin
            plugin = SmartCutPlugin()
            normalized_path = input_data.get("normalized_path", input_path)
            output_path = os.path.join(job_dir, "smartcut_output.mp4")
            
            threshold = self.config.get("smart_cut_threshold", 0.04)
            margin = self.config.get("smart_cut_margin", "0.2s")
            
            try:
                plugin.run_smart_cut(
                    input_path=normalized_path,
                    output_path=output_path,
                    threshold=threshold,
                    margin=margin
                )
                logger.info("Auto-Editor smart cut applied via SmartCutPlugin: %s -> %s", normalized_path, output_path)
                return {
                    "normalized_path": output_path,
                    "smart_cut_applied": True,
                }
            except Exception as e:
                logger.error(
                    "SmartCutPlugin smart cut failed, falling back to original video: %s",
                    e,
                )
                return {
                    "normalized_path": normalized_path,
                    "smart_cut_applied": False,
                    "error": str(e),
                }

        elif stage_name == "audio_extract":
            from backend.video_pipeline.audio_extractor import AudioExtractor
            extractor = AudioExtractor(output_dir=job_dir)
            normalized_path = input_data.get("normalized_path", input_path)
            result = _require_success(
                stage_name, extractor.extract(normalized_path))
            return {
                "audio_path": result.audio_path,
            }

        elif stage_name == "transcribe":
            from backend.video_pipeline.transcription_service import (
                TranscriptionService,
            )
            service = TranscriptionService(
                model_name=self.config.get("whisper_model", "base"),
                language=self.config.get("language", "ja"),
                refine_enabled=self.config.get("refine_enabled", True),
            )
            audio_path = input_data.get("audio_path", "")
            result = _require_success(
                stage_name, service.transcribe(audio_path))
            return {
                "transcript": result,
                "transcript_segments": [
                    {"start": s.start, "end": s.end, "text": s.text}
                    for s in result.segments
                ],
            }

        elif stage_name == "subtitle_gen":
            from backend.video_pipeline.subtitle_generator import (
                SubtitleGenerator,
            )
            generator = SubtitleGenerator(
                max_chars_per_line=self.config.get("max_chars_per_line", 13),
            )
            transcript = input_data.get("transcript")
            srt_path = os.path.join(job_dir, "subtitles.srt")
            result = _require_success(
                stage_name, generator.generate_srt(transcript, srt_path))
            return {
                "subtitle_path": result.output_path,
                "subtitle_entries": result.entry_count,
            }

        elif stage_name == "soul_feedback":
            from backend.video_pipeline.soul_feedback_engine import (
                ProductionContext,
                SoulFeedbackEngine,
            )

            engine = SoulFeedbackEngine()
            segments = input_data.get("transcript_segments", [])

            # transcript_segmentsからテキストを結合してcontextに渡す
            transcript_text = " ".join(
                s.get("text", "") for s in segments if s.get("text")
            )

            try:
                context = ProductionContext(
                    extra={"transcript": transcript_text}
                    if transcript_text
                    else {}
                )
                feedback = engine.generate_suggestions(context=context)
                suggestions_data = [
                    {
                        "category": s.category,
                        "suggestion": s.suggestion,
                        "priority": s.priority,
                        "confidence": s.confidence,
                    }
                    for s in feedback.suggestions
                ]
                return {
                    "soul_feedback_done": True,
                    "segments": segments,
                    "soul_suggestions": suggestions_data,
                    "soul_score": feedback.overall_score,
                    "soul_summary": feedback.analysis_summary,
                }
            except Exception as e:
                logger.warning("soul_feedback 提案生成失敗、スキップ: %s", e)
                return {"soul_feedback_done": True, "segments": segments}

        elif stage_name == "telop_render":
            from backend.video_pipeline.telop_renderer import TelopRenderer

            soul_suggestions = input_data.get("soul_suggestions", [])
            if soul_suggestions:
                logger.info(
                    "soul_feedback提案を受信 (%d件): %s",
                    len(soul_suggestions),
                    [s.get("category") for s in soul_suggestions],
                )

            renderer = TelopRenderer(output_dir=job_dir)
            segments = input_data.get("transcript_segments", [])
            texts = [s.get("text", "") for s in segments if s.get("text")]
            results = renderer.render_batch(texts)
            return {
                "telop_images": [r.image_path for r in results if r.success],
                "soul_suggestions": soul_suggestions,
            }

        elif stage_name == "compose":
            from backend.video_pipeline.video_composer import VideoComposer

            soul_suggestions = input_data.get("soul_suggestions", [])
            if soul_suggestions:
                logger.info(
                    "soul_feedback提案を受信 (%d件): %s",
                    len(soul_suggestions),
                    [s.get("category") for s in soul_suggestions],
                )

            composer = VideoComposer(output_dir=job_dir)
            normalized_path = input_data.get("normalized_path", input_path)
            subtitle_path = input_data.get("subtitle_path", "")
            output_path = os.path.join(job_dir, "composed_output.mp4")
            result = _require_success(stage_name, composer.compose(
                video_path=normalized_path,
                subtitle_path=subtitle_path,
                output_path=output_path,
            ))
            return {
                "output_path": output_path,
                "soul_suggestions": soul_suggestions,
            }

        elif stage_name == "quality_gate":
            from backend.video_pipeline.quality_gate import QualityGate
            gate = QualityGate()
            output_path = input_data.get("output_path", "")
            result = gate.evaluate(output_path, subtitle_path=input_data.get("subtitle_path"))
            return {
                "quality_score": getattr(result, "overall_score", 0.0),
                "quality_gate_passed": getattr(result, "passed", False),
            }

        elif stage_name == "thumbnail":
            from backend.video_pipeline.thumbnail_generator import (
                ThumbnailGenerator,
            )
            generator = ThumbnailGenerator(output_dir=job_dir)
            video_path = input_data.get("output_path", input_path)
            result = _require_success(
                stage_name, generator.generate(video_path, title=""))
            return {
                "thumbnail_path": result.image_path,
                "thumbnail_score": getattr(result, "score", 0.0),
            }

        else:
            raise ValueError(f"未知のステージ名: {stage_name}")

    def _create_job(self, input_path: str) -> str:
        """新しいジョブを作成しジョブIDを返す。

        ジョブ用の作業ディレクトリも作成する。

        Args:
            input_path: 入力ファイルのパス

        Returns:
            ジョブID文字列
        """
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        job_dir = os.path.join(self.work_dir, job_id)
        Path(job_dir).mkdir(parents=True, exist_ok=True)

        self._jobs[job_id] = {
            "status": "running",
            "input_path": input_path,
            "job_dir": job_dir,
            "stages_completed": [],
            "created_at": time.time(),
            "duration_seconds": 0.0,
        }

        logger.info("ジョブ作成: %s → %s", job_id, job_dir)
        return job_id

    def get_status(self, job_id: str) -> dict:
        """ジョブのステータスを取得する。

        Args:
            job_id: ジョブID

        Returns:
            ジョブステータスの辞書。未知のジョブIDの場合はエラー情報を含む辞書
        """
        if job_id in self._jobs:
            return dict(self._jobs[job_id])

        return {
            "status": "unknown",
            "error": f"ジョブが見つかりません: {job_id}",
        }

    def _log_event(
        self, job_id: str, event_type: str, data: dict
    ) -> None:
        """event_log.jsonl にイベントを記録する。

        Args:
            job_id: ジョブID
            event_type: イベント種別 (例: "pipeline_start", "stage_complete")
            data: イベントデータの辞書
        """
        event = {
            "timestamp": time.time(),
            "job_id": job_id,
            "event_type": event_type,
            **data,
        }
        event_log_path = os.path.join(self.work_dir, "event_log.jsonl")

        try:
            with open(event_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError:
            logger.warning("event_log.jsonl への書き込みに失敗")

    def _run_ffmpeg(self, cmd: list[str]) -> subprocess.CompletedProcess:
        """FFmpeg/ffprobeコマンドを実行する。

        テスト時は safe_popen_mock でこのメソッドをモックすることで、
        実際のFFmpeg実行を回避できる。

        subprocess.Popenモック安全規約:
          - poll() は return_value=0 で即座に終了コードを返すこと
          - readline() は空文字列 "" を返すこと

        Args:
            cmd: 実行するコマンドのリスト

        Returns:
            subprocess.CompletedProcess: 実行結果

        Raises:
            subprocess.CalledProcessError: コマンドが非ゼロ終了した場合
        """
        logger.info("FFmpegコマンド実行: %s", " ".join(cmd))
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        logger.info("FFmpegコマンド完了 (returncode=%d)", result.returncode)
        return result


if __name__ == "__main__":
    # 動作確認用のサンプルコード
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # `backend/.env` を読む。**CLI は誰も読んでいなかった**（cost_guard の
    # load_env と同じ問題）。読まないと実キーがあってもダミー扱いになり、
    # 実走のつもりが全部 STUB に落ちる。既存の環境変数は上書きしない。
    try:
        from backend.cost_guard import load_env
    except ImportError:
        from cost_guard import load_env
    load_env()

    if len(sys.argv) < 2:
        print("使用方法:")
        print("  python -m backend.video_pipeline.pipeline_coordinator "
              "<入力ファイルパス>")
        print("  python -m backend.video_pipeline.pipeline_coordinator "
              "--resume <run_id>   # 落ちた工程から再実行する")
        sys.exit(1)

    # **実走は必ず記録する。** 記録が無ければ成果物ゲートが FAIL する
    # 仕様なので、実キーで動かす唯一の入口であるここで渡す。
    from backend.revenue.artifact_gate import RUNS_DIR

    from backend.cost_guard import LEDGER_PATH

    coordinator = PipelineCoordinator(
        work_dir="./pipeline_work", runs_dir=RUNS_DIR,
        ledger_path=LEDGER_PATH,
    )

    if sys.argv[1] == "--resume":
        if len(sys.argv) < 3:
            print("再開する run_id を指定してください "
                  "（一覧: python -m backend.revenue.run_record --list）")
            sys.exit(1)
        try:
            result = coordinator.resume_run(sys.argv[2])
        except ResumeNotPossible as e:
            print(f"🚫 再開できません: {e}")
            sys.exit(1)
    else:
        result = coordinator.run_pipeline(sys.argv[1])

    print(f"パイプライン結果: success={result.success}, "
          f"job_id={result.job_id}, "
          f"stages={result.stages_completed}")
    if result.error_message:
        print(f"エラー: {result.error_message}")
    print(f"実行記録: {RUNS_DIR}")
    sys.exit(0 if result.success else 1)
