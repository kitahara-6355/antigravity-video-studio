import sys
import os
import pathlib
import pytest
from unittest.mock import MagicMock, patch

# オリジナルのPath.mkdirを退避
original_mkdir = pathlib.Path.mkdir

def mock_mkdir(self, *args, **kwargs):
    # final_build や video-automation がパスに含まれている場合は何もしない（エラーを防ぐ）
    if "final_build" in str(self) or "video-automation" in str(self):
        return
    return original_mkdir(self, *args, **kwargs)

@pytest.fixture(autouse=True)
def patch_mkdir():
    with patch.object(pathlib.Path, "mkdir", mock_mkdir):
        yield

def test_gen_telops_coverage():
    # 各種モックを定義
    mock_font = MagicMock()
    
    mock_logo = MagicMock()
    mock_logo.mode = "RGBA"
    mock_logo.resize.return_value = mock_logo
    
    mock_img = MagicMock()
    mock_img.mode = "RGBA"
    
    old_gen_telops = sys.modules.get("gen_telops")
    
    try:
        # パッチを当てる対象：
        # 1. PIL.ImageFont.truetype (フォントファイル非依存化)
        # 2. PIL.Image.new (新規画像作成)
        # 3. PIL.Image.open (ロゴ画像読み込み)
        # 4. ImageDraw.Draw (描画オブジェクト)
        # 5. print
        with patch("PIL.ImageFont.truetype", return_value=mock_font),          patch("PIL.Image.new", return_value=mock_img),          patch("PIL.Image.open", return_value=mock_logo),          patch("PIL.ImageDraw.Draw") as mock_draw_cls,          patch("builtins.print") as mock_print:
             
            mock_draw = MagicMock()
            mock_draw_cls.return_value = mock_draw
            
            # モジュールがすでにインポートされている場合はキャッシュから削除
            if "gen_telops" in sys.modules:
                del sys.modules["gen_telops"]
                
            # 1. 通常のモジュールインポートと関数実行のテスト
            import gen_telops
            gen_telops.generate_telops()
            
            # 2. __main__ ブロック実行のテスト (runpyを使用)
            import runpy
            script_path = os.path.abspath(gen_telops.__file__)
            
            # 再度キャッシュから削除して、runpyでの再ロード実行時に全行が走るようにする
            if "gen_telops" in sys.modules:
                del sys.modules["gen_telops"]
                
            runpy.run_path(script_path, run_name="__main__")
            
            # アサーション: 成功メッセージが2回（手動呼び出しと__main__実行）出力されていること
            assert mock_print.call_count >= 2
            mock_print.assert_any_call("✅ テロップ生成完了")
    finally:
        if old_gen_telops is not None:
            sys.modules["gen_telops"] = old_gen_telops
        else:
            sys.modules.pop("gen_telops", None)
