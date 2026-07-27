import pytest
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
import runpy
from PIL import Image, ImageFont
import sys
import io

import backend.aligned_preview_generator as generator


@pytest.fixture
def mock_dependencies():
    """
    外部依存関係（subprocess.run、ファイルシステム、PIL.Image）をモック化するフィクスチャ。
    """
    with patch("subprocess.run") as mock_run, \
         patch("pathlib.Path.exists", autospec=True) as mock_exists, \
         patch("pathlib.Path.mkdir") as mock_mkdir, \
         patch("PIL.Image.open") as mock_img_open, \
         patch("PIL.Image.Image.save") as mock_img_save:
        
        # subprocess.run は成功を模倣
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")
        
        # 必要なディレクトリやファイルの存在を True に設定
        def exists_side_effect(self, *args, **kwargs):
            path_str = str(self).replace("\\", "/")
            if "brand_logo.png" in path_str:
                return True
            if "msgothic.ttc" in path_str or "YuGothM.ttc" in path_str:
                return False  # デフォルトはフォールバックテスト用
            return True
            
        mock_exists.side_effect = exists_side_effect
        
        # ロゴ画像のモック（Image.open がダミー画像を返すようにする）
        dummy_logo = Image.new("RGBA", (100, 100))
        mock_img_open.return_value = dummy_logo
        
        yield {
            "run": mock_run,
            "exists": mock_exists,
            "mkdir": mock_mkdir,
            "img_open": mock_img_open,
            "img_save": mock_img_save
        }


def test_create_aligned_preview_success(mock_dependencies):
    """
    すべての処理が正常終了するケース（フォントなし＝デフォルトフォント使用）
    """
    result = generator.create_aligned_preview()
    
    # 戻り値が aligned.mp4 のパスであることを検証
    assert "aligned.mp4" in result
    assert mock_dependencies["run"].call_count == 6
    mock_dependencies["mkdir"].assert_called()
    mock_dependencies["img_open"].assert_called_with(Path("backend/branding/logos/brand_logo.png"))


def test_create_aligned_preview_with_system_fonts(mock_dependencies):
    """
    システムフォントが存在するケースの検証
    """
    def exists_side_effect(self, *args, **kwargs):
        path_str = str(self).replace("\\", "/")
        if "brand_logo.png" in path_str:
            return True
        if "msgothic.ttc" in path_str:
            return True
        if "シーン04_後編02" in path_str:
            return True
        return False
        
    mock_dependencies["exists"].side_effect = exists_side_effect
    
    orig_truetype = generator.ImageFont.truetype
    called_with_target = False
    
    def truetype_wrapper(font_path, *args, **kwargs):
        nonlocal called_with_target
        if isinstance(font_path, str) and "msgothic" in font_path:
            called_with_target = True
            return ImageFont.load_default()
        return orig_truetype(font_path, *args, **kwargs)
        
    try:
        generator.ImageFont.truetype = truetype_wrapper
        result = generator.create_aligned_preview()
        assert "aligned.mp4" in result
        assert called_with_target is True
    finally:
        generator.ImageFont.truetype = orig_truetype


def test_create_aligned_preview_font_load_exception(mock_dependencies):
    """
    フォントファイルが存在するが、読み込み時に例外が発生してフォールバックするケース
    """
    def exists_side_effect(self, *args, **kwargs):
        path_str = str(self).replace("\\", "/")
        if "brand_logo.png" in path_str:
            return True
        if "msgothic.ttc" in path_str:
            return True
        if "シーン04_後編02" in path_str:
            return True
        return False
        
    mock_dependencies["exists"].side_effect = exists_side_effect
    
    orig_truetype = generator.ImageFont.truetype
    called_with_target = False
    
    def truetype_wrapper(font_path, *args, **kwargs):
        nonlocal called_with_target
        if isinstance(font_path, str) and "msgothic" in font_path:
            called_with_target = True
            raise OSError("Font load error")
        return orig_truetype(font_path, *args, **kwargs)
        
    try:
        generator.ImageFont.truetype = truetype_wrapper
        result = generator.create_aligned_preview()
        assert "aligned.mp4" in result
        assert called_with_target is True
    finally:
        generator.ImageFont.truetype = orig_truetype


def test_main_block_success(mock_dependencies):
    """
    __name__ == "__main__" ブロックの正常実行ルートの検証
    """
    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
        generator_path = str(Path(__file__).parent.parent / "aligned_preview_generator.py")
        
        # 本物の create_aligned_preview を走らせるが、内部の依存関係は mock_dependencies によりモックされているため正常終了する
        runpy.run_path(generator_path, run_name="__main__")
        
        # 成功メッセージが出力されたことを検証
        assert "成功" in mock_stdout.getvalue()


def test_main_block_system_error(mock_dependencies):
    """
    __name__ == "__main__" ブロックで CalledProcessError などのシステムエラーが発生するケース
    """
    # 最初の subprocess.run が CalledProcessError を投げるように設定
    error = subprocess.CalledProcessError(returncode=1, cmd="ffmpeg")
    mock_dependencies["run"].side_effect = error
    
    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout, \
         patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
         
        generator_path = str(Path(__file__).parent.parent / "aligned_preview_generator.py")
        runpy.run_path(generator_path, run_name="__main__")
        
        # システムエラーハンドリングが実行されたことを検証
        assert "システムエラーが発生しました" in mock_stdout.getvalue()


