"""
apply_full_premium_telop.py のカバレッジ 100% を達成するためのテスト
"""
import pytest
from unittest.mock import patch, MagicMock
import subprocess
from pathlib import Path
import runpy
import sys

# テスト対象
import backend.apply_full_premium_telop as target_module

BASE_PATH = Path(target_module.__file__).resolve().parent.parent

# 1. create_premium_branding のフォントフォールバックテスト

def _expected_output_path():
    """生成される premium_branding.png の期待パス。

    以前は project_root 起点で組んでいたが、テストが本番の
    backend/branding/premium_branding.png（Git 追跡下のブランド画像）を
    上書きしていた。生成物なので writable_path で解決する。
    """
    try:
        from backend.path_resolver import writable_path
    except ImportError:
        from path_resolver import writable_path
    return writable_path("backend/branding/premium_branding.png")


def test_create_premium_branding_font_fallback():
    """フォント読み込みのフォールバック処理を検証する"""
    font_mock_calls = []

    def mock_truetype(font_path, font_size):
        font_mock_calls.append(font_path)
        if "YuGothB.ttc" in font_path:
            raise OSError("Yu Gothic Bold not found")
        elif "meiryob.ttc" in font_path:
            raise OSError("Meiryo Bold not found")
        # msgothic.ttc は成功
        mock_font = MagicMock()
        return mock_font

    with patch("backend.apply_full_premium_telop.Image") as mock_image_cls, \
         patch("backend.apply_full_premium_telop.ImageDraw") as mock_imagedraw_cls, \
         patch("backend.apply_full_premium_telop.ImageFont.truetype", side_effect=mock_truetype):

        # PILのオブジェクト構築をシミュレート
        mock_logo = MagicMock()
        mock_image_cls.open.return_value = mock_logo
        mock_logo.convert.return_value = mock_logo

        mock_telop = MagicMock()
        mock_combined = MagicMock()
        mock_image_cls.new.side_effect = [mock_telop, mock_combined]

        mock_draw = MagicMock()
        mock_imagedraw_cls.Draw.return_value = mock_draw
        mock_draw.textbbox.return_value = (0, 0, 100, 20)

        # 実行
        result = target_module.create_premium_branding()

        # 検証
        assert len(font_mock_calls) == 3
        assert "YuGothB.ttc" in font_mock_calls[0]
        assert "meiryob.ttc" in font_mock_calls[1]
        assert "msgothic.ttc" in font_mock_calls[2]
        
        mock_logo.convert.assert_called_with('RGBA')
        mock_combined.paste.assert_any_call(mock_logo, (0, 0), mock_logo)
        mock_combined.paste.assert_any_call(mock_telop, (28, 0), mock_telop)
        mock_combined.save.assert_called_once()
        assert result == _expected_output_path()


# 2. apply_premium_telop_to_entire_video: 入力動画なし ＆ 再構築(concat)失敗
def test_apply_premium_telop_missing_input_concat_fail():
    """入力動画が存在せず、セグメントからの再構築(concat)も失敗するケース"""
    def mock_exists(path_obj):
        # input_video のみ存在しないが、concat_list は存在する
        if "soul_narrative_REBUILT.mp4" in str(path_obj):
            return False
        return True

    mock_run_result = MagicMock()
    mock_run_result.returncode = 1
    mock_run_result.stderr = "FFmpeg concat error"

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch("backend.apply_full_premium_telop.subprocess.run", return_value=mock_run_result) as mock_run:

        result = target_module.apply_premium_telop_to_entire_video()

        assert result is None
        # ffmpeg -f concat が呼び出されたことを確認
        called_args = mock_run.call_args[0][0]
        assert "concat" in " ".join(called_args)


# 2b. apply_premium_telop_to_entire_video: 入力動画なし ＆ concat_listも存在しない
def test_apply_premium_telop_missing_input_no_concat_list():
    """入力動画が存在せず、再構築用の concat.txt も存在しないケース (ガード処理)"""
    def mock_exists(path_obj):
        if "soul_narrative_REBUILT.mp4" in str(path_obj):
            return False
        if "concat.txt" in str(path_obj):
            return False
        return True

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists):
        result = target_module.apply_premium_telop_to_entire_video()
        assert result is None


