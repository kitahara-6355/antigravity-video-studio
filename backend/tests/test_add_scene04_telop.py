import os
import pytest
from unittest.mock import MagicMock, patch, call
import pathlib
import subprocess
import runpy
from PIL import ImageFont, Image

import backend.add_scene04_telop as target_module

# pathlib.Path の exists と stat をパッチするためのラッパー
def mock_path_exists(self, *args, **kwargs):
    if self.name in ("soul_narrative_TELOP_UNIFIED.mp4", "scene04_telop.png", "soul_narrative_FINAL_EDITED.mp4"):
        return True
    try:
        return os.path.exists(str(self))
    except (TypeError, ValueError):
        return False

def mock_path_stat(self, *args, **kwargs):
    if self.name == "soul_narrative_TELOP_UNIFIED.mp4":
        stat_res = MagicMock()
        stat_res.st_size = 10 * 1024 * 1024  # 10 MB
        return stat_res
    return os.stat(str(self))


@pytest.fixture
def patch_path_methods():
    with patch("pathlib.Path.exists", new=mock_path_exists), \
         patch("pathlib.Path.stat", new=mock_path_stat):
        yield


def test_create_scene04_telop_font_success_yugothb(patch_path_methods):
    """YuGothB.ttc が成功する場合のテスト"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    with patch("PIL.ImageFont.truetype", return_value=mock_font) as mock_truetype, \
         patch("PIL.Image.Image.save") as mock_save:
        
        path = target_module.create_scene04_telop()
        
        assert path.name == "scene04_telop.png"
        mock_truetype.assert_called_once_with(r"C:\Windows\Fonts\YuGothB.ttc", 20)
        mock_save.assert_called_once()


def test_create_scene04_telop_font_fallback_meiryo(patch_path_methods):
    """YuGothB が失敗し、meiryob が成功する場合のテスト"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def side_effect(font_path, size):
        if "YuGothB" in font_path:
            raise OSError("YuGothB not found")
        return mock_font

    with patch("PIL.ImageFont.truetype", side_effect=side_effect) as mock_truetype, \
         patch("PIL.Image.Image.save") as mock_save:
        
        path = target_module.create_scene04_telop()
        
        assert path.name == "scene04_telop.png"
        assert mock_truetype.call_count == 2
        mock_truetype.assert_has_calls([
            call(r"C:\Windows\Fonts\YuGothB.ttc", 20),
            call(r"C:\Windows\Fonts\meiryob.ttc", 20)
        ])
        mock_save.assert_called_once()


def test_create_scene04_telop_font_fallback_msgothic(patch_path_methods):
    """YuGothB と meiryob が失敗し、msgothic が成功する場合のテスト"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def side_effect(font_path, size):
        if "YuGothB" in font_path or "meiryo" in font_path:
            raise OSError("Font not found")
        return mock_font

    with patch("PIL.ImageFont.truetype", side_effect=side_effect) as mock_truetype, \
         patch("PIL.Image.Image.save") as mock_save:
        
        path = target_module.create_scene04_telop()
        
        assert path.name == "scene04_telop.png"
        assert mock_truetype.call_count == 3
        mock_truetype.assert_has_calls([
            call(r"C:\Windows\Fonts\YuGothB.ttc", 20),
            call(r"C:\Windows\Fonts\meiryob.ttc", 20),
            call(r"C:\Windows\Fonts\msgothic.ttc", 20)
        ])
        mock_save.assert_called_once()


def test_create_scene04_telop_font_all_fail(patch_path_methods):
    """すべてのフォントが失敗して load_default() にフォールバックするケースのテスト"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    with patch("PIL.ImageFont.truetype", side_effect=OSError("Font not found")) as mock_truetype, \
         patch("PIL.ImageFont.load_default", return_value=mock_font) as mock_load_default, \
         patch("PIL.Image.Image.save") as mock_save:
        
        path = target_module.create_scene04_telop()
        
        assert path.name == "scene04_telop.png"
        assert mock_truetype.call_count == 3
        mock_load_default.assert_called_once()
        mock_save.assert_called_once()


def test_add_telop_to_scene04_only_success(patch_path_methods):
    """add_telop_to_scene04_only が成功する場合のテスト"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        if cmd[0] == "ffprobe":
            res.stdout = "2256.0\n"
        else:
            res.stdout = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run) as mock_subprocess_run:
        
        video_path = target_module.add_telop_to_scene04_only()
        
        assert video_path is not None
        assert "soul_narrative_TELOP_UNIFIED.mp4" in video_path
        assert mock_subprocess_run.call_count == 2


def test_add_telop_to_scene04_only_ffmpeg_fail(patch_path_methods):
    """ffmpeg が失敗する場合のテスト"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        if cmd[0] == "ffmpeg":
            res.returncode = 1
            res.stderr = "FFmpeg failed mock error"
        else:
            res.returncode = 0
            res.stdout = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run) as mock_subprocess_run:
        
        video_path = target_module.add_telop_to_scene04_only()
        
        assert video_path is None
        assert mock_subprocess_run.call_count == 1  # ffprobe は呼ばれない