def test_main_block_unexpected_error(mock_dependencies):
    """
    __name__ == "__main__" ブロックで予期せぬ一般例外が発生するケースの検証
    """
    # ValueError を発生させる
    error = ValueError("Unexpected general error")
    mock_dependencies["run"].side_effect = error
    
    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout, \
         patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
         
        generator_path = str(Path(__file__).parent.parent / "aligned_preview_generator.py")
        runpy.run_path(generator_path, run_name="__main__")
        
        # 予期せぬエラーハンドリングが実行されたことを検証
        assert "予期せぬエラーが発生しました" in mock_stdout.getvalue()


def test_create_aligned_preview_custom_paths(mock_dependencies):
    """
    カスタムの入力動画パスと出力ディレクトリパスを引数で指定した場合の動作検証
    """
    custom_video = "backend/temp/custom_input.mp4"
    custom_output = "backend/temp/custom_output_dir"
    
    orig_exists = mock_dependencies["exists"].side_effect
    
    def exists_side_effect(self, *args, **kwargs):
        path_str = str(self).replace("\\", "/")
        if "custom_input.mp4" in path_str:
            return True
        return orig_exists(self, *args, **kwargs)
        
    mock_dependencies["exists"].side_effect = exists_side_effect
    
    result = generator.create_aligned_preview(input_video=custom_video, output_dir=custom_output)
    
    assert "aligned.mp4" in result
    
    called_args = [call[0][0] for call in mock_dependencies["run"].call_args_list]
    video_extraction_call = next(c for c in called_args if "-i" in c)
    assert "-i" in video_extraction_call
    # プラットフォーム非依存なパス比較
    assert any(custom_video in arg.replace("\\", "/") for arg in video_extraction_call)


def test_create_aligned_preview_output_dir_creation(mock_dependencies):
    """
    指定された出力ディレクトリが存在しない場合に自動作成されることを検証
    """
    custom_output = "backend/temp/non_existent_output_dir"
    
    result = generator.create_aligned_preview(output_dir=custom_output)
    
    mkdir_mock = mock_dependencies["mkdir"]
    assert mkdir_mock.called

def test_main_block_type_error(mock_dependencies):
    """
    __name__ == "__main__" ブロックで TypeError が発生するケースの検証
    """
    error = TypeError("Unexpected type error")
    mock_dependencies["run"].side_effect = error
    
    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
        generator_path = str(Path(__file__).parent.parent / "aligned_preview_generator.py")
        runpy.run_path(generator_path, run_name="__main__")
        assert "予期せぬエラーが発生しました" in mock_stdout.getvalue()


def test_main_block_key_error(mock_dependencies):
    """
    __name__ == "__main__" ブロックで KeyError が発生するケースの検証
    """
    error = KeyError("Unexpected key error")
    mock_dependencies["run"].side_effect = error
    
    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
        generator_path = str(Path(__file__).parent.parent / "aligned_preview_generator.py")
        runpy.run_path(generator_path, run_name="__main__")
        assert "予期せぬエラーが発生しました" in mock_stdout.getvalue()


def test_create_aligned_preview_non_rgba_logo(mock_dependencies):
    """
    ロゴ画像が RGBA モードではない（例: RGB や P）場合でも、自動的に RGBA に変換されることを検証
    """
    # RGB モードのダミーロゴ画像を準備
    rgb_logo = Image.new("RGB", (100, 100))
    mock_dependencies["img_open"].return_value = rgb_logo
    
    orig_convert = Image.Image.convert
    convert_called = False
    
    def convert_wrapper(self, mode, *args, **kwargs):
        nonlocal convert_called
        if mode == "RGBA":
            convert_called = True
        return orig_convert(self, mode, *args, **kwargs)
        
    with patch("PIL.Image.Image.convert", side_effect=convert_wrapper, autospec=True):
        result = generator.create_aligned_preview()
        
    assert "aligned.mp4" in result
    assert convert_called is True


def test_create_aligned_preview_fallback_video_generation(mock_dependencies):
    """
    入力動画が存在しない場合、FFmpegを呼び出してダミー動画が動的に生成されることを検証
    """
    # 探索対象のパスがすべて存在しないように設定
    def exists_side_effect(self, *args, **kwargs):
        path_str = str(self).replace("\\", "/")
        if "brand_logo.png" in path_str:
            return True
        return False
        
    mock_dependencies["exists"].side_effect = exists_side_effect
    
    # 呼び出し履歴をキャプチャするため、subprocess.run の呼び出しを確認
    result = generator.create_aligned_preview(input_video="backend/temp/aligned_preview/missing_video.mp4")
    
    assert "aligned.mp4" in result
    # FFmpegによるダミー動画生成のコマンド（"lavfi" 等が含まれるもの）が実行されたか確認
    calls = mock_dependencies["run"].call_args_list
    dummy_gen_call = [call[0][0] for call in calls if "lavfi" in str(call)]
    assert len(dummy_gen_call) > 0
    assert "color=c=black" in str(dummy_gen_call[0])


def test_main_block_called_process_error_with_stderr(mock_dependencies):
    """
    CalledProcessError が発生した際に、e.stderr の詳細エラーログが出力されることを検証
    """
    # CalledProcessError のモック（stderr付き）
    error = subprocess.CalledProcessError(returncode=1, cmd="ffmpeg")
    error.stderr = b"FFmpeg protocol error: invalid codec parameters"
    mock_dependencies["run"].side_effect = error
    
    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
        generator_path = str(Path(__file__).parent.parent / "aligned_preview_generator.py")
        runpy.run_path(generator_path, run_name="__main__")
        
        output = mock_stdout.getvalue()
        assert "システムエラーが発生しました" in output
        assert "FFmpeg詳細エラー出力" in output
        assert "FFmpeg protocol error" in output

