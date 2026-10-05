"""
SmartCutWorker — SmartCut構成ステージ

テキスト密度 × 位置重みに基づくセグメント選定。
目標尺に合わせた自動カットポイント決定。
"""

import logging
import time

from agents.pipeline_types import PipelineStageWorker, PipelineContext, StageResult

logger = logging.getLogger(__name__)


def _get_segment_field(segment, field_name, default=0):
    """辞書またはオブジェクトから安全にフィールド値を取得するヘルパー"""
    if isinstance(segment, dict):
        return segment.get(field_name, default)
    return getattr(segment, field_name, default)


def _get_segment_duration(segment) -> float:
    """セグメントの継続時間を sourceStart/sourceEnd または start/end から取得するヘルパー"""
    start = _get_segment_field(segment, "sourceStart", _get_segment_field(segment, "start", 0))
    end = _get_segment_field(segment, "sourceEnd", _get_segment_field(segment, "end", 0))
    return max(end - start, 0.0)


def _source_key(segment) -> tuple:
    """字幕の行が指す**元の区間**。校閲の整形で1つの発話が数行に分かれても、
    行はみな同じ sourceStart/sourceEnd を持つ（レンダリングはこの区間で切る）。"""
    start = _get_segment_field(segment, "sourceStart", _get_segment_field(segment, "start", 0))
    end = _get_segment_field(segment, "sourceEnd", _get_segment_field(segment, "end", 0))
    return (start, end)


def _unique_duration(segments) -> float:
    """元の区間ごとに1回だけ数えた尺。"""
    return sum(max(e - s, 0.0) for s, e in {_source_key(seg) for seg in segments})


MERGE_TOLERANCE_SEC = 0.3  # smart_cut_engine.render_smart_cut と同じ結合の許容


def planned_output_seconds(segments) -> float:
    """残す区間を、レンダリングと同じ規則（隙間 0.3秒以内はつなぐ）で結合した合計尺。"""
    ranges = sorted({_source_key(seg) for seg in segments})
    total = 0.0
    cur = None
    for start, end in ranges:
        if cur and start <= cur[1] + MERGE_TOLERANCE_SEC:
            cur[1] = max(cur[1], end)
            continue
        if cur:
            total += max(cur[1] - cur[0], 0.0)
        cur = [start, end]
    if cur:
        total += max(cur[1] - cur[0], 0.0)
    return total