def test_add_telop_to_scene04_only_output_not_exist(patch_path_methods):
    """ffmpeg は成功したが、出力ファイルが存在しない場合のテスト"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    # exists が False を返すようにする
    def mock_path_not_exists(self):
        if self.name == "soul_narrative_TELOP_UNIFIED.mp4":
            return False
        return mock_path_exists(self)

    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stdout = ""
        res.stderr = ""
        return res

    with patch("pathlib.Path.exists", new=mock_path_not_exists), \
         patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run) as mock_subprocess_run:
        
        video_path = target_module.add_telop_to_scene04_only()
        
        assert video_path is None
        assert mock_subprocess_run.call_count == 1  # ffprobe は呼ばれない


def test_main_execution_success(patch_path_methods):
    """__name__ == '__main__' 実行ブロックを通すテスト (成功パス)"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        if cmd[0] == "ffprobe":
            res.stdout = "2256.0\n"
        else:
            res.stdout = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run):
        
        # run_path を使ってモジュールをメインプログラムとしてロード実行
        # これによりカバレッジ測定器が正しく実行行を追跡できるようになります
        runpy.run_path(target_module.__file__, run_name="__main__")



def test_main_execution_fail(patch_path_methods):
    """__name__ == '__main__' 実行ブロックを通すテスト (失敗パス)"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        if cmd[0] == "ffmpeg":
            res.returncode = 1
            res.stderr = "FFmpeg failed mock error"
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run):
        
        runpy.run_path(target_module.__file__, run_name="__main__")


def test_add_telop_to_scene04_only_ffmpeg_os_error(patch_path_methods):
    """ffmpeg 実行時に OSError が発生した場合のテスト"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=OSError("FFmpeg command not found")):
        
        video_path = target_module.add_telop_to_scene04_only()
        
        assert video_path is None


def test_add_telop_to_scene04_only_ffprobe_os_error(patch_path_methods):
    """ffprobe 実行時に OSError が発生した場合のテスト"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        if cmd[0] == "ffmpeg":
            res = MagicMock(spec=subprocess.CompletedProcess)
            res.returncode = 0
            res.stderr = ""
            return res
        else:
            raise OSError("ffprobe not found")

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run) as mock_subprocess_run:
        
        video_path = target_module.add_telop_to_scene04_only()
        
        # ffprobeが落ちても正常に終了し、動画パスは返される (Durationのみunknownになる)
        assert video_path is not None
        assert "soul_narrative_TELOP_UNIFIED.mp4" in video_path
        assert mock_subprocess_run.call_count == 2


def test_add_telop_to_scene04_only_ffprobe_value_error(patch_path_methods):
    """ffprobe の出力が不正で ValueError が発生した場合のテスト"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        if cmd[0] == "ffprobe":
            res.stdout = "invalid_duration_string\n"
            res.stderr = "ffprobe mock stderr output"
        else:
            res.stdout = ""
            res.stderr = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run) as mock_subprocess_run:
        
        video_path = target_module.add_telop_to_scene04_only()
        
        assert video_path is not None
        assert "soul_narrative_TELOP_UNIFIED.mp4" in video_path
        assert mock_subprocess_run.call_count == 2


def test_add_telop_to_scene04_only_ffprobe_nonzero_exit(patch_path_methods):
    """ffprobe が非ゼロの終了コードを返した場合のテスト"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.stderr = "ffprobe execution error"
        if cmd[0] == "ffprobe":
            res.returncode = 1
            res.stdout = ""
        else:
            res.returncode = 0
            res.stdout = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run) as mock_subprocess_run:
        
        video_path = target_module.add_telop_to_scene04_only()
        
        assert video_path is not None
        assert "soul_narrative_TELOP_UNIFIED.mp4" in video_path
        assert mock_subprocess_run.call_count == 2


def test_dynamic_path_resolution():
    """base パスが正しくプロジェクトルート（backend の親）を指していることをテスト"""
    import backend.add_scene04_telop as target_module
    import pathlib
    
    expected_base = pathlib.Path(target_module.__file__).resolve().parent.parent
    
    # 期待されるプロジェクトルート直下に backend ディレクトリが存在することを確認
    assert (expected_base / "backend").exists()
    assert (expected_base / "backend" / "add_scene04_telop.py").exists()


def test_add_telop_to_scene04_only_ffprobe_duration_edge_cases(patch_path_methods):
    """ffprobe が返す duration の様々な境界値/異常値パターンのテスト"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))

    # パターン1: 整数値のduration（例: "2200"）
    def mock_run_integer(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        if cmd[0] == "ffprobe":
            res.stdout = "2200\n"
        else:
            res.stdout = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run_integer):
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is not None

    # パターン2: 0秒のduration（例: "0.0"）
    def mock_run_zero(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        if cmd[0] == "ffprobe":
            res.stdout = "0.0\n"
        else:
            res.stdout = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run_zero):
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is not None

    # パターン3: 空文字列のduration（ValueErrorの発生を期待）
    def mock_run_empty(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        if cmd[0] == "ffprobe":
            res.stdout = "\n"
        else:
            res.stdout = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run_empty):
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is not None


def test_add_telop_to_scene04_only_ffmpeg_fail_with_empty_stderr(patch_path_methods):
    """ffmpeg が失敗し、stderr が None や空文字列の場合のテスト"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))

    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 1
        res.stderr = None  # None に設定
        res.stdout = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run):
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is None


def test_main_execution_via_run_path_direct(patch_path_methods):
    """runpy.run_path を直接使用してモジュールファイルを実行する新規テスト"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        if cmd[0] == "ffprobe":
            res.stdout = "2256.0\n"
        else:
            res.stdout = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font),          patch("PIL.Image.Image.save"),          patch("subprocess.run", side_effect=mock_run) as mock_subprocess_run:
        
        # run_path で直接実行
        runpy.run_path(target_module.__file__, run_name="__main__")
        
        # subprocess.run が正しく呼び出されたこと（ffmpegとffprobe）を検証
        assert mock_subprocess_run.call_count == 2
        calls = [c[0][0][0] for c in mock_subprocess_run.call_args_list]
        assert "ffmpeg" in calls
        assert "ffprobe" in calls