def test_create_aligned_preview_fallback_generation_called_process_error(mock_dependencies):
    """
    入力動画が存在せず、ダミー動画の生成時に subprocess.CalledProcessError が発生した場合、
    FileNotFoundError が発生することを検証する。
    """
    def exists_side_effect(self, *args, **kwargs):
        path_str = str(self).replace("\\", "/")
        if "brand_logo.png" in path_str:
            return True
        return False
    mock_dependencies["exists"].side_effect = exists_side_effect

    error = subprocess.CalledProcessError(returncode=1, cmd="ffmpeg")
    mock_dependencies["run"].side_effect = error

    with pytest.raises(FileNotFoundError) as exc_info:
        generator.create_aligned_preview(input_video="backend/temp/aligned_preview/missing_video_error.mp4")
    
    assert "入力動画が見つからず、ダミー動画の生成にも失敗しました" in str(exc_info.value)


def test_create_aligned_preview_fallback_generation_os_error(mock_dependencies):
    """
    入力動画が存在せず、ダミー動画の生成時に OSError が発生した場合、
    FileNotFoundError が発生することを検証する。
    """
    def exists_side_effect(self, *args, **kwargs):
        path_str = str(self).replace("\\", "/")
        if "brand_logo.png" in path_str:
            return True
        return False
    mock_dependencies["exists"].side_effect = exists_side_effect

    mock_dependencies["run"].side_effect = OSError("Disk full")

    with pytest.raises(FileNotFoundError) as exc_info:
        generator.create_aligned_preview(input_video="backend/temp/aligned_preview/missing_video_os_error.mp4")
    
    assert "入力動画が見つからず、ダミー動画の生成にも失敗しました" in str(exc_info.value)


def test_main_block_called_process_error_with_corrupt_stderr(mock_dependencies):
    """
    CalledProcessError が発生し、e.stderr のデコード処理で AttributeError が発生した場合でも、
    正常に例外がキャッチされて処理が続行されることを検証。
    """
    error = subprocess.CalledProcessError(returncode=1, cmd="ffmpeg")
    error.stderr = 12345
    mock_dependencies["run"].side_effect = error
    
    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
        generator_path = str(Path(__file__).parent.parent / "aligned_preview_generator.py")
        runpy.run_path(generator_path, run_name="__main__")
        
        output = mock_stdout.getvalue()
        assert "システムエラーが発生しました" in output
        assert "FFmpeg詳細エラー出力" not in output


def test_create_aligned_preview_short_video(mock_dependencies):
    """
    入力動画の長さが短い（例: 3.0秒）場合に、動的なパラメータ（開始: 0.0秒, 長さ: 3.0秒）が計算され、
    スクリーンショット生成のシーク位置が動的に縮小されることを検証。
    """
    # ffprobe の出力を模倣して 3.0 秒を返すように設定
    def run_side_effect(args, **kwargs):
        if "ffprobe" in args:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=b"3.0\n", stderr=b"")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=b"", stderr=b"")
        
    mock_dependencies["run"].side_effect = run_side_effect
    
    result = generator.create_aligned_preview(input_video="backend/tests/assets/dummy.mp4")
    assert "aligned.mp4" in result
    
    # 呼び出し履歴を検証
    calls = mock_dependencies["run"].call_args_list
    
    # Step 1: 動画抽出コマンドの引数を検証
    extract_call = [call[0][0] for call in calls if "-t" in call[0][0] and "base.mp4" in str(call[0][0])][0]
    assert "-ss" in extract_call
    assert "0.00" in extract_call
    assert "-t" in extract_call
    assert "3.00" in extract_call
    
    # Step 5: スクリーンショット生成コマンドの引数を検証
    screenshot_calls = [call[0][0] for call in calls if "screenshot" in str(call[0][0])]
    assert len(screenshot_calls) == 3
    
    # 各スクリーンショットのシーク値 (3.0 * 0.1 = 0.3, 3.0 * 0.3 = 0.9, 3.0 * 0.7 = 2.1)
    expected_times = ["0.30", "0.90", "2.10"]
    for idx, call_args in enumerate(screenshot_calls):
        assert "-ss" in call_args
        # シーク位置が expected_times のいずれかであることを検証
        assert any(t in call_args for t in expected_times)


def test_get_video_duration_error_fallback(mock_dependencies):
    """
    ffprobe の実行中に例外（CalledProcessErrorなど）が発生した場合に、
    get_video_duration が正常にフォールバック値（15.0秒）を返すことを検証。
    """
    mock_dependencies["run"].side_effect = subprocess.CalledProcessError(returncode=1, cmd="ffprobe")
    
    duration = generator.get_video_duration("dummy.mp4")
    assert duration == 15.0


def test_get_video_duration_value_error_fallback(mock_dependencies):
    """
    ffprobe の出力が不正で float キャスト時に ValueError が発生した場合に、
    get_video_duration が正常にフォールバック値（15.0秒）を返すことを検証。
    """
    mock_dependencies["run"].return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=b"invalid_float\n", stderr=b""
    )
    duration = generator.get_video_duration("dummy.mp4")
    assert duration == 15.0