# 3. apply_premium_telop_to_entire_video: 入力動画なし ＆ 再構築(concat)成功 ＆ overlay成功
def test_apply_premium_telop_missing_input_concat_success():
    """入力動画が存在せず、セグメントからの再構築(concat)が成功し、overlayも成功するケース"""
    existing_paths = set()
    existing_paths.add("brand_logo.png")
    existing_paths.add("soul_narrative_FINAL_PREMIUM.mp4")
    existing_paths.add("concat.txt")  # 新規追加したガードをパスするために必要

    def mock_exists(path_obj):
        path_str = str(path_obj)
        if "soul_narrative_REBUILT.mp4" in path_str:
            return "soul_narrative_REBUILT.mp4" in existing_paths
        for p in existing_paths:
            if p in path_str:
                return True
        return False

    def mock_run_cmd(cmd, *args, **kwargs):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        res = MagicMock()
        if "concat" in cmd_str:
            existing_paths.add("soul_narrative_REBUILT.mp4")
            res.returncode = 0
        elif "overlay" in cmd_str:
            res.returncode = 0
        elif "ffprobe" in cmd_str:
            res.returncode = 0
            res.stdout = "150.0\n"
        return res

    mock_stat = MagicMock()
    mock_stat.st_size = 10 * 1024 * 1024  # 10 MB

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch.object(Path, "stat", return_value=mock_stat), \
         patch("backend.apply_full_premium_telop.subprocess.run", side_effect=mock_run_cmd), \
         patch("backend.apply_full_premium_telop.create_premium_branding", return_value=Path("mock_branding.png")):

        result = target_module.apply_premium_telop_to_entire_video()
        assert result == str(BASE_PATH / "soul_narrative_FINAL_PREMIUM.mp4")


# 4. apply_premium_telop_to_entire_video: 入力動画あり ＆ overlay成功
def test_apply_premium_telop_input_exists_success():
    """入力動画が最初から存在し、overlay処理が成功するケース"""
    def mock_exists(path_obj):
        return True

    def mock_run_cmd(cmd, *args, **kwargs):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        res = MagicMock()
        if "overlay" in cmd_str:
            res.returncode = 0
        elif "ffprobe" in cmd_str:
            res.returncode = 0
            res.stdout = "65.4\n"
        return res

    mock_stat = MagicMock()
    mock_stat.st_size = 5 * 1024 * 1024  # 5 MB

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch.object(Path, "stat", return_value=mock_stat), \
         patch("backend.apply_full_premium_telop.subprocess.run", side_effect=mock_run_cmd), \
         patch("backend.apply_full_premium_telop.create_premium_branding", return_value=Path("mock_branding.png")):

        result = target_module.apply_premium_telop_to_entire_video()
        assert result == str(BASE_PATH / "soul_narrative_FINAL_PREMIUM.mp4")


# 5. apply_premium_telop_to_entire_video: 入力動画あり ＆ overlay失敗
def test_apply_premium_telop_input_exists_overlay_fail():
    """入力動画が存在するが、overlay処理（ffmpeg）が失敗するケース"""
    def mock_exists(path_obj):
        if "soul_narrative_FINAL_PREMIUM.mp4" in str(path_obj):
            return False
        return True

    mock_run_result = MagicMock()
    mock_run_result.returncode = 1
    mock_run_result.stderr = "FFmpeg overlay processing failed"

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch("backend.apply_full_premium_telop.subprocess.run", return_value=mock_run_result), \
         patch("backend.apply_full_premium_telop.create_premium_branding", return_value=Path("mock_branding.png")):

        result = target_module.apply_premium_telop_to_entire_video()
        assert result is None


# 6. __main__ ブロックの実行検証（処理成功ケース）
def test_main_block_success():
    """__main__ブロックが実行され、処理全体が成功するパスを検証"""
    def mock_exists(path_obj):
        return True

    def mock_run_cmd(cmd, *args, **kwargs):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        res = MagicMock()
        if "overlay" in cmd_str:
            res.returncode = 0
        elif "ffprobe" in cmd_str:
            res.returncode = 0
            res.stdout = "65.4\n"
        return res

    mock_stat = MagicMock()
    mock_stat.st_size = 5 * 1024 * 1024  # 5 MB

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch.object(Path, "stat", return_value=mock_stat), \
         patch("backend.apply_full_premium_telop.subprocess.run", side_effect=mock_run_cmd), \
         patch("backend.apply_full_premium_telop.create_premium_branding", return_value=Path("mock_branding.png")), \
         patch("time.time", side_effect=[1000.0, 1060.0]):

        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*found in sys.modules.*")
            runpy.run_module("backend.apply_full_premium_telop", run_name="__main__")