def test_create_scene04_telop_font_offset_correction(patch_path_methods):
    """Pillowのdraw.text描画位置に対するフォントバウンディングボックスのオフセット補正が正しく計算されるかをテスト"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    # bboxが (2, 5, 302, 45) の場合をシミュレート
    mock_font.getbbox.return_value = (2, 5, 302, 45)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    mock_image = MagicMock(spec=Image.Image)
    mock_draw = MagicMock()
    mock_draw.textbbox.return_value = (2, 5, 302, 45)
    
    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.new", return_value=mock_image), \
         patch("PIL.ImageDraw.Draw", return_value=mock_draw), \
         patch("PIL.Image.Image.save"):
        
        path = target_module.create_scene04_telop()
        
        assert path.name == "scene04_telop.png"
        
        # text_width = 302 - 2 + 20 = 320
        # text_height = 45 - 5 + 10 = 50
        # x = 10 - 2 = 8
        # y = (50 - (45 - 5)) // 2 - 5 = (50 - 40) // 2 - 5 = 5 - 5 = 0
        mock_draw.text.assert_called_once_with(
            (8, 0),
            "有名人も注目！山田の書道教室",
            font=mock_font,
            fill=(255, 255, 255, 255)
        )


def test_create_scene04_telop_ensures_parent_directory(patch_path_methods):
    """保存先親ディレクトリが存在しない場合でも、mkdir が呼び出されることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    with patch("PIL.ImageFont.truetype", return_value=mock_font),          patch("PIL.Image.Image.save"),          patch("pathlib.Path.mkdir") as mock_mkdir:
         
        path = target_module.create_scene04_telop()
        
        assert path.name == "scene04_telop.png"
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)


def test_add_telop_to_scene04_only_cleans_up_temporary_file(patch_path_methods):
    """正常終了時に一時テロップファイルが削除されることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        if cmd[0] == "ffprobe":
            res.stdout = "2256.0\n"
        else:
            res.stdout = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font),          patch("PIL.Image.Image.save"),          patch("subprocess.run", side_effect=mock_run),          patch("pathlib.Path.unlink") as mock_unlink:
         
        video_path = target_module.add_telop_to_scene04_only()
        
        assert video_path is not None
        mock_unlink.assert_called_once_with(missing_ok=True)


def test_add_telop_to_scene04_only_cleans_up_temporary_file_on_error(patch_path_methods):
    """エラー（FFmpeg失敗）時にも一時テロップファイルが削除されることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        if cmd[0] == "ffmpeg":
            res.returncode = 1
            res.stderr = "FFmpeg failed mock error"
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font),          patch("PIL.Image.Image.save"),          patch("subprocess.run", side_effect=mock_run),          patch("pathlib.Path.unlink") as mock_unlink:
         
        video_path = target_module.add_telop_to_scene04_only()
        
        assert video_path is None
        mock_unlink.assert_called_once_with(missing_ok=True)


def test_add_telop_to_scene04_only_unlink_exception_is_handled(patch_path_methods):
    """一時ファイルの削除時に例外が発生した場合も適切にハンドルされ、関数自体は例外を投げずに処理が完了することを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        if cmd[0] == "ffprobe":
            res.stdout = "2256.0\n"
        else:
            res.stdout = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font),          patch("PIL.Image.Image.save"),          patch("subprocess.run", side_effect=mock_run),          patch("pathlib.Path.unlink", side_effect=OSError("Permission denied")):
         
        video_path = target_module.add_telop_to_scene04_only()
        
        assert video_path is not None


def test_add_telop_to_scene04_only_input_video_not_found():
    """入力動画ファイルが存在しない場合に早期リターンし、create_scene04_telopを呼び出さないことを検証"""
    def mock_exists(self):
        if self.name == "soul_narrative_FINAL_EDITED.mp4":
            return False
        return True

    with patch("pathlib.Path.exists", new=mock_exists), \
         patch("backend.add_scene04_telop.create_scene04_telop") as mock_create:
        
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is None
        mock_create.assert_not_called()


def test_add_telop_to_scene04_only_ffmpeg_timeout(patch_path_methods):
    """ffmpeg実行時にタイムアウトが発生した場合に適切にハンドルされてNoneを返し、一時ファイルが削除されることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        if cmd[0] == "ffmpeg":
            raise subprocess.TimeoutExpired(cmd, 120)
        return MagicMock()

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run), \
         patch("pathlib.Path.unlink") as mock_unlink:
         
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is None
        mock_unlink.assert_called_once_with(missing_ok=True)


def test_add_telop_to_scene04_only_ffprobe_timeout(patch_path_methods):
    """ffprobe実行時にタイムアウトが発生した場合に適切に警告が出力され、最終的に動画パスが返ることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        res.stdout = ""
        if cmd[0] == "ffprobe":
            raise subprocess.TimeoutExpired(cmd, 10)
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run):
         
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is not None
        assert "soul_narrative_TELOP_UNIFIED.mp4" in video_path


def test_create_scene04_telop_save_exception(patch_path_methods):
    """Image.save() 時に OSError が発生した場合に create_scene04_telop が None を返すことを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save", side_effect=OSError("Disk full")) as mock_save:
        
        path = target_module.create_scene04_telop()
        assert path is None
        mock_save.assert_called_once()


def test_add_telop_to_scene04_only_when_telop_creation_fails(patch_path_methods):
    """create_scene04_telop が None を返した場合に add_telop_to_scene04_only が例外なく None を返すことを検証"""
    with patch("backend.add_scene04_telop.create_scene04_telop", return_value=None):
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is None