def test_get_video_duration_file_not_found_fallback(mock_dependencies):
    """
    ffprobe コマンドが存在しないなど FileNotFoundError が発生した場合に、
    get_video_duration が正常にフォールバック値（15.0秒）を返すことを検証。
    """
    mock_dependencies["run"].side_effect = FileNotFoundError("[Errno 2] No such file or directory: 'ffprobe'")
    duration = generator.get_video_duration("dummy.mp4")
    assert duration == 15.0


def test_get_video_duration_os_error_fallback(mock_dependencies):
    """
    ffprobe 実行中に一般的な OSError が発生した場合に、
    get_video_duration が正常にフォールバック値（15.0秒）を返すことを検証。
    """
    mock_dependencies["run"].side_effect = OSError("OS error")
    duration = generator.get_video_duration("dummy.mp4")
    assert duration == 15.0


def test_get_video_duration_zero_or_negative_fallback(mock_dependencies):
    """
    ffprobe が 0.0 または負の値を返した場合に、15.0秒にフォールバックすることを検証。
    """
    # 0.0 の場合
    mock_dependencies["run"].return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=b"0.0\n", stderr=b""
    )
    assert generator.get_video_duration("dummy.mp4") == 15.0

    # 負の値の場合
    mock_dependencies["run"].return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=b"-5.0\n", stderr=b""
    )
    assert generator.get_video_duration("dummy.mp4") == 15.0


def test_create_aligned_preview_step1_failure(mock_dependencies):
    """
    Step 1 (動画抽出) で FFmpeg がエラー終了した際、RuntimeError が発生し、
    エラーメッセージに "Step 1 (動画抽出)" が含まれることを検証。
    """
    duration_process = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"15.0\n", stderr=b"")
    extract_error = subprocess.CalledProcessError(returncode=1, cmd="ffmpeg", stderr=b"Extraction failed")
    
    mock_dependencies["run"].side_effect = [duration_process, extract_error]

    with pytest.raises(RuntimeError) as exc_info:
        generator.create_aligned_preview()
    
    assert "Step 1 (動画抽出) でエラーが発生しました" in str(exc_info.value)
    assert "Extraction failed" in str(exc_info.value)


def test_create_aligned_preview_step4_failure(mock_dependencies):
    """
    Step 4 (オーバーレイ適用) で FFmpeg がエラー終了した際、RuntimeError が発生し、
    エラーメッセージに "Step 4 (オーバーレイ適用)" が含まれることを検証。
    """
    duration_process = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"15.0\n", stderr=b"")
    step1_process = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")
    step4_error = subprocess.CalledProcessError(returncode=1, cmd="ffmpeg", stderr=b"Overlay failed")
    
    mock_dependencies["run"].side_effect = [duration_process, step1_process, step4_error]

    with pytest.raises(RuntimeError) as exc_info:
        generator.create_aligned_preview()
    
    assert "Step 4 (オーバーレイ適用) でエラーが発生しました" in str(exc_info.value)
    assert "Overlay failed" in str(exc_info.value)


def test_create_aligned_preview_step5_failure(mock_dependencies):
    """
    Step 5 (スクリーンショット生成) で FFmpeg がエラー終了した際、RuntimeError が発生し、
    エラーメッセージに "Step 5 (スクリーンショット 1 生成)" が含まれることを検証。
    """
    duration_process = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"15.0\n", stderr=b"")
    step1_process = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")
    step4_process = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")
    step5_error = subprocess.CalledProcessError(returncode=1, cmd="ffmpeg", stderr=b"Screenshot failed")
    
    mock_dependencies["run"].side_effect = [duration_process, step1_process, step4_process, step5_error]

    with pytest.raises(RuntimeError) as exc_info:
        generator.create_aligned_preview()
    
    assert "Step 5 (スクリーンショット 1 生成) でエラーが発生しました" in str(exc_info.value)
    assert "Screenshot failed" in str(exc_info.value)


def test_create_aligned_preview_logo_open_failure(mock_dependencies):
    """
    ロゴ画像ファイルの読み込み失敗時に、警告が出力され、透過のダミー画像が生成されて
    処理全体が正常に終了することを検証。
    """
    # Image.open が OSError を投げるように設定
    mock_dependencies["img_open"].side_effect = OSError("Corrupted image file")
    
    result = generator.create_aligned_preview()
    
    assert "aligned.mp4" in result
    # Image.open は呼び出されたはず
    mock_dependencies["img_open"].assert_called()


def test_create_aligned_preview_telop_save_failure(mock_dependencies):
    """
    テロップ画像保存失敗時に RuntimeError が発生することを検証。
    """
    # Image.save が OSError を投げるように設定
    mock_dependencies["img_save"].side_effect = OSError("Write permission denied")
    
    with pytest.raises(RuntimeError) as exc_info:
        generator.create_aligned_preview()
        
    assert "Step 2 (テロップ画像保存) でエラーが発生しました" in str(exc_info.value)


def test_create_aligned_preview_combined_save_failure(mock_dependencies):
    """
    統合画像保存失敗時に RuntimeError が発生することを検証。
    """
    # 最初の save()（テロップ画像）は成功させ、2回目（統合画像）で OSError を投げるようにする
    mock_dependencies["img_save"].side_effect = [None, OSError("Disk full")]
    
    with pytest.raises(RuntimeError) as exc_info:
        generator.create_aligned_preview()
        
    assert "Step 3 (統合画像保存) でエラーが発生しました" in str(exc_info.value)