# 7. __main__ ブロックの実行検証（処理失敗ケース）
def test_main_block_fail():
    """__main__ブロックが実行され、処理全体が失敗するパスを検証"""
    def mock_exists(path_obj):
        if "soul_narrative_FINAL_PREMIUM.mp4" in str(path_obj):
            return False
        return True

    mock_run_result = MagicMock()
    mock_run_result.returncode = 1
    mock_run_result.stderr = "FFmpeg overlay failed"

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch("backend.apply_full_premium_telop.subprocess.run", return_value=mock_run_result), \
         patch("backend.apply_full_premium_telop.create_premium_branding", return_value=Path("mock_branding.png")), \
         patch("time.time", side_effect=[1000.0, 1010.0]):

        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*found in sys.modules.*")
            runpy.run_module("backend.apply_full_premium_telop", run_name="__main__")


# 8. create_premium_branding: すべてのフォント読み込みが失敗するケース
def test_create_premium_branding_all_fonts_fail():
    """Yu Gothic, Meiryo, MS Gothic すべてのフォントの読み込みに失敗した場合の例外挙動"""
    def mock_truetype(font_path, font_size):
        raise OSError("Font not found: " + str(font_path))

    with patch("backend.apply_full_premium_telop.Image") as mock_image_cls, \
         patch("backend.apply_full_premium_telop.ImageDraw") as mock_imagedraw_cls, \
         patch("backend.apply_full_premium_telop.ImageFont.truetype", side_effect=mock_truetype):

        mock_logo = MagicMock()
        mock_image_cls.open.return_value = mock_logo
        mock_logo.convert.return_value = mock_logo

        mock_telop = MagicMock()
        mock_combined = MagicMock()
        mock_image_cls.new.side_effect = [mock_telop, mock_combined]

        mock_draw = MagicMock()
        mock_imagedraw_cls.Draw.return_value = mock_draw

        with pytest.raises(OSError):
            target_module.create_premium_branding()


# 9. create_premium_branding: ロゴ画像が存在しないケース (ガード処理で FileNotFoundError になる)
def test_create_premium_branding_logo_missing():
    """ロゴ画像のオープン時に例外が発生するケース"""
    def mock_exists(path_obj):
        if "brand_logo.png" in str(path_obj):
            return False
        return True

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists):
        with pytest.raises(FileNotFoundError):
            target_module.create_premium_branding()


# 10. apply_premium_telop_to_entire_video: ffprobeの出力が不正でfloat変換に失敗するケース
def test_apply_premium_telop_ffprobe_invalid_output():
    """ffprobeの出力が数値以外の場合の挙動"""
    def mock_exists(path_obj):
        return True

    def mock_run_cmd(cmd, *args, **kwargs):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        res = MagicMock()
        if "overlay" in cmd_str:
            res.returncode = 0
        elif "ffprobe" in cmd_str:
            res.returncode = 0
            res.stdout = "invalid_duration\n"
        return res

    mock_stat = MagicMock()
    mock_stat.st_size = 5 * 1024 * 1024

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch.object(Path, "stat", return_value=mock_stat), \
         patch("backend.apply_full_premium_telop.subprocess.run", side_effect=mock_run_cmd), \
         patch("backend.apply_full_premium_telop.create_premium_branding", return_value=Path("mock_branding.png")):

        result = target_module.apply_premium_telop_to_entire_video()
        assert result is None


# 11. apply_premium_telop_to_entire_video: ffprobeコマンドがエラー終了するケース
def test_apply_premium_telop_ffprobe_run_fail():
    """ffprobeの実行自体がエラー（exit code != 0）を返した場合"""
    def mock_exists(path_obj):
        return True

    def mock_run_cmd(cmd, *args, **kwargs):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        res = MagicMock()
        if "overlay" in cmd_str:
            res.returncode = 0
        elif "ffprobe" in cmd_str:
            res.returncode = 1
            res.stdout = ""
            res.stderr = "ffprobe error"
        return res

    mock_stat = MagicMock()
    mock_stat.st_size = 5 * 1024 * 1024

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch.object(Path, "stat", return_value=mock_stat), \
         patch("backend.apply_full_premium_telop.subprocess.run", side_effect=mock_run_cmd), \
         patch("backend.apply_full_premium_telop.create_premium_branding", return_value=Path("mock_branding.png")):

        result = target_module.apply_premium_telop_to_entire_video()
        assert result is None


