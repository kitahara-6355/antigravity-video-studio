"""
Whisper Transcriber - Phase 18 Architecture
faster-whisper による高精度タイムスタンプ付き音声認識
"""

from faster_whisper import WhisperModel
from pathlib import Path
from typing import List, Dict, Optional, Callable
import logging
import time
import subprocess
import json as _json

from path_resolver import vault_environments_dir

logger = logging.getLogger(__name__)


class WhisperTranscriber:
    """faster-whisper 統合クラス（Phase E: large-v3 対応）"""
    
    def __init__(self, model_size: str = "large-v3"):
        """
        Args:
            model_size: Whisperモデルサイズ（tiny, base, small, medium, large-v3）
        """
        self.model_size = model_size
        self.model = None
        self.last_progress_update = 0
    
    def _add_cuda_dll_paths(self):
        """CUDA DLL パスを自動追加"""
        import os, sys
        _nvidia_search_paths = [
            Path(sys.executable).parent.parent / "Lib" / "site-packages" / "nvidia",
            vault_environments_dir() / ".venv" / "Lib" / "site-packages" / "nvidia",
        ]
        for site_packages in _nvidia_search_paths:
            if site_packages.exists():
                for sub in ["cublas/bin", "cudnn/bin", "cuda_nvrtc/bin"]:
                    dll_path = str(site_packages / sub)
                    if Path(dll_path).exists() and dll_path not in os.environ.get("PATH", ""):
                        os.environ["PATH"] = dll_path + os.pathsep + os.environ.get("PATH", "")
                        logger.info(f"📂 CUDA DLL path added: {dll_path}")

    def _detect_gpu_device(self) -> tuple[str, str]:
        """GPU自動検出: CUDAが使えれば高速化"""
        device = "cpu"
        compute_type = "int8"
        try:
            import ctranslate2
            ctranslate2.get_supported_compute_types("cuda")
            device = "cuda"
            compute_type = "float16"
            logger.info("🚀 CUDA GPU detected — attempting GPU acceleration")
        except (ImportError, ValueError, RuntimeError) as gpu_detect_err:
            logger.info(f"⚠️ CUDA not available ({type(gpu_detect_err).__name__}: {gpu_detect_err}) — using CPU (slower)")
        except (AttributeError, OSError, TypeError) as e:
            logger.warning(f"Unexpected error detecting GPU: {e}", exc_info=True)
            logger.info("Using CPU (slower)")
        return device, compute_type

    def _instantiate_model(self, device: str, compute_type: str):
        """モデルロード（cuDNN DLL不在でクラッシュする場合のCPUフォールバック）"""
        logger.info(f"Loading faster-whisper model ({self.model_size}) on {device}...")
        try:
            self.model = WhisperModel(
                self.model_size, 
                device=device, 
                compute_type=compute_type
            )
            logger.info(f"✅ Model loaded successfully on {device.upper()}")
        except (RuntimeError, ValueError, FileNotFoundError) as gpu_err:
            if device == "cuda":
                logger.warning(f"⚠️ GPU load failed ({gpu_err}), falling back to CPU...")
                self.model = WhisperModel(
                    self.model_size,
                    device="cpu",
                    compute_type="int8"
                )
                logger.info("✅ Model loaded on CPU (fallback)")
            else:
                raise
        except (OSError, TypeError, KeyError, ImportError) as e:
            logger.error(f"Unexpected error loading model: {e}", exc_info=True)
            raise

    def _load_model(self):
        """Whisperモデルをロード（遅延初期化 + GPU自動検出 + cuDNNフォールバック）"""
        if self.model is None:
            self._add_cuda_dll_paths()
            device, compute_type = self._detect_gpu_device()
            self._instantiate_model(device, compute_type)
    
    def _get_video_duration(self, video_path: str) -> float:
        """動画の長さを取得（Phase D: ffprobe ベース）"""
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "json", video_path],
                capture_output=True, text=True, timeout=30
            )
            data = _json.loads(result.stdout)
            duration = float(data["format"]["duration"])
            logger.info(f"Video duration: {duration:.2f}s")
            return duration
        except (subprocess.SubprocessError, FileNotFoundError, _json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to get duration via ffprobe ({type(e).__name__}): {e}")
            return 1800.0  # フォールバック: 30分
        except (OSError, TypeError) as e:
            logger.error(f"Unexpected error getting duration via ffprobe: {e}", exc_info=True)
            return 1800.0  # フォールバック: 30分

    def _write_segments_to_checkpoint(
        self,
        segments_iter,
        total_duration: float,
        checkpoint_path: str,
        progress_callback: Optional[Callable]
    ) -> int:
        """セグメントをディスクに逐次書き出し（メモリ蓄積を回避）"""
        segment_count = 0
        self.last_progress_update = time.time()
        
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            for segment in segments_iter:
                # 進捗計算
                progress = int((segment.end / total_duration) * 100)
                progress = min(progress, 99)
                
                # 進捗更新（0.5秒間隔）
                if time.time() - self.last_progress_update > 0.5:
                    if progress_callback:
                        progress_callback("processing", f"Transcribing... {progress}%", progress)
                    self.last_progress_update = time.time()
                    logger.info(f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text} ({progress}%)")
                
                # セグメントをファイルに逐次書き出し（JSONLines形式）
                seg_dict = {
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text.strip(),
                    "sourceStart": segment.start,
                    "sourceEnd": segment.end
                }
                f.write(_json.dumps(seg_dict, ensure_ascii=False) + "\n")
                segment_count += 1
        return segment_count
    
    async def transcribe(
        self,
        video_path: str,
        language: str = "ja",
        beam_size: int = 1,
        progress_callback: Optional[Callable] = None,
        enable_diarization: bool = False,
        num_speakers: Optional[int] = None,
    ) -> List[Dict]:
        """
        動画ファイルを文字起こし（タイムスタンプ付き）
        
        Args:
            video_path: 動画ファイルパス
            language: 言語コード（ja, en等）
            beam_size: ビームサーチサイズ（1=高速、5=高精度）
            progress_callback: 進捗コールバック(status, message, progress)
            enable_diarization: True で話者分離を実行（U-05）
            num_speakers: 想定話者数（None=自動検出）
        
        Returns:
            字幕セグメントのリスト
        """
        logger.info(f"Whisper transcription started: {video_path}")
        
        try:
            # モデルロード
            if progress_callback:
                progress_callback("processing", f"Loading Model ({self.model_size})...", 0)
            
            self._load_model()
            
            # 動画の長さを取得
            total_duration = self._get_video_duration(video_path)
            
            # チェックポイントファイル: セグメントを逐次書き出し（OOM防止）
            checkpoint_path = str(Path(video_path).parent / "_whisper_segments.jsonl")
            
            # 文字起こし開始
            if progress_callback:
                progress_callback("processing", "Transcribing...", 0)
            
            logger.info(f"Transcribing {video_path}...")
            segments_iter, info = self.model.transcribe(
                video_path,
                beam_size=beam_size,
                language=language
            )
            
            segment_count = self._write_segments_to_checkpoint(
                segments_iter=segments_iter,
                total_duration=total_duration,
                checkpoint_path=checkpoint_path,
                progress_callback=progress_callback
            )
            
            logger.info(f"Transcription completed: {segment_count} segments (saved to disk)")
            
            # ⚠️ self.model は解放しない（CTranslate2デストラクタ→CUDAクラッシュ回避）
            # セグメントはディスクに保存済み — ファイルパスを返して呼び出し側で読み込み
            logger.info(f"✅ セグメントはディスクに保存済み — チェックポイントパスを返却: {checkpoint_path}")
            
            if progress_callback:
                progress_callback("processing", "Transcription complete", 99)
            
            # チェックポイントファイルパスを返す（セグメントリストではない）
            return checkpoint_path
            
        except FileNotFoundError as e:
            logger.error(f"Video file not found: {e}")
            if progress_callback:
                progress_callback("failed", f"File not found: {e}", 0)
            return [{
                "start": 0.0,
                "end": 1.0,
                "text": f"音声認識に失敗しました（ファイル未検出）: {str(e)[:100]}"
            }]
        except (RuntimeError, ValueError, OSError, TypeError, KeyError, AttributeError, ImportError, IndexError) as e:
            logger.error(f"Whisper transcription error ({type(e).__name__}): {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            
            # エラー時はフォールバック
            if progress_callback:
                progress_callback("failed", str(e), 0)
            
            return [{
                "start": 0.0,
                "end": 1.0,
                "text": f"音声認識に失敗しました: {str(e)[:100]}"
            }]
    
    async def transcribe_with_proofreading(
        self,
        video_path: str,
        language: str = "ja",
        beam_size: int = 1,
        progress_callback: Optional[Callable] = None
    ) -> List[Dict]:
        """
        文字起こし + Gemini校閲の統合パイプライン
        
        Args:
            video_path: 動画ファイルパス
            language: 言語コード
            beam_size: ビームサーチサイズ
            progress_callback: 進捗コールバック
        
        Returns:
            校閲済み字幕セグメント
        """
        # 1. Whisper文字起こし
        result = await self.transcribe(
            video_path=video_path,
            language=language,
            beam_size=beam_size,
            progress_callback=progress_callback
        )
        
        # 文字起こし結果（ファイルパス文字列）をリストに復元
        segments = []
        if isinstance(result, str):
            checkpoint_path = Path(result)
            if checkpoint_path.exists():
                try:
                    with open(checkpoint_path, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.strip():
                                segments.append(_json.loads(line.strip()))
                except (OSError, _json.JSONDecodeError, TypeError, ValueError) as e:
                    logger.error(f"Failed to read whisper checkpoint file: {e}", exc_info=True)
            else:
                logger.error(f"Whisper checkpoint file not found: {checkpoint_path}")
        elif isinstance(result, list):
            segments = result
        else:
            logger.error(f"Unexpected transcribe result type: {type(result)}")
        
        # 2. Gemini校閲
        if progress_callback:
            progress_callback("processing", "AI校閲を実行中 (Gemini 3.0)...", 99)
        
        logger.info("Starting AI Proofreading...")
        
        from .ai_proofreader import proofread_segments
        segments = proofread_segments(
            segments, 
            update_callback=progress_callback
        )
        
        if progress_callback:
            progress_callback("completed", "Success", 100)
        
        return segments
