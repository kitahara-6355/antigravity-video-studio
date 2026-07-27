import subprocess
import shutil
import logging
from pathlib import Path
import uuid

logger = logging.getLogger(__name__)


class AudioMaster:
    """
    音響マスタリングエンジン
    - ラウドネス正規化
    - ノイズ除去
    - BGM ダッキング
    """
    def __init__(self):
        # FFmpeg の自動検出（IMP-010: 不在時もインスタンス生成を許可）
        self.ffmpeg = shutil.which('ffmpeg')
        if not self.ffmpeg:
            local_ffmpeg = Path('./backend/bin/ffmpeg.exe')
            if local_ffmpeg.exists():
                self.ffmpeg = str(local_ffmpeg)
            else:
                logger.warning(
                    "⚠️ AudioMaster: FFmpeg not found. Audio mastering features disabled."
                )
                self.ffmpeg = None  # 各メソッドで None チェック
        
        # 出力ディレクトリ
        self.output_dir = Path("audio_mastered")
        self.output_dir.mkdir(exist_ok=True)
        
        if self.ffmpeg:
            logger.info(f"✅ AudioMaster initialized. FFmpeg: {self.ffmpeg}")

    def _ensure_ffmpeg(self) -> None:
        """FFmpeg が利用可能かチェックする。利用不可の場合は RuntimeError"""
        if not self.ffmpeg:
            raise RuntimeError("AudioMaster: FFmpeg not available")

    def _verify_file_exists(self, file_path: str) -> None:
        """指定されたファイルが存在するかチェックする。存在しない場合は FileNotFoundError"""
        if not Path(file_path).exists():
            ext = Path(file_path).suffix.lower()
            if ext in ('.mp4', '.webm', '.mkv', '.avi', '.mov', '.flv'):
                raise FileNotFoundError(f"動画ファイルが見つかりません: {file_path}")
            raise FileNotFoundError(f"Audio file not found: {file_path}")

    def _generate_output_path(self, suffix: str) -> Path:
        """UUID を付与したユニークな出力ファイルパスを生成する"""
        output_id = str(uuid.uuid4())
        return self.output_dir / f"{output_id}_{suffix}"

    def _run_ffmpeg(self, cmd: list, log_msg: str) -> None:
        """FFmpeg コマンドを実行し、共通のエラーハンドリングを行う"""
        try:
            logger.info(log_msg)
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            stderr_msg = e.stderr.decode("utf-8", errors="replace")
            logger.error(f"❌ FFmpeg error: {stderr_msg}")
            raise RuntimeError(f"FFmpeg operation failed: {stderr_msg}")

    def normalize_loudness(self, audio_path: str, target_lufs: float = None, template_config=None) -> str:
        """
        ラウドネス正規化（放送基準: -16 LUFS）
        
        Args:
            audio_path: 入力音声ファイル
            target_lufs: 目標ラウドネス（Noneの場合template_configから取得、もしくはデフォルト-16）
            template_config: テンプレート設定（LUFS値をテンプレート別に取得）
        
        Returns:
            正規化された音声ファイルのパス
        """
        self._ensure_ffmpeg()
        self._verify_file_exists(audio_path)

        # H-03: template_config からテンプレート別LUFS設定を取得
        if target_lufs is None:
            if template_config and hasattr(template_config, 'is_active') and template_config.is_active:
                audio_config = template_config.get_audio_config()
                if audio_config and isinstance(audio_config, dict):
                    target_lufs = audio_config.get('target_lufs', -16.0)
                else:
                    target_lufs = -16.0
            else:
                target_lufs = -16.0
        
        output = self._generate_output_path("normalized.mp3")
        
        # FFmpeg loudnorm フィルタ
        cmd = [
            self.ffmpeg,
            '-i', audio_path,
            '-af', f'loudnorm=I={target_lufs}:TP=-1.5:LRA=11',
            '-ar', '44100',  # サンプリングレート
            '-b:a', '192k',   # ビットレート
            str(output)
        ]
        
        self._run_ffmpeg(cmd, f"🎚️ Normalizing loudness to {target_lufs} LUFS...")
        logger.info(f"✅ Loudness normalized: {output}")
        return str(output)
    
    def remove_noise(self, audio_path: str, noise_reduction: float = 0.5) -> str:
        """
        ノイズ除去（FFmpeg afftdn フィルタ）
        
        Args:
            audio_path: 入力音声ファイル
            noise_reduction: ノイズ除去の強度（0.0-1.0）
        
        Returns:
            ノイズ除去された音声ファイルのパス
        """
        self._ensure_ffmpeg()
        self._verify_file_exists(audio_path)
        
        output = self._generate_output_path("denoised.mp3")
        
        # 0.0-1.0 の範囲に制限
        noise_reduction = max(0.0, min(1.0, noise_reduction))
        
        # FFmpeg afftdn フィルタ（ノイズ除去、nrは1-97の範囲にクリッピング）
        nr_value = max(1, min(97, int(noise_reduction * 100)))
        cmd = [
            self.ffmpeg,
            '-i', audio_path,
            '-af', f'afftdn=nr={nr_value}:nf=-25',
            '-ar', '44100',
            '-b:a', '192k',
            str(output)
        ]
        
        self._run_ffmpeg(cmd, f"🔇 Removing noise (strength: {noise_reduction})...")
        logger.info(f"✅ Noise removed: {output}")
        return str(output)
    
    def duck_bgm(self, voice_path: str, bgm_path: str, duck_amount: float = 0.3) -> str:
        """
        BGM ダッキング（音声がある時、BGMを自動で下げる）
        
        Args:
            voice_path: 音声ファイル
            bgm_path: BGM ファイル
            duck_amount: ダッキングの強度（0.0-1.0、低いほど強い）
        
        Returns:
            ミックスされた音声ファイルのパス
        """
        self._ensure_ffmpeg()
        self._verify_file_exists(voice_path)
        # 0.0-1.0 の範囲に制限 (FFmpeg sidechaincompress の threshold 範囲 0.00009-1.0 に適合させる)
        duck_amount = max(0.0001, min(1.0, duck_amount))
        
        output = self._generate_output_path("ducked.mp3")
        
        # サイドチェイン圧縮によるダッキング (ratio は 1.0-20.0 の範囲)
        ratio = int(max(1.0, min(20.0, 1.0 / duck_amount)))
        # [1:a] (BGM) を [0:a] (Voice) で圧縮する
        cmd = [
            self.ffmpeg,
            '-i', voice_path,
            '-i', bgm_path,
            '-filter_complex',
            f'[1:a][0:a]sidechaincompress=threshold={duck_amount}:ratio={ratio}:attack=20:release=250[bgm_ducked];'
            f'[0:a][bgm_ducked]amix=inputs=2:duration=first[final]',
            '-map', '[final]',
            '-ar', '44100',
            '-b:a', '192k',
            str(output)
        ]
        
        self._run_ffmpeg(cmd, f"🎵 Ducking BGM (amount: {duck_amount})...")
        logger.info(f"✅ BGM ducked: {output}")
        return str(output)
    
    def apply_filter(self, audio_path: str, filter_type: str = "highpass", cutoff: float = 100.0) -> str:
        """
        音響フィルタ（ハイパス/ローパス）を適用する
        
        Args:
            audio_path: 入力音声ファイル
            filter_type: フィルタの種類（'highpass' または 'lowpass'）
            cutoff: カットオフ周波数（Hz）
            
        Returns:
            フィルタ適用後の音声ファイルのパス
        """
        self._ensure_ffmpeg()
        self._verify_file_exists(audio_path)
        
        # フィルタタイプのバリデーション
        if filter_type not in ("highpass", "lowpass"):
            raise ValueError(f"Invalid filter_type: {filter_type}. Must be 'highpass' or 'lowpass'")
            
        # カットオフ周波数のバリデーション (正の値)
        if cutoff <= 0:
            raise ValueError("Cutoff frequency must be greater than 0")
            
        output = self._generate_output_path(f"{filter_type}.mp3")
        
        cmd = [
            self.ffmpeg,
            '-i', audio_path,
            '-af', f'{filter_type}=f={cutoff}',
            '-ar', '44100',
            '-b:a', '192k',
            str(output)
        ]
        
        self._run_ffmpeg(cmd, f"🔊 Applying {filter_type} filter (cutoff: {cutoff} Hz)...")
        logger.info(f"✅ Filter applied: {output}")
        return str(output)

    def master_audio(
        self, 
        audio_path: str, 
        normalize: bool = True, 
        denoise: bool = True,
        target_lufs: float = None,
        noise_reduction: float = 0.5,
        highpass_cutoff: float = None,
        lowpass_cutoff: float = None,
        template_config = None
    ) -> str:
        """
        音響マスタリング（パイプライン処理）
        
        Returns:
            最終的にマスタリングされた音声ファイルのパス
        """
        output = audio_path
        
        # 1. ハイパスフィルタ
        if highpass_cutoff is not None:
            output = self.apply_filter(output, "highpass", highpass_cutoff)
            
        # 2. ローパスフィルタ
        if lowpass_cutoff is not None:
            output = self.apply_filter(output, "lowpass", lowpass_cutoff)
        
        # 3. ノイズ除去
        if denoise:
            output = self.remove_noise(output, noise_reduction)
        
        # 4. ラウドネス正規化
        if normalize:
            output = self.normalize_loudness(output, target_lufs, template_config)
        
        return output

    def process(
        self,
        input_path: str,
        normalize: bool = True,
        denoise: bool = True,
        target_lufs: float = None,
        noise_reduction: float = 0.5,
        highpass_cutoff: float = None,
        lowpass_cutoff: float = None,
        template_config = None
    ) -> str:
        """
        音響マスタリングの統合処理エンドポイント。
        入力が動画ファイルの場合は、映像ストリームとマスタリング後音声を結合した動画ファイルを返す。
        入力が音声ファイルの場合は、マスタリングされた音声ファイルを返す。
        """
        self._ensure_ffmpeg()
        self._verify_file_exists(input_path)
        
        ext = Path(input_path).suffix.lower()
        is_video = ext in ('.mp4', '.webm', '.mkv', '.avi', '.mov', '.flv')
        
        # 1. 音声マスタリング（一時ファイル生成）
        mastered_audio = self.master_audio(
            audio_path=input_path,
            normalize=normalize,
            denoise=denoise,
            target_lufs=target_lufs,
            noise_reduction=noise_reduction,
            highpass_cutoff=highpass_cutoff,
            lowpass_cutoff=lowpass_cutoff,
            template_config=template_config
        )
        
        if not is_video:
            return mastered_audio
            
        # 2. 動画の場合は映像とマスタリング音声をマージ
        output_video = self._generate_output_path(f"mastered{ext}")
        
        cmd = [
            self.ffmpeg,
            '-y',
            '-i', input_path,
            '-i', mastered_audio,
            '-map', '0:v:0',
            '-map', '1:a:0',
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-map_metadata', '0',
            str(output_video)
        ]
        
        self._run_ffmpeg(cmd, f"🎬 Merging mastered audio with video stream ({output_video})...")
        logger.info(f"✅ Video audio mastered and merged: {output_video}")
        
        # 一時マスタリング音声の削除
        try:
            if Path(mastered_audio).exists() and mastered_audio != input_path:
                Path(mastered_audio).unlink()
        except OSError as e:
            logger.warning(f"Failed to remove temporary mastered audio: {e}")
            
        return str(output_video)


# グローバルインスタンス
audio_master = AudioMaster()