# 12. create_premium_branding: Yu Gothic Bold が直接成功するケース
def test_create_premium_branding_yugothic_success():
    """Yu Gothic Bold が直接成功し、以降のフォールバックが試行されないことを検証"""
    font_mock_calls = []

    def mock_truetype(font_path, font_size):
        font_mock_calls.append(font_path)
        mock_font = MagicMock()
        return mock_font

    with patch("backend.apply_full_premium_telop.Image") as mock_image_cls, \
         patch("backend.apply_full_premium_telop.ImageDraw") as mock_imagedraw_cls, \
         patch("backend.apply_full_premium_telop.ImageFont.truetype", side_effect=mock_truetype):

        mock_logo = MagicMock()
        mock_image_cls.open.return_value = mock_logo
        mock_logo.convert.return_value = mock_logo

        mock_telop = MagicMock()
        mock_combined = MagicMock()
        mock_image_cls.new.side_effect = [mock_telop, mock_combined]

        mock_draw = MagicMock()
        mock_imagedraw_cls.Draw.return_value = mock_draw
        mock_draw.textbbox.return_value = (0, 0, 100, 20)

        result = target_module.create_premium_branding()

        assert len(font_mock_calls) == 1
        assert "YuGothB.ttc" in font_mock_calls[0]
        assert result == _expected_output_path()


# 13. create_premium_branding: Yu Gothic Bold が失敗し、Meiryo Bold が成功するケース
def test_create_premium_branding_meiryo_success():
    """Yu Gothic Bold が失敗し、Meiryo Bold が成功し、以降のフォールバックが試行されないことを検証"""
    font_mock_calls = []

    def mock_truetype(font_path, font_size):
        font_mock_calls.append(font_path)
        if "YuGothB.ttc" in font_path:
            raise OSError("Yu Gothic Bold not found")
        mock_font = MagicMock()
        return mock_font

    with patch("backend.apply_full_premium_telop.Image") as mock_image_cls, \
         patch("backend.apply_full_premium_telop.ImageDraw") as mock_imagedraw_cls, \
         patch("backend.apply_full_premium_telop.ImageFont.truetype", side_effect=mock_truetype):

        mock_logo = MagicMock()
        mock_image_cls.open.return_value = mock_logo
        mock_logo.convert.return_value = mock_logo

        mock_telop = MagicMock()
        mock_combined = MagicMock()
        mock_image_cls.new.side_effect = [mock_telop, mock_combined]

        mock_draw = MagicMock()
        mock_imagedraw_cls.Draw.return_value = mock_draw
        mock_draw.textbbox.return_value = (0, 0, 100, 20)

        result = target_module.create_premium_branding()

        assert len(font_mock_calls) == 2
        assert "YuGothB.ttc" in font_mock_calls[0]
        assert "meiryob.ttc" in font_mock_calls[1]
        assert result == _expected_output_path()


# 14. apply_premium_telop_to_entire_video: ffprobe実行中にSubprocessErrorが発生するケース
def test_apply_premium_telop_ffprobe_subprocess_error():
    """ffprobe実行中にSubprocessErrorが発生した場合の挙動"""
    def mock_exists(path_obj):
        return True

    def mock_run_cmd(cmd, *args, **kwargs):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        if "ffprobe" in cmd_str:
            raise subprocess.SubprocessError("Subprocess failed")
        res = MagicMock()
        res.returncode = 0
        return res

    mock_stat = MagicMock()
    mock_stat.st_size = 5 * 1024 * 1024

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch.object(Path, "stat", return_value=mock_stat), \
         patch("backend.apply_full_premium_telop.subprocess.run", side_effect=mock_run_cmd), \
         patch("backend.apply_full_premium_telop.create_premium_branding", return_value=Path("mock_branding.png")):

        result = target_module.apply_premium_telop_to_entire_video()
        assert result is None


# ===================== 新規追加テスト (例外・エラーガードのカバー用) =====================

# 15. apply_premium_telop_to_entire_video: concat 実行時に FileNotFoundError (ffmpeg コマンドなし)
def test_apply_premium_telop_concat_ffmpeg_not_found():
    """concat実行時にffmpegが見つからない場合の挙動を検証"""
    def mock_exists(path_obj):
        if "soul_narrative_REBUILT.mp4" in str(path_obj):
            return False
        return True

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch("backend.apply_full_premium_telop.subprocess.run", side_effect=FileNotFoundError("ffmpeg not found")):
        result = target_module.apply_premium_telop_to_entire_video()
        assert result is None