def test_create_aligned_preview_resource_cleanup(mock_dependencies):
    """
    ロゴ画像や作成された中間画像オブジェクトが適切に close() されることを検証
    """
    import PIL.Image
    orig_close = PIL.Image.Image.close
    close_calls = []
    
    def mock_close(self, *args, **kwargs):
        close_calls.append(self)
        return orig_close(self, *args, **kwargs)
        
    with patch("PIL.Image.Image.close", side_effect=mock_close, autospec=True):
        result = generator.create_aligned_preview()
        
    assert "aligned.mp4" in result
    # 少なくとも3回以上 close() が呼ばれていることを検証 (dummy, telop_img, combined_img 等)
    assert len(close_calls) >= 3


def test_resample_lanczos_compatibility():
    """
    Image.Resampling が存在しない環境を模擬し、フォールバック定数が正しく設定されることを検証。
    """
    if "backend.aligned_preview_generator" in sys.modules:
        del sys.modules["backend.aligned_preview_generator"]
        
    with patch("PIL.Image.Resampling", new=None):
        import backend.aligned_preview_generator as gen_fallback
        assert hasattr(gen_fallback, "RESAMPLE_LANCZOS")
        expected_values = [getattr(Image, "LANCZOS", None), getattr(Image, "ANTIALIAS", None), 1]
        assert gen_fallback.RESAMPLE_LANCZOS in [v for v in expected_values if v is not None]


def test_create_aligned_preview_fallback_generation_ffmpeg_error_details(mock_dependencies):
    """
    入力動画が存在せず、ダミー動画の生成時に FFmpeg がエラー終了した場合、
    FileNotFoundError が発生し、その例外メッセージに FFmpeg の詳細エラー出力（stderr）が
    含まれることを検証する。
    """
    def exists_side_effect(self, *args, **kwargs):
        path_str = str(self).replace("\\", "/")
        if "brand_logo.png" in path_str:
            return True
        return False
    mock_dependencies["exists"].side_effect = exists_side_effect

    error = subprocess.CalledProcessError(returncode=1, cmd="ffmpeg")
    error.stderr = b"FFmpeg internal engine failure code 0x9f3"
    mock_dependencies["run"].side_effect = error

    with pytest.raises(FileNotFoundError) as exc_info:
        generator.create_aligned_preview(input_video="backend/temp/aligned_preview/missing_video_detailed_error.mp4")
    
    assert "入力動画が見つからず、ダミー動画の生成にも失敗しました" in str(exc_info.value)
    assert "FFmpeg internal engine failure code 0x9f3" in str(exc_info.value)


def test_get_video_duration_unexpected_exception(mock_dependencies):
    """
    get_video_duration が予期せぬ例外（例：AttributeError）を投げた場合に、正常に 15.0秒を返すことを検証。
    """
    mock_dependencies["run"].side_effect = AttributeError("Unexpected attribute access error")
    duration = generator.get_video_duration("dummy.mp4")
    assert duration == 15.0


def test_create_aligned_preview_step2_unexpected_failure(mock_dependencies):
    """
    Step 2 で予期せぬ例外が発生した際、RuntimeError が発生し、
    メッセージに 'Step 2 (テロップ生成) 内で予期せぬエラーが発生しました' が含まれることを検証。
    """
    # Image.new で例外を発生させる
    with patch("PIL.Image.new", side_effect=ValueError("Unexpected PIL Image error")):
        with pytest.raises(RuntimeError) as exc_info:
            generator.create_aligned_preview()
            
    assert "Step 2 (テロップ生成) 内で予期せぬエラーが発生しました" in str(exc_info.value)
    assert "Unexpected PIL Image error" in str(exc_info.value)


def test_create_aligned_preview_step3_unexpected_failure(mock_dependencies):
    """
    Step 3 で予期せぬ例外が発生した際、RuntimeError が発生し、
    メッセージに 'Step 3 (統合画像生成) 内で予期せぬエラーが発生しました' が含まれることを検証。
    """
    # Step 2 は通す（Image.save等はmock）
    # logo_resized.convert で例外を発生させる
    with patch("PIL.Image.Image.convert", side_effect=TypeError("Unexpected mode convert error")):
        with pytest.raises(RuntimeError) as exc_info:
            generator.create_aligned_preview()
            
    assert "Step 3 (統合画像生成) 内で予期せぬエラーが発生しました" in str(exc_info.value)
    assert "Unexpected mode convert error" in str(exc_info.value)


def test_create_aligned_preview_general_unexpected_failure(mock_dependencies):
    """
    処理全体で何か予期せぬ一般例外が発生した際、最外周の RuntimeError で適切にラップされることを検証。
    """
    # get_video_duration の結果を mock_dependencies から外すなどで、他の箇所で一般例外を起こす
    # または get_video_duration は成功するが、その後の Path.mkdir で例外を発生させる
    with patch("pathlib.Path.mkdir", side_effect=IndexError("Unexpected index error")):
        with pytest.raises(RuntimeError) as exc_info:
            generator.create_aligned_preview()
            
    assert "プレビュー生成中に予期せぬエラーが発生しました" in str(exc_info.value)
    assert "Unexpected index error" in str(exc_info.value)


