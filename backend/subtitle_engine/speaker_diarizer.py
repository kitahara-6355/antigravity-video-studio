"""
話者分離エンジン — VADベース簡易話者推定

U-05: 話者分類の高度化

機能:
- 音声エネルギー差分による簡易話者セグメンテーション
- FFmpeg + silencedetect による発話区間検出
- 対談動画での2話者分離（左右チャンネル分離 or エネルギーベース）
- pyannote-audio が利用可能な場合は高精度モードに切替

設計方針:
- pyannote-audio はオプション依存（なくても動作する）
- FFmpeg は必須（既にプロジェクト全体で使用）
- faster-whisper の結果と統合して speaker_id を付与
"""

import subprocess
import logging
import json
import re
import tempfile
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ============================================================
# データ構造
# ============================================================

@dataclass
class SpeakerSegment:
    """話者セグメント"""
    start: float
    end: float
    speaker_id: str  # "speaker_0", "speaker_1", ...
    confidence: float = 0.0


@dataclass
class DiarizationResult:
    """話者分離結果"""
    segments: List[SpeakerSegment] = field(default_factory=list)
    num_speakers: int = 0
    method: str = "unknown"  # "vad", "pyannote", "stereo"
    duration: float = 0.0


# ============================================================
# メインクラス
# ============================================================

