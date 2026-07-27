import os
import pytest
import runpy
import subprocess
from pathlib import Path
from unittest import mock
from PIL import Image, ImageFont

# テスト前に環境変数をセットして一時的なディレクトリを使用するようにする
@pytest.fixture(autouse=True)
def setup_env(tmp_path):
    os.environ["ANTIGRAVITY_BASE_DIR"] = str(tmp_path)
    
    # 必要なディレクトリ構造を作成
    logo_dir = tmp_path / "backend" / "branding" / "logos"
    logo_dir.mkdir(parents=True, exist_ok=True)
    
    # ダミーのロゴ画像を作成
    logo_img = Image.new("RGBA", (23, 45), (255, 0, 0, 255))
    logo_img.save(logo_dir / "brand_logo.png")
    
    # ダミーの入力動画ファイルを作成
    input_video = tmp_path / "soul_narrative_FINAL_EDITED.mp4"
    input_video.touch()
    
    # モジュールをロードして BASE_DIR を明示的に設定
    import backend.add_premium_branding as apb
    import importlib
    importlib.reload(apb)
    apb.BASE_DIR = tmp_path
    
    yield tmp_path

# フォント読み込みモック用のヘルパー
# Windowsの Fonts ディレクトリには msgothic.ttc や Arial が必ずあるため、
# 例外シミュレーション以外は msgothic.ttc を代わりに読み込ませて getmask2 エラーを防ぐ。
original_truetype = ImageFont.truetype

def make_mock_truetype(fail_yugothb=False, fail_meiryo=False, fail_msgothic=False):
    def mock_truetype(font_path, size):
        # パスに基づいて失敗させる
        if "YuGothB" in font_path and fail_yugothb:
            raise OSError("Mock YuGothB failure")
        if "meiryo" in font_path and fail_meiryo:
            raise OSError("Mock Meiryo failure")
        if "msgothic" in font_path and fail_msgothic:
            raise OSError("Mock MS Gothic failure")
        
        # 実際には存在するフォントを読み込む
        # Windowsの msgothic.ttc を使う
        try:
            return original_truetype(r"C:\Windows\Fonts\msgothic.ttc", size)
        except OSError:
            # 万が一 Windows 以外の環境（CI等）で msgothic.ttc が無い場合
            return ImageFont.load_default()
    return mock_truetype

def test_create_premium_branding_font_fallback(setup_env):
    import backend.add_premium_branding as apb
    
    # 1. 正常系 (すべてデフォルト)
    with mock.patch("PIL.ImageFont.truetype", side_effect=make_mock_truetype()):
        res = apb.create_premium_branding()
        assert res.exists()
        
    # 2. 1回目失敗 (Yu Gothic Bold 失敗 -> Meiryo 成功)
    with mock.patch("PIL.ImageFont.truetype", side_effect=make_mock_truetype(fail_yugothb=True)):
        res = apb.create_premium_branding()
        assert res.exists()

    # 3. 1, 2回目失敗 (Yu Gothic Bold, Meiryo 失敗 -> MS Gothic 成功)
    with mock.patch("PIL.ImageFont.truetype", side_effect=make_mock_truetype(fail_yugothb=True, fail_meiryo=True)):
        res = apb.create_premium_branding()
        assert res.exists()

    # 4. 全て失敗 (すべてのフォントで例外)
    with mock.patch("PIL.ImageFont.truetype", side_effect=make_mock_truetype(fail_yugothb=True, fail_meiryo=True, fail_msgothic=True)):
        with pytest.raises(Exception):
            apb.create_premium_branding()

def test_add_premium_branding_success(setup_env):
    import backend.add_premium_branding as apb
    
    output_video = setup_env / "soul_narrative_YOUTUBE_PREMIUM.mp4"
    
    def mock_run(cmd, *args, **kwargs):
        if "ffmpeg" in cmd[0]:
            # 出力ビデオファイルを作成して成功を模倣
            output_video.touch()
            return mock.Mock(returncode=0, stdout="", stderr="")
        elif "ffprobe" in cmd[0]:
            return mock.Mock(returncode=0, stdout="125.5\n", stderr="")
        return mock.Mock(returncode=0)
        
    with mock.patch("subprocess.run", side_effect=mock_run):
        with mock.patch("PIL.ImageFont.truetype", side_effect=make_mock_truetype()):
            res = apb.add_premium_branding()
            assert res == str(output_video)

def test_add_premium_branding_failure(setup_env):
    import backend.add_premium_branding as apb
    
    def mock_run(cmd, *args, **kwargs):
        if "ffmpeg" in cmd[0]:
            return mock.Mock(returncode=1, stdout="", stderr="ffmpeg simulation error")
        return mock.Mock(returncode=0)
        
    with mock.patch("subprocess.run", side_effect=mock_run):
        with mock.patch("PIL.ImageFont.truetype", side_effect=make_mock_truetype()):
            res = apb.add_premium_branding()
            assert res is None

def test_main_success(setup_env):
    import backend.add_premium_branding as apb
    output_video = setup_env / "soul_narrative_YOUTUBE_PREMIUM.mp4"
    
    def mock_run(cmd, *args, **kwargs):
        if "ffmpeg" in cmd[0]:
            output_video.touch()
            return mock.Mock(returncode=0, stdout="", stderr="")
        elif "ffprobe" in cmd[0]:
            return mock.Mock(returncode=0, stdout="65.0\n", stderr="")
        return mock.Mock(returncode=0)
        
    script_path = str(Path(apb.__file__))
    
    with mock.patch("subprocess.run", side_effect=mock_run):
        with mock.patch("PIL.ImageFont.truetype", side_effect=make_mock_truetype()):
            # スクリプトを __main__ として実行
            runpy.run_path(script_path, run_name="__main__")

def test_main_failure(setup_env):
    import backend.add_premium_branding as apb
    
    def mock_run(cmd, *args, **kwargs):
        if "ffmpeg" in cmd[0]:
            return mock.Mock(returncode=1, stdout="", stderr="ffmpeg execution error")
        return mock.Mock(returncode=0)
        
    script_path = str(Path(apb.__file__))
    
    with mock.patch("subprocess.run", side_effect=mock_run):
        with mock.patch("PIL.ImageFont.truetype", side_effect=make_mock_truetype()):
            # スクリプトを __main__ として実行し、失敗ルートを通す
            runpy.run_path(script_path, run_name="__main__")