# 16. apply_premium_telop_to_entire_video: concat 実行時に SubprocessError 
def test_apply_premium_telop_concat_subprocess_error():
    """concat実行時にSubprocessErrorが発生した場合の挙動を検証"""
    def mock_exists(path_obj):
        if "soul_narrative_REBUILT.mp4" in str(path_obj):
            return False
        return True

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch("backend.apply_full_premium_telop.subprocess.run", side_effect=subprocess.SubprocessError("Subprocess failed")):
        result = target_module.apply_premium_telop_to_entire_video()
        assert result is None


# 17. apply_premium_telop_to_entire_video: overlay 実行時に FileNotFoundError
def test_apply_premium_telop_overlay_ffmpeg_not_found():
    """overlay実行時にffmpegが見つからない場合の挙動を検証"""
    def mock_exists(path_obj):
        return True

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch("backend.apply_full_premium_telop.create_premium_branding", return_value=Path("mock_branding.png")), \
         patch("backend.apply_full_premium_telop.subprocess.run", side_effect=FileNotFoundError("ffmpeg not found")):
        result = target_module.apply_premium_telop_to_entire_video()
        assert result is None


# 18. apply_premium_telop_to_entire_video: overlay 実行時に SubprocessError
def test_apply_premium_telop_overlay_subprocess_error():
    """overlay実行時にSubprocessErrorが発生した場合の挙動を検証"""
    def mock_exists(path_obj):
        return True

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch("backend.apply_full_premium_telop.create_premium_branding", return_value=Path("mock_branding.png")), \
         patch("backend.apply_full_premium_telop.subprocess.run", side_effect=subprocess.SubprocessError("Subprocess failed")):
        result = target_module.apply_premium_telop_to_entire_video()
        assert result is None


# 19. apply_premium_telop_to_entire_video: ffprobe 実行時に FileNotFoundError
def test_apply_premium_telop_ffprobe_not_found():
    """ffprobe実行時にffprobeが見つからない場合の挙動を検証"""
    def mock_exists(path_obj):
        return True

    def mock_run_cmd(cmd, *args, **kwargs):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        if "ffprobe" in cmd_str:
            raise FileNotFoundError("ffprobe not found")
        res = MagicMock()
        res.returncode = 0
        return res

    mock_stat = MagicMock()
    mock_stat.st_size = 5 * 1024 * 1024

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch.object(Path, "stat", return_value=mock_stat), \
         patch("backend.apply_full_premium_telop.subprocess.run", side_effect=mock_run_cmd), \
         patch("backend.apply_full_premium_telop.create_premium_branding", return_value=Path("mock_branding.png")):
        result = target_module.apply_premium_telop_to_entire_video()
        assert result is None


# 20. apply_premium_telop_to_entire_video: overlay 成功するが出力ファイルが存在しないケース
def test_apply_premium_telop_overlay_success_but_output_missing():
    """overlayの終了コードは0だが、出力動画ファイルが生成されなかったケース"""
    def mock_exists(path_obj):
        # 出力ファイルのみ存在しない
        if "soul_narrative_FINAL_PREMIUM.mp4" in str(path_obj):
            return False
        return True

    mock_run_result = MagicMock()
    mock_run_result.returncode = 0
    mock_run_result.stderr = ""

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch("backend.apply_full_premium_telop.subprocess.run", return_value=mock_run_result), \
         patch("backend.apply_full_premium_telop.create_premium_branding", return_value=Path("mock_branding.png")):

        result = target_module.apply_premium_telop_to_entire_video()
        assert result is None