class SpeakerDiarizer:
    """
    話者分離エンジン

    3つの戦略を段階的に試行:
    1. pyannote-audio（利用可能な場合、最高精度）
    2. ステレオチャンネル分離（2話者対談向け）
    3. VAD + エネルギー差分（フォールバック）
    """

    def __init__(self):
        self._pyannote_available = self._check_pyannote()

    def _check_pyannote(self) -> bool:
        """pyannote-audio の利用可否を確認"""
        try:
            import pyannote.audio  # noqa: F401
            logger.info("🎙️ pyannote-audio available — high-accuracy mode")
            return True
        except ImportError:
            logger.info("pyannote-audio not installed — using VAD fallback")
            return False
        except (ImportError, AttributeError, TypeError, RuntimeError) as e:
            logger.warning(f"Failed to import pyannote.audio due to unexpected error: {e}. Using VAD fallback.", exc_info=True)
            return False

    async def diarize(
        self,
        audio_path: str,
        num_speakers: Optional[int] = None,
        method: Optional[str] = None,
    ) -> DiarizationResult:
        """
        話者分離を実行

        Args:
            audio_path: 音声/動画ファイルパス
            num_speakers: 想定話者数（Noneで自動検出）
            method: 強制メソッド指定（"pyannote", "stereo", "vad"）
        """
        if method == "pyannote" or (method is None and self._pyannote_available):
            try:
                return await self._diarize_pyannote(audio_path, num_speakers)
            except (ImportError, ValueError) as e:
                logger.warning(f"pyannote failed, falling back to VAD: {e}")
            except (RuntimeError, KeyError) as e:
                logger.error(f"Unexpected error in pyannote diarization, falling back to VAD: {e}", exc_info=True)

        if method == "stereo" or (method is None and num_speakers == 2):
            try:
                return await self._diarize_stereo(audio_path)
            except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as e:
                logger.warning(f"Stereo failed, falling back to VAD: {e}")
            except (ValueError, KeyError, AttributeError) as e:
                logger.error(f"Unexpected error in stereo diarization, falling back to VAD: {e}", exc_info=True)

        return await self._diarize_vad(audio_path, num_speakers or 2)

    # ============================================================
    # 戦略1: pyannote-audio（高精度）
    # ============================================================

    async def _diarize_pyannote(
        self, audio_path: str, num_speakers: Optional[int]
    ) -> DiarizationResult:
        """pyannote-audio による高精度話者分離"""
        import asyncio

        def _run():
            from pyannote.audio import Pipeline
            import torch

            pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=True,
            )

            if torch.cuda.is_available():
                pipeline.to(torch.device("cuda"))

            kwargs = {}
            if num_speakers:
                kwargs["num_speakers"] = num_speakers

            diarization = pipeline(audio_path, **kwargs)

            segments = []
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                segments.append(SpeakerSegment(
                    start=turn.start,
                    end=turn.end,
                    speaker_id=speaker,
                    confidence=0.9,
                ))

            speakers = set(s.speaker_id for s in segments)
            return segments, len(speakers)

        loop = asyncio.get_running_loop()
        segments, n_speakers = await loop.run_in_executor(None, _run)

        return DiarizationResult(
            segments=segments,
            num_speakers=n_speakers,
            method="pyannote",
            duration=segments[-1].end if segments else 0,
        )

    # ============================================================
    # 戦略2: ステレオチャンネル分離（対談向け）
    # ============================================================

    async def _diarize_stereo(self, audio_path: str) -> DiarizationResult:
        """
        ステレオ音声の左右チャンネルで話者分離

        対談動画で話者がL/Rに分かれている場合に有効。
        """
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        def _run():
            # チャンネル数を確認
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries",
                 "stream=channels,duration", "-of", "json", audio_path],
                capture_output=True, text=True, timeout=30,
            )
            probe_data = json.loads(probe.stdout)
            streams = probe_data.get("streams", [{}])
            channels = int(streams[0].get("channels", 1))

            if channels < 2:
                raise ValueError("Mono audio — stereo diarization not applicable")

            duration = float(streams[0].get("duration", 0))

            # 左右チャンネルの活動区間を取得 (ThreadPoolExecutorで並列化)
            segments = []
            window_sec = 0.5  # 0.5秒ウィンドウ

            def run_ffmpeg_for_channel(channel_idx: int, speaker_id: str) -> List[SpeakerSegment]:
                cmd = [
                    "ffmpeg", "-i", audio_path,
                    "-af", f"pan=mono|c0=c{channel_idx},silencedetect=noise=-30dB:d=0.5",
                    "-f", "null", "-",
                ]
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=300,
                )

                # silencedetectのメタデータからエネルギー（発話区間）を推定
                energy_regions = self._parse_energy_from_stderr(
                    result.stderr, duration, window_sec
                )

                chan_segs = []
                for start, end in energy_regions:
                    chan_segs.append(SpeakerSegment(
                        start=start, end=end,
                        speaker_id=speaker_id,
                        confidence=0.7,
                    ))
                return chan_segs

            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(run_ffmpeg_for_channel, 0, "speaker_0"),
                    executor.submit(run_ffmpeg_for_channel, 1, "speaker_1")
                ]
                for future in futures:
                    segments.extend(future.result())

            segments.sort(key=lambda s: s.start)
            return segments, 2, duration

        loop = asyncio.get_running_loop()
        segments, n_speakers, duration = await loop.run_in_executor(None, _run)

        return DiarizationResult(
            segments=segments,
            num_speakers=n_speakers,
            method="stereo",
            duration=duration,
        )

    # ============================================================
    # 戦略3: VAD + エネルギー差分（フォールバック）
    # ============================================================

    async def _diarize_vad(
        self, audio_path: str, num_speakers: int = 2
    ) -> DiarizationResult:
        """
        FFmpeg silencedetect による簡易 VAD ベース話者推定

        非発話区間（無音）を検出し、発話ブロック間の
        エネルギー差分で話者を推定する。
        """
        import asyncio

        def _run():
            # silencedetect で無音区間を検出
            cmd = [
                "ffmpeg", "-i", audio_path,
                "-af", "silencedetect=noise=-30dB:d=0.5",
                "-f", "null", "-",
            ]
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=600,
                )
                if result.returncode != 0:
                    logger.warning(f"ffmpeg silencedetect returned non-zero exit code {result.returncode}: {result.stderr}")
                    silence_intervals = []
                else:
                    silence_intervals = self._parse_silence_detect(result.stderr)
            except subprocess.TimeoutExpired as e:
                logger.warning(f"ffmpeg silencedetect timeout expired: {e}")
                silence_intervals = []
            except subprocess.SubprocessError as e:
                logger.warning(f"Subprocess error during ffmpeg silencedetect: {e}")
                silence_intervals = []
            except OSError as e:
                logger.warning(f"OS error during ffmpeg silencedetect execution (is ffmpeg installed?): {e}")
                silence_intervals = []

            # 動画の長さを取得
            try:
                duration = self._get_duration(audio_path)
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to get duration: {e}")
                duration = 3600.0

            # 発話区間を構築（無音区間の補集合）
            try:
                speech_intervals = self._invert_intervals(silence_intervals, duration)
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to invert intervals: {e}")
                speech_intervals = []

            # 話者を推定（交互話者モデル）
            segments = []
            current_speaker = 0

            for i, (start, end) in enumerate(speech_intervals):
                # 直前の無音が1秒以上 → 話者交代の可能性
                if i > 0:
                    gap = start - speech_intervals[i - 1][1]
                    if gap > 1.0:
                        current_speaker = (current_speaker + 1) % num_speakers

                segments.append(SpeakerSegment(
                    start=start,
                    end=end,
                    speaker_id=f"speaker_{current_speaker}",
                    confidence=0.5,  # VADベースは信頼度低め
                ))

            return segments, num_speakers, duration

        loop = asyncio.get_running_loop()
        segments, n_speakers, duration = await loop.run_in_executor(None, _run)

        return DiarizationResult(
            segments=segments,
            num_speakers=n_speakers,
            method="vad",
            duration=duration,
        )

    # ============================================================
    # ヘルパー
    # ============================================================

    def _parse_silence_detect(self, stderr: str) -> List[Tuple[float, float]]:
        """FFmpeg silencedetect の出力をパース"""
        silence_starts = re.findall(
            r"silence_start: ([\d.]+)", stderr
        )
        silence_ends = re.findall(
            r"silence_end: ([\d.]+)", stderr
        )

        intervals = []
        for s, e in zip(silence_starts, silence_ends):
            try:
                start_val = float(s)
                end_val = float(e)
                if start_val < 0.0 or end_val < 0.0:
                    raise ValueError(f"Interval values must be non-negative (start={start_val}, end={end_val})")
                if start_val > end_val:
                    raise ValueError(f"Start time cannot be greater than end time (start={start_val}, end={end_val})")
                intervals.append((start_val, end_val))
            except ValueError as ex:
                logger.warning(f"Failed to parse silence interval due to ValueError (start='{s}', end='{e}'): {ex}", exc_info=True)
            except TypeError as ex:
                logger.warning(f"Failed to parse silence interval due to TypeError (start='{s}', end='{e}'): {ex}", exc_info=True)
        return intervals

    def _invert_intervals(
        self, silences: List[Tuple[float, float]], duration: float
    ) -> List[Tuple[float, float]]:
        """無音区間の補集合（＝発話区間）を生成"""
        speech = []
        prev_end = 0.0

        for s_start, s_end in silences:
            if s_start > prev_end:
                speech.append((prev_end, s_start))
            prev_end = s_end

        if prev_end < duration:
            speech.append((prev_end, duration))

        return speech

    def _parse_energy_from_stderr(
        self, stderr: str, duration: float, window: float
    ) -> List[Tuple[float, float]]:
        """astats のstderrから高エネルギー区間を抽出（簡易版）"""
        # astats の詳細パースが困難な場合、silencedetect に委譲
        # ここでは silencedetect の補集合を返す
        silence_intervals = self._parse_silence_detect(stderr)
        return self._invert_intervals(silence_intervals, duration)

    def _get_duration(self, audio_path: str) -> float:
        """音声/動画の長さを取得"""
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries",
                 "format=duration", "-of", "json", audio_path],
                capture_output=True, text=True, timeout=30,
            )
            returncode = result.returncode
            if returncode is not None and isinstance(returncode, int) and returncode != 0:
                logger.warning(f"ffprobe returned non-zero exit code {result.returncode}: {result.stderr}")
                return 3600.0
            
            data = json.loads(result.stdout)
            return float(data["format"]["duration"])
        except subprocess.TimeoutExpired as e:
            logger.warning(f"ffprobe timeout expired during duration retrieval: {e}")
            return 3600.0
        except subprocess.SubprocessError as e:
            logger.warning(f"Subprocess error during ffprobe execution: {e}")
            return 3600.0
        except OSError as e:
            logger.warning(f"OS error (is ffprobe installed?): {e}")
            return 3600.0
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to decode JSON output from ffprobe: {e}")
            return 3600.0
        except KeyError as e:
            logger.warning(f"Expected key not found in ffprobe JSON output: {e}")
            return 3600.0
        except ValueError as e:
            logger.warning(f"Failed to convert duration to float: {e}")
            return 3600.0

    # ============================================================
    # Whisper セグメントとの統合
    # ============================================================

    def assign_speakers_to_segments(
        self,
        whisper_segments: List[Dict],
        diarization: DiarizationResult,
    ) -> List[Dict]:
        """
        Whisper の字幕セグメントに speaker_id を付与

        各セグメントの中間時点が、どの話者セグメントに含まれるかで判定。

        Args:
            whisper_segments: Whisperの出力セグメント
            diarization: 話者分離結果

        Returns:
            speaker_id が付与されたセグメントリスト
        """
        if not diarization.segments:
            return whisper_segments

        import bisect
        try:
            diarization_starts = [d.start for d in diarization.segments]
        except AttributeError as e:
            logger.warning(f"Invalid segments structure in diarization: {e}")
            return whisper_segments

        for seg in whisper_segments:
            try:
                if "start" not in seg or "end" not in seg:
                    logger.warning(f"Skipping segment assignment due to missing 'start' or 'end' key in: {seg}")
                    continue
                
                try:
                    start_val = float(seg["start"])
                    end_val = float(seg["end"])
                except (ValueError, TypeError) as ex:
                    logger.warning(f"Failed to parse segment starts/ends as float: {ex} in segment: {seg}")
                    continue

                midpoint = (start_val + end_val) / 2

                # バイナリサーチで中間時点の直前・直後のセグメントインデックスを特定
                idx = bisect.bisect_right(diarization_starts, midpoint)

                # 中間時点を含む話者セグメントを探す
                assigned = False
                if idx > 0:
                    d_seg = diarization.segments[idx - 1]
                    if d_seg.start <= midpoint <= d_seg.end:
                        seg["speaker_id"] = d_seg.speaker_id
                        seg["speaker_confidence"] = d_seg.confidence
                        assigned = True

                if not assigned:
                    # 最も近い話者セグメントを使用 (前後の候補を比較)
                    candidates = []
                    if idx > 0:
                        candidates.append(diarization.segments[idx - 1])
                    if idx < len(diarization.segments):
                        candidates.append(diarization.segments[idx])

                    if candidates:
                        try:
                            closest = min(
                                candidates,
                                key=lambda d: abs((d.start + d.end) / 2 - midpoint),
                            )
                            seg["speaker_id"] = closest.speaker_id
                            seg["speaker_confidence"] = closest.confidence * 0.5
                        except ValueError as ex:
                            logger.warning(f"Failed to find closest segment due to ValueError: {ex}")
            except (KeyError, TypeError, AttributeError) as ex:
                logger.warning(f"Error while processing segment assignment: {ex} in segment: {seg}")

        try:
            speakers_found = set(s.get("speaker_id", "") for s in whisper_segments)
            logger.info(
                f"🎙️ Speaker assignment: {len(speakers_found)} speakers, "
                f"{len(whisper_segments)} segments, "
                f"method={diarization.method}"
            )
        except (AttributeError, TypeError) as ex:
            logger.warning(f"Failed to log speaker assignment info: {ex}")

        return whisper_segments


    def generate_diarization_thumbnail(
        self,
        output_path: str,
        diarization: DiarizationResult,
        width: int = 1280,
        height: int = 720,
        title: str = "話者分離結果サマリー (Speaker Diarization)",
    ) -> str:
        """
        話者分離結果を可視化した高品質なサムネイル画像を生成する。
        """
        from PIL import Image, ImageDraw
        import os
        import uuid

        if width < 1280 or height < 720:
            raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")

        aspect_ratio = width / height
        if abs(aspect_ratio - 16.0 / 9.0) > 0.01:
            raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")

        # 画像を初期化 (背景: ダークネイビーグラデーション)
        image = Image.new("RGB", (width, height), color=(15, 15, 25))
        draw = ImageDraw.Draw(image)

        # 背景グラデーション
        for y in range(height):
            r = int(15 + (y / height) * 20)
            g = int(15 + (y / height) * 15)
            b = int(25 + (y / height) * 35)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        # 外枠
        draw.rectangle([(15, 15), (width - 15, height - 15)], outline=(70, 80, 120), width=4)

        # テキスト描画
        text_color = (240, 240, 255)
        
        # タイトル描画
        draw.text((50, 50), title, fill=text_color)
        
        # 基本情報の描画
        info_text = f"検出話者数: {diarization.num_speakers}名 | 処理方法: {diarization.method.upper()} | 音声長: {diarization.duration:.2f}秒"
        draw.text((50, 120), info_text, fill=(180, 190, 220))

        # タイムラインの可視化 (視覚的にリッチなタイムバーを描画)
        timeline_y = int(height * 0.4)
        timeline_h = int(height * 0.15)
        timeline_w = width - 100
        
        # タイムライン背景
        draw.rectangle([(50, timeline_y), (width - 50, timeline_y + timeline_h)], fill=(40, 40, 60), outline=(80, 90, 130), width=2)
        
        # セグメントの描画
        colors = [
            (59, 130, 246),  # 青
            (16, 185, 129),  # 緑
            (239, 68, 68),   # 赤
            (245, 158, 11),  # オレンジ
            (139, 92, 246),  # 紫
        ]
        
        if diarization.duration > 0 and diarization.segments:
            for seg in diarization.segments:
                if seg.end > diarization.duration:
                    continue
                start_x = 50 + (seg.start / diarization.duration) * timeline_w
                end_x = 50 + (seg.end / diarization.duration) * timeline_w
                
                # 話者IDから色インデックスを決定
                try:
                    spk_num = int(seg.speaker_id.split("_")[-1])
                except (ValueError, IndexError):
                    logger.debug(f"Failed to parse speaker_id '{seg.speaker_id}', falling back to hash")
                    spk_num = hash(seg.speaker_id)
                color = colors[spk_num % len(colors)]
                
                # セグメント描画 (塗りつぶし)
                draw.rectangle([(start_x, timeline_y + 5), (end_x, timeline_y + timeline_h - 5)], fill=color)

        # 凡例の描画
        legend_y = int(height * 0.65)
        draw.text((50, legend_y), "凡例:", fill=(150, 160, 180))
        # 簡易話者凡例
        for i in range(min(diarization.num_speakers or 2, 5)):
            color = colors[i % len(colors)]
            x_offset = 120 + i * 150
            draw.rectangle([(x_offset, legend_y), (x_offset + 20, legend_y + 20)], fill=color)
            draw.text((x_offset + 30, legend_y), f"話者 {i}", fill=(200, 200, 220))

        # 原子的なファイル書き込み (Atomic Write)
        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        temp_path = output_path + f".{uuid.uuid4().hex}.tmp"
        
        success = False
        try:
            image.save(temp_path, "PNG")
            if os.path.exists(output_path):
                os.unlink(output_path)
            os.rename(temp_path, output_path)
            success = True
        except OSError as e:
            logger.error(f"Failed to save diarization thumbnail atomically due to OS error: {e}", exc_info=True)
            raise
        except (OSError, ValueError) as e:
            logger.error(f"Unexpected error while saving diarization thumbnail: {e}", exc_info=True)
            raise
        finally:
            if not success and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError as ue:
                    logger.warning(f"Failed to clean up temporary thumbnail file '{temp_path}': {ue}")

        # ファイルサイズチェック (4MB制限)
        size_bytes = os.path.getsize(output_path)
        if size_bytes >= 4 * 1024 * 1024:
            raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")

        return output_path