class SmartCutWorker(PipelineStageWorker):
    def __init__(self):
        super().__init__("SmartCut構成", "✂️", 2)

    def get_definition_of_done(self) -> str:
        return "目標尺±2分の構成が生成され、重要シーンが含まれていること"

    def _calculate_total_duration(self, segments: list) -> float:
        """全セグメントの中から最大の終了時刻（＝総尺秒数）を算出する"""
        durations = []
        for segment in segments:
            end_val = _get_segment_field(segment, "sourceEnd", None)
            if end_val is None:
                end_val = _get_segment_field(segment, "end", 0)
            durations.append(end_val)
        return max(durations) if durations else 0.0

    def _score_segments(self, segments: list) -> list[tuple[float, float, int, dict]]:
        """各セグメントのテキスト密度、位置重み、前後の無音ギャップに基づいてスコアリングを行う"""
        MIN_GAP_FOR_CLEAN_CUT = 0.3  # この秒数以上のギャップがある場所でカット
        scored_segments = []

        for idx, segment in enumerate(segments):
            duration = _get_segment_duration(segment)
            text = _get_segment_field(segment, "text", "")
            text_len = len(text)

            # 位置重み（冒頭・末尾を優先）
            position_ratio = idx / max(len(segments), 1)
            position_weight = 1.0
            if position_ratio < 0.1:
                position_weight = 1.5
            elif position_ratio > 0.85:
                position_weight = 1.3

            # 極小セグメント除外（1秒未満）
            if duration < 1.0:
                continue

            # A-4: 前後のギャップ検査（前後に無音ギャップがあればカットポイントとして評価）
            gap_bonus = 0.0
            src_start = _get_segment_field(segment, "sourceStart", _get_segment_field(segment, "start", 0))
            src_end = _get_segment_field(segment, "sourceEnd", _get_segment_field(segment, "end", 0))

            if idx > 0:
                prev_end = _get_segment_field(segments[idx - 1], "sourceEnd", _get_segment_field(segments[idx - 1], "end", 0))
                gap_before = src_start - prev_end
                if gap_before >= MIN_GAP_FOR_CLEAN_CUT:
                    gap_bonus += 0.3
            if idx < len(segments) - 1:
                next_start = _get_segment_field(segments[idx + 1], "sourceStart", _get_segment_field(segments[idx + 1], "start", 0))
                gap_after = next_start - src_end
                if gap_after >= MIN_GAP_FOR_CLEAN_CUT:
                    gap_bonus += 0.3

            density = text_len / max(duration, 0.1)
            score = (density * position_weight) + gap_bonus
            scored_segments.append((score, duration, idx, segment))

        return scored_segments

    def _select_segments_by_score(
        self,
        scored_segments: list[tuple[float, float, int, dict]],
        target_seconds: float,
        segments: list | None = None,
    ) -> tuple[set[int], float]:
        """スコアの高い順に**元の区間**を累積し、目標尺に達するまで選定する。

        同じ元の区間を指す行（校閲の整形で分かれた行）は、1行選ばれたら全部選び、
        尺は1回だけ数える。以前は行の数だけ数えていて、38分の発話が19分になった
        （2026-10-05 の raw 4本の実走）。
        """
        siblings: dict[tuple, list[int]] = {}
        for i, seg in enumerate(segments or []):
            siblings.setdefault(_source_key(seg), []).append(i)

        selected_indices = set()
        counted: set[tuple] = set()
        accumulated_duration = 0.0

        # スコア降順ソート
        sorted_scored = sorted(scored_segments, key=lambda x: x[0], reverse=True)
        for score, duration, index, segment in sorted_scored:
            if accumulated_duration >= target_seconds:
                break
            key = _source_key(segment)
            if key in counted:
                continue
            counted.add(key)
            selected_indices.update(siblings.get(key, [index]))
            accumulated_duration += duration

        return selected_indices, accumulated_duration

    def _group_continuous_runs(self, sorted_indices: list[int]) -> list[list[int]]:
        """連続するインデックスをグループ化してリストのリストを返す"""
        if not sorted_indices:
            return []
        continuous_runs = []
        current_run = [sorted_indices[0]]
        for index in sorted_indices[1:]:
            if index == current_run[-1] + 1:
                current_run.append(index)
            else:
                continuous_runs.append(current_run)
                current_run = [index]
        continuous_runs.append(current_run)
        return continuous_runs

    def _filter_short_runs(
        self,
        selected_indices: set[int],
        segments: list,
        target_seconds: float,
        accumulated_duration: float
    ) -> set[int]:
        """A-5: 時系列順にソートし、短い孤立区間を除去（ただし目標尺の50%以下にならない安全弁付き）"""
        MIN_KEPT_DURATION = 10.0  # 保持区間の最小尺
        sorted_indices = sorted(selected_indices)
        if not sorted_indices:
            return selected_indices

        # 連続区間を識別 (関数分割)
        continuous_runs = self._group_continuous_runs(sorted_indices)

        # 短い区間を除去（安全弁付き）
        filtered_indices = set()
        removed_duration = 0.0
        for run in continuous_runs:
            run_duration = _unique_duration(segments[idx] for idx in run)
            if run_duration >= MIN_KEPT_DURATION or len(continuous_runs) <= 3:
                for idx in run:
                    filtered_indices.add(idx)
            else:
                removed_duration += run_duration
                logger.info(f"A-5: 短い保持区間を除去候補 ({run_duration:.1f}s, segments {run[0]}-{run[-1]})")

        # 安全弁: フィルタ後の合計尺がtarget_secondsの50%以下になる場合はフィルタを無効化
        filtered_duration = accumulated_duration - removed_duration
        if filtered_indices and filtered_duration >= target_seconds * 0.5:
            logger.info(f"A-5: フィルタ適用 (除去{removed_duration:.1f}s, 残{filtered_duration:.1f}s)")
            return filtered_indices
        else:
            logger.info(f"A-5: 安全弁発動 — フィルタ無効 (除去後{filtered_duration:.1f}s < 目標{target_seconds*0.5:.1f}s)")
            return selected_indices

    async def execute(self, ctx: PipelineContext) -> StageResult:
        """SmartCut構成を実行

        入力契約:
            ctx.segments: list[dict] — 必須。各dictに start, end, text を含む
            ctx.target_minutes: int — 必須。目標尺（分）
        出力契約:
            ctx.selected_segments: list[dict] — 選定されたセグメント（⊆ segments）
        """
        start_time = time.time()
        segments = ctx.segments if ctx.segments else []
        segment_count = len(segments)
        logger.info(f"✂️ SmartCut開始: ctx.segments={segment_count}件")

        if not segments:
            ctx.selected_segments = []
            return StageResult(
                stage_name=self.name, success=False,
                detail="セグメントなし", duration_seconds=0.0,
            )

        target_seconds = ctx.target_minutes * 60.0
        total_duration = self._calculate_total_duration(segments)

        if total_duration <= target_seconds:
            # 目標尺以下 → カット不要
            ctx.selected_segments = segments
            ctx.planned_output_sec = planned_output_seconds(segments)
            return StageResult(
                stage_name=self.name, success=True,
                detail=f"カット不要 — 元尺{total_duration/60:.1f}分 ≤ 目標{ctx.target_minutes}分",
                data={"segments": len(segments), "duration": total_duration},
                duration_seconds=round(time.time() - start_time, 1),
            )

        # ━━━ SmartCut: 目標尺に向けたセグメント選定 ━━━
        scored_segments = self._score_segments(segments)

        # 目標尺まで累積
        selected_indices, accumulated_duration = self._select_segments_by_score(
            scored_segments, target_seconds, segments)

        # A-5: 連続保持区間の最小尺チェック（短い孤立区間の除去）
        selected_indices = self._filter_short_runs(selected_indices, segments, target_seconds, accumulated_duration)

        selected_segments = [segments[index] for index in sorted(selected_indices)]
        ctx.selected_segments = selected_segments
        ctx.planned_output_sec = planned_output_seconds(selected_segments)

        estimated_duration = _unique_duration(selected_segments)
        cut_percent = (1.0 - len(selected_segments) / len(segments)) * 100.0

        return StageResult(
            stage_name=self.name, success=True,
            detail=f"{len(selected_segments)}セグメント選定 / 推定{estimated_duration/60:.1f}分 (カット率{cut_percent:.0f}%)",
            data={"segments": len(selected_segments), "duration": estimated_duration, "cut_percent": round(cut_percent, 1)},
            duration_seconds=round(time.time() - start_time, 1),
        )
