"""
Progressive Preview System
各編集処理完了後にスクリーンショットを自動抽出し、Before/After比較画像を生成

Phase 30.5 - プログレッシブ・プレビュー機能
Phase 30.6 - 改善: 並列処理、差分ハイライト、音声分析
"""

import subprocess
import json
from pathlib import Path
from datetime import datetime
from typing import Optional
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np

from path_resolver import project_root, writable_path

logger = logging.getLogger(__name__)


class ProgressivePreview:
    """処理ステップごとのプレビュー管理"""
    
    def __init__(self, session_id: Optional[str] = None, output_dir: Optional[str] = None):
        """
        Args:
            session_id: セッション識別子（未指定で自動生成）
            output_dir: 出力ディレクトリ
        """
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # **`Path(__file__).parent` を起点にしない。** ここは実行のたびに中身が
        # 変わる出力なので `writable_path` が置き場を決める（テストでは conftest が
        # 一時ディレクトリへ向ける）。コードの所在を起点にすると、**構築しただけで
        # リポジトリ内に `backend/temp/previews/<session_id>/` が実際に作られる**。
        # 2026-08-17 の CI 実測で `default` と `test_b27` の2件が増え、
        # 本番ファイル汚染ラチェットが赤になった（その他 116 → 118）。
        self.output_dir = Path(
            output_dir or writable_path("backend/temp/previews") / self.session_id)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.steps: list[dict] = []
        self.metadata_path = self.output_dir / "session_metadata.json"
        
        logger.info(f"ProgressivePreview initialized: session={self.session_id}")
    
    def detect_feature_points(
        self, 
        video_path: str, 
        max_points: int = 5,
        threshold: float = 0.3,
        srt_path: Optional[str] = None
    ) -> list[float]:
        """
        FFmpegのsceneフィルタ + 字幕タイミングで特徴的なタイムスタンプを自動検出
        
        Args:
            video_path: 動画パス
            max_points: 最大検出ポイント数
            threshold: シーン変化閾値（0-1、低いほど敏感）
            srt_path: 字幕ファイルパス（指定で字幕タイミングも含む）
        
        Returns:
            特徴的なタイムスタンプのリスト（秒）
        """
        logger.info(f"Detecting feature points: {video_path}")
        
        all_timestamps = []
        
        # 1. SRT字幕からのタイミング抽出（優先）
        if srt_path and Path(srt_path).exists():
            srt_timestamps = self._extract_srt_timestamps(srt_path, max_points)
            all_timestamps.extend(srt_timestamps)
            logger.info(f"Extracted {len(srt_timestamps)} timestamps from SRT")
        
        # 2. シーン変化検出
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-select_streams", "v:0",
            "-show_entries", "frame=pts_time",
            "-of", "csv=p=0",
            "-f", "lavfi",
            f"movie='{video_path}',select='gt(scene,{threshold})'"
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if line:
                        try:
                            ts = float(line)
                            all_timestamps.append(ts)
                        except ValueError:
                            continue
            
            # タイムスタンプを統合・重複除去・ソート
            if all_timestamps:
                filtered = self._filter_and_thin_timestamps(all_timestamps, max_points)
                logger.info(f"Detected {len(filtered)} feature points (combined)")
                return filtered
            
            return self._fallback_sampling(video_path, max_points)
            
        except subprocess.TimeoutExpired:
            logger.warning("Scene detection timed out")
            return self._fallback_sampling(video_path, max_points)
        except Exception as e:
            logger.error(f"Scene detection error: {e}")
            return self._fallback_sampling(video_path, max_points)
    
    def _extract_srt_timestamps(self, srt_path: str, max_points: int = 5) -> list[float]:
        """SRTファイルから字幕開始タイムスタンプを抽出"""
        import re
        
        timestamps = []
        time_pattern = re.compile(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})')
        
        try:
            with open(srt_path, 'r', encoding='utf-8') as f:
                for line in f:
                    match = time_pattern.match(line.strip())
                    if match:
                        h, m, s, ms = map(int, match.groups())
                        ts = h * 3600 + m * 60 + s + ms / 1000
                        timestamps.append(ts)
            
            # 均等に間引き
            if len(timestamps) > max_points * 2:
                step = len(timestamps) // (max_points * 2)
                timestamps = timestamps[::step]
            
            return timestamps[:max_points * 2]  # シーン検出と合わせるため多めに返す
        except Exception as e:
            logger.warning(f"Failed to parse SRT: {e}")
            return []
    
    def _fallback_sampling(self, video_path: str, num_points: int) -> list[float]:
        """フォールバック: 等間隔サンプリング"""
        duration = self._get_video_duration(video_path)
        if duration <= 0:
            return [1.0, 3.0, 5.0][:num_points]
        
        interval = duration / (num_points + 1)
        return [interval * (i + 1) for i in range(num_points)]
    
    def _get_video_duration(self, video_path: str) -> float:
        """動画の長さを取得"""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            video_path
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return float(result.stdout.strip())
        except Exception as e:
            logger.warning(f"Failed to get video duration for {video_path}: {e}")
            return 0.0

    def _filter_and_thin_timestamps(self, timestamps: list[float], max_points: int) -> list[float]:
        """タイムスタンプの重複排除、近接フィルタリング（2.0秒以内）、および最大ポイント数への間引きを行う"""
        if not timestamps:
            return []
            
        sorted_ts = sorted(set(timestamps))
        filtered = [sorted_ts[0]]
        for ts in sorted_ts[1:]:
            if ts - filtered[-1] >= 2.0:
                filtered.append(ts)
                
        if len(filtered) > max_points:
            step = len(filtered) // max_points
            filtered = filtered[::step][:max_points]
            
        return filtered

    def _create_placeholder_image(self, path: str, width: int, height: int, text: str):
        """プレースホルダー画像を生成するヘルパー関数"""
        from PIL import Image, ImageDraw
        try:
            with Image.new('RGB', (width, height), (50, 50, 50)) as img:
                draw = ImageDraw.Draw(img)
                draw.rectangle([(10, 10), (width - 10, height - 10)], outline=(100, 100, 100), width=2)
                draw.text((20, 20), text, fill=(200, 200, 200))
                img.save(path, quality=90)
        except Exception as e:
            logger.error(f"Failed to create placeholder image: {e}")
    
    def extract_screenshot(
        self, 
        video_path: str, 
        timestamp: float, 
        output_path: str,
        width: int = 1280
    ) -> str:
        """動画から指定時刻のスクリーンショットを抽出"""
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(timestamp),
            "-i", video_path,
            "-frames:v", "1",
            "-vf", f"scale={width}:-1",
            output_path
        ]
        
        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=30)
        except subprocess.TimeoutExpired as e:
            logger.error(f"FFmpeg screenshot extraction timed out for {video_path} at {timestamp}s: {e}")
            self._create_placeholder_image(output_path, width, int(width * 9 // 16), f"Timeout: {timestamp}s")
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg screenshot extraction failed for {video_path} at {timestamp}s: {e.stderr}")
            self._create_placeholder_image(output_path, width, int(width * 9 // 16), f"Error: {timestamp}s")
        except Exception as e:
            logger.error(f"Error during screenshot extraction: {e}")
            self._create_placeholder_image(output_path, width, int(width * 9 // 16), f"Failed: {timestamp}s")
            
        return output_path
    
    def create_comparison_image(
        self, 
        before_path: str, 
        after_path: str, 
        output_path: str,
        label_before: str = "Before",
        label_after: str = "After",
        apply_contrast: bool = False,
        apply_sharpen: bool = True
    ) -> str:
        """
        Before/Afterを横並び合成
        
        Args:
            before_path: 処理前画像
            after_path: 処理後画像
            output_path: 出力パス
            label_before: Beforeラベル
            label_after: Afterラベル
            apply_contrast: コントラスト自動調整を適用するか
            apply_sharpen: シャープネスフィルタを適用するか
        
        Returns:
            出力パス
        """
        from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
        
        if not Path(before_path).exists() and not Path(after_path).exists():
            raise FileNotFoundError(f"Both before and after images are missing: {before_path}, {after_path}")
            
        if not Path(before_path).exists():
            logger.warning(f"Before image missing: {before_path}. Using after image as placeholder.")
            before_path = after_path
        elif not Path(after_path).exists():
            logger.warning(f"After image missing: {after_path}. Using before image as placeholder.")
            after_path = before_path
        
        try:
            with Image.open(before_path) as before_img, Image.open(after_path) as after_img:
                # サイズ統一
                target_height = min(before_img.height, after_img.height, 720)
                
                before_ratio = target_height / before_img.height
                after_ratio = target_height / after_img.height
                
                # アスペクト比を維持してリサイズ
                before_width = int(before_img.width * before_ratio)
                after_width = int(after_img.width * after_ratio)
                
                # 幅が極端に0になるのを防止
                before_width = max(1, before_width)
                after_width = max(1, after_width)
                
                before_resized = before_img.resize(
                    (before_width, target_height),
                    Image.Resampling.LANCZOS
                )
                after_resized = after_img.resize(
                    (after_width, target_height),
                    Image.Resampling.LANCZOS
                )
                
                # 品質向上処理
                if apply_contrast:
                    before_resized = ImageOps.autocontrast(before_resized)
                    after_resized = ImageOps.autocontrast(after_resized)
                if apply_sharpen:
                    before_resized = before_resized.filter(ImageFilter.SHARPEN)
                    after_resized = after_resized.filter(ImageFilter.SHARPEN)
                
                # 合成キャンバス（中央に区切り線）
                gap = 4
                total_width = before_resized.width + gap + after_resized.width
                header_height = 30
                
                with Image.new('RGB', (total_width, target_height + header_height), (30, 30, 30)) as canvas:
                    # ラベル描画
                    draw = ImageDraw.Draw(canvas)
                    try:
                        font = ImageFont.truetype("C:/Windows/Fonts/Yu Gothic UI.ttf", 16)
                    except (OSError, ValueError, RuntimeError):
                        font = ImageFont.load_default()
                    
                    draw.text((10, 5), label_before, fill=(200, 200, 200), font=font)
                    draw.text((before_resized.width + gap + 10, 5), label_after, fill=(100, 255, 100), font=font)
                    
                    # 画像配置
                    canvas.paste(before_resized, (0, header_height))
                    canvas.paste(after_resized, (before_resized.width + gap, header_height))
                    
                    # 区切り線
                    draw.line(
                        [(before_resized.width + 1, header_height), 
                         (before_resized.width + 1, target_height + header_height)],
                        fill=(255, 255, 255), width=2
                    )
                    
                    # 高品質での保存パラメータ設定
                    canvas.save(
                        output_path, 
                        quality=95, 
                        subsampling=0, 
                        optimize=True
                    )
                    logger.info(f"Comparison image saved with enhanced quality: {output_path}")
                
                before_resized.close()
                after_resized.close()
                
            return output_path
        except (OSError, ValueError, RuntimeError) as e:
            logger.error(f"Failed to create comparison image: {e}")
            try:
                # フォールバックとしてAfter画像をそのままコピー
                from shutil import copy
                copy(after_path, output_path)
                return output_path
            except Exception as copy_err:
                logger.error(f"Comparison ultimate fallback failed: {copy_err}")
                raise e
    
    def _determine_snapshot_timestamps(
        self, 
        before_video: str, 
        after_video: str, 
        num_samples: int, 
        timestamps: Optional[list[float]]
    ) -> list[float]:
        """snapshot_step 用のタイムスタンプを決定する"""
        if timestamps is not None:
            return timestamps

        # 短い方のデュレーションを基準にする
        dur_before = self._get_video_duration(before_video)
        dur_after = self._get_video_duration(after_video)
        min_duration = min(dur_before, dur_after) if (dur_before > 0 and dur_after > 0) else max(dur_before, dur_after)
        
        raw_timestamps = self.detect_feature_points(after_video, num_samples)
        if min_duration > 0:
            # デュレーションの95%以下に制限（マージンを持たせる）
            limit_duration = min_duration * 0.95
            resolved_timestamps = [ts for ts in raw_timestamps if ts < limit_duration]
        else:
            resolved_timestamps = raw_timestamps
            
        # もしサンプリングポイントが足りなくなった場合、短い方を基準に等間隔サンプリング
        if len(resolved_timestamps) < num_samples and min_duration > 0:
            limit_duration = min_duration * 0.95
            interval = limit_duration / (num_samples + 1)
            resolved_timestamps = [interval * (i + 1) for i in range(num_samples)]
            
        return resolved_timestamps

    def _extract_screenshots_parallel(
        self, 
        before_video: str, 
        after_video: str, 
        timestamps: list[float], 
        step_dir: Path
    ) -> list[tuple[int, float, str, str]]:
        """並列でBefore/Afterのスクリーンショットを抽出する"""
        def extract_pair(args):
            """並列実行用: 1つのタイムスタンプでBefore/After抽出"""
            i, ts = args
            before_ss = step_dir / f"before_{i+1}_{ts:.1f}s.png"
            after_ss = step_dir / f"after_{i+1}_{ts:.1f}s.png"
            
            self.extract_screenshot(before_video, ts, str(before_ss))
            self.extract_screenshot(after_video, ts, str(after_ss))
            
            return i, ts, str(before_ss), str(after_ss)
        
        # 並列でスクリーンショット抽出（最大4スレッド）
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(extract_pair, (i, ts)) for i, ts in enumerate(timestamps)]
            results = []
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    logger.warning(f"Screenshot extraction failed: {e}")
        
        # 結果をソート（タイムスタンプ順）
        results.sort(key=lambda x: x[0])
        return results

    def _generate_comparisons_and_diffs(
        self, 
        step_dir: Path, 
        extracted_results: list[tuple[int, float, str, str]],
        total_timestamps_len: int
    ) -> list[dict]:
        """抽出したスクリーンショット群から比較画像と差分ハイライト画像を生成する"""
        # 実際に画像ファイルが正常に生成されたもののみを処理対象にする
        valid_results = []
        for i, ts, before_ss, after_ss in extracted_results:
            if Path(before_ss).exists() and Path(after_ss).exists():
                valid_results.append((i, ts, before_ss, after_ss))
            else:
                logger.warning(
                    f"Skipping sample {i+1} at {ts:.1f}s because screenshot files "
                    f"were not generated correctly (before exists: {Path(before_ss).exists()}, "
                    f"after exists: {Path(after_ss).exists()})."
                )
        
        comparisons = []
        # 比較画像生成（差分ハイライト付き）
        for i, ts, before_ss, after_ss in valid_results:
            comparison = step_dir / f"comparison_{i+1}_{ts:.1f}s.png"
            diff_path = step_dir / f"diff_{i+1}_{ts:.1f}s.png"
            
            # 差分ハイライト画像を生成
            self.create_diff_highlight(before_ss, after_ss, str(diff_path))
            
            self.create_comparison_image(
                before_ss, 
                after_ss, 
                str(comparison),
                f"Before ({ts:.1f}s)",
                f"After ({ts:.1f}s)"
            )
            
            comparisons.append({
                "timestamp": ts,
                "before": before_ss,
                "after": after_ss,
                "comparison": str(comparison),
                "diff_highlight": str(diff_path)
            })
            
            logger.info(f"  ✅ Sample {i+1}/{total_timestamps_len}: {ts:.1f}s")
            
        return comparisons

    def snapshot_step(
        self, 
        step_name: str,
        before_video: str, 
        after_video: str,
        num_samples: int = 3,
        timestamps: Optional[list[float]] = None
    ) -> dict:
        """
        処理ステップ完了時に呼び出し、比較画像を生成
        
        Args:
            step_name: 処理ステップ名（例: "crop", "logo", "subtitle"）
            before_video: 処理前の動画パス
            after_video: 処理後の動画パス
            num_samples: サンプル数
            timestamps: 指定タイムスタンプ（未指定で自動検出）
        
        Returns:
            ステップ結果のdict
        """
        step_dir = self.output_dir / step_name
        step_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"\n{'='*60}")
        logger.info(f"📸 Snapshot Step: {step_name}")
        logger.info(f"{'='*60}")
        
        # タイムスタンプ決定
        resolved_timestamps = self._determine_snapshot_timestamps(
            before_video, after_video, num_samples, timestamps
        )
        
        # 並列でスクリーンショット抽出
        extracted = self._extract_screenshots_parallel(
            before_video, after_video, resolved_timestamps, step_dir
        )
        
        # 比較画像と差分ハイライトの生成
        comparisons = self._generate_comparisons_and_diffs(
            step_dir, extracted, len(resolved_timestamps)
        )
        
        step_result = {
            "step_name": step_name,
            "before_video": before_video,
            "after_video": after_video,
            "created_at": datetime.now().isoformat(),
            "comparisons": comparisons
        }
        
        self.steps.append(step_result)
        self._save_metadata()
        
        logger.info(f"\n✅ Step '{step_name}' completed with {len(comparisons)} comparisons")
        
        return step_result
    
    def _save_metadata(self):
        """メタデータをJSONに保存"""
        metadata = {
            "session_id": self.session_id,
            "created_at": datetime.now().isoformat(),
            "steps": self.steps
        }
        
        with open(self.metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    
    def get_all_comparisons(self) -> list[str]:
        """全ステップの比較画像パスをリストで返す"""
        comparisons = []
        for step in self.steps:
            for comp in step.get("comparisons", []):
                comparisons.append(comp["comparison"])
        return comparisons
    
    # === Phase 30.6: 差分ハイライト機能 ===
    def create_diff_highlight(
        self,
        before_path: str,
        after_path: str,
        output_path: str,
        threshold: int = 30,
        highlight_color: tuple = (255, 0, 0, 180),
        min_diff_area: int = 4
    ) -> str:
        """
        Before/After間の差分を検出し、変更箇所を赤でハイライト表示
        
        Args:
            before_path: 処理前画像パス
            after_path: 処理後画像パス
            output_path: 差分ハイライト画像の出力パス
            threshold: 差分検出の閾値（0-255、低いほど敏感）
            highlight_color: ハイライト色 (R, G, B, A)
            min_diff_area: ノイズ除去用の最小連続領域閾値（簡易版）
        
        Returns:
            出力パス
        """
        from PIL import Image, ImageChops
        
        if not Path(before_path).exists() or not Path(after_path).exists():
            logger.warning(f"Missing image for diff: before={before_path}, after={after_path}")
            if Path(after_path).exists():
                from shutil import copy
                copy(after_path, output_path)
                return output_path
            elif Path(before_path).exists():
                from shutil import copy
                copy(before_path, output_path)
                return output_path
            else:
                raise FileNotFoundError("Both source images missing for diff highlight")
                
        try:
            with Image.open(before_path) as before_raw, Image.open(after_path) as after_raw:
                before_img = before_raw.convert('RGBA')
                after_img = after_raw.convert('RGBA')
                
                # サイズを揃える
                if before_img.size != after_img.size:
                    after_resized = after_img.resize(before_img.size, Image.Resampling.LANCZOS)
                    after_img.close()
                    after_img = after_resized
                
                # 差分を計算
                with before_img.convert('RGB') as before_rgb, after_img.convert('RGB') as after_rgb:
                    with ImageChops.difference(before_rgb, after_rgb) as diff:
                        with diff.convert('L') as diff_gray:
                            diff_array = np.array(diff_gray)
                            mask = diff_array > threshold
                            
                            # ノイズの除去
                            if min_diff_area > 0 and np.any(mask):
                                try:
                                    from scipy.ndimage import binary_opening
                                    mask = binary_opening(mask, structure=np.ones((2, 2)))
                                except ImportError:
                                    # scipy がない場合のフォールバック: 孤立ピクセル除去
                                    padded = np.pad(mask, 1, mode='constant', constant_values=False)
                                    neighbors = (
                                        padded[1:-1, :-2] | padded[1:-1, 2:] | 
                                        padded[:-2, 1:-1] | padded[2:, 1:-1]
                                    )
                                    mask = mask & neighbors
                
                # ハイライト画像 (RGBA) を NumPy で効率的に作成
                highlight_array = np.zeros((before_img.height, before_img.width, 4), dtype=np.uint8)
                highlight_array[mask] = highlight_color
                
                with Image.fromarray(highlight_array, 'RGBA') as highlight:
                    with Image.alpha_composite(after_img, highlight) as result:
                        result.save(output_path, quality=95, optimize=True)
                        logger.info(f"Diff highlight saved with high quality: {output_path}")
                
                before_img.close()
                after_img.close()
                
            return output_path
        except (OSError, ValueError, RuntimeError) as e:
            logger.warning(f"Failed to create diff highlight: {e}")
            from shutil import copy
            copy(after_path, output_path)
            return output_path
    
    # === Phase 30.6: 音声波形分析による無音区間検出 ===
    def detect_silence_points(
        self,
        video_path: str,
        silence_threshold: str = "-30dB",
        min_silence_duration: float = 0.5,
        max_points: int = 5
    ) -> list[float]:
        """
        FFmpegのsilencedetectフィルタで無音区間を検出し、特徴点として返す
        
        Args:
            video_path: 動画パス
            silence_threshold: 無音判定の閾値（dB）
            min_silence_duration: 最小無音時間（秒）
            max_points: 最大検出ポイント数
        
        Returns:
            無音区間の開始タイムスタンプリスト
        """
        logger.info(f"Detecting silence points: {video_path}")
        
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-af", f"silencedetect=noise={silence_threshold}:d={min_silence_duration}",
            "-f", "null",
            "-"
        ]
        
        try:
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=60,
                encoding='utf-8',
                errors='ignore'
            )
            
            # stderr から silence_start を抽出
            import re
            pattern = r'silence_start: ([\d.]+)'
            matches = re.findall(pattern, result.stderr)
            
            timestamps = [float(ts) for ts in matches]
            
            if len(timestamps) > max_points:
                step = len(timestamps) // max_points
                timestamps = timestamps[::step][:max_points]
            
            logger.info(f"Detected {len(timestamps)} silence points")
            return timestamps
            
        except subprocess.TimeoutExpired:
            logger.warning("Silence detection timed out")
            return []
        except Exception as e:
            logger.error(f"Silence detection error: {e}")
            return []
    
    def detect_feature_points_enhanced(
        self,
        video_path: str,
        max_points: int = 5,
        srt_path: Optional[str] = None,
        include_silence: bool = True
    ) -> list[float]:
        """
        拡張特徴点検出: シーン変化 + 字幕タイミング + 無音区間
        
        Args:
            video_path: 動画パス
            max_points: 最大検出ポイント数
            srt_path: 字幕ファイルパス
            include_silence: 無音区間を含めるか
        
        Returns:
            統合された特徴点リスト
        """
        all_timestamps = []
        
        # 1. 既存の特徴点検出（シーン変化 + 字幕）
        base_points = self.detect_feature_points(video_path, max_points * 2, srt_path=srt_path)
        all_timestamps.extend(base_points)
        
        # 2. 無音区間を追加
        if include_silence:
            silence_points = self.detect_silence_points(video_path, max_points=max_points)
            all_timestamps.extend(silence_points)
        
        # 重複除去・ソート・間引き
        if all_timestamps:
            return self._filter_and_thin_timestamps(all_timestamps, max_points)
        
        return self._fallback_sampling(video_path, max_points)

    def validate_thumbnail_quality(self, file_path) -> dict:
        """サムネイル・プレビュー画像の品質要件を検証する"""
        from PIL import Image
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Preview file not found: {file_path}")
            
        size_bytes = file_path.stat().st_size
        if size_bytes >= 4 * 1024 * 1024:
            raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")
            
        try:
            with Image.open(file_path) as img:
                img.verify()
        except Exception as e:
            raise ValueError(f"Image is corrupted or invalid format: {e}")
            
        try:
            with Image.open(file_path) as img:
                img.load()
                width, height = img.size
        except Exception as e:
            raise ValueError(f"Image is corrupted or invalid format: {e}")
            
        if width < 1280 or height < 720:
            raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
            
        aspect_ratio = width / height
        target_ratio = 16.0 / 9.0
        # 16:9 の誤差許容（アスペクト比 16/9 = 1.777...）
        if abs(aspect_ratio - target_ratio) > 0.05:
            raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")
            
        return {
            "path": str(file_path),
            "width": width,
            "height": height,
            "size_bytes": size_bytes
        }

    async def resolve_progressive_preview_task(self, task_id: str) -> str:
        """StageBoundAgent の process_func として動作する非同期タスク処理"""
        import json
        # **リポジトリ相対の直書きにしない。** ここは実行のたびに中身が変わる
        # 出力なので `writable_path` が置き場を決める（テストでは conftest が
        # 一時ディレクトリへ向ける）。直書きだと CWD 次第でリポジトリの中に
        # `backend/temp/previews/<task_id>.png` が落ち、本番ファイル汚染
        # ラチェットが赤くなる（2026-08-17 の CI 実測: その他 116 → 118）。
        output_dir = Path(getattr(self, "output_dir", None)
                          or writable_path("backend/temp/previews"))
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{task_id}.png"
        
        width = getattr(self, "width", 1280)
        height = getattr(self, "height", 720)
        video_path = getattr(self, "video_path", None)
        timestamp = getattr(self, "timestamp", 1.0)
        
        if video_path and Path(video_path).exists():
            self.extract_screenshot(video_path, timestamp, str(output_path), width=width)
        else:
            # テスト/ダミー用: 高品質画像を生成
            from PIL import Image, ImageDraw
            img = Image.new("RGB", (width, height), color=(50, 80, 120))
            draw = ImageDraw.Draw(img)
            draw.text((20, 20), f"Preview Task: {task_id}", fill=(255, 255, 255))
            img.save(output_path, "PNG")
            
        result_info = self.validate_thumbnail_quality(output_path)
        return json.dumps(result_info)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    
    # テスト用
    preview = ProgressivePreview(session_id="test_session")
    
    # ダミーテスト（実際の動画パスを指定）
    test_video = str(project_root() / "test_10sec.mp4")
    
    if Path(test_video).exists():
        # 同じ動画でBefore/Afterテスト（実際は処理後動画を指定）
        result = preview.snapshot_step(
            step_name="test_step",
            before_video=test_video,
            after_video=test_video,
            num_samples=3
        )
        
        print("\n📊 Result:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Test video not found: {test_video}")