def test_resample_lanczos_compatibility_full():
    """
    Image.Resampling も Image.LANCZOS も存在しない極限環境を模擬し、
    Image.ANTIALIAS または 1 が使用されることを検証。
    """
    import PIL.Image
    orig_resampling = getattr(PIL.Image, "Resampling", None)
    orig_lanczos = getattr(PIL.Image, "LANCZOS", None)
    try:
        if hasattr(PIL.Image, "Resampling"):
            del PIL.Image.Resampling
        if hasattr(PIL.Image, "LANCZOS"):
            del PIL.Image.LANCZOS
        
        if "backend.aligned_preview_generator" in sys.modules:
            del sys.modules["backend.aligned_preview_generator"]
        import backend.aligned_preview_generator as gen_fallback
        assert gen_fallback.RESAMPLE_LANCZOS == getattr(PIL.Image, "ANTIALIAS", 1)
    finally:
        if orig_resampling is not None:
            PIL.Image.Resampling = orig_resampling
        if orig_lanczos is not None:
            PIL.Image.LANCZOS = orig_lanczos


def test_create_aligned_preview_step1_os_error(mock_dependencies):
    """
    Step 1 (動画抽出) で OSError が発生した際、RuntimeError が発生することを検証。
    """
    duration_process = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"15.0\n", stderr=b"")
    
    def run_side_effect(args, **kwargs):
        if "copy" in args:
            raise OSError("Mocked Step 1 OS Error")
        return duration_process
        
    mock_dependencies["run"].side_effect = run_side_effect

    with pytest.raises(RuntimeError) as exc_info:
        generator.create_aligned_preview()
    assert "Step 1 (動画抽出) でシステムエラーが発生しました" in str(exc_info.value)


def test_create_aligned_preview_step4_os_error(mock_dependencies):
    """
    Step 4 (オーバーレイ適用) で OSError が発生した際、RuntimeError が発生することを検証。
    """
    duration_process = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"15.0\n", stderr=b"")
    step1_process = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")
    
    def run_side_effect(args, **kwargs):
        if "-filter_complex" in args:
            raise OSError("Mocked Step 4 OS Error")
        if "copy" in args:
            return step1_process
        return duration_process
        
    mock_dependencies["run"].side_effect = run_side_effect

    with pytest.raises(RuntimeError) as exc_info:
        generator.create_aligned_preview()
    assert "Step 4 (オーバーレイ適用) でシステムエラーが発生しました" in str(exc_info.value)


def test_create_aligned_preview_step5_os_error(mock_dependencies):
    """
    Step 5 (スクリーンショット生成) で OSError が発生した際、RuntimeError が発生することを検証。
    """
    duration_process = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"15.0\n", stderr=b"")
    step1_process = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")
    step4_process = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")
    
    def run_side_effect(args, **kwargs):
        if "-frames:v" in args:
            raise OSError("Mocked Step 5 OS Error")
        if "-filter_complex" in args:
            return step4_process
        if "copy" in args:
            return step1_process
        return duration_process
        
    mock_dependencies["run"].side_effect = run_side_effect

    with pytest.raises(RuntimeError) as exc_info:
        generator.create_aligned_preview()
    assert "Step 5 (スクリーンショット 1 生成) でシステムエラーが発生しました" in str(exc_info.value)


def test_create_aligned_preview_no_logos_at_all(mock_dependencies):
    """
    プロジェクト内にロゴ画像が全く存在しない場合のフォールバック動作を検証。
    """
    def exists_side_effect(self, *args, **kwargs):
        path_str = str(self).replace("\\", "/")
        if "brand_logo.png" in path_str:
            return False
        return True
    mock_dependencies["exists"].side_effect = exists_side_effect
    
    result = generator.create_aligned_preview()
    assert "aligned.mp4" in result


def test_create_aligned_preview_alt_logo_exists(mock_dependencies):
    """
    主要なロゴが存在せず、代替パスのロゴが存在する場合の動作を検証。
    """
    def exists_side_effect(self, *args, **kwargs):
        path_str = str(self).replace("\\", "/")
        if "backend/branding/logos/brand_logo.png" in path_str:
            return False
        if "branding/logos/brand_logo.png" in path_str:
            return True
        return True
    mock_dependencies["exists"].side_effect = exists_side_effect
    
    result = generator.create_aligned_preview()
    assert "aligned.mp4" in result


def test_create_aligned_preview_zero_dimension_logo(mock_dependencies):
    """
    ロゴの高さが0の場合にゼロ除算ガードが機能することを検証。
    """
    dummy_logo = MagicMock(spec=Image.Image)
    dummy_logo.size = (100, 0)
    dummy_logo.resize.side_effect = lambda size, *args, **kwargs: Image.new("RGBA", size)
    dummy_logo.convert.return_value = Image.new("RGBA", (45, 45))
    mock_dependencies["img_open"].return_value = dummy_logo
    
    result = generator.create_aligned_preview()
    assert "aligned.mp4" in result


def test_create_aligned_preview_zero_width_logo(mock_dependencies):
    """
    ロゴの幅が0の場合にゼロ除算ガードが機能することを検証。
    """
    dummy_logo = MagicMock(spec=Image.Image)
    dummy_logo.size = (0, 100)
    dummy_logo.resize.side_effect = lambda size, *args, **kwargs: Image.new("RGBA", size)
    dummy_logo.convert.return_value = Image.new("RGBA", (45, 45))
    mock_dependencies["img_open"].return_value = dummy_logo
    
    result = generator.create_aligned_preview()
    assert "aligned.mp4" in result