def test_create_scene04_telop_type_error(patch_path_methods):
    """draw.textbbox が TypeError を投げた場合に create_scene04_telop が安全に None を返すことを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    
    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.ImageDraw.Draw") as mock_draw_cls:
        
        mock_draw = MagicMock()
        mock_draw.textbbox.side_effect = TypeError("Invalid bbox argument type")
        mock_draw_cls.return_value = mock_draw
        
        path = target_module.create_scene04_telop()
        assert path is None


def test_add_telop_to_scene04_only_ffprobe_empty_stdout(patch_path_methods):
    """ffprobe が正常終了したが stdout が空の場合に安全に unknown にフォールバックすることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        if cmd[0] == "ffprobe":
            res.stdout = ""  # 空文字列
        else:
            res.stdout = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run):
        
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is not None


def test_add_telop_to_scene04_only_ffmpeg_timeout_with_output(patch_path_methods):
    """ffmpeg タイムアウト発生時に stdout/stderr があればログに出力されることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        if cmd[0] == "ffmpeg":
            raise subprocess.TimeoutExpired(cmd, 120, output="ffmpeg timed out stdout", stderr="ffmpeg timed out stderr")
        return MagicMock()

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run), \
         patch("pathlib.Path.unlink"):
         
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is None


def test_add_telop_to_scene04_only_unlink_type_error(patch_path_methods):
    """一時ファイル削除時に Path の型エラー（TypeError）が発生した場合も、例外が伝播せずに動画パスを返すことを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        if cmd[0] == "ffprobe":
            res.stdout = "2256.0\n"
        else:
            res.stdout = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run), \
         patch("pathlib.Path.unlink", side_effect=TypeError("invalid path type")):
         
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is not None
        assert "soul_narrative_TELOP_UNIFIED.mp4" in video_path


def test_add_telop_to_scene04_only_ffmpeg_subprocess_error(patch_path_methods):
    """ffmpeg実行時に一般的な SubprocessError が発生した場合に適切にハンドルされて None を返すことを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        if cmd[0] == "ffmpeg":
            raise subprocess.SubprocessError("FFmpeg generic subprocess error")
        return MagicMock()

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run), \
         patch("pathlib.Path.unlink") as mock_unlink:
         
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is None
        mock_unlink.assert_called_once_with(missing_ok=True)


def test_add_telop_to_scene04_only_ffprobe_subprocess_error(patch_path_methods):
    """ffprobe実行時に一般的な SubprocessError が発生した場合に警告が出力され、最終的に動画パスが返ることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        res.stdout = ""
        if cmd[0] == "ffprobe":
            raise subprocess.SubprocessError("ffprobe generic subprocess error")
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run):
         
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is not None
        assert "soul_narrative_TELOP_UNIFIED.mp4" in video_path


def test_create_scene04_telop_programming_error(patch_path_methods):
    """テロップ作成時に AttributeError や IndexError などのプログラミングエラーが発生した場合に None を返すことを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    
    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.ImageDraw.Draw") as mock_draw_cls:
        
        mock_draw = MagicMock()
        mock_draw.textbbox.side_effect = AttributeError("Mock AttributeError")
        mock_draw_cls.return_value = mock_draw
        
        path = target_module.create_scene04_telop()
        assert path is None


def test_create_scene04_telop_font_all_fail_default_also_fail(patch_path_methods):
    """フォント候補がすべて失敗し、さらにデフォルトフォントの読み込みも失敗した場合に None を返すことを検証"""
    with patch("PIL.ImageFont.truetype", side_effect=OSError("Font not found")), \
         patch("PIL.ImageFont.load_default", side_effect=OSError("Default font load failed")):
         
        path = target_module.create_scene04_telop()
        assert path is None


def test_create_scene04_telop_unexpected_exception(patch_path_methods):
    """テロップ作成時に想定外の一般例外（RuntimeError）が発生した場合、安全に None を返すことを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.ImageDraw.Draw") as mock_draw_cls:
        
        mock_draw = MagicMock()
        mock_draw.textbbox.side_effect = RuntimeError("Unexpected generic exception")
        mock_draw_cls.return_value = mock_draw
        
        path = target_module.create_scene04_telop()
        assert path is None


def test_add_telop_to_scene04_only_ffmpeg_unexpected_exception(patch_path_methods):
    """ffmpeg実行時に想定外の一般例外（Exception）が発生した場合、安全に None を返し、一時ファイルが削除されることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=Exception("Unexpected ffmpeg exception")), \
         patch("pathlib.Path.unlink") as mock_unlink:
         
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is None
        mock_unlink.assert_called_once_with(missing_ok=True)


def test_add_telop_to_scene04_only_ffprobe_unexpected_exception(patch_path_methods):
    """ffprobe実行時に想定外の一般例外（Exception）が発生した場合、例外が伝播せずに動画パスを返すことを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        res.stdout = ""
        if cmd[0] == "ffprobe":
            raise RuntimeError("Unexpected ffprobe exception")
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run):
         
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is not None
        assert "soul_narrative_TELOP_UNIFIED.mp4" in video_path


def test_add_telop_to_scene04_only_unlink_unexpected_exception(patch_path_methods):
    """一時ファイル削除時に想定外の一般例外（Exception）が発生した場合も、例外が伝播せずに関数が正常終了することを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        if cmd[0] == "ffprobe":
            res.stdout = "2256.0\n"
        else:
            res.stdout = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run), \
         patch("pathlib.Path.unlink", side_effect=TypeError("Unexpected unlink exception")):
         
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is not None
        assert "soul_narrative_TELOP_UNIFIED.mp4" in video_path


def test_add_telop_to_scene04_only_unlink_os_error_handled(patch_path_methods):
    """一時ファイル削除時に OSError が発生した場合、例外がキャッチされ、正常終了して動画パスが返ることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        if cmd[0] == "ffprobe":
            res.stdout = "2256.0\n"
        else:
            res.stdout = ""
        return res
    
    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run), \
         patch("pathlib.Path.unlink", side_effect=OSError("Permission denied")):
         
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is not None
        assert "soul_narrative_TELOP_UNIFIED.mp4" in video_path