async def run_diarizer_thumbnail_task(
    db_path: str,
    task_id: str,
    output_path: str,
    diarization_data_json: str,
    width: int = 1280,
    height: int = 720,
    title: str = "話者分離結果サマリー",
) -> str:
    """
    StageBoundAgent から呼び出し可能な非同期タスクハンドラー。
    DiarizationResultのJSON表現からサムネイル画像を生成し、品質要件を検証する。
    """
    import json
    from agents.stage_bound_agent import validate_thumbnail
    
    # JSON文字列からDiarizationResultを復元
    data = json.loads(diarization_data_json)
    segments = []
    for seg_data in data.get("segments", []):
        segments.append(SpeakerSegment(
            start=seg_data["start"],
            end=seg_data["end"],
            speaker_id=seg_data["speaker_id"],
            confidence=seg_data.get("confidence", 0.0),
        ))
    
    diarization = DiarizationResult(
        segments=segments,
        num_speakers=data.get("num_speakers", 0),
        method=data.get("method", "unknown"),
        duration=data.get("duration", 0.0),
    )
    
    # サムネイル生成
    diarizer = SpeakerDiarizer()
    diarizer.generate_diarization_thumbnail(
        output_path=output_path,
        diarization=diarization,
        width=width,
        height=height,
        title=title
    )
    
    # 品質検証
    validation_result = validate_thumbnail(output_path)
    return json.dumps(validation_result)


# ============================================================
# シングルトン
# ============================================================
speaker_diarizer = SpeakerDiarizer()