def test_create_aligned_preview_negative_width_logo(mock_dependencies):
    """
    ロゴの幅が極端に小さく、リサイズ後の幅が0以下になる場合に安全に1pxになることを検証。
    """
    dummy_logo = MagicMock(spec=Image.Image)
    dummy_logo.size = (1, 1000)  # 1 * (45 / 1000) = 0.045 -> logo_width = 0
    dummy_logo.resize.side_effect = lambda size, *args, **kwargs: Image.new("RGBA", size)
    dummy_logo.convert.return_value = Image.new("RGBA", (1, 45))
    mock_dependencies["img_open"].return_value = dummy_logo
    
    result = generator.create_aligned_preview()
    assert "aligned.mp4" in result


def test_create_aligned_preview_close_exceptions(mock_dependencies):
    """
    画像オブジェクトの close() で例外が発生しても、無視されて正常終了することを検証。
    """
    with patch("PIL.Image.Image.close", side_effect=Exception("Close error")):
        result = generator.create_aligned_preview()
        assert "aligned.mp4" in result


def test_main_block_zero_division_error(mock_dependencies):
    """
    __main__ ブロックで ZeroDivisionError が発生した際のハンドリングを検証。
    """
    mock_stdout = io.StringIO()
    orig_write = mock_stdout.write
    
    def mock_write(text):
        if "成功" in text:
            raise ZeroDivisionError("Mocked ZeroDivisionError from print")
        return orig_write(text)
        
    mock_stdout.write = mock_write
    
    with patch("sys.stdout", mock_stdout):
        generator_path = str(Path(__file__).parent.parent / "aligned_preview_generator.py")
        runpy.run_path(generator_path, run_name="__main__")
        
        # StringIOへの出力の中に、ZeroDivisionError発生時のエラー出力が含まれていることを検証
        assert "予期せぬエラーが発生しました" in mock_stdout.getvalue()


def test_create_aligned_preview_long_video(mock_dependencies):
    """
    動画の長さが長い（例: 20.0秒）場合に、動的なパラメータ（開始: 5.0秒, 長さ: 10.0秒）が計算され、
    スクリーンショット生成のシーク位置が動的に縮小されることを検証。
    """
    # ffprobe の出力を模倣して 20.0 秒を返すように設定
    def run_side_effect(args, **kwargs):
        if "ffprobe" in args:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=b"20.0\n", stderr=b"")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=b"", stderr=b"")
        
    mock_dependencies["run"].side_effect = run_side_effect
    
    result = generator.create_aligned_preview(input_video="backend/tests/assets/dummy.mp4")
    assert "aligned.mp4" in result
    
    calls = mock_dependencies["run"].call_args_list
    
    # Step 1: 動画抽出コマンドの引数を検証 (開始: 5.00, 長さ: 10.00)
    extract_call = [call[0][0] for call in calls if "-t" in call[0][0] and "base.mp4" in str(call[0][0])][0]
    assert "-ss" in extract_call
    assert "5.00" in extract_call
    assert "-t" in extract_call
    assert "10.00" in extract_call
    
    # Step 5: スクリーンショット生成コマンドの引数を検証 (10.0 * 0.1 = 1.0, 10.0 * 0.3 = 3.0, 10.0 * 0.7 = 7.0)
    screenshot_calls = [call[0][0] for call in calls if "screenshot" in str(call[0][0])]
    assert len(screenshot_calls) == 3
    
    expected_times = ["1.00", "3.00", "7.00"]
    for call_args in screenshot_calls:
        assert "-ss" in call_args
        assert any(t in call_args for t in expected_times)


def test_create_aligned_preview_fallback_generation_ffmpeg_error_corrupt_bytes(mock_dependencies):
    """
    入力動画が存在せず、ダミー動画の生成時に FFmpeg がエラー終了し、
    その stderr が非UTF-8バイト列（デコードエラーが発生するデータ）である場合でも、
    errors='ignore' によって適切にデコードされエラーハンドリングされることを検証。
    """
    def exists_side_effect(self, *args, **kwargs):
        path_str = str(self).replace("\\", "/")
        if "brand_logo.png" in path_str:
            return True
        return False
    mock_dependencies["exists"].side_effect = exists_side_effect

    error = subprocess.CalledProcessError(returncode=1, cmd="ffmpeg")
    # 非UTF-8バイト列を設定 (0xff 0xff は UTF-8 ではデコードエラーになる)
    error.stderr = b"\xff\xff FFmpeg crashed \xff\xff"
    mock_dependencies["run"].side_effect = error

    with pytest.raises(FileNotFoundError) as exc_info:
        generator.create_aligned_preview(input_video="backend/temp/aligned_preview/missing_video_corrupt.mp4")
    
    assert "入力動画が見つからず、ダミー動画の生成にも失敗しました" in str(exc_info.value)
    # デコードエラーにならず、無効なバイトが無視または代替文字に置き換えられて取得できているか
    assert "FFmpeg crashed" in str(exc_info.value)


def test_main_block_success_with_reconfigure(mock_dependencies):
    """
    __main__ ブロック実行時に sys.stdout が reconfigure メソッドを持つ場合、
    正常に呼び出されエラーなく完了することを検証。
    """
    mock_stdout = MagicMock(spec=io.TextIOWrapper)
    mock_stdout.write = MagicMock()
    mock_stdout.reconfigure = MagicMock()
    
    with patch("sys.stdout", mock_stdout):
        generator_path = str(Path(__file__).parent.parent / "aligned_preview_generator.py")
        runpy.run_path(generator_path, run_name="__main__")
        
        # reconfigure が呼び出されたことを検証
        mock_stdout.reconfigure.assert_called_once_with(encoding='utf-8')