def test_add_telop_to_scene04_only_ffprobe_attribute_error(patch_path_methods):
    """ffprobe結果パース時に AttributeError（stdoutがNoneなど）が発生した場合に、安全に unknown にフォールバックすることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        if cmd[0] == "ffprobe":
            # stdout属性を削除する、あるいはNoneにして AttributeError を誘発する
            del res.stdout
        else:
            res.stdout = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run):
         
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is not None
        assert "soul_narrative_TELOP_UNIFIED.mp4" in video_path


def test_create_scene04_telop_raises_error(patch_path_methods):
    """create_scene04_telop(raise_on_error=True) で例外発生時に TelopCreationError が発生することをテスト"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    
    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.ImageDraw.Draw") as mock_draw_cls:
        
        mock_draw = MagicMock()
        mock_draw.textbbox.side_effect = TypeError("Invalid bbox argument type")
        mock_draw_cls.return_value = mock_draw
        
        with pytest.raises(target_module.TelopCreationError):
            target_module.create_scene04_telop(raise_on_error=True)


def test_add_telop_to_scene04_only_raises_error_input_missing():
    """入力動画ファイルが存在しない場合に VideoProcessingError が発生することをテスト"""
    def mock_exists(self):
        if self.name == "soul_narrative_FINAL_EDITED.mp4":
            return False
        return True

    with patch("pathlib.Path.exists", new=mock_exists):
        with pytest.raises(target_module.VideoProcessingError) as exc_info:
            target_module.add_telop_to_scene04_only(raise_on_error=True)
        assert "Input video file not found" in str(exc_info.value)


def test_add_telop_to_scene04_only_raises_error_ffmpeg_fail(patch_path_methods):
    """FFmpeg 失敗時に VideoProcessingError が発生することをテスト"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        if cmd[0] == "ffmpeg":
            res.returncode = 1
            res.stderr = "FFmpeg failed mock error"
        else:
            res.returncode = 0
            res.stdout = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run):
        
        with pytest.raises(target_module.VideoProcessingError) as exc_info:
            target_module.add_telop_to_scene04_only(raise_on_error=True)
        assert "Failed to add telop" in str(exc_info.value)


def test_add_telop_to_scene04_only_raises_error_ffmpeg_timeout(patch_path_methods):
    """FFmpeg タイムアウト時に VideoProcessingError が発生することをテスト"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        if cmd[0] == "ffmpeg":
            raise subprocess.TimeoutExpired(cmd, 120)
        return MagicMock()

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run):
         
        with pytest.raises(target_module.VideoProcessingError) as exc_info:
            target_module.add_telop_to_scene04_only(raise_on_error=True)
        assert "FFmpeg process timed out" in str(exc_info.value)


def test_add_telop_to_scene04_only_ffprobe_duration_result_none(patch_path_methods):
    """ffprobe実行結果が None の場合に例外が発生せず、安全に unknown にフォールバックすることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        if cmd[0] == "ffprobe":
            raise OSError("Mock OSError for ffprobe")
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        res.stdout = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run):
         
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is not None
        assert "soul_narrative_TELOP_UNIFIED.mp4" in video_path


def test_create_scene04_telop_raises_error_default_font_fail(patch_path_methods):
    """フォント候補がすべて失敗し、さらにデフォルトフォントの読み込みも失敗し、かつ raise_on_error=True の場合に TelopCreationError が発生することを検証"""
    with patch("PIL.ImageFont.truetype", side_effect=OSError("Font not found")), \
         patch("PIL.ImageFont.load_default", side_effect=OSError("Default font load failed")):
         
        with pytest.raises(target_module.TelopCreationError) as exc_info:
            target_module.create_scene04_telop(raise_on_error=True)
        assert "Failed to load default font" in str(exc_info.value)


def test_create_scene04_telop_raises_error_on_runtime_error(patch_path_methods):
    """テロップ画像作成中の runtime error (OSError/ValueError) 発生時に raise_on_error=True で TelopCreationError がスローされることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save", side_effect=OSError("Save failed")):
         
        with pytest.raises(target_module.TelopCreationError) as exc_info:
            target_module.create_scene04_telop(raise_on_error=True)
        assert "Runtime error failed to create or save scene04 telop" in str(exc_info.value)


def test_create_scene04_telop_raises_error_on_unexpected_runtime_or_key_error(patch_path_methods):
    """テロップ作成時に想定外の RuntimeError/KeyError が発生した場合に raise_on_error=True で TelopCreationError がスローされることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.ImageDraw.Draw") as mock_draw_cls:
        
        mock_draw = MagicMock()
        mock_draw.textbbox.side_effect = RuntimeError("Unexpected crash")
        mock_draw_cls.return_value = mock_draw
        
        with pytest.raises(target_module.TelopCreationError) as exc_info:
            target_module.create_scene04_telop(raise_on_error=True)
        assert "Unexpected runtime or key error in scene04 telop creation" in str(exc_info.value)


def test_add_telop_to_scene04_only_raises_error_on_creation_failure(patch_path_methods):
    """create_scene04_telop が None を返した場合に raise_on_error=True で VideoProcessingError がスローされることを検証"""
    with patch.object(target_module, "create_scene04_telop", return_value=None):
        with pytest.raises(target_module.VideoProcessingError) as exc_info:
            target_module.add_telop_to_scene04_only(raise_on_error=True)
        assert "Cannot proceed because telop generation failed" in str(exc_info.value)


def test_add_telop_to_scene04_only_raises_error_ffmpeg_os_error(patch_path_methods):
    """ffmpeg 起動時の OSError 発生時に raise_on_error=True で VideoProcessingError がスローされることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=OSError("ffmpeg missing")):
         
        with pytest.raises(target_module.VideoProcessingError) as exc_info:
            target_module.add_telop_to_scene04_only(raise_on_error=True)
        assert "Failed to run FFmpeg" in str(exc_info.value)