# 21. apply_premium_telop_to_entire_video: ffprobe での動画秒数境界値のテスト
def test_apply_premium_telop_duration_boundary_cases():
    """ffprobe が返す秒数が境界値（0.0, 3599.9, 3600.0）の場合の挙動を検証"""
    durations = ["0.0", "3599.9", "3600.0"]

    for dur in durations:
        def mock_exists(path_obj):
            return True

        def mock_run_cmd(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            res = MagicMock()
            if "overlay" in cmd_str:
                res.returncode = 0
            elif "ffprobe" in cmd_str:
                res.returncode = 0
                res.stdout = f"{dur}\n"
            return res

        mock_stat = MagicMock()
        mock_stat.st_size = 5 * 1024 * 1024

        with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
             patch.object(Path, "stat", return_value=mock_stat), \
             patch("backend.apply_full_premium_telop.subprocess.run", side_effect=mock_run_cmd), \
             patch("backend.apply_full_premium_telop.create_premium_branding", return_value=Path("mock_branding.png")):

            result = target_module.apply_premium_telop_to_entire_video()
            assert result == str(BASE_PATH / "soul_narrative_FINAL_PREMIUM.mp4")


# 22. create_premium_branding: ロゴ画像が破損しており Image.open が失敗するケース
def test_create_premium_branding_logo_corrupted():
    """ロゴファイルは存在するが、オープン時に例外が発生するケース"""
    def mock_exists(path_obj):
        return True

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch("backend.apply_full_premium_telop.Image.open", side_effect=OSError("Corrupted image")):
        with pytest.raises(OSError, match="Corrupted image"):
            target_module.create_premium_branding()


# 23. apply_premium_telop_to_entire_video: 再構築(concat)成功後、stat取得で例外が発生するケース
def test_apply_premium_telop_rebuild_success_but_stat_fails():
    """再構築は成功するが、サイズ取得(stat)で例外が発生するケース"""
    def mock_exists(path_obj):
        if "soul_narrative_REBUILT.mp4" in str(path_obj):
            return False  # 再構築をトリガーするため
        return True

    def mock_run_cmd(cmd, *args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        return res

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch.object(Path, "stat", side_effect=OSError("Permission denied")), \
         patch("backend.apply_full_premium_telop.subprocess.run", side_effect=mock_run_cmd):
        with pytest.raises(OSError, match="Permission denied"):
            target_module.apply_premium_telop_to_entire_video()

# ===================== 新規追加テスト（境界値・堅牢化） =====================

# 24. apply_premium_telop_to_entire_video: ffprobeの出力が改行やスペースを多く含むケース
def test_apply_premium_telop_ffprobe_whitespace_output():
    """ffprobeの出力値の前後に不要な空白や改行が多く含まれる場合のパース挙動を検証"""
    def mock_exists(path_obj):
        return True

    def mock_run_cmd(cmd, *args, **kwargs):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        res = MagicMock()
        if "overlay" in cmd_str:
            res.returncode = 0
        elif "ffprobe" in cmd_str:
            res.returncode = 0
            res.stdout = "   \n\r  123.456 \n\r   "
        return res

    mock_stat = MagicMock()
    mock_stat.st_size = 5 * 1024 * 1024

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch.object(Path, "stat", return_value=mock_stat), \
         patch("backend.apply_full_premium_telop.subprocess.run", side_effect=mock_run_cmd), \
         patch("backend.apply_full_premium_telop.create_premium_branding", return_value=Path("mock_branding.png")):

        result = target_module.apply_premium_telop_to_entire_video()
        assert result == str(BASE_PATH / "soul_narrative_FINAL_PREMIUM.mp4")


# 25. apply_premium_telop_to_entire_video: ffprobeの出力が空文字列の場合
def test_apply_premium_telop_ffprobe_empty_output():
    """ffprobeの出力値が空（または改行のみ）で、パース時に ValueError になる挙動を検証"""
    def mock_exists(path_obj):
        return True

    def mock_run_cmd(cmd, *args, **kwargs):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        res = MagicMock()
        if "overlay" in cmd_str:
            res.returncode = 0
        elif "ffprobe" in cmd_str:
            res.returncode = 0
            res.stdout = "\n"
        return res

    mock_stat = MagicMock()
    mock_stat.st_size = 5 * 1024 * 1024

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch.object(Path, "stat", return_value=mock_stat), \
         patch("backend.apply_full_premium_telop.subprocess.run", side_effect=mock_run_cmd), \
         patch("backend.apply_full_premium_telop.create_premium_branding", return_value=Path("mock_branding.png")):

        result = target_module.apply_premium_telop_to_entire_video()
        assert result is None


# 26. create_premium_branding: Image.new の引数や処理中に例外が発生するケース
def test_create_premium_branding_image_new_value_error():
    """Image.new の呼出時に ValueError が発生したものとしてのエラー伝播を検証"""
    with patch("backend.apply_full_premium_telop.Image.open") as mock_open, \
         patch("backend.apply_full_premium_telop.Image.new", side_effect=ValueError("Invalid image size")), \
         patch.object(Path, "exists", return_value=True):
        
        mock_logo = MagicMock()
        mock_open.return_value = mock_logo
        mock_logo.convert.return_value = mock_logo

        with pytest.raises(ValueError, match="Invalid image size"):
            target_module.create_premium_branding()


# 27. apply_premium_telop_to_entire_video: subprocess.run でエラーが無視され無視される挙動 of チェック
def test_apply_premium_telop_subprocess_errors_ignore():
    """subprocess.run が errors='ignore' や encoding='utf-8' を引数に正しく実行されることを確認"""
    def mock_exists(path_obj):
        return True

    mock_stat = MagicMock()
    mock_stat.st_size = 5 * 1024 * 1024

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch.object(Path, "stat", return_value=mock_stat), \
         patch("backend.apply_full_premium_telop.subprocess.run") as mock_run, \
         patch("backend.apply_full_premium_telop.create_premium_branding", return_value=Path("mock_branding.png")):

        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "120.0\n"
        mock_res.stderr = ""
        mock_run.return_value = mock_res

        result = target_module.apply_premium_telop_to_entire_video()
        assert result == str(BASE_PATH / "soul_narrative_FINAL_PREMIUM.mp4")

        # 呼び出された引数に encoding='utf-8' と errors='ignore' が含まれていることを確認
        assert mock_run.call_count >= 2
        for call_args in mock_run.call_args_list:
            kwargs = call_args[1]
            assert kwargs.get('encoding') == 'utf-8'
            assert kwargs.get('errors') == 'ignore'


# ===================== 新規追加テスト (分割された関数の個別テスト) =====================

def test_load_logo_image_success():
    """_load_logo_image が正常にロゴ画像を読み込めることを検証"""
    mock_logo = MagicMock()
    with patch("backend.apply_full_premium_telop.Image.open") as mock_open, \
         patch.object(Path, "exists", return_value=True):
        mock_open.return_value = mock_logo
        mock_logo.convert.return_value = mock_logo
        
        result = target_module._load_logo_image(Path("dummy_logo.png"))
        assert result == mock_logo
        mock_open.assert_called_once_with(Path("dummy_logo.png"))
        mock_logo.convert.assert_called_once_with('RGBA')


def test_load_logo_image_not_found():
    """_load_logo_image が存在しないパスに対して FileNotFoundError を投げることを検証"""
    with patch.object(Path, "exists", return_value=False):
        with pytest.raises(FileNotFoundError):
            target_module._load_logo_image(Path("dummy_logo.png"))


def test_build_premium_image():
    """_build_premium_image がフォント読み込みとテロップ画像合成を正しく行うことを検証"""
    mock_logo = MagicMock()
    mock_font = MagicMock()
    mock_telop = MagicMock()
    mock_combined = MagicMock()
    
    with patch("backend.apply_full_premium_telop._load_font_with_fallback", return_value=mock_font) as mock_load_font, \
         patch("backend.apply_full_premium_telop._generate_telop_image", return_value=mock_telop) as mock_gen_telop, \
         patch("backend.apply_full_premium_telop._combine_logo_and_telop", return_value=mock_combined) as mock_combine:
         
        result = target_module._build_premium_image(mock_logo, "text")
        assert result == mock_combined
        mock_load_font.assert_called_once_with(target_module.FONT_SIZE)
        mock_gen_telop.assert_called_once_with("text", mock_font)
        mock_combine.assert_called_once_with(mock_logo, mock_telop)


def test_get_file_size_mb():
    """_get_file_size_mb が正しくファイルサイズをMB換算で返すことを検証"""
    mock_stat = MagicMock()
    mock_stat.st_size = 2.5 * 1024 * 1024  # 2.5 MB
    
    with patch.object(Path, "stat", return_value=mock_stat):
        result = target_module._get_file_size_mb(Path("dummy_video.mp4"))
        assert result == 2.5


def test_convert_seconds_to_minutes_and_seconds():
    """_convert_seconds_to_minutes_and_seconds が正しく秒数を分と秒に変換できるか検証"""
    assert target_module._convert_seconds_to_minutes_and_seconds(0.0) == (0, 0)
    assert target_module._convert_seconds_to_minutes_and_seconds(65.4) == (1, 5)
    assert target_module._convert_seconds_to_minutes_and_seconds(3600.0) == (60, 0)


def test_get_video_metadata_summary_success():
    """_get_video_metadata_summary が正常時にメタデータ辞書を正しく返すか検証"""
    with patch("backend.apply_full_premium_telop._get_file_size_mb", return_value=12.5) as mock_size, \
         patch("backend.apply_full_premium_telop._get_video_duration", return_value=90.0) as mock_dur:
        
        res = target_module._get_video_metadata_summary(Path("dummy.mp4"))
        assert res == {"size_mb": 12.5, "duration_sec": 90.0}
        mock_size.assert_called_once_with(Path("dummy.mp4"))
        mock_dur.assert_called_once_with(Path("dummy.mp4"))


def test_get_video_metadata_summary_ffprobe_missing():
    """_get_video_metadata_summary で ffprobe が見つからない場合に FileNotFoundError を投げるか検証"""
    with patch("backend.apply_full_premium_telop._get_file_size_mb", return_value=12.5), \
         patch("backend.apply_full_premium_telop._get_video_duration", side_effect=FileNotFoundError("ffprobe not found")):
        
        with pytest.raises(FileNotFoundError, match="ffprobe command not found"):
            target_module._get_video_metadata_summary(Path("dummy.mp4"))


def test_get_video_metadata_summary_ffprobe_fail():
    """_get_video_metadata_summary で ffprobe が失敗した場合に subprocess.SubprocessError を投げるか検証"""
    with patch("backend.apply_full_premium_telop._get_file_size_mb", return_value=12.5), \
         patch("backend.apply_full_premium_telop._get_video_duration", side_effect=subprocess.SubprocessError("ffprobe fail")):
        
        with pytest.raises(subprocess.SubprocessError, match="Failed to parse video duration"):
            target_module._get_video_metadata_summary(Path("dummy.mp4"))


def test_print_header(capsys):
    """_print_header が正しいヘッダー情報を標準出力に出力するか検証"""
    target_module._print_header()
    captured = capsys.readouterr()
    assert "Adding Premium Telop to ENTIRE Video" in captured.out


def test_handle_overlay_failure(capsys):
    """_handle_overlay_failure がエラー出力を正しく出力するか検証"""
    mock_result = MagicMock()
    mock_result.stderr = "FFmpeg conversion error detail"
    target_module._handle_overlay_failure(mock_result)
    captured = capsys.readouterr()
    assert "Failed to add premium telop" in captured.out
    assert "FFmpeg conversion error detail" in captured.out


# ===================== 新規追加テスト (直接のユニットテスト) =====================

def test_calculate_text_center_position_direct():
    """_calculate_text_center_position 関数の直接的な動作確認を行うユニットテスト"""
    mock_draw = MagicMock()
    mock_draw.textbbox.return_value = (10, 20, 110, 70)  # width = 100, height = 50
    mock_font = MagicMock()
    
    text_x, text_y = target_module._calculate_text_center_position(
        mock_draw,
        "dummy text",
        mock_font,
        300,
        150
    )
    
    assert text_x == 100
    assert text_y == 50
    mock_draw.textbbox.assert_called_once_with((0, 0), "dummy text", font=mock_font)


def test_generate_telop_image_direct():
    """_generate_telop_image 関数の動作を直接検証する"""
    mock_image = MagicMock()
    mock_draw = MagicMock()
    mock_font = MagicMock()

    with patch("backend.apply_full_premium_telop.Image.new", return_value=mock_image) as mock_new, \
         patch("backend.apply_full_premium_telop.ImageDraw.Draw", return_value=mock_draw) as mock_draw_cls, \
         patch("backend.apply_full_premium_telop._calculate_text_center_position", return_value=(10, 5)) as mock_calc:
         
        result = target_module._generate_telop_image("test text", mock_font, 200, 100)
        
        assert result == mock_image
        mock_new.assert_called_once_with('RGBA', (200, 100), (0, 0, 0, 128))
        mock_draw_cls.assert_called_once_with(mock_image)
        mock_calc.assert_called_once_with(mock_draw, "test text", mock_font, 200, 100)
        mock_draw.text.assert_called_once_with((10, 5), "test text", font=mock_font, fill=(255, 255, 255, 255))


def test_combine_logo_and_telop_direct():
    """_combine_logo_and_telop 関数の動作を直接検証する"""
    mock_logo = MagicMock()
    mock_telop = MagicMock()
    mock_combined = MagicMock()

    with patch("backend.apply_full_premium_telop.Image.new", return_value=mock_combined) as mock_new:
        result = target_module._combine_logo_and_telop(mock_logo, mock_telop, 400, 50, 30)
        
        assert result == mock_combined
        mock_new.assert_called_once_with('RGBA', (400, 50), (0, 0, 0, 0))
        mock_combined.paste.assert_any_call(mock_logo, (0, 0), mock_logo)
        mock_combined.paste.assert_any_call(mock_telop, (30, 0), mock_telop)


def test_resolve_branding_paths_direct():
    """_resolve_branding_paths 関数の動作を直接検証する"""
    dummy_root = Path("/dummy/project/root")
    logo, output = target_module._resolve_branding_paths(dummy_root)
    assert logo == dummy_root / "backend" / "branding" / "logos" / "brand_logo.png"
    assert output == _expected_output_path()
