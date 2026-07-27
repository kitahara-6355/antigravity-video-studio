"""
silence_trimmer.py — 無音検出と自動トリミング（ジェットカット）モジュール

FFmpegのsilencedetectフィルターを用いて無音区間を検出し、
指定した長さにトリミングすることでテンポ感を向上させる。
同時に、SRTファイルの字幕タイムスタンプも動的に前方にずらして同期を維持する。
"""

import logging
import os
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class SilenceTrimmerError(Exception):
    """silence_trimmerモジュールにおける基底例外クラス"""
    pass


class SilenceDetectionError(SilenceTrimmerError):
    """無音区間の検出中に発生したエラー"""
    pass


class VideoTrimError(SilenceTrimmerError):
    """動画のトリミング処理中に発生したエラー"""
    pass


def detect_silence(video_path: str, noise_db: int = -40, duration_limit: float = 1.5) -> list[dict]:
    """
    FFmpegのsilencedetectフィルターを使用して無音区間を検出する。

    Args:
        video_path: 動画ファイルのパス
        noise_db: 無音判定する音量閾値（dB）
        duration_limit: 無音判定する最小秒数

    Returns:
        無音区間の情報のリスト [{"start": float, "end": float, "duration": float}]
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    cmd = [
        "ffmpeg", "-i", video_path,
        "-af", f"silencedetect=n={noise_db}dB:d={duration_limit}",
        "-f", "null", "-"
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output = result.stderr
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg silencedetect failed: {e.stderr}")
        raise SilenceDetectionError(f"FFmpeg silencedetect command failed with exit code {e.returncode}") from e
    except OSError as e:
        logger.error(f"Failed to execute FFmpeg silencedetect: {e}")
        raise SilenceDetectionError(f"Failed to execute FFmpeg command: {e}") from e

    silences = []
    start_matches = list(re.finditer(r"silence_start: (\d+\.?\d*)", output))
    end_matches = list(re.finditer(r"silence_end: (\d+\.?\d*) \| silence_duration: (\d+\.?\d*)", output))

    starts = [float(m.group(1)) for m in start_matches]
    ends_durations = [(float(m.group(1)), float(m.group(2))) for m in end_matches]

    # start と end-duration がペアになるよう処理
    # ffmpegの処理途中で切れた場合などを考慮
    for i in range(min(len(starts), len(ends_durations))):
        silences.append({
            "start": starts[i],
            "end": ends_durations[i][0],
            "duration": ends_durations[i][1]
        })

    logger.info(f"Detected {len(silences)} silence zones (>={duration_limit}s, n={noise_db}dB)")
    return silences


def trim_silence_and_srt(
    video_path: str,
    srt_path: str,
    output_video_path: str,
    output_srt_path: str,
    noise_db: int = -40,
    min_silence_len: float = 1.5,
    keep_silence_len: float = 0.5
) -> None:
    """
    無音区間をトリミングし、対応するSRT字幕ファイルの時間も前方にずらす。

    Args:
        video_path: 入力動画パス
        srt_path: 入力SRTパス
        output_video_path: 出力動画パス
        output_srt_path: 出力SRTパス
        noise_db: 無音判定する音量閾値（dB）
        min_silence_len: トリミング対象とする最小無音秒数
        keep_silence_len: 残す無音秒数
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Input video file not found: {video_path}")

    silences = detect_silence(video_path, noise_db, min_silence_len)
    
    # 削る区間（トリミング対象）のリストを作成
    cut_ranges = []
    for s in silences:
        s_start = s["start"]
        s_end = s["end"]
        s_dur = s["duration"]
        if s_dur > min_silence_len:
            # 前後のマージンとして keep_silence_len / 2 ずつ残す
            trim_start = s_start + (keep_silence_len / 2.0)
            trim_end = s_end - (keep_silence_len / 2.0)
            if trim_end > trim_start:
                cut_ranges.append((trim_start, trim_end))

    # 削る区間がない場合は、そのままファイルを複製して完了
    if not cut_ranges:
        logger.info("No silences to trim. Copying files directly.")
        import shutil
        shutil.copy2(video_path, output_video_path)
        if srt_path and os.path.exists(srt_path):
            shutil.copy2(srt_path, output_srt_path)
        return

    # 動画の長さを取得してキープ区間（残す範囲）を算出
    # 動画編集エンジンからFFmpegラッパーを使って duration を取得
    try:
        from video_editor_engine import video_editor
        duration = video_editor.ffmpeg.get_duration(video_path)
    except (ImportError, AttributeError, ValueError, TypeError) as e:
        logger.warning(f"Could not get video duration via video_editor: {e}. Fallback to ffprobe.")
        # ffprobeによるフォールバック
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", video_path
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            duration = float(result.stdout.strip())
        except (subprocess.CalledProcessError, ValueError, TypeError):
            duration = 9999.0  # フォールバック

    keep_ranges = []
    current_pos = 0.0
    for c_start, c_end in cut_ranges:
        if c_start > current_pos:
            keep_ranges.append((current_pos, c_start))
        current_pos = c_end
    if current_pos < duration:
        keep_ranges.append((current_pos, duration))

    # FFmpegの select/aselect フィルターを使ってトリミング（再エンコード）
    v_select = "+".join(f"between(t,{start:.3f},{end:.3f})" for start, end in keep_ranges)
    a_select = "+".join(f"between(t,{start:.3f},{end:.3f})" for start, end in keep_ranges)

    # タイムスタンプ再構築
    vf = f"select='{v_select}',setpts=N/FRAME_RATE/TB"
    af = f"aselect='{a_select}',asetpts=N/SR/TB"

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", vf,
        "-af", af,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        output_video_path
    ]

    logger.info(f"Running FFmpeg jet-cut for {video_path}...")
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        logger.info(f"Successfully trimmed video: {output_video_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg trim execution failed: {e.stderr}")
        raise VideoTrimError(f"FFmpeg trim execution failed: {e.stderr}") from e
    except OSError as e:
        logger.error(f"Failed to execute FFmpeg trim: {e}")
        raise VideoTrimError(f"Failed to execute FFmpeg command: {e}") from e

    # SRTのタイムスタンプ修正
    if srt_path and os.path.exists(srt_path):
        from auto_full_build import parse_srt, write_srt

        segments = parse_srt(srt_path)

        def adjust_time(t):
            shift = 0.0
            for c_start, c_end in cut_ranges:
                if t > c_end:
                    shift += (c_end - c_start)
                elif c_start <= t <= c_end:
                    shift += (t - c_start)
            return t - shift

        adjusted_segments = []
        for seg in segments:
            new_start = adjust_time(seg["start"])
            new_end = adjust_time(seg["end"])
            # 極端に短い、または逆転しているセグメントは除外
            if new_end > new_start + 0.1:
                new_seg = dict(seg)
                new_seg["start"] = new_start
                new_seg["end"] = new_end
                adjusted_segments.append(new_seg)

        write_srt(adjusted_segments, output_srt_path)
        logger.info(f"Successfully adjusted SRT timestamps and wrote to {output_srt_path}")