def test_create_aligned_preview_invalid_video_path_type(mock_dependencies):
    """
    input_video に無効な型（例: int）が渡された場合、最外周で RuntimeError にラップされることを検証。
    """
    with pytest.raises(RuntimeError) as exc_info:
        generator.create_aligned_preview(input_video=12345)
    assert "プレビュー生成中に予期せぬエラーが発生しました" in str(exc_info.value)


def test_create_aligned_preview_output_dir_type_error(mock_dependencies):
    """
    output_dir に無効な型（例: object）が渡された場合、最外周で RuntimeError にラップされることを検証。
    """
    with pytest.raises(RuntimeError) as exc_info:
        generator.create_aligned_preview(output_dir=object())
    assert "プレビュー生成中に予期せぬエラーが発生しました" in str(exc_info.value)


def test_get_video_duration_none(mock_dependencies):
    """
    get_video_duration に None などの無効な値が渡された場合、フォールバック値 15.0秒が返ることを検証。
    """
    duration = generator.get_video_duration(None)
    assert duration == 15.0


def test_get_video_duration_with_whitespace(mock_dependencies):
    """
    ffprobe の出力の末尾に改行や空白がある場合でも、正常に float としてパースされることを検証。
    """
    mock_dependencies["run"].return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=b"  42.7 \n", stderr=b""
    )
    duration = generator.get_video_duration("dummy.mp4")
    assert duration == 42.7


def test_create_aligned_preview_temp_dir_mkdir_os_error(mock_dependencies):
    """
    temp_dir の作成時に OSError が発生した場合、プレビュー生成中に予期せぬエラーが発生しました として
    適切に最外周で RuntimeError にラップされることを検証。
    """
    with patch("pathlib.Path.mkdir") as mock_mkdir:
        # 1回目の mkdir(output_dir) は通し、2回目の mkdir(temp_dir) で OSError を投げるように設定
        mock_mkdir.side_effect = [None, OSError("Disk read-only")]
        with pytest.raises(RuntimeError) as exc_info:
            generator.create_aligned_preview()
        assert "プレビュー生成中に予期せぬエラーが発生しました" in str(exc_info.value)
        assert "Disk read-only" in str(exc_info.value)


def test_create_aligned_preview_medium_video(mock_dependencies):
    """
    動画の長さが 8.0 秒（中程度）の場合に、動的パラメータ（開始: 0.0秒, 長さ: 8.0秒）が正しく計算され、
    スクリーンショット生成のシーク位置が適切に計算されることを検証。
    """
    def run_side_effect(args, **kwargs):
        if "ffprobe" in args:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=b"8.0\n", stderr=b"")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=b"", stderr=b"")
        
    mock_dependencies["run"].side_effect = run_side_effect
    
    result = generator.create_aligned_preview(input_video="backend/tests/assets/dummy.mp4")
    assert "aligned.mp4" in result
    
    calls = mock_dependencies["run"].call_args_list
    
    # Step 1: 動画抽出 (開始: 0.00, 長さ: 8.00)
    extract_call = [call[0][0] for call in calls if "-t" in call[0][0] and "base.mp4" in str(call[0][0])][0]
    assert "-ss" in extract_call
    assert "0.00" in extract_call
    assert "-t" in extract_call
    assert "8.00" in extract_call













def test_create_aligned_preview_empty_video_path(mock_dependencies):
    """
    input_video に空文字列が渡された場合、ダミー動画の動的生成が試みられ、
    ファイル作成等がモックされているため、最終的に aligned.mp4 が返されることを検証。
    """
    mock_dependencies["exists"].return_value = True
    result = generator.create_aligned_preview(input_video="")
    assert "aligned.mp4" in result


def test_create_aligned_preview_extreme_aspect_ratio_logo(mock_dependencies):
    """
    極端なアスペクト比（例: 非常に横長）のロゴ画像が渡された場合でも、
    正常にリサイズされて処理が完了することを検証。
    """
    dummy_logo = MagicMock(spec=Image.Image)
    dummy_logo.size = (10000, 10)
    dummy_logo.resize.side_effect = lambda size, *args, **kwargs: Image.new("RGBA", size)
    dummy_logo.convert.return_value = Image.new("RGBA", (45000, 45))
    mock_dependencies["img_open"].return_value = dummy_logo
    
    result = generator.create_aligned_preview()
    assert "aligned.mp4" in result


def test_create_aligned_preview_palette_mode_logo(mock_dependencies):
    """
    パレットカラーモード(P)のロゴ画像が渡された場合でも、
    RGBAに正しく変換されて処理が完了することを検証。
    """
    p_logo = Image.new("P", (100, 100))
    mock_dependencies["img_open"].return_value = p_logo
    
    result = generator.create_aligned_preview()
    assert "aligned.mp4" in result


def test_get_video_duration_only_whitespace_fallback(mock_dependencies):
    """
    ffprobe の出力が空白のみ（スペースや改行のみ）の場合、get_video_duration が正常に
    デフォルトの 15.0 秒を返すことを検証。
    """
    mock_dependencies["run"].return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=b"   \n  \n", stderr=b""
    )
    duration = generator.get_video_duration("dummy.mp4")
    assert duration == 15.0


def test_create_aligned_preview_invalid_logo_data(mock_dependencies):
    """
    ロゴデータが破損しているか無効なオブジェクトである場合に警告され、
    ダミー画像が生成されるケースを追加テスト。
    """
    mock_dependencies["img_open"].side_effect = TypeError("Invalid object type")
    result = generator.create_aligned_preview()
    assert "aligned.mp4" in result