def test_add_telop_to_scene04_only_raises_error_ffmpeg_subprocess_error(patch_path_methods):
    """ffmpeg 起動時の SubprocessError 発生時に raise_on_error=True で VideoProcessingError がスローされることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=subprocess.SubprocessError("ffmpeg subprocess crash")):
         
        with pytest.raises(target_module.VideoProcessingError) as exc_info:
            target_module.add_telop_to_scene04_only(raise_on_error=True)
        assert "Failed to run FFmpeg (Subprocess error)" in str(exc_info.value)


def test_add_telop_to_scene04_only_raises_error_ffmpeg_unexpected_exception(patch_path_methods):
    """ffmpeg 起動時の一般例外発生時に raise_on_error=True で VideoProcessingError がスローされることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=Exception("ffmpeg unexpected exception")):
         
        with pytest.raises(target_module.VideoProcessingError) as exc_info:
            target_module.add_telop_to_scene04_only(raise_on_error=True)
        assert "Unexpected error in add_telop_to_scene04_only" in str(exc_info.value)


def test_add_telop_to_scene04_only_raises_error_when_telop_error(patch_path_methods):
    """TelopError（ここではVideoProcessingError）が直接発生し、かつ raise_on_error=True のときにそのまま再スローされることを検証"""
    with patch.object(target_module, "create_scene04_telop", side_effect=target_module.TelopCreationError("Creation error mock")):
        with pytest.raises(target_module.TelopCreationError) as exc_info:
            target_module.add_telop_to_scene04_only(raise_on_error=True)
        assert "Creation error mock" in str(exc_info.value)


def test_add_telop_to_scene04_only_handles_telop_error_cleanly(patch_path_methods):
    """TelopError（ここではVideoProcessingError）が発生し、かつ raise_on_error=False のときにログを出力して例外を投げずに None を返すことを検証"""
    with patch.object(target_module, "create_scene04_telop", side_effect=target_module.TelopCreationError("Creation error mock")):
        video_path = target_module.add_telop_to_scene04_only(raise_on_error=False)
        assert video_path is None


def test_create_scene04_telop_bbox_none_value_error(patch_path_methods):
    """draw.textbbox が None を返した場合に ValueError が発生し、適切にハンドリングされて None が返ることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    
    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.ImageDraw.Draw") as mock_draw_cls:
        
        mock_draw = MagicMock()
        mock_draw.textbbox.return_value = None  # Noneを返す
        mock_draw_cls.return_value = mock_draw
        
        path = target_module.create_scene04_telop()
        assert path is None


def test_add_telop_to_scene04_only_input_corrupted(patch_path_methods):
    """入力動画の事前検証で ffprobe がエラー（非ゼロ終了コード）を返した場合に VideoProcessingError が発生することを検証"""
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        if cmd[0] == "ffprobe" and "soul_narrative_FINAL_EDITED.mp4" in cmd[-1]:
            res.returncode = 1
            res.stderr = "ffprobe check error"
            res.stdout = ""
        else:
            res.returncode = 0
            res.stderr = ""
            res.stdout = ""
        return res

    with patch("pathlib.Path.is_file", return_value=True), \
         patch("subprocess.run", side_effect=mock_run):
        with pytest.raises(target_module.VideoProcessingError) as exc_info:
            target_module.add_telop_to_scene04_only(raise_on_error=True)
        assert "Input video file is corrupted or invalid" in str(exc_info.value)


def test_add_telop_to_scene04_only_input_corruption_check_exception(patch_path_methods):
    """入力動画の事前検証で ffprobe 起動時に OSError が発生した場合でも、警告表示のみで処理自体は続行され、動画パスが返ることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))

    def mock_run(cmd, *args, **kwargs):
        if cmd[0] == "ffprobe" and "soul_narrative_FINAL_EDITED.mp4" in cmd[-1]:
            raise OSError("ffprobe command execution error")
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        if cmd[0] == "ffprobe":
            res.stdout = "2256.0\n"
        else:
            res.stdout = ""
        return res

    with patch("pathlib.Path.is_file", return_value=True), \
         patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run):
        
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is not None
        assert "soul_narrative_TELOP_UNIFIED.mp4" in video_path


def test_add_telop_to_scene04_only_input_corrupted_no_raise(patch_path_methods):
    """入力動画の事前検証で ffprobe がエラー（非ゼロ終了コード）を返し、かつ raise_on_error=False の場合に例外なく None を返すことを検証"""
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        if cmd[0] == "ffprobe" and "soul_narrative_FINAL_EDITED.mp4" in cmd[-1]:
            res.returncode = 1
            res.stderr = "ffprobe check error"
            res.stdout = ""
        else:
            res.returncode = 0
            res.stderr = ""
            res.stdout = ""
        return res

    with patch("pathlib.Path.is_file", return_value=True), \
         patch("subprocess.run", side_effect=mock_run):
        video_path = target_module.add_telop_to_scene04_only(raise_on_error=False)
        assert video_path is None


