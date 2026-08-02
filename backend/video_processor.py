"""
VideoProcessor - 動画処理統合モジュール

ムード選択からFFmpeg処理、プレビュー生成までを統合
"""

import os
import time
import logging
import subprocess
import json
from pathlib import Path
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

from path_resolver import raw_videos_dir, writable_path as _writable_path

logger = logging.getLogger(__name__)

class ProcessingPhase(Enum):
    IDLE = "idle"
    PREFLIGHT = "preflight"
    PROCESSING = "processing"
    MERGING = "merging"
    FINALIZING = "finalizing"
    COMPLETE = "complete"
    ERROR = "error"

class VideoMood(Enum):
    ELEGANT = "elegant"
    DYNAMIC = "dynamic"
    DRAMATIC = "dramatic"

@dataclass
class MoodSettings:
    """ムード別の動画処理設定"""
    name: str
    color_preset: str  # FFmpegカラープリセット
    transition: str    # トランジションタイプ
    music_style: str   # BGMスタイル
    telop_style: str   # テロップスタイル
    logo_opacity: float = 0.6
    telop_size: int = 24

# ムード設定マッピング
MOOD_SETTINGS: Dict[str, MoodSettings] = {
    "elegant": MoodSettings(
        name="エレガント",
        color_preset="warm",
        transition="fade",
        music_style="classical",
        telop_style="minimal",
        logo_opacity=0.5,
        telop_size=22
    ),
    "dynamic": MoodSettings(
        name="ダイナミック",
        color_preset="vibrant",
        transition="wipe",
        music_style="upbeat",
        telop_style="bold",
        logo_opacity=0.7,
        telop_size=28
    ),
    "dramatic": MoodSettings(
        name="ドラマチック",
        color_preset="cinematic",
        transition="crossfade",
        music_style="orchestral",
        telop_style="dramatic",
        logo_opacity=0.6,
        telop_size=26
    ),
}

@dataclass
class ProcessingTask:
    """処理タスク"""
    task_id: str
    video_paths: List[str]
    mood: str
    guest_assets: List[str] = field(default_factory=list)
    output_name: str = "output"
    
    # 状態
    phase: ProcessingPhase = ProcessingPhase.IDLE
    progress: int = 0
    current_step: str = "待機中"
    output_path: Optional[str] = None
    preview_url: Optional[str] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)

