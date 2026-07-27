import pytest
import subprocess
import tempfile
import pathlib
from pathlib import Path
from unittest.mock import patch, MagicMock

# 1. FFmpegがどこにも見つからない場合のテスト
def test_audio_master_init_ffmpeg_not_found():
    """AudioMaster.__init__ - FFmpegがシステムパスおよびローカルパスのいずれにも見つからない場合"""
    from audio_master import AudioMaster
    
    orig_exists = Path.exists
    def mock_exists(self):
        if "ffmpeg.exe" in str(self):
            return False
        return orig_exists(self)

    with patch("shutil.which", return_value=None), \
         patch("pathlib.Path.exists", mock_exists):
        master = AudioMaster()
        assert master.ffmpeg is None

# 2. ローカルのffmpeg.exeが見つかる場合のテスト
def test_audio_master_init_local_ffmpeg_found():
    """AudioMaster.__init__ - システムパスにはないがローカルのffmpeg.exeが見つかる場合"""
    from audio_master import AudioMaster
    
    orig_exists = Path.exists
    def mock_exists(self):
        if "ffmpeg.exe" in str(self):
            return True
        return orig_exists(self)

    with patch("shutil.which", return_value=None), \
         patch("pathlib.Path.exists", mock_exists):
        master = AudioMaster()
        assert master.ffmpeg == str(Path('./backend/bin/ffmpeg.exe'))

# 3. FFmpeg実行時にCalledProcessErrorが発生した際のエラーハンドリングのテスト
def test_audio_master_ffmpeg_error_handling():
    """AudioMaster._run_ffmpeg - subprocess.CalledProcessErrorが発生した際にRuntimeErrorになることを検証"""
    from audio_master import AudioMaster
    
    master = AudioMaster.__new__(AudioMaster)
    master.ffmpeg = "ffmpeg"
    master.output_dir = Path("dummy_dir")

    err = subprocess.CalledProcessError(
        returncode=1,
        cmd=["ffmpeg"],
        stderr=b"Test FFmpeg Error Output"
    )
    with patch("subprocess.run", side_effect=err):
        with pytest.raises(RuntimeError) as exc_info:
            master._run_ffmpeg(["ffmpeg"], "testing error")
        assert "FFmpeg operation failed: Test FFmpeg Error Output" in str(exc_info.value)

# 4. normalize_loudnessでデフォルト値が適用されるかのテスト
def test_audio_master_normalize_default_lufs():
    """AudioMaster.normalize_loudness - target_lufsおよびtemplate_configがNoneの際、デフォルト値-16.0 LUFSが適用されることを検証"""
    from audio_master import AudioMaster
    
    with tempfile.TemporaryDirectory() as tmpdir:
        master = AudioMaster.__new__(AudioMaster)
        master.ffmpeg = "ffmpeg"
        master.output_dir = Path(tmpdir)

        # ダミーの入力ファイルを作成
        with tempfile.NamedTemporaryFile(suffix=".mp3", dir=tmpdir, delete=False) as f:
            audio_path = f.name

        captured_cmd = {}
        def _mock_run(cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=_mock_run):
            master.normalize_loudness(audio_path, target_lufs=None, template_config=None)
            cmd_str = " ".join(captured_cmd.get("cmd", []))
            assert "loudnorm=I=-16.0" in cmd_str


# 5. _ensure_ffmpeg の RuntimeError 発生テスト
def test_audio_master_ensure_ffmpeg_missing():
    """AudioMaster._ensure_ffmpeg - ffmpegがNoneの際にRuntimeErrorが発生することを検証"""
    from audio_master import AudioMaster
    with patch("shutil.which", return_value=None), \
         patch("pathlib.Path.exists", return_value=False):
        master = AudioMaster()
        with pytest.raises(RuntimeError) as exc_info:
            master._ensure_ffmpeg()
        assert "AudioMaster: FFmpeg not available" in str(exc_info.value)