def test_add_telop_to_scene04_only_input_check_success(patch_path_methods):
    """入力動画の事前検証で ffprobe が正常終了し、そのまま後続の処理に成功することを検証 (L130 -> L139)"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))

    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        if cmd[0] == "ffprobe":
            res.stdout = "2256.0\n"
        else:
            res.stdout = ""
        return res

    with patch("pathlib.Path.is_file", return_value=True), \
         patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run) as mock_subprocess_run:
         
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is not None
        assert "soul_narrative_TELOP_UNIFIED.mp4" in video_path
        # 1. 入力動画の破損チェック (ffprobe)
        # 2. ffmpeg コマンド
        # 3. 出力動画の duration チェック (ffprobe)
        # 計 3 回の subprocess.run が呼ばれる
        assert mock_subprocess_run.call_count == 3


def test_add_telop_to_scene04_only_ffprobe_nonzero_exit_empty_stderr(patch_path_methods):
    """ffprobe が非ゼロで終了し、かつ stderr が空の場合に、警告を出しつつも正常に unknown にフォールバックすることを検証 (L208 -> L210)"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))

    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        if cmd[0] == "ffprobe" and "soul_narrative_TELOP_UNIFIED.mp4" in cmd[-1]:
            res.returncode = 1
            res.stdout = ""
            res.stderr = ""  # 空文字列
        else:
            res.returncode = 0
            res.stdout = ""
            res.stderr = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run) as mock_subprocess_run:
         
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is not None
        assert "soul_narrative_TELOP_UNIFIED.mp4" in video_path


def test_create_scene04_telop_font_fallback_syntax_value_error(patch_path_methods):
    """YuGothB が SyntaxError、meiryob が ValueError を投げ、msgothic が成功する場合のテスト"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def side_effect(font_path, size):
        if "YuGothB" in font_path:
            raise SyntaxError("Mock font SyntaxError")
        if "meiryo" in font_path:
            raise ValueError("Mock font ValueError")
        return mock_font

    with patch("PIL.ImageFont.truetype", side_effect=side_effect) as mock_truetype, \
         patch("PIL.Image.Image.save") as mock_save:
        
        path = target_module.create_scene04_telop()
        
        assert path.name == "scene04_telop.png"
        assert mock_truetype.call_count == 3
        mock_truetype.assert_has_calls([
            call(r"C:\Windows\Fonts\YuGothB.ttc", 20),
            call(r"C:\Windows\Fonts\meiryob.ttc", 20),
            call(r"C:\Windows\Fonts\msgothic.ttc", 20)
        ])
        mock_save.assert_called_once()


def test_create_scene04_telop_font_all_fail_default_value_error(patch_path_methods):
    """フォント候補がすべて失敗し、さらにデフォルトフォントの読み込みで ValueError が発生した場合に None を返すことを検証"""
    with patch("PIL.ImageFont.truetype", side_effect=OSError("Font not found")), \
         patch("PIL.ImageFont.load_default", side_effect=ValueError("Default font ValueError")):
         
        path = target_module.create_scene04_telop()
        assert path is None


def test_create_scene04_telop_font_all_fail_default_value_error_raises(patch_path_methods):
    """フォント候補がすべて失敗し、さらにデフォルトフォントの読み込みで ValueError が発生し、かつ raise_on_error=True の場合に TelopCreationError が発生することを検証"""
    with patch("PIL.ImageFont.truetype", side_effect=OSError("Font not found")), \
         patch("PIL.ImageFont.load_default", side_effect=ValueError("Default font ValueError")):
         
        with pytest.raises(target_module.TelopCreationError) as exc_info:
            target_module.create_scene04_telop(raise_on_error=True)
        assert "Failed to load default font" in str(exc_info.value)


def test_create_scene04_telop_value_error_on_drawing(patch_path_methods):
    """画像描画時に ValueError が発生した場合に None を返し、raise_on_error=True で TelopCreationError を投げることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.ImageDraw.Draw") as mock_draw_cls:
        
        mock_draw = MagicMock()
        mock_draw.textbbox.side_effect = ValueError("Mock ValueError during textbbox")
        mock_draw_cls.return_value = mock_draw
        
        # raise_on_error=False
        path = target_module.create_scene04_telop(raise_on_error=False)
        assert path is None
        
        # raise_on_error=True
        with pytest.raises(target_module.TelopCreationError) as exc_info:
            target_module.create_scene04_telop(raise_on_error=True)
        assert "Runtime error failed to create or save scene04 telop" in str(exc_info.value)


def test_create_scene04_telop_index_error_on_drawing(patch_path_methods):
    """画像描画時に IndexError が発生した場合に None を返し、raise_on_error=True で TelopCreationError を投げることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.ImageDraw.Draw") as mock_draw_cls:
        
        mock_draw = MagicMock()
        mock_draw.textbbox.side_effect = IndexError("Mock IndexError during textbbox")
        mock_draw_cls.return_value = mock_draw
        
        # raise_on_error=False
        path = target_module.create_scene04_telop(raise_on_error=False)
        assert path is None
        
        # raise_on_error=True
        with pytest.raises(target_module.TelopCreationError) as exc_info:
            target_module.create_scene04_telop(raise_on_error=True)
        assert "Programming error in scene04 telop creation" in str(exc_info.value)


def test_create_scene04_telop_key_error_on_drawing(patch_path_methods):
    """画像描画時に KeyError が発生した場合に None を返し、raise_on_error=True で TelopCreationError を投げることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.ImageDraw.Draw") as mock_draw_cls:
        
        mock_draw = MagicMock()
        mock_draw.textbbox.side_effect = KeyError("Mock KeyError during textbbox")
        mock_draw_cls.return_value = mock_draw
        
        # raise_on_error=False
        path = target_module.create_scene04_telop(raise_on_error=False)
        assert path is None
        
        # raise_on_error=True
        with pytest.raises(target_module.TelopCreationError) as exc_info:
            target_module.create_scene04_telop(raise_on_error=True)
        assert "Unexpected runtime or key error in scene04 telop creation" in str(exc_info.value)