class VideoProcessor:
    """動画処理エンジン"""
    
    def __init__(self, output_dir: str = None):
        # 絶対パスで出力ディレクトリを設定（二重構造バグ防止）
        if output_dir is None:
            # このファイルの親ディレクトリ（backend）基準で設定
            base_dir = Path(__file__).parent
            output_dir = base_dir / "temp" / "video_output"
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.tasks: Dict[str, ProcessingTask] = {}
        self._progress_callback: Optional[Callable] = None
    
    def set_progress_callback(self, callback: Callable):
        """進捗コールバックを設定（WebSocket通知用）"""
        self._progress_callback = callback
    
    def _notify_progress(self, task: ProcessingTask):
        """進捗を通知"""
        if self._progress_callback:
            self._progress_callback(task)
    
    def get_mood_settings(self, mood: str) -> MoodSettings:
        """ムード設定を取得"""
        return MOOD_SETTINGS.get(mood.lower(), MOOD_SETTINGS["elegant"])
    
    def _record_soul_narrative(self, task_id: str, output_name: str, settings: MoodSettings, scene_count: int):
        """Soul Narrative: 制作履歴をevolution_logに自動記録"""
        try:
            import json
            from datetime import datetime
            
            evolution_log_path = _writable_path("backend/branding/evolution_log.json")
            
            # 既存ログを読み込み
            if evolution_log_path.exists():
                with open(evolution_log_path, 'r', encoding='utf-8') as f:
                    evo_log = json.load(f)
            else:
                evo_log = {"entries": [], "philosophies": []}
            
            # 新しいエントリを追加
            new_entry = {
                "timestamp": time.time(),
                "iso_time": datetime.now().isoformat(),
                "type": "video_production",
                "task_id": task_id,
                "summary": f"{output_name} - {settings.name}スタイルで{scene_count}シーンを編集",
                "insight": f"カラープリセット'{settings.color_preset}'と遷移'{settings.transition}'を使用。" +
                           f"テンポ{getattr(settings, 'tempo', 'standard')}の演出で制作完了。",
                "stat_changes": [
                    f"Production Count +1",
                    f"Style: {settings.name}"
                ]
            }
            
            evo_log["entries"].append(new_entry)
            
            # 最新10件のみ保持
            if len(evo_log["entries"]) > 10:
                evo_log["entries"] = evo_log["entries"][-10:]
            
            # 保存
            with open(evolution_log_path, 'w', encoding='utf-8') as f:
                json.dump(evo_log, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Soul Narrative recorded: {task_id}")
        except (json.JSONDecodeError, OSError, IOError) as e:
            logger.warning(f"Failed to record Soul Narrative (IO/JSON error): {e}")
        except Exception as e:
            logger.error(f"Unexpected error recording Soul Narrative: {e}")
    
    def create_task(
        self,
        task_id: str,
        video_paths: List[str],
        mood: str,
        guest_assets: List[str] = None,
        output_name: str = "output"
    ) -> ProcessingTask:
        """処理タスクを作成"""
        if not task_id or not isinstance(task_id, str):
            raise ValueError("task_id must be a non-empty string")
        if not isinstance(video_paths, list):
            raise ValueError("video_paths must be a list of strings")
        if not video_paths:
            raise ValueError("video_paths must not be empty")
        if not all(isinstance(p, str) for p in video_paths):
            raise ValueError("all elements in video_paths must be strings")
        if not mood or not isinstance(mood, str):
            raise ValueError("mood must be a non-empty string")

        task = ProcessingTask(
            task_id=task_id,
            video_paths=video_paths,
            mood=mood,
            guest_assets=guest_assets or [],
            output_name=output_name
        )
        self.tasks[task_id] = task
        logger.info(f"Task created: {task_id} with mood '{mood}'")
        return task
    
    def get_task(self, task_id: str) -> Optional[ProcessingTask]:
        """タスクを取得"""
        return self.tasks.get(task_id)
    
    def process_video(self, task_id: str) -> bool:
        """動画処理を実行"""
        task = self.get_task(task_id)
        if not task:
            logger.error(f"Task not found: {task_id}")
            return False
        
        try:
            settings = self.get_mood_settings(task.mood)
            
            # Phase 1: プリフライトチェック
            task.phase = ProcessingPhase.PREFLIGHT
            task.current_step = "素材ファイルを確認中..."
            task.progress = 5
            self._notify_progress(task)
            
            # 動画ファイル存在確認
            valid_paths = []
            for path in task.video_paths:
                if Path(path).exists():
                    valid_paths.append(path)
                else:
                    logger.warning(f"Video not found: {path}")
            
            if not valid_paths:
                # デモ用：既存の動画を使用（複数パス候補）
                demo_dirs = [
                    Path("raw_videos/AI Studio アップロード用動画"),
                    raw_videos_dir() / "AI Studio アップロード用動画",
                    Path("../raw_videos/AI Studio アップロード用動画"),
                ]
                for demo_dir in demo_dirs:
                    if demo_dir.exists():
                        valid_paths = [str(p) for p in demo_dir.glob("*.mp4")][:4]
                        if valid_paths:
                            logger.info(f"Using demo videos from: {demo_dir}")
                            break
            
            task.progress = 10
            self._notify_progress(task)
            time.sleep(0.5)
            
            # Phase 2: ムード設定適用
            task.current_step = f"ムード '{settings.name}' を適用中..."
            task.progress = 15
            self._notify_progress(task)
            time.sleep(0.5)
            
            # Phase 3: 各シーンを処理
            task.phase = ProcessingPhase.PROCESSING
            processed_scenes = []
            
            for i, video_path in enumerate(valid_paths):
                scene_num = i + 1
                # 各シーンの進捗範囲を計算（15%〜65%の範囲を4シーンで分割）
                scene_progress_start = 15 + int((i / len(valid_paths)) * 50)
                scene_progress_range = int(50 / len(valid_paths))  # 1シーンあたりの進捗幅
                
                task.current_step = f"シーン {scene_num}/{len(valid_paths)} を処理中..."
                task.progress = scene_progress_start
                self._notify_progress(task)
                
                # FFmpeg処理（リアルタイム進捗更新対応）
                output_scene = self.output_dir / f"scene_{scene_num}_{task_id[:8]}.mp4"
                self._process_scene(
                    video_path, str(output_scene), settings,
                    task=task, base_progress=scene_progress_start, progress_range=scene_progress_range
                )
                processed_scenes.append(str(output_scene))
            
            # Phase 4: マージ処理
            task.phase = ProcessingPhase.MERGING
            task.current_step = "シーンをマージ中..."
            task.progress = 75
            self._notify_progress(task)
            
            merged_path = self.output_dir / f"merged_{task_id[:8]}.mp4"
            self._merge_scenes(processed_scenes, str(merged_path))
            
            task.progress = 85
            time.sleep(0.5)
            
            # Phase 5: 最終処理
            task.phase = ProcessingPhase.FINALIZING
            task.current_step = "ロゴ・テロップを適用中..."
            task.progress = 90
            self._notify_progress(task)
            
            final_path = self.output_dir / f"{task.output_name}_{task_id[:8]}.mp4"
            self._apply_branding(str(merged_path), str(final_path), settings)
            
            task.progress = 95
            time.sleep(0.5)
            
            # 完了
            task.phase = ProcessingPhase.COMPLETE
            task.current_step = "処理完了"
            task.progress = 100
            task.output_path = str(final_path)
            task.preview_url = f"/api/video/preview/{task_id}"
            self._notify_progress(task)
            
            # Soul Narrative: 制作履歴を自動記録
            self._record_soul_narrative(task_id, task.output_name, settings, len(valid_paths))
            
            logger.info(f"Task completed: {task_id} -> {final_path}")
            return True
            
        except Exception as e:
            task.phase = ProcessingPhase.ERROR
            task.error = str(e)
            task.current_step = f"エラー: {str(e)}"
            self._notify_progress(task)
            logger.exception(f"Task failed with exception: {task_id} - {e}")
            return False
    
    def _run_ffmpeg(self, cmd: List[str], description: str, timeout: int = 600, 
                     task: ProcessingTask = None, base_progress: int = 0, progress_range: int = 10) -> bool:
        """FFmpegコマンドを実行（リアルタイム進捗更新対応）"""
        logger.info(f"[{description}] Starting...")
        
        import re
        import threading
        
        process = None
        progress_thread = None
        try:
            # Popenでプロセスを開始（stderrからリアルタイム読み取り）
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )
            
            # 進捗解析用の変数
            duration_seconds = None
            last_update_time = time.time()
            
            def parse_progress():
                nonlocal duration_seconds, last_update_time
                try:
                    # process.stderr を直接イテレートすることでモックの poll() 無限ループを回避
                    for line in process.stderr:
                        if not line:
                            continue
                        
                        # Duration取得（例: Duration: (\d+):(\d+):(\d+\.\d+)）
                        if duration_seconds is None:
                            duration_match = re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)', line)
                            if duration_match:
                                h, m, s = duration_match.groups()
                                duration_seconds = int(h) * 3600 + int(m) * 60 + float(s)
                        
                        # 現在時間取得（例: time=(\d+):(\d+):(\d+\.\d+)）
                        time_match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
                        if time_match and duration_seconds and task:
                            h, m, s = time_match.groups()
                            current_seconds = int(h) * 3600 + int(m) * 60 + float(s)
                            
                            # 進捗率計算（1秒ごとに更新）
                            if time.time() - last_update_time >= 1.0:
                                ffmpeg_progress = min(current_seconds / duration_seconds, 1.0)
                                task.progress = base_progress + int(ffmpeg_progress * progress_range)
                                task.current_step = f"{description} ({int(ffmpeg_progress * 100)}%)"
                                self._notify_progress(task)
                                last_update_time = time.time()
                                logger.debug(f"Progress: {task.progress}% - {task.current_step}")
                except Exception as thread_err:
                    logger.warning(f"Error parsing FFmpeg progress in thread: {thread_err}")
            
            # 別スレッドで進捗解析
            progress_thread = threading.Thread(target=parse_progress, daemon=True)
            progress_thread.start()
            
            # プロセス完了待機
            process.wait(timeout=timeout)
            
            if process.returncode == 0:
                logger.info(f"✅ {description}")
                return True
            else:
                stderr_output = process.stderr.read() if process.stderr else ''
                logger.error(f"❌ {description} failed with code {process.returncode}: {stderr_output[-300:] if stderr_output else ''}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"❌ {description} timed out after {timeout}s")
            if process:
                try:
                    process.kill()
                    process.wait(timeout=5)  # ゾンビプロセス回収
                except (OSError, subprocess.SubprocessError) as kill_err:
                    logger.error(f"Failed to kill timed out process: {kill_err}")
            return False
        except Exception as e:
            logger.error(f"❌ {description} error: {e}")
            if process:
                try:
                    process.kill()
                    process.wait(timeout=5)
                except OSError as kill_err:
                    logger.warning(f"Failed to kill or wait process: {kill_err}")
            return False
        finally:
            if progress_thread and progress_thread.is_alive():
                progress_thread.join(timeout=5)
    
    def _get_color_filter(self, settings: MoodSettings) -> str:
        """ムード別のカラーフィルタを生成（H-1: テーマ名統一対応）"""
        filters = {
            # 旧名（互換性維持）
            "warm": "colorbalance=rs=0.1:gs=0:bs=-0.1:rm=0.1:gm=0:bm=-0.05",
            "vibrant": "eq=saturation=1.3:contrast=1.1,colorbalance=rs=0.05:gs=0.05:bs=0.05",
            "cinematic": "eq=saturation=0.9:contrast=1.2,colorbalance=rs=-0.05:gs=-0.05:bs=0.1",
            # MOOD_THEMES名（themes_router統一）
            "cool": "eq=saturation=0.9:contrast=1.2,colorbalance=rs=-0.05:gs=-0.05:bs=0.1",
            "energetic": "eq=saturation=1.3:contrast=1.1,colorbalance=rs=0.05:gs=0.05:bs=0.05",
            "calm": "eq=saturation=0.85:contrast=1.0,colorbalance=rs=-0.03:gs=-0.02:bs=0.05",
            "elegant": "eq=saturation=0.9:contrast=1.2,colorbalance=rs=-0.05:gs=-0.05:bs=0.1",
        }
        return filters.get(settings.color_preset, "")
    
    def _get_audio_normalize_args(self, input_path: str) -> list:
        """
        2パスEBU R128ノーマライズ引数を生成。
        Pass1で計測 → Pass2で精密適用。失敗時は1パスフォールバック。
        """
        try:
            from template_config import template_config
            
            # Pass 1: 計測（null出力でラウドネス統計を取得）
            pass1_filter = template_config.get_loudnorm_pass1_filter()
            measure_cmd = [
                "ffmpeg", "-i", input_path,
                "-af", pass1_filter,
                "-f", "null", "-"
            ]
            
            result = subprocess.run(
                measure_cmd, capture_output=True, text=True,
                timeout=120, encoding='utf-8', errors='ignore'
            )
            
            # stderrからJSON部分を抽出
            stderr = result.stderr or ""
            json_start = stderr.rfind("{")
            json_end = stderr.rfind("}") + 1
            
            if json_start >= 0 and json_end > json_start:
                measured = json.loads(stderr[json_start:json_end])
                pass2_filter = template_config.get_loudnorm_pass2_filter(measured)
                logger.info(f"🔊 2パスloudnorm適用: I={measured.get('input_i')} LUFS")
                return ["-af", pass2_filter]
            
            # JSON取得失敗 → 1パスフォールバック
            logger.warning("2パスloudnorm Pass1失敗 → 1パスフォ フォールバック") # 誤字に注意：フォールバックです。元の通りにします
            return ["-af", template_config.get_loudnorm_filter()]
            
        except (subprocess.SubprocessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.warning(f"音声ノーマライズ計測失敗（1パスへフォールバック）: {e}")
            try:
                from template_config import template_config
                return ["-af", template_config.get_loudnorm_filter()]
            except (ImportError, AttributeError):
                return []
        except (json.JSONDecodeError, KeyError, ValueError, AttributeError, ImportError) as e:
            logger.warning(f"音声ノーマライズ解析データの処理失敗（計測スキップ）: {e}")
            return []
        except Exception as e:
            logger.debug(f"音声ノーマライズスキップ（想定外のエラー）: {e}")
            return []

    
    def _process_scene(self, input_path: str, output_path: str, settings: MoodSettings,
                        task: ProcessingTask = None, base_progress: int = 0, progress_range: int = 10):
        """シーン単位の処理（FFmpeg実処理・リアルタイム進捗対応）"""
        logger.info(f"Processing scene: {input_path} -> {output_path}")
        
        # カラーフィルタ: テンプレート基準優先 → ムード設定フォールバック
        color_filter = ""
        try:
            from template_config import template_config
            if template_config.is_active:
                color_filter = template_config.get_color_grading_filter()
                if color_filter:
                    logger.info(f"🎨 テンプレートカラーグレーディング適用: {template_config.template_id}")
        except (ImportError, AttributeError) as e:
            logger.debug(f"Template color grading unavailable (Import/Attribute error): {e}")
        except Exception as e:
            logger.debug(f"Template color grading unavailable (Unexpected error): {e}")
        
        if not color_filter:
            color_filter = self._get_color_filter(settings)
        
        # 基本フィルタ（1280x720にスケール）
        base_filter = "scale=1280:720"
        
        # フィルタを結合
        if color_filter:
            video_filter = f"{base_filter},{color_filter}"
        else:
            video_filter = base_filter
        
        # 音声ノーマライズ: 2パス試行 → 1パスフォールバック
        audio_args = self._get_audio_normalize_args(input_path)
        
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", video_filter,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            *audio_args,
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            output_path
        ]
        
        # タスク情報を渡してリアルタイム進捗更新
        success = self._run_ffmpeg(
            cmd, f"シーン処理: {Path(input_path).name}", 
            timeout=600, task=task, base_progress=base_progress, progress_range=progress_range
        )
        
        if not success:
            # フォールバック: コピー処理
            logger.warning(f"FFmpeg failed, attempting copy: {input_path}")
            import shutil
            try:
                shutil.copy(input_path, output_path)
            except (shutil.Error, OSError) as e:
                logger.error(f"Copy also failed (IO error): {e}")
            except Exception as e:
                logger.error(f"Copy also failed (Unexpected error): {e}")
    
    def _merge_scenes(self, scene_paths: List[str], output_path: str):
        """シーンをマージ（FFmpeg concat demuxer使用）"""
        logger.info(f"Merging {len(scene_paths)} scenes -> {output_path}")
        
        # 有効なシーンパスのみ使用
        valid_paths = [p for p in scene_paths if Path(p).exists()]
        
        if len(valid_paths) == 0:
            logger.warning("No valid scenes to merge")
            return
        
        if len(valid_paths) == 1:
            # シーンが1つの場合はコピー
            import shutil
            try:
                shutil.copy(valid_paths[0], output_path)
            except (shutil.Error, OSError) as e:
                logger.error(f"Copy single scene failed: {e}")
            return
        
        # concat用ファイルリストを作成
        concat_file = self.output_dir / "concat_list.txt"
        with open(concat_file, "w", encoding="utf-8") as f:
            for path in valid_paths:
                # Windowsパスをスラッシュに変換
                safe_path = str(Path(path).absolute()).replace("\\", "/")
                f.write(f"file '{safe_path}'\n")
        
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            output_path
        ]
        
        success = self._run_ffmpeg(cmd, "Merge scenes", timeout=600)
        
        if not success:
            # フォールバック: 最初のシーンをコピー
            logger.warning("Merge failed, using first scene only")
            import shutil
            if valid_paths:
                try:
                    shutil.copy(valid_paths[0], output_path)
                except (shutil.Error, OSError) as e:
                    logger.error(f"Copy first scene failed: {e}")
    
    def _apply_branding(self, input_path: str, output_path: str, settings: MoodSettings):
        """ロゴ・テロップを適用（FFmpeg overlay）"""
        logger.info(f"Applying branding: {input_path} -> {output_path}")
        
        # ロゴパス
        base_dir = Path(__file__).parent
        logo_path = base_dir / "branding" / "logos" / "brand_logo.png"
        
        if not logo_path.exists():
            # ロゴがない場合はコピー
            logger.warning(f"Logo not found at {logo_path}, skipping branding")
            import shutil
            try:
                shutil.copy(input_path, output_path)
            except (shutil.Error, OSError) as e:
                logger.error(f"Copy without branding failed: {e}")
            return
        
        # オーバーレイフィルタ（ロゴを左上に配置）
        opacity = settings.logo_opacity
        overlay_filter = f"overlay=15:15:alpha={opacity}"
        
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-i", str(logo_path),
            "-filter_complex", overlay_filter,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "copy", "-movflags", "+faststart",
            output_path
        ]
        
        success = self._run_ffmpeg(cmd, "Apply branding", timeout=600)
        
        if not success:
            # フォールバック: ブランディングなしでコピー
            logger.warning("Branding failed, copying without branding")
            import shutil
            try:
                shutil.copy(input_path, output_path)
            except (shutil.Error, OSError) as e:
                logger.error(f"Copy without branding failed: {e}")

# シングルトンインスタンス
video_processor = VideoProcessor()