# 6. _verify_file_exists の FileNotFoundError 発生テスト
def test_audio_master_verify_file_not_found():
    """AudioMaster._verify_file_exists - ファイルが存在しない場合にFileNotFoundErrorが発生することを検証"""
    from audio_master import AudioMaster
    master = AudioMaster.__new__(AudioMaster)
    with pytest.raises(FileNotFoundError) as exc_info:
        master._verify_file_exists("non_existent_file.mp3")
    assert "Audio file not found: non_existent_file.mp3" in str(exc_info.value)

# 7. normalize_loudness で active な template_config を指定するテスト
def test_audio_master_normalize_with_active_template_config():
    """AudioMaster.normalize_loudness - template_configがactiveの際、そこからLUFS値が適用されることを検証"""
    from audio_master import AudioMaster
    with tempfile.TemporaryDirectory() as tmpdir:
        master = AudioMaster.__new__(AudioMaster)
        master.ffmpeg = "ffmpeg"
        master.output_dir = Path(tmpdir)

        with tempfile.NamedTemporaryFile(suffix=".mp3", dir=tmpdir, delete=False) as f:
            audio_path = f.name

        captured_cmd = {}
        def _mock_run(cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            return MagicMock(returncode=0)

        # template_config のモック作成
        mock_config = MagicMock()
        mock_config.is_active = True
        mock_config.get_audio_config.return_value = {"target_lufs": -14.0}

        with patch("subprocess.run", side_effect=_mock_run):
            master.normalize_loudness(audio_path, target_lufs=None, template_config=mock_config)
            cmd_str = " ".join(captured_cmd.get("cmd", []))
            assert "loudnorm=I=-14.0" in cmd_str

# 8. remove_noise の正常系および境界値テスト
@pytest.mark.parametrize("noise_reduction, expected_nr", [
    (0.0, 1),
    (0.5, 50),
    (1.0, 97),
])
def test_audio_master_remove_noise(noise_reduction, expected_nr):
    """AudioMaster.remove_noise - 異なる強度でノイズ除去を実行した際のパラメータ変換を検証"""
    from audio_master import AudioMaster
    with tempfile.TemporaryDirectory() as tmpdir:
        master = AudioMaster.__new__(AudioMaster)
        master.ffmpeg = "ffmpeg"
        master.output_dir = Path(tmpdir)

        with tempfile.NamedTemporaryFile(suffix=".mp3", dir=tmpdir, delete=False) as f:
            audio_path = f.name

        captured_cmd = {}
        def _mock_run(cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=_mock_run):
            master.remove_noise(audio_path, noise_reduction=noise_reduction)
            cmd_str = " ".join(captured_cmd.get("cmd", []))
            assert f"afftdn=nr={expected_nr}:nf=-25" in cmd_str

# 9. duck_bgm の正常系および境界値テスト
@pytest.mark.parametrize("duck_amount, expected_ratio", [
    (0.0, 20),      # クリッピングにより threshold=0.0001, ratio=20
    (0.0001, 20),   # クリッピングにより ratio=20
    (0.3, 3),       # ratio = int(1/0.3) = 3
    (1.0, 1),       # ratio = 1
])
def test_audio_master_duck_bgm(duck_amount, expected_ratio):
    """AudioMaster.duck_bgm - 異なるダッキング強度でBGMダッキングを実行した際のパラメータ変換を検証"""
    from audio_master import AudioMaster
    with tempfile.TemporaryDirectory() as tmpdir:
        master = AudioMaster.__new__(AudioMaster)
        master.ffmpeg = "ffmpeg"
        master.output_dir = Path(tmpdir)

        with tempfile.NamedTemporaryFile(suffix="_voice.mp3", dir=tmpdir, delete=False) as f_voice, \
             tempfile.NamedTemporaryFile(suffix="_bgm.mp3", dir=tmpdir, delete=False) as f_bgm:
            voice_path = f_voice.name
            bgm_path = f_bgm.name

        captured_cmd = {}
        def _mock_run(cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=_mock_run):
            master.duck_bgm(voice_path, bgm_path, duck_amount=duck_amount)
            cmd_str = " ".join(captured_cmd.get("cmd", []))
            clip_amount = max(0.0001, min(1.0, duck_amount))
            assert f"sidechaincompress=threshold={clip_amount}:ratio={expected_ratio}" in cmd_str

# 10. master_audio パイプラインの全パターン検証
@pytest.mark.parametrize("denoise, normalize", [
    (True, True),
    (False, True),
    (True, False),
    (False, False),
])
def test_audio_master_pipeline_execution(denoise, normalize):
    """AudioMaster.master_audio - 各種フラグの組み合わせによるマスタリングパイプライン呼び出しを検証"""
    from audio_master import AudioMaster
    master = AudioMaster.__new__(AudioMaster)
    master.ffmpeg = "ffmpeg"
    
    with patch.object(master, "remove_noise", return_value="denoised.mp3") as mock_remove_noise, \
         patch.object(master, "normalize_loudness", return_value="normalized.mp3") as mock_normalize:
        
        result = master.master_audio("input.mp3", denoise=denoise, normalize=normalize)
        
        if denoise and normalize:
            mock_remove_noise.assert_called_once_with("input.mp3", 0.5)
            mock_normalize.assert_called_once_with("denoised.mp3", None, None)
            assert result == "normalized.mp3"
        elif denoise and not normalize:
            mock_remove_noise.assert_called_once_with("input.mp3", 0.5)
            mock_normalize.assert_not_called()
            assert result == "denoised.mp3"
        elif not denoise and normalize:
            mock_remove_noise.assert_not_called()
            mock_normalize.assert_called_once_with("input.mp3", None, None)
            assert result == "normalized.mp3"
        else:
            mock_remove_noise.assert_not_called()
            mock_normalize.assert_not_called()
            assert result == "input.mp3"


# 11. template_config の get_audio_config() が None または辞書以外を返す場合のテスト
def test_audio_master_normalize_invalid_template_config():
    """AudioMaster.normalize_loudness - get_audio_config() が None または辞書以外を返す場合、デフォルト値 -16.0 LUFS が適用されることを検証"""
    from audio_master import AudioMaster
    with tempfile.TemporaryDirectory() as tmpdir:
        master = AudioMaster.__new__(AudioMaster)
        master.ffmpeg = "ffmpeg"
        master.output_dir = Path(tmpdir)

        with tempfile.NamedTemporaryFile(suffix=".mp3", dir=tmpdir, delete=False) as f:
            audio_path = f.name

        captured_cmd = {}
        def _mock_run(cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            return MagicMock(returncode=0)

        # ケースA: get_audio_config() が None
        mock_config_none = MagicMock()
        mock_config_none.is_active = True
        mock_config_none.get_audio_config.return_value = None

        with patch("subprocess.run", side_effect=_mock_run):
            master.normalize_loudness(audio_path, target_lufs=None, template_config=mock_config_none)
            cmd_str = " ".join(captured_cmd.get("cmd", []))
            assert "loudnorm=I=-16.0" in cmd_str

        # ケースB: get_audio_config() が 辞書型ではない (リスト等)
        mock_config_invalid = MagicMock()
        mock_config_invalid.is_active = True
        mock_config_invalid.get_audio_config.return_value = [-14.0]

        with patch("subprocess.run", side_effect=_mock_run):
            master.normalize_loudness(audio_path, target_lufs=None, template_config=mock_config_invalid)
            cmd_str = " ".join(captured_cmd.get("cmd", []))
            assert "loudnorm=I=-16.0" in cmd_str

# 12. remove_noise の引数範囲外クリッピングテスト
@pytest.mark.parametrize("noise_reduction, expected_nr", [
    (-0.5, 1),   # -0.5 -> 0.0 に補正 -> nr=1 (クリッピング)
    (1.5, 97),  # 1.5 -> 1.0 に補正 -> nr=97 (クリッピング)
])
def test_audio_master_remove_noise_out_of_bounds(noise_reduction, expected_nr):
    """AudioMaster.remove_noise - 範囲外の強度が渡された場合に適切に 0.0-1.0 にクリッピングされることを検証"""
    from audio_master import AudioMaster
    with tempfile.TemporaryDirectory() as tmpdir:
        master = AudioMaster.__new__(AudioMaster)
        master.ffmpeg = "ffmpeg"
        master.output_dir = Path(tmpdir)

        with tempfile.NamedTemporaryFile(suffix=".mp3", dir=tmpdir, delete=False) as f:
            audio_path = f.name

        captured_cmd = {}
        def _mock_run(cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=_mock_run):
            master.remove_noise(audio_path, noise_reduction=noise_reduction)
            cmd_str = " ".join(captured_cmd.get("cmd", []))
            assert f"afftdn=nr={expected_nr}:nf=-25" in cmd_str

# 13. duck_bgm の引数範囲外クリッピングテスト
@pytest.mark.parametrize("duck_amount, expected_ratio", [
    (-0.5, 20),  # -0.5 -> 0.0001 に補正 -> ratio=20
    (1.5, 1),     # 1.0 超過 -> 1.0 に補正 -> ratio=1
])
def test_audio_master_duck_bgm_out_of_bounds(duck_amount, expected_ratio):
    """AudioMaster.duck_bgm - 範囲外の強度が渡された場合に適切に 0.0-1.0 にクリッピングされることを検証"""
    from audio_master import AudioMaster
    with tempfile.TemporaryDirectory() as tmpdir:
        master = AudioMaster.__new__(AudioMaster)
        master.ffmpeg = "ffmpeg"
        master.output_dir = Path(tmpdir)

        with tempfile.NamedTemporaryFile(suffix="_voice.mp3", dir=tmpdir, delete=False) as f_voice, \
             tempfile.NamedTemporaryFile(suffix="_bgm.mp3", dir=tmpdir, delete=False) as f_bgm:
            voice_path = f_voice.name
            bgm_path = f_bgm.name

        captured_cmd = {}
        def _mock_run(cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=_mock_run):
            # duck_amount が範囲外の場合、正しくクリッピングされ FFmpeg コマンドに期待値が入る
            # -0.5 -> max(0.0001, min(1.0, -0.5)) = 0.0001
            # 1.5 -> max(0.0001, min(1.0, 1.5)) = 1.0
            clip_amount = max(0.0001, min(1.0, duck_amount))
            master.duck_bgm(voice_path, bgm_path, duck_amount=duck_amount)
            cmd_str = " ".join(captured_cmd.get("cmd", []))
            assert f"sidechaincompress=threshold={clip_amount}:ratio={expected_ratio}" in cmd_str


# 14. apply_filter の正常系テスト（highpass / lowpass）
@pytest.mark.parametrize("filter_type, cutoff", [
    ("highpass", 150.0),
    ("lowpass", 4000.0),
])
def test_audio_master_apply_filter_success(filter_type, cutoff):
    """AudioMaster.apply_filter - ハイパスおよびローパスフィルタ適用時のパラメータ変換とFFmpegコマンドの検証"""
    from audio_master import AudioMaster
    with tempfile.TemporaryDirectory() as tmpdir:
        master = AudioMaster.__new__(AudioMaster)
        master.ffmpeg = "ffmpeg"
        master.output_dir = Path(tmpdir)

        with tempfile.NamedTemporaryFile(suffix=".mp3", dir=tmpdir, delete=False) as f:
            audio_path = f.name

        captured_cmd = {}
        def _mock_run(cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=_mock_run):
            result = master.apply_filter(audio_path, filter_type=filter_type, cutoff=cutoff)
            cmd_str = " ".join(captured_cmd.get("cmd", []))
            assert f"{filter_type}=f={cutoff}" in cmd_str
            assert result.endswith(f"{filter_type}.mp3")

# 15. apply_filter の異常系テスト（ValueError）
def test_audio_master_apply_filter_invalid_params():
    """AudioMaster.apply_filter - 不正なパラメータが渡された際に ValueError が発生することを検証"""
    from audio_master import AudioMaster
    master = AudioMaster.__new__(AudioMaster)
    master.ffmpeg = "ffmpeg"
    
    # 存在確認をダミーでパスさせる
    with patch("pathlib.Path.exists", return_value=True):
        # 無効なフィルタタイプ
        with pytest.raises(ValueError) as exc_info:
            master.apply_filter("input.mp3", filter_type="invalid_filter", cutoff=100.0)
        assert "Invalid filter_type" in str(exc_info.value)

        # 無効なカットオフ周波数 (0以下)
        with pytest.raises(ValueError) as exc_info:
            master.apply_filter("input.mp3", filter_type="highpass", cutoff=0.0)
        assert "Cutoff frequency must be greater than 0" in str(exc_info.value)
        
        with pytest.raises(ValueError) as exc_info:
            master.apply_filter("input.mp3", filter_type="highpass", cutoff=-50.0)
        assert "Cutoff frequency must be greater than 0" in str(exc_info.value)

# 16. master_audio パイプラインでのフィルタ適用の検証
def test_audio_master_pipeline_with_filters():
    """AudioMaster.master_audio - ハイパスおよびローパスフィルタ指定時に、パイプラインで順次実行されることを検証"""
    from audio_master import AudioMaster
    master = AudioMaster.__new__(AudioMaster)
    master.ffmpeg = "ffmpeg"
    
    with patch.object(master, "apply_filter") as mock_apply_filter, \
         patch.object(master, "remove_noise", return_value="denoised.mp3") as mock_remove_noise, \
         patch.object(master, "normalize_loudness", return_value="normalized.mp3") as mock_normalize:
        
        # 連続した呼び出しに対する戻り値を設定
        mock_apply_filter.side_effect = ["highpass_out.mp3", "lowpass_out.mp3"]
        
        result = master.master_audio(
            "input.mp3", 
            normalize=True, 
            denoise=True,
            highpass_cutoff=120.0,
            lowpass_cutoff=3000.0
        )
        
        # 期待される順序での呼び出し検証
        mock_apply_filter.assert_any_call("input.mp3", "highpass", 120.0)
        mock_apply_filter.assert_any_call("highpass_out.mp3", "lowpass", 3000.0)
        mock_remove_noise.assert_called_once_with("lowpass_out.mp3", 0.5)
        mock_normalize.assert_called_once_with("denoised.mp3", None, None)
        assert result == "normalized.mp3"


# 17. _verify_file_exists で動画ファイルが見つからない場合の検証
def test_audio_master_verify_video_file_not_found():
    """AudioMaster._verify_file_exists - 動画ファイル形式が存在しない場合に '動画ファイルが見つかりません' エラーが発生することを検証"""
    from audio_master import AudioMaster
    master = AudioMaster.__new__(AudioMaster)
    with pytest.raises(FileNotFoundError) as exc_info:
        master._verify_file_exists("non_existent_video.mp4")
    assert "動画ファイルが見つかりません" in str(exc_info.value)
    
    with pytest.raises(FileNotFoundError) as exc_info:
        master._verify_file_exists("non_existent_audio.mp3")
    assert "Audio file not found" in str(exc_info.value)


# 18. process のテスト（音声ファイルが入力された場合と、動画ファイルが入力された場合）
def test_audio_master_process_audio_input():
    """AudioMaster.process - 入力が音声ファイルの場合はそのままマスタリングされた音声ファイルを返す"""
    from audio_master import AudioMaster
    master = AudioMaster.__new__(AudioMaster)
    master.ffmpeg = "ffmpeg"
    
    with patch.object(master, "_ensure_ffmpeg") as mock_ensure, \
         patch.object(master, "_verify_file_exists") as mock_verify, \
         patch.object(master, "master_audio", return_value="mastered_output.mp3") as mock_master:
         
        result = master.process("input_voice.mp3")
        
        mock_ensure.assert_called_once()
        mock_verify.assert_called_once_with("input_voice.mp3")
        mock_master.assert_called_once_with(
            audio_path="input_voice.mp3",
            normalize=True,
            denoise=True,
            target_lufs=None,
            noise_reduction=0.5,
            highpass_cutoff=None,
            lowpass_cutoff=None,
            template_config=None
        )
        assert result == "mastered_output.mp3"


def test_audio_master_process_video_input():
    """AudioMaster.process - 入力が動画ファイルの場合は映像とマスタリング音声ストリームを結合した動画ファイルを返す"""
    from audio_master import AudioMaster
    with tempfile.TemporaryDirectory() as tmpdir:
        master = AudioMaster.__new__(AudioMaster)
        master.ffmpeg = "ffmpeg"
        master.output_dir = Path(tmpdir)
        
        input_video = str(Path(tmpdir) / "input.mp4")
        
        captured_cmd = {}
        def _mock_run(cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            return MagicMock(returncode=0)
            
        with patch.object(master, "_ensure_ffmpeg"), \
             patch.object(master, "_verify_file_exists"), \
             patch.object(master, "master_audio", return_value="mastered_output.mp3") as mock_master, \
             patch("subprocess.run", side_effect=_mock_run), \
             patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.unlink") as mock_unlink:
             
            result = master.process(input_video)
            
            mock_master.assert_called_once()
            cmd_str = " ".join(captured_cmd.get("cmd", []))
            
            # FFmpegで映像がコピーされ、音声がAACでエンコードされてマージされるコマンドの検証
            assert "-c:v copy" in cmd_str
            assert "-c:a aac" in cmd_str
            assert result.endswith("mastered.mp4")
            
            # 一時音声ファイルが削除されることを検証
            mock_unlink.assert_called_once()


def test_audio_master_process_video_input_unlink_oserror():
    """AudioMaster.process - 一時ファイルの削除時に OSError が発生しても、例外が呼び出し元に伝播せずログ警告が出力されることを検証"""
    from audio_master import AudioMaster
    with tempfile.TemporaryDirectory() as tmpdir:
        master = AudioMaster.__new__(AudioMaster)
        master.ffmpeg = "ffmpeg"
        master.output_dir = Path(tmpdir)
        
        input_video = str(Path(tmpdir) / "input.mp4")
        
        def _mock_run(cmd, **kwargs):
            return MagicMock(returncode=0)
            
        with patch.object(master, "_ensure_ffmpeg"), \
             patch.object(master, "_verify_file_exists"), \
             patch.object(master, "master_audio", return_value="mastered_output.mp3") as mock_master, \
             patch("subprocess.run", side_effect=_mock_run), \
             patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.unlink", side_effect=OSError("Test Permission Error")) as mock_unlink, \
             patch("audio_master.logger.warning") as mock_logger_warning:
             
            result = master.process(input_video)
            
            mock_master.assert_called_once()
            mock_unlink.assert_called_once()
            assert result.endswith("mastered.mp4")
            
            # OSError時の警告ログが出力されているかを検証
            mock_logger_warning.assert_called_once()
            log_arg = mock_logger_warning.call_args[0][0]
            assert "Failed to remove temporary mastered audio" in log_arg
            assert "Test Permission Error" in log_arg



# =========================================================================
# バグ修正検証テスト (T-batch_f24614-bug_hunter-002)
# =========================================================================

# 19. remove_noise における nr パラメータの範囲クリッピングテスト
def test_audio_master_remove_noise_nr_clipping():
    """AudioMaster.remove_noise - noise_reductionが0.0または1.0の際にnr値が1-97の範囲にクリッピングされることを検証"""
    from audio_master import AudioMaster
    with tempfile.TemporaryDirectory() as tmpdir:
        master = AudioMaster.__new__(AudioMaster)
        master.ffmpeg = "ffmpeg"
        master.output_dir = Path(tmpdir)

        with tempfile.NamedTemporaryFile(suffix=".mp3", dir=tmpdir, delete=False) as f:
            audio_path = f.name

        captured_cmd = {}
        def _mock_run(cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            return MagicMock(returncode=0)

        # 0.0 -> nr=1
        with patch("subprocess.run", side_effect=_mock_run):
            master.remove_noise(audio_path, noise_reduction=0.0)
            cmd_str = " ".join(captured_cmd.get("cmd", []))
            assert "afftdn=nr=1:nf=-25" in cmd_str

        # 1.0 -> nr=97
        with patch("subprocess.run", side_effect=_mock_run):
            master.remove_noise(audio_path, noise_reduction=1.0)
            cmd_str = " ".join(captured_cmd.get("cmd", []))
            assert "afftdn=nr=97:nf=-25" in cmd_str


# 20. duck_bgm における ratio パラメータの範囲クリッピングテスト
def test_audio_master_duck_bgm_ratio_clipping():
    """AudioMaster.duck_bgm - duck_amountが極小または0.0の際にratioが20を超えないことを検証"""
    from audio_master import AudioMaster
    with tempfile.TemporaryDirectory() as tmpdir:
        master = AudioMaster.__new__(AudioMaster)
        master.ffmpeg = "ffmpeg"
        master.output_dir = Path(tmpdir)

        with tempfile.NamedTemporaryFile(suffix="_voice.mp3", dir=tmpdir, delete=False) as f_voice,              tempfile.NamedTemporaryFile(suffix="_bgm.mp3", dir=tmpdir, delete=False) as f_bgm:
            voice_path = f_voice.name
            bgm_path = f_bgm.name

        captured_cmd = {}
        def _mock_run(cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            return MagicMock(returncode=0)

        # 0.0 -> ratio=20
        with patch("subprocess.run", side_effect=_mock_run):
            master.duck_bgm(voice_path, bgm_path, duck_amount=0.0)
            cmd_str = " ".join(captured_cmd.get("cmd", []))
            assert "sidechaincompress=threshold=0.0001:ratio=20" in cmd_str

        # 0.005 -> ratio=20 (1/0.005 = 200 だが、最大値20にクリッピング)
        with patch("subprocess.run", side_effect=_mock_run):
            master.duck_bgm(voice_path, bgm_path, duck_amount=0.005)
            cmd_str = " ".join(captured_cmd.get("cmd", []))
            assert "sidechaincompress=threshold=0.005:ratio=20" in cmd_str


# 21. master_audio および process から normalize_loudness への template_config 伝播の検証
def test_audio_master_template_config_propagation():
    """AudioMaster.master_audio および process が template_config を受け取り normalize_loudness に正しく伝播していることを検証"""
    from audio_master import AudioMaster
    with tempfile.TemporaryDirectory() as tmpdir:
        master = AudioMaster.__new__(AudioMaster)
        master.ffmpeg = "ffmpeg"
        master.output_dir = Path(tmpdir)

        with tempfile.NamedTemporaryFile(suffix=".mp3", dir=tmpdir, delete=False) as f:
            audio_path = f.name

        captured_cmd = {}
        def _mock_run(cmd, **kwargs):
            captured_cmd["cmd"] = cmd
            return MagicMock(returncode=0)

        # template_config のモック
        mock_config = MagicMock()
        mock_config.is_active = True
        mock_config.get_audio_config.return_value = {"target_lufs": -12.0}

        # master_audio 経由での伝播テスト
        with patch("subprocess.run", side_effect=_mock_run):
            # target_lufs=None にして template_config を指定する
            master.master_audio(audio_path, normalize=True, denoise=False, target_lufs=None, template_config=mock_config)
            cmd_str = " ".join(captured_cmd.get("cmd", []))
            # template_config に設定した -12.0 LUFS が適用されていることを確認
            assert "loudnorm=I=-12.0" in cmd_str

        # process 経由での伝播テスト (音声入力)
        with patch.object(master, "_ensure_ffmpeg"),              patch.object(master, "_verify_file_exists"),              patch("subprocess.run", side_effect=_mock_run):
            master.process(audio_path, normalize=True, denoise=False, target_lufs=None, template_config=mock_config)
            cmd_str = " ".join(captured_cmd.get("cmd", []))
            # template_config に設定した -12.0 LUFS が適用されていることを確認
            assert "loudnorm=I=-12.0" in cmd_str