def test_add_telop_to_scene04_only_input_corruption_check_subprocess_error(patch_path_methods):
    """入力動画の事前検証で ffprobe 起動時に SubprocessError が発生した場合でも、警告表示のみで処理自体は続行され、動画パスが返ることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))

    def mock_run(cmd, *args, **kwargs):
        if cmd[0] == "ffprobe" and "soul_narrative_FINAL_EDITED.mp4" in cmd[-1]:
            raise subprocess.SubprocessError("ffprobe subprocess error during input check")
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        if cmd[0] == "ffprobe":
            res.stdout = "2256.0\n"
        else:
            res.stdout = ""
        return res

    with patch("pathlib.Path.is_file", return_value=True), \
         patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run):
        
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is not None
        assert "soul_narrative_TELOP_UNIFIED.mp4" in video_path


def test_add_telop_to_scene04_only_ffprobe_type_error(patch_path_methods):
    """ffprobe結果パース時に TypeError が発生した場合に、安全に unknown にフォールバックすることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        if cmd[0] == "ffprobe" and "soul_narrative_TELOP_UNIFIED.mp4" in cmd[-1]:
            res.stdout = MagicMock()
            # strip() はリストを返し、float() 呼び出し時に TypeError を誘発する
            res.stdout.strip.return_value = []
        else:
            res.stdout = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run):
         
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is not None
        assert "soul_narrative_TELOP_UNIFIED.mp4" in video_path



def test_add_telop_to_scene04_only_ffprobe_key_error(patch_path_methods):
    """ffprobe結果パース時に KeyError が発生した場合に、安全に unknown にフォールバックすることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        if cmd[0] == "ffprobe" and "soul_narrative_TELOP_UNIFIED.mp4" in cmd[-1]:
            res.stdout = MagicMock()
            res.stdout.strip.side_effect = KeyError("Mock KeyError during strip")
        else:
            res.stdout = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run):
         
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is not None
        assert "soul_narrative_TELOP_UNIFIED.mp4" in video_path


def test_add_telop_to_scene04_only_ffprobe_runtime_error(patch_path_methods):
    """ffprobe結果パース時に RuntimeError が発生した場合に、安全に unknown にフォールバックすることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        if cmd[0] == "ffprobe" and "soul_narrative_TELOP_UNIFIED.mp4" in cmd[-1]:
            res.stdout = MagicMock()
            res.stdout.strip.side_effect = RuntimeError("Mock RuntimeError during strip")
        else:
            res.stdout = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run):
         
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is not None
        assert "soul_narrative_TELOP_UNIFIED.mp4" in video_path


def test_add_telop_to_scene04_only_unlink_value_error(patch_path_methods):
    """一時ファイル削除時に Path の ValueError が発生した場合も、例外が伝播せずに動画パスを返すことを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        if cmd[0] == "ffprobe":
            res.stdout = "2256.0\n"
        else:
            res.stdout = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run), \
         patch("pathlib.Path.unlink", side_effect=ValueError("invalid path value")):
         
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is not None
        assert "soul_narrative_TELOP_UNIFIED.mp4" in video_path


def test_add_telop_to_scene04_only_ffprobe_duration_non_float_fallback(patch_path_methods):
    """ffprobe が返す duration が float に変換できない文字列（例: "N/A"）の場合に、安全に unknown にフォールバックすることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        res.returncode = 0
        res.stderr = ""
        if cmd[0] == "ffprobe" and "soul_narrative_TELOP_UNIFIED.mp4" in cmd[-1]:
            res.stdout = "N/A\n"
        else:
            res.stdout = ""
        return res

    with patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run):
         
        video_path = target_module.add_telop_to_scene04_only()
        assert video_path is not None
        assert "soul_narrative_TELOP_UNIFIED.mp4" in video_path


def test_add_telop_to_scene04_only_raises_error_on_ffprobe_invalid_input_corruption(patch_path_methods):
    """入力動画の破損チェックで ffprobe がエラーコードを返し、かつ raise_on_error=True の場合に VideoProcessingError を投げることを検証"""
    mock_font = MagicMock(spec=ImageFont.FreeTypeFont)
    mock_font.getbbox.return_value = (0, 0, 300, 40)
    mock_font.getmask2.return_value = (Image.new("L", (1, 1)).im, (0, 0))
    
    def mock_run(cmd, *args, **kwargs):
        res = MagicMock(spec=subprocess.CompletedProcess)
        if cmd[0] == "ffprobe" and "soul_narrative_FINAL_EDITED.mp4" in cmd[-1]:
            res.returncode = 1
            res.stderr = "Corrupted video frame"
        else:
            res.returncode = 0
            res.stdout = ""
            res.stderr = ""
        return res

    with patch("pathlib.Path.is_file", return_value=True), \
         patch("PIL.ImageFont.truetype", return_value=mock_font), \
         patch("PIL.Image.Image.save"), \
         patch("subprocess.run", side_effect=mock_run):
         
        with pytest.raises(target_module.VideoProcessingError) as exc_info:
            target_module.add_telop_to_scene04_only(raise_on_error=True)
        assert "Input video file is corrupted or invalid" in str(exc_info.value)











